# Project Status

Updated: 2026-07-26

## Implemented

- 96-point synthetic park forecast with load, PV, tariff, and battery temperature event.
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
- FastAPI/OpenAPI service and responsive operator console.
- Locally hosted Three.js interactive park scene with orthographic camera, lighting, shadows,
  drag rotation, wheel zoom, and animated energy-flow particles.
- 96-point load, PV, grid-import, and SOC trend chart plus before/after optimization bars.
- Explicit single-Agent chat selection and unselected multi-Agent collaboration modes, driven by
  current scenario, plan, audit, and execution context.
- Change-triggered child tasks that repeat perception, dispatch, audit, approval, and simulation.
- Structured, idempotent simulated EMS/PCS/load commands with 96-interval result confirmation.
- Human-handoff tasks for unresolved sensor conflict and safe-fallback tasks for execution
  deviations above 5%.
- Unit and API integration tests plus Docker and Compose definitions.

## Next

- Add authenticated users and signed approval records.
- Add forecast uncertainty bands and rolling-horizon re-optimization.
- Evaluate against multiple seasons and measured-but-anonymized benchmark profiles.
- Implement an MCP read-only facade only after its contracts and authentication are tested.
- Integrate AgentTeams only when an actual runtime and reproducible test environment are available.

## Known limitations

- No AgentTeams runtime, MCP connection, cloud service, production database, or physical equipment
  is connected.
- The model is park-level economic dispatch, not network power flow or real-time control.
- Docker validation depends on a host with Docker; absence must be reported in verification notes.
- Demo approval is suitable only for a local presentation because authentication is not yet present.
- Agent chat uses a deterministic local context engine. No LLM, memory service, or natural-language
  control interface is connected.

## Verification

- Ruff format and lint: passed.
- mypy strict type check: passed for 11 source modules.
- pytest unit and API integration tests: 10 passed, including approval-close regression coverage.
- Browser workflow: Three.js scene rendered at 802 x 696 canvas pixels; nonblank screenshot crop
  measured entropy 3.35. Camera zoom, 96-point trend chart, single-Agent selection, and
  multi-Agent collaboration were verified at the desktop app width.
- Responsive CSS includes 760 px and 470 px breakpoints, but the final mobile visual pass was not
  completed because the in-app browser viewport session timed out; do not claim mobile QA passed.
- A wheel build passed before the Three.js console update. The final wheel rebuild was not completed:
  `python -m build` is not installed and the local `pip wheel` process was denied loading Python's
  `mmap` extension by the host code-signing policy. Static source files are present in the package
  directory, but the final artifact contents must be rechecked in CI.
- Docker/Compose runtime build: not run because Docker is not installed on the current host;
  Compose safety fields were parsed and checked.
