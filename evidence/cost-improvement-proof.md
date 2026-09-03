# EnergyMesh Cost Improvement Evidence

Date: 2026-09-03

## Verification Scope

This record captures the EnergyMesh local verification used before demo recording. It proves that a real EnergyMesh task was created from campus telemetry, multiple Workers participated in the dispatch lifecycle, and the selected Agent-generated dispatch plan had a lower computed cost than the original baseline strategy.

Runtime boundary for this run:

- EnergyMesh FastAPI/UI: `http://127.0.0.1:8000`
- Simulation mode: `true`
- Production write: `false`
- Data source: `data/opencem/2025-07-a.csv`
- Normalized telemetry: 717 raw rows into 96 quarter-hour intervals
- Real device contact: none

AgentTeams Element was not part of this specific proof run because the local GitHub CLI token was invalid and Codespaces port forwarding could not be restored at verification time. The EnergyMesh multi-Worker business lifecycle below ran through the local WorkerPool/Skill registry and produced auditable TaskRecord evidence.

## Operator Flow

The demo verification followed this sequence:

```text
1. Open EnergyMesh UI at http://127.0.0.1:8000.
2. Upload or use OpenCEM campus CSV data.
3. Start monitor at interval 20.
4. Step monitor until PV/load change invalidates V1 and wakes the Agent workflow.
5. Inspect the created task, trace, and cost comparison.
```

Equivalent API sequence:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s -X POST 'http://127.0.0.1:8000/api/data/upload?filename=2025-07-a.csv' \
  -H 'Content-Type: text/csv' \
  --data-binary @data/opencem/2025-07-a.csv
curl -s -X POST 'http://127.0.0.1:8000/api/monitor/start?start_interval=20'
curl -s -X POST http://127.0.0.1:8000/api/monitor/step
curl -s http://127.0.0.1:8000/api/tasks/<task_id>
curl -s http://127.0.0.1:8000/api/tasks/<task_id>/cost-comparison
```

## Observed Task

Observed task from the verification run:

```text
task_id: task_9ee3f7da35dd
plan_version: V2
task_state: AWAITING_APPROVAL
trigger: OPENCEM_MONITOR_PLAN_INVALIDATION
```

The task reached the human approval gate only after the Worker chain produced a candidate plan and independent audit.

Observed actors:

```text
orchestrator
team_leader
perception_worker
team_leader
dispatch_worker
team_leader
audit_worker
orchestrator
approval_gate
```

Observed actions:

```text
task_received
worker_dispatched
operational_context_validated
worker_dispatched
candidate_plans_generated
worker_dispatched
independent_policy_audit
audited_plan_selected
human_approval_requested
```

## Cost Comparison

The selected plan came from the Dispatch Worker output and was audited before reaching the approval gate.

```text
baseline_total_cost_yuan: 19.81
optimized_total_cost_yuan: 8.73
savings_yuan: 11.08
savings_percent: 55.93%
optimized_profile: balanced
```

Interpretation:

- The original strategy is the baseline plan generated from the same site forecast, tariff, storage limits, transformer constraints, and production minimum load.
- The optimized strategy is the selected multi-Agent dispatch candidate. It is not a front-end hard-coded cost; it is read from `TaskRecord.baseline_plan` and the selected `DispatchPlan.metrics.total_cost_yuan`.
- The cost comparison is exposed through `GET /api/tasks/{task_id}/cost-comparison` so the UI and demo script can verify the same numbers.

## Campus Change

The monitor invalidated V1 because the live replay detected material PV/load changes in the campus data window. After invalidation:

```text
V1_INVALIDATED
AGENTTEAMS_WOKEN
V2_REPLANNED_AND_AUDITED
```

The system then moved from passive monitoring to a new dispatch task. The new plan lowers purchased electricity cost while respecting SOC, transformer, grid import, and protected production-load constraints. The task remains at the human approval gate until the operator explicitly adopts the audited plan.

## Front-End Recording Checklist

For demo recording, the EnergyMesh UI should show:

- The uploaded campus dataset and 96-interval replay.
- The AgentTeams/current task panel with task ID, worker timeline, and world state loaded.
- Worker messages or compact Worker activity notes for Team Leader, Perception, Dispatch, Audit, and approval gate.
- Cost cards showing baseline cost, Agent optimized cost, savings, and savings percent.
- The approval control before execution, demonstrating that the system does not directly contact production devices.

