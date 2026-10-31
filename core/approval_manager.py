"""Approval management: the approval-first gate before tool execution.

Every tool execution passes through :meth:`ApprovalManager.request`. The
permission checker decides whether approval is needed; a handler (UI dialog,
console prompt, or auto-deny) collects the user's decision; every proposal
and decision is written to the audit trail (spec section 16).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from core.tool_registry import ToolDefinition
from security.audit_logger import AuditLogger
from security.permission_checker import PermissionChecker

logger = logging.getLogger("jarvis.core.approval")


@dataclass(frozen=True)
class PendingApproval:
    """Everything the user needs to see before deciding (section 16)."""

    tool: str
    description: str
    risk: str
    arguments: dict[str, Any]
    reason: str
    consequences: str = field(default="")

    def summary(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items()) or "none"
        lines = [
            f"Action: {self.description}",
            f"Tool: {self.tool} (risk: {self.risk})",
            f"Arguments: {args}",
        ]
        if self.consequences:
            lines.append(f"Consequences: {self.consequences}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ApprovalDecision:
    """The user's (or policy's) decision."""

    approved: bool
    reason: str


ApprovalHandler = Callable[[PendingApproval], ApprovalDecision]


class AutoDenyHandler:
    """Denies everything - safe default for headless/unattended runs."""

    def __call__(self, pending: PendingApproval) -> ApprovalDecision:
        return ApprovalDecision(
            approved=False,
            reason="no interactive approval handler available; denied by default",
        )


class ConsoleApprovalHandler:
    """Asks on the terminal (for CLI use and manual testing)."""

    def __call__(self, pending: PendingApproval) -> ApprovalDecision:
        print("\n=== JARVIS approval required ===")
        print(pending.summary())
        answer = input("Approve? [y/N]: ").strip().lower()
        return ApprovalDecision(
            approved=answer == "y", reason="user console decision"
        )


class ApprovalManager:
    """Gatekeeper between tool proposals and execution."""

    def __init__(
        self,
        permission_checker: PermissionChecker,
        audit: AuditLogger,
        handler: ApprovalHandler | None = None,
    ) -> None:
        self._checker = permission_checker
        self._audit = audit
        self._handler = handler

    def set_handler(self, handler: ApprovalHandler) -> None:
        """Install the interactive handler (e.g. the UI dialog)."""
        self._handler = handler

    def request(self, tool: ToolDefinition, arguments: dict[str, Any]) -> ApprovalDecision:
        """Check permissions and, when required, ask for approval."""
        decision = self._checker.check(tool.name, tool.risk)
        if not decision.approval_required:
            self._audit.log(
                "tool_auto_allowed",
                tool=tool.name,
                risk=tool.risk,
                reason=decision.reason,
            )
            return ApprovalDecision(approved=True, reason=decision.reason)

        pending = PendingApproval(
            tool=tool.name,
            description=tool.description,
            risk=tool.risk,
            arguments=dict(arguments),
            reason=decision.reason,
            consequences=(
                "JARVIS will run this action on your system. "
                "Approve only if you recognise this request."
            ),
        )
        self._audit.log(
            "approval_requested",
            tool=pending.tool,
            risk=pending.risk,
            arguments=pending.arguments,
            reason=pending.reason,
        )

        handler = self._handler or AutoDenyHandler()
        try:
            result = handler(pending)
        except Exception as exc:  # a broken dialog must deny, not execute
            logger.exception("approval handler failed")
            result = ApprovalDecision(
                approved=False, reason=f"approval handler error: {type(exc).__name__}"
            )
        self._audit.log(
            "approval_decided",
            tool=pending.tool,
            approved=result.approved,
            reason=result.reason,
        )
        return result
