# dispatch_audit_verify

Use this Skill to independently audit every candidate dispatch plan.

Inputs: scenario, candidate plan, original EMS baseline.

Outputs: audit decision, findings, checked rules, improvement metrics.

Local implementation: `energymesh.audit.IndependentSafetyAuditor`.

Safety: fail closed; safety constraints override economic gains.
