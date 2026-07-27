# EnergyMesh AgentTeams Assets

This directory contains the runtime assets for using EnergyMesh Agents with the open-source
`agentscope-ai/AgentTeams` framework:

https://github.com/agentscope-ai/AgentTeams

The local MVP still runs with `EnergyMeshOrchestrator` so the demo works without cloud credentials.
AgentTeams governs the same roles as a Team Leader plus four Workers:

- `energymesh_team_leader`: task intake, decomposition, progress supervision, human-in-the-loop.
- `perception_worker`: context ingestion, data validation, anomaly and conflict detection.
- `dispatch_worker`: candidate dispatch generation and optimization.
- `audit_worker`: independent safety, business, and improvement audit.
- `execution_worker`: approved command mapping, simulated execution, confirmation, rollback.

AgentTeams resource mapping:

- Declarative Team/Human resources: `agentteams/agentteams-resources.yaml`
- Team Leader SOUL/AGENT: `agentteams/team-leader/`
- Worker SOUL/AGENT files: `agentteams/workers/*/`
- Skill package specs: `agentteams/skills/*/SKILL.md`
- Local API manifest: `GET /api/agentteams/manifest`

Local runtime shape:

1. Start EnergyMesh API: `make run`
2. Install AgentTeams from upstream quickstart.
3. Open AgentTeams Element Web at `http://127.0.0.1:18088`.
4. Apply or create the EnergyMesh team from `agentteams/agentteams-resources.yaml`.
5. Use the Team room to route operator requests through the Team Leader and Workers.

The current safety boundary is intentionally strict: `SIMULATION_MODE=true`,
`ALLOW_PRODUCTION_WRITE=false`, and real device contact count remains `0`.
