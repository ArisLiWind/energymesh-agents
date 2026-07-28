# dispatch_plan_generate

Use this Skill after context is trusted and a dispatch task has been redefined.

## Inputs

- Trusted `Scenario`.
- Site constraints validated by `microgrid_context_ingest`.
- Objective priority from the perception report.
- Original EMS baseline policy.

## Outputs

- Baseline plan.
- Restricted strategy script drafts for economic, balanced, and conservative profiles.
- Script rationale, assumptions, and expected metrics.
- Candidate dispatch plans produced by the scripts.
- 96 quarter-hour charge, discharge, grid import, curtailment, flexible-load shed, and SOC points.
- Metrics for total cost, demand charge, degradation, peak import, PV self-consumption, and shed energy.

## Calling Conditions

Call only when the perception report is complete and no human handoff is required.

## Dependencies

- Restricted strategy-script generator or equivalent policy authoring component.
- `energymesh.optimizer.DispatchOptimizer`
- `scipy.optimize.milp`
- `POST /api/external/dispatch`

## Failure Handling

Script-generation failure, script output infeasibility, or optimization infeasibility raises a workflow error. The Team Leader must not execute a partial plan.

## Safety Boundary

Generates strategy script drafts and plans only. It has no approval, execution, network, filesystem, or equipment-write permission.

## Validation

Tests verify that all generated plans are power-balanced and respect transformer limits. Audit must also statically check scripts and replay them in a sandbox before execution.

## Reuse Value

The script generator or optimizer can be replaced by another deterministic or AI-assisted implementation if it preserves the same restricted script and `DispatchPlan` contracts.
