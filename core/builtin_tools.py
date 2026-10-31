"""Built-in tools registered at startup (Phase 4).

Low-risk starter set per spec section 16: opening registered applications,
searching memory, listing applications, and reading the time. All tools go
through the same registry, permission checks, and audit trail as future
higher-risk tools.
"""

from __future__ import annotations

import logging
from datetime import datetime

from automation.app_launcher import AppLauncher
from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from memory.conversation_store import ConversationStore

logger = logging.getLogger("jarvis.core.builtin_tools")


def _open_application(launcher: AppLauncher):
    def execute(arguments: dict) -> ToolExecutionResult:
        result = launcher.open(str(arguments["app"]))
        return ToolExecutionResult(
            tool="open_application",
            success=result.success,
            output=result.message,
            details={"executable": result.executable, "pid": result.pid},
        )

    return execute


def _search_memory(store: ConversationStore):
    def execute(arguments: dict) -> ToolExecutionResult:
        limit = int(arguments.get("limit", 5))
        results = store.search(str(arguments["query"]), limit=limit)
        if not results:
            return ToolExecutionResult(
                tool="search_memory",
                success=True,
                output="No matching messages found in memory.",
            )
        lines = [
            f"- [{r.created_at}] ({r.role}) {r.snippet}"
            for r in results
        ]
        return ToolExecutionResult(
            tool="search_memory",
            success=True,
            output="\n".join(lines),
            details={"matches": len(results)},
        )

    return execute


def _list_applications(launcher: AppLauncher):
    def execute(_arguments: dict) -> ToolExecutionResult:
        apps = launcher.list_apps()
        lines = [
            f"- {app.name}: {app.display_name or app.name}" for app in apps
        ]
        return ToolExecutionResult(
            tool="list_applications",
            success=True,
            output="\n".join(lines) if lines else "No applications registered.",
            details={"count": len(apps)},
        )

    return execute


def _get_current_time():
    def execute(_arguments: dict) -> ToolExecutionResult:
        now = datetime.now().astimezone()
        return ToolExecutionResult(
            tool="get_current_time",
            success=True,
            output=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )

    return execute


def register_builtin_tools(
    registry: ToolRegistry,
    launcher: AppLauncher,
    store: ConversationStore,
) -> None:
    """Register the Phase 4 starter tool set."""
    registry.register(
        ToolDefinition(
            name="open_application",
            description=(
                "Open an application registered in applications.yaml by its "
                "name or alias"
            ),
            risk="low",
            parameters={
                "app": {
                    "type": "string",
                    "description": "registered application name or alias",
                    "required": True,
                }
            },
        ),
        _open_application(launcher),
    )
    registry.register(
        ToolDefinition(
            name="search_memory",
            description="Search past conversations by keywords",
            risk="low",
            parameters={
                "query": {
                    "type": "string",
                    "description": "keywords to search for",
                    "required": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "maximum results (default 5)",
                },
            },
        ),
        _search_memory(store),
    )
    registry.register(
        ToolDefinition(
            name="list_applications",
            description="List the applications JARVIS can open",
            risk="low",
            parameters={},
        ),
        _list_applications(launcher),
    )
    registry.register(
        ToolDefinition(
            name="get_current_time",
            description="Get the current local date and time",
            risk="low",
            parameters={},
        ),
        _get_current_time(),
    )
    logger.info("registered %d built-in tools", len(registry.list_tools()))
