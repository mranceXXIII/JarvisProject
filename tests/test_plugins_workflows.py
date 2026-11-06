"""Tests for Phase 10: plugin lifecycle and workflow manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from core.workflow_manager import WorkflowError, WorkflowManager
from plugins.plugin_manager import PluginError, PluginManager
from providers.base_adapter import ToolCall
from security.audit_logger import AuditLogger


@pytest.fixture
def plugin_env(tmp_path: Path):
    registry = ToolRegistry()
    audit = AuditLogger(tmp_path / "audit.log")
    decisions: list[bool] = []

    def approver(_tool, _description) -> bool:
        return decisions.pop(0) if decisions else False

    manager = PluginManager(tmp_path / "plugins", registry, audit, approver)
    return manager, registry, audit, decisions


def _write_plugin(directory: Path, source: str, permissions: list[str] | None = None):
    import json

    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": directory.name,
        "version": "1.0.0",
        "description": "test plugin",
        "permissions": permissions or [],
        "entry": "plugin.py",
        "enabled": True,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (directory / "plugin.py").write_text(source, encoding="utf-8")


SAFE_PLUGIN = '''
"""Safe test plugin."""

from core.tool_registry import ToolDefinition, ToolExecutionResult


def register(registry) -> None:
    def greet(arguments):
        return ToolExecutionResult("safe_plugin_greet", True, "hi!")

    registry.register(
        ToolDefinition(
            name="safe_plugin_greet",
            description="Greets politely",
            risk="low",
            parameters={},
        ),
        greet,
    )
'''

DANGEROUS_PLUGIN = '''
"""Plugin that shells out without declaring it."""

import subprocess


def register(registry) -> None:
    pass
'''


@pytest.mark.unit
class TestStaticAnalysis:
    def test_safe_source_needs_no_permissions(self) -> None:
        from plugins.plugin_manager import analyze_source

        assert analyze_source(SAFE_PLUGIN) == set()

    def test_subprocess_detected(self) -> None:
        from plugins.plugin_manager import analyze_source

        assert "process" in analyze_source(DANGEROUS_PLUGIN)

    def test_network_detected(self) -> None:
        from plugins.plugin_manager import analyze_source

        assert "network" in analyze_source("import socket\n")

    def test_eval_detected(self) -> None:
        from plugins.plugin_manager import analyze_source

        assert "code_execution" in analyze_source("x = eval('1+1')\n")

    def test_syntax_error_raises(self) -> None:
        from plugins.plugin_manager import analyze_source

        with pytest.raises(PluginError, match="syntax error"):
            analyze_source("def broken(:")


@pytest.mark.unit
class TestPluginLifecycle:
    def test_stage_and_validate_generated_plugin(self, plugin_env) -> None:
        manager, _, _, _ = plugin_env
        manager.stage_new_plugin("greeter", "Greets people")
        assert manager.validate_staged("greeter") == []

    def test_stage_duplicate_rejected(self, plugin_env) -> None:
        manager, _, _, _ = plugin_env
        manager.stage_new_plugin("greeter", "d")
        with pytest.raises(PluginError, match="already exists"):
            manager.stage_new_plugin("greeter", "d")

    def test_validation_fails_on_undeclared_capabilities(
        self, plugin_env, tmp_path
    ) -> None:
        manager, _, _, _ = plugin_env
        manager.stage_new_plugin("shelly", "shells out")
        staged = tmp_path / "plugins" / "staging" / "shelly"
        _write_plugin(staged, DANGEROUS_PLUGIN)  # no permissions declared
        problems = manager.validate_staged("shelly")
        assert any("undeclared capabilities" in p for p in problems)
        assert any("process" in p for p in problems)

    def test_validation_passes_with_declared_permissions(
        self, plugin_env, tmp_path
    ) -> None:
        manager, _, _, _ = plugin_env
        manager.stage_new_plugin("shelly", "shells out")
        staged = tmp_path / "plugins" / "staging" / "shelly"
        _write_plugin(staged, DANGEROUS_PLUGIN, permissions=["process"])
        assert manager.validate_staged("shelly") == []

    def test_install_requires_approval(self, plugin_env) -> None:
        manager, registry, audit, decisions = plugin_env
        manager.stage_new_plugin("greeter", "Greets")
        decisions.append(False)
        result = manager.install_staged("greeter")
        assert "denied" in result
        assert registry.list_tools() == ()
        assert audit.read_events()[-1]["event"] == "plugin_install_denied"

    def test_install_approved_registers_tools(self, plugin_env) -> None:
        manager, registry, audit, decisions = plugin_env
        manager.stage_new_plugin("greeter", "Greets")
        decisions.append(True)
        result = manager.install_staged("greeter")
        assert "installed and registered" in result
        tool_names = {t.name for t in registry.list_tools()}
        assert any(n.endswith("_hello") for n in tool_names)
        assert audit.read_events()[-1]["event"] == "plugin_loaded"

    def test_install_fails_if_not_staged(self, plugin_env) -> None:
        manager, _, _, _ = plugin_env
        with pytest.raises(PluginError, match="no manifest.json"):
            manager.install_staged("ghost")

    def test_disable_persists_and_skips_load(self, plugin_env, tmp_path) -> None:
        manager, registry, audit, decisions = plugin_env
        manager.stage_new_plugin("greeter", "Greets")
        decisions.append(True)
        manager.install_staged("greeter")
        result = manager.set_enabled("greeter", False)
        assert "disabled" in result
        manifest_path = (
            tmp_path / "plugins" / "custom" / "greeter" / "manifest.json"
        )
        assert '"enabled": false' in manifest_path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestWorkflowManager:
    def _manager(self, tmp_path: Path, auto_approve: bool = True):
        registry = ToolRegistry()
        executed: list[tuple[str, dict]] = []

        def greet(args):
            executed.append(("greet_tool", args))
            return ToolExecutionResult("greet_tool", True, f"hi {args.get('who')}")

        registry.register(
            ToolDefinition(
                name="greet_tool",
                description="greets",
                risk="low",
                parameters={
                    "who": {
                        "type": "string",
                        "description": "who",
                        "required": True,
                    }
                },
            ),
            greet,
        )
        audit = AuditLogger(tmp_path / "audit.log")
        planner = TaskPlanner(registry)
        from core.approval_manager import ApprovalManager, AutoDenyHandler
        from core.config_loader import PermissionPolicy
        from security.permission_checker import PermissionChecker

        policy = (
            PermissionPolicy(trusted_tools=["greet_tool"])
            if auto_approve
            else PermissionPolicy()
        )
        approvals = ApprovalManager(
            PermissionChecker(policy), audit, AutoDenyHandler()
        )
        executor = TaskExecutor(registry, approvals, audit, default_timeout=5)
        manager = WorkflowManager(
            tmp_path / "workflows.yaml", planner, executor, audit
        )
        return manager, registry, executed, audit

    def test_create_validates_steps(self, tmp_path) -> None:
        manager, _, _, _ = self._manager(tmp_path)
        result = manager.create(
            "hello",
            "Greets",
            [{"tool": "greet_tool", "arguments": {"who": "x"}}],
        )
        assert "created with 1 step" in result

    def test_create_rejects_unknown_tool(self, tmp_path) -> None:
        manager, _, _, _ = self._manager(tmp_path)
        with pytest.raises(WorkflowError, match="ghost_tool"):
            manager.create("bad", "", [{"tool": "ghost_tool", "arguments": {}}])

    def test_duplicate_rejected(self, tmp_path) -> None:
        manager, _, _, _ = self._manager(tmp_path)
        manager.create(
            "dup", "", [{"tool": "greet_tool", "arguments": {"who": "x"}}]
        )
        with pytest.raises(WorkflowError, match="already exists"):
            manager.create(
                "dup", "", [{"tool": "greet_tool", "arguments": {"who": "x"}}]
            )

    def test_run_executes_steps_with_approval(self, tmp_path) -> None:
        manager, _, executed, audit = self._manager(tmp_path)
        manager.create(
            "hello", "", [{"tool": "greet_tool", "arguments": {"who": "bob"}}]
        )
        result = manager.run("hello")
        assert "1/1 steps succeeded" in result
        assert executed == [("greet_tool", {"who": "bob"})]
        assert audit.read_events()[-1]["event"] == "workflow_run"

    def test_run_respects_denials(self, tmp_path) -> None:
        manager, _, executed, _ = self._manager(tmp_path, auto_approve=False)
        # medium-risk step: approval required, AutoDenyHandler denies it
        registry_tool = ToolDefinition(
            name="mail_tool",
            description="sends mail",
            risk="medium",
            parameters={
                "who": {
                    "type": "string",
                    "description": "who",
                    "required": True,
                }
            },
        )
        registry = ToolRegistry()
        registry.register(
            registry_tool,
            lambda args: (
                executed.append(("mail_tool", args)),
                ToolExecutionResult("mail_tool", True, "sent"),
            )[1],
        )
        audit = AuditLogger(tmp_path / "audit2.log")
        from core.approval_manager import ApprovalManager, AutoDenyHandler
        from core.config_loader import PermissionPolicy
        from security.permission_checker import PermissionChecker

        approvals = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        planner = TaskPlanner(registry)
        executor = TaskExecutor(registry, approvals, audit, default_timeout=5)
        manager2 = WorkflowManager(
            tmp_path / "workflows2.yaml", planner, executor, audit
        )
        manager2.create(
            "notify", "", [{"tool": "mail_tool", "arguments": {"who": "bob"}}]
        )
        result = manager2.run("notify")
        assert "0/1 steps succeeded" in result
        assert executed == []  # denied step never ran

    def test_persisted_across_reopen(self, tmp_path) -> None:
        manager, _, _, _ = self._manager(tmp_path)
        manager.create(
            "hello", "", [{"tool": "greet_tool", "arguments": {"who": "x"}}]
        )
        reopened, _, _, _ = self._manager(tmp_path)
        assert reopened.get("hello").name == "hello"

    def test_pause_and_delete(self, tmp_path) -> None:
        manager, _, _, _ = self._manager(tmp_path)
        manager.create(
            "hello", "", [{"tool": "greet_tool", "arguments": {"who": "x"}}]
        )
        assert "paused" in manager.set_paused("hello", True)
        assert "paused" in manager.run("hello")
        manager.set_paused("hello", False)
        assert "deleted" in manager.delete("hello")
        with pytest.raises(WorkflowError, match="unknown workflow"):
            manager.run("hello")
