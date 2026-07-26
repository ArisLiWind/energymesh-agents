# EnergyMesh Agents Engineering Rules

## Safety invariants

- This repository is a simulation and decision-support system, not a real-time controller.
- `SIMULATION_MODE=true` and `ALLOW_PRODUCTION_WRITE=false` are mandatory defaults.
- Do not add adapters that contact real EMS, BMS, PCS, SCADA, PLC, switches, or production databases.
- Natural-language or LLM output is never an execution command. Numerical schedules come from a
  deterministic optimizer and must pass the independent auditor.
- A plan that cannot be verified is rejected. Flexible-load actions require explicit human approval.
- Secrets belong only in environment variables. Never place credentials in source, fixtures, logs,
  browser bundles, evidence packages, or documentation.

## Engineering workflow

- Read `STATUS.md`, `ARCHITECTURE.md`, and affected tests before changing behavior.
- Preserve the 15-minute, 96-interval default horizon unless a migration is documented.
- Keep perception, optimizer, auditor, approval gate, and executor as separate trust boundaries.
- Every candidate must be compared against the original EMS policy under the same input forecast.
- Data changes create a new child task and require a new audit and approval; never reuse approval.
- Unresolved missing data or conflicting redundant sensors must stop optimization and hand control
  to a human operator.
- Execution deviation above the verified tolerance must activate the conservative fallback; never
  mark that task completed.
- Add tests for every state transition or safety rule change.
- Run `make format` and `make verify` before handing off a change.
- Update `STATUS.md` when capability, limitations, or verification status changes.
- Never claim AgentTeams, MCP, cloud observability, or physical equipment integration without a
  real, reproducible integration test.

## Product boundary

- Included: park-level economic dispatch, PV self-consumption, battery scheduling, transformer
  capacity, demand charge, flexible-load approval, simulation, audit evidence.
- Excluded: cell-level control, relay protection, power flow, voltage/fault control, and direct
  production writes.
