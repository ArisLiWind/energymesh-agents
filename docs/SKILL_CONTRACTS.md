# Skill 工程契约

EnergyMesh Agents 将关键能力沉淀为可复用 Skill。Skill 是 Agent 的能力抽象层，FastAPI/OpenAPI 或后续 MCP Server 是工具连接层。

## 1. `microgrid_context_ingest`

- 用途：接入并核验园区数字孪生上下文。
- 调用 Agent：Team Leader、感知 Agent。
- 调用条件：收到外部数据快照、告警、生产计划变化或人工调度目标。
- 输入：
  - `Scenario.forecast`
  - `Scenario.site`
  - `Scenario.alerts`
  - `Scenario.device_status`
  - `Scenario.production_plan`
- 输出：
  - `PerceptionReport.data_complete`
  - `quality_score`
  - `anomalies`
  - `conflicts`
  - `objective_priority`
  - `required_tools`
- 依赖工具：`GET /api/external/snapshot`、`energymesh.perception.PerceptionAgent`。
- 失败处理：缺失关键字段时 request_missing_data；双路温度冲突时 human_handoff；设备状态非法时阻断自动调度。
- 安全边界：只读，不写设备、不生成控制指令。
- 验证方式：`tests/test_api.py`、`tests/test_optimizer_audit.py`。
- 复用价值：可复用于园区、算力中心、工厂和充储站的数据可信上下文核验。

## 2. `dispatch_plan_generate`

- 用途：基于可信上下文生成多套候选策略脚本草案，并由脚本输出候选调度方案。
- 调用 Agent：调度 Agent。
- 调用条件：感知 Agent 输出 `data_complete=true` 且未进入 human_handoff。
- 输入：
  - `Scenario`
  - 站点安全边界
  - 目标优先级
  - 原 EMS 基线策略
  - 感知 Agent 输出的异常、冲突和目标优先级
- 输出：
  - 受限策略脚本草案
  - 脚本说明和依赖假设
  - `baseline_plan`
  - `DispatchPlan[]`
  - 每个计划的 96 点 charge/discharge/grid/curtail/shed/SOC
  - `PlanMetrics`
- 依赖工具：`energymesh.optimizer.DispatchOptimizer`、`scipy.optimize.milp`。
- 失败处理：脚本草案无法生成、脚本输出不可行或优化不可行时抛出 WorkflowError；不产生任何执行命令。
- 安全边界：脚本生成、脚本审核和设备执行分离；脚本不得导入库、访问网络、读写文件或直接写设备。
- 验证方式：`test_optimizer_generates_three_power_balanced_candidates`。
- 复用价值：可替换脚本生成器或优化器，实现同一输入输出契约下的滚动优化、鲁棒优化、启发式调度或站点定制策略。

## 3. `dispatch_audit_verify`

- 用途：独立验证策略脚本是否安全、候选计划是否可执行、是否优于原 EMS 基线。
- 调用 Agent：审核 Agent。
- 调用条件：调度 Agent 已生成候选计划。
- 输入：
  - 策略脚本草案
  - 脚本依赖假设
  - `Scenario`
  - `DispatchPlan`
  - baseline `DispatchPlan`
- 输出：
  - 静态审查结果
  - 沙箱回放结果
  - `AuditReport.decision`
  - `AuditFinding[]`
  - `checked_rules`
  - `improvement_yuan`
  - `improvement_ratio`
- 依赖工具：`energymesh.audit.IndependentSafetyAuditor`。
- 失败处理：脚本越权、未知变量、不确定行为或任一硬约束 critical finding 直接 rejected；柔性负荷削减进入 requires_approval。
- 安全边界：fail closed；不可验证即不放行。
- 验证方式：`test_independent_audit_blocks_unsafe_reserve_and_gates_load_shed`。
- 复用价值：可作为任意储能/负荷调度计划的独立审计器。

## 4. `execution_mapping`

- 用途：将获批计划映射为结构化、幂等、可审计的模拟执行命令。
- 调用 Agent：执行 Agent。
- 调用条件：审核通过，或 requires_approval 且审批记录 approved。
- 输入：
  - selected `DispatchPlan`
  - baseline plan
  - optional `approval_id`
- 输出：
  - `ExecutionCommand[]`
  - execution_summary
  - confirmation_ratio
  - deviation_intervals
- 依赖工具：`energymesh.simulator.SimulationExecutor`。
- 失败处理：执行偏差超过 5% 时 safe_fallback；生产写入尝试被 `Settings.assert_safe_runtime` 阻断。
- 安全边界：真实设备连接数必须为 0；生产写入关闭。
- 验证方式：API workflow tests、execution summary assertions。
- 复用价值：可迁移到真实 EMS/PCS adapter，只需替换工具层并保留幂等命令 Schema。

## 5. `approval_rollback`

- 用途：管理人工审批、拒绝、变化后重新审批和执行偏差回退。
- 调用 Agent：Team Leader、审核 Agent、执行 Agent。
- 调用条件：审核结论 requires_approval、审批拒绝、执行偏差、外部数据变化。
- 输入：
  - task_id
  - `ApprovalRequest`
  - execution_summary
  - trigger
- 输出：
  - `ApprovalRecord`
  - rejected/completed/safe_fallback state
  - sealed evidence SHA-256
- 依赖工具：`POST /api/tasks/{task_id}/approval`、`POST /api/tasks/{task_id}/reoptimize`、`EvidenceStore`。
- 失败处理：非 awaiting_approval 状态审批返回冲突；新子任务不得复用旧审批。
- 安全边界：高风险动作必须人工确认；回退策略零充放电、零负荷削减并交还人工。
- 验证方式：API approval tests、workflow state tests。
- 复用价值：适用于能源、运维、安全处置等高风险 Agent 执行门禁。

## 6. 版本、发布、回滚和质量评估

- 版本载体：每个 Skill 存放在 `agentteams/skills/<skill>/SKILL.md`，由 git commit 和 release tag 管理。
- 发布方式：随 AgentTeams worker 包和 `/api/agentteams/manifest` 一起发布。
- 回滚方式：回滚 git tag 或替换 AgentTeams 声明资源中的 Skill 包版本。
- 质量评估：
  - 单元测试覆盖优化、审计和 API 闭环。
  - 运行证据包含 task trace、metrics 和 SHA-256 evidence。
  - 未来可将每次 Skill 调用映射为 OpenTelemetry span 或 AgentLoop trace。

## 7. 阿里云官方用云 Skills 适配策略

当前 Demo 不要求云账号即可复现，因此官方用云 Skills 作为可替换云操作层设计：

- Nacos Skill：管理 Agent 配置、模型配置、Prompt/Skill 版本和服务发现。
- Higress Skill：管理模型网关和外部工具入口的鉴权、路由、限流、观测。
- PolarDB for PostgreSQL Skill：创建审计日志、长记忆、RAG 和向量索引存储。
- RocketMQ Skill：创建外部数据事件、审批事件、执行确认事件的可靠消息流。
- AgentLoop/LoongSuite Skill：采集 Agent trace、metrics、成本、延迟和错误率。

迁移原则：Skill 的业务输入输出不变，只替换底层工具连接器，避免重写 Agent 协作链。
