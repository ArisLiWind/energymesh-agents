# Project Status

Updated: 2026-09-02

## Implemented

- Current AgentTeams `agentteams.io/v1beta1` resource shape with five standalone Worker CRs, one
  Level-2 Human CR, and a Team that references exactly one Team Leader plus four Workers through
  `spec.workerMembers`.
- AgentTeams-native coordination contracts: the Team Leader owns a dynamic dependency-aware task
  DAG, Worker delegation/progress/revision/acceptance, Human intervention and stalled-task
  handling; EnergyMesh APIs are explicitly limited to domain-tool responsibilities.
- Per-Worker packaged Energy Skill assets under each `package` directory, plus implemented
  least-privilege MCP server separation for read, planning, audit and control scopes with Higress
  route assets under `deploy/`.
- Official OpenCEM CUHK-Shenzhen real PV-and-battery microgrid CSV replay, with an unmodified,
  checksum-pinned public measurement partition and explicit CC BY 4.0 attribution.
- Shared `ExternalDataSnapshot` normalization boundary for uploaded history and future read-only
  park connectors; downstream Monitor, perception, optimizer, auditor, and executor are source
  agnostic.
- Deterministic continuous Monitor that keeps AgentTeams asleep during valid V1 operation and wakes
  the team only after a material measured load/PV deviation invalidates the plan.
- Separate V2 audit, human approval, simulated execution, rollback, and SHA-256 evidence controls in
  the operator console. Approval no longer implies execution on the real-data replay path.

- 96-point synthetic park forecast with load, PV, tariff, and battery temperature event.
- External-data simulator for EMS/BMS/PCS/weather/MES-style inputs, covering load, PV, battery
  SOC, tariff, transformer derating, grid interconnection, device faults, and production plan.
- Perception Agent validation for device state, forecast cadence, battery SOC, production plan,
  redundant transformer sensors, original-task validity, missing information, objective priority,
  and required tools.
- Original preconfigured EMS policy baseline replay for every task.
- Three deterministic dispatch profiles using SciPy linear optimization.
- Independent plan audit covering SOC, PCS power, temperature derating, transformer capacity,
  grid-interconnection capacity, production plan, interval power balance, flexible-load
  authorization, and independently recomputed improvement over baseline.
- Explicit task state machine, human approval gate, rejection path, simulation-only executor, and
  post-execution verification.
- SQLite task/trace persistence and SHA-256 JSON evidence packages.
- PolarDB for PostgreSQL DSN support through `POLARDB_DSN` / `DATABASE_URL`, with SQLite fallback
  for offline demo runs.
- FastAPI/OpenAPI service and responsive operator console.
- Live MCP JSON-RPC endpoints at `/mcp/readonly`, `/mcp/planning`, `/mcp/audit` and `/mcp/control`,
  plus `energymesh-mcp` stdio entrypoint for AgentTeams or local MCP clients.
- Vercel Python serverless preview configuration; local `vercel build --yes` completed
  successfully after adding `api/index.py`, `vercel.json`, `.python-version`, and `uv.lock`.
- Open-source `agentscope-ai/AgentTeams` Team Leader, Worker, Skill, MCP, and trace mapping manifest
  at `/api/agentteams/manifest`, with declarative Team/Human resources and Worker packages under
  `agentteams/`.
- Judging alignment, Agent Identity, Skill contracts, MCP-equivalent tool contracts, RAG/context,
  observability, and Alibaba Cloud integration design documents under `docs/`.
- Minimal operator workbench with Insights, signal summary, 96-point load/PV/tariff trend chart,
  candidate plans, audit records, trace, and evidence access.
- Explicit single-Agent chat selection and unselected multi-Agent collaboration modes, driven by
  current scenario, plan, audit, and execution context.
- Change-triggered child tasks that repeat perception, dispatch, audit, approval, and simulation.
- Structured, idempotent simulated EMS/PCS/load commands with 96-interval result confirmation.
- Human-handoff tasks for unresolved sensor conflict and safe-fallback tasks for execution
  deviations above 5%.
- Unit and API integration tests plus Docker and Compose definitions.
- GitHub Codespaces minimal official AgentTeams v1.2.3 proof captured: controller, manager,
  qwenpaw Worker, Team Room, Task Room and `energymesh-demo` Team reached a real
  delegate/ack/submit/accept/complete path. Evidence is recorded in
  `evidence/agentteams-codespaces-proof.md`.
- EnergyMesh FastAPI now treats AgentTeams as the required Worker runtime for dispatch/execution
  intents. It sends the current white-UI `world_state` into the configured Matrix Team Room,
  mirrors AgentTeams events into runtime artifacts, and streams standardized task events back to
  the EnergyMesh UI.
- The white EnergyMesh UI restores and displays the live AgentTeams task mirror with the same
  session/task/project/room IDs, Worker timeline, `dispatch_plan`, audit, approval, execution and
  completion stages.

## Next

- Capture one polished live evidence run where the same `project_id`, EnergyMesh `task_id`,
  Team Room and Task Room are visible in both AgentTeams Element and the white EnergyMesh UI while
  `dispatch_plan` changes the 3D campus preview and execution receipt adopts it.
- Deploy `energymesh-readonly`, `energymesh-planning`, `energymesh-audit` and
  `energymesh-control` behind a real Higress gateway with cloud-side per-Worker consumer
  authorization policies.
- Add authenticated users and signed approval records.
- Add forecast uncertainty bands and rolling-horizon re-optimization.
- Evaluate against multiple seasons and measured-but-anonymized benchmark profiles.
- Verify the MCP endpoints through the target AgentTeams MCP client and capture the same-task
  discovery/call transcript.
- Provision PolarDB for PostgreSQL and verify `POLARDB_DSN` against the target cloud database
  before using Vercel as a long-running shared demo.
- Validate `agentteams/agentteams-resources.yaml` against a live `agentscope-ai/AgentTeams`
  quickstart or Helm deployment.

## Known limitations

- This local Mac host should not be treated as the AgentTeams runtime target; the verified path is
  GitHub Codespaces or another Docker Linux host. Local Python orchestration is still domain
  simulation evidence only, but dispatch/execution chat paths no longer fall back to a fake local
  multi-Agent Worker pipeline when AgentTeams is unavailable.
- The four named EnergyMesh MCP servers are implemented as JSON-RPC endpoints and stdio profiles,
  but the current local checkout has not been deployed behind a real Higress gateway.
- No production database, cloud account, or physical equipment is connected in the local checkout.
- Alibaba Cloud Skills/Nacos/RocketMQ/AgentLoop remain documented integration contracts and
  migration targets; Higress and PolarDB now have repository-level runtime/configuration assets but
  still require cloud provisioning for production proof.
- The model is park-level economic dispatch, not network power flow or real-time control.
- Docker validation depends on Codespaces or a Docker Linux host; absence on the Mac must be
  reported in verification notes.
- Demo approval is suitable only for a local presentation because authentication is not yet present.
- Agent chat can use per-Agent OpenAI-compatible model settings when configured, but the local MVP
  remains safe without model keys; model API keys are stored server-side and masked in public output.

## Verification

- Ruff format and lint: passed.
- mypy strict type check: passed for 14 source modules.
- pytest unit and API integration tests: last full local run passed before the AgentTeams live
  mirror update; rerun required after final Codespaces proof capture.
- Browser workflow: operator page served locally; 96-point trend chart, single-Agent selection,
  and multi-Agent collaboration remain available at the desktop app width.
- Responsive CSS includes 760 px and 470 px breakpoints, but the final mobile visual pass was not
  completed because the in-app browser viewport session timed out; do not claim mobile QA passed.
- Vercel preview build: passed locally with Vercel CLI 54.18.1 after installing `uv` into the local
  virtual environment. Production persistence still requires external storage.
- Docker/Compose runtime build: not run because Docker is not installed on the current host;
  Compose safety fields were parsed and checked.
