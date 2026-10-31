"""Basic JARVIS dashboard (Phases 1-2, CustomTkinter).

Two tabs:
- Home: status, configured providers summary, disabled chat preview.
- API & Gateway: provider/gateway overview with the Test Connection action.

Full chat arrives when tool orchestration and approvals land (Phases 3-4);
this foundation proves the UI shell, configuration wiring, and clean
startup/shutdown.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from core.config_loader import AppConfig
from gateway.gateway_manager import GatewayManager
from providers.provider_manager import ProviderManager
from providers.provider_registry import ProviderRegistry

logger = logging.getLogger("jarvis.interface.dashboard")

WINDOW_TITLE = "JARVIS"
WINDOW_SIZE = "820x560"
STATUS_PHASE = "Phase 2: API manager online - tool orchestration arrives in Phase 4"


class Dashboard(ctk.CTk):
    """Main JARVIS dashboard window."""

    def __init__(
        self,
        app_config: AppConfig,
        registry: ProviderRegistry,
        gateways: GatewayManager,
        provider_manager: ProviderManager,
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__()
        self._config = app_config
        self._registry = registry
        self._gateways = gateways
        self._provider_manager = provider_manager
        self._on_quit = on_quit

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.protocol("WM_DELETE_WINDOW", self._hide)

        self._build_layout()
        logger.info("dashboard initialized")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        home_tab = self.tabs.add("Home")
        settings_tab = self.tabs.add("API & Gateway")

        self._build_home(home_tab)
        self.api_panel = _build_api_panel(
            settings_tab, self._provider_manager, self._config
        )

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        self.status_label = ctk.CTkLabel(footer, text=STATUS_PHASE)
        self.status_label.pack(side="left", padx=6)
        ctk.CTkButton(footer, text="Hide to tray", command=self._hide).pack(
            side="right", padx=6
        )
        ctk.CTkButton(
            footer, text="Quit JARVIS", command=self._quit, fg_color="#B23A3A"
        ).pack(side="right", padx=6)

    def _build_home(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(tab)
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(
            header,
            text=self._config.settings.app.name,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left", padx=12, pady=10)

        providers_frame = ctk.CTkFrame(tab)
        providers_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ctk.CTkLabel(
            providers_frame,
            text="Configured providers (details under 'API & Gateway')",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.providers_text = ctk.CTkTextbox(providers_frame)
        self.providers_text.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._refresh_providers()

        chat_frame = ctk.CTkFrame(tab)
        chat_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(
            chat_frame,
            text="Chat (arrives with memory + approvals in Phases 3-4)",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.chat_entry = ctk.CTkEntry(
            chat_frame, placeholder_text="Text chat is wired in a later phase"
        )
        self.chat_entry.configure(state="disabled")
        self.chat_entry.pack(fill="x", padx=10, pady=(2, 10))

    def _refresh_providers(self) -> None:
        providers = self._registry.list_providers()
        lines = [
            f"- {p.name} [{p.type}] "
            f"{'active' if p.active else ('enabled' if p.enabled else 'disabled')}"
            for p in providers
        ] or ["No providers configured. Edit config/providers.yaml."]
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


def _build_api_panel(tab, provider_manager: ProviderManager, app_config: AppConfig):
    """Construct the API & Gateway settings panel inside *tab*."""
    from interface.api_gateway_panel import ApiGatewayPanel

    panel = ApiGatewayPanel(
        master=tab,
        provider_manager=provider_manager,
        providers=list(app_config.providers),
        gateways=list(app_config.gateways),
        on_status=lambda message: None,
    )
    panel.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
    tab.grid_rowconfigure(0, weight=1)
    tab.grid_columnconfigure(0, weight=1)
    return panel
