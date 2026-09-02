"""Asynchronous Worker Pool for AgentTeams.

Workers receive tasks, execute Skills with timeouts and retries, and report back
via callbacks. The Team Leader makes dynamic routing decisions based on Worker results.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from energymesh.agent_registry import SkillRegistry, SkillResult, SkillResultStatus
from energymesh.models import AgentHandoff, SkillInvocation, TaskEvent


class WorkerState(StrEnum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REASSIGNED = "reassigned"


@dataclass
class WorkerTask:
    task_id: str
    task_version: int
    trace_id: str
    worker_id: str
    skill_name: str
    context: dict[str, Any]
    assigned_at: datetime
    deadline_seconds: float = 30.0
    attempt: int = 1
    max_attempts: int = 3


@dataclass
class WorkerResult:
    worker_id: str
    task_id: str
    task_version: int
    skill_name: str
    status: WorkerState
    result: SkillResult | None = None
    error: str | None = None
    duration_ms: float = 0.0
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reassigned_to: str | None = None


@dataclass
class WorkerSpec:
    worker_id: str
    display_name: str
    role: str
    skills: list[str]
    permissions: list[str]
    max_concurrent: int = 1
    default_timeout: float = 30.0


class WorkerPool:
    """Pool of Workers that execute Skills asynchronously.

    - Team Leader dispatches tasks to Workers
    - Workers execute Skills with timeout and retry
    - Failed tasks can be reassigned to backup Workers
    - All state transitions are recorded as Handoff and Event traces
    """

    def __init__(self, registry: SkillRegistry, max_workers: int = 8) -> None:
        self.registry = registry
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="em_worker")
        self._workers: dict[str, WorkerSpec] = {}
        self._busy: dict[str, WorkerTask | None] = {}
        self._results: dict[str, list[WorkerResult]] = {}
        self._callbacks: list[Callable[[WorkerResult], None]] = []
        self._lock = threading.RLock()
        self._shutdown = False

    def register_worker(self, spec: WorkerSpec) -> None:
        with self._lock:
            self._workers[spec.worker_id] = spec
            self._busy[spec.worker_id] = None
            if spec.worker_id not in self._results:
                self._results[spec.worker_id] = []

    def list_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "worker_id": wid,
                    "display_name": spec.display_name,
                    "state": (
                        "busy"
                        if self._busy.get(wid) is not None
                        else "idle"
                    ),
                    "skills": spec.skills,
                }
                for wid, spec in self._workers.items()
            ]

    def dispatch(
        self,
        worker_id: str,
        task_id: str,
        task_version: int,
        trace_id: str,
        skill_name: str,
        context: dict[str, Any],
        timeout_seconds: float | None = None,
        on_complete: Callable[[WorkerResult], None] | None = None,
    ) -> Future[WorkerResult]:
        """Assign a Skill task to a Worker and return a Future.

        If the Worker is busy or fails, the task can be reassigned.
        """
        with self._lock:
            if self._shutdown:
                raise RuntimeError("WorkerPool is shut down")
            spec = self._workers.get(worker_id)
            if spec is None:
                raise ValueError(f"Worker '{worker_id}' not registered")

            effective_timeout = timeout_seconds or spec.default_timeout
            wt = WorkerTask(
                task_id=task_id,
                task_version=task_version,
                trace_id=trace_id,
                worker_id=worker_id,
                skill_name=skill_name,
                context=context,
                assigned_at=datetime.now(UTC),
                deadline_seconds=effective_timeout,
                attempt=1,
                max_attempts=spec.max_concurrent * 2,
            )
            self._busy[worker_id] = wt

        future: Future[WorkerResult] = self._executor.submit(
            self._execute_skill, wt
        )
        if on_complete:
            future.add_done_callback(
                lambda f: on_complete(f.result()) if not f.exception() else on_complete(
                    WorkerResult(
                        worker_id=worker_id,
                        task_id=task_id,
                        task_version=task_version,
                        skill_name=skill_name,
                        status=WorkerState.FAILED,
                        error=str(f.exception()),
                    )
                )
            )
        return future

    def _execute_skill(self, wt: WorkerTask) -> WorkerResult:
        started = datetime.now(UTC)
        try:
            result = self.registry.invoke(
                name=wt.skill_name,
                agent_id=wt.worker_id,
                context=wt.context,
                task_id=wt.task_id,
                task_version=wt.task_version,
                trace_id=wt.trace_id,
            )
            duration = (datetime.now(UTC) - started).total_seconds() * 1000
            with self._lock:
                self._busy[wt.worker_id] = None
            wr = WorkerResult(
                worker_id=wt.worker_id,
                task_id=wt.task_id,
                task_version=wt.task_version,
                skill_name=wt.skill_name,
                status=WorkerState.SUCCESS,
                result=result,
                duration_ms=duration,
            )
            self._record_result(wr)
            return wr
        except TimeoutError as e:
            duration = (datetime.now(UTC) - started).total_seconds() * 1000
            with self._lock:
                self._busy[wt.worker_id] = None
            wr = WorkerResult(
                worker_id=wt.worker_id,
                task_id=wt.task_id,
                task_version=wt.task_version,
                skill_name=wt.skill_name,
                status=WorkerState.TIMEOUT,
                error=f"Timeout after {wt.deadline_seconds}s: {e}",
                duration_ms=duration,
            )
            self._record_result(wr)
            return wr
        except Exception as e:
            duration = (datetime.now(UTC) - started).total_seconds() * 1000
            with self._lock:
                self._busy[wt.worker_id] = None
            wr = WorkerResult(
                worker_id=wt.worker_id,
                task_id=wt.task_id,
                task_version=wt.task_version,
                skill_name=wt.skill_name,
                status=WorkerState.FAILED,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )
            self._record_result(wr)
            return wr

    def _record_result(self, wr: WorkerResult) -> None:
        with self._lock:
            if wr.worker_id not in self._results:
                self._results[wr.worker_id] = []
            self._results[wr.worker_id].append(wr)
        for cb in self._callbacks:
            try:
                cb(wr)
            except Exception:
                pass

    def add_callback(self, cb: Callable[[WorkerResult], None]) -> None:
        self._callbacks.append(cb)

    def get_results(self, task_id: str) -> list[WorkerResult]:
        with self._lock:
            return [
                wr
                for results in self._results.values()
                for wr in results
                if wr.task_id == task_id
            ]

    def find_backup_worker(self, skill_name: str, exclude: list[str]) -> str | None:
        """Find an idle Worker that has the requested Skill."""
        with self._lock:
            for wid, spec in self._workers.items():
                if wid in exclude:
                    continue
                if skill_name not in spec.skills:
                    continue
                if self._busy.get(wid) is None:
                    return wid
        return None

    def reassign(
        self,
        failed_result: WorkerResult,
        new_worker_id: str | None = None,
        on_complete: Callable[[WorkerResult], None] | None = None,
    ) -> Future[WorkerResult] | None:
        """Reassign a failed task to a backup Worker."""
        if new_worker_id is None:
            new_worker_id = self.find_backup_worker(
                failed_result.skill_name, exclude=[failed_result.worker_id]
            )
        if new_worker_id is None:
            return None
        return self.dispatch(
            worker_id=new_worker_id,
            task_id=failed_result.task_id,
            task_version=failed_result.task_version,
            trace_id=f"reassign_{uuid4().hex[:8]}",
            skill_name=failed_result.skill_name,
            context={},
            on_complete=on_complete,
        )

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
        self._executor.shutdown(wait=True)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "workers_total": len(self._workers),
                "workers_busy": sum(1 for v in self._busy.values() if v is not None),
                "workers_idle": sum(1 for v in self._busy.values() if v is None),
                "results_recorded": sum(len(v) for v in self._results.values()),
            }
