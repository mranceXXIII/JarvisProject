"""Phase 10 tools: plugin management and workflow management.

plugin_generate / plugin_approve_install / workflow_save / workflow_delete
are MEDIUM risk (they modify configuration and, for plugins, add executable
code - which is additionally approved at install time). Listing/running
workflows is low risk because every workflow step still passes its own
approval gates.
"""

from __future__ import annotations

import logging

from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from core.workflow_manager import WorkflowError, WorkflowManager
from plugins.plugin_manager import PluginManager

logger = logging.getLogger("jarvis.core.management_tools")


def _wrap_tool(tool_name: str, function):
    def execute(arguments: dict) -> ToolExecutionResult:
        try:
            output = function(**arguments)
            return ToolExecutionResult(tool=tool_name, success=True, output=str(output))
        except Exception as exc:
            logger.warning("tool '%s' failed: %s", tool_name, exc)
            return ToolExecutionResult(tool=tool_name, success=False, output=str(exc))

    return execute


def register_plugin_tools(registry: ToolRegistry, manager: PluginManager) -> None:
    """Register plugin lifecycle tools."""

    def plugin_list() -> str:
        plugins = manager.list_installed()
        if not plugins:
            return "No plugins installed. Generated plugins wait in staging."
        lines = []
        for plugin in plugins:
            disabled = plugin.get("disabled_by_user") or not plugin.get(
                "enabled", True
            )
            lines.append(
                f"- {plugin.get('name')} v{plugin.get('version', '?')}: "
                f"{'disabled' if disabled else 'enabled'}; permissions: "
                f"{', '.join(plugin.get('permissions', [])) or 'none'}"
            )
            if plugin.get("error"):
                lines.append(f"    ERROR: {plugin['error']}")
        return "\n".join(lines)

    registry.register(
        ToolDefinition(
            name="plugin_list",
            description="List installed plugins and their permissions",
            risk="low",
            parameters={},
        ),
        _wrap_tool("plugin_list", plugin_list),
    )
    registry.register(
        ToolDefinition(
            name="plugin_generate",
            description=(
                "Generate a new plugin skeleton in the staging area "
                "(staged plugins are analyzed and need approval to install)"
            ),
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "plugin name (letters/digits/underscore)",
                    "required": True,
                },
                "description": {
                    "type": "string",
                    "description": "what the plugin should do",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "plugin_generate",
            lambda name, description: (
                f"Plugin staged at {manager.stage_new_plugin(name, description)}. "
                "Run plugin_validate, then plugin_approve_install."
            ),
        ),
    )
    registry.register(
        ToolDefinition(
            name="plugin_validate",
            description="Run static safety checks on a staged plugin",
            risk="low",
            parameters={
                "name": {
                    "type": "string",
                    "description": "staged plugin name",
                    "required": True,
                }
            },
        ),
        _wrap_tool(
            "plugin_validate",
            lambda name: (
                "Validation OK - ready for plugin_approve_install."
                if not manager.validate_staged(name)
                else "Problems: " + "; ".join(manager.validate_staged(name))
            ),
        ),
    )
    registry.register(
        ToolDefinition(
            name="plugin_approve_install",
            description=(
                "Approve and install a staged plugin (shows its permissions; "
                "requires explicit user approval)"
            ),
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "staged plugin name",
                    "required": True,
                }
            },
        ),
        _wrap_tool("plugin_approve_install", manager.install_staged),
    )
    registry.register(
        ToolDefinition(
            name="plugin_toggle",
            description="Enable or disable an installed plugin",
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "plugin name",
                    "required": True,
                },
                "enabled": {"type": "boolean", "description": "true to enable"},
            },
        ),
        _wrap_tool(
            "plugin_toggle",
            lambda name, enabled=True: manager.set_enabled(name, bool(enabled)),
        ),
    )
    logger.info("plugin management tools registered")


def register_workflow_tools(
    registry: ToolRegistry, manager: WorkflowManager
) -> None:
    """Register workflow tools."""

    def workflow_list() -> str:
        workflows = manager.list_workflows()
        if not workflows:
            return (
                "No workflows defined. Edit config/workflows.yaml or ask "
                "JARVIS to create one."
            )
        return "\n".join(
            f"- {w['name']}: {w['description'] or '(no description)'} "
            f"({w['steps']} steps"
            + ("; paused" if w["paused"] else "")
            + (f"; schedule: {w['schedule']}" if w["schedule"] else "")
            + ")"
            for w in workflows
        )

    registry.register(
        ToolDefinition(
            name="workflow_list",
            description="List defined workflows",
            risk="low",
            parameters={},
        ),
        _wrap_tool("workflow_list", workflow_list),
    )
    registry.register(
        ToolDefinition(
            name="workflow_run",
            description=(
                "Run a workflow by name; every step still requires its own "
                "approvals"
            ),
            risk="low",
            parameters={
                "name": {
                    "type": "string",
                    "description": "workflow name",
                    "required": True,
                }
            },
        ),
        _wrap_tool("workflow_run", manager.run),
    )
    registry.register(
        ToolDefinition(
            name="workflow_save",
            description=(
                "Create a workflow from steps (each step must reference an "
                "existing tool with valid arguments)"
            ),
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "workflow name",
                    "required": True,
                },
                "description": {"type": "string", "description": "description"},
                "steps": {
                    "type": "string",
                    "description": (
                        "steps as 'tool1 arg=val; tool2 arg=val' separated "
                        "by semicolons"
                    ),
                    "required": True,
                },
            },
        ),
        _wrap_tool("workflow_save", _workflow_saver(manager)),
    )
    registry.register(
        ToolDefinition(
            name="workflow_delete",
            description="Delete a workflow",
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "workflow name",
                    "required": True,
                }
            },
        ),
        _wrap_tool("workflow_delete", manager.delete),
    )
    registry.register(
        ToolDefinition(
            name="workflow_pause",
            description="Pause or resume a workflow",
            risk="medium",
            parameters={
                "name": {
                    "type": "string",
                    "description": "workflow name",
                    "required": True,
                },
                "paused": {"type": "boolean", "description": "true to pause"},
            },
        ),
        _wrap_tool(
            "workflow_pause",
            lambda name, paused=True: manager.set_paused(name, bool(paused)),
        ),
    )
    logger.info("workflow tools registered")


def _workflow_saver(manager: WorkflowManager):
    def save(name: str, steps: str, description: str = "") -> str:
        parsed: list[dict] = []
        for chunk in steps.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split()
            tool = parts[0]
            arguments: dict = {}
            for part in parts[1:]:
                if "=" in part:
                    key, _, value = part.partition("=")
                    arguments[key] = value
            parsed.append({"tool": tool, "arguments": arguments})
        if not parsed:
            raise WorkflowError("no steps could be parsed from the input")
        return manager.create(name, description, parsed)

    return save
