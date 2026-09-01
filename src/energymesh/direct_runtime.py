from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from energymesh.model_gateway import chat_with_agent_config, describe_model_error
from energymesh.models import (
    AgentMessage,
    AgentRuntimeChatResponse,
    AgentRuntimeStep,
    RuntimeArtifact,
)
from energymesh.storage import EvidenceStore


class DirectLeaderRuntimeError(RuntimeError):
    pass


class DirectLeaderRuntime:
    """Single-agent model chat for normal conversation; never simulates Worker handoff."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
        world_state: dict[str, Any] | None = None,
    ) -> AgentRuntimeChatResponse:
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"direct_task_{uuid4().hex[:12]}"
        self._save_message(
            active_session_id,
            active_task_id,
            "operator",
            "user",
            message,
            {"runtime": "direct_leader", "world_state_loaded": world_state is not None},
        )
        payload = {
            "operator_request": message,
            "world_state": world_state,
            "routing_plan": {
                "mode": "leader_only",
                "workers": [],
                "reason": "Normal chat or state explanation; no Worker task requested.",
            },
        }
        artifact = self.store.save_runtime_artifact(
            RuntimeArtifact(
                artifact_id=f"artifact_{uuid4().hex[:12]}",
                session_id=active_session_id,
                task_id=active_task_id,
                agent_id="team_leader",
                artifact_type="leader_response",
                name="leader_response.md",
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
        config = self.store.get_model_config("team_leader")
        if config is None or not config.api_key:
            raise DirectLeaderRuntimeError("Team Leader model gateway is not configured.")
        prompt = (
            "你是 EnergyMesh Team Leader。像正常 AI 一样直接回答用户。"
            "如果 world_state 存在，基于当前园区负荷、光伏、储能 SOC、购电、限发和成本回答。"
            "用户没有明确要求调度、模拟、预览、采用或执行时，不要点名 Worker，"
            "不要生成多 Agent 流程，不要声称已经控制设备。\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        try:
            response = chat_with_agent_config(config, prompt)
            self.store.update_model_status("team_leader", "正常", None)
        except Exception as error:
            message_text = describe_model_error(error)
            self.store.update_model_status("team_leader", "失败", message_text)
            raise DirectLeaderRuntimeError(message_text) from error
        self._save_message(
            active_session_id,
            active_task_id,
            "team_leader",
            "assistant",
            response,
            {"runtime": "direct_leader"},
        )
        step = AgentRuntimeStep(
            agent_id="team_leader",
            model=config.model,
            response=response,
            input_artifacts=[],
            output_artifact=artifact.artifact_id,
        )
        return AgentRuntimeChatResponse(
            session_id=active_session_id,
            task_id=active_task_id,
            routed_agents=["team_leader"],
            steps=[step],
            messages=self.store.list_agent_messages(active_session_id, limit=100),
            artifacts=[
                item.model_dump(mode="json")
                for item in self.store.list_runtime_artifacts(active_task_id)
            ],
        )

    def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
        world_state: dict[str, Any] | None = None,
    ):
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"direct_task_{uuid4().hex[:12]}"
        yield {
            "type": "runtime_started",
            "runtime": "direct_leader",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": ["team_leader"],
            "world_state_loaded": world_state is not None,
        }
        yield {
            "type": "stage_start",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "index": 0,
            "agent_id": "team_leader",
            "stage": "leader_response",
            "message": "思考中：Team Leader 正在基于当前园区状态直接回答。",
        }
        response = self.chat(message, active_session_id, active_task_id, world_state)
        yield {
            "type": "agent_step",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "index": 0,
            "step": response.steps[-1].model_dump(mode="json"),
        }
        yield {
            "type": "runtime_completed",
            "runtime": "direct_leader",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": ["team_leader"],
            "artifacts": response.artifacts,
        }

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
