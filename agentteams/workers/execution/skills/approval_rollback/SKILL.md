# approval_rollback

Stop a deviating or superseded simulated plan and return control to the Team Leader.

- Input: current task identity, execution/readback evidence and rollback reason.
- Output: safe fallback receipt, evidence digest and a request for Human handoff/new perception.
- Tool: `energymesh-control` with an idempotency key.
- Failure: remain blocked, preserve the last safe state and escalate in Matrix.
- Never increase power or production impact while attempting fallback.
