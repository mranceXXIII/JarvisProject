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

from automation.app_launcher import AppLauncher
from core.ai_router import AIRouter
from core.approval_manager import ApprovalManager
from core.assistant import JarvisAssistant
from core.builtin_tools import register_builtin_tools
from core.config_loader import ConfigError, load_app_config
from core.logging_setup import setup_logging
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_registry import ToolRegistry
from gateway.gateway_manager import GatewayManager
from memory.conversation_store import ConversationStore
from memory.database import MemoryDatabase
from providers.provider_manager import ProviderManager
from providers.provider_registry import ProviderRegistry
from security.audit_logger import AuditLogger
from security.credential_manager import CredentialManager
from security.permission_checker import PermissionChecker

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
    logger.info("JARVIS starting (Phase 7: web research enabled)")

    credential_manager = CredentialManager()
    registry, gateways = build_registries(app_config, credential_manager)
    provider_manager = ProviderManager(credential_manager, gateways)
    router = AIRouter.from_config(app_config.routing, app_config.providers, provider_manager)
    assistant = JarvisAssistant(provider_manager, router)

    data_dir = PROJECT_ROOT / app_config.settings.app.data_dir
    memory_db = MemoryDatabase(data_dir / "jarvis.db")
    memory_store = ConversationStore(memory_db)

    # Tool orchestration (Phase 4): registry -> permissions -> approvals.
    launcher = AppLauncher.from_config_dir(args.config_dir)
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry, launcher, memory_store)

    # Desktop automation (Phase 6): windows, files, commands, screenshots.
    from automation.command_runner import CommandRunner
    from automation.file_manager import FileManager
    from automation.window_manager import WindowManager
    from core.automation_tools import register_automation_tools

    window_manager = WindowManager()
    file_manager = FileManager(app_config.file_access)
    command_runner = CommandRunner(app_config.command_runner)
    register_automation_tools(
        tool_registry,
        window_manager,
        file_manager,
        command_runner,
        data_dir / "generated",
    )

    audit = AuditLogger(data_dir / "audit" / "audit.log")

    # Web research (Phase 7): search, page reading, sourced reports.
    from core.research_tools import register_research_tools
    from research.search_engine import DuckDuckGoSearch
    from research.webpage_reader import WebPageReader

    research_config = app_config.research
    if research_config.enabled:
        register_research_tools(
            tool_registry,
            DuckDuckGoSearch(
                max_results=research_config.max_search_results,
                timeout_seconds=research_config.timeout_seconds,
            ),
            WebPageReader(
                max_bytes=research_config.max_page_bytes,
                timeout_seconds=research_config.timeout_seconds,
            ),
            data_dir / "generated" / "research",
            max_report_pages=research_config.max_report_pages,
        )
    approvals = ApprovalManager(
        PermissionChecker(app_config.permissions), audit
    )
    planner = TaskPlanner(tool_registry)
    executor = TaskExecutor(tool_registry, approvals, audit)
    assistant = JarvisAssistant(provider_manager, router, planner, executor)

    # Voice (Phase 5): optional; engines degrade honestly when unavailable.
    voice_pipeline = None
    if app_config.settings.voice.enabled:

        def handle_voice_command(text: str) -> str:
            reply = assistant.handle_text(
                text, tools=tool_registry.to_tool_specs()
            )
            return reply.text

        from voice.pipeline import VoicePipeline

        voice_pipeline = VoicePipeline.from_config(
            app_config.settings.voice, credential_manager, handle_voice_command
        )
        voice_pipeline.start()

    logger.info(
        "loaded %d provider(s) and %d gateway(s), routing mode '%s', "
        "memory at %s (FTS: %s)",
        len(registry.list_providers()),
        len(gateways.list_gateways()),
        app_config.routing.settings.mode,
        memory_db.path,
        memory_store.full_text_search_enabled,
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
            from interface.approval_dialog import UiApprovalHandler
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
                provider_manager=provider_manager,
                on_quit=request_quit,
                assistant=assistant,
                memory_store=memory_store,
                voice_pipeline=voice_pipeline,
            )
            approvals.set_handler(UiApprovalHandler(dashboard))
            dashboard.run()

        # Dashboard-only mode or closed window: keep running for the tray.
        while not quit_event.is_set() and tray is not None:
            time.sleep(0.2)
    finally:
        if voice_pipeline is not None:
            voice_pipeline.stop()
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
