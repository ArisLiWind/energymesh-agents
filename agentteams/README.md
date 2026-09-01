# EnergyMesh on official AgentTeams

This directory is the AgentTeams control-plane package for EnergyMesh. The supported upstream is
[`agentscope-ai/AgentTeams`](https://github.com/agentscope-ai/AgentTeams), using
`agentteams.io/v1beta1` resources.

## Ownership boundary

AgentTeams owns:

- Worker, Human and Team resources and lifecycle;
- Matrix identities, Team Room communication and Human intervention;
- Team Leader task decomposition, delegation, progress, heartbeat, revision and acceptance;
- shared task specs, plans, progress and result artifacts in AgentTeams object storage;
- per-Worker model/MCP identity and Higress authorization.

EnergyMesh FastAPI owns deterministic domain tools only: snapshot normalization, optimization,
independent constraint recomputation, approval validation, simulation, readback and evidence.
Calling these APIs in a Python sequence is not AgentTeams collaboration evidence.

## Resources

`agentteams-resources.yaml` declares five standalone Worker CRs, one Level-2 Human and one Team CR.
The Team references Workers through `spec.workerMembers` and contains exactly one
`role: team_leader`, matching the current AgentTeams API.

Before apply, the following MCP servers must exist in Higress and be authorized per Worker:

- `energymesh-readonly`: snapshots, task/context and evidence reads;
- `energymesh-planning`: baseline and candidate generation;
- `energymesh-audit`: independent verification;
- `energymesh-control`: approval validation, simulation, readback and rollback.

The repository does not yet ship those as live MCP servers. Current FastAPI/OpenAPI endpoints are
domain contracts, not a substitute for MCP discovery, Higress consumer identity or framework-level
authorization.

## Required runtime proof

A valid competition run must show all of the following from the same task:

1. `agt apply` accepts the Worker, Human and Team resources.
2. Team status is `Active`, Leader is ready and all four Workers are ready.
3. The Human submits the dispatch goal in Matrix to the Team Leader.
4. The Leader creates shared task specs and delegates ready tasks dynamically.
5. Workers acknowledge, create plans, publish progress and write results in shared storage.
6. External changes cause old work to be superseded and the task DAG to be revised.
7. A high-risk branch creates a real Human approval event in the Team Room.
8. Worker/tool failure demonstrates retry, reassignment, compensation or Human escalation.
9. Final AgentTeams task state, EnergyMesh decision ledger and evidence digest share the same IDs.

Until this proof is captured, the assets are an AgentTeams integration package pending live apply,
not a completed AgentTeams runtime integration.
