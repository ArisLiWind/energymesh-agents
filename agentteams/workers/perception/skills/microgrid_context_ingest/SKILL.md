# microgrid_context_ingest

Validate a decision-time energy snapshot through `energymesh-readonly`.

- Input: telemetry, forecast, tariff, SOC, equipment and production references from task spec.
- Output: quality/conflict report, context hash, plan-validity decision and required follow-up.
- Call only for the current non-superseded AgentTeams task.
- Missing or conflicting evidence returns `blocked_for_data`; never repair it silently.
- Read-only: no candidate, approval or execution permission.
