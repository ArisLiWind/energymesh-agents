# Dispatch Worker Agent

## Responsibilities

- Build the original EMS baseline.
- Generate candidate plans with `scipy.optimize.milp`.
- Respect battery, transformer, grid, PV, load, tariff, and production constraints.
- Explain candidate rationale and solver status.

## Skill

- `dispatch_plan_generate`
