from __future__ import annotations

from pathlib import Path

import pytest

from energymesh.audit import IndependentSafetyAuditor
from energymesh.config import Settings
from energymesh.demo import load_demo_scenario
from energymesh.optimizer import DispatchOptimizer
from energymesh.orchestrator import EnergyMeshOrchestrator
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        simulation_mode=True,
        allow_production_write=False,
        agentteams_enabled=True,
        agentteams_team_name="energymesh-test-team",
        agentteams_instance_id=None,
        db_path=tmp_path / "energymesh.db",
        evidence_dir=tmp_path / "evidence",
        host="127.0.0.1",
        port=8000,
    )


@pytest.fixture
def orchestrator(settings: Settings) -> EnergyMeshOrchestrator:
    return EnergyMeshOrchestrator(
        perception=PerceptionAgent(),
        optimizer=DispatchOptimizer(),
        auditor=IndependentSafetyAuditor(),
        executor=SimulationExecutor(settings),
        store=EvidenceStore(settings.db_path, settings.evidence_dir),
    )


@pytest.fixture
def scenario():
    return load_demo_scenario()
