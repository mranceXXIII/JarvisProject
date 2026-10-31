"""Dashboard voice controls (Phase 5).

Compact panel showing honest engine availability and the voice state, with
Activate / Mute / Pause / Emergency Stop controls (spec section 7). When the
voice pipeline is disabled or unavailable, the panel says so plainly.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import customtkinter as ctk

logger = logging.getLogger("jarvis.interface.voice_panel")

STATE_COLORS = {
    "standby": "#5B7C99",
    "active": "#2E7D32",
    "processing": "#B58900",
    "speaking": "#2E7D32",
    "muted": "#B23A3A",
    "paused": "#B58900",
    "stopped": "#8B0000",
}


class VoicePanel(ctk.CTkFrame):
    """Voice status + controls."""

    def __init__(self, master, pipeline, on_status=None) -> None:
        super().__init__(master)
        self._pipeline = pipeline
        self._on_status = on_status
        self.grid_columnconfigure(1, weight=1)
        self._build()
        self.refresh()

    def _build(self) -> None:
        ctk.CTkLabel(self, text="Voice", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )
        self.status_label = ctk.CTkLabel(self, text="...")
        self.status_label.grid(row=0, column=1, sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ctk.CTkButton(
            buttons, text="Activate", width=90, command=self._activate
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            buttons, text="Mute", width=70, command=self._toggle_mute
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            buttons, text="Pause", width=70, command=self._toggle_pause
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            buttons, text="Emergency stop", width=120,
            command=self._emergency_stop, fg_color="#B23A3A",
        ).pack(side="left", padx=3)

    def refresh(self) -> None:
        if self._pipeline is None:
            self.status_label.configure(
                text="Voice disabled (enable in settings.yaml)", text_color="#777777"
            )
            return
        report: dict[str, Any] = self._pipeline.status_report()
        state = report["state"]
        color = STATE_COLORS.get(state, "#777777")
        unavailable = [
            name
            for name, ok in (
                ("microphone", report["microphone"]),
                ("speech-to-text", report["stt"]),
                ("text-to-speech", report["tts"]),
                ("wake word", report["wake_word"]),
            )
            if not ok
        ]
        text = state.upper()
        if unavailable:
            text += (
                " (unavailable: " + ", ".join(unavailable)
                + " - manual/text activation still works)"
            )
        self.status_label.configure(text=text, text_color=color)
        if self._on_status is not None:
            self._on_status("Voice: " + text)

    def _activate(self) -> None:
        if self._pipeline is not None:
            self._pipeline.activate_manual()
            self.refresh()

    def _toggle_mute(self) -> None:
        if self._pipeline is None:
            return
        if self._pipeline.state.value == "muted":
            self._pipeline.unmute()
        else:
            self._pipeline.mute()
        self.refresh()

    def _toggle_pause(self) -> None:
        if self._pipeline is None:
            return
        if self._pipeline.state.value == "paused":
            self._pipeline.resume()
        else:
            self._pipeline.pause()
        self.refresh()

    def _emergency_stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.emergency_stop()
            self.refresh()
