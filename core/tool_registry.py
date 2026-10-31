"""Tool registry: declares what JARVIS can do and validates tool calls.

Every tool carries a risk level used by the permission checker, a simple
argument schema, and an executor function. The registry is the single source
of truth for what the model may request (spec sections 6, 14, 16).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from providers.base_adapter import ToolSpec

logger = logging.getLogger("jarvis.core.tool_registry")


@dataclass(frozen=True)
class ToolDefinition:
    """A registered tool's contract."""

    name: str
    description: str
    risk: str  # low | medium | high
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class ToolExecutionResult:
    """The verified outcome of one tool execution."""

    tool: str
    success: bool
    output: str
    details: dict[str, Any] = field(default_factory=dict)


ToolExecutor = Callable[[dict[str, Any]], ToolExecutionResult]


class ToolRegistry:
    """Holds tool definitions and their executors."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, ToolExecutor] = {}

    def register(
        self, definition: ToolDefinition, executor: ToolExecutor
    ) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: '{definition.name}'")
        if definition.risk not in ("low", "medium", "high"):
            raise ValueError(
                f"tool '{definition.name}' has invalid risk '{definition.risk}'"
            )
        self._tools[definition.name] = definition
        self._executors[definition.name] = executor

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: '{name}'") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools.values())

    def to_tool_specs(self) -> list[ToolSpec]:
        """Provider-neutral tool specs for chat requests."""
        return [
            ToolSpec(
                name=tool.name,
                description=f"{tool.description} (risk: {tool.risk})",
                parameters={
                    "type": "object",
                    "properties": {
                        param: {
                            "type": spec.get("type", "string"),
                            "description": spec.get("description", ""),
                        }
                        for param, spec in tool.parameters.items()
                    },
                    "required": [
                        param
                        for param, spec in tool.parameters.items()
                        if spec.get("required")
                    ],
                },
            )
            for tool in self._tools.values()
            if tool.enabled
        ]

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> list[str]:
        """Return a list of argument problems (empty when valid)."""
        tool = self.get(name)
        errors: list[str] = []
        for param, spec in tool.parameters.items():
            if spec.get("required") and param not in arguments:
                errors.append(f"missing required argument '{param}'")
        for key in arguments:
            if key not in tool.parameters:
                errors.append(f"unknown argument '{key}'")
        return errors

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        """Execute a tool directly (no approval - callers handle that)."""
        errors = self.validate_arguments(name, arguments)
        if errors:
            return ToolExecutionResult(
                tool=name, success=False, output="; ".join(errors)
            )
        executor = self._executors[name]
        try:
            return executor(arguments)
        except Exception as exc:  # executor bugs must not crash orchestration
            logger.exception("tool '%s' raised", name)
            return ToolExecutionResult(
                tool=name,
                success=False,
                output=f"tool failed: {type(exc).__name__}",
            )
