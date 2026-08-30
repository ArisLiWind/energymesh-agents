from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from energymesh.agentteams import actor_to_worker
from energymesh.audit import IndependentSafetyAuditor
from energymesh.models import (
    ApprovalRecord,
    ApprovalRequest,
    AuditDecision,
    Scenario,
    TaskRecord,
    TaskState,
    TraceEvent,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore


class WorkflowError(RuntimeError):
    pass


class EnergyMeshOrchestrator:
    def __init__(
        self,
        perception: PerceptionAgent,
        optimizer: DispatchOptimizer,
        auditor: IndependentSafetyAuditor,
        executor: SimulationExecutor,
        store: EvidenceStore,
    ) -> None:
        self.perception = perception
        self.optimizer = optimizer
        self.auditor = auditor
        self.executor = executor
        self.store = store

    @staticmethod
    def _record(task: TaskRecord, actor: str, action: str, status: str, **detail: object) -> None:
        now = datetime.now(UTC)
        agentteams_worker = actor_to_worker(actor)
        if agentteams_worker is not None:
            detail = {**detail, "agentteams_worker": agentteams_worker}
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

    def run(
        self,
        scenario: Scenario,
        trigger: str = "day_ahead_schedule",
        parent_task_id: str | None = None,
    ) -> TaskRecord:
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
        )
        self._record(task, "orchestrator", "task_received", "ok", trigger=trigger)
        self.store.save(task)

        task.perception = self.perception.inspect(scenario)
        if (
            not task.perception.data_complete
            or task.perception.recommended_action == "human_handoff"
        ):
            task.state = TaskState.HUMAN_HANDOFF
            reasons = [*task.perception.missing_data, *task.perception.conflicts]
            task.human_handoff_reason = "; ".join(reasons)
            self._record(
                task,
                "perception_agent",
                "human_handoff_required",
                "blocked",
                reasons=reasons,
            )
            task.evidence_sha256 = self.store.seal_evidence(task)
            self.store.save(task)
            return task
        task.state = TaskState.CONTEXT_READY
        self._record(
            task,
            "perception_agent",
            "operational_context_validated",
            "ok",
            intervals=len(scenario.forecast),
            alerts=scenario.alerts,
            quality_score=task.perception.quality_score,
            original_task_valid=task.perception.original_task_valid,
            recommended_action=task.perception.recommended_action,
            objective_priority=task.perception.objective_priority,
        )
        self.store.save(task)

        task.baseline_plan = self.optimizer.build_baseline(scenario)
        task.plans = self.optimizer.optimize_candidates(scenario)
        task.state = TaskState.PLANS_GENERATED
        self._record(
            task,
            "dispatch_agent",
            "candidate_plans_optimized",
            "ok",
            plan_ids=[plan.plan_id for plan in task.plans],
            baseline_plan_id=task.baseline_plan.plan_id,
            solver="scipy.optimize.milp",
            tools=task.perception.required_tools,
        )
        self.store.save(task)

        task.audits = [
            self.auditor.audit(scenario, plan, task.baseline_plan) for plan in task.plans
        ]
        task.state = TaskState.AUDITED
        self._record(
            task,
            "audit_agent",
            "independent_policy_audit",
            "ok",
            decisions={report.plan_id: report.decision.value for report in task.audits},
        )
        self.store.save(task)

        eligible = [
            plan
            for plan in task.plans
            if next(report for report in task.audits if report.plan_id == plan.plan_id).decision
            != AuditDecision.REJECTED
        ]
        if not eligible:
            task.state = TaskState.FAILED
            self._record(task, "orchestrator", "selection_failed", "blocked")
            self.store.save(task)
            raise WorkflowError("all candidate plans were rejected by the independent auditor")

        selected = min(eligible, key=lambda plan: plan.metrics.total_cost_yuan)
        task.selected_plan_id = selected.plan_id
        selected_audit = next(
            report for report in task.audits if report.plan_id == selected.plan_id
        )
        self._record(
            task,
            "orchestrator",
            "audited_plan_selected",
            "ok",
            plan_id=selected.plan_id,
            profile=selected.profile,
        )

        if selected_audit.decision == AuditDecision.REQUIRES_APPROVAL:
            task.state = TaskState.AWAITING_APPROVAL
            self._record(task, "approval_gate", "human_approval_requested", "pending")
            self.store.save(task)
            return task

        return self._execute(task)

    def decide(self, task_id: str, request: ApprovalRequest) -> TaskRecord:
        task = self.approve_only(task_id, request)
        if not request.approved:
            return task
        return self.execute_approved(task_id)

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
        if not request.approved:
            task.state = TaskState.REJECTED
            self._record(task, "human_approver", "approval_rejected", "blocked")
            task.evidence_sha256 = self.store.seal_evidence(task)
            self.store.save(task)
            return task

        task.state = TaskState.APPROVED
        self._record(
            task,
            "human_approver",
            "approval_granted",
            "ok",
            approval_id=task.approval.approval_id,
        )
        self.store.save(task)
        return task

    def execute_approved(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task is None:
            raise WorkflowError("task not found")
        if task.state != TaskState.APPROVED:
            raise WorkflowError(f"task is not approved for execution: {task.state.value}")
        if task.approval is None or not task.approval.approved:
            raise WorkflowError("valid human approval is required before execution")
        return self._execute(task)

    def _execute(self, task: TaskRecord) -> TaskRecord:
        scenario = task.scenario_snapshot
        if task.baseline_plan is None:
            raise WorkflowError("task has no baseline plan")
        selected = next(plan for plan in task.plans if plan.plan_id == task.selected_plan_id)
        selected_audit = next(
            report for report in task.audits if report.plan_id == selected.plan_id
        )
        if selected_audit.decision == AuditDecision.REJECTED:
            raise WorkflowError("rejected plan cannot execute")
        if selected_audit.decision == AuditDecision.REQUIRES_APPROVAL and (
            task.approval is None or not task.approval.approved
        ):
            raise WorkflowError("approval is required before execution")

        task.state = TaskState.EXECUTING
        self._record(task, "execution_agent", "simulation_started", "ok")
        self.store.save(task)
        task.execution_summary = self.executor.execute(
            scenario,
            selected,
            task.baseline_plan,
            task.approval.approval_id if task.approval else None,
        )
        fallback_activated = bool(task.execution_summary["safe_fallback_activated"])
        task.state = TaskState.SAFE_FALLBACK if fallback_activated else TaskState.COMPLETED
        self._record(
            task,
            "execution_agent" if fallback_activated else "audit_agent",
            ("safe_fallback_activated" if fallback_activated else "post_execution_verification"),
            "fallback" if fallback_activated else "ok",
            real_devices_contacted=0,
            soc_bounds_held=task.execution_summary["soc_bounds_held"],
            confirmations_received=task.execution_summary["confirmations_received"],
            deviation_intervals=task.execution_summary["deviation_intervals"],
        )
        task.evidence_sha256 = self.store.seal_evidence(task)
        self.store.save(task)
        return task
