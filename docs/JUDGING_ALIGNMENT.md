# EnergyMesh Agents 评审对齐矩阵

本文按赛题评分项逐条说明 EnergyMesh Agents 的当前实现、可验证证据、仍需增强项和复用价值。

## 1. 场景价值与行业可复制性 25%

**当前判断：基本符合，材料已补强。**

- 真实场景：园区、工业中心和算力中心的源网荷储协同调度。
- 目标用户：园区能源运营团队、工业企业能源管理工程师、算力中心基础设施运维团队、储能运营商。
- 核心痛点：传统 EMS 依赖固定规则或人工重新设参；高级 EMS 需要问题已被正确定义；现实中负荷、光伏、储能 SOC、电价、设备热状态和生产计划会同时变化。
- 可感知收益：降低峰值购电、降低总用能成本、提升光伏自用率、减少人工策略重配、降低高风险调度误执行概率。
- 行业复制性：同一“环境感知 -> 策略脚本生成 -> 静态审查 -> 确定性验证 -> 审批执行 -> 证据沉淀”链路可迁移到工商业园区、数据中心、微电网、充储一体站和虚拟电厂局部调度。

可验证证据：

- README 中明确业务问题和目标用户。
- `/api/external/snapshot` 生成 EMS/BMS/PCS/气象/MES 模拟外部数据。
- `/api/external/dispatch` 使用外部环境态势触发完整 Agent 调度闭环。
- `src/energymesh/external_data.py` 覆盖负荷、光伏、储能、电价、变压器、并网、设备故障和生产计划。

## 2. 多 Agent 协同与自主闭环能力 25%

**当前判断：符合。**

- AgentTeams 基点：`agentteams/agentteams-resources.yaml` 声明 Team Leader、Human 和四类 Worker。
- Agent 角色：感知、调度、审核、执行四类 Worker，超过“至少 3 个不同职能 Agent”的要求。
- 任务拆解：Team Leader 接收外部数据触发的调度任务，分派给感知、调度、审核、执行 Worker。
- 上下文传递：`TaskRecord` 保存 scenario、perception、baseline、plans、audits、selected_plan、approval、trace、execution_summary。
- 状态流转：`TaskState` 覆盖 received、context_ready、plans_generated、audited、awaiting_approval、approved、executing、completed、safe_fallback、human_handoff、failed。
- 异常冲突：传感器冲突进入 human_handoff；执行偏差超过阈值进入 safe_fallback。
- 多方案选择：调度 Agent 为 economic_aggressive、balanced、conservative 三类目标生成策略脚本草案和候选动作，审核 Agent 拦截不安全脚本和方案，编排器在可执行候选中选取成本最低方案。
- 高风险边界：柔性负荷响应需要人工审批；被拒绝或变化后的子任务不能复用旧审批。

可验证证据：

- `src/energymesh/orchestrator.py`
- `src/energymesh/models.py`
- `src/energymesh/audit.py`
- `tests/test_workflow.py`
- `tests/test_api.py`

## 3. Skill 工程体系与生态复用 25%

**当前判断：核心 Skill 已实现，阿里云官方用云 Skills 为明确集成契约和迁移计划。**

当前仓库提供 5 个 AgentTeams Skill 资产：

- `microgrid_context_ingest`
- `dispatch_plan_generate`
- `dispatch_audit_verify`
- `execution_mapping`
- `approval_rollback`

每个 Skill 都在 `agentteams/skills/*/SKILL.md` 中补齐用途、输入、输出、调用条件、依赖工具、失败处理、安全边界、验证方式和复用价值。

生态复用设计：

- AgentTeams：作为协同编排和 Worker 身份基点。
- 阿里云官方用云 Skills：用于后续封装 Higress、Nacos、PolarDB for PostgreSQL、RocketMQ、AgentLoop 等资源操作；当前 Demo 不绑定云账号，避免把评审复现依赖云资源。
- MCP：当前用 FastAPI/OpenAPI 提供等价工具契约，后续迁移到 MCP Server 只需协议适配。

可验证证据：

- `agentteams/skills/*/SKILL.md`
- `/api/agentteams/manifest`
- `docs/SKILL_CONTRACTS.md`
- `docs/TOOLING_AND_CLOUD_INTEGRATION.md`
- `docs/STRATEGY_SCRIPT_FLOW.md`

## 4. 工程落地、运行验证与安全可审计 20%

**当前判断：符合本地可运行 Demo，生产化存储和真实设备接入仍保持安全边界。**

- 本地运行：FastAPI + static console + Three.js 3D 沙盘。
- 部署：本地 Python、Docker Compose、Vercel Python serverless preview 均有配置；Vercel build 已通过。
- 模型配置：每个 Agent 可配置 OpenAI-compatible Base URL、API Key、model，API Key 只保存在后端 SQLite，前端只返回 masked key。
- Trace：每个 Agent 行为写入 `TaskRecord.trace`，并映射到 AgentTeams worker。
- Metrics：调度成本、峰值购电、光伏自用、SOC、约束余量、执行确认率、偏差时段等。
- Evidence：SQLite 保存任务和模型配置，`runs/` 生成 SHA-256 证据包。
- 安全：`SIMULATION_MODE=true` 且 `ALLOW_PRODUCTION_WRITE=false`；执行器只生成模拟 EMS/PCS/load-control 命令。
- 审批和回滚：人工审批 gate，审批拒绝不执行，执行偏差触发安全回退。

可验证证据：

- `make verify`
- `tests/`
- `/api/tasks`
- `/api/tasks/{task_id}`
- `/api/tasks/{task_id}/approval`
- `src/energymesh/storage.py`
- `SECURITY.md`

## 5. 开放 / 开源贡献 5%

**当前判断：符合基础开源材料，后续可增强云 Skill 模板发布。**

- 开源接口：FastAPI/OpenAPI、AgentTeams manifest、Skill Markdown 资产。
- 文档：README、Architecture、Security、Status、评审对齐、Skill 契约、云工具集成契约。
- 第三方依赖：`pyproject.toml`、`requirements.txt`、`uv.lock`、`THIRD_PARTY_NOTICES.md`。
- 可复用成果：外部数据模拟器、策略脚本信息流、确定性审计器、AgentTeams worker 包、OpenAI-compatible per-Agent model config。

## 6. 补充要求逐条核验

### AgentTeams 不只是提名字

当前实现把 AgentTeams 映射为：

- Team/Human 资源：`agentteams/agentteams-resources.yaml`
- Team Leader 和 Worker 包：`agentteams/team-leader`、`agentteams/workers/*`
- Skill 资产：`agentteams/skills/*`
- 运行 manifest：`/api/agentteams/manifest`
- Trace 映射：`TRACE_ACTOR_MAPPING`

### Skill 是必选项

已提供 5 个 Skill，均可被多个 Agent 或相似能源场景复用。每个 Skill 说明输入输出、失败处理、调用条件和安全边界。

### 推荐工具不按数量评分

本项目不堆叠工具。当前只把必要外部系统抽象为稳定契约：

- 外部数据源：EMS/BMS/PCS/气象/MES
- 模型网关：OpenAI-compatible per-Agent config
- 审计证据：SQLite + JSON evidence，本地可替换为 PolarDB for PostgreSQL
- 可观测：Task trace + metrics + evidence，可迁移到 OpenTelemetry/AgentLoop

## 7. 当前缺口与复赛增强

- 真实 AgentTeams runtime apply 尚未在当前机器完成，当前为声明式资源和 manifest 级对接。
- MCP Server 尚未实现，当前为 FastAPI/OpenAPI 等价契约。
- RAG 知识库未接入；当前已实现共享状态管理和轨迹可观测，满足“不使用 RAG 时除知识库外至少实现 2 项”的要求。
- 阿里云官方用云 Skills 尚未真实调用云账号；当前给出权限边界、资源契约和迁移计划。
- Vercel preview 使用 `/tmp` 存储，只适合演示；长期 API Key、审计证据和运行历史应迁移到 PolarDB for PostgreSQL 或等价外部数据库。
