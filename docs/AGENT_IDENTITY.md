# Agent Identity 清单

本清单说明 EnergyMesh Agents 中每个 Agent 的身份、能力边界、协作关系和审计责任。

## 1. EnergyMesh Team Leader

- AgentTeams worker id：`energymesh_team_leader`
- 声明资源：`agentteams/team-leader`
- 身份定位：园区能源调度任务主控 Agent。
- 核心职责：接收外部数据告警或人工目标，拆解任务，协调感知、调度、审核、执行 Worker，维护全局状态。
- 输入：外部数据快照、人工任务、历史 TaskRecord、审批状态。
- 输出：任务拆解、Worker 调用顺序、状态更新、人工审批请求。
- 能力边界：不直接生成设备控制指令；不绕过审核和审批。
- 协作关系：向感知 Agent 传递环境态势，向调度 Agent 传递可信上下文，向审核 Agent 传递候选方案，向执行 Agent 传递获批方案。
- 审计责任：所有关键状态转移必须进入 `TaskRecord.trace`。

## 2. 感知 Agent

- AgentTeams worker id：`perception_worker`
- 本地 actor：`perception_agent`
- 声明资源：`agentteams/workers/perception`
- 身份定位：能源运行上下文核验 Agent。
- 核心职责：核验负荷、光伏、储能 SOC、电价、设备状态、变压器温度、并网限制和生产计划。
- 输入：`Scenario`、`ExternalDataSnapshot`、设备状态、告警列表。
- 输出：`PerceptionReport`，包括数据完整性、异常、冲突、目标优先级、所需工具。
- 能力边界：只读；发现关键数据缺失或传感器冲突时必须进入 human_handoff。
- 协作关系：向调度 Agent 输出可信上下文和目标优先级；向 Team Leader 输出是否可以自动继续。
- 失败处理：时间戳不连续、生产计划无效、设备状态缺失时进入 request_missing_data 或 human_handoff。

## 3. 调度 Agent

- AgentTeams worker id：`dispatch_worker`
- 本地 actor：`dispatch_agent`
- 声明资源：`agentteams/workers/dispatch`
- 身份定位：策略生成和多方案比较 Agent。
- 核心职责：回放原 EMS 基线，调用优化算法生成充电、放电、购电、弃光、柔性负荷候选动作。
- 输入：可信 `Scenario`、站点约束、目标优先级、基线策略。
- 输出：`DispatchPlan[]`，包含 96 个 15 分钟动作点、策略说明和 metrics。
- 能力边界：只生成计划；不得直接执行设备动作或修改审批状态。
- 协作关系：接收感知 Agent 的上下文；向审核 Agent 交付候选方案和原 EMS 基线。
- 失败处理：优化器不可行时抛出 WorkflowError，由 Team Leader 标记 failed 或 human_handoff。

## 4. 审核 Agent

- AgentTeams worker id：`audit_worker`
- 本地 actor：`audit_agent`
- 声明资源：`agentteams/workers/audit`
- 身份定位：独立安全审计和确定性验证 Agent。
- 核心职责：逐点复算 SOC、PCS 功率、温度降额、变压器容量、并网功率、生产最低负荷、能量守恒和相对基线收益。
- 输入：`Scenario`、`DispatchPlan`、baseline plan。
- 输出：`AuditReport`，包括 approved、rejected、requires_approval、findings、checked_rules、improvement。
- 能力边界：fail closed；经济收益不能覆盖硬安全约束。
- 协作关系：向 Team Leader 返回哪些方案可选；向执行 Agent 输出是否需要审批。
- 失败处理：硬约束失败直接 rejected；柔性负荷削减但硬约束通过时 requires_approval。

## 5. 执行 Agent

- AgentTeams worker id：`execution_worker`
- 本地 actor：`execution_agent`
- 声明资源：`agentteams/workers/execution`
- 身份定位：获批计划映射、模拟执行和结果验证 Agent。
- 核心职责：把获批方案映射为 EMS、PCS、LOAD_CONTROLLER 幂等命令，在本地模拟器回放，并比较计划与实际。
- 输入：获批 `DispatchPlan`、`AuditReport`、可选 approval_id。
- 输出：`ExecutionCommand[]`、execution_summary、safe fallback policy。
- 能力边界：当前 MVP 真实设备连接数必须为 0；生产写入必须关闭。
- 协作关系：接收审核 Agent 放行结论；向审核 Agent 和 Team Leader 返回执行确认、偏差和回退结果。
- 失败处理：偏差超过 5% 或真实写入被尝试时触发 safe_fallback，并把控制权交还人工。

## 6. Human Operator

- AgentTeams resource：`park-operator`
- 身份定位：高风险动作审批人与接管者。
- 核心职责：审批或拒绝柔性负荷响应、生产影响策略和安全回退后的人工接管。
- 输入：审核摘要、候选方案影响、证据包。
- 输出：`ApprovalRecord`。
- 能力边界：审批只对当前 task_id 有效；外部数据变化产生的新子任务不得复用旧审批。
