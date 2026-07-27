# approval_rollback

Use this Skill when a plan requires human approval, is rejected, or execution deviates from plan.

Inputs: task, audit decision, approval request, execution summary.

Outputs: approval record, rejected state, safe fallback policy, sealed evidence.

Local implementation: `energymesh.orchestrator.EnergyMeshOrchestrator`.

Safety: no old approval can be reused for a changed child task.
