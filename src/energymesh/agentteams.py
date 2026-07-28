from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from energymesh.config import Settings
from energymesh.models import AgentModelConfigPublic


class AgentTeamsSkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    local_module: str
    tool_contract: str
    safety_boundary: str


class AgentTeamsWorkerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str
    display_name: str
    role: str
    soul_md: str
    agents_md: str
    skills: list[str]
    mcp_servers: list[str]
    permissions: list[str]


class AgentTeamsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: str
    framework_repository: str
    runtime_mode: str
    team_name: str
    instance_id: str | None
    leader_worker_pattern: bool
    human_in_the_loop: bool
    local_orchestrator: str
    import_assets_path: str
    declarative_resources: str
    workers: list[AgentTeamsWorkerSpec]
    skills: list[AgentTeamsSkillSpec]
    mcp_servers: list[dict[str, Any]]
    trace_actor_mapping: dict[str, str]
    model_configs: dict[str, AgentModelConfigPublic]


TRACE_ACTOR_MAPPING = {
    "orchestrator": "energymesh_team_leader",
    "perception_agent": "perception_worker",
    "dispatch_agent": "dispatch_worker",
    "audit_agent": "audit_worker",
    "execution_agent": "execution_worker",
    "approval_gate": "human_in_the_loop_gate",
    "human_approver": "human_in_the_loop_gate",
}


def actor_to_worker(actor: str) -> str | None:
    return TRACE_ACTOR_MAPPING.get(actor)


def build_agentteams_manifest(
    settings: Settings,
    model_configs: dict[str, AgentModelConfigPublic] | None = None,
) -> AgentTeamsManifest:
    runtime_mode = (
        "agentteams-declarative-local" if settings.agentteams_enabled else "local-only"
    )
    return AgentTeamsManifest(
        framework="agentscope-ai/AgentTeams open-source runtime",
        framework_repository="https://github.com/agentscope-ai/AgentTeams",
        runtime_mode=runtime_mode,
        team_name=settings.agentteams_team_name,
        instance_id=settings.agentteams_instance_id,
        leader_worker_pattern=True,
        human_in_the_loop=True,
        local_orchestrator="energymesh.orchestrator.EnergyMeshOrchestrator",
        import_assets_path="agentteams/",
        declarative_resources="agentteams/agentteams-resources.yaml",
        trace_actor_mapping=TRACE_ACTOR_MAPPING,
        workers=[
            AgentTeamsWorkerSpec(
                worker_id="energymesh_team_leader",
                display_name="EnergyMesh Team Leader",
                role="意图理解、任务拆解、进度监控和人机协同入口",
                soul_md="agentteams/team-leader/SOUL.md",
                agents_md="agentteams/team-leader/AGENTS.md",
                skills=[
                    "microgrid_context_ingest",
                    "dispatch_plan_generate",
                    "dispatch_audit_verify",
                    "execution_mapping",
                    "approval_rollback",
                ],
                mcp_servers=["energymesh-local-api"],
                permissions=["read_scenario", "create_task", "request_human_approval"],
            ),
            AgentTeamsWorkerSpec(
                worker_id="perception_worker",
                display_name="感知 Agent",
                role="核验运行上下文、识别异常和重新定义调度任务",
                soul_md="agentteams/workers/perception/SOUL.md",
                agents_md="agentteams/workers/perception/AGENTS.md",
                skills=["microgrid_context_ingest"],
                mcp_servers=["energymesh-local-api"],
                permissions=["read_scenario", "read_task"],
            ),
            AgentTeamsWorkerSpec(
                worker_id="dispatch_worker",
                display_name="调度 Agent",
                role="生成候选策略并调用优化模型",
                soul_md="agentteams/workers/dispatch/SOUL.md",
                agents_md="agentteams/workers/dispatch/AGENTS.md",
                skills=["dispatch_plan_generate"],
                mcp_servers=["energymesh-local-api"],
                permissions=["read_context", "generate_plan"],
            ),
            AgentTeamsWorkerSpec(
                worker_id="audit_worker",
                display_name="审核 Agent",
                role="独立复算安全约束、收益和审批门槛",
                soul_md="agentteams/workers/audit/SOUL.md",
                agents_md="agentteams/workers/audit/AGENTS.md",
                skills=["dispatch_audit_verify"],
                mcp_servers=["energymesh-local-api"],
                permissions=["read_plan", "write_audit_decision"],
            ),
            AgentTeamsWorkerSpec(
                worker_id="execution_worker",
                display_name="执行 Agent",
                role="把获批方案映射为幂等指令并模拟执行确认",
                soul_md="agentteams/workers/execution/SOUL.md",
                agents_md="agentteams/workers/execution/AGENTS.md",
                skills=["execution_mapping", "approval_rollback"],
                mcp_servers=["energymesh-local-api"],
                permissions=["read_approved_plan", "write_simulated_commands"],
            ),
        ],
        skills=[
            AgentTeamsSkillSpec(
                name="microgrid_context_ingest",
                description="汇总园区负荷、光伏、储能、电价、设备状态和生产计划并给出可信上下文。",
                local_module="energymesh.perception.PerceptionAgent",
                tool_contract="GET /api/external/snapshot, GET /api/tasks/{task_id}",
                safety_boundary="只读数据；数据缺失或冲突时必须交还人工。",
            ),
            AgentTeamsSkillSpec(
                name="dispatch_plan_generate",
                description="基于已核验上下文生成候选储能和柔性负荷调度方案。",
                local_module="energymesh.optimizer.DispatchOptimizer",
                tool_contract="POST /api/external/dispatch, POST /api/tasks/{task_id}/reoptimize",
                safety_boundary="只生成方案，不直接执行设备动作。",
            ),
            AgentTeamsSkillSpec(
                name="dispatch_audit_verify",
                description="独立复算 SOC、功率、变压器、并网、生产计划和收益约束。",
                local_module="energymesh.audit.IndependentSafetyAuditor",
                tool_contract="TaskRecord.audits",
                safety_boundary="不可验证时默认不放行；安全优先于经济收益。",
            ),
            AgentTeamsSkillSpec(
                name="execution_mapping",
                description="将获批方案映射为 EMS、PCS、负荷控制系统的结构化幂等指令。",
                local_module="energymesh.simulator.SimulationExecutor",
                tool_contract="POST /api/tasks/{task_id}/approval",
                safety_boundary="当前 MVP 仅本地模拟，真实设备接触数必须为 0。",
            ),
            AgentTeamsSkillSpec(
                name="approval_rollback",
                description="管理人工审批、拒绝、执行偏差和安全回退证据。",
                local_module="energymesh.orchestrator.EnergyMeshOrchestrator",
                tool_contract="POST /api/tasks/{task_id}/approval",
                safety_boundary="高风险柔性负荷动作无审批不得执行。",
            ),
        ],
        mcp_servers=[
            {
                "name": "energymesh-local-api",
                "type": "http",
                "base_url": "http://127.0.0.1:8000",
                "status": "local_contract_ready",
                "production_write": False,
            }
        ],
        model_configs=model_configs or {},
    )
