from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    simulation_mode: bool
    allow_production_write: bool
    agentteams_enabled: bool
    agentteams_live_required: bool
    agentteams_team_name: str
    agentteams_instance_id: str | None
    db_path: Path
    evidence_dir: Path
    host: str
    port: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            simulation_mode=_bool_env("SIMULATION_MODE", True),
            allow_production_write=_bool_env("ALLOW_PRODUCTION_WRITE", False),
            agentteams_enabled=_bool_env("AGENTTEAMS_ENABLED", True),
            agentteams_live_required=_bool_env("AGENTTEAMS_LIVE_REQUIRED", True),
            agentteams_team_name=os.getenv(
                "AGENTTEAMS_TEAM_NAME", "energymesh-park-control"
            ),
            agentteams_instance_id=os.getenv("AGENTTEAMS_INSTANCE_ID") or None,
            db_path=Path(os.getenv("ENERGYMESH_DB_PATH", "./var/energymesh.db")),
            evidence_dir=Path(os.getenv("ENERGYMESH_EVIDENCE_DIR", "./runs")),
            host=os.getenv("ENERGYMESH_HOST", "0.0.0.0"),
            port=int(os.getenv("ENERGYMESH_PORT", "8000")),
        )

    def assert_safe_runtime(self) -> None:
        if not self.simulation_mode:
            raise RuntimeError("SIMULATION_MODE must remain true in the community MVP")
        if self.allow_production_write:
            raise RuntimeError(
                "ALLOW_PRODUCTION_WRITE must remain false in the community MVP"
            )
