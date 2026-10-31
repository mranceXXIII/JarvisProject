"""Chat panel with persistent memory (Phases 2-3).

Sends user text through the assistant (routing + fallback), stores both
sides of the conversation, and displays history. Assistant calls run on a
background thread so the UI never freezes; results are posted back through
the Tk event loop.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import customtkinter as ctk

from core.assistant import JarvisAssistant
from memory.conversation_store import ConversationStore

logger = logging.getLogger("jarvis.interface.chat_panel")

HISTORY_LINES = 400


class ChatPanel(ctk.CTkFrame):
    """Working chat with conversation persistence."""

    def __init__(
        self,
        master,
        assistant: JarvisAssistant,
        store: ConversationStore,
        on_activity: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._assistant = assistant
        self._store = store
        self._on_activity = on_activity
        self._conversation_id: int | None = None
        self._busy = False
        self._build()
        logger.info("chat panel initialized (memory-backed)")

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.history = ctk.CTkTextbox(self, state="disabled", wrap="word")
        self.history.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))

        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        input_row.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(input_row, placeholder_text="Ask JARVIS...")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry.bind("<Return>", self._on_enter)
        self.send_button = ctk.CTkButton(
            input_row, text="Send", width=90, command=self._on_send
        )
        self.send_button.grid(row=0, column=1)

    def _append_history(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n\n")
        line_count = int(self.history.index("end-1c").split(".")[0])
        if line_count > HISTORY_LINES:
            self.history.delete("1.0", f"{line_count - HISTORY_LINES}.0")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _on_enter(self, _event) -> None:
        self._on_send()

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self._busy = True
        self.entry.delete(0, "end")
        self.send_button.configure(state="disabled", text="...")
        self._append_history(f"You: {text}")

        if self._conversation_id is None:
            self._conversation_id = self._store.create_conversation(
                title=text[:60]
            )
        self._store.add_message(self._conversation_id, "user", text)
        if self._on_activity is not None:
            self._on_activity("thinking...")

        history = [
            {"role": m.role, "content": m.content}
            for m in self._store.recent_messages(self._conversation_id, 20)[:-1]
        ]
        thread = threading.Thread(
            target=self._process, args=(text, history), daemon=True
        )
        thread.start()

    def _process(self, text: str, history: list[dict[str, str]]) -> None:
        try:
            reply = self._assistant.handle_text(text, history=history)
        except Exception as exc:  # defensive: never kill the UI thread
            logger.exception("assistant crashed")
            self.after(0, lambda: self._finish(f"(internal error: {type(exc).__name__})", None))
            return

        if reply.success:
            content = reply.text or "(empty response)"
            provider_line = f" [{reply.provider_name}]" if reply.provider_name else ""
            self._store.add_message(
                self._conversation_id,
                "assistant",
                content,
                provider=reply.provider_name,
                model=reply.model,
            )
            if reply.tool_calls:
                content += "\n(tool calls requested - execution arrives in Phase 4)"
            if reply.errors:
                content += f"\n(fallbacks after: {'; '.join(reply.errors)})"
            self.after(0, lambda: self._finish(f"JARVIS{provider_line}: {content}", "ready"))
        else:
            detail = reply.text + (f" ({'; '.join(reply.errors)})" if reply.errors else "")
            self._store.record_task_outcome(
                "chat", "failed", detail[:500], self._conversation_id
            )
            self.after(0, lambda: self._finish(f"JARVIS: {detail}", "ready"))

    def _finish(self, history_text: str, status: str | None) -> None:
        self._append_history(history_text)
        self._busy = False
        self.send_button.configure(state="normal", text="Send")
        if status and self._on_activity is not None:
            self._on_activity(status)
