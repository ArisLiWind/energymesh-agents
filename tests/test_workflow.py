from __future__ import annotations

import json
from pathlib import Path

import pytest

from energymesh.config import Settings
from energymesh.demo import apply_operational_change
from energymesh.models import ApprovalRequest, ReoptimizationRequest, TaskState
from energymesh.optimizer import DispatchOptimizer
from energymesh.orchestrator import WorkflowError
from energymesh.simulator import SimulationExecutor


def test_workflow_requires_approval_then_executes_simulation(
    orchestrator, scenario, settings
) -> None:
    task = orchestrator.run(scenario)

    assert task.state == TaskState.AWAITING_APPROVAL
    assert task.execution_summary is None
    assert task.selected_plan_id is not None

    completed = orchestrator.decide(
        task.task_id,
        ApprovalRequest(
            approved=True,
            approver="test-approver",
            reason="constraints reviewed in test",
        ),
    )

    assert completed.state == TaskState.COMPLETED
    assert completed.execution_summary is not None
    assert completed.execution_summary["mode"] == "simulation"
    assert completed.execution_summary["real_devices_contacted"] == 0
    assert completed.execution_summary["confirmation_ratio"] == 1.0
    assert completed.execution_summary["simulated_commands_dispatched"] == 288
    assert completed.evidence_sha256 is not None
    evidence_path = settings.evidence_dir / f"{completed.task_id}.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["sha256"] == completed.evidence_sha256
    assert evidence["safety_declaration"]["allow_production_write"] is False


def test_workflow_records_real_multi_agent_task_and_costs(orchestrator, scenario) -> None:
    task = orchestrator.run(scenario, trigger="operator_chat_dispatch_request")

    actors = [event.actor for event in task.trace]
    assert any(actor in actors for actor in ("perception_worker", "perception_agent"))
    assert any(actor in actors for actor in ("dispatch_worker", "dispatch_agent"))
    assert any(actor in actors for actor in ("audit_worker", "audit_agent"))
    assert task.baseline_plan is not None
    assert task.selected_plan_id is not None
    selected = next(plan for plan in task.plans if plan.plan_id == task.selected_plan_id)
    assert selected.metrics.total_cost_yuan < task.baseline_plan.metrics.total_cost_yuan


def test_rejected_approval_never_executes(orchestrator, scenario) -> None:
    task = orchestrator.run(scenario)
    rejected = orchestrator.decide(
        task.task_id,
        ApprovalRequest(
            approved=False,
            approver="test-approver",
            reason="load response not authorized",
        ),
    )

    assert rejected.state == TaskState.REJECTED
    assert rejected.execution_summary is None
    with pytest.raises(WorkflowError, match="not awaiting approval"):
        orchestrator.decide(
            task.task_id,
            ApprovalRequest(approved=True, approver="operator", reason="late change"),
        )


def test_executor_refuses_unsafe_runtime(scenario) -> None:
    settings = Settings(
        simulation_mode=False,
        allow_production_write=False,
        agentteams_enabled=True,
        agentteams_live_required=False,
        agentteams_team_name="energymesh-test-team",
        agentteams_instance_id=None,
        db_path=Path("unsafe.db"),
        evidence_dir=Path("unsafe-evidence"),
        host="127.0.0.1",
        port=8000,
    )
    candidate = DispatchOptimizer().optimize_candidates(scenario)[-1]

    with pytest.raises(RuntimeError, match="SIMULATION_MODE"):
        SimulationExecutor(settings).execute(
            scenario,
            candidate,
            DispatchOptimizer().build_baseline(scenario),
            None,
        )


def test_sensor_conflict_hands_control_to_engineer(orchestrator, scenario) -> None:
    conflicting = apply_operational_change(
        scenario,
        ReoptimizationRequest(
            trigger="TRANSFORMER_SENSOR_CONFLICT",
            transformer_temperature_c=91,
            transformer_redundant_temperature_c=55,
        ),
    )
    task = orchestrator.run(conflicting, trigger="TRANSFORMER_SENSOR_CONFLICT")

    assert task.state == TaskState.HUMAN_HANDOFF
    assert task.plans == []
    assert task.perception is not None
    assert task.perception.conflicts
    assert task.human_handoff_reason is not None
    assert task.evidence_sha256 is not None


def test_execution_deviation_activates_safe_fallback(orchestrator, scenario) -> None:
    deviating = scenario.model_copy(update={"simulation_faults": ["EXECUTION_DEVIATION"]})
    task = orchestrator.run(deviating)
    completed = orchestrator.decide(
        task.task_id,
        ApprovalRequest(
            approved=True,
            approver="test-approver",
            reason="exercise fallback behavior",
        ),
    )

    assert completed.state == TaskState.SAFE_FALLBACK
    assert completed.execution_summary is not None
    assert completed.execution_summary["safe_fallback_activated"] is True
    assert completed.execution_summary["deviation_intervals"] > 0
    assert completed.execution_summary["safe_fallback_policy"]["control_owner"] == (
        "human_operator"
    )
