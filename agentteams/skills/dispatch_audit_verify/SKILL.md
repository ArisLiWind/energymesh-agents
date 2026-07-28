# dispatch_audit_verify

Use this Skill to independently audit every candidate dispatch plan.

## Inputs

- `Scenario`
- Candidate `DispatchPlan`
- Original EMS baseline `DispatchPlan`

## Outputs

- `AuditReport.decision`: approved, rejected, or requires_approval.
- `AuditFinding[]` with severity and interval.
- Checked deterministic rules.
- Improvement metrics against the original EMS baseline.

## Calling Conditions

Call after `dispatch_plan_generate` returns candidate plans and before any selection or execution.

## Dependencies

- `energymesh.audit.IndependentSafetyAuditor`
- `TaskRecord.audits`

## Failure Handling

- Any critical finding rejects the candidate.
- Flexible-load shed with otherwise valid constraints requires human approval.
- Missing baseline or mismatched scenario must block selection.

## Safety Boundary

Fail closed. Economic benefit never overrides SOC, PCS power, transformer, grid, production, or energy-balance constraints.

## Validation

Tests verify unsafe reserve rejection, human approval gating, and measurable improvement checks.

## Reuse Value

Can be reused as a standalone safety verifier for dispatch plans produced by non-EnergyMesh optimizers.
