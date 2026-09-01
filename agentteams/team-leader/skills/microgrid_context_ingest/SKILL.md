# microgrid_context_ingest

Use for read-only decision-snapshot validation before the Team Leader creates planning tasks.

- Input: snapshot ID, forecast/tariff/constraint versions, telemetry quality and current plan.
- Output: trusted context reference plus `plan_still_valid`, `plan_invalidated`, or
  `blocked_for_data`.
- Tool: `energymesh-readonly` MCP only.
- Failure: keep dependent tasks blocked and create a Human/data-resolution task.
- Boundary: never generate or execute a schedule.
