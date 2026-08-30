from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from energymesh.demo import load_demo_scenario
from energymesh.models import (
    AgentHandoff,
    ApprovalDecisionRequest,
    ApprovalRecordV2,
    AuditVerdictRecord,
    CandidatePlanRecord,
    ContextSnapshot,
    DemoRunResponse,
    ExecuteRequest,
    ExecutionCommandRecord,
    ExecutionReceipt,
    RollbackRecord,
    SkillInvocation,
    TaskEvent,
    TaskRecord,
    TaskState,
    VerificationResult,
)
from energymesh.storage import EvidenceStore, PayloadRow


class DemoWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoIdentity:
    task_id: str = "TASK-20260731-014"
    trace_id: str = "TRACE-20260731-014"
    context_id: str = "CTX-014-V2"


class CompoundChangeDemo:
    legal_transitions: dict[TaskState, set[TaskState]] = {
        TaskState.TASK_RECEIVED: {TaskState.SENSING},
        TaskState.SENSING: {TaskState.CONTEXT_VALIDATED, TaskState.REPLANNING_REQUIRED},
        TaskState.CONTEXT_VALIDATED: {TaskState.PLANNING},
        TaskState.REPLANNING_REQUIRED: {TaskState.PLANNING},
        TaskState.PLANNING: {TaskState.AUDITING},
        TaskState.AUDITING: {TaskState.AWAITING_APPROVAL, TaskState.REJECTED},
        TaskState.AWAITING_APPROVAL: {TaskState.EXECUTING, TaskState.REJECTED},
        TaskState.EXECUTING: {TaskState.VERIFYING},
        TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.ROLLBACK, TaskState.FAILED},
        TaskState.COMPLETED: set(),
        TaskState.REJECTED: set(),
        TaskState.ROLLBACK: set(),
        TaskState.FAILED: set(),
    }

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        self.identity = DemoIdentity()
        self.scenario = load_demo_scenario()

    def run(self) -> DemoRunResponse:
        self.store.reset_demo_records(self.identity.task_id)
        created = self._new_task(TaskState.TASK_RECEIVED, 1, self._at(1))
        self.store.save(created)
        self._event(None, TaskState.TASK_RECEIVED, 1, "Team Leader", "创建14:00复合变化任务")
        self._transition(
            created,
            TaskState.SENSING,
            "Team Leader",
            "任务交给感知Agent读取模拟EMS/BMS/PCS/PV/负荷/电价/生产计划",
        )
        self._handoff(
            "HANDOFF-014-001",
            1,
            "Team Leader",
            "Perception Agent",
            "TASK-20260731-014/V1",
            "CTX-014-V2",
            "microgrid_context_ingest",
        )
        self._skill(
            "SKILL-014-001",
            1,
            "Perception Agent",
            "microgrid_context_ingest",
            "simulated_external_feeds@14:00",
            "CTX-014-V2",
            820,
        )

        context = self._context_snapshot()
        self.store.save_context_snapshot(context)
        self._transition(
            created,
            TaskState.REPLANNING_REQUIRED,
            "Perception Agent",
            "新增负荷、光伏偏差、传感器冲突和峰价共同使V1计划失效，任务升级为V2",
            version=2,
            context=context,
        )
        self._transition(
            created,
            TaskState.PLANNING,
            "Team Leader",
            "按V2上下文交给调度Agent重新规划",
        )
        self._handoff(
            "HANDOFF-014-002",
            2,
            "Team Leader",
            "Dispatch Agent",
            context.context_id,
            "CANDIDATES-014-V2",
            "dispatch_plan_generate",
        )
        self._skill(
            "SKILL-014-002",
            2,
            "Dispatch Agent",
            "dispatch_plan_generate",
            context.context_id,
            "CANDIDATES-014-V2",
            1310,
        )
        for candidate in self._candidate_plans(context):
            self.store.save_candidate_plan(candidate)
        self._transition(
            created,
            TaskState.AUDITING,
            "Dispatch Agent",
            "三套候选策略脚本已生成，调度Agent无批准权限",
        )
        self._handoff(
            "HANDOFF-014-003",
            2,
            "Team Leader",
            "Audit Agent",
            "CANDIDATES-014-V2",
            "AUDIT-014-V2",
            "dispatch_audit_verify",
        )
        self._skill(
            "SKILL-014-003",
            2,
            "Audit Agent",
            "dispatch_audit_verify",
            "CANDIDATES-014-V2",
            "AUDIT-014-V2",
            970,
        )
        for verdict in self._audit_verdicts(context):
            self.store.save_audit_verdict(verdict)
        self._transition(
            created,
            TaskState.AWAITING_APPROVAL,
            "Audit Agent",
            "Candidate A被否决，Candidate B/C通过硬约束并等待人工审批",
        )
        self._save_task_state(created, TaskState.AWAITING_APPROVAL, 2, context)
        return DemoRunResponse(
            task_id=self.identity.task_id,
            task_version=2,
            trace_id=self.identity.trace_id,
            state=TaskState.AWAITING_APPROVAL,
            context_id=context.context_id,
            context_hash=context.context_hash,
        )

    def approve(self, task_id: str, request: ApprovalDecisionRequest) -> ApprovalRecordV2:
        task = self._get_task(task_id)
        context = self._context(task_id)
        if task.state != TaskState.AWAITING_APPROVAL:
            raise DemoWorkflowError(f"task is not awaiting approval: {task.state.value}")
        self._assert_version_and_hash(request.task_version, request.context_hash, context)
        verdict = self._audit_for(task_id, request.candidate_id)
        if verdict is None or verdict["verdict"] != "approved":
            raise DemoWorkflowError("candidate has not passed Audit Agent verification")
        approval = ApprovalRecordV2(
            id=f"APPROVAL-{request.candidate_id}-V{request.task_version}",
            task_id=task_id,
            task_version=request.task_version,
            trace_id=self.identity.trace_id,
            candidate_id=request.candidate_id,
            context_hash=request.context_hash,
            approved=request.approved,
            valid=request.approved,
            approver=request.approver,
            reason=request.reason,
            created_at=self._at(19),
        )
        self.store.save_approval_record(approval)
        if not request.approved:
            self._transition(task, TaskState.REJECTED, "Human Approval", "人工审批拒绝执行")
            self._save_task_state(task, TaskState.REJECTED, request.task_version, context)
        else:
            self._event(
                TaskState.AWAITING_APPROVAL,
                TaskState.AWAITING_APPROVAL,
                request.task_version,
                "Human Approval",
                f"{request.candidate_id}已通过人工审批，审批绑定context_hash",
                input_reference=request.candidate_id,
                output_reference=approval.id,
            )
        return approval

    def execute(self, task_id: str, request: ExecuteRequest) -> ExecutionReceipt:
        existing = self.store.get_execution_receipt_by_key(request.idempotency_key)
        if existing is not None:
            return ExecutionReceipt.model_validate(existing)
        task = self._get_task(task_id)
        context = self._context(task_id)
        if task.state != TaskState.AWAITING_APPROVAL:
            raise DemoWorkflowError(f"task is not awaiting approval: {task.state.value}")
        self._assert_version_and_hash(request.task_version, request.context_hash, context)
        approval = self._valid_approval(task_id, request.candidate_id, request.context_hash)
        if approval is None:
            raise DemoWorkflowError("valid human approval is required before execution")
        candidate = self._candidate_for(task_id, request.candidate_id)
        if candidate is None:
            raise DemoWorkflowError("candidate not found")
        self._transition(
            task,
            TaskState.EXECUTING,
            "Team Leader",
            "审批有效，交给执行Agent映射模拟指令",
        )
        self._handoff(
            "HANDOFF-014-004",
            request.task_version,
            "Team Leader",
            "Execution Agent",
            cast(str, approval["id"]),
            "EXECUTION-RECEIPT-014",
            "execution_mapping",
        )
        self._skill(
            "SKILL-014-004",
            request.task_version,
            "Execution Agent",
            "execution_mapping",
            request.candidate_id,
            request.idempotency_key,
            640,
        )
        commands = self._commands(request)
        for command in commands:
            self.store.save_execution_command(command)
        receipt = ExecutionReceipt(
            id=f"RECEIPT-{request.candidate_id}-V{request.task_version}",
            task_id=task_id,
            task_version=request.task_version,
            trace_id=self.identity.trace_id,
            candidate_id=request.candidate_id,
            idempotency_key=request.idempotency_key,
            status="simulated_dispatched",
            command_count=len(commands),
            simulated=True,
            created_at=self._at(21),
        )
        self.store.save_execution_receipt(receipt)
        self._transition(
            task,
            TaskState.VERIFYING,
            "Execution Agent",
            "结构化指令已生成，进入执行偏差验证",
        )
        deviation = (
            request.force_deviation_percent if request.force_deviation_percent is not None else 2.4
        )
        evidence_hash = self._evidence_hash(task_id)
        verification = VerificationResult(
            id=f"VERIFY-{request.candidate_id}-V{request.task_version}",
            task_id=task_id,
            task_version=request.task_version,
            trace_id=self.identity.trace_id,
            candidate_id=request.candidate_id,
            status="passed" if deviation <= 5 else "deviation_exceeded",
            max_deviation_percent=deviation,
            evidence_hash=evidence_hash,
            created_at=self._at(23),
        )
        self.store.save_verification_result(verification)
        if deviation > 5:
            rollback = RollbackRecord(
                id=f"ROLLBACK-{request.candidate_id}-V{request.task_version}",
                task_id=task_id,
                task_version=request.task_version,
                trace_id=self.identity.trace_id,
                reason=f"执行偏差{deviation:.1f}%超过5%阈值",
                baseline_restored=True,
                fallback_policy={
                    "policy": "safe_baseline",
                    "pcs_power_kw": 0,
                    "grid_import_limit_kw": 950,
                    "control_owner": "human_operator",
                },
                created_at=self._at(24),
            )
            self.store.save_rollback_record(rollback)
            self._transition(task, TaskState.ROLLBACK, "Verification", rollback.reason)
            self._save_task_state(task, TaskState.ROLLBACK, request.task_version, context)
        else:
            self._transition(
                task,
                TaskState.COMPLETED,
                "Verification",
                "执行偏差低于5%，证据包封存",
            )
            self._save_task_state(task, TaskState.COMPLETED, request.task_version, context)
        self._seal_demo(task_id)
        return receipt

    def run_rollback(self) -> DemoRunResponse:
        response = self.run()
        self.approve(
            response.task_id,
            ApprovalDecisionRequest(
                candidate_id="Candidate-B",
                task_version=response.task_version,
                context_hash=response.context_hash or "",
                approver="rollback-demo",
                reason="演示回滚路径审批",
            ),
        )
        self.execute(
            response.task_id,
            ExecuteRequest(
                candidate_id="Candidate-B",
                task_version=response.task_version,
                context_hash=response.context_hash or "",
                idempotency_key="IDEMP-TASK-014-B-ROLLBACK",
                force_deviation_percent=7.8,
            ),
        )
        task = self._get_task(response.task_id)
        return response.model_copy(update={"state": task.state})

    def evidence(self, task_id: str) -> dict[str, object]:
        return self.store.demo_evidence(task_id)

    def _new_task(self, state: TaskState, version: int, when: datetime) -> TaskRecord:
        return TaskRecord(
            task_id=self.identity.task_id,
            scenario_id=self.scenario.scenario_id,
            scenario_snapshot=self.scenario,
            state=state,
            task_version=version,
            trace_id=self.identity.trace_id,
            created_at=when,
            updated_at=when,
            trigger="14:00_compound_change",
        )

    def _save_task_state(
        self,
        task: TaskRecord,
        state: TaskState,
        version: int,
        context: ContextSnapshot | None = None,
    ) -> None:
        task.state = state
        task.task_version = version
        task.context_id = context.context_id if context else task.context_id
        task.context_hash = context.context_hash if context else task.context_hash
        task.trace_id = self.identity.trace_id
        task.updated_at = self._at(25)
        task.execution_summary = {
            "mode": "simulation",
            "real_devices_contacted": 0,
            "agentteams_trace": self.identity.trace_id,
            "task_version": version,
            "context_id": task.context_id,
            "context_hash": task.context_hash,
        }
        self.store.save(task)

    def _transition(
        self,
        task: TaskRecord,
        to_state: TaskState,
        actor: str,
        reason: str,
        *,
        version: int | None = None,
        context: ContextSnapshot | None = None,
    ) -> None:
        from_state = task.state
        if to_state not in self.legal_transitions.get(from_state, set()) and to_state != from_state:
            message = f"illegal state transition: {from_state.value} -> {to_state.value}"
            raise DemoWorkflowError(message)
        task.state = to_state
        task.task_version = version or task.task_version
        self._event(from_state, to_state, task.task_version, actor, reason)
        if context:
            task.context_id = context.context_id
            task.context_hash = context.context_hash

    def _event(
        self,
        from_state: TaskState | None,
        to_state: TaskState,
        version: int,
        actor: str,
        reason: str,
        *,
        input_reference: str | None = None,
        output_reference: str | None = None,
        skill_name: str | None = None,
    ) -> None:
        index = len(self.store.list_task_events(self.identity.task_id)) + 1
        event = TaskEvent(
            event_id=f"EVT-014-{index:03d}",
            task_id=self.identity.task_id,
            task_version=version,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            timestamp=self._at(index),
            reason=reason,
            trace_id=self.identity.trace_id,
            input_reference=input_reference,
            output_reference=output_reference,
            skill_name=skill_name,
            detail={"agentteams_task_state": to_state.value},
        )
        self.store.save_task_event(event)

    def _handoff(
        self,
        handoff_id: str,
        version: int,
        from_agent: str,
        to_agent: str,
        input_reference: str,
        output_reference: str,
        skill_name: str,
    ) -> None:
        self.store.save_agent_handoff(
            AgentHandoff(
                id=handoff_id,
                task_id=self.identity.task_id,
                task_version=version,
                trace_id=self.identity.trace_id,
                from_agent=from_agent,
                to_agent=to_agent,
                status="completed",
                input_reference=input_reference,
                output_reference=output_reference,
                skill_name=skill_name,
                created_at=self._at(len(self.store.list_agent_handoffs(self.identity.task_id)) + 2),
            )
        )

    def _skill(
        self,
        invocation_id: str,
        version: int,
        agent: str,
        skill_name: str,
        input_reference: str,
        output_reference: str,
        duration_ms: int,
    ) -> None:
        started = self._at(len(self.store.list_skill_invocations(self.identity.task_id)) + 3)
        self.store.save_skill_invocation(
            SkillInvocation(
                id=invocation_id,
                task_id=self.identity.task_id,
                task_version=version,
                trace_id=self.identity.trace_id,
                agent=agent,
                skill_name=skill_name,
                status="completed",
                input_reference=input_reference,
                output_reference=output_reference,
                started_at=started,
                ended_at=started + timedelta(milliseconds=duration_ms),
                duration_ms=duration_ms,
            )
        )

    def _context_snapshot(self) -> ContextSnapshot:
        body = {
            "context_id": self.identity.context_id,
            "task_id": self.identity.task_id,
            "task_version": 2,
            "timestamp": "2026-07-31T14:00:06+08:00",
            "changes": {
                "production_load_added_kw": 420,
                "pv_actual_vs_forecast_percent": -18.6,
                "transformer_temperature_conflict": True,
                "tariff_period": "peak",
            },
            "data_quality": {
                "ems": "valid",
                "bms": "valid",
                "pcs": "valid",
                "pv": "valid",
                "load": "valid",
                "tariff": "valid",
                "weather": "valid",
                "production_plan": "valid",
                "transformer_sensor": "conflict",
            },
            "previous_plan_status": "invalidated",
            "automation_permission": "restricted",
            "constraint_set_version": "1.4",
        }
        digest = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ContextSnapshot.model_validate({**body, "context_hash": digest})

    def _candidate_plans(self, context: ContextSnapshot) -> list[CandidatePlanRecord]:
        created = self._at(12)
        return [
            CandidatePlanRecord(
                id="PLAN-014-A",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                context_id=context.context_id,
                context_hash=context.context_hash,
                candidate_id="Candidate-A",
                name="经济优先",
                priority="cost_first",
                status="audit_rejected",
                cost_yuan=9280,
                max_power_kw=1298,
                soc_min_percent=28,
                soc_max_percent=72,
                transformer_load_percent=103.8,
                reserve_capacity_kwh=120,
                actions=[
                    {
                        "interval": "14:00-15:00",
                        "action": "battery_discharge",
                        "power_kw": 280,
                    },
                    {
                        "interval": "14:00-16:00",
                        "action": "flexible_load_reduce",
                        "power_kw": 60,
                    },
                ],
                created_at=created,
            ),
            CandidatePlanRecord(
                id="PLAN-014-B",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                context_id=context.context_id,
                context_hash=context.context_hash,
                candidate_id="Candidate-B",
                name="安全均衡",
                priority="safety_balanced",
                status="audit_approved",
                cost_yuan=9860,
                max_power_kw=1126,
                soc_min_percent=35,
                soc_max_percent=68,
                transformer_load_percent=90.1,
                reserve_capacity_kwh=210,
                actions=[
                    {
                        "interval": "14:00-15:00",
                        "action": "battery_discharge",
                        "power_kw": 220,
                    },
                    {
                        "interval": "14:00-16:00",
                        "action": "flexible_load_reduce",
                        "power_kw": 110,
                    },
                    {
                        "interval": "17:00-18:00",
                        "action": "reserve_capacity_hold",
                        "energy_kwh": 210,
                    },
                ],
                created_at=created,
            ),
            CandidatePlanRecord(
                id="PLAN-014-C",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                context_id=context.context_id,
                context_hash=context.context_hash,
                candidate_id="Candidate-C",
                name="保供优先",
                priority="reliability_first",
                status="audit_approved",
                cost_yuan=10480,
                max_power_kw=1062,
                soc_min_percent=42,
                soc_max_percent=74,
                transformer_load_percent=84.9,
                reserve_capacity_kwh=280,
                actions=[
                    {
                        "interval": "14:00-15:00",
                        "action": "battery_discharge",
                        "power_kw": 160,
                    },
                    {
                        "interval": "14:00-18:00",
                        "action": "production_shift",
                        "load_kw": 160,
                    },
                    {
                        "interval": "all_peak",
                        "action": "reserve_capacity_hold",
                        "energy_kwh": 280,
                    },
                ],
                created_at=created,
            ),
        ]

    def _audit_verdicts(self, context: ContextSnapshot) -> list[AuditVerdictRecord]:
        created = self._at(16)
        checks = {
            "soc_boundary": "passed",
            "pcs_power_boundary": "passed",
            "grid_interconnection_limit": "passed",
            "energy_conservation": "passed",
            "production_constraint": "passed",
        }
        return [
            AuditVerdictRecord(
                id="AUDIT-014-A",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                candidate_id="Candidate-A",
                context_hash=context.context_hash,
                verdict="rejected",
                reason="预计变压器负载率103.8%，超过95%安全上限",
                transformer_load_percent=103.8,
                safety_limit_percent=95,
                checks={**checks, "transformer_capacity": "rejected"},
                created_at=created,
            ),
            AuditVerdictRecord(
                id="AUDIT-014-B",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                candidate_id="Candidate-B",
                context_hash=context.context_hash,
                verdict="approved",
                reason="硬约束全部通过，需人工确认生产柔性负荷调整",
                transformer_load_percent=90.1,
                safety_limit_percent=95,
                checks={**checks, "transformer_capacity": "passed"},
                created_at=created + timedelta(seconds=1),
            ),
            AuditVerdictRecord(
                id="AUDIT-014-C",
                task_id=self.identity.task_id,
                task_version=2,
                trace_id=self.identity.trace_id,
                candidate_id="Candidate-C",
                context_hash=context.context_hash,
                verdict="approved",
                reason="保留容量更高，成本较高但风险最低",
                transformer_load_percent=84.9,
                safety_limit_percent=95,
                checks={**checks, "transformer_capacity": "passed"},
                created_at=created + timedelta(seconds=2),
            ),
        ]

    def _commands(self, request: ExecuteRequest) -> list[ExecutionCommandRecord]:
        rows = [
            ("EMS", "dispatch-plan", "select_candidate", 1, "flag"),
            ("BMS", "battery-cluster-01", "set_discharge_power", 220, "kW"),
            ("PCS", "pcs-01", "limit_export_power", 0, "kW"),
            ("MES", "production-line-a", "shift_flexible_load", 110, "kW"),
        ]
        return [
            ExecutionCommandRecord(
                id=f"CMD-014-{index:02d}",
                task_id=self.identity.task_id,
                task_version=request.task_version,
                trace_id=self.identity.trace_id,
                candidate_id=request.candidate_id,
                idempotency_key=request.idempotency_key,
                target_system=target,
                resource_id=resource,
                command=command,
                value=value,
                unit=unit,
                status="simulated",
                created_at=self._at(21),
            )
            for index, (target, resource, command, value, unit) in enumerate(rows, start=1)
        ]

    def _assert_version_and_hash(
        self, task_version: int, context_hash: str, context: ContextSnapshot
    ) -> None:
        if task_version != context.task_version:
            raise DemoWorkflowError("task version does not match active context")
        if context_hash != context.context_hash:
            raise DemoWorkflowError("context hash does not match active context")

    def _get_task(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task is None:
            raise DemoWorkflowError("task not found")
        return task

    def _context(self, task_id: str) -> ContextSnapshot:
        context = self.store.get_context_snapshot(task_id)
        if context is None:
            raise DemoWorkflowError("context snapshot not found")
        return ContextSnapshot.model_validate(context)

    def _audit_for(self, task_id: str, candidate_id: str) -> PayloadRow | None:
        return next(
            (
                item
                for item in self.store.list_audit_verdicts(task_id)
                if item["candidate_id"] == candidate_id
            ),
            None,
        )

    def _candidate_for(self, task_id: str, candidate_id: str) -> PayloadRow | None:
        return next(
            (
                item
                for item in self.store.list_candidate_plans(task_id)
                if item["candidate_id"] == candidate_id
            ),
            None,
        )

    def _valid_approval(
        self, task_id: str, candidate_id: str, context_hash: str
    ) -> PayloadRow | None:
        return next(
            (
                item
                for item in reversed(self.store.list_approvals(task_id))
                if item["candidate_id"] == candidate_id
                and item["context_hash"] == context_hash
                and item["approved"]
                and item["valid"]
            ),
            None,
        )

    def _evidence_hash(self, task_id: str) -> str:
        evidence = self.store.demo_evidence(task_id)
        return str(evidence["sha256"])

    def _seal_demo(self, task_id: str) -> None:
        evidence = self.store.demo_evidence(task_id)
        task = self._get_task(task_id)
        task.evidence_sha256 = str(evidence["sha256"])
        self.store.save(task)
        target = self.store.evidence_dir / f"{task_id}.json"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{task_id}-", suffix=".tmp", dir=self.store.evidence_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(evidence, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _at(second: int) -> datetime:
        return datetime.fromisoformat("2026-07-31T14:00:00+08:00") + timedelta(seconds=second)
