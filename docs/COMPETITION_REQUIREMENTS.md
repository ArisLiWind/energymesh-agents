# Agent Infra 赛题要求映射

当前完整评审矩阵见 [JUDGING_ALIGNMENT.md](JUDGING_ALIGNMENT.md)。本文保留为简版索引，方便快速核验必选项。

## 必选项

### AgentTeams

EnergyMesh Agents 以 `agentscope-ai/AgentTeams` 为协同设计基点：

- 声明式资源：`agentteams/agentteams-resources.yaml`
- Team Leader：`agentteams/team-leader`
- Workers：`agentteams/workers/perception|dispatch|audit|execution`
- Skills：`agentteams/skills/*`
- 运行 manifest：`GET /api/agentteams/manifest`
- Trace 映射：`src/energymesh/agentteams.py`

### 至少 3 个 Agent

当前实现 5 个协作身份：

- EnergyMesh Team Leader
- 感知 Agent
- 调度 Agent
- 审核 Agent
- 执行 Agent

详细身份清单见 [AGENT_IDENTITY.md](AGENT_IDENTITY.md)。

### Skill

当前 Skill：

- `microgrid_context_ingest`
- `dispatch_plan_generate`
- `dispatch_audit_verify`
- `execution_mapping`
- `approval_rollback`

每个 Skill 的输入输出、调用条件、依赖工具、失败处理、安全边界和复用价值见
[SKILL_CONTRACTS.md](SKILL_CONTRACTS.md)。

## 多 Agent 闭环

1. 任务输入：`GET /api/external/snapshot` 模拟外部 EMS/BMS/PCS/气象/MES 数据。
2. 任务拆解：Team Leader 创建 TaskRecord 并驱动四类 Worker。
3. 上下文传递：`TaskRecord` 保存 scenario、perception、策略脚本草案、plans、audits、approval、trace、execution_summary。
4. 工具调用：Skill 调用 FastAPI/OpenAPI 工具契约；调度 Agent 生成受限脚本草案；后续可包装为 MCP Server。
5. 结果验证：审核 Agent 对脚本做静态审查和沙箱回放，独立复算硬约束和收益；执行 Agent 回放计划并检查偏差。
6. 证据沉淀：SQLite audit_events、TaskRecord trace、JSON evidence SHA-256。
7. 审批与回滚：柔性负荷响应需要人工审批；执行偏差触发 safe_fallback。
8. 经验沉淀：Task evidence 与策略脚本版本可迁移到 PolarDB/RAG/长记忆，用于后续策略复盘。

## MCP、RAG、可观测

当前未实现 live MCP Server，但已提供等价 OpenAPI 工具契约，迁移成本低。当前已实现：

- 共享状态管理：TaskRecord。
- 轨迹可观测：Trace、audit_events、PlanMetrics、execution_summary。

RAG 作为复赛增强项，建议接入 PolarDB for PostgreSQL + pgvector。完整设计见
[TOOLING_AND_CLOUD_INTEGRATION.md](TOOLING_AND_CLOUD_INTEGRATION.md)。

## 推荐云工具

当前本地 MVP 不绑定云账号。阿里云官方用云 Skills、Nacos、Higress、PolarDB for PostgreSQL、
RocketMQ、AgentLoop/LoongSuite 的必要性、接口契约、权限边界、可替换性和迁移成本见
[TOOLING_AND_CLOUD_INTEGRATION.md](TOOLING_AND_CLOUD_INTEGRATION.md)。
