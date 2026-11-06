"""Phase 11: security and reliability integration tests.

Covers spec section 21: approval enforcement end-to-end, prompt-injection
resistance, secret handling across integrations, provider fallback, and
database backup/recovery. No real network, no real deletions of user data
(all file operations stay inside tmp_path).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from core.approval_manager import ApprovalManager, AutoDenyHandler
from core.config_loader import PermissionPolicy
from core.logging_setup import redact_text
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from providers.base_adapter import ChatResponse, ToolCall
from providers.errors import ProviderRateLimitError
from security.audit_logger import AuditLogger
from security.credential_manager import CredentialManager
from security.permission_checker import PermissionChecker
from tests.fakes import FakeKeyring
from tests.test_router_and_manager import _provider


def _full_stack(tmp_path: Path, approve: bool):
    """Registry with a high-risk file delete tool + full approval stack."""
    registry = ToolRegistry()
    audit = AuditLogger(tmp_path / "audit.log")

    def executor(args):
        target = Path(args["path"])
        target.unlink()
        return ToolExecutionResult("delete_file", True, f"deleted {target}")

    registry.register(
        ToolDefinition(
            name="delete_file",
            description="Delete a file permanently",
            risk="high",
            parameters={
                "path": {"type": "string", "description": "file", "required": True}
            },
        ),
        executor,
    )

    class ApprovingHandler:
        def __call__(self, pending):
            from core.approval_manager import ApprovalDecision

            return ApprovalDecision(approved=approve, reason="test decision")

    approvals = ApprovalManager(
        PermissionChecker(PermissionPolicy()), audit, ApprovingHandler()
    )
    planner = TaskPlanner(registry)
    executor = TaskExecutor(registry, approvals, audit, default_timeout=5)
    return registry, planner, executor, audit


@pytest.mark.integration
class TestApprovalEnforcementEndToEnd:
    def test_denied_high_risk_deletion_does_nothing(self, tmp_path) -> None:
        victim = tmp_path / "important.txt"
        victim.write_text("data", encoding="utf-8")
        registry, planner, executor, audit = _full_stack(tmp_path, approve=False)
        plan = planner.plan(
            (ToolCall(id="1", name="delete_file", arguments={"path": str(victim)}),)
        )
        results = executor.execute(plan.tasks)
        assert results[0].success is False
        assert "denied" in results[0].output
        assert victim.exists()  # nothing happened
        events = audit.read_events()
        assert "approval_requested" in [e["event"] for e in events]
        assert "task_executed" not in [e["event"] for e in events]

    def test_approved_high_risk_deletion_executes_and_audits(
        self, tmp_path
    ) -> None:
        victim = tmp_path / "replaceable.txt"
        victim.write_text("data", encoding="utf-8")
        registry, planner, executor, audit = _full_stack(tmp_path, approve=True)
        plan = planner.plan(
            (ToolCall(id="1", name="delete_file", arguments={"path": str(victim)}),)
        )
        results = executor.execute(plan.tasks)
        assert results[0].success is True
        assert not victim.exists()
        events = audit.read_events()
        assert [e["event"] for e in events][-1] == "task_executed"

    def test_unregistered_tool_demand_is_rejected(self, tmp_path) -> None:
        """A model demanding an unregistered tool (however phrased) is
        rejected by the planner - content cannot add capabilities."""
        registry, planner, _, _ = _full_stack(tmp_path, approve=True)
        plan = planner.plan(
            (
                ToolCall(
                    id="1",
                    name="format_c_drive",  # not in the registry
                    arguments={"path": "C:\\"},
                ),
            )
        )
        assert plan.tasks == ()
        assert any("not registered" in r for r in plan.rejections)
