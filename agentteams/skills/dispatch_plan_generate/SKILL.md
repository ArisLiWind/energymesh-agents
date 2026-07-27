# dispatch_plan_generate

Use this Skill after context is trusted and a dispatch task has been redefined.

Inputs: scenario, site constraints, validated objective priority.

Outputs: baseline policy and candidate dispatch plans.

Local implementation: `energymesh.optimizer.DispatchOptimizer`.

Safety: generates plans only; no device execution.
