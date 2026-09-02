"""AgentWorker: autonomous workers with timeout, retry, and handoff.

Each worker has a distinct role, permission boundary, and Skill set.
The Team Leader dispatches tasks to workers asynchronously and re-routes
based on intermediate results.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable

from energymesh.skill_registry import SkillRegistry, SkillInvocationRecord


class WorkerStatus(StrEnum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REASSIGNED = "reassigned"
    CONFLICT = "conflict"


class WorkerRole(StrEnum):
    PERCEPTION = "perception"
    DISPATCH = "dispatch"
    AUDIT = "audit"
    EXECUTION = "execution"


@dataclass
class WorkerResult:
    worker_id: str
    role: str
    task_id: str
    skill_name: str
    status: str
    data: dict[str, Any] | None
    error: str | None
    duration_ms: int
    invocation_record: SkillInvocationRecord | None


@dataclass
class AgentWorker:
    worker_id: str
    role: WorkerRole
    display_name: str
    skills: list[str]
    permissions: list[str]
    max_retries: int = 2
    timeout_seconds: float = 30.0
    # runtime state
    status: WorkerStatus = WorkerStatus.IDLE
    assigned_task_id: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def can_accept(self, skill_name: str) -> bool:
        return skill_name in self.skills

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or "*" in self.permissions

    def execute(
        self,
        task_id: str,
        task_version: int,
        trace_id: str,
        skill_name: str,
        payload: dict[str, Any],
        registry: SkillRegistry,
    ) -> WorkerResult:
        self.status = WorkerStatus.ASSIGNED
        self.assigned_task_id = task_id
        self.status = WorkerStatus.RUNNING
        attempt = 0
        last_error = None
        last_inv: SkillInvocationRecord | None = None
        t0 = time.perf_counter()
        while attempt <= self.max_retries:
            attempt += 1
            try:
                last_inv = registry.invoke(
                    skill_name=skill_name,
                    agent_id=self.worker_id,
                    task_id=task_id,
                    task_version=task_version,
                    trace_id=trace_id,
                    payload=payload,
                    timeout_seconds=self.timeout_seconds,
                )
                if last_inv.status == "success":
                    elapsed = int((time.perf_counter() - t0) * 1000)
                    self.status = WorkerStatus.SUCCESS
                    self.history.append(
                        {
                            "task_id": task_id,
                            "skill": skill_name,
                            "status": "success",
                            "attempts": attempt,
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    return WorkerResult(
                        worker_id=self.worker_id,
                        role=self.role.value,
                        task_id=task_id,
                        skill_name=skill_name,
                        status="success",
                        data=last_inv.output_payload,
                        error=None,
                        duration_ms=elapsed,
                        invocation_record=last_inv,
                    )
                last_error = last_inv.error or "Skill returned non-success"
                if last_inv.status == "timeout":
                    self.status = WorkerStatus.TIMEOUT
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.status = WorkerStatus.FAILED
        elapsed = int((time.perf_counter() - t0) * 1000)
        self.history.append(
            {
                "task_id": task_id,
                "skill": skill_name,
                "status": self.status.value,
                "attempts": attempt,
                "error": last_error,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        return WorkerResult(
            worker_id=self.worker_id,
            role=self.role.value,
            task_id=task_id,
            skill_name=skill_name,
            status=self.status.value,
            data=None,
            error=last_error,
            duration_ms=elapsed,
            invocation_record=last_inv,
        )

    def reset(self) -> None:
        self.status = WorkerStatus.IDLE
        self.assigned_task_id = None


@dataclass
class WorkerPool:
    workers: list[AgentWorker]
    _by_role: dict[WorkerRole, list[AgentWorker]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_role = {}
        for w in self.workers:
            self._by_role.setdefault(w.role, []).append(w)

    def dispatch(
        self,
        role: WorkerRole,
        task_id: str,
        task_version: int,
        trace_id: str,
        skill_name: str,
        payload: dict[str, Any],
        registry: SkillRegistry,
    ) -> WorkerResult:
        candidates = [w for w in self._by_role.get(role, []) if w.can_accept(skill_name)]
        if not candidates:
            raise RuntimeError(f"No worker for role={role.value} skill={skill_name}")
        # Simple load-balancing: pick idle or least-recently-failed
        chosen = min(candidates, key=lambda w: (0 if w.status == WorkerStatus.IDLE else 1))
        return chosen.execute(task_id, task_version, trace_id, skill_name, payload, registry)

    def health(self) -> dict[str, Any]:
        return {
            "total_workers": len(self.workers),
            "by_role": {
                role.value: [w.worker_id for w in workers]
                for role, workers in self._by_role.items()
            },
            "status_summary": {
                w.worker_id: w.status.value for w in self.workers
            },
        }
