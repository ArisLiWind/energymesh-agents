# MCP、RAG、可观测与阿里云工具集成方案

本文说明 EnergyMesh Agents 如何把外部工具抽象为可被 Agent/Skill 稳定调用的能力，并给出后续迁移到 MCP 与阿里云推荐工具链的边界。

## 1. 当前工具连接层

当前本地 Demo 使用 FastAPI/OpenAPI 作为等价工具契约，原因是：

- 无需云账号即可复现；
- 输入输出 Schema 由 Pydantic 和 OpenAPI 明确定义；
- 后续迁移到 MCP Server 时只需要协议适配，不需要重写 Agent、Skill 和状态机。

核心入口：

- `GET /api/external/snapshot`
- `POST /api/external/dispatch`
- `GET /api/agentteams/manifest`
- `PUT /api/agents/{agent_id}/model`
- `POST /api/agents/{agent_id}/model/test`
- `POST /api/agents/{agent_id}/chat`
- `POST /api/tasks/{task_id}/approval`
- `POST /api/tasks/{task_id}/reoptimize`
- `GET /api/tasks/{task_id}`

## 2. MCP 等价工具契约

### `external_energy_snapshot`

- 调用入口：`GET /api/external/snapshot`
- 参数 Schema：`seed:int`、`current_interval:int`、`fault_mode:str`
- 返回结构：`ExternalDataSnapshot`
- 权限范围：只读模拟 EMS/BMS/PCS/气象/MES 数据。
- 失败重试：可按相同参数重试；结果确定性一致。
- 幂等控制：seed + current_interval + fault_mode。
- 审计日志：进入 TaskRecord 前由 Team Leader 记录触发参数。
- 降级方式：失败时回退 `GET /api/demo/scenario`。
- MCP 迁移成本：低；把 HTTP endpoint 包装为 MCP tool 即可。

### `dispatch_from_external_context`

- 调用入口：`POST /api/external/dispatch`
- 参数 Schema：`ExternalDispatchRequest`
- 返回结构：`TaskRecord`
- 权限范围：创建本地模拟调度任务，不写真实设备。
- 失败重试：相同外部数据可重新创建新 task；执行命令使用 idempotency_key。
- 幂等控制：执行命令级幂等，任务级保留独立证据。
- 审计日志：`TaskRecord.trace`、SQLite、JSON evidence。
- 降级方式：优化失败进入 failed/human_handoff。
- MCP 迁移成本：低；状态机和业务模型不变。

### `approve_or_reject_dispatch`

- 调用入口：`POST /api/tasks/{task_id}/approval`
- 参数 Schema：`ApprovalRequest`
- 返回结构：`TaskRecord`
- 权限范围：只对 awaiting_approval 的当前 task 生效。
- 失败重试：同一任务状态变化后重复审批返回冲突。
- 幂等控制：approval_id 和 task_id 绑定。
- 审计日志：审批记录进入 TaskRecord 和证据包。
- 降级方式：拒绝或超时保持执行门禁关闭。
- MCP 迁移成本：低；未来可接入企业审批系统。

## 3. RAG 与上下文增强

赛题要求在 Agent 记忆存储、知识库 RAG、共享状态管理、轨迹可观测 4 项中至少实现 2 项。

当前已实现：

- 共享状态管理：`TaskRecord` 保存场景、计划、审核、审批、执行、证据哈希。
- 轨迹可观测：`TaskRecord.trace` 保存 actor/action/status/detail；execution_summary 保存 metrics。

当前未实现知识库 RAG，理由：

- MVP 的确定性安全验证优先级高于知识库检索；
- 当前调度约束直接来自结构化场景和设备边界，不依赖非结构化知识。

复赛增强：

- PolarDB for PostgreSQL + pgvector：存储设备手册、事故复盘、站点策略模板、历史任务 evidence。
- RAG Skill：封装检索、证据对齐、引用写入和低置信度 human_handoff。
- Agent 使用方式：感知 Agent 判断检索结果是否足以支撑任务重定义；审核 Agent 可检索站点安全规则和审批策略。

## 4. 可观测方案

当前覆盖：

- Trace：`TaskRecord.trace`
- Log：FastAPI/Uvicorn 请求日志，SQLite `audit_events`
- Metrics：PlanMetrics、AuditReport improvement、ExecutionSummary confirmation/deviation/fallback。

建议语义：

- 每次 Skill 调用映射为 span：
  - `gen_ai.operation.name`
  - `agent.name`
  - `skill.name`
  - `tool.name`
  - `task.id`
  - `decision.state`
- 每次模型调用记录：
  - provider base_url 域名
  - model name
  - success/failure
  - error message
  - latency
  - 不记录完整 API Key。

后端存储：

- 本地：SQLite + JSON evidence。
- 生产：PolarDB for PostgreSQL 保存 trace、metrics、approval、evidence；对象存储保存大文件证据。

推荐平台：

- AgentLoop 或 AgentScope Studio：展示 Agent 推理轨迹、错误率、耗时和成本。
- LoongSuite：统一采集应用 trace/log/metrics。

## 5. 阿里云推荐工具链映射

### AgentTeams

- 必选，当前已作为协同设计基点。
- 当前证据：`agentteams/agentteams-resources.yaml`、worker 包、Skill 包、manifest。

### 阿里云官方用云 Skills

- 定位：云资源操作层，不替代业务 Skill。
- 当前状态：给出集成契约；本地 Demo 不强制云账号。
- 权限边界：只允许创建/读取必要资源；生产写入动作必须二次审批。

### Nacos

- 必要性：管理 Agent、Skill、Prompt、模型配置和服务发现。
- 可替换性：可替换为 Consul、etcd、Kubernetes ConfigMap。
- 迁移成本：低；当前 Settings/manifest 已集中管理运行配置。

### Higress

- 必要性：统一模型网关、Agent API、外部工具 API 的鉴权、路由、限流和观测。
- 可替换性：可替换为 Kong、Envoy、APISIX。
- 迁移成本：中；需要把 `/api/agents/*/model` 和外部工具调用切到网关域名。

### PolarDB for PostgreSQL

- 必要性：长期保存 API Key 密文、审计证据、长记忆、RAG 向量和任务历史。
- 可替换性：可替换为 PostgreSQL、Supabase、Neon、SQLite 本地演示。
- 迁移成本：中；需要把 `EvidenceStore` SQLite 实现替换为 PostgreSQL adapter。

### UnifiedModel

- 必要性：统一描述站点、设备、测点、计划、约束、任务和证据之间的实体关系。
- 可替换性：可用内部 CMDB/资产模型替代。
- 迁移成本：中；当前 Pydantic models 已提供结构化实体基础。

### RocketMQ

- 必要性：外部告警、生产计划变化、审批结果、执行确认适合事件驱动。
- 可替换性：Kafka、Pulsar、云消息队列。
- 迁移成本：中；需要把 `/api/external/dispatch` 从同步 HTTP 扩展为事件消费。

### AgentLoop / LoongSuite / AgentScope Studio

- 必要性：从 Demo 走向生产时，评估 Agent 决策质量、延迟、成本和失败原因。
- 可替换性：OpenTelemetry collector + Grafana/Tempo/Loki。
- 迁移成本：低到中；当前 trace/detail/metrics 已结构化。

## 6. 安全与权限边界

- 模型 API Key：只保存在后端；manifest 和前端只返回 masked key。
- 设备控制：当前不连接真实设备；真实设备 adapter 必须在审核通过和人工审批后启用。
- 审批：审批只绑定当前 task_id；数据变化产生的新任务必须重新审批。
- 回滚：偏差超过阈值时零充放电、零负荷削减，控制权交还人工。
- 审计：每次状态变化写入 trace，每次完成或拒绝封存 evidence SHA-256。
