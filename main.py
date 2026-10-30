"""JARVIS application entry point (Phase 1).

Loads and validates configuration, configures secret-redacting logging,
initializes the provider/gateway registries, and starts the UI foundation
(dashboard and/or system tray according to ``config/settings.yaml``).

Usage:
    python main.py            # normal start (dashboard and/or tray)
    python main.py --headless # start without UI; idles until Ctrl+C
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from core.config_loader import ConfigError, load_app_config
from core.logging_setup import setup_logging
from gateway.gateway_manager import GatewayManager
from providers.provider_registry import ProviderRegistry
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.main")

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS personal AI assistant")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without dashboard or tray (for testing and services)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=PROJECT_ROOT / "config",
        help="configuration directory (default: ./config)",
    )
    return parser.parse_args(argv)


def build_registries(
    app_config, credential_manager: CredentialManager
) -> tuple[ProviderRegistry, GatewayManager]:
    """Construct the provider registry and gateway manager from config."""
    registry = ProviderRegistry(
        providers=app_config.providers, credential_manager=credential_manager
    )
    gateways = GatewayManager(app_config.gateways)
    return registry, gateways


def run() -> int:
    args = parse_args()
    try:
        app_config = load_app_config(args.config_dir)
    except ConfigError as exc:
        # Logging may not be configured yet; print safely and exit nonzero.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(app_config.settings.logging, project_root=PROJECT_ROOT)
    logger.info("JARVIS starting (Phase 1 foundation)")

    credential_manager = CredentialManager()
    registry, gateways = build_registries(app_config, credential_manager)
    logger.info(
        "loaded %d provider(s) and %d gateway(s)",
        len(registry.list_providers()),
        len(gateways.list_gateways()),
    )

    if args.headless:
        return _run_headless()

    app_settings = app_config.settings.app
    quit_event = threading.Event()

    def request_quit() -> None:
        quit_event.set()

    tray = None
    dashboard = None

    try:
        if app_settings.tray_enabled and app_settings.startup_mode in ("tray", "both"):
            from interface.system_tray import SystemTray

            def open_dashboard() -> None:
                if dashboard is not None:
                    dashboard.after(0, dashboard.show)

            tray = SystemTray(on_open_dashboard=open_dashboard, on_quit=request_quit)
            tray.start()

        if app_settings.dashboard_enabled and app_settings.startup_mode in (
            "dashboard",
            "both",
        ):
            from interface.dashboard import Dashboard

            dashboard = Dashboard(
                app_config=app_config,
                registry=registry,
                gateways=gateways,
                on_quit=request_quit,
            )
            dashboard.run()

        # Dashboard-only mode or closed window: keep running for the tray.
        while not quit_event.is_set() and tray is not None:
            time.sleep(0.2)
    finally:
        if tray is not None:
            tray.stop()
        logger.info("JARVIS shut down cleanly")
    return 0


def _run_headless() -> int:
    logger.info("headless mode: idling until Ctrl+C")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("headless mode interrupted; shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(run())
