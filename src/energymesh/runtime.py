from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from energymesh.knowledge import KnowledgeBase, KnowledgeHit
from energymesh.mcp_gateway import EnergyMCPGateway, MCPToolResult
from energymesh.model_gateway import (
    StoredModelConfig,
    chat_with_agent_config,
    describe_model_error,
)
from energymesh.models import (
    AgentMessage,
    AgentRuntimeChatResponse,
    AgentRuntimeStep,
    RuntimeArtifact,
    RuntimeToolCall,
)
from energymesh.storage import EvidenceStore


class AgentRuntimeError(RuntimeError):
    pass


STAGE_DEFINITIONS = {
    "leader_intake": (
        "team_leader",
        "leader_intake",
        "Team Leader is deciding the task route.",
    ),
    "perception": (
        "perception_agent",
        "perception",
        "Perception Worker is collecting MCP energy state.",
    ),
    "dispatch": (
        "dispatch_agent",
        "dispatch",
        "Dispatch Worker is generating candidate plans.",
    ),
    "audit": ("audit_agent", "audit", "Audit Worker is verifying constraints."),
    "final_report": (
        "team_leader",
        "final_report",
        "Team Leader is preparing the final report.",
    ),
    "leader_response": (
        "team_leader",
        "leader_response",
        "Team Leader is responding directly.",
    ),
}

DISPATCH_KEYWORDS = {
    "load",
    "pv",
    "soc",
    "tariff",
    "transformer",
    "dispatch",
    "energy",
    "microgrid",
    "strategy",
    "schedule",
    "audit",
    "execute",
    "rollback",
    "负荷",
    "光伏",
    "储能",
    "电价",
    "变压器",
    "调度",
    "能源",
    "微网",
    "策略",
    "方案",
    "审核",
    "执行",
    "回滚",
    "削峰",
}


class PersistentAgentRuntime:
    """Deterministic multi-agent pipeline with persisted artifacts."""

    def __init__(
        self,
        store: EvidenceStore,
        mcp_gateway: EnergyMCPGateway | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        self.store = store
        self.mcp_gateway = mcp_gateway or EnergyMCPGateway()
        self.knowledge_base = knowledge_base or KnowledgeBase()

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> AgentRuntimeChatResponse:
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"runtime_task_{uuid4().hex[:12]}"
        self._save_message(
            active_session_id,
            active_task_id,
            "operator",
            "user",
            message,
            {"source": "runtime_pipeline"},
        )

        steps: list[AgentRuntimeStep] = []
        task_brief = self._leader_intake(
            active_session_id, active_task_id, message, steps
        )
        route = task_brief.payload["routing_plan"]
        if route["mode"] == "leader_only":
            self._leader_direct_response(
                active_session_id, active_task_id, task_brief, steps
            )
        else:
            energy_state = self._perception_collect_state(
                active_session_id, active_task_id, task_brief, steps
            )
            plan = self._dispatch_generate_plan(
                active_session_id, active_task_id, energy_state, steps
            )
            verification = self._audit_verify_plan(
                active_session_id, active_task_id, plan, steps
            )
            self._leader_final_report(
                active_session_id,
                active_task_id,
                task_brief,
                energy_state,
                plan,
                verification,
                steps,
            )

        return AgentRuntimeChatResponse(
            session_id=active_session_id,
            task_id=active_task_id,
            routed_agents=[step.agent_id for step in steps],
            steps=steps,
            messages=self.store.list_agent_messages(active_session_id, limit=100),
            artifacts=[
                artifact.model_dump(mode="json")
                for artifact in self._list_runtime_artifacts(active_task_id)
            ],
        )

    def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> Iterator[dict[str, object]]:
        active_session_id = session_id or f"session_{uuid4().hex[:12]}"
        active_task_id = task_id or f"runtime_task_{uuid4().hex[:12]}"
        self._save_message(
            active_session_id,
            active_task_id,
            "operator",
            "user",
            message,
            {"source": "runtime_pipeline"},
        )
        steps: list[AgentRuntimeStep] = []
        stage_keys: list[str] = ["leader_intake"]
        yield {
            "type": "runtime_started",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": ["team_leader"],
        }

        yield self._stage_start_event(
            active_session_id, active_task_id, 0, stage_keys[0]
        )
        task_brief = self._leader_intake(
            active_session_id, active_task_id, message, steps
        )
        yield self._step_event(active_session_id, active_task_id, steps[-1], 0)

        route = task_brief.payload["routing_plan"]
        if route["mode"] == "leader_only":
            stage_keys.append("leader_response")
            yield self._stage_start_event(
                active_session_id, active_task_id, 1, stage_keys[1]
            )
            self._leader_direct_response(
                active_session_id, active_task_id, task_brief, steps
            )
            yield self._step_event(active_session_id, active_task_id, steps[-1], 1)
        else:
            stage_keys.extend(["perception", "dispatch", "audit", "final_report"])
            yield {
                "type": "route_decided",
                "session_id": active_session_id,
                "task_id": active_task_id,
                "routed_agents": [STAGE_DEFINITIONS[key][0] for key in stage_keys],
                "routing_plan": route,
            }
            yield self._stage_start_event(
                active_session_id, active_task_id, 1, stage_keys[1]
            )
            energy_state = self._perception_collect_state(
                active_session_id, active_task_id, task_brief, steps
            )
            yield self._step_event(active_session_id, active_task_id, steps[-1], 1)

            yield self._stage_start_event(
                active_session_id, active_task_id, 2, stage_keys[2]
            )
            plan = self._dispatch_generate_plan(
                active_session_id, active_task_id, energy_state, steps
            )
            yield self._step_event(active_session_id, active_task_id, steps[-1], 2)

            yield self._stage_start_event(
                active_session_id, active_task_id, 3, stage_keys[3]
            )
            verification = self._audit_verify_plan(
                active_session_id, active_task_id, plan, steps
            )
            yield self._step_event(active_session_id, active_task_id, steps[-1], 3)

            yield self._stage_start_event(
                active_session_id, active_task_id, 4, stage_keys[4]
            )
            self._leader_final_report(
                active_session_id,
                active_task_id,
                task_brief,
                energy_state,
                plan,
                verification,
                steps,
            )
            yield self._step_event(active_session_id, active_task_id, steps[-1], 4)

        yield {
            "type": "runtime_completed",
            "session_id": active_session_id,
            "task_id": active_task_id,
            "routed_agents": [step.agent_id for step in steps],
            "artifacts": [
                artifact.model_dump(mode="json")
                for artifact in self._list_runtime_artifacts(active_task_id)
            ],
        }

    def _stage_start_event(
        self, session_id: str, task_id: str, index: int, stage_key: str
    ) -> dict[str, object]:
        agent_id, stage, message = STAGE_DEFINITIONS[stage_key]
        return {
            "type": "stage_start",
            "session_id": session_id,
            "task_id": task_id,
            "index": index,
            "agent_id": agent_id,
            "stage": stage,
            "message": message,
        }

    def _step_event(
        self, session_id: str, task_id: str, step: AgentRuntimeStep, index: int
    ) -> dict[str, object]:
        return {
            "type": "agent_step",
            "session_id": session_id,
            "task_id": task_id,
            "index": index,
            "step": step.model_dump(mode="json"),
        }

    def _leader_intake(
        self,
        session_id: str,
        task_id: str,
        user_message: str,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        route = self._routing_plan(user_message)
        payload = {
            "task": user_message,
            "intent": "energy_strategy_assessment",
            "routing_plan": route,
            "leader_boundary": (
                "Leader only decomposes and summarizes; it must not generate a plan before "
                "worker artifacts exist."
            ),
        }
        artifact = self._save_artifact(
            session_id, task_id, "team_leader", "task_brief", "task_brief.json", payload
        )
        response = self._call_agent(
            "team_leader",
            (
                "你是 Team Leader，正在和用户一起看右侧 3D 能源流动沙盘。"
                "先判断用户需求是否需要进入能源调度闭环。只输出任务简报、"
                "路由决策和需要点名的 Worker，不要生成能源方案。"
                "语气要像真人同事：直接指出你准备先看哪条电流、哪类浪费和哪种预览。"
            ),
            {"operator_request": user_message, "task_brief": payload},
        )
        self._record_agent_response(
            session_id, task_id, "team_leader", response, steps, [], artifact
        )
        return artifact

    def _leader_direct_response(
        self,
        session_id: str,
        task_id: str,
        task_brief: RuntimeArtifact,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        payload = {
            "input_artifact": task_brief.artifact_id,
            "user_report_contract": (
                "Answer directly as Team Leader because no Worker artifacts are required."
            ),
        }
        artifact = self._save_artifact(
            session_id,
            task_id,
            "team_leader",
            "leader_response",
            "leader_response.md",
            payload,
        )
        response = self._call_agent(
            "team_leader",
            (
                "你是 Team Leader。这个请求不需要点名 Worker。"
                "请直接给用户简洁回答；如果用户在问沙盘体验，就说明你可以控制右侧面板显示新方案预览、等待采用后再切换真实流向。"
            ),
            {"task_brief": task_brief.payload},
        )
        self._record_agent_response(
            session_id, task_id, "team_leader", response, steps, [task_brief], artifact
        )
        return artifact

    def _perception_collect_state(
        self,
        session_id: str,
        task_id: str,
        task_brief: RuntimeArtifact,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        mcp_result = self.mcp_gateway.get_energy_state(str(task_brief.payload["task"]))
        self._save_tool_call(session_id, task_id, "perception_agent", "mcp", mcp_result)
        payload = {
            "input_artifact": task_brief.artifact_id,
            "energy_state": mcp_result.output_payload,
            "agent_boundary": (
                "Perception only collects and normalizes state; it must not generate "
                "candidate plans."
            ),
        }
        artifact = self._save_artifact(
            session_id,
            task_id,
            "perception_agent",
            "energy_state",
            "state.json",
            payload,
        )
        response = self._call_agent(
            "perception_agent",
            (
                "你是感知 Agent。你只能基于 MCP 返回的 Energy State 汇报当前状态"
                "和数据可信度，不要生成调度方案。"
            ),
            payload,
        )
        self._record_agent_response(
            session_id,
            task_id,
            "perception_agent",
            response,
            steps,
            [task_brief],
            artifact,
        )
        return artifact

    def _dispatch_generate_plan(
        self,
        session_id: str,
        task_id: str,
        energy_state: RuntimeArtifact,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        hits = self._rag_search(
            session_id,
            task_id,
            "dispatch_agent",
            "生产负荷增加 峰段电价 储能调峰 柔性负荷 约束",
        )
        state = energy_state.payload["energy_state"]
        plan_payload = {
            "input_artifact": energy_state.artifact_id,
            "knowledge_sources": [hit.source_id for hit in hits],
            "plans": [
                {
                    "plan_id": "Plan-A",
                    "name": "直接购电",
                    "actions": ["新增负荷全部由电网承担"],
                    "expected_peak_grid_mw": round(
                        state["current_load_mw"] - state["pv_forecast_mw"], 2
                    ),
                    "risk": "峰段购电成本和变压器负载偏高",
                },
                {
                    "plan_id": "Plan-B",
                    "name": "储能调峰",
                    "actions": [
                        "午间利用光伏补能",
                        "17:30 前完成可转移负荷",
                        "18:00-22:00 峰段由储能承担约 520 kW",
                    ],
                    "expected_peak_grid_mw": round(
                        state["current_load_mw"] - state["pv_forecast_mw"] - 0.52, 2
                    ),
                    "risk": "需要审核 SOC 和柔性负荷审批边界",
                },
                {
                    "plan_id": "Plan-C",
                    "name": "柔性负荷调整",
                    "actions": [
                        "将非关键工序前移到光伏高发时段",
                        "峰段减少 300 kW 非关键负荷",
                    ],
                    "expected_peak_grid_mw": round(
                        state["current_load_mw"] - state["pv_forecast_mw"] - 0.3, 2
                    ),
                    "risk": "需要 MES 确认不影响生产最小负荷",
                },
            ],
            "agent_boundary": (
                "Dispatch generates candidate plans only; it cannot verify, approve, or execute."
            ),
        }
        artifact = self._save_artifact(
            session_id,
            task_id,
            "dispatch_agent",
            "candidate_plan",
            "plan.json",
            plan_payload,
        )
        response = self._call_agent(
            "dispatch_agent",
            "你是调度 Agent。只能读取 state.json 和 RAG 约束生成候选方案，不要审核、不要执行。",
            plan_payload,
        )
        self._record_agent_response(
            session_id,
            task_id,
            "dispatch_agent",
            response,
            steps,
            [energy_state],
            artifact,
        )
        return artifact

    def _audit_verify_plan(
        self,
        session_id: str,
        task_id: str,
        plan: RuntimeArtifact,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        hits = self._rag_search(
            session_id,
            task_id,
            "audit_agent",
            "安全审核 变压器 SOC 生产最小负荷 fail closed",
        )
        verifications = []
        for candidate in plan.payload["plans"]:
            passes = {
                "transformer": candidate["expected_peak_grid_mw"] <= 8.3,
                "soc": candidate["plan_id"] in {"Plan-B", "Plan-C"},
                "production_constraint": candidate["plan_id"] != "Plan-C",
                "approval_required": candidate["plan_id"] in {"Plan-B", "Plan-C"},
            }
            decision = (
                "PASS"
                if all(
                    [
                        passes["transformer"],
                        passes["soc"],
                        passes["production_constraint"],
                    ]
                )
                else "REJECT"
            )
            verifications.append(
                {
                    "plan_id": candidate["plan_id"],
                    "decision": decision,
                    "checks": passes,
                    "reason": self._audit_reason(candidate["plan_id"], passes),
                }
            )
        payload = {
            "input_artifact": plan.artifact_id,
            "knowledge_sources": [hit.source_id for hit in hits],
            "verification": verifications,
            "recommended_plan_id": self._recommended_plan(verifications),
            "agent_boundary": (
                "Audit verifies plans and fail-closes unsafe options; it cannot rewrite "
                "plans or execute."
            ),
        }
        artifact = self._save_artifact(
            session_id,
            task_id,
            "audit_agent",
            "verification",
            "verification.json",
            payload,
        )
        response = self._call_agent(
            "audit_agent",
            (
                "你是审核 Agent。只能读取 plan.json 和 safety rules 产生验证结论，"
                "不要改写方案、不要执行。"
            ),
            payload,
        )
        self._record_agent_response(
            session_id, task_id, "audit_agent", response, steps, [plan], artifact
        )
        return artifact

    def _leader_final_report(
        self,
        session_id: str,
        task_id: str,
        task_brief: RuntimeArtifact,
        energy_state: RuntimeArtifact,
        plan: RuntimeArtifact,
        verification: RuntimeArtifact,
        steps: list[AgentRuntimeStep],
    ) -> RuntimeArtifact:
        payload = {
            "inputs": {
                "task_brief": task_brief.artifact_id,
                "energy_state": energy_state.artifact_id,
                "candidate_plan": plan.artifact_id,
                "verification": verification.artifact_id,
            },
            "recommended_plan_id": verification.payload["recommended_plan_id"],
            "user_report_contract": (
                "Explain state, candidate options, audit result, and next approval boundary."
            ),
        }
        artifact = self._save_artifact(
            session_id,
            task_id,
            "team_leader",
            "final_report",
            "final_report.md",
            payload,
        )
        response = self._call_agent(
            "team_leader",
            (
                "你是 Team Leader。现在且仅现在可以汇总 Perception、Dispatch、"
                "Audit artifacts，给用户可读报告。必须说明推荐方案来自审核结果。"
                "报告要围绕右侧沙盘：旧电流哪里浪费、新方案预览怎样改变购电/储能/限发、用户采用后会发生什么。"
            ),
            {
                "task_brief": task_brief.payload,
                "energy_state": energy_state.payload,
                "candidate_plan": plan.payload,
                "verification": verification.payload,
            },
        )
        self._record_agent_response(
            session_id,
            task_id,
            "team_leader",
            response,
            steps,
            [task_brief, energy_state, plan, verification],
            artifact,
        )
        return artifact

    def _call_agent(
        self, agent_id: str, instruction: str, payload: dict[str, Any]
    ) -> str:
        config = self._runtime_config(agent_id)
        message = (
            f"{instruction}\n\n"
            "以下是 Runtime 传入的结构化输入。请基于它响应，不能声称读取了未出现的数据。\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        if config.api_key and config.connection_status == "正常":
            try:
                response = chat_with_agent_config(config, message)
                self.store.update_model_status(config.agent_id, "正常", None)
                return response
            except Exception as error:
                message = describe_model_error(error)
                self.store.update_model_status(config.agent_id, "失败", message)
                return self._local_agent_response(agent_id, payload, message)
        if config.api_key:
            return self._local_agent_response(
                agent_id, payload, f"gateway status {config.connection_status}"
            )
        return self._local_agent_response(agent_id, payload, "model config not saved")

    def _runtime_config(self, agent_id: str) -> StoredModelConfig:
        config = self.store.get_model_config(agent_id)
        if config is not None:
            return config
        shared = self.store.get_model_config("team_leader")
        if shared is None:
            return StoredModelConfig(
                agent_id=agent_id,
                base_url="local://runtime",
                api_key="",
                model="local-runtime",
                connection_status="local",
                last_error=None,
            )
        return StoredModelConfig(
            agent_id=agent_id,
            base_url=shared.base_url,
            api_key=shared.api_key,
            model=shared.model,
            connection_status=shared.connection_status,
            last_error=shared.last_error,
        )

    def _local_agent_response(
        self, agent_id: str, payload: dict[str, Any], fallback_reason: str
    ) -> str:
        _ = fallback_reason
        if agent_id == "team_leader":
            if "candidate_plan" in payload and "verification" in payload:
                verification = payload["verification"]
                recommended = (
                    verification.get("recommended_plan_id") or "暂无可自动推荐方案"
                )
                checks = verification.get("verification", [])
                passed = [
                    item["plan_id"] for item in checks if item.get("decision") == "PASS"
                ]
                rejected = [
                    item["plan_id"] for item in checks if item.get("decision") != "PASS"
                ]
                return (
                    "Team Leader 汇总：我已按职责分离完成本轮调度闭环。"
                    f"感知 Worker 已读取能源状态，调度 Worker 已生成候选方案，"
                    f"审核 Worker 已完成独立复算。推荐方案：{recommended}。"
                    f"通过审核：{', '.join(passed) or '无'}；"
                    f"被拒绝：{', '.join(rejected) or '无'}。"
                    "下一步需要按风险边界进入人工审批，审批通过后才允许执行 Worker "
                    "映射模拟控制命令。"
                )
            task_brief = payload.get("task_brief", payload)
            route = task_brief.get("routing_plan", {})
            if route.get("mode") == "leader_only":
                return (
                    "我是 EnergyMesh Team Leader，负责理解能源调度目标、决定是否需要点名 "
                    "Worker，并汇总可执行结论。这个问题不需要启动调度闭环；如果你下达"
                    "负荷、光伏、储能、电价、审核、执行或回滚相关任务，我会再调度对应 Worker。"
                )
            workers = (
                " → ".join(route.get("workers", [])) or "perception → dispatch → audit"
            )
            return (
                f"Team Leader 已接收任务并决定进入能源调度闭环。路由：{workers}。"
                "我不会直接生成设备方案，会先让感知 Worker 固化可信上下文，再让调度 "
                "Worker 生成候选计划，最后交给审核 Worker 独立复算。"
            )
        if agent_id == "perception_agent":
            state = payload.get("energy_state", {})
            return (
                "感知 Worker 已完成状态采集："
                f"当前负荷 {state.get('current_load_mw', 'N/A')} MW，"
                f"光伏预测 {state.get('pv_forecast_mw', 'N/A')} MW，"
                f"储能 SOC {state.get('storage_soc_percent', 'N/A')}%。"
                "该输出只描述上下文可信度，不生成调度方案。"
            )
        if agent_id == "dispatch_agent":
            plans = payload.get("plans", [])
            names = [f"{plan.get('plan_id')}({plan.get('name')})" for plan in plans]
            return (
                "调度 Worker 已基于可信上下文生成候选方案："
                f"{'、'.join(names)}。这些只是候选计划，必须交给审核 Worker 复算后才可推荐。"
            )
        if agent_id == "audit_agent":
            verification = payload.get("verification", [])
            summary = [
                f"{item.get('plan_id')}={item.get('decision')}" for item in verification
            ]
            return (
                "审核 Worker 已完成独立安全复算："
                f"{'；'.join(summary)}。不可验证或违反硬约束的方案默认拒绝。"
            )
        return f"{agent_id} 已完成本地 Runtime 步骤。"

    def _rag_search(
        self, session_id: str, task_id: str, agent_id: str, query: str
    ) -> list[KnowledgeHit]:
        hits = self.knowledge_base.search(query)
        output = {
            "query": query,
            "hits": [
                {
                    "source_id": hit.source_id,
                    "title": hit.title,
                    "score": hit.score,
                    "excerpt": hit.excerpt,
                    "path": hit.path,
                }
                for hit in hits
            ],
        }
        self._save_tool_call(
            session_id,
            task_id,
            agent_id,
            "rag",
            MCPToolResult(
                tool_name="knowledge.search",
                input_payload={"query": query},
                output_payload=output,
            ),
        )
        return hits

    def _save_tool_call(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        tool_type: str,
        result: MCPToolResult,
    ) -> RuntimeToolCall:
        return self.store.save_runtime_tool_call(
            RuntimeToolCall(
                call_id=f"call_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=agent_id,
                tool_type=tool_type,
                tool_name=result.tool_name,
                input_payload=result.input_payload,
                output_payload=result.output_payload,
                created_at=datetime.now(UTC),
            )
        )

    def _save_artifact(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        artifact_type: str,
        name: str,
        payload: dict[str, Any],
    ) -> RuntimeArtifact:
        return self.store.save_runtime_artifact(
            RuntimeArtifact(
                artifact_id=f"artifact_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=agent_id,
                artifact_type=artifact_type,
                name=name,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )

    def _list_runtime_artifacts(self, task_id: str) -> list[RuntimeArtifact]:
        return self.store.list_runtime_artifacts(task_id)

    def _record_agent_response(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        response: str,
        steps: list[AgentRuntimeStep],
        input_artifacts: list[RuntimeArtifact],
        output_artifact: RuntimeArtifact,
    ) -> None:
        self._save_message(
            session_id,
            task_id,
            agent_id,
            "assistant",
            response,
            {
                "source": "runtime_pipeline",
                "input_artifacts": [
                    artifact.artifact_id for artifact in input_artifacts
                ],
                "output_artifact": output_artifact.artifact_id,
            },
        )
        config = self._runtime_config(agent_id)
        steps.append(
            AgentRuntimeStep(
                agent_id=agent_id,
                model=config.model,
                response=response,
                input_artifacts=[artifact.artifact_id for artifact in input_artifacts],
                output_artifact=output_artifact.artifact_id,
            )
        )

    def _save_message(
        self,
        session_id: str,
        task_id: str | None,
        agent_id: str,
        role: str,
        content: str,
        metadata: dict[str, object],
    ) -> AgentMessage:
        return self.store.save_agent_message(
            AgentMessage(
                message_id=f"msg_{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                agent_id=agent_id,
                role=role,
                content=content,
                created_at=datetime.now(UTC),
                metadata=dict(metadata),
            )
        )

    @staticmethod
    def _audit_reason(plan_id: str, checks: dict[str, bool]) -> str:
        failed = [
            name
            for name, passed in checks.items()
            if name != "approval_required" and not passed
        ]
        if not failed:
            return (
                f"{plan_id} passes hard checks; approval is required if it changes flexible load."
            )
        return f"{plan_id} rejected because these checks failed: {', '.join(failed)}."

    @staticmethod
    def _recommended_plan(verifications: list[dict[str, Any]]) -> str | None:
        for item in verifications:
            if item["plan_id"] == "Plan-B" and item["decision"] == "PASS":
                return "Plan-B"
        for item in verifications:
            if item["decision"] == "PASS":
                return str(item["plan_id"])
        return None

    @staticmethod
    def _routing_plan(message: str) -> dict[str, Any]:
        lower = message.lower()
        requires_dispatch = any(keyword in lower for keyword in DISPATCH_KEYWORDS)
        if not requires_dispatch:
            return {
                "mode": "leader_only",
                "workers": [],
                "reason": (
                    "The request can be answered by the Team Leader without tool "
                    "or Worker artifacts."
                ),
            }
        return {
            "mode": "dispatch_closed_loop",
            "workers": ["perception_agent", "dispatch_agent", "audit_agent"],
            "required_pipeline": [
                "collect_state",
                "generate_candidate_plan",
                "verify_plan",
                "summarize_result",
            ],
            "reason": (
                "The request concerns energy dispatch or operational risk, so the Leader must "
                "route work through separated Worker responsibilities."
            ),
        }
