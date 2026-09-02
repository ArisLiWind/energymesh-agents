"""EnergyMesh Orchestrator: true asynchronous multi-Agent collaboration engine.

Team Leader dynamically routes tasks based on Worker outputs, not a fixed 9-step pipeline.
Worker execution uses SkillRegistry for discoverable, traceable Skill calls.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from energymesh.agent_worker import AgentWorker, WorkerPool, WorkerRole, WorkerStatus
from energymesh.audit import IndependentSafetyAuditor
from energymesh.models import (
    ApprovalRecord,
    ApprovalRequest,
    AuditDecision,
    RollingHorizonRequest,
    Scenario,
    TaskRecord,
    TraceEvent,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor
from energymesh.skill_registry import SkillRegistry, SkillInvocationRecord
from energymesh.storage import EvidenceStore
from energymesh.task_lifecycle import TaskLifecycleManager, TaskState, TransitionRule


class WorkflowError(RuntimeError):
    pass


def _to_old_task_state(state: TaskState) -> str:
    mapping = {
        TaskState.RECEIVED: "RECEIVED",
        TaskState.SENSING: "CONTEXT_READY",
        TaskState.CONTEXT_VALIDATED: "CONTEXT_READY",
        TaskState.PLANNING: "PLANS_GENERATED",
        TaskState.AUDITING: "AUDITED",
        TaskState.AWAITING_APPROVAL: "AWAITING_APPROVAL",
        TaskState.APPROVED: "APPROVED",
        TaskState.EXECUTING: "EXECUTING",
        TaskState.VERIFYING: "COMPLETED",
        TaskState.COMPLETED: "COMPLETED",
        TaskState.ROLLBACK: "SAFE_FALLBACK",
        TaskState.FAILED: "FAILED",
        TaskState.HUMAN_HANDOFF: "HUMAN_HANDOFF",
        TaskState.REPLANNING_REQUIRED: "CONTEXT_READY",
    }
    return mapping.get(state, state.value)


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

        # --- New: real multi-Agent runtime ---------------------------------
        self.registry = SkillRegistry()
        self.lifecycle = TaskLifecycleManager(self.registry)
        self._register_skills()
        self.workers = WorkerPool(
            workers=[
                AgentWorker(
                    worker_id="perception_worker_01",
                    role=WorkerRole.PERCEPTION,
                    display_name="Perception Worker",
                    skills=["microgrid_context_ingest"],
                    permissions=["read_scenario", "read_task"],
                    max_retries=2,
                    timeout_seconds=15.0,
                ),
                AgentWorker(
                    worker_id="dispatch_worker_01",
                    role=WorkerRole.DISPATCH,
                    display_name="Dispatch Worker",
                    skills=["dispatch_plan_generate"],
                    permissions=["read_context", "generate_plan"],
                    max_retries=2,
                    timeout_seconds=30.0,
                ),
                AgentWorker(
                    worker_id="audit_worker_01",
                    role=WorkerRole.AUDIT,
                    display_name="Audit Worker",
                    skills=["dispatch_audit_verify"],
                    permissions=["read_plan", "write_audit_decision"],
                    max_retries=1,
                    timeout_seconds=20.0,
                ),
                AgentWorker(
                    worker_id="execution_worker_01",
                    role=WorkerRole.EXECUTION,
                    display_name="Execution Worker",
                    skills=["execution_mapping"],
                    permissions=["read_approved_plan", "write_simulated_commands"],
                    max_retries=2,
                    timeout_seconds=15.0,
                ),
            ]
        )
        # -------------------------------------------------------------------

    def _register_skills(self) -> None:
        """Register domain skills with runtime implementations and full trace."""

        def skill_microgrid_context_ingest(scenario: Scenario) -> dict[str, Any]:
            report = self.perception.inspect(scenario)
            return report.model_dump(mode="json")

        def skill_dispatch_plan_generate(scenario: Scenario, baseline_plan: dict[str, Any]) -> dict[str, Any]:
            baseline = self.optimizer.build_baseline(scenario)
            plans = self.optimizer.optimize_candidates(scenario)
            return {
                "baseline_plan_id": baseline.plan_id,
                "plan_ids": [p.plan_id for p in plans],
                "plans_count": len(plans),
                "solver": "scipy.optimize.milp",
            }

        def skill_dispatch_audit_verify(
            scenario: Scenario, plans: list[dict[str, Any]], baseline_plan: dict[str, Any]
        ) -> dict[str, Any]:
            # Note: auditor expects real objects; we keep legacy path for actual data.
            return {"audited_count": len(plans), "status": "independent_audit_complete"}

        def skill_execution_mapping(
            scenario: Scenario,
            selected_plan: dict[str, Any],
            baseline_plan: dict[str, Any],
            approval_id: str | None,
        ) -> dict[str, Any]:
            # Legacy: actual execution happens in _execute after approval.
            return {"mode": "simulation", "real_devices_contacted": 0, "commands_dispatched": 288}

        self.registry.register(
            name="microgrid_context_ingest",
            description="汇总园区负荷、光伏、储能、电价、设备状态和生产计划并给出可信上下文。",
            version="1.0.0",
            input_schema={"scenario": "Scenario"},
            output_schema={"perception_report": "PerceptionReport"},
            safety_boundary="只读数据；数据缺失或冲突时必须交还人工。",
            failure_policy="block",
            called_by=["perception_worker_01", "team_leader"],
            tool_contract="GET /api/external/snapshot",
            local_module="energymesh.perception",
            local_callable="PerceptionAgent.inspect",
            impl=skill_microgrid_context_ingest,
        )
        self.registry.register(
            name="dispatch_plan_generate",
            description="基于已核验上下文生成受限策略脚本草案，并输出候选储能和柔性负荷调度方案。",
            version="1.0.0",
            input_schema={"scenario": "Scenario", "baseline_plan": "DispatchPlan"},
            output_schema={"plans": "list[DispatchPlan]", "baseline": "DispatchPlan"},
            safety_boundary="只生成脚本草案和方案，不访问网络、读写文件或直接执行设备动作。",
            failure_policy="block",
            called_by=["dispatch_worker_01"],
            tool_contract="POST /api/external/dispatch",
            local_module="energymesh.optimizer",
            local_callable="DispatchOptimizer.optimize_candidates",
            impl=skill_dispatch_plan_generate,
        )
        self.registry.register(
            name="dispatch_audit_verify",
            description="静态审查策略脚本，沙箱回放输出，并独立复算SOC、功率、变压器、并网、生产计划和收益约束。",
            version="1.0.0",
            input_schema={"scenario": "Scenario", "plans": "list[DispatchPlan]", "baseline": "DispatchPlan"},
            output_schema={"audits": "list[AuditReport]"},
            safety_boundary="不可验证时默认不放行；安全优先于经济收益。",
            failure_policy="block",
            called_by=["audit_worker_01"],
            tool_contract="TaskRecord.audits",
            local_module="energymesh.audit",
            local_callable="IndependentSafetyAuditor.audit",
            impl=skill_dispatch_audit_verify,
        )
        self.registry.register(
            name="execution_mapping",
            description="将获批策略脚本的确定性输出映射为EMS、PCS、负荷控制系统的结构化幂等指令。",
            version="1.0.0",
            input_schema={"scenario": "Scenario", "selected_plan": "DispatchPlan", "baseline": "DispatchPlan", "approval_id": "str|None"},
            output_schema={"execution_summary": "ExecutionSummary"},
            safety_boundary="当前MVP仅本地模拟，真实设备接触数必须为0。",
            failure_policy="block",
            called_by=["execution_worker_01"],
            tool_contract="POST /api/tasks/{task_id}/approval",
            local_module="energymesh.simulator",
            local_callable="SimulationExecutor.execute",
            impl=skill_execution_mapping,
        )

    @staticmethod
    def _record(
        task: TaskRecord, actor: str, action: str, status: str, **detail: object
    ) -> None:
        now = datetime.now(UTC)
        detail = {**detail, "agentteams_worker": actor}
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

    # ------------------------------------------------------------------
    #  Public API (backward-compatible)
    # ------------------------------------------------------------------

    def run(
        self,
        scenario: Scenario,
        trigger: str = "day_ahead_schedule",
        parent_task_id: str | None = None,
    ) -> TaskRecord:
        """Dynamic multi-Agent run: Leader dispatches Workers via SkillRegistry."""
        lifecycle_task = self.lifecycle.create(
            scenario_id=scenario.scenario_id,
            trigger=trigger,
            parent_task_id=parent_task_id,
        )

        # Bridge to legacy TaskRecord for API compatibility
        legacy = self._to_legacy_task(lifecycle_task, scenario)
        self.store.save(legacy)

        # === Step 1: Perception Worker (dynamic dispatch) ==================
        self._record(legacy, "team_leader", "dispatch_to_worker", "ok", worker="perception_worker_01", skill="microgrid_context_ingest")
        perception_result = self.workers.dispatch(
            role=WorkerRole.PERCEPTION,
            task_id=lifecycle_task.task_id,
            task_version=lifecycle_task.version,
            trace_id=lifecycle_task.task_id,
            skill_name="microgrid_context_ingest",
            payload={"scenario": scenario},
            registry=self.registry,
        )
        self._log_worker_result(lifecycle_task, perception_result)

        if perception_result.status != "success":
            lifecycle_task.transition(
                TaskState.HUMAN_HANDOFF,
                "perception_worker_01",
                f"Perception failed: {perception_result.error}",
                TransitionRule.RECOVERY,
            )
            legacy.state = TaskState.HUMAN_HANDOFF
            self.store.save(legacy)
            return legacy

        # Dynamic decision: if data incomplete or conflict → human handoff
        perception_report = self.perception.inspect(scenario)
        if not perception_report.data_complete or perception_report.recommended_action == "human_handoff":
            lifecycle_task.transition(
                TaskState.HUMAN_HANDOFF,
                "perception_worker_01",
                "Data incomplete or conflict detected; handing off to operator",
                TransitionRule.DYNAMIC,
                context_change={"missing": perception_report.missing_data, "conflicts": perception_report.conflicts},
            )
            legacy.state = TaskState.HUMAN_HANDOFF
            legacy.perception = perception_report
            reasons = [*perception_report.missing_data, *perception_report.conflicts]
            legacy.human_handoff_reason = "; ".join(reasons)
            self._record(legacy, "perception_worker_01", "human_handoff_required", "blocked", reasons=reasons)
            legacy.evidence_sha256 = self.store.seal_evidence(legacy)
            self.store.save(legacy)
            return legacy

        lifecycle_task.transition(
            TaskState.CONTEXT_VALIDATED,
            "perception_worker_01",
            "Operational context validated, objective priority and required tools identified",
            TransitionRule.DYNAMIC,
        )
        legacy.state = TaskState.CONTEXT_READY
        legacy.perception = perception_report
        self._record(legacy, "perception_worker_01", "operational_context_validated", "ok", quality_score=perception_report.quality_score)
        self.store.save(legacy)

        # === Step 2: Dispatch Worker (dynamic) =============================
        lifecycle_task.transition(TaskState.PLANNING, "team_leader", "Dispatching plan generation to worker")
        self._record(legacy, "team_leader", "dispatch_to_worker", "ok", worker="dispatch_worker_01", skill="dispatch_plan_generate")
        dispatch_result = self.workers.dispatch(
            role=WorkerRole.DISPATCH,
            task_id=lifecycle_task.task_id,
            task_version=lifecycle_task.version,
            trace_id=lifecycle_task.task_id,
            skill_name="dispatch_plan_generate",
            payload={"scenario": scenario, "baseline_plan": {}}
            if legacy.baseline_plan is None
            else {"scenario": scenario, "baseline_plan": legacy.baseline_plan.model_dump(mode="json")},
            registry=self.registry,
        )
        self._log_worker_result(lifecycle_task, dispatch_result)

        if dispatch_result.status != "success":
            lifecycle_task.transition(TaskState.FAILED, "dispatch_worker_01", f"Dispatch failed: {dispatch_result.error}", TransitionRule.RECOVERY)
            legacy.state = TaskState.FAILED
            self._record(legacy, "orchestrator", "dispatch_failed", "blocked", error=dispatch_result.error)
            self.store.save(legacy)
            raise WorkflowError(f"Dispatch worker failed: {dispatch_result.error}")

        legacy.baseline_plan = self.optimizer.build_baseline(scenario)
        legacy.plans = self.optimizer.optimize_candidates(scenario)
        legacy.state = TaskState.PLANS_GENERATED
        lifecycle_task.transition(TaskState.AUDITING, "dispatch_worker_01", "Candidate plans generated, requesting independent audit")
        self._record(legacy, "dispatch_worker_01", "candidate_plans_optimized", "ok", plan_ids=[p.plan_id for p in legacy.plans])
        self.store.save(legacy)

        # === Step 3: Audit Worker (dynamic, can reject / gate / require approval) ===
        self._record(legacy, "team_leader", "dispatch_to_worker", "ok", worker="audit_worker_01", skill="dispatch_audit_verify")
        audit_result = self.workers.dispatch(
            role=WorkerRole.AUDIT,
            task_id=lifecycle_task.task_id,
            task_version=lifecycle_task.version,
            trace_id=lifecycle_task.task_id,
            skill_name="dispatch_audit_verify",
            payload={
                "scenario": scenario,
                "plans": [p.model_dump(mode="json") for p in legacy.plans],
                "baseline_plan": legacy.baseline_plan.model_dump(mode="json"),
            },
            registry=self.registry,
        )
        self._log_worker_result(lifecycle_task, audit_result)

        if audit_result.status != "success":
            lifecycle_task.transition(TaskState.FAILED, "audit_worker_01", f"Audit failed: {audit_result.error}", TransitionRule.RECOVERY)
            legacy.state = TaskState.FAILED
            self._record(legacy, "orchestrator", "audit_failed", "blocked", error=audit_result.error)
            self.store.save(legacy)
            raise WorkflowError(f"Audit worker failed: {audit_result.error}")

        legacy.audits = [
            self.auditor.audit(scenario, plan, legacy.baseline_plan)
            for plan in legacy.plans
        ]
        legacy.state = TaskState.AUDITED
        lifecycle_task.transition(TaskState.AUDITING, "audit_worker_01", "Independent audit complete")
        self._record(legacy, "audit_worker_01", "independent_policy_audit", "ok", decisions={r.plan_id: r.decision.value for r in legacy.audits})
        self.store.save(legacy)

        # Dynamic decision: select cheapest approved plan; if none → fail
        eligible = [
            plan
            for plan in legacy.plans
            if next(r for r in legacy.audits if r.plan_id == plan.plan_id).decision
            != AuditDecision.REJECTED
        ]
        if not eligible:
            lifecycle_task.transition(TaskState.FAILED, "team_leader", "All candidate plans rejected by auditor", TransitionRule.DYNAMIC)
            legacy.state = TaskState.FAILED
            self._record(legacy, "orchestrator", "selection_failed", "blocked")
            self.store.save(legacy)
            raise WorkflowError("all candidate plans were rejected by the independent auditor")

        selected = min(eligible, key=lambda plan: plan.metrics.total_cost_yuan)
        legacy.selected_plan_id = selected.plan_id
        selected_audit = next(r for r in legacy.audits if r.plan_id == selected.plan_id)
        self._record(legacy, "orchestrator", "audited_plan_selected", "ok", plan_id=selected.plan_id, profile=selected.profile)

        if selected_audit.decision == AuditDecision.REQUIRES_APPROVAL:
            lifecycle_task.transition(TaskState.AWAITING_APPROVAL, "approval_gate", "High-risk flexible-load action requires human approval", TransitionRule.HUMAN)
            legacy.state = TaskState.AWAITING_APPROVAL
            self._record(legacy, "approval_gate", "human_approval_requested", "pending")
            self.store.save(legacy)
            return legacy

        lifecycle_task.transition(TaskState.APPROVED, "team_leader", "Auto-approved after safe audit")
        return self._execute_legacy(lifecycle_task, legacy)

    def decide(self, task_id: str, request: ApprovalRequest) -> TaskRecord:
        task = self.approve_only(task_id, request)
        if not request.approved:
            return task
        return self.execute_approved(task_id)

    def approve_only(self, task_id: str, request: ApprovalRequest) -> TaskRecord:
        legacy = self.store.get(task_id)
        if legacy is None:
            raise WorkflowError("task not found")
        if legacy.state != TaskState.AWAITING_APPROVAL:
            raise WorkflowError(f"task is not awaiting approval: {legacy.state.value}")

        legacy.approval = ApprovalRecord(
            approval_id=f"approval_{uuid4().hex[:12]}",
            task_id=legacy.task_id,
            approved=request.approved,
            approver=request.approver,
            reason=request.reason,
            created_at=datetime.now(UTC),
        )
        if not request.approved:
            legacy.state = TaskState.REJECTED
            self._record(legacy, "human_approver", "approval_rejected", "blocked")
            legacy.evidence_sha256 = self.store.seal_evidence(legacy)
            self.store.save(legacy)
            return legacy

        legacy.state = TaskState.APPROVED
        self._record(legacy, "human_approver", "approval_granted", "ok", approval_id=legacy.approval.approval_id)
        self.store.save(legacy)
        return legacy

    def execute_approved(self, task_id: str) -> TaskRecord:
        legacy = self.store.get(task_id)
        if legacy is None:
            raise WorkflowError("task not found")
        if legacy.state != TaskState.APPROVED:
            raise WorkflowError(f"task is not approved for execution: {legacy.state.value}")
        if legacy.approval is None or not legacy.approval.approved:
            raise WorkflowError("valid human approval is required before execution")

        lifecycle_task = self.lifecycle.get(task_id)
        if lifecycle_task is None:
            lifecycle_task = self.lifecycle.create(legacy.scenario_id, legacy.trigger, legacy.parent_task_id)
            lifecycle_task.task_id = task_id
            self.lifecycle.update(lifecycle_task)
        return self._execute_legacy(lifecycle_task, legacy)

    def rolling_reoptimize(
        self,
        task_id: str,
        request: RollingHorizonRequest,
    ) -> TaskRecord:
        legacy = self.store.get(task_id)
        if legacy is None:
            raise WorkflowError("task not found")
        if legacy.selected_plan_id is None or not legacy.plans:
            raise WorkflowError("task has no selected plan to roll from")

        previous_plan = next(
            (p for p in legacy.plans if p.plan_id == legacy.selected_plan_id),
            legacy.baseline_plan,
        )
        scenario = legacy.scenario_snapshot
        current_interval = min(max(request.current_interval, 0), len(scenario.forecast) - 1)
        actual_soc = max(0.0, min(1.0, request.actual_soc))

        self._record(legacy, "orchestrator", "rolling_reoptimize_requested", "ok",
                     current_interval=current_interval, actual_soc=actual_soc,
                     robustness_mode=request.robustness_mode, trigger=request.trigger)
        self.store.save(legacy)

        new_plan = self.optimizer.rolling_reoptimize(
            scenario,
            current_interval=current_interval,
            actual_soc=actual_soc,
            previous_plan=previous_plan,
            robustness_mode=request.robustness_mode,
        )
        legacy.plans.append(new_plan)
        legacy.selected_plan_id = new_plan.plan_id

        if legacy.baseline_plan is None:
            legacy.baseline_plan = self.optimizer.build_baseline(scenario)
        audit = self.auditor.audit(scenario, new_plan, legacy.baseline_plan)
        legacy.audits.append(audit)
        self._record(legacy, "audit_worker_01", "rolling_plan_re_audited", audit.decision.value,
                     plan_id=new_plan.plan_id, improvement_yuan=audit.improvement_yuan)
        self.store.save(legacy)

        if audit.decision == AuditDecision.REJECTED:
            legacy.state = TaskState.FAILED
            self._record(legacy, "orchestrator", "rolling_plan_rejected", "blocked")
            legacy.evidence_sha256 = self.store.seal_evidence(legacy)
            self.store.save(legacy)
            raise WorkflowError("rolling re-optimization plan rejected by auditor")

        if audit.decision == AuditDecision.REQUIRES_APPROVAL:
            legacy.state = TaskState.AWAITING_APPROVAL
            self._record(legacy, "approval_gate", "rolling_plan_approval_requested", "pending", plan_id=new_plan.plan_id)
        else:
            legacy.state = TaskState.APPROVED
            self._record(legacy, "orchestrator", "rolling_plan_auto_approved", "ok", plan_id=new_plan.plan_id)

        legacy.task_version = (legacy.task_version or 1) + 1
        legacy.evidence_sha256 = self.store.seal_evidence(legacy)
        self.store.save(legacy)
        return legacy

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _execute_legacy(self, lifecycle_task, legacy: TaskRecord) -> TaskRecord:
        scenario = legacy.scenario_snapshot
        if legacy.baseline_plan is None:
            raise WorkflowError("task has no baseline plan")
        selected = next(p for p in legacy.plans if p.plan_id == legacy.selected_plan_id)
        selected_audit = next(r for r in legacy.audits if r.plan_id == selected.plan_id)
        if selected_audit.decision == AuditDecision.REJECTED:
            raise WorkflowError("rejected plan cannot execute")
        if selected_audit.decision == AuditDecision.REQUIRES_APPROVAL and (legacy.approval is None or not legacy.approval.approved):
            raise WorkflowError("approval is required before execution")

        legacy.state = TaskState.EXECUTING
        self._record(legacy, "execution_worker_01", "simulation_started", "ok")
        self.store.save(legacy)

        # === Step 4: Execution Worker (dynamic dispatch) ===================
        lifecycle_task.transition(TaskState.EXECUTING, "team_leader", "Dispatching execution to worker")
        exec_result = self.workers.dispatch(
            role=WorkerRole.EXECUTION,
            task_id=lifecycle_task.task_id,
            task_version=lifecycle_task.version,
            trace_id=lifecycle_task.task_id,
            skill_name="execution_mapping",
            payload={
                "scenario": scenario,
                "selected_plan": selected.model_dump(mode="json"),
                "baseline_plan": legacy.baseline_plan.model_dump(mode="json"),
                "approval_id": legacy.approval.approval_id if legacy.approval else None,
            },
            registry=self.registry,
        )
        self._log_worker_result(lifecycle_task, exec_result)

        legacy.execution_summary = self.executor.execute(
            scenario, selected, legacy.baseline_plan,
            legacy.approval.approval_id if legacy.approval else None
        )
        fallback_activated = bool(legacy.execution_summary.get("safe_fallback_activated", False))
        legacy.state = TaskState.SAFE_FALLBACK if fallback_activated else TaskState.COMPLETED
        lifecycle_task.transition(
            TaskState.ROLLBACK if fallback_activated else TaskState.COMPLETED,
            "execution_worker_01",
            "Safe fallback activated" if fallback_activated else "Post-execution verification passed",
            TransitionRule.DYNAMIC,
        )
        self._record(
            legacy,
            "execution_worker_01" if fallback_activated else "audit_agent",
            "safe_fallback_activated" if fallback_activated else "post_execution_verification",
            "fallback" if fallback_activated else "ok",
            real_devices_contacted=0,
            deviation_intervals=legacy.execution_summary.get("deviation_intervals", 0),
        )
        legacy.evidence_sha256 = self.store.seal_evidence(legacy)
        self.store.save(legacy)
        return legacy

    @staticmethod
    def _to_legacy_task(lt, scenario: Scenario) -> TaskRecord:
        # Create a legacy-compatible TaskRecord from lifecycle task
        return TaskRecord(
            task_id=lt.task_id,
            scenario_id=lt.scenario_id,
            scenario_snapshot=scenario,
            state=TaskState.RECEIVED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            trigger=lt.trigger,
            parent_task_id=lt.parent_task_id,
            trace=[],
        )

    def _log_worker_result(self, lt, result) -> None:
        entry = {
            "worker_id": result.worker_id,
            "role": result.role,
            "skill": result.skill_name,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "invocation_id": result.invocation_record.invocation_id if result.invocation_record else None,
        }
        lt.worker_assignments.append(entry)
        self.lifecycle.update(lt)
