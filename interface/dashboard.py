"""Basic JARVIS dashboard (Phase 1 foundation, CustomTkinter).

Phase 1 shows application status, configured providers (with masked
credentials), and a disabled chat preview. Chat, provider editing, and
connection testing arrive in later phases; this foundation only proves the
UI shell, configuration wiring, and clean startup/shutdown.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from core.config_loader import AppConfig
from gateway.gateway_manager import GatewayManager
from providers.provider_registry import ProviderRegistry

logger = logging.getLogger("jarvis.interface.dashboard")

WINDOW_TITLE = "JARVIS"
WINDOW_SIZE = "760x520"
STATUS_PHASE_1 = "Phase 1: foundation running - AI features arrive in Phase 2"


class Dashboard(ctk.CTk):
    """Main JARVIS dashboard window."""

    def __init__(
        self,
        app_config: AppConfig,
        registry: ProviderRegistry,
        gateways: GatewayManager,
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__()
        self._config = app_config
        self._registry = registry
        self._gateways = gateways
        self._on_quit = on_quit

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.protocol("WM_DELETE_WINDOW", self._hide)

        self._build_layout()
        self._refresh_status()
        logger.info("dashboard initialized")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        ctk.CTkLabel(
            header,
            text=self._config.settings.app.name,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left", padx=12, pady=10)
        self.status_label = ctk.CTkLabel(header, text=STATUS_PHASE_1)
        self.status_label.pack(side="right", padx=12)

        body = ctk.CTkFrame(self)
        body.grid(row=1, column=0, padx=12, pady=6, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        providers_frame = ctk.CTkFrame(body)
        providers_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ctk.CTkLabel(
            providers_frame, text="Configured providers", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.providers_text = ctk.CTkTextbox(providers_frame, height=160)
        self.providers_text.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        chat_frame = ctk.CTkFrame(body)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ctk.CTkLabel(
            chat_frame, text="Chat (available in Phase 2)", font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.chat_entry = ctk.CTkEntry(
            chat_frame, placeholder_text="Text chat is implemented in Phase 2"
        )
        self.chat_entry.configure(state="disabled")
        self.chat_entry.pack(fill="x", padx=10, pady=(2, 10))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=12, pady=(6, 12), sticky="ew")
        ctk.CTkButton(footer, text="Hide to tray", command=self._hide).pack(
            side="right", padx=6
        )
        ctk.CTkButton(
            footer, text="Quit JARVIS", command=self._quit, fg_color="#B23A3A"
        ).pack(side="right", padx=6)

    def _refresh_status(self) -> None:
        lines: list[str] = []
        providers = self._registry.list_providers()
        if not providers:
            lines.append("No providers configured. Edit config/providers.yaml.")
        for provider in providers:
            state = "active" if provider.active else ("enabled" if provider.enabled else "disabled")
            lines.append(f"- {provider.name} [{provider.type}] - {state}")
            lines.append(f"    credential_ref: {provider.credential_ref or '<none>'}")
        lines.append("")
        gateways = self._gateways.list_gateways()
        if not gateways:
            lines.append("No gateways configured. Edit config/gateways.yaml.")
        for gateway in gateways:
            state = "enabled" if gateway.enabled else "disabled"
            lines.append(f"- {gateway.name} -> {gateway.url} [{state}]")
        self.providers_text.configure(state="normal")
        self.providers_text.delete("1.0", tk.END)
        self.providers_text.insert("1.0", "\n".join(lines))
        self.providers_text.configure(state="disabled")

    def _hide(self) -> None:
        """Hide the window; the tray keeps JARVIS alive if enabled."""
        self.withdraw()
        logger.info("dashboard hidden to tray")

    def show(self) -> None:
        """Show and raise the dashboard window."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit(self) -> None:
        logger.info("quit requested from dashboard")
        self.destroy()
        self._on_quit()

    def run(self) -> None:
        """Run the Tk main loop until the window is destroyed."""
        self.mainloop()
