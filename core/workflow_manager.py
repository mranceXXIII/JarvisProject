"""Reusable workflows (spec section 15).

A workflow is a named sequence of tool calls stored in an editable YAML
file (``config/workflows.yaml``). Running a workflow replays its steps
through the task executor, so **every step still passes the permission
checker, approval dialog, and audit trail** - a workflow never bypasses
the approval-first model. Schedule strings are stored for Phase 12
scheduling; execution is on-demand for now (stated honestly).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from providers.base_adapter import ToolCall
from security.audit_logger import AuditLogger

logger = logging.getLogger("jarvis.workflows")


class WorkflowStep(BaseModel):
    """One tool call inside a workflow."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class Workflow(BaseModel):
    """A named, reusable workflow."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    steps: list[WorkflowStep] = Field(min_length=1)
    enabled: bool = True
    paused: bool = False
    schedule: str | None = None  # stored for Phase 12 scheduling


class WorkflowError(RuntimeError):
    """Raised for workflow management problems."""


class WorkflowManager:
    """CRUD and execution for YAML-defined workflows."""

    def __init__(
        self,
        path: Path,
        planner: TaskPlanner,
        executor: TaskExecutor,
        audit: AuditLogger,
    ) -> None:
        self._path = path
        self._planner = planner
        self._executor = executor
        self._audit = audit
        self._workflows: dict[str, Workflow] = {}
        self.reload()

    # -- persistence ------------------------------------------------------

    def reload(self) -> int:
        """Load workflows from the YAML file; returns the count."""
        self._workflows = {}
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("workflows: []\n", encoding="utf-8")
            return 0
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            items = payload.get("workflows", []) if isinstance(payload, dict) else []
            for item in items:
                workflow = Workflow.model_validate(item)
                self._workflows[workflow.name.lower()] = workflow
        except (yaml.YAMLError, ValidationError) as exc:
            raise WorkflowError(f"invalid workflows file: {exc}") from exc
        return len(self._workflows)

    def _persist(self) -> None:
        payload = {"workflows": [w.model_dump() for w in self._workflows.values()]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

    # -- CRUD ---------------------------------------------------------------

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {
                "name": w.name,
                "description": w.description,
                "steps": len(w.steps),
                "enabled": w.enabled,
                "paused": w.paused,
                "schedule": w.schedule,
            }
            for w in self._workflows.values()
        ]

    def get(self, name: str) -> Workflow:
        workflow = self._workflows.get(name.strip().lower())
        if workflow is None:
            known = ", ".join(sorted(self._workflows)) or "<none>"
            raise WorkflowError(f"unknown workflow '{name}' (known: {known})")
        return workflow

    def create(
        self, name: str, description: str, steps: list[dict[str, Any]]
    ) -> str:
        key = name.strip().lower()
        if key in self._workflows:
            raise WorkflowError(f"workflow '{name}' already exists")
        workflow = Workflow.model_validate(
            {"name": name, "description": description, "steps": steps}
        )
        self._validate_steps(workflow)
        self._workflows[key] = workflow
        self._persist()
        self._audit.log("workflow_created", workflow=workflow.name)
        return (
            f"Workflow '{workflow.name}' created with "
            f"{len(workflow.steps)} step(s)."
        )

    def rename(self, old_name: str, new_name: str) -> str:
        workflow = self.get(old_name)
        new_key = new_name.strip().lower()
        if new_key in self._workflows:
            raise WorkflowError(f"workflow '{new_name}' already exists")
        updated = workflow.model_copy(update={"name": new_name})
        del self._workflows[workflow.name.lower()]
        self._workflows[new_key] = updated
        self._persist()
        return f"Workflow '{workflow.name}' renamed to '{new_name}'."

    def delete(self, name: str) -> str:
        workflow = self.get(name)
        del self._workflows[workflow.name.lower()]
        self._persist()
        self._audit.log("workflow_deleted", workflow=workflow.name)
        return f"Workflow '{workflow.name}' deleted."

    def set_paused(self, name: str, paused: bool) -> str:
        workflow = self.get(name)
        updated = workflow.model_copy(update={"paused": paused})
        self._workflows[workflow.name.lower()] = updated
        self._persist()
        state = "paused" if paused else "resumed"
        return f"Workflow '{workflow.name}' {state}."

    def _validate_steps(self, workflow: Workflow) -> None:
        """Every step's tool must exist with valid arguments."""
        for index, step in enumerate(workflow.steps, start=1):
            call = ToolCall(
                id=f"wf_{workflow.name}_{index}",
                name=step.tool,
                arguments=step.arguments,
            )
            plan = self._planner.plan((call,))
            if plan.rejections:
                raise WorkflowError(
                    f"step {index} of workflow '{workflow.name}': "
                    + "; ".join(plan.rejections)
                )

    # -- execution -------------------------------------------------------------

    def run(self, name: str) -> str:
        """Run a workflow; each step goes through approvals and the audit."""
        workflow = self.get(name)
        if not workflow.enabled:
            return f"Workflow '{workflow.name}' is disabled."
        if workflow.paused:
            return f"Workflow '{workflow.name}' is paused."
        if workflow.schedule:
            logger.info(
                "workflow '%s' has a schedule (%s); scheduled execution "
                "arrives in Phase 12 - running on demand now",
                workflow.name,
                workflow.schedule,
            )
        calls = tuple(
            ToolCall(
                id=f"wf_{workflow.name}_{index}",
                name=step.tool,
                arguments=dict(step.arguments),
            )
            for index, step in enumerate(workflow.steps, start=1)
        )
        plan = self._planner.plan(calls)
        if not plan.tasks:
            return (
                "Workflow produced no executable steps: "
                + "; ".join(plan.rejections)
            )
        results = self._executor.execute(plan.tasks)
        self._audit.log(
            "workflow_run",
            workflow=workflow.name,
            steps=len(results),
            successes=sum(1 for r in results if r.success),
        )
        lines = [
            f"- {r.tool}: {'OK' if r.success else 'FAILED'} - {r.output}"
            for r in results
        ]
        succeeded = sum(1 for r in results if r.success)
        return (
            f"Workflow '{workflow.name}': {succeeded}/{len(results)} steps "
            "succeeded.\n" + "\n".join(lines)
        )
