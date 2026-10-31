"""API & Gateway Settings panel (Phase 2).

Shows configured providers and gateways and offers the 'Test Connection'
action from the spec (5.4). Results never display secret values. Editing
provider definitions is done via the YAML files in this phase; the full
add/edit/remove UI with hot reload is a later-phase refinement.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import customtkinter as ctk

from providers.provider_manager import ProviderManager

logger = logging.getLogger("jarvis.interface.api_gateway_panel")

RESULT_SUCCESS_COLOR = "#2E7D32"
RESULT_ERROR_COLOR = "#B23A3A"


class ApiGatewayPanel(ctk.CTkFrame):
    """Provider/gateway overview plus Test Connection action."""

    def __init__(
        self,
        master,
        provider_manager: ProviderManager,
        providers: list,
        gateways: list,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._manager = provider_manager
        self._providers = list(providers)
        self._gateways = list(gateways)
        self._on_status = on_status
        self._build()
        self._refresh_overview()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(self)
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(controls, text="Provider:").pack(side="left", padx=(8, 4))
        names = [p.name for p in self._providers] or ["<no providers configured>"]
        self.provider_choice = ctk.CTkOptionMenu(controls, values=names, width=280)
        self.provider_choice.pack(side="left", padx=4)
        self.test_button = ctk.CTkButton(
            controls, text="Test Connection", command=self._run_test
        )
        self.test_button.pack(side="left", padx=8)

        self.result_label = ctk.CTkLabel(
            controls, text="Save is not proof: run Test Connection to verify.",
            wraplength=380, justify="left",
        )
        self.result_label.pack(side="left", padx=12)

        self.overview = ctk.CTkTextbox(self)
        self.overview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _refresh_overview(self) -> None:
        lines = ["Providers:", ""]
        for provider in self._providers:
            state = (
                "active" if provider.active
                else ("enabled" if provider.enabled else "disabled")
            )
            lines.append(f"  - {provider.name}  [{provider.type}]  {state}")
            lines.append(f"      model: {provider.model or '<not set>'}")
            lines.append(f"      credential_ref: {provider.credential_ref or '<none>'}")
        lines += ["", "Gateways:", ""]
        for gateway in self._gateways:
            state = "enabled" if gateway.enabled else "disabled"
            lines.append(f"  - {gateway.name}  -> {gateway.url}  [{state}]")
        lines += [
            "",
            "Edit config/providers.yaml, config/gateways.yaml and",
            "config/routing.yaml to change this list, then restart JARVIS.",
        ]
        self.overview.configure(state="normal")
        self.overview.delete("1.0", "end")
        self.overview.insert("1.0", "\n".join(lines))
        self.overview.configure(state="disabled")

    def _run_test(self) -> None:
        name = self.provider_choice.get()
        provider = next((p for p in self._providers if p.name == name), None)
        if provider is None:
            self._show_result(False, "Select a configured provider first.")
            return
        self.test_button.configure(state="disabled")
        self._show_result(False, f"Testing '{provider.name}' ...")
        thread = threading.Thread(
            target=self._test_in_background, args=(provider,), daemon=True
        )
        thread.start()

    def _test_in_background(self, provider) -> None:
        result = self._manager.test_connection(provider)
        logger.info(
            "connection test for '%s': %s", provider.name,
            "success" if result.success else "failed",
        )
        self.after(0, lambda: self._show_result(result.success, result.message))
        self.after(0, lambda: self.test_button.configure(state="normal"))

    def _show_result(self, success: bool, message: str) -> None:
        self.result_label.configure(
            text=message,
            text_color=RESULT_SUCCESS_COLOR if success else RESULT_ERROR_COLOR,
        )
        if self._on_status is not None:
            self._on_status(message)
