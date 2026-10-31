"""Task planning: turn model tool calls into validated, executable tasks.

The model proposes; the planner disposes. Unknown tools, disabled tools, and
invalid arguments are rejected here so the executor only ever sees sound
tasks (spec section 6: the model proposes tool calls, local Python validates).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.tool_registry import ToolDefinition, ToolRegistry
from providers.base_adapter import ToolCall

logger = logging.getLogger("jarvis.core.planner")


@dataclass(frozen=True)
class PlannedTask:
    """A validated tool invocation ready for approval and execution."""

    tool: ToolDefinition
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PlanResult:
    """Validated tasks plus rejected calls with reasons."""

    tasks: tuple[PlannedTask, ...] = ()
    rejections: tuple[str, ...] = field(default_factory=tuple)


class TaskPlanner:
    """Validates tool calls from the model into a safe execution plan."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def plan(self, tool_calls: tuple[ToolCall, ...]) -> PlanResult:
        tasks: list[PlannedTask] = []
        rejections: list[str] = []
        for call in tool_calls:
            if not call.name:
                rejections.append(f"{call.id}: empty tool name")
                continue
            if not self._registry.has(call.name):
                rejections.append(
                    f"{call.id}: tool '{call.name}' is not registered"
                )
                continue
            tool = self._registry.get(call.name)
            if not tool.enabled:
                rejections.append(f"{call.id}: tool '{call.name}' is disabled")
                continue
            errors = self._registry.validate_arguments(call.name, call.arguments)
            if errors:
                rejections.append(f"{call.id}: " + "; ".join(errors))
                continue
            tasks.append(PlannedTask(tool=tool, arguments=dict(call.arguments)))

        if rejections:
            logger.info("planner rejected %d call(s)", len(rejections))
        return PlanResult(tasks=tuple(tasks), rejections=tuple(rejections))
