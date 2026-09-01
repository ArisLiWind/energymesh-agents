from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib import request as urlrequest
from urllib.error import URLError
from uuid import uuid4

from energymesh.models import (
    AgentMessage,
    AgentRuntimeChatResponse,
    AgentRuntimeStep,
    RuntimeArtifact,
)
from energymesh.storage import EvidenceStore


class LiveAgentTeamsRuntimeError(RuntimeError):
    pass


WORKER_TRIGGER_KEYWORDS = {
    "dispatch",
    "schedule",
    "simulate",
    "simulation",
    "execute",
    "execution",
    "approve",
    "adopt",
    "preview",
    "optimize",
    "optimise",
    "rebalance",
    "shift load",
    "reduce cost",
    "reduce waste",
    "调度",
    "模拟",
    "仿真",
    "执行",
    "采用",
    "批准",
    "审批",
    "预览",
    "优化",
    "重规划",
    "调整",
    "削峰",
    "移峰",
    "降低购电",
    "减少购电",
    "减少浪费",
    "降低浪费",
    "储能充电",
    "储能放电",
    "换方案",
    "控制",
}


def requires_agentteams_workers(message: str) -> bool:
    """Return true only when the operator explicitly asks to change/plan operation."""
    normalized = message.lower()
    return any(keyword.lower() in normalized for keyword in WORKER_TRIGGER_KEYWORDS)


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


def _matrix_reachable(base_url: str, access_token: str) -> bool:
    if not base_url or not access_token:
        return False
    url = f"{base_url.rstrip('/')}/_matrix/client/versions?access_token={access_token}"
    try:
        with urlrequest.urlopen(url, timeout=4) as response:
            return response.status < 300
    except Exception:
        return False


def probe_agentteams_runtime() -> AgentTeamsRuntimeStatus:
    runtime_mode = os.getenv("AGENTTEAMS_RUNTIME_MODE", "local_docker").strip().lower()
    matrix_base_url = os.getenv("AGENTTEAMS_MATRIX_BASE_URL", "").rstrip("/")
    matrix_access_token = os.getenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN", "")
    team_room_configured = bool(os.getenv("AGENTTEAMS_TEAM_ROOM_ID"))
    matrix_bridge_configured = bool(matrix_base_url and matrix_access_token)
    if runtime_mode == "remote_matrix":
        matrix_ok = _matrix_reachable(matrix_base_url, matrix_access_token)
        remote_workers = [
            item.strip()
            for item in os.getenv("AGENTTEAMS_REMOTE_WORKERS", "energy-dispatcher").split(",")
            if item.strip()
        ]
        remote_team = os.getenv("AGENTTEAMS_TEAM_NAME", "energymesh-demo")
        problems: list[str] = []
        if not team_room_configured:
            problems.append("AGENTTEAMS_TEAM_ROOM_ID is not configured for the live Team Room bridge.")
        if not matrix_bridge_configured:
            problems.append(
                "AGENTTEAMS_MATRIX_BASE_URL and AGENTTEAMS_MATRIX_ACCESS_TOKEN are required "
                "for the remote Matrix bridge."
            )
        if matrix_bridge_configured and not matrix_ok:
            problems.append("Remote AgentTeams Matrix client API is not reachable.")
        if not remote_workers:
            problems.append("AGENTTEAMS_REMOTE_WORKERS must list at least one verified Running Worker.")
        ready = not problems
        return AgentTeamsRuntimeStatus(
            ready=ready,
            mode="remote_matrix_agentteams" if ready else "not_ready",
            docker_available=False,
            agt_available=False,
            controller_running=matrix_ok,
            manager_running=matrix_ok,
            team_room_configured=team_room_configured,
            workers=remote_workers if matrix_ok else [],
            teams=[remote_team] if matrix_ok else [],
            problems=problems,
            next_steps=[] if ready else [
                "Start the Codespace or remote AgentTeams runtime.",
                "Forward or expose Matrix: AGENTTEAMS_MATRIX_BASE_URL must answer /_matrix/client/versions.",
                "Export AGENTTEAMS_TEAM_ROOM_ID, AGENTTEAMS_MATRIX_ACCESS_TOKEN and AGENTTEAMS_REMOTE_WORKERS.",
            ],
        )

    docker_available = shutil.which("docker") is not None
    docker_ps = _run(["docker", "ps", "--format", "{{.Names}}"]) if docker_available else ""
    containers = [line.strip() for line in docker_ps.splitlines() if line.strip()]
    controller_running = any("agentteams-controller" in name for name in containers)
    manager_running = any("agentteams-manager" in name for name in containers)
    workers = [
        name
        for name in containers
        if any(
            marker in name
            for marker in (
                "agentteams-worker",
                "agentteams-copaw-worker",
                "agentteams-hermes-worker",
            )
        )
    ]
    host_agt_available = shutil.which("agt") is not None
    agt_available = host_agt_available or controller_running
    if host_agt_available:
        teams_output = _run(["agt", "get", "teams"])
    elif controller_running:
        teams_output = _run(["docker", "exec", "agentteams-controller", "agt", "get", "teams"])
    else:
        teams_output = ""
    teams = [line for line in teams_output.splitlines() if "energymesh" in line]
    problems: list[str] = []
    if not docker_available:
        problems.append("Docker is not installed or not available in PATH.")
    if not agt_available:
        problems.append("AgentTeams CLI `agt` is not available on the host or inside agentteams-controller.")
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

    ready = not problems
    next_steps = [
        "Install Docker Desktop and make `docker ps` work.",
        "Install AgentTeams: AGENTTEAMS_LLM_API_KEY=<key> make install from the official AgentTeams repo, or use its install script.",
        "Apply EnergyMesh resources: agt apply -f agentteams/agentteams-resources.yaml.",
        "Verify: docker ps | grep agentteams; agt get workers; agt get teams.",
        "Export Team Room bridge env: AGENTTEAMS_TEAM_ROOM_ID, AGENTTEAMS_MATRIX_BASE_URL, AGENTTEAMS_MATRIX_ACCESS_TOKEN.",
        "Optional: export AGENTTEAMS_EVENT_STREAM_URL; otherwise FastAPI polls Matrix Team Room messages directly.",
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

    def __init__(
        self,
        store: EvidenceStore,
        team_name: str,
        world_state_provider: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.store = store
        self.team_name = team_name
        self.world_state_provider = world_state_provider
        self.matrix_base_url = os.getenv("AGENTTEAMS_MATRIX_BASE_URL", "").rstrip("/")
        self.matrix_access_token = os.getenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN", "")
        self.team_room_id = os.getenv("AGENTTEAMS_TEAM_ROOM_ID", "")
        self.project_id = os.getenv("AGENTTEAMS_PROJECT_ID", "")
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
        world_state = self._world_state()
        status = self.assert_ready()
        self._save_message(
            active_session_id,
            active_task_id,
            "operator",
            "user",
            message,
            {"runtime": "live_agentteams", "world_state": world_state},
        )

        yield {
            "type": "runtime_started",
            "runtime": "live_agentteams",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": ["agentteams_manager"],
            "world_state_loaded": world_state is not None,
        }
        self._mirror_event(
            active_session_id,
            active_task_id,
            {
                "type": "task_created",
                "agent_id": "agentteams_manager",
                "message": "EnergyMesh 请求已进入真实 AgentTeams runtime。",
                "project_id": self.project_id or None,
                "team_room_id": self.team_room_id,
                "world_state_loaded": world_state is not None,
            },
        )
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
            "message": "思考中：正在把操作员消息和右侧园区 world_state 发送到真实 AgentTeams Team Room。",
        }
        if world_state:
            artifact = self.store.save_runtime_artifact(
                RuntimeArtifact(
                    artifact_id=f"artifact_{uuid4().hex[:12]}",
                    session_id=active_session_id,
                    task_id=active_task_id,
                    agent_id="agentteams_manager",
                    artifact_type="world_state",
                    name="world_state.json",
                    payload=world_state,
                    created_at=datetime.now(UTC),
                )
            )
            yield {
                "type": "world_state_loaded",
                "session_id": active_session_id,
                "task_id": active_task_id,
                "agent_id": "agentteams_manager",
                "artifact_id": artifact.artifact_id,
                "message": "右侧 CSV/沙盘状态已作为 AgentTeams world_state 输入。",
                "world_state": world_state,
            }
            self._mirror_event(
                active_session_id,
                active_task_id,
                {
                    "type": "artifact_created",
                    "agent_id": "agentteams_manager",
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": "world_state",
                    "message": "右侧 CSV/沙盘状态已作为真实 world_state 输入 AgentTeams。",
                    "project_id": self.project_id or None,
                    "world_state": world_state,
                },
            )

        self._send_matrix_message(active_session_id, active_task_id, message, world_state)
        yield {
            "type": "team_room_message",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "agent_id": "operator",
            "project_id": self.project_id or None,
            "team_room_id": self.team_room_id,
            "message": message,
        }

        steps: list[dict[str, str]] = []
        for event in self._stream_agentteams_events(active_session_id, active_task_id):
            agent_id = str(event.get("agent_id") or event.get("worker") or "agentteams_manager")
            message_text = str(event.get("message") or event.get("response") or event.get("body") or "")
            if event.get("type") in {"worker_joined", "handoff", "agent_joined"}:
                event["type"] = "worker_joined"
                event.setdefault("message", f"{agent_id} 加入真实 AgentTeams Team Room。")
            normalized_event = self._standardize_event(event, agent_id, message_text)
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
            event["standard_event"] = normalized_event
            self._mirror_event(active_session_id, active_task_id, normalized_event)
            yield event

        completed_event = self._mirror_event(
            active_session_id,
            active_task_id,
            {
                "type": "completed",
                "agent_id": "agentteams_manager",
                "message": "真实 AgentTeams 事件流已完成本次 EnergyMesh 任务同步。",
                "project_id": self.project_id or None,
                "team_room_id": self.team_room_id,
                "routed_agents": [step["agent_id"] for step in steps],
            },
        )
        yield {
            "type": "runtime_completed",
            "runtime": "live_agentteams",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": [step["agent_id"] for step in steps],
            "steps": steps,
            "standard_event": completed_event,
            "artifacts": [
                artifact.model_dump(mode="json")
                for artifact in self.store.list_runtime_artifacts(active_task_id)
            ],
        }

    def _send_matrix_message(
        self,
        session_id: str,
        task_id: str,
        message: str,
        world_state: dict[str, Any] | None,
    ) -> None:
        body = message
        if world_state:
            body = (
                f"{message}\n\n"
                "[EnergyMesh world_state]\n"
                f"{json.dumps(world_state, ensure_ascii=False, separators=(',', ':'))}"
            )
        payload = {
            "msgtype": "m.text",
            "body": body,
            "energymesh": {
                "session_id": session_id,
                "task_id": task_id,
                "project_id": self.project_id or None,
                "team_name": self.team_name,
                "source": "fastapi_runtime_chat",
                "intent": "dispatch_or_execution",
                "world_state": world_state,
                "required_workers": [
                    "perception_worker",
                    "dispatch_worker",
                    "audit_worker",
                    "execution_worker",
                ],
                "response_contract": {
                    "must_use_world_state": True,
                    "must_emit_verifiable_plan": True,
                    "must_wait_for_human_adoption_before_execution": True,
                    "ui_expected_events": [
                        "worker_joined",
                        "agent_step",
                        "dispatch_plan",
                        "audit_verdict",
                        "execution_receipt",
                    ],
                },
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
        if not self.event_stream_url:
            yield from self._poll_matrix_team_room(session_id, task_id)
            return
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

    def _poll_matrix_team_room(self, session_id: str, task_id: str):
        import time

        seen: set[str] = set()
        deadline = time.time() + int(os.getenv("AGENTTEAMS_MATRIX_POLL_TIMEOUT", "90"))
        yielded = 0
        while time.time() < deadline:
            url = (
                f"{self.matrix_base_url}/_matrix/client/v3/rooms/"
                f"{self.team_room_id}/messages?dir=b&limit=30"
                f"&access_token={self.matrix_access_token}"
            )
            try:
                with urlrequest.urlopen(url, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:
                time.sleep(2)
                continue
            messages = list(reversed(payload.get("chunk", [])))
            for item in messages:
                event_id = str(item.get("event_id") or "")
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                if item.get("type") != "m.room.message":
                    continue
                content = item.get("content") or {}
                body = str(content.get("body") or "")
                sender = str(item.get("sender") or "")
                if not body or sender.startswith("@admin:"):
                    continue
                if session_id not in body and task_id not in body and "EnergyMesh" not in body and "dispatch" not in body.lower() and "调度" not in body:
                    continue
                yielded += 1
                yield {
                    "type": "agent_step",
                    "agent_id": sender.split(":", 1)[0].removeprefix("@") or "agentteams_worker",
                    "worker": sender,
                    "body": body,
                    "event_id": event_id,
                    "project_id": self.project_id or None,
                    "team_room_id": self.team_room_id,
                    "source": "matrix_team_room_poll",
                }
                if any(token in body for token in ("TASK_COMPLETED", "项目状态报告", "Project Status Report")):
                    return
            time.sleep(2)
        if yielded == 0:
            yield {
                "type": "step_started",
                "agent_id": "agentteams_manager",
                "message": "已提交到真实 AgentTeams Team Room；Matrix 轮询暂未看到 Worker 回复。",
                "project_id": self.project_id or None,
                "team_room_id": self.team_room_id,
                "source": "matrix_team_room_poll",
            }

    def _world_state(self) -> dict[str, Any] | None:
        if not self.world_state_provider:
            return None
        return self.world_state_provider()

    def _standardize_event(
        self, event: dict[str, Any], agent_id: str, message_text: str
    ) -> dict[str, Any]:
        raw_type = str(event.get("type") or "")
        lowered = message_text.lower()
        embedded = self._extract_embedded_payload(message_text)
        event_type = "step_started"
        if str(embedded.get("type") or embedded.get("event") or "") in {
            "dispatch_plan",
            "audit_verdict",
            "awaiting_approval",
            "execution_receipt",
        }:
            event_type = str(embedded.get("type") or embedded.get("event"))
        elif raw_type in {"worker_joined", "handoff", "agent_joined"}:
            event_type = "worker_joined"
        elif raw_type in {"tool_call", "tool_started"} or "execute_" in lowered or "teamharness__" in lowered:
            event_type = "tool_call"
        elif "dispatch_plan" in lowered or "调度方案" in message_text or "dispatch plan" in lowered:
            event_type = "dispatch_plan"
        elif "audit" in lowered or "审核" in message_text or "pass" in lowered:
            event_type = "audit_verdict"
        elif "awaiting approval" in lowered or "等待人工" in message_text or "采用方案" in message_text:
            event_type = "awaiting_approval"
        elif "execution_receipt" in lowered or "执行完成" in message_text:
            event_type = "execution_receipt"
        elif raw_type in {"runtime_error", "failed"}:
            event_type = "failed"
        plan_payload = self._extract_dispatch_payload(event, embedded, message_text)
        return {
            "type": event_type,
            "raw_type": raw_type,
            "agent_id": agent_id,
            "worker_id": event.get("worker") or agent_id,
            "message": message_text or str(event.get("message") or event.get("stage") or raw_type),
            "project_id": (
                event.get("project_id") or embedded.get("project_id") or self.project_id or None
            ),
            "task_room_id": (
                event.get("task_room_id") or embedded.get("task_room_id") or event.get("room_id")
            ),
            "team_room_id": self.team_room_id,
            **plan_payload,
            "payload": event,
        }

    def _extract_embedded_payload(self, message_text: str) -> dict[str, Any]:
        candidates = [message_text]
        candidates.extend(
            re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", message_text, flags=re.DOTALL)
        )
        candidates.extend(
            re.findall(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", message_text, flags=re.DOTALL)
        )
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _extract_dispatch_payload(
        self, event: dict[str, Any], embedded: dict[str, Any], message_text: str
    ) -> dict[str, Any]:
        source = embedded or event
        plan = source.get("dispatch_plan") or source.get("plan") or source.get("candidate_plan")
        if not isinstance(plan, dict):
            plan = {}
        metrics = source.get("metrics") or plan.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        lowered = message_text.lower()
        def number_from(*keys: str) -> float | None:
            for key in keys:
                value = metrics.get(key) or plan.get(key) or source.get(key)
                if isinstance(value, int | float):
                    return float(value)
            return None
        savings_yuan = number_from(
            "savings_yuan", "cost_savings_yuan", "purchase_cost_savings_yuan"
        )
        savings_percent = number_from("savings_percent", "cost_savings_percent")
        waste_drop = number_from(
            "waste_reduction_kwh", "curtailment_reduction_kwh", "pv_waste_reduction_kwh"
        )
        manual_drop = number_from(
            "manual_dispatch_cost_reduction_yuan", "labor_cost_savings_yuan"
        )
        if savings_yuan is None:
            match = re.search(
                r"(?:节省|saving[s]?)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:元|yuan|rmb|¥)?",
                lowered,
            )
            if match:
                savings_yuan = float(match.group(1))
        value = {
            "dispatch_plan": plan or None,
            "impact": {
                "purchase_cost_savings_yuan": savings_yuan,
                "purchase_cost_savings_percent": savings_percent,
                "energy_waste_reduction_kwh": waste_drop,
                "manual_dispatch_cost_reduction_yuan": manual_drop,
            },
        }
        return value

    def _mirror_event(
        self, session_id: str, task_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            **event,
            "runtime": "live_agentteams",
            "team_name": self.team_name,
            "task_id": task_id,
            "session_id": session_id,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        artifact = self.store.save_runtime_artifact(
            RuntimeArtifact(
                artifact_id=f"artifact_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=str(payload.get("agent_id") or "agentteams_manager"),
                artifact_type="agentteams_task_event",
                name=f"{payload['type']}.agentteams-task-event.json",
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
        return {**payload, "artifact_id": artifact.artifact_id}

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
