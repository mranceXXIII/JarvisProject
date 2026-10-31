"""Approval dialog for tool execution (spec section 16).

Shows the exact action, tool, arguments, and consequences with Approve and
Reject choices. Used from the dashboard via a thread-safe handler.
"""

from __future__ import annotations

import logging
import threading

import customtkinter as ctk

from core.approval_manager import ApprovalDecision, PendingApproval

logger = logging.getLogger("jarvis.interface.approval")


class ApprovalDialog(ctk.CTkToplevel):
    """Approval prompt showing exactly what will happen."""

    def __init__(self, master, pending: PendingApproval, callback) -> None:
        super().__init__(master)
        self.title("JARVIS - approval required")
        self.geometry("520x360")
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", lambda: self._decide(False, "dialog closed"))

        ctk.CTkLabel(
            self,
            text="JARVIS asks for approval",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 8))

        body = ctk.CTkTextbox(self, wrap="word")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.insert("1.0", pending.summary())
        body.configure(state="disabled")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkLabel(buttons, text=pending.reason).pack(side="left", padx=4)
        ctk.CTkButton(
            buttons,
            text="Reject",
            width=100,
            command=lambda: self._decide(False, "rejected by user"),
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            buttons,
            text="Approve",
            width=100,
            command=lambda: self._decide(True, "approved by user"),
        ).pack(side="right", padx=4)

        self._callback = callback
        self._decided = False

    def _decide(self, approved: bool, reason: str) -> None:
        if self._decided:
            return
        self._decided = True
        logger.info("approval decision: %s (%s)", approved, reason)
        self.destroy()
        self._callback(ApprovalDecision(approved=approved, reason=reason))


class UiApprovalHandler:
    """Thread-safe approval handler that shows the dialog on the UI thread."""

    def __init__(self, root) -> None:
        self._root = root

    def __call__(self, pending: PendingApproval) -> ApprovalDecision:
        result: dict = {}
        done = threading.Event()

        def show_dialog() -> None:
            ApprovalDialog(
                self._root,
                pending,
                callback=lambda d: (result.__setitem__("decision", d), done.set()),
            )

        self._root.after(0, show_dialog)
        done.wait()
        return result.get("decision") or ApprovalDecision(
            approved=False, reason="no decision captured"
        )
