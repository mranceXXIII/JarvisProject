"""Permission checking: decides when tools need user approval (section 16).

Risk levels follow the spec:
  low    : read-only or non-consequential actions
  medium : modifying settings/files, ordinary messages, scripts
  high   : deletion, purchases, public posting, sensitive sharing
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config_loader import PermissionPolicy

logger = logging.getLogger("jarvis.security.permissions")

RISK_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class PermissionDecision:
    """Outcome of a permission check."""

    approval_required: bool
    reason: str


class PermissionChecker:
    """Applies the configured policy to tool risk levels."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> PermissionPolicy:
        return self._policy

    def check(self, tool_name: str, risk: str) -> PermissionDecision:
        """Decide whether *tool_name* (declared at *risk*) needs approval."""
        if risk not in RISK_LEVELS:
            # Unknown risk: be conservative and require approval.
            return PermissionDecision(
                approval_required=True,
                reason=f"unknown risk level '{risk}' - approval required by default",
            )
        if tool_name in self._policy.trusted_tools:
            return PermissionDecision(
                approval_required=False,
                reason=f"'{tool_name}' is trusted in permissions.yaml",
            )
        if risk == "medium" and self._policy.require_approval_medium:
            return PermissionDecision(
                approval_required=True, reason="medium-risk actions require approval"
            )
        if risk == "high" and self._policy.require_approval_high:
            return PermissionDecision(
                approval_required=True, reason="high-risk actions require approval"
            )
        return PermissionDecision(
            approval_required=False, reason=f"{risk}-risk action allowed by policy"
        )
