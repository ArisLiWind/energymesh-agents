# Security Model

## Default-deny execution

The application starts only when `SIMULATION_MODE=true` and `ALLOW_PRODUCTION_WRITE=false`.
`SimulationExecutor` checks the same invariants immediately before replay. This repository ships no
production write adapter and makes no request to EMS, BMS, PCS, SCADA, PLC, or field equipment.

## Decision integrity

- Inputs are validated by strict Pydantic schemas.
- Numerical dispatch comes from a deterministic optimizer, not free-form natural language.
- Every candidate passes an independent, fail-closed rule audit.
- The auditor independently recomputes plan and original-policy costs before accepting improvement.
- Any flexible-load reduction requires a named human approval with a reason.
- Approval is bound to one task and cannot be reused after the state changes.
- Rejected plans cannot reach the executor.
- Unresolved redundant-sensor conflict stops before optimization and creates a human-handoff
  evidence package.
- Execution commands are structured, idempotent, task-bound records; this MVP dispatches them only
  to local simulated EMS, PCS, and flexible-load adapters and confirms all 96 intervals.
- Actual-versus-plan deviation above 5% changes the terminal state to `safe_fallback`, sets battery
  and load-shed commands to zero in the fallback declaration, and returns ownership to an operator.

## Evidence

Task state and append-only event sequence numbers are stored in SQLite. Terminal outcomes are
written atomically to JSON and sealed with SHA-256 over a canonical representation. This detects
accidental or unsophisticated modification; it is not a digital signature or external immutable
ledger.

## Secrets and data

No secret is required for the local MVP. Future credentials must be supplied only through
environment variables or a secret manager and must never be emitted into traces or evidence.
Committed demo data is synthetic and contains no customer or production data.

## Known limitations

- Authentication and role-based access control are not implemented; bind the MVP to trusted local
  or isolated demo environments only.
- SQLite audit events are locally mutable by a host administrator.
- No external policy engine, signed approval, SBOM, or vulnerability scanner is configured.
- The optimizer and simulator are planning models, not safety-certified control software.

Report security issues privately to the repository maintainers. Do not include real site data,
credentials, or device endpoints in a report.
