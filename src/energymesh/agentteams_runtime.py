from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentTeamsRuntimeStatus:
    ready: bool
    mode: str
    docker_available: bool
    agt_available: bool
    controller_running: bool
    manager_running: bool
    workers: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "mode": self.mode,
            "docker_available": self.docker_available,
            "agt_available": self.agt_available,
            "controller_running": self.controller_running,
            "manager_running": self.manager_running,
            "workers": self.workers,
            "teams": self.teams,
            "problems": self.problems,
            "next_steps": self.next_steps,
        }


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def probe_agentteams_runtime() -> AgentTeamsRuntimeStatus:
    docker_available = shutil.which("docker") is not None
    agt_available = shutil.which("agt") is not None
    docker_ps = _run(["docker", "ps", "--format", "{{.Names}}"]) if docker_available else ""
    containers = [line.strip() for line in docker_ps.splitlines() if line.strip()]
    controller_running = any("agentteams-controller" in name for name in containers)
    manager_running = any("agentteams-manager" in name for name in containers)
    workers = [name for name in containers if "agentteams-worker" in name]
    teams_output = _run(["agt", "get", "teams"]) if agt_available else ""
    teams = [line for line in teams_output.splitlines() if "energymesh" in line]

    problems: list[str] = []
    if not docker_available:
        problems.append("Docker is not installed or not available in PATH.")
    if not agt_available:
        problems.append("AgentTeams CLI `agt` is not installed or not available in PATH.")
    if docker_available and not controller_running:
        problems.append("agentteams-controller container is not running.")
    if docker_available and not manager_running:
        problems.append("agentteams-manager container is not running.")
    if docker_available and not workers:
        problems.append("No AgentTeams worker containers are running.")
    if agt_available and not teams:
        problems.append("No EnergyMesh AgentTeams team is registered.")

    ready = not problems
    next_steps = [
        "Install Docker Desktop and make `docker ps` work.",
        "Install AgentTeams: AGENTTEAMS_LLM_API_KEY=<key> make install from the official AgentTeams repo, or use its install script.",
        "Apply EnergyMesh resources: agt apply -f agentteams/agentteams-resources.yaml.",
        "Verify: docker ps | grep agentteams; agt get workers; agt get teams.",
    ]
    return AgentTeamsRuntimeStatus(
        ready=ready,
        mode="live_agentteams" if ready else "not_ready",
        docker_available=docker_available,
        agt_available=agt_available,
        controller_running=controller_running,
        manager_running=manager_running,
        workers=workers,
        teams=teams,
        problems=problems,
        next_steps=[] if ready else next_steps,
    )
