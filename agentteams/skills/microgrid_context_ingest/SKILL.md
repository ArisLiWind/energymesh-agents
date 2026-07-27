# microgrid_context_ingest

Use this Skill when a Worker needs to ingest and validate microgrid context for a scheduling task.

Inputs: scenario forecast, tariff, device status, production plan, alerts.

Outputs: trusted context, anomalies, conflicts, objective priority, required tools.

Local implementation: `energymesh.perception.PerceptionAgent`.

Safety: read-only; conflict or missing critical data must trigger human handoff.
