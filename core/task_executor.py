"""Task execution: run approved tasks with timeouts and cancellation.

Execution rules (spec section 4.3):
- Every task passes through the approval manager first; denied tasks are
  NOT executed and reported as such.
- Each task runs in a worker thread bounded by a timeout; timeouts are
  reported honestly as failures.
- A cancellation event stops the queue between tasks.
- Every proposal, decision, and outcome lands in the audit trail.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from core.approval_manager import ApprovalManager
from core.tool_registry import ToolExecutionResult, ToolRegistry
from security.audit_logger import AuditLogger
from core.task_planner import PlannedTask

logger = logging.getLogger("jarvis.core.executor")

DEFAULT_TASK_TIMEOUT_SECONDS = 30


class TaskExecutor:
    """Executes planned tasks under approvals, timeouts, and cancellation."""

    def __init__(
        self,
        registry: ToolRegistry,
        approvals: ApprovalManager,
        audit: AuditLogger,
        default_timeout: float = DEFAULT_TASK_TIMEOUT_SECONDS,
    ) -> None:
        self._registry = registry
        self._approvals = approvals
        self._audit = audit
        self._timeout = default_timeout

    def execute(
        self,
        tasks: tuple[PlannedTask, ...],
        cancel_event: threading.Event | None = None,
    ) -> tuple[ToolExecutionResult, ...]:
        """Run tasks in order; returns one result per task."""
        results: list[ToolExecutionResult] = []
        for task in tasks:
            if cancel_event is not None and cancel_event.is_set():
                results.append(
                    ToolExecutionResult(
                        tool=task.tool.name,
                        success=False,
                        output="cancelled before execution",
                    )
                )
                self._audit.log(
                    "task_cancelled", tool=task.tool.name, arguments=task.arguments
                )
                continue

            decision = self._approvals.request(task.tool, task.arguments)
            if not decision.approved:
                results.append(
                    ToolExecutionResult(
                        tool=task.tool.name,
                        success=False,
                        output=f"denied: {decision.reason}",
                    )
                )
                continue

            result = self._execute_with_timeout(task)
            results.append(result)
            self._audit.log(
                "task_executed",
                tool=task.tool.name,
                arguments=task.arguments,
                success=result.success,
                output=result.output,
            )
        return tuple(results)

    def _execute_with_timeout(self, task: PlannedTask) -> ToolExecutionResult:
        timeout = task.tool.parameters.get("_timeout", self._timeout)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-task") as pool:
            future = pool.submit(self._registry.execute, task.tool.name, task.arguments)
            try:
                return future.result(timeout=timeout)
            except FutureTimeoutError:
                future.cancel()
                logger.warning("task '%s' timed out after %.0fs", task.tool.name, timeout)
                return ToolExecutionResult(
                    tool=task.tool.name,
                    success=False,
                    output=f"timed out after {timeout:.0f}s",
                )
