"""TaskLifecycle: full state machine with dynamic routing, reassignment, and recovery.

States: RECEIVED → SENSING → CONTEXT_VALIDATED → PLANNING → AUDITING →
        AWAITING_APPROVAL → APPROVED → EXECUTING → VERIFYING → COMPLETED/ROLLBACK/FAILED

Also supports:
- Dynamic re-route by Team Leader after mid-result.
- Conflict resolution (multiple audit outcomes, competing plans).
- Worker timeout / failure → reassignment or human handoff.
- Rollback and child-task creation when external context changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from energymesh.skill_registry import SkillRegistry


class TaskState(StrEnum):
    RECEIVED = "RECEIVED"
    SENSING = "SENSING"
    CONTEXT_VALIDATED = "CONTEXT_VALIDATED"
    PLANNING = "PLANNING"
    AUDITING = "AUDITING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ROLLBACK = "ROLLBACK"
    FAILED = "FAILED"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    REPLANNING_REQUIRED = "REPLANNING_REQUIRED"


class TransitionRule(StrEnum):
    FIXED = "fixed"          # state machine enforces next
    DYNAMIC = "dynamic"      # Team Leader decides next based on evidence
    HUMAN = "human"          # must stop for operator
    RECOVERY = "recovery"    # failure branch


LEGAL_TRANSITIONS: dict[TaskState, dict[TaskState, TransitionRule]] = {
    TaskState.RECEIVED: {
        TaskState.SENSING: TransitionRule.FIXED,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.SENSING: {
        TaskState.CONTEXT_VALIDATED: TransitionRule.FIXED,
        TaskState.REPLANNING_REQUIRED: TransitionRule.DYNAMIC,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.CONTEXT_VALIDATED: {
        TaskState.PLANNING: TransitionRule.FIXED,
        TaskState.REPLANNING_REQUIRED: TransitionRule.DYNAMIC,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
    },
    TaskState.REPLANNING_REQUIRED: {
        TaskState.PLANNING: TransitionRule.FIXED,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
    },
    TaskState.PLANNING: {
        TaskState.AUDITING: TransitionRule.FIXED,
        TaskState.FAILED: TransitionRule.RECOVERY,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
    },
    TaskState.AUDITING: {
        TaskState.AWAITING_APPROVAL: TransitionRule.DYNAMIC,
        TaskState.APPROVED: TransitionRule.DYNAMIC,
        TaskState.ROLLBACK: TransitionRule.DYNAMIC,
        TaskState.FAILED: TransitionRule.RECOVERY,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
    },
    TaskState.AWAITING_APPROVAL: {
        TaskState.APPROVED: TransitionRule.HUMAN,
        TaskState.REJECTED: TransitionRule.HUMAN,
        TaskState.ROLLBACK: TransitionRule.DYNAMIC,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.APPROVED: {
        TaskState.EXECUTING: TransitionRule.FIXED,
        TaskState.ROLLBACK: TransitionRule.DYNAMIC,
    },
    TaskState.EXECUTING: {
        TaskState.VERIFYING: TransitionRule.FIXED,
        TaskState.ROLLBACK: TransitionRule.RECOVERY,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.VERIFYING: {
        TaskState.COMPLETED: TransitionRule.DYNAMIC,
        TaskState.ROLLBACK: TransitionRule.DYNAMIC,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.ROLLBACK: {
        TaskState.SENSING: TransitionRule.DYNAMIC,
        TaskState.HUMAN_HANDOFF: TransitionRule.RECOVERY,
        TaskState.FAILED: TransitionRule.RECOVERY,
    },
    TaskState.HUMAN_HANDOFF: {
        TaskState.SENSING: TransitionRule.HUMAN,
        TaskState.FAILED: TransitionRule.HUMAN,
    },
    TaskState.COMPLETED: {},
    TaskState.FAILED: {
        TaskState.SENSING: TransitionRule.RECOVERY,
    },
}


@dataclass
class TaskTransition:
    from_state: TaskState | None
    to_state: TaskState
    actor: str
    reason: str
    rule: TransitionRule
    timestamp: str
    context_change: dict[str, Any] | None = None
    worker_result: dict[str, Any] | None = None


@dataclass
class TaskRecord:
    task_id: str
    scenario_id: str
    state: TaskState
    version: int = 1
    parent_task_id: str | None = None
    trigger: str = ""
    context_id: str | None = None
    context_hash: str | None = None
    selected_plan_id: str | None = None
    approved: bool = False
    approval_reason: str | None = None
    approver: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    transitions: list[TaskTransition] = field(default_factory=list)
    worker_assignments: list[dict[str, Any]] = field(default_factory=list)
    evidence_sha256: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def transition(
        self,
        to_state: TaskState,
        actor: str,
        reason: str,
        rule: TransitionRule = TransitionRule.DYNAMIC,
        context_change: dict[str, Any] | None = None,
        worker_result: dict[str, Any] | None = None,
    ) -> None:
        allowed = LEGAL_TRANSITIONS.get(self.state, {})
        if to_state not in allowed and to_state != self.state:
            raise ValueError(
                f"Illegal transition {self.state.value} -> {to_state.value}"
            )
        self.transitions.append(
            TaskTransition(
                from_state=self.state,
                to_state=to_state,
                actor=actor,
                reason=reason,
                rule=rule,
                timestamp=datetime.now(UTC).isoformat(),
                context_change=context_change,
                worker_result=worker_result,
            )
        )
        self.state = to_state
        self.updated_at = datetime.now(UTC).isoformat()
        if to_state == TaskState.APPROVED:
            self.approved = True

    def child_task(self, trigger: str, reason: str) -> TaskRecord:
        child = TaskRecord(
            task_id=f"task_{uuid4().hex[:12]}",
            scenario_id=self.scenario_id,
            state=TaskState.RECEIVED,
            version=1,
            parent_task_id=self.task_id,
            trigger=trigger,
        )
        child.transition(TaskState.SENSING, "orchestrator", reason, TransitionRule.FIXED)
        return child

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scenario_id": self.scenario_id,
            "state": self.state.value,
            "version": self.version,
            "parent_task_id": self.parent_task_id,
            "trigger": self.trigger,
            "context_id": self.context_id,
            "context_hash": self.context_hash,
            "selected_plan_id": self.selected_plan_id,
            "approved": self.approved,
            "approver": self.approver,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "transitions": [
                {
                    "from": t.from_state.value if t.from_state else None,
                    "to": t.to_state.value,
                    "actor": t.actor,
                    "reason": t.reason,
                    "rule": t.rule.value,
                    "timestamp": t.timestamp,
                }
                for t in self.transitions
            ],
            "evidence_sha256": self.evidence_sha256,
            "extra": self.extra,
        }


class TaskLifecycleManager:
    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.tasks: dict[str, TaskRecord] = {}
        self.registry = registry

    def create(
        self,
        scenario_id: str,
        trigger: str = "day_ahead_schedule",
        parent_task_id: str | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            task_id=f"task_{uuid4().hex[:12]}",
            scenario_id=scenario_id,
            state=TaskState.RECEIVED,
            parent_task_id=parent_task_id,
            trigger=trigger,
        )
        task.transition(TaskState.SENSING, "team_leader", "task created and dispatched to perception worker")
        self.tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        return self.tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[TaskRecord]:
        return sorted(self.tasks.values(), key=lambda t: t.updated_at, reverse=True)[:limit]

    def update(self, task: TaskRecord) -> None:
        self.tasks[task.task_id] = task

    def invalidate_by_context_change(
        self, task_id: str, change_description: str, changed_fields: dict[str, Any]
    ) -> TaskRecord:
        """When external conditions change, create a child task and mark parent stale."""
        parent = self.tasks.get(task_id)
        if parent is None:
            raise ValueError(f"Task {task_id} not found")
        child = parent.child_task(
            trigger=f"CONTEXT_CHANGE:{change_description}",
            reason=f"Context changed: {change_description}",
        )
        parent.transition(
            TaskState.REPLANNING_REQUIRED,
            "monitor",
            f"External change detected: {change_description}; child task {child.task_id} created",
            TransitionRule.DYNAMIC,
            context_change=changed_fields,
        )
        self.tasks[child.task_id] = child
        return child
