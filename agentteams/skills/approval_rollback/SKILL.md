# approval_rollback

Use this Skill when a plan requires human approval, is rejected, or execution deviates from plan.

## Inputs

- Current `TaskRecord`
- Audit decision
- `ApprovalRequest`
- Execution summary
- Reoptimization trigger

## Outputs

- `ApprovalRecord`
- Rejected, completed, safe_fallback, or human_handoff state.
- Safe fallback policy.
- Sealed SHA-256 evidence package.

## Calling Conditions

Call when a candidate includes high-risk flexible-load response, when an operator rejects execution, when external data changes, or when execution deviates from plan.

## Dependencies

- `POST /api/tasks/{task_id}/approval`
- `POST /api/tasks/{task_id}/reoptimize`
- `energymesh.storage.EvidenceStore`

## Failure Handling

- Approval is rejected when the task is not awaiting approval.
- Changed child tasks always require a new approval.
- Execution deviation triggers fallback and human handoff.

## Safety Boundary

No old approval can be reused for a changed child task. Fallback commands must not increase risk.

## Validation

API workflow tests cover approval, reoptimization child tasks, and execution summaries.

## Reuse Value

Reusable for other high-risk Agent workflows where automated actions require human confirmation and rollback evidence.
