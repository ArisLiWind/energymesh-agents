from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from urllib import request as urlrequest
from urllib.error import URLError

from energymesh.models import (
    AgentMessage,
    AgentRuntimeChatResponse,
    AgentRuntimeStep,
    RuntimeArtifact,
)
from energymesh.storage import EvidenceStore


class LiveAgentTeamsRuntimeError(RuntimeError):
    pass

@dataclass(frozen=True)
class AgentTeamsRuntimeStatus:
    ready: bool
    mode: str
    docker_available: bool
    agt_available: bool
    controller_running: bool
    manager_running: bool
    team_room_configured: bool
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
            "team_room_configured": self.team_room_configured,
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
    team_room_configured = bool(os.getenv("AGENTTEAMS_TEAM_ROOM_ID"))
    matrix_bridge_configured = bool(
        os.getenv("AGENTTEAMS_MATRIX_BASE_URL")
        and os.getenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN")
    )
    event_stream_configured = bool(os.getenv("AGENTTEAMS_EVENT_STREAM_URL"))

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
    if not team_room_configured:
        problems.append("AGENTTEAMS_TEAM_ROOM_ID is not configured for the live Team Room bridge.")
    if not matrix_bridge_configured:
        problems.append("AGENTTEAMS_MATRIX_BASE_URL and AGENTTEAMS_MATRIX_ACCESS_TOKEN are required for the live Team Room bridge.")
    if not event_stream_configured:
        problems.append("AGENTTEAMS_EVENT_STREAM_URL is required so UI events come from the real AgentTeams runtime.")

    ready = not problems
    next_steps = [
        "Install Docker Desktop and make `docker ps` work.",
        "Install AgentTeams: AGENTTEAMS_LLM_API_KEY=<key> make install from the official AgentTeams repo, or use its install script.",
        "Apply EnergyMesh resources: agt apply -f agentteams/agentteams-resources.yaml.",
        "Verify: docker ps | grep agentteams; agt get workers; agt get teams.",
        "Export Team Room bridge env: AGENTTEAMS_TEAM_ROOM_ID, AGENTTEAMS_MATRIX_BASE_URL, AGENTTEAMS_MATRIX_ACCESS_TOKEN.",
        "Export AGENTTEAMS_EVENT_STREAM_URL so FastAPI can proxy real Worker and Team Room events.",
    ]
    return AgentTeamsRuntimeStatus(
        ready=ready,
        mode="live_agentteams" if ready else "not_ready",
        docker_available=docker_available,
        agt_available=agt_available,
        controller_running=controller_running,
        manager_running=manager_running,
        team_room_configured=team_room_configured,
        workers=workers,
        teams=teams,
        problems=problems,
        next_steps=[] if ready else next_steps,
    )


class LiveAgentTeamsRuntime:
    """Bridge FastAPI chat to the real AgentTeams Team Room instead of a local fake pipeline."""

    def __init__(self, store: EvidenceStore, team_name: str) -> None:
        self.store = store
        self.team_name = team_name
        self.matrix_base_url = os.getenv("AGENTTEAMS_MATRIX_BASE_URL", "").rstrip("/")
        self.matrix_access_token = os.getenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN", "")
        self.team_room_id = os.getenv("AGENTTEAMS_TEAM_ROOM_ID", "")
        self.event_stream_url = os.getenv("AGENTTEAMS_EVENT_STREAM_URL", "")

    def assert_ready(self) -> AgentTeamsRuntimeStatus:
        status = probe_agentteams_runtime()
        if not status.ready:
            raise LiveAgentTeamsRuntimeError(
                "Live AgentTeams is not ready: "
                + "; ".join(status.problems)
                + " | Next: "
                + " ".join(status.next_steps)
            )
        if not self.matrix_base_url or not self.matrix_access_token:
            raise LiveAgentTeamsRuntimeError(
                "Live AgentTeams Team Room is configured, but Matrix bridge credentials are missing. "
                "Set AGENTTEAMS_MATRIX_BASE_URL and AGENTTEAMS_MATRIX_ACCESS_TOKEN."
            )
        return status

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> AgentRuntimeChatResponse:
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"agentteams_task_{uuid4().hex[:12]}"
        events = list(self.stream_chat(message, active_session_id, active_task_id))
        final = next((event for event in reversed(events) if event["type"] == "runtime_completed"), None)
        if final is None:
            raise LiveAgentTeamsRuntimeError("Live AgentTeams did not complete the Team Room turn.")
        return AgentRuntimeChatResponse(
            session_id=active_session_id,
            task_id=active_task_id,
            routed_agents=final.get("routed_agents", []),
            steps=[
                AgentRuntimeStep(
                    agent_id=step["agent_id"],
                    model="agentscope-ai/AgentTeams",
                    response=step["response"],
                    input_artifacts=[],
                    output_artifact=step.get("output_artifact"),
                )
                for step in final.get("steps", [])
            ],
            messages=self.store.list_agent_messages(active_session_id, limit=100),
            artifacts=[
                artifact.model_dump(mode="json")
                for artifact in self.store.list_runtime_artifacts(active_task_id)
            ],
        )

    def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
    ):
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"agentteams_task_{uuid4().hex[:12]}"
        status = self.assert_ready()
        self._save_message(active_session_id, active_task_id, "operator", "user", message, {"runtime": "live_agentteams"})

        yield {
            "type": "runtime_started",
            "runtime": "live_agentteams",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": ["agentteams_manager"],
        }
        yield {
            "type": "agentteams_runtime_check",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "status": status.model_dump(),
        }
        yield {
            "type": "stage_start",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "index": 0,
            "agent_id": "agentteams_manager",
            "stage": "team_room_submit",
            "message": "Submitting operator message to the live AgentTeams Team Room.",
        }

        self._send_matrix_message(active_session_id, active_task_id, message)
        yield {
            "type": "team_room_message",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "agent_id": "operator",
            "message": message,
        }

        steps: list[dict[str, str]] = []
        for event in self._stream_agentteams_events(active_session_id, active_task_id):
            agent_id = str(event.get("agent_id") or event.get("worker") or "agentteams_manager")
            message_text = str(event.get("message") or event.get("response") or event.get("body") or "")
            if event.get("type") == "agent_step" and message_text:
                step = self._record_step(active_session_id, active_task_id, agent_id, message_text)
                steps.append(step)
                event["step"] = {
                    "agent_id": agent_id,
                    "model": "agentscope-ai/AgentTeams",
                    "response": message_text,
                    "input_artifacts": [],
                    "output_artifact": step["output_artifact"],
                }
            event.setdefault("session_id", active_session_id)
            event.setdefault("task_id", active_task_id)
            yield event

        yield {
            "type": "runtime_completed",
            "runtime": "live_agentteams",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": [step["agent_id"] for step in steps],
            "steps": steps,
            "artifacts": [
                artifact.model_dump(mode="json")
                for artifact in self.store.list_runtime_artifacts(active_task_id)
            ],
        }

    def _send_matrix_message(self, session_id: str, task_id: str, message: str) -> None:
        payload = {
            "msgtype": "m.text",
            "body": message,
            "energymesh": {
                "session_id": session_id,
                "task_id": task_id,
                "team_name": self.team_name,
                "source": "fastapi_runtime_chat",
            },
        }
        txn_id = uuid4().hex
        url = (
            f"{self.matrix_base_url}/_matrix/client/v3/rooms/"
            f"{self.team_room_id}/send/m.room.message/{txn_id}"
            f"?access_token={self.matrix_access_token}"
        )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PUT")
        try:
            with urlrequest.urlopen(req, timeout=12) as response:
                if response.status >= 300:
                    raise LiveAgentTeamsRuntimeError(f"Matrix Team Room send failed with HTTP {response.status}.")
        except URLError as error:
            raise LiveAgentTeamsRuntimeError(f"Matrix Team Room send failed: {error}") from error

    def _stream_agentteams_events(self, session_id: str, task_id: str):
        url = (
            f"{self.event_stream_url}"
            f"{'&' if '?' in self.event_stream_url else '?'}"
            f"session_id={session_id}&task_id={task_id}&team={self.team_name}"
        )
        try:
            with urlrequest.urlopen(url, timeout=60) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line.removeprefix("data: "))
                    if isinstance(event, dict):
                        yield event
        except Exception as error:
            raise LiveAgentTeamsRuntimeError(
                f"AgentTeams event stream failed; cannot prove Worker handoff: {error}"
            ) from error

    def _record_step(self, session_id: str, task_id: str, agent_id: str, response: str) -> dict[str, str]:
        artifact = self.store.save_runtime_artifact(
            RuntimeArtifact(
                artifact_id=f"artifact_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=agent_id,
                artifact_type="agentteams_event",
                name=f"{agent_id}.agentteams-event.json",
                payload={
                    "runtime": "live_agentteams",
                    "team_name": self.team_name,
                    "team_room_id": self.team_room_id,
                    "response": response,
                },
                created_at=datetime.now(UTC),
            )
        )
        self._save_message(session_id, task_id, agent_id, "assistant", response, {"runtime": "live_agentteams"})
        return {"agent_id": agent_id, "response": response, "output_artifact": artifact.artifact_id}

    def _save_message(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any],
    ) -> AgentMessage:
        return self.store.save_agent_message(
            AgentMessage(
                message_id=f"msg_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=agent_id,
                role=role,
                content=content,
                metadata=metadata,
                created_at=datetime.now(UTC),
            )
        )
