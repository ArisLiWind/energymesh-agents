# approval_rollback

Use when AgentTeams must create a Human approval task, cancel stale execution, or coordinate
rollback after failed verification.

- Input: AgentTeams task ID, task version, candidate ID, context hash, audit and readback evidence.
- Output: version-bound Human decision or rollback/handoff task references.
- Tool: `energymesh-control` MCP; Human decision remains visible in Matrix.
- Failure: leave execution blocked and escalate with existing evidence.
- Boundary: approval is never inferred and never reused across a new context/version.
