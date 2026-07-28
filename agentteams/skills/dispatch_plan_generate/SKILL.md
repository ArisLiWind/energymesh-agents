# dispatch_plan_generate

Use this Skill after context is trusted and a dispatch task has been redefined.

## Inputs

- Trusted `Scenario`.
- Site constraints validated by `microgrid_context_ingest`.
- Objective priority from the perception report.
- Original EMS baseline policy.

## Outputs

- Baseline plan.
- Candidate dispatch plans for economic, balanced, and conservative profiles.
- 96 quarter-hour charge, discharge, grid import, curtailment, flexible-load shed, and SOC points.
- Metrics for total cost, demand charge, degradation, peak import, PV self-consumption, and shed energy.

## Calling Conditions

Call only when the perception report is complete and no human handoff is required.

## Dependencies

- `energymesh.optimizer.DispatchOptimizer`
- `scipy.optimize.milp`
- `POST /api/external/dispatch`

## Failure Handling

Optimization infeasibility raises a workflow error. The Team Leader must not execute a partial plan.

## Safety Boundary

Generates plans only. It has no approval, execution, or equipment-write permission.

## Validation

Tests verify that all generated plans are power-balanced and respect transformer limits.

## Reuse Value

The optimizer can be replaced by another deterministic or AI-assisted solver if it preserves the same `DispatchPlan` contract.
