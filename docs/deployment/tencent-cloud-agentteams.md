# Tencent Cloud Live AgentTeams Deployment

EnergyMesh should run Docker and the official `agentscope-ai/AgentTeams` runtime on a cloud VM, not on a developer laptop. The local FastAPI/UI process only talks to the remote Team Room and remote AgentTeams event stream.

## Target Architecture

```text
Browser / FastAPI
  |  /api/runtime/chat/stream
  v
EnergyMesh LiveAgentTeamsRuntime
  |  Matrix room send
  |  AgentTeams event stream proxy
  v
Tencent Cloud CVM
  - Docker
  - official agentscope-ai/AgentTeams
  - agentteams-controller
  - agentteams-manager
  - EnergyMesh Worker containers
  - Team Room / Matrix bridge
```

## Tencent Cloud VM

Recommended minimum for a demo environment:

- Ubuntu 22.04 LTS
- 4 vCPU
- 8 GB RAM
- 80 GB cloud disk
- Security group allowing SSH from your IP
- Security group allowing only the Team Room/event-stream ports required by your bridge

Do not expose Docker or internal AgentTeams control ports publicly.

## Bootstrap

On the Tencent Cloud CVM:

```bash
git clone https://github.com/ArisLiWind/energymesh-agents.git
cd energymesh-agents

export AGENTTEAMS_LLM_API_KEY=<your-model-key>
scripts/tencent_cloud_agentteams_bootstrap.sh
```

The script installs Docker Engine if missing, clones the official AgentTeams repository, installs the upstream runtime, then applies:

```bash
agt apply -f agentteams/agentteams-resources.yaml
```

## Required FastAPI Environment

After AgentTeams creates the Matrix Team Room and event stream bridge, configure the EnergyMesh app:

```bash
export AGENTTEAMS_LIVE_REQUIRED=true
export AGENTTEAMS_TEAM_NAME=energymesh-park-control
export AGENTTEAMS_TEAM_ROOM_ID=<matrix-room-id-created-by-agentteams>
export AGENTTEAMS_MATRIX_BASE_URL=<remote-matrix-client-base-url>
export AGENTTEAMS_MATRIX_ACCESS_TOKEN=<fastapi-bridge-access-token>
export AGENTTEAMS_EVENT_STREAM_URL=<remote-agentteams-event-stream-sse-url>
```

Then verify:

```bash
scripts/agentteams_runtime_check.sh
curl http://127.0.0.1:8000/api/agentteams/runtime
```

`ready=true` is the only acceptable state for claiming live AgentTeams. If `ready=false`, the UI must not show Worker handoff as if it happened.

## Evidence Required For A Real Demo

A successful EnergyMesh demo must capture all of these from the same `task_id`:

1. `agt get teams` shows the EnergyMesh Team is active.
2. `agt get workers` shows Team Leader, Perception, Dispatch, Audit and Execution Workers are running.
3. The user message is submitted to the actual Team Room.
4. Worker join, handoff, progress and result events come from `AGENTTEAMS_EVENT_STREAM_URL`.
5. Energy data is loaded from the uploaded/connected park snapshot, not hard-coded constants.
6. Baseline cost, optimized energy cost, code-labor avoided cost and total savings are stored in evidence.
7. Adoption triggers Execution Worker participation and writes an execution/readback artifact.

If any of these are missing, the system is not allowed to claim live multi-agent dispatch.
