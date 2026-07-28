# execution_mapping

Use this Skill only after a plan is approved or explicitly requires no approval.

## Inputs

- Approved selected `DispatchPlan`.
- Matching `AuditReport`.
- Baseline plan for comparison.
- Optional `approval_id`.

## Outputs

- Idempotent EMS grid-import schedule commands.
- Idempotent PCS active-power setpoint commands.
- Idempotent flexible-load controller commands.
- Execution confirmation summary, deviation count, confirmation ratio, fallback status.

## Calling Conditions

Call only after audit approval, or after required human approval has been granted for the current task.

## Dependencies

- `energymesh.simulator.SimulationExecutor`
- `POST /api/tasks/{task_id}/approval`
- `Settings.assert_safe_runtime`

## Failure Handling

- Runtime refuses to run when `SIMULATION_MODE=false` or `ALLOW_PRODUCTION_WRITE=true`.
- Execution deviation above threshold activates safe fallback.

## Safety Boundary

Current MVP is local simulation only. Real device contact count must remain 0.

## Validation

API workflow tests assert completed execution and zero real-device contact.

## Reuse Value

The command schema is ready for future EMS, PCS, and load-controller adapters while preserving idempotency and auditability.
