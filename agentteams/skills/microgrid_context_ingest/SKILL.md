# microgrid_context_ingest

Use this Skill when a Worker needs to ingest and validate microgrid context for a scheduling task.

## Inputs

- `Scenario.forecast`: 96 quarter-hour load, PV, tariff, temperature, production minimum-load points.
- `Scenario.site`: SOC, PCS, transformer, grid-interconnection, flexible-load limits.
- `Scenario.alerts`: external faults or business changes.
- `Scenario.device_status`: meter, PV, battery, transformer availability.
- `Scenario.production_plan`: MES-derived production continuity requirements.

## Outputs

- `PerceptionReport.data_complete`
- `quality_score`
- `anomalies`
- `conflicts`
- `objective_priority`
- `required_tools`

## Calling Conditions

Call after `external_energy_snapshot` or equivalent EMS/BMS/PCS/MES input is available, before any optimization or execution attempt.

## Dependencies

- `GET /api/external/snapshot`
- `energymesh.perception.PerceptionAgent`

## Failure Handling

- Missing cadence, production-plan, or device-state data blocks automatic dispatch.
- Redundant transformer sensor conflict triggers human handoff.
- Alerts mark the original task invalid and force task redefinition.

## Safety Boundary

Read-only. This Skill never creates a dispatch command and never writes to equipment.

## Validation

Covered by API and optimizer/audit tests that require 96 valid intervals and conflict handling.

## Reuse Value

Reusable for industrial parks, data centers, charging-storage stations, and virtual-power-plant local scheduling.
