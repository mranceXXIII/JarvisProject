"""Registration of Phase 6 automation tools.

Risk levels follow spec section 16: reading windows/directories is low;
writing/moving/copying files and closing windows are medium; deleting files
and running allowlisted commands are high (always approved first).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry

logger = logging.getLogger("jarvis.core.automation_tools")


def _wrap_tool(tool_name: str, function):
    def execute(arguments: dict) -> ToolExecutionResult:
        try:
            output = function(**arguments)
            return ToolExecutionResult(tool=tool_name, success=True, output=str(output))
        except Exception as exc:
            logger.warning("tool '%s' failed: %s", tool_name, exc)
            return ToolExecutionResult(tool=tool_name, success=False, output=str(exc))

    return execute


def _command_executor(runner):
    def run(executable: str, args: str = "") -> str:
        argument_list = args.split() if args else []
        result = runner.run(executable, argument_list)
        header = f"rc={result.return_code} ({result.duration_seconds:.1f}s)"
        return f"{header}\n{result.output}"

    return run


def _screenshot_executor(directory: Path):
    def capture() -> str:
        from PIL import ImageGrab

        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        ImageGrab.grab().save(target)
        logger.info("screenshot saved to %s", target)
        return f"screenshot saved to {target}"

    return capture


def register_automation_tools(
    registry: ToolRegistry,
    window_manager,
    file_manager,
    command_runner,
    screenshot_dir: Path,
) -> None:
    """Register window, file, command, and screenshot tools."""
    if window_manager is not None and window_manager.available:
        registry.register(
            ToolDefinition(
                name="list_windows",
                description="List visible desktop windows with their titles",
                risk="low",
                parameters={},
            ),
            _wrap_tool(
                "list_windows",
                lambda: "\n".join(
                    f"- {w.title}{' (minimized)' if w.minimized else ''}"
                    f"{' (maximized)' if w.maximized else ''}"
                    for w in window_manager.list_windows()
                )
                or "No visible windows found.",
            ),
        )

        def _title_action(action: str, risk: str, description: str) -> None:
            registry.register(
                ToolDefinition(
                    name=f"{action}_window",
                    description=description,
                    risk=risk,
                    parameters={
                        "title": {
                            "type": "string",
                            "description": "window title (or part of it)",
                            "required": True,
                        }
                    },
                ),
                _wrap_tool(f"{action}_window", getattr(window_manager, action)),
            )

        _title_action("activate", "low", "Bring a window to the foreground")
        _title_action("minimize", "low", "Minimize a window")
        _title_action("maximize", "low", "Maximize a window")
        _title_action("restore", "low", "Restore a minimized window")
        _title_action(
            "close",
            "medium",
            "Close a window (the app may ask to save unsaved work)",
        )

    if file_manager is not None:
        _register_file_tools(registry, file_manager)

    if command_runner is not None:
        registry.register(
            ToolDefinition(
                name="run_command",
                description=(
                    "Run an allowlisted system command (requires approval; "
                    f"allowlist: {', '.join(command_runner.allowed_executables)})"
                ),
                risk="high",
                parameters={
                    "executable": {
                        "type": "string",
                        "description": "allowlisted executable name",
                        "required": True,
                    },
                    "args": {
                        "type": "string",
                        "description": "space-separated arguments",
                    },
                },
            ),
            _wrap_tool("run_command", _command_executor(command_runner)),
        )

    registry.register(
        ToolDefinition(
            name="take_screenshot",
            description="Capture the screen and save it locally",
            risk="low",
            parameters={},
        ),
        _wrap_tool("take_screenshot", _screenshot_executor(screenshot_dir)),
    )
    logger.info(
        "automation tools registered (windows: %s, files: %s, commands: %s)",
        window_manager is not None and window_manager.available,
        file_manager is not None,
        command_runner is not None,
    )


def _register_file_tools(registry: ToolRegistry, file_manager) -> None:
    """Register the file tools with their risk levels."""
    path_param = {
        "path": {
            "type": "string",
            "description": "path (must be inside allowed roots)",
            "required": True,
        }
    }
    src_dst = {
        "source": {"type": "string", "description": "source path", "required": True},
        "destination": {
            "type": "string",
            "description": "destination path",
            "required": True,
        },
    }
    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List directory contents inside allowed roots",
            risk="low",
            parameters=path_param,
        ),
        _wrap_tool("list_directory", file_manager.list_directory),
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read a text file (size-limited) inside allowed roots",
            risk="low",
            parameters=path_param,
        ),
        _wrap_tool("read_file", file_manager.read_text),
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description="Create or overwrite a text file inside allowed roots",
            risk="medium",
            parameters={
                "path": path_param["path"],
                "content": {
                    "type": "string",
                    "description": "text to write",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "write_file",
            lambda path, content: file_manager.write_text(path, content),
        ),
    )
    registry.register(
        ToolDefinition(
            name="move_file",
            description="Move/rename a file inside allowed roots",
            risk="medium",
            parameters=src_dst,
        ),
        _wrap_tool("move_file", file_manager.move_file),
    )
    registry.register(
        ToolDefinition(
            name="copy_file",
            description="Copy a file inside allowed roots",
            risk="medium",
            parameters=src_dst,
        ),
        _wrap_tool("copy_file", file_manager.copy_file),
    )
    registry.register(
        ToolDefinition(
            name="delete_file",
            description=(
                "Permanently delete a file inside allowed roots "
                "(requires approval; cannot be undone)"
            ),
            risk="high",
            parameters=path_param,
        ),
        _wrap_tool("delete_file", file_manager.delete_file),
    )
