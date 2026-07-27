# EnergyMesh AgentTeams Assets

This directory contains the AgentTeams-compatible assets for importing EnergyMesh Agents into
Alibaba Cloud AgentTeams.

The local MVP still runs with `EnergyMeshOrchestrator` so the demo works without cloud credentials.
AgentTeams can govern the same roles as a Team Leader plus four Workers:

- `energymesh_team_leader`: task intake, decomposition, progress supervision, human-in-the-loop.
- `perception_worker`: context ingestion, data validation, anomaly and conflict detection.
- `dispatch_worker`: candidate dispatch generation and optimization.
- `audit_worker`: independent safety, business, and improvement audit.
- `execution_worker`: approved command mapping, simulated execution, confirmation, rollback.

Import path mapping:

- Team Leader SOUL/AGENT: `agentteams/team-leader/`
- Worker SOUL/AGENT files: `agentteams/workers/*/`
- Skill package specs: `agentteams/skills/*/SKILL.md`
- Local API manifest: `GET /api/agentteams/manifest`

The current safety boundary is intentionally strict: `SIMULATION_MODE=true`,
`ALLOW_PRODUCTION_WRITE=false`, and real device contact count remains `0`.
