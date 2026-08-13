# EnergyMesh Agents

2026 GOAI 新智基座 AI infra：面向工业园区、算力中心与分布式能源的多 Agent 电力自主协同调度系统。

EnergyMesh Agents 是 TRANSREALM 超境创新为真实能源场景构建的 AgentTeams 业务团队。它不让单一
大模型直接控制设备，而是在既有 EMS、BMS、PCS、SCADA、气象和 MES 系统之上增加一层可审计的
自主协同：当负荷、电价、光伏、储能、生产计划或设备状态发生变化时，系统重新判断原任务是否
仍然成立，由 Team Leader 指挥多个 Worker Agent 完成感知、规划、审核、审批、执行、验证、
回滚与证据沉淀。

> 传统 EMS 会执行规则；优化型 EMS 会重算方案；EnergyMesh Agents 要解决的是变化发生后，
> 系统能否重新理解任务、拆分责任、独立审核、受控执行，并把每一次决策沉淀为可复用经验。

## 核心问题

AI 算力正在推高数据中心和工业园区的用电需求，新能源、储能、电价机制和生产计划又让电力系统
的运行条件持续变化。很多园区已经接入 EMS 或 SCADA，但这些系统更擅长采集、展示、执行规则和
求解预设优化问题。真正困难的是：当现实条件改变以后，原来的调度任务是否还成立，哪些数据可信，
目标优先级是否需要重排，应该调用哪些工具，哪些方案必须被拦截，什么时候必须交给人。

EnergyMesh Agents 的设计目标不是替代已有系统，而是把工程师原本分散完成的判断、核验、重算、
审核、审批和复盘过程组织成标准闭环。它把高风险能源调度拆成多个权限分离的 Agent 角色，让任意
单个 Agent 都不能同时提案、审核自己并执行设备。

## 正确架构：Leader 指挥 Workers

本项目的运行形态是 AgentTeams 的 Leader + Workers 协作架构：

```text
任务输入
  ↓
Team Leader：理解目标、拆解任务、分派 Worker、监督状态、保持人工在环
  ↓
感知 Worker：读取外部态势，核验可信上下文，判断原任务是否失效
  ↓
调度 Worker：在可信上下文上生成候选策略脚本和 96 点调度方案
  ↓
审核 Worker：独立复算安全、业务和收益约束，fail closed
  ↓
风险判断：高风险进入 Human Operator 审批，低风险继续执行
  ↓
执行 Worker：只映射已审核、已审批或明确免审的方案，模拟执行并验证偏差
  ↓
证据沉淀：Trace / Metrics / Evidence
  ↓
经验沉淀：历史任务 / 策略模板 / RAG 知识库
  ↓
安全回退：偏差超阈值时停止策略、交还人工，并回到感知重新核验
```

这条链路对应官网架构图中的 14 个节点：任务输入、Team Leader、感知 Agent、可信上下文、调度
Agent、审核 Agent、风险判断、Human Operator、执行 Agent、证据沉淀、结果验证、安全回退、
回到感知、经验沉淀。核心原则是提案权、审核权、审批权、执行权分离。

## Agent 清单

| 角色 | AgentTeams 资源 | 身份定位 | 核心职责 | 权限边界 |
| --- | --- | --- | --- | --- |
| Team Leader | `energymesh_team_leader` | 调度团队指挥层 | 接收任务、拆解步骤、分派 Worker、汇总上下文、监督状态、触发人工审批和回滚 | 不直接生成设备控制命令，不跳过 Worker 审核 |
| Perception Worker | `perception_worker` | 电力运行上下文校验 | 核验 96 点负荷、光伏、SOC、电价、设备状态、生产计划和变压器温度，判断原 EMS 任务是否失效 | 只读，不生成调度方案，不写设备 |
| Dispatch Worker | `dispatch_worker` | 策略生成与候选方案 | 构建原 EMS 基线，生成经济优先、安全均衡、保守保供等候选策略脚本和 96 点调度计划 | 只提案，不审批，不执行，不越过审核 |
| Audit Worker | `audit_worker` | 独立安全审计 | 复算 SOC、PCS 功率、变压器容量、并网功率、生产最小负荷、能量守恒和相对基线收益 | fail closed；不可验证即拒绝；经济收益不覆盖硬约束 |
| Execution Worker | `execution_worker` | 获批计划映射与验证 | 将通过审核和审批的方案映射为幂等 EMS / PCS / 负荷控制命令，在模拟器中执行并验证计划与实际偏差 | 当前只模拟，真实设备接触数必须为 0，偏差超限即回退 |
| Human Operator | `park-operator` | 人工审批与接管 | 对高风险柔性负荷、越权边界和异常回退进行人工确认或驳回 | 审批绑定 `task_version` 与 `context_hash`，旧审批不能复用 |

## Skill 清单

| Skill | 由谁调用 | 输入 | 输出 | 安全边界 |
| --- | --- | --- | --- | --- |
| `microgrid_context_ingest` | Perception Worker / Team Leader | EMS、BMS、PCS、气象、MES、设备状态、生产约束 | 可信上下文、异常、冲突、目标优先级、所需工具 | 只读；缺数据或冲突时阻断自动调度 |
| `dispatch_plan_generate` | Dispatch Worker | 可信上下文、目标优先级、原 EMS 基线 | 候选策略脚本、96 点调度计划、成本/峰值/SOC 指标 | 只生成方案；无审批和执行权限 |
| `dispatch_audit_verify` | Audit Worker | 候选计划、场景约束、原 EMS 基线 | 审核结论、拒绝原因、约束复算、改进指标 | 关键约束失败即拒绝；柔性负荷动作需审批 |
| `execution_mapping` | Execution Worker | 获批计划、审核报告、审批记录、幂等键 | EMS / PCS / 负荷控制模拟命令、执行摘要、验证结果 | `SIMULATION_MODE=true`；不接触真实设备 |
| `approval_rollback` | Team Leader / Execution Worker | 审批请求、执行摘要、重优化触发 | 审批记录、回滚状态、安全策略、证据包 | 旧审批不可复用；偏差超阈值交还人工 |

## 电力闭环如何运行

演示场景中，14:00 工业园区出现复合变化：生产任务增加 420 kW，光伏实际出力低于预测 18.6%，
变压器双路温度读数冲突，并即将进入高峰电价。此时原 EMS 基线计划不再可信。

1. **任务输入**：告警、工单、外部数据或人工目标进入 Team Leader。
2. **任务拆解**：Team Leader 创建任务，要求 Perception Worker 先核验外部态势。
3. **感知核验**：Perception Worker 校验负荷、光伏、SOC、电价、设备状态、生产计划和温度冲突，
   生成可信上下文，判断原计划失效。
4. **可信上下文**：系统固化 `context_id`、`context_hash`、目标优先级、所需工具和自动化权限。
5. **策略生成**：Dispatch Worker 基于可信上下文生成候选调度策略，而不是直接控制设备。
6. **独立审核**：Audit Worker 对每个候选方案做静态审查、沙箱回放和确定性复算。
7. **风险判断**：高风险动作进入 Human Operator 审批；低风险且审核通过的动作才允许执行。
8. **人工审批**：审批绑定当前任务版本和上下文哈希，外部条件变化后必须重新审批。
9. **执行映射**：Execution Worker 将获批计划映射为幂等模拟命令。
10. **证据沉淀**：Trace、Metrics、Evidence、审批记录、执行回执和 SHA-256 证据包被保存。
11. **结果验证**：系统比较计划与实际，偏差超过阈值则停止策略。
12. **安全回退**：回退到零充放电、零负荷削减等安全策略，交还人工。
13. **重新感知**：回退或外部变化会创建新任务，回到感知环节。
14. **经验沉淀**：历史任务、策略模板、失败原因和审计证据进入后续 RAG / 知识库。

## 为什么需要多 Agent

能源系统不能让一个模型既制定方案、又审核自己、再直接控制设备。EnergyMesh Agents 的多 Agent
不是为了让 AI 更自由，而是为了让任何一个 AI 都没有独自犯下严重错误的权力。

- 感知和调度分离：数据是否可信先被确认，再允许生成方案。
- 调度和审核分离：方案必须由独立 Worker 复算和拦截。
- 审核和审批分离：高风险动作必须由 Human Operator 绑定版本确认。
- 审批和执行分离：Execution Worker 只能执行获批方案，不能改写目标。
- 执行和验证分离：计划与实际偏差超限时进入安全回退。
- 当前版本只做模拟执行：真实设备接触数为 0，所有写入进入本地模拟适配器。

## 当前实现

当前仓库包含两个层次：

- **AgentTeams 资产层**：`agentteams/agentteams-resources.yaml` 声明 Team、Leader、Workers、Human；
  `agentteams/team-leader/`、`agentteams/workers/*/` 和 `agentteams/skills/*/SKILL.md` 描述角色、灵魂、
  能力边界和 Skill 契约。
- **能源业务工具层**：本地 FastAPI 服务提供外部态势模拟、任务编排、候选方案生成、独立审核、
  审批、执行模拟、证据存储和 `/api/agentteams/manifest` 清单。

重要安全配置：

```text
SIMULATION_MODE=true
ALLOW_PRODUCTION_WRITE=false
AGENTTEAMS_ENABLED=true
```

当前不连接真实 EMS、BMS、PCS、SCADA 或生产数据库，不进行电芯控制、继电保护、潮流计算和线路
故障控制。所有结构化“下发”只进入本地模拟器。

- 开源框架：`agentscope-ai/AgentTeams`（官网：<https://hiclaw.io/>，原名 Hiclaw）
- AgentTeams quickstart 验证入口：`http://127.0.0.1:18088`（框架级验证入口；需另行启动
  AgentTeams quickstart。本地 FastAPI Demo 可独立复现能源业务闭环，完整参赛验证应启动
  quickstart 并加载本仓库声明式资源）
- 声明式资源：`agentteams/agentteams-resources.yaml`
- 本地 manifest：`GET /api/agentteams/manifest`
- Worker 包资产：`agentteams/`
- Team Leader：`agentteams/team-leader/SOUL.md` 与 `agentteams/team-leader/AGENTS.md`
- Workers：`agentteams/workers/perception|dispatch|audit|execution`
- Skills：`agentteams/skills/*/SKILL.md`

## API 与验证入口

| 入口 | 用途 |
| --- | --- |
| `GET /` | 本地演示界面 |
| `GET /api/health` | 运行状态与安全配置 |
| `GET /api/agentteams/manifest` | Team、Worker、Skill、Human 和模型配置清单 |
| `GET /api/external/snapshot` | 模拟 EMS / BMS / PCS / 气象 / MES 外部态势 |
| `POST /api/external/dispatch` | 用外部态势触发完整调度闭环 |
| `POST /api/demo/run` | 运行 14:00 复合变化演示 |
| `POST /api/tasks/{task_id}/approve` | 对获审方案进行人工审批 |
| `POST /api/tasks/{task_id}/execute` | 模拟执行获批方案 |
| `GET /api/tasks/{task_id}/evidence` | 查看证据包 |

## 一键运行

需要 Python 3.12 或更高版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
make verify
make run
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。OpenAPI 文档位于
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

Docker Compose：

```bash
docker compose up --build
```

## AgentTeams 框架级验证

本地 FastAPI Demo 可以独立复现能源业务闭环；AgentTeams quickstart 用于验证 Leader + Workers 的
框架接入。

1. 启动 EnergyMesh API：`make run`
2. 启动 AgentTeams quickstart / Element Web：`http://127.0.0.1:18088`
3. 加载 `agentteams/agentteams-resources.yaml`
4. 在 Team room 中提交园区调度任务
5. 观察 Team Leader 如何分派 Perception、Dispatch、Audit、Execution Workers，并在高风险动作前
   请求 Human Operator 审批

## 演示材料与评审核验

- **官网叙事**：TRANSREALM 官网将 EnergyMesh Agents 定义为面向工业园区、算力中心、储能与分布式
  能源的多智能体调度系统，强调约束核验、决策生成、执行验证和可审计证据闭环。
- **架构图对应**：本 README 的闭环流程对应官网“多 Agent 电力闭环架构图”。
- **Agent Identity**：见 `docs/AGENT_IDENTITY.md`。
- **Skill 契约**：见 `docs/SKILL_CONTRACTS.md` 与 `agentteams/skills/*/SKILL.md`。
- **策略脚本流**：见 `docs/STRATEGY_SCRIPT_FLOW.md`。
- **工具与云集成**：见 `docs/TOOLING_AND_CLOUD_INTEGRATION.md`。
- **安全模型**：见 `SECURITY.md`。
- **实现状态**：见 `STATUS.md`。

## 常用命令

```bash
make format       # Ruff 格式化与自动修复
make lint         # 格式和静态规则
make typecheck    # mypy 严格类型检查
make test         # 单元与 API 集成测试
make verify       # lint + typecheck + test
```

## 目录

```text
agentteams/       AgentTeams Team、Leader、Workers、Human、Skills 声明资产
src/energymesh/   领域模型、外部数据模拟、优化、审计、编排、API 与静态界面
tests/            优化、安全状态机与 API 集成测试
runs/             运行时证据包（默认不提交）
docs/             架构、Agent Identity、Skill 契约、策略流、评审材料
```

EnergyMesh Agents 的核心价值不是“AI 替人按按钮”，而是把电力系统在变化后的判断、规划、审核、
审批、执行、验证和经验沉淀做成可复用、可追踪、可回退的 AI infra。
