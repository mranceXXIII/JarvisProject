"""Tests for Phase 4: permissions, registry, approvals, planner, executor."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.approval_manager import (
    ApprovalDecision,
    ApprovalManager,
    AutoDenyHandler,
    PendingApproval,
)
from core.config_loader import PermissionPolicy
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_registry import (
    ToolDefinition,
    ToolExecutionResult,
    ToolRegistry,
)
from security.audit_logger import AuditLogger
from security.permission_checker import PermissionChecker


def _low_tool(name: str = "tool_a", **overrides) -> ToolDefinition:
    data = {
        "name": name,
        "description": "test tool",
        "risk": "low",
        "parameters": {
            "target": {"type": "string", "description": "target", "required": True},
            "extra": {"type": "string", "description": "optional"},
        },
    }
    data.update(overrides)
    return ToolDefinition(**data)


def _audit(tmp_path: Path) -> AuditLogger:
    return AuditLogger(tmp_path / "audit.log")


@pytest.mark.unit
class TestPermissionChecker:
    def test_low_risk_allowed_without_approval(self) -> None:
        checker = PermissionChecker(PermissionPolicy())
        assert checker.check("t", "low").approval_required is False

    def test_medium_requires_approval_by_default(self) -> None:
        checker = PermissionChecker(PermissionPolicy())
        assert checker.check("t", "medium").approval_required is True

    def test_high_requires_approval_by_default(self) -> None:
        checker = PermissionChecker(PermissionPolicy())
        assert checker.check("t", "high").approval_required is True

    def test_medium_can_be_configured_not_to_require(self) -> None:
        policy = PermissionPolicy(require_approval_medium=False)
        assert PermissionChecker(policy).check("t", "medium").approval_required is False

    def test_trusted_tool_bypasses(self) -> None:
        policy = PermissionPolicy(trusted_tools=["risky_tool"])
        decision = PermissionChecker(policy).check("risky_tool", "high")
        assert decision.approval_required is False

    def test_unknown_risk_is_conservative(self) -> None:
        checker = PermissionChecker(PermissionPolicy())
        assert checker.check("t", "extreme").approval_required is True


@pytest.mark.unit
class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _low_tool(), lambda args: ToolExecutionResult("tool_a", True, "ok")
        )
        assert registry.has("tool_a")
        assert registry.get("tool_a").risk == "low"

    def test_duplicate_registration_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_low_tool(), lambda args: None)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_low_tool(), lambda args: None)

    def test_invalid_risk_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid risk"):
            ToolRegistry().register(_low_tool(risk="extreme"), lambda args: None)

    def test_validate_arguments(self) -> None:
        registry = ToolRegistry()
        registry.register(_low_tool(), lambda args: None)
        assert registry.validate_arguments("tool_a", {"target": "x"}) == []
        assert "missing required" in registry.validate_arguments("tool_a", {})[0]
        assert "unknown argument" in registry.validate_arguments(
            "tool_a", {"target": "x", "junk": 1}
        )[0]

    def test_execute_rejects_bad_arguments(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _low_tool(), lambda args: ToolExecutionResult("tool_a", True, "ran")
        )
        assert registry.execute("tool_a", {}).success is False

    def test_executor_exception_caught(self) -> None:
        def boom(_args):
            raise RuntimeError("exploded")

        registry = ToolRegistry()
        registry.register(_low_tool(), boom)
        assert registry.execute("tool_a", {"target": "x"}).success is False

    def test_to_tool_specs_marks_required(self) -> None:
        registry = ToolRegistry()
        registry.register(_low_tool(), lambda args: None)
        spec = registry.to_tool_specs()[0]
        assert spec.name == "tool_a"
        assert spec.parameters["required"] == ["target"]


@pytest.mark.unit
class TestApprovalManager:
    def test_low_risk_auto_allowed_and_audited(self, tmp_path: Path) -> None:
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        decision = manager.request(_low_tool(), {"target": "x"})
        assert decision.approved is True
        assert audit.read_events()[0]["event"] == "tool_auto_allowed"

    def test_medium_risk_uses_handler(self, tmp_path: Path) -> None:
        audit = _audit(tmp_path)
        decisions = iter([ApprovalDecision(approved=True, reason="ok")])
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()),
            audit,
            lambda pending: next(decisions),
        )
        tool = _low_tool("medium_tool", risk="medium")
        assert manager.request(tool, {"target": "x"}).approved is True
        events = audit.read_events()
        assert [e["event"] for e in events] == [
            "approval_requested",
            "approval_decided",
        ]

    def test_denial_recorded(self, tmp_path: Path) -> None:
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        tool = _low_tool("high_tool", risk="high")
        decision = manager.request(tool, {"target": "x"})
        assert decision.approved is False
        assert audit.read_events()[-1]["event"] == "approval_decided"

    def test_handler_crash_denies(self, tmp_path: Path) -> None:
        audit = _audit(tmp_path)

        def broken(_pending):
            raise RuntimeError("boom")

        manager = ApprovalManager(PermissionChecker(PermissionPolicy()), audit, broken)
        decision = manager.request(_low_tool("m", risk="medium"), {"target": "x"})
        assert decision.approved is False

    def test_pending_summary_contains_required_elements(self) -> None:
        pending = PendingApproval(
            tool="open_application",
            description="Open an app",
            risk="low",
            arguments={"app": "notepad"},
            reason="policy",
        )
        text = pending.summary()
        assert "Action:" in text and "Arguments:" in text
        assert "notepad" in text


@pytest.mark.unit
class TestAuditLogger:
    def test_events_written_and_redacted(self, tmp_path: Path) -> None:
        audit = _audit(tmp_path)
        audit.log(
            "task_executed", tool="open_application", arguments={"app": "notepad"}
        )
        secret = "sk-abcdef1234567890abcdef"
        audit.log("tool_call", detail=f"key was {secret}")
        events = audit.read_events()
        assert events[0]["tool"] == "open_application"
        assert secret not in events[1]["detail"]
        assert "REDACTED" in events[1]["detail"]

    def test_empty_file_reads_empty(self, tmp_path: Path) -> None:
        assert AuditLogger(tmp_path / "none.log").read_events() == []


class RecordingStub:
    """Provider stub returning scripted results in sequence."""

    def __init__(self, sequence: list) -> None:
        self._sequence = list(sequence)
        self.calls: list[list[dict]] = []

    def is_local(self, provider):
        return provider.type in ("ollama", "lm_studio")

    def capabilities_of(self, provider):
        from providers.provider_manager import _ADAPTER_CLASSES

        cls = _ADAPTER_CLASSES[provider.type]
        return cls.__new__(cls).capabilities

    def chat(self, provider, request):
        self.calls.append(list(request.messages))
        outcome = self._sequence.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _single_provider_setup(stub):
    from core.ai_router import AIRouter
    from core.config_loader import RouteEntry, RoutingConfig
    from tests.test_router_and_manager import _provider

    providers = [_provider("primary", "openai")]
    routing = RoutingConfig(
        default=RouteEntry(provider="primary"), fallback_chain=["primary"]
    )
    router = AIRouter(
        routing,
        {p.name: p for p in providers},
        {p.name: stub.is_local(p) for p in providers},
        stub.capabilities_of,
    )
    return router


@pytest.mark.unit
class TestPlannerExecutor:
    def test_plan_validates_and_rejects(self) -> None:
        from providers.base_adapter import ToolCall

        registry = ToolRegistry()
        registry.register(_low_tool(), lambda args: None)
        planner = TaskPlanner(registry)
        good = planner.plan(
            (ToolCall(id="1", name="tool_a", arguments={"target": "x"}),)
        )
        assert len(good.tasks) == 1 and good.rejections == ()
        bad = planner.plan(
            (
                ToolCall(id="2", name="ghost_tool", arguments={}),
                ToolCall(id="3", name="tool_a", arguments={}),
            )
        )
        assert bad.tasks == () and len(bad.rejections) == 2

    def test_executor_runs_approved_task(self, tmp_path: Path) -> None:
        from providers.base_adapter import ToolCall

        calls: list = []

        def executor(args):
            calls.append(args)
            return ToolExecutionResult("tool_a", True, "ran")

        registry = ToolRegistry()
        registry.register(_low_tool(), executor)
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        executor2 = TaskExecutor(registry, manager, audit, default_timeout=5)
        plan = TaskPlanner(registry).plan(
            (ToolCall(id="1", name="tool_a", arguments={"target": "notepad"}),)
        )
        results = executor2.execute(plan.tasks)
        assert results[0].success is True
        assert calls == [{"target": "notepad"}]
        assert audit.read_events()[-1]["event"] == "task_executed"

    def test_executor_denied_task_not_executed(self, tmp_path: Path) -> None:
        from providers.base_adapter import ToolCall

        registry = ToolRegistry()
        executed: list = []

        def record_and_run(args):
            executed.append(args)
            return ToolExecutionResult("medium_tool", True, "x")

        registry.register(_low_tool("medium_tool", risk="medium"), record_and_run)
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        executor = TaskExecutor(registry, manager, audit, default_timeout=5)
        plan = TaskPlanner(registry).plan(
            (ToolCall(id="1", name="medium_tool", arguments={"target": "x"}),)
        )
        results = executor.execute(plan.tasks)
        assert results[0].success is False
        assert "denied" in results[0].output
        assert executed == []

    def test_executor_cancellation(self, tmp_path: Path) -> None:
        from providers.base_adapter import ToolCall

        registry = ToolRegistry()
        registry.register(
            _low_tool(), lambda args: ToolExecutionResult("tool_a", True, "ran")
        )
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        executor = TaskExecutor(registry, manager, audit, default_timeout=5)
        plan = TaskPlanner(registry).plan(
            (ToolCall(id="1", name="tool_a", arguments={"target": "x"}),)
        )
        cancel = threading.Event()
        cancel.set()
        results = executor.execute(plan.tasks, cancel_event=cancel)
        assert results[0].output == "cancelled before execution"

    def test_executor_timeout_reported(self, tmp_path: Path) -> None:
        from providers.base_adapter import ToolCall

        def slow(_args):
            time.sleep(1.5)
            return ToolExecutionResult("tool_a", True, "late")

        registry = ToolRegistry()
        registry.register(_low_tool(), slow)
        audit = _audit(tmp_path)
        manager = ApprovalManager(
            PermissionChecker(PermissionPolicy()), audit, AutoDenyHandler()
        )
        executor = TaskExecutor(registry, manager, audit, default_timeout=0.2)
        plan = TaskPlanner(registry).plan(
            (ToolCall(id="1", name="tool_a", arguments={"target": "x"}),)
        )
        results = executor.execute(plan.tasks)
        assert results[0].success is False
        assert "timed out" in results[0].output


@pytest.mark.unit
class TestAssistantToolRound:
    def _make_assistant(self, stub, trusted: bool):
        from core.assistant import JarvisAssistant

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="get_time",
                description="Get the current time",
                risk="low" if trusted else "medium",
                parameters={},
            ),
            lambda args: ToolExecutionResult("get_time", True, "10:00"),
        )
        audit = AuditLogger(Path.cwd() / "pytest_audit_assistant.log")
        policy = PermissionPolicy(trusted_tools=["get_time"] if trusted else [])
        manager = ApprovalManager(PermissionChecker(policy), audit, AutoDenyHandler())
        assistant = JarvisAssistant(
            stub,
            _single_provider_setup(stub),
            TaskPlanner(registry),
            TaskExecutor(registry, manager, audit, default_timeout=5),
        )
        return assistant, registry

    def test_tool_round_executes_and_feeds_back(self) -> None:
        from providers.base_adapter import ChatResponse, ToolCall

        stub = RecordingStub(
            [
                ChatResponse(
                    provider_name="primary",
                    model="m",
                    content="",
                    tool_calls=(ToolCall(id="c1", name="get_time", arguments={}),),
                ),
                ChatResponse(
                    provider_name="primary", model="m", content="It is 10:00."
                ),
            ]
        )
        assistant, registry = self._make_assistant(stub, trusted=True)
        reply = assistant.handle_text(
            "what time is it?", tools=registry.to_tool_specs()
        )
        assert reply.success is True
        assert reply.text == "It is 10:00."
        assert reply.tool_results[0].output == "10:00"
        assert any("10:00" in m["content"] for m in stub.calls[1])

    def test_denied_tools_reported_honestly(self) -> None:
        from providers.base_adapter import ChatResponse, ToolCall

        stub = RecordingStub(
            [
                ChatResponse(
                    provider_name="primary",
                    model="m",
                    content="",
                    tool_calls=(ToolCall(id="c1", name="get_time", arguments={}),),
                ),
                ChatResponse(
                    provider_name="primary", model="m", content="Cannot get time."
                ),
            ]
        )
        assistant, registry = self._make_assistant(stub, trusted=False)
        reply = assistant.handle_text(
            "what time is it?", tools=registry.to_tool_specs()
        )
        assert reply.success is True
        assert reply.tool_results[0].success is False
        assert "denied" in reply.tool_results[0].output
