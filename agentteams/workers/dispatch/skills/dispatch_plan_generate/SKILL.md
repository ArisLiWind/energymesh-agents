# dispatch_plan_generate

Generate versioned baseline and candidate dispatch artifacts through `energymesh-planning`.

- Input: immutable trusted context, objective priorities and original EMS policy.
- Output: 96-point candidates, cost/renewable/production/safety metrics, solver and Skill version.
- Call only after the AgentTeams dependency on trusted context is completed.
- Tool failure or infeasibility returns blocked and no partial command artifact.
- Proposal-only: cannot audit, approve or execute.
