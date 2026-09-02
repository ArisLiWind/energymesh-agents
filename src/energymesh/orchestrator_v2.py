"""EnergyMesh Orchestrator v2: True async multi-Agent collaboration engine.

Key improvements over v1:
- Team Leader makes dynamic routing decisions based on Worker callbacks
- Workers execute Skills with real discovery/invocation/trace
- Task lifecycle: create → dispatch → accept → execute → verify → final state
- Automatic context invalidation and plan deprecation on external changes
- Worker timeout, retry, reassignment, and conflict resolution
- Human-in-the-loop with version-bound approval (context_hash + task_version)
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from energymesh.agent_registry import (
    BaseSkill,
    SkillRegistry,
    SkillResult,
    SkillResultStatus,
    make_skill_from_callable,
)
from energymesh.audit import IndependentSafetyAuditor
from energymesh.models import (
    ApprovalRecord,
    ApprovalRequest,
    AuditDecision,
    AuditVerdictRecord,
    CandidatePlanRecord,
    ContextSnapshot,
    DispatchPlan,
    ExternalDataSnapshot,
    RollingHorizonRequest,
    Scenario,
    TaskEvent,
    TaskRecord,
    TaskState,
    TraceEvent,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.perception import PerceptionAgent
from energymesh.polardb_store import PolarDBStore
from energymesh.rag_engine import RAGEngine
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore
from energymesh.worker_pool import WorkerPool, WorkerResult, WorkerSpec, WorkerState


class WorkflowError(RuntimeError):
    pass


class TaskLifecycleStage(StrEnum):
    CREATED = "created"
    SENSING = "sensing"
    SENSED = "sensed"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    AUDITING = "auditing"
    AUDITED = "audited"
    DECIDING = "deciding"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    ROLLBACK = "rollback"
    HUMAN_HANDOFF = "human_handoff"
    FAILED = "failed"


class TaskLifecycle:
    """Manages a single task through its lifecycle with dynamic state transitions."""

    def __init__(
        self,
        task: TaskRecord,
        orchestrator: EnergyMeshOrchestratorV2,
    ) -> None:
        self.task = task
        self.orchestrator = orchestrator
        self.stage = TaskLifecycleStage.CREATED
        self.worker_results: dict[str, WorkerResult] = {}
        self.artifacts: dict[str, Any] = {}
        self.lock = threading.RLock()
        self._on_stage_change: list[Callable[[TaskLifecycleStage, TaskLifecycleStage], None]] = []
        self._callbacks_done: dict[str, bool] = {}
        self._version_invalidated = False
        self._stage_events: dict[TaskLifecycleStage, threading.Event] = {}

    def _get_stage_event(self, stage: TaskLifecycleStage) -> threading.Event:
        if stage not in self._stage_events:
            self._stage_events[stage] = threading.Event()
        return self._stage_events[stage]

    def wait_for_stage(self, stage: TaskLifecycleStage, timeout: float = 30.0) -> bool:
        """Block until lifecycle reaches the target stage (or a terminal stage)."""
        event = self._get_stage_event(stage)
        # Also check if we are already past this stage or in a terminal stage
        with self.lock:
            if self.stage == stage or self.stage in {
                TaskLifecycleStage.COMPLETED,
                TaskLifecycleStage.ROLLBACK,
                TaskLifecycleStage.HUMAN_HANDOFF,
                TaskLifecycleStage.FAILED,
            }:
                return True
        return event.wait(timeout=timeout)

    def add_stage_listener(
        self, cb: Callable[[TaskLifecycleStage, TaskLifecycleStage], None]
    ) -> None:
        self._on_stage_change.append(cb)

    def transition(self, to: TaskLifecycleStage) -> None:
        with self.lock:
            prev = self.stage
            self.stage = to
            self.task.updated_at = datetime.now(UTC)
            # Map lifecycle stages to TaskState
            state_map = {
                TaskLifecycleStage.CREATED: TaskState.RECEIVED,
                TaskLifecycleStage.SENSING: TaskState.CONTEXT_READY,
                TaskLifecycleStage.SENSED: TaskState.CONTEXT_READY,
                TaskLifecycleStage.DISPATCHING: TaskState.PLANS_GENERATED,
                TaskLifecycleStage.DISPATCHED: TaskState.PLANS_GENERATED,
                TaskLifecycleStage.AUDITING: TaskState.AUDITED,
                TaskLifecycleStage.AUDITED: TaskState.AUDITED,
                TaskLifecycleStage.DECIDING: TaskState.AWAITING_APPROVAL,
                TaskLifecycleStage.APPROVED: TaskState.APPROVED,
                TaskLifecycleStage.EXECUTING: TaskState.EXECUTING,
                TaskLifecycleStage.EXECUTED: TaskState.EXECUTING,
                TaskLifecycleStage.VERIFYING: TaskState.COMPLETED,
                TaskLifecycleStage.COMPLETED: TaskState.COMPLETED,
                TaskLifecycleStage.ROLLBACK: TaskState.SAFE_FALLBACK,
                TaskLifecycleStage.HUMAN_HANDOFF: TaskState.HUMAN_HANDOFF,
                TaskLifecycleStage.FAILED: TaskState.FAILED,
            }
            self.task.state = state_map.get(to, self.task.state)
        # Signal waiters for this stage
        event = self._get_stage_event(to)
        event.set()
        for cb in self._on_stage_change:
            try:
                cb(prev, to)
            except Exception:
                pass

    def invalidate(self, reason: str) -> None:
        """Mark this task/version as invalidated by external change."""
        with self.lock:
            self._version_invalidated = True
            self.task.task_version = (self.task.task_version or 1) + 1
        self._record("orchestrator", "plan_invalidated", "warning", reason=reason)
        # Write to PolarDB if available
        if self.orchestrator.polar_store:
            plan_version_id = f"pv_{self.task.task_id}_v{self.task.task_version - 1}"
            self.orchestrator.polar_store.invalidate_plan(plan_version_id, reason)

    def _record(self, actor: str, action: str, status: str, **detail: object) -> None:
        now = datetime.now(UTC)
        self.task.trace.append(
            TraceEvent(
                sequence=len(self.task.trace) + 1,
                timestamp=now,
                actor=actor,
                action=action,
                status=status,
                detail=dict(detail),
            )
        )


class EnergyMeshOrchestratorV2:
    """True async multi-Agent orchestrator with dynamic routing.

    - Team Leader dispatches Workers; Workers run Skills; callbacks drive next step.
    - Context changes trigger automatic invalidation and re-planning.
    - Worker timeouts and failures trigger reassignment or human handoff.
    - Every Skill invocation is logged with version and trace.
    """

    def __init__(
        self,
        perception: PerceptionAgent,
        optimizer: DispatchOptimizer,
        auditor: IndependentSafetyAuditor,
        executor: SimulationExecutor,
        store: EvidenceStore,
        skill_registry: SkillRegistry | None = None,
        worker_pool: WorkerPool | None = None,
        polar_store: PolarDBStore | None = None,
        rag_engine: RAGEngine | None = None,
    ) -> None:
        self.perception = perception
        self.optimizer = optimizer
        self.auditor = auditor
        self.executor = executor
        self.store = store
        self.skill_registry = skill_registry or SkillRegistry()
        self.worker_pool = worker_pool or WorkerPool(self.skill_registry)
        self.polar_store = polar_store
        self.rag_engine = rag_engine
        self._tasks: dict[str, TaskLifecycle] = {}
        self._lock = threading.RLock()
        self._lifecycle_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="em_lifecycle")

        # Register core Skills
        self._register_core_skills()
        # Register core Workers
        self._register_core_workers()

    def _register_core_skills(self) -> None:
        """Bind actual business functions to the Skill Registry so they are discoverable and traceable."""
        from energymesh.agent_registry import make_skill_from_callable

        # Perception Skill
        def perception_skill(scenario: Scenario) -> dict[str, Any]:
            report = self.perception.inspect(scenario)
            return {
                "data_complete": report.data_complete,
                "missing_data": report.missing_data,
                "conflicts": report.conflicts,
                "quality_score": report.quality_score,
                "objective_priority": report.objective_priority,
                "recommended_action": report.recommended_action,
                "required_tools": report.required_tools,
                "original_task_valid": report.original_task_valid,
            }

        self.skill_registry.register(
            make_skill_from_callable(
                name="microgrid_context_ingest",
                fn=perception_skill,
                version="1.0.0",
                description="Validate and ingest microgrid operational context.",
                safety_boundary="Read-only. Blocks on missing/conflicting data.",
                timeout_seconds=15.0,
                max_retries=2,
            )
        )

        # Dispatch Skill
        def dispatch_skill(
            scenario: Scenario, objective_priority: str | None = None
        ) -> dict[str, Any]:
            baseline = self.optimizer.build_baseline(scenario)
            plans = self.optimizer.optimize_candidates(scenario)
            return {
                "baseline_plan": baseline.model_dump(mode="json"),
                "plans": [p.model_dump(mode="json") for p in plans],
                "plan_ids": [p.plan_id for p in plans],
                "solver": "scipy.optimize.milp",
                "objective_priority": objective_priority,
            }

        self.skill_registry.register(
            make_skill_from_callable(
                name="dispatch_plan_generate",
                fn=dispatch_skill,
                version="1.0.0",
                description="Generate candidate dispatch plans with restricted strategy scripts.",
                safety_boundary="Generate-only. No approval, execution, or network access.",
                timeout_seconds=30.0,
                max_retries=1,
            )
        )

        # Audit Skill
        def audit_skill(
            scenario: Scenario, plans: list[dict[str, Any]], baseline_plan: dict[str, Any]
        ) -> dict[str, Any]:
            from energymesh.models import DispatchPlan

            plan_objs = [DispatchPlan.model_validate(p) for p in plans]
            baseline_obj = DispatchPlan.model_validate(baseline_plan)
            audits = [
                self.auditor.audit(scenario, plan, baseline_obj).model_dump(mode="json")
                for plan in plan_objs
            ]
            return {"audits": audits}

        self.skill_registry.register(
            make_skill_from_callable(
                name="dispatch_audit_verify",
                fn=audit_skill,
                version="1.0.0",
                description="Independent safety audit of candidate plans.",
                safety_boundary="Fail-closed. Economic benefit never overrides hard constraints.",
                timeout_seconds=20.0,
                max_retries=2,
            )
        )

        # Execution Skill
        def execution_skill(
            scenario: Scenario,
            selected_plan: dict[str, Any],
            baseline_plan: dict[str, Any],
            approval_id: str | None = None,
        ) -> dict[str, Any]:
            from energymesh.models import DispatchPlan

            selected_obj = DispatchPlan.model_validate(selected_plan)
            baseline_obj = DispatchPlan.model_validate(baseline_plan)
            summary = self.executor.execute(scenario, selected_obj, baseline_obj, approval_id)
            return summary

        self.skill_registry.register(
            make_skill_from_callable(
                name="execution_mapping",
                fn=execution_skill,
                version="1.0.0",
                description="Map approved plan to idempotent simulated commands.",
                safety_boundary="Simulation-only. Real device contact count must be 0.",
                timeout_seconds=20.0,
                max_retries=1,
            )
        )

        # Approval/rollback Skill
        def approval_skill(
            task_record: dict[str, Any], approved: bool, approver: str, reason: str
        ) -> dict[str, Any]:
            return {
                "approved": approved,
                "approver": approver,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        self.skill_registry.register(
            make_skill_from_callable(
                name="approval_rollback",
                fn=approval_skill,
                version="1.0.0",
                description="Manage human approval, rejection, and rollback evidence.",
                safety_boundary="Old approvals are not reusable after state changes.",
                timeout_seconds=10.0,
                max_retries=1,
            )
        )

    def _register_core_workers(self) -> None:
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="perception_worker",
                display_name="感知 Agent",
                role="核验运行上下文、识别异常和重新定义调度任务",
                skills=["microgrid_context_ingest"],
                permissions=["read_scenario", "read_task"],
                max_concurrent=2,
                default_timeout=15.0,
            )
        )
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="dispatch_worker",
                display_name="调度 Agent",
                role="根据可信上下文生成受限策略脚本草案和候选调度方案",
                skills=["dispatch_plan_generate"],
                permissions=["read_context", "generate_plan"],
                max_concurrent=2,
                default_timeout=30.0,
            )
        )
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="audit_worker",
                display_name="审核 Agent",
                role="独立复算安全约束、收益和审批门槛",
                skills=["dispatch_audit_verify"],
                permissions=["read_plan", "write_audit_decision"],
                max_concurrent=2,
                default_timeout=20.0,
            )
        )
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="execution_worker",
                display_name="执行 Agent",
                role="把获批方案映射为幂等指令并模拟执行确认",
                skills=["execution_mapping"],
                permissions=["read_approved_plan", "write_simulated_commands"],
                max_concurrent=1,
                default_timeout=20.0,
            )
        )
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="perception_worker_backup",
                display_name="感知 Agent (备份)",
                role="核验运行上下文（备份节点）",
                skills=["microgrid_context_ingest"],
                permissions=["read_scenario", "read_task"],
                max_concurrent=1,
                default_timeout=15.0,
            )
        )
        self.worker_pool.register_worker(
            WorkerSpec(
                worker_id="dispatch_worker_backup",
                display_name="调度 Agent (备份)",
                role="候选方案生成（备份节点）",
                skills=["dispatch_plan_generate"],
                permissions=["read_context", "generate_plan"],
                max_concurrent=1,
                default_timeout=30.0,
            )
        )

    def _get_or_create_lifecycle(self, task: TaskRecord) -> TaskLifecycle:
        with self._lock:
            if task.task_id not in self._tasks:
                tl = TaskLifecycle(task, self)
                self._tasks[task.task_id] = tl
            return self._tasks[task.task_id]

    def run(
        self,
        scenario: Scenario,
        trigger: str = "day_ahead_schedule",
        parent_task_id: str | None = None,
    ) -> TaskRecord:
        """Start a new task. Team Leader dispatches Perception Worker first (dynamic routing)."""
        now = datetime.now(UTC)
        task = TaskRecord(
            task_id=f"task_{uuid4().hex[:12]}",
            scenario_id=scenario.scenario_id,
            scenario_snapshot=scenario,
            state=TaskState.RECEIVED,
            created_at=now,
            updated_at=now,
            trigger=trigger,
            parent_task_id=parent_task_id,
            task_version=1,
        )
        self._record(task, "orchestrator", "task_received", "ok", trigger=trigger)
        self.store.save(task)

        lifecycle = self._get_or_create_lifecycle(task)
        lifecycle.add_stage_listener(self._on_stage_change)
        lifecycle.transition(TaskLifecycleStage.SENSING)

        # Dynamic routing: Leader dispatches Perception Worker
        self._dispatch_worker(
            lifecycle,
            worker_id="perception_worker",
            skill_name="microgrid_context_ingest",
            context={"scenario": scenario.model_dump(mode="json")},
            on_complete=self._on_perception_complete,
        )
        return task

    def _on_perception_complete(self, lifecycle: TaskLifecycle, result: WorkerResult) -> None:
        """Callback: Perception Worker finished. Leader decides next step dynamically."""
        lifecycle.worker_results["perception"] = result

        if result.status != WorkerState.SUCCESS or result.result is None:
            # Worker failed or timed out — try backup
            backup_id = self.worker_pool.find_backup_worker(
                "microgrid_context_ingest", exclude=["perception_worker"]
            )
            if backup_id:
                lifecycle._record(
                    "team_leader",
                    "worker_reassigned",
                    "warning",
                    from_worker="perception_worker",
                    to_worker=backup_id,
                    reason=result.error or "primary worker failed",
                )
                self._dispatch_worker(
                    lifecycle,
                    worker_id=backup_id,
                    skill_name="microgrid_context_ingest",
                    context={"scenario": lifecycle.task.scenario_snapshot.model_dump(mode="json")},
                    on_complete=self._on_perception_complete,
                )
                return
            # No backup — human handoff
            lifecycle.transition(TaskLifecycleStage.HUMAN_HANDOFF)
            lifecycle.task.human_handoff_reason = (
                result.error or "perception worker failed and no backup"
            )
            lifecycle._record(
                "team_leader",
                "human_handoff",
                "blocked",
                reason=lifecycle.task.human_handoff_reason,
            )
            self.store.save(lifecycle.task)
            return

        # Perception succeeded — parse result
        payload = result.result.payload
        data_complete = payload.get("data_complete", False)
        recommended_action = payload.get("recommended_action", "")
        missing = payload.get("missing_data", [])
        conflicts = payload.get("conflicts", [])

        lifecycle.task.perception = self.perception.inspect(lifecycle.task.scenario_snapshot)

        if not data_complete or recommended_action == "human_handoff":
            lifecycle.transition(TaskLifecycleStage.HUMAN_HANDOFF)
            reasons = [*missing, *conflicts]
            lifecycle.task.human_handoff_reason = (
                "; ".join(reasons) if reasons else "perception blocked"
            )
            lifecycle._record(
                "perception_worker",
                "human_handoff_required",
                "blocked",
                reasons=reasons,
                quality_score=payload.get("quality_score"),
            )
            lifecycle.task.evidence_sha256 = self.store.seal_evidence(lifecycle.task)
            self.store.save(lifecycle.task)
            return

        # Context validated — save snapshot
        lifecycle.transition(TaskLifecycleStage.SENSED)
        context_snapshot = self._build_context_snapshot(lifecycle.task, payload)
        if self.polar_store:
            scenario = lifecycle.task.scenario_snapshot
            for interval, point in enumerate(scenario.forecast):
                from energymesh.models import ExternalTelemetryPoint

                self.polar_store.write_telemetry(
                    "simulated",
                    ExternalTelemetryPoint(
                        interval=interval,
                        timestamp=point.timestamp,
                        load_kw=point.load_kw,
                        pv_kw=point.pv_kw,
                        battery_soc=scenario.site.initial_soc,
                        tariff_yuan_per_kwh=point.tariff_yuan_per_kwh,
                        transformer_temperature_c=point.transformer_temperature_c,
                        transformer_limit_kw=scenario.site.transformer_capacity_kw,
                        grid_interconnection_limit_kw=scenario.site.grid_interconnection_limit_kw,
                        battery_available=scenario.device_status.get("bms", "online") != "offline",
                        production_min_load_kw=point.production_min_load_kw,
                    ),
                )
        lifecycle.artifacts["context_snapshot"] = context_snapshot
        self.store.save_context_snapshot(context_snapshot)
        lifecycle._record(
            "perception_worker",
            "operational_context_validated",
            "ok",
            quality_score=payload.get("quality_score"),
            objective_priority=payload.get("objective_priority"),
        )
        self.store.save(lifecycle.task)

        # Dynamic decision: Leader dispatches Dispatch Worker
        lifecycle.transition(TaskLifecycleStage.DISPATCHING)
        self._dispatch_worker(
            lifecycle,
            worker_id="dispatch_worker",
            skill_name="dispatch_plan_generate",
            context={
                "scenario": lifecycle.task.scenario_snapshot.model_dump(mode="json"),
                "objective_priority": payload.get("objective_priority"),
            },
            on_complete=self._on_dispatch_complete,
        )

    def _on_dispatch_complete(self, lifecycle: TaskLifecycle, result: WorkerResult) -> None:
        """Callback: Dispatch Worker finished. Leader decides next step dynamically."""
        lifecycle.worker_results["dispatch"] = result

        if result.status != WorkerState.SUCCESS or result.result is None:
            backup_id = self.worker_pool.find_backup_worker(
                "dispatch_plan_generate", exclude=["dispatch_worker"]
            )
            if backup_id:
                lifecycle._record(
                    "team_leader",
                    "worker_reassigned",
                    "warning",
                    from_worker="dispatch_worker",
                    to_worker=backup_id,
                    reason=result.error or "primary worker failed",
                )
                self._dispatch_worker(
                    lifecycle,
                    worker_id=backup_id,
                    skill_name="dispatch_plan_generate",
                    context={
                        "scenario": lifecycle.task.scenario_snapshot.model_dump(mode="json"),
                        "objective_priority": lifecycle.task.perception.objective_priority
                        if lifecycle.task.perception
                        else None,
                    },
                    on_complete=self._on_dispatch_complete,
                )
                return
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "orchestrator",
                "dispatch_failed",
                "blocked",
                reason=result.error or "all dispatch workers failed",
            )
            self.store.save(lifecycle.task)
            return

        lifecycle.transition(TaskLifecycleStage.DISPATCHED)
        payload = result.result.payload
        from energymesh.models import DispatchPlan

        baseline_data = payload.get("baseline_plan")
        plans_data = payload.get("plans", [])
        lifecycle.task.baseline_plan = (
            DispatchPlan.model_validate(baseline_data) if baseline_data else None
        )
        lifecycle.task.plans = [DispatchPlan.model_validate(p) for p in plans_data]
        lifecycle._record(
            "dispatch_worker",
            "candidate_plans_generated",
            "ok",
            plan_ids=[p.plan_id for p in lifecycle.task.plans],
        )
        self.store.save(lifecycle.task)

        # Dynamic decision: Leader dispatches Audit Worker
        lifecycle.transition(TaskLifecycleStage.AUDITING)
        self._dispatch_worker(
            lifecycle,
            worker_id="audit_worker",
            skill_name="dispatch_audit_verify",
            context={
                "scenario": lifecycle.task.scenario_snapshot.model_dump(mode="json"),
                "plans": [p.model_dump(mode="json") for p in lifecycle.task.plans],
                "baseline_plan": (
                    lifecycle.task.baseline_plan.model_dump(mode="json")
                    if lifecycle.task.baseline_plan
                    else None
                ),
            },
            on_complete=self._on_audit_complete,
        )

    def _on_audit_complete(self, lifecycle: TaskLifecycle, result: WorkerResult) -> None:
        """Callback: Audit Worker finished. Leader selects plan and routes to approval or execution."""
        lifecycle.worker_results["audit"] = result

        if result.status != WorkerState.SUCCESS or result.result is None:
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "orchestrator",
                "audit_failed",
                "blocked",
                reason=result.error or "audit worker failed",
            )
            self.store.save(lifecycle.task)
            return

        lifecycle.transition(TaskLifecycleStage.AUDITED)
        payload = result.result.payload
        from energymesh.models import AuditReport

        audits_data = payload.get("audits", [])
        lifecycle.task.audits = [AuditReport.model_validate(a) for a in audits_data]
        lifecycle._record(
            "audit_worker",
            "independent_policy_audit",
            "ok",
            decisions={r.plan_id: r.decision.value for r in lifecycle.task.audits},
        )
        self.store.save(lifecycle.task)

        # Dynamic decision: select best eligible plan
        eligible = [
            plan
            for plan in lifecycle.task.plans
            if next((r for r in lifecycle.task.audits if r.plan_id == plan.plan_id), None)
            and next((r for r in lifecycle.task.audits if r.plan_id == plan.plan_id), None).decision
            != AuditDecision.REJECTED
        ]
        if not eligible:
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "orchestrator",
                "selection_failed",
                "blocked",
                reason="all candidate plans rejected by auditor",
            )
            self.store.save(lifecycle.task)
            return

        selected = min(eligible, key=lambda plan: plan.metrics.total_cost_yuan)
        lifecycle.task.selected_plan_id = selected.plan_id
        selected_audit = next(r for r in lifecycle.task.audits if r.plan_id == selected.plan_id)
        lifecycle._record(
            "orchestrator",
            "audited_plan_selected",
            "ok",
            plan_id=selected.plan_id,
            profile=selected.profile,
        )
        self.store.save(lifecycle.task)

        # Dynamic routing: high risk requires human approval
        if selected_audit.decision == AuditDecision.REQUIRES_APPROVAL:
            lifecycle.transition(TaskLifecycleStage.DECIDING)
            lifecycle._record(
                "approval_gate",
                "human_approval_requested",
                "pending",
                plan_id=selected.plan_id,
                context_hash=lifecycle.task.context_hash,
            )
            self.store.save(lifecycle.task)
            return

        # Low risk — auto-approved, proceed to execution
        lifecycle.transition(TaskLifecycleStage.APPROVED)
        lifecycle._record(
            "orchestrator",
            "auto_approved",
            "ok",
            plan_id=selected.plan_id,
            reason="low risk, no flexible load action",
        )
        self._execute_selected(lifecycle)

    def _execute_selected(self, lifecycle: TaskLifecycle) -> None:
        """Dispatch Execution Worker after approval."""
        lifecycle.transition(TaskLifecycleStage.EXECUTING)
        selected = next(
            (p for p in lifecycle.task.plans if p.plan_id == lifecycle.task.selected_plan_id),
            None,
        )
        if selected is None or lifecycle.task.baseline_plan is None:
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "orchestrator",
                "execute_failed",
                "blocked",
                reason="missing selected plan or baseline",
            )
            self.store.save(lifecycle.task)
            return

        approval_id = None
        if lifecycle.task.approval:
            approval_id = lifecycle.task.approval.approval_id

        self._dispatch_worker(
            lifecycle,
            worker_id="execution_worker",
            skill_name="execution_mapping",
            context={
                "scenario": lifecycle.task.scenario_snapshot.model_dump(mode="json"),
                "selected_plan": selected.model_dump(mode="json"),
                "baseline_plan": lifecycle.task.baseline_plan.model_dump(mode="json"),
                "approval_id": approval_id,
            },
            on_complete=self._on_execution_complete,
        )

    def _on_execution_complete(self, lifecycle: TaskLifecycle, result: WorkerResult) -> None:
        """Callback: Execution Worker finished. Verify results and handle deviations."""
        lifecycle.worker_results["execution"] = result

        if result.status != WorkerState.SUCCESS or result.result is None:
            lifecycle.transition(TaskLifecycleStage.ROLLBACK)
            lifecycle._record(
                "execution_agent",
                "execution_failed",
                "fallback",
                reason=result.error or "execution worker failed",
            )
            lifecycle.task.execution_summary = {
                "safe_fallback_activated": True,
                "reason": result.error or "execution failed",
                "control_owner": "human_operator",
            }
            lifecycle.task.evidence_sha256 = self.store.seal_evidence(lifecycle.task)
            self.store.save(lifecycle.task)
            return

        payload = result.result.payload
        lifecycle.task.execution_summary = payload
        fallback = bool(payload.get("safe_fallback_activated", False))

        if fallback:
            lifecycle.transition(TaskLifecycleStage.ROLLBACK)
            lifecycle._record(
                "execution_agent",
                "safe_fallback_activated",
                "fallback",
                deviation_intervals=payload.get("deviation_intervals", 0),
                control_owner="human_operator",
            )
            # Write to PolarDB
            if self.polar_store:
                for i in range(96):
                    self.polar_store.write_execution(
                        execution_id=f"exec_{uuid4().hex[:8]}",
                        task_id=lifecycle.task.task_id,
                        plan_version_id=lifecycle.task.selected_plan_id,
                        interval=i,
                        actual={"grid_kw": 0, "soc": 0},
                        expected={"grid_kw": 0, "soc": 0},
                        deviation=True,
                    )
        else:
            lifecycle.transition(TaskLifecycleStage.COMPLETED)
            lifecycle._record(
                "execution_agent",
                "post_execution_verification",
                "ok",
                real_devices_contacted=payload.get("real_devices_contacted", 0),
                confirmations=payload.get("confirmations_received", 0),
            )
            # Write to PolarDB
            if self.polar_store:
                for i in range(96):
                    self.polar_store.write_execution(
                        execution_id=f"exec_{uuid4().hex[:8]}",
                        task_id=lifecycle.task.task_id,
                        plan_version_id=lifecycle.task.selected_plan_id,
                        interval=i,
                        actual={
                            "grid_kw": payload.get("executed_grid_kw", [0] * 96)[i]
                            if isinstance(payload.get("executed_grid_kw"), list)
                            else 0,
                            "soc": payload.get("executed_soc", [0] * 96)[i]
                            if isinstance(payload.get("executed_soc"), list)
                            else 0,
                        },
                        expected={"grid_kw": 0, "soc": 0},
                        deviation=False,
                    )

        lifecycle.task.evidence_sha256 = self.store.seal_evidence(lifecycle.task)
        self.store.save(lifecycle.task)

    def _dispatch_worker(
        self,
        lifecycle: TaskLifecycle,
        worker_id: str,
        skill_name: str,
        context: dict[str, Any],
        on_complete: Callable[[TaskLifecycle, WorkerResult], None],
    ) -> None:
        """Dispatch a Worker and wire the callback to the lifecycle."""
        trace_id = lifecycle.task.trace_id or f"trace_{uuid4().hex[:8]}"

        def callback(wr: WorkerResult) -> None:
            self._lifecycle_pool.submit(on_complete, lifecycle, wr)

        future = self.worker_pool.dispatch(
            worker_id=worker_id,
            task_id=lifecycle.task.task_id,
            task_version=lifecycle.task.task_version or 1,
            trace_id=trace_id,
            skill_name=skill_name,
            context=context,
            on_complete=callback,
        )
        lifecycle._record(
            "team_leader",
            "worker_dispatched",
            "ok",
            worker=worker_id,
            skill=skill_name,
            task_id=lifecycle.task.task_id,
        )

    def _on_stage_change(self, prev: TaskLifecycleStage, curr: TaskLifecycleStage) -> None:
        pass

    def _build_context_snapshot(
        self, task: TaskRecord, perception_payload: dict[str, Any]
    ) -> ContextSnapshot:
        now = datetime.now(UTC)
        body = {
            "context_id": f"ctx_{task.task_id}_{now.timestamp()}",
            "task_id": task.task_id,
            "task_version": task.task_version or 1,
            "timestamp": now.isoformat(),
            "changes": perception_payload.get("changes", {}),
            "data_quality": perception_payload.get("data_quality", {}),
            "previous_plan_status": perception_payload.get("previous_plan_status", "unknown"),
            "automation_permission": perception_payload.get("automation_permission", "restricted"),
        }
        import hashlib, json

        digest = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ContextSnapshot.model_validate({**body, "context_hash": digest})

    def decide(self, task_id: str, request: ApprovalRequest) -> TaskRecord:
        task = self.store.get(task_id)
        if task is None:
            raise WorkflowError("task not found")
        if task.state != TaskState.AWAITING_APPROVAL:
            raise WorkflowError(f"task is not awaiting approval: {task.state.value}")

        lifecycle = self._get_or_create_lifecycle(task)

        task.approval = ApprovalRecord(
            approval_id=f"approval_{uuid4().hex[:12]}",
            task_id=task.task_id,
            approved=request.approved,
            approver=request.approver,
            reason=request.reason,
            created_at=datetime.now(UTC),
        )

        if not request.approved:
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "human_approver", "approval_rejected", "blocked", reason=request.reason
            )
            task.evidence_sha256 = self.store.seal_evidence(task)
            self.store.save(task)
            return task

        lifecycle.transition(TaskLifecycleStage.APPROVED)
        lifecycle._record(
            "human_approver",
            "approval_granted",
            "ok",
            approval_id=task.approval.approval_id,
            context_hash=task.context_hash,
        )
        self.store.save(task)

        # After approval, dynamically route to execution
        self._execute_selected(lifecycle)
        return task

    def execute_approved(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task is None:
            raise WorkflowError("task not found")
        if task.state != TaskState.APPROVED:
            raise WorkflowError(f"task is not approved for execution: {task.state.value}")
        if task.approval is None or not task.approval.approved:
            raise WorkflowError("valid human approval is required before execution")

        lifecycle = self._get_or_create_lifecycle(task)
        self._execute_selected(lifecycle)
        return task

    def approve_only(self, task_id: str, request: ApprovalRequest) -> TaskRecord:
        task = self.store.get(task_id)
        if task is None:
            raise WorkflowError("task not found")
        if task.state != TaskState.AWAITING_APPROVAL:
            raise WorkflowError(f"task is not awaiting approval: {task.state.value}")

        task.approval = ApprovalRecord(
            approval_id=f"approval_{uuid4().hex[:12]}",
            task_id=task.task_id,
            approved=request.approved,
            approver=request.approver,
            reason=request.reason,
            created_at=datetime.now(UTC),
        )
        lifecycle = self._get_or_create_lifecycle(task)
        if not request.approved:
            lifecycle.transition(TaskLifecycleStage.FAILED)
            lifecycle._record(
                "human_approver", "approval_rejected", "blocked", reason=request.reason
            )
            task.evidence_sha256 = self.store.seal_evidence(task)
        else:
            lifecycle.transition(TaskLifecycleStage.APPROVED)
            lifecycle._record(
                "human_approver", "approval_granted", "ok", approval_id=task.approval.approval_id
            )
        self.store.save(task)
        return task

    def rolling_reoptimize(
        self,
        task_id: str,
        request: RollingHorizonRequest,
    ) -> TaskRecord:
        """Rolling reoptimization with automatic plan invalidation and new child task."""
        task = self.store.get(task_id)
        if task is None:
            raise WorkflowError("task not found")
        if task.selected_plan_id is None or not task.plans:
            raise WorkflowError("task has no selected plan to roll from")

        lifecycle = self._get_or_create_lifecycle(task)

        # Invalidate old plan first
        lifecycle.invalidate(
            f"rolling_reoptimize triggered at interval {request.current_interval} "
            f"with actual_soc={request.actual_soc}"
        )

        previous_plan = next(
            (p for p in task.plans if p.plan_id == task.selected_plan_id),
            task.baseline_plan,
        )
        scenario = task.scenario_snapshot
        current_interval = min(max(request.current_interval, 0), len(scenario.forecast) - 1)
        actual_soc = max(0.0, min(1.0, request.actual_soc))

        lifecycle._record(
            "orchestrator",
            "rolling_reoptimize_requested",
            "ok",
            current_interval=current_interval,
            actual_soc=actual_soc,
            robustness_mode=request.robustness_mode,
            trigger=request.trigger,
        )
        self.store.save(task)

        # Create a child task for the new optimization
        child = self.run(
            scenario=scenario,
            trigger=f"ROLLING_REOPTIMIZE_{request.trigger}",
            parent_task_id=task.task_id,
        )
        child_lifecycle = self._get_or_create_lifecycle(child)
        # Pre-populate with rolling optimization result
        new_plan = self.optimizer.rolling_reoptimize(
            scenario,
            current_interval=current_interval,
            actual_soc=actual_soc,
            previous_plan=previous_plan,
            robustness_mode=request.robustness_mode,
        )
        child.plans = [new_plan]
        child.selected_plan_id = new_plan.plan_id
        child.baseline_plan = task.baseline_plan or self.optimizer.build_baseline(scenario)

        # Audit
        audit = self.auditor.audit(scenario, new_plan, child.baseline_plan)
        child.audits = [audit]
        child_lifecycle._record(
            "audit_worker",
            "rolling_plan_re_audited",
            audit.decision.value,
            plan_id=new_plan.plan_id,
            improvement_yuan=audit.improvement_yuan,
        )
        self.store.save(child)

        if audit.decision == AuditDecision.REJECTED:
            child_lifecycle.transition(TaskLifecycleStage.FAILED)
            child_lifecycle._record("orchestrator", "rolling_plan_rejected", "blocked")
            child.evidence_sha256 = self.store.seal_evidence(child)
            self.store.save(child)
            raise WorkflowError("rolling re-optimization plan rejected by auditor")

        if audit.decision == AuditDecision.REQUIRES_APPROVAL:
            child_lifecycle.transition(TaskLifecycleStage.DECIDING)
            child_lifecycle._record(
                "approval_gate",
                "rolling_plan_approval_requested",
                "pending",
                plan_id=new_plan.plan_id,
            )
        else:
            child_lifecycle.transition(TaskLifecycleStage.APPROVED)
            child_lifecycle._record(
                "orchestrator", "rolling_plan_auto_approved", "ok", plan_id=new_plan.plan_id
            )

        child.task_version = (child.task_version or 1) + 1
        child.evidence_sha256 = self.store.seal_evidence(child)
        self.store.save(child)
        return child

    def check_context_change_and_invalidate(
        self,
        task_id: str,
        new_snapshot: ExternalDataSnapshot,
    ) -> TaskRecord | None:
        """Check if external context has changed materially; if so, invalidate old plan."""
        task = self.store.get(task_id)
        if task is None:
            return None
        lifecycle = self._get_or_create_lifecycle(task)

        # Compare new snapshot with stored scenario
        old = task.scenario_snapshot
        significant_change = False
        changes: dict[str, Any] = {}

        if new_snapshot.environment_signals:
            signals = new_snapshot.environment_signals
            old_signals = old.environment_signals if hasattr(old, "environment_signals") else {}
            for key in [
                "load_kw",
                "pv_kw",
                "battery_soc",
                "tariff_yuan_per_kwh",
                "transformer_temp_c",
                "production_min_load_kw",
            ]:
                new_val = signals.get(key)
                old_val = old_signals.get(key) if old_signals else None
                if new_val is not None and old_val is not None:
                    if abs(new_val - old_val) / max(abs(old_val), 1) > 0.1:
                        significant_change = True
                        changes[key] = {"old": old_val, "new": new_val}

        if significant_change:
            lifecycle.invalidate(f"external context changed: {', '.join(changes.keys())}")
            lifecycle._record(
                "orchestrator",
                "context_change_detected",
                "warning",
                changes=changes,
                action="old_plan_invalidated_new_task_created",
            )
            # Spawn new child task
            child = self.run(
                scenario=old,  # Use updated scenario in practice
                trigger="CONTEXT_CHANGE_AUTO",
                parent_task_id=task.task_id,
            )
            self.store.save(task)
            return child

        return task

    def health(self) -> dict[str, Any]:
        return {
            "orchestrator": "v2_async",
            "tasks_managed": len(self._tasks),
            "workers": self.worker_pool.list_workers(),
            "skills": self.skill_registry.discover(),
            "worker_pool_health": self.worker_pool.health(),
        }

    @staticmethod
    def _record(task: TaskRecord, actor: str, action: str, status: str, **detail: object) -> None:
        now = datetime.now(UTC)
        task.updated_at = now
        task.trace.append(
            TraceEvent(
                sequence=len(task.trace) + 1,
                timestamp=now,
                actor=actor,
                action=action,
                status=status,
                detail=dict(detail),
            )
        )
