# EnergyMesh Agents

超境创新自研的多智能体能源调度系统，让能源调度从固定规则执行和自动滚动优化，走向
自主协同决策。

## 一、没有被充分利用的电力

在 AI 算力持续扩大、电力越来越短缺的同时，大量已经建设的光伏、储能和可调负荷，仍然
没有被真正充分利用起来。

大量园区、工业中心和算力中心已经部署能源管理系统，但这些系统的能力并不相同：

EnergyMesh Agents 基于 AgentTeams 构建 Team Leader 与「感知 Agent、调度 Agent、审核 Agent、执行 Agent」四类 Worker 协作链路：Team Leader 拆解任务并监督进度，感知 Agent 核验运行上下文，调度 Agent 不是简单选择已有策略，而是根据新情况生成可解释的策略脚本草案，审核 Agent 对脚本、回放结果、执行动作和证据进行安全审计，执行 Agent 只将获批脚本的确定性输出转换成具体设备、策略参数和执行位置。系统最终形成从任务输入、脚本生成、确定性验证、执行落位、审计验证到复盘沉淀的端到端闭环。

- **基础型 EMS** 主要依靠工程师预先设置运行时段、控制阈值和充放电规则，再按照固定策略
  自动执行。电价低时充电、电价高时放电，负荷超过阈值时削峰，光伏富余时优先储存。一旦
  设备、负荷、生产计划或电价机制变化，工程师需要重新调整规则和参数。
- **高级 EMS** 可以预测负荷、光伏出力和电价变化，并通过优化算法滚动生成新的调度方案。
  它不再只执行固定规则，但仍然在预先定义的目标、模型和约束内重新计算。

## 二、真正没有解决的问题

现实中的能源系统，并不总是一道已经定义好的数学题。

光伏出力、用电负荷、电价、生产计划、算力需求和设备状态每天都在变化。一次紧急生产任务、
一台设备异常升温、一组失真的传感器数据或一次突变天气，都可能让原来的调度目标和运行方案
同时失效。

基础型 EMS 依赖工程师修改策略；高级 EMS 可以重新优化，但仍需要一个已经被正确定义的问题：
优化目标是什么，哪些数据可信，约束是否变化，应调用什么模型，异常以后如何处理。

真正困难的是：现实变化以后，系统能否主动判断发生了什么、原任务是否仍然成立、还缺少哪些
信息，以及接下来应组织哪些系统采取行动。

## 三、EnergyMesh Agents

EnergyMesh Agents 不替代已有 EMS 和优化算法，而是在它们之上构建自主协同层，把原本分散在
工程师、能源管理系统、生产系统和设备控制系统之间的工作，组织成持续运行的闭环：

- **感知 Agent** 收集并核验负荷、光伏、储能 SOC、电价、设备状态和生产计划，发现数据缺失、
  异常和相互冲突，判断原调度任务是否仍然有效，并提出缺失信息与下一步动作。
- **调度 Agent** 根据重新确定的任务和目标优先级，选择并调用负荷预测、光伏预测、传感器一致性
  检查、热降额模型和优化算法，生成不需要编译器的受限策略脚本草案。脚本表达“何时充电、何时
  放电、保留多少备用容量、遇到异常如何降级”，而不是直接写设备。
- **审核 Agent** 先对策略脚本做静态审查，再在沙箱中确定性回放，独立复算储能 SOC、充放电功率、
  变压器热容量、并网功率、生产安全、能量守恒等约束，并在相同输入下判断新脚本是否真正优于
  原 EMS 方案。
- **执行 Agent** 只接收审核通过的脚本输出，将其映射为 EMS、储能 PCS 和负荷控制系统的结构化
  幂等指令，持续比较计划结果与实际结果。偏差超限时停止原策略、回退安全策略并把控制权交还
  工程师。

当负荷、天气、生产任务、传感器或设备状态再次变化时，系统创建新的子任务，重新经历感知、
任务判断、工具调用、策略脚本生成、脚本审核、审批、执行和验证；旧任务的审批绝不复用。

## 四、智能发生在变化之中

演示场景中，工业园区突然增加一项不可延期的生产任务，光伏出力低于预测，变压器温度异常，
并即将进入电价高峰。

感知 Agent 先判断原任务已经失效，再使用双路温度读数核验异常究竟是传感器错误还是设备风险。
读数冲突且无法消解时，系统停止自动调度并交还工程师；双路读数一致超限时，系统确认热风险，
降低变压器可用容量，并将优先级重排为“生产安全 → 设备热负载 → 关键负荷连续性 → 用电成本”。

调度 Agent 据此生成多个策略脚本草案。审核 Agent 拦截包含越权动作、低 SOC、变压器过载、
违反生产计划或没有证明优于原策略的脚本。获批脚本在模拟执行后持续核对购电功率、SOC 和设备
状态；实际结果偏离计划超过 5% 时，系统激活零充放电、零负荷削减的安全回退，并把控制权交还
工程师。

> 基础型 EMS 执行预先配置的规则；高级 EMS 在预先定义的目标和约束中动态优化；
> EnergyMesh Agents 进一步根据现实变化，组织数据核验、任务判断、工具调用、安全审核、
> 跨系统执行和结果验证。

对于园区，它让光伏、储能、充电设施和建筑负荷持续协同；对于工业中心，它让能源调度主动
适应生产计划和设备状态；对于算力中心，它可以协调算力负载、制冷、储能和供电容量，以更少
的实际电力支撑更多有效计算。

## 当前实现边界

当前版本使用开源 `agentscope-ai/AgentTeams` 的 Manager-Workers 协作框架作为多 Agent 运行
与治理底座。仓库提供 `agentteams/agentteams-resources.yaml` 声明式 Team/Human 资源，以及
Team Leader、四类 Worker、SOUL.md、AGENTS.md 和 Skill 资产；本地 FastAPI 服务承担能源业务
工具/API 层，并通过 `/api/agentteams/manifest` 暴露运行清单。当前通过
`/api/external/snapshot` 模拟 EMS、BMS、PCS、气象和 MES 外部数据输入，通过
`/api/external/dispatch` 触发完整多 Agent 调度闭环。当前不连接真实 EMS、BMS、PCS 或生产数据库，
不进行电芯控制、继电保护、潮流计算和线路故障控制。所有结构化“下发”只进入本地模拟适配器：

```text
SIMULATION_MODE=true
ALLOW_PRODUCTION_WRITE=false
AGENTTEAMS_ENABLED=true
```

## AgentTeams 开源框架对接

- 开源框架：`agentscope-ai/AgentTeams`
- AgentTeams quickstart 验证入口：`http://127.0.0.1:18088`（框架级验证入口；需另行启动
  AgentTeams quickstart。本地 FastAPI Demo 可独立复现能源业务闭环，完整参赛验证应启动
  quickstart 并加载本仓库声明式资源）
- 声明式资源：`agentteams/agentteams-resources.yaml`
- 本地 manifest：`GET /api/agentteams/manifest`
- Worker 包资产：`agentteams/`
- Team Leader：`agentteams/team-leader/SOUL.md` 与 `agentteams/team-leader/AGENTS.md`
- Workers：`agentteams/workers/perception|dispatch|audit|execution`
- Skills：`agentteams/skills/*/SKILL.md`

这套实现把 EnergyMesh 业务闭环明确映射到 AgentTeams 的 Manager-Workers 模式：Team Leader
负责任务拆解、上下文汇总和状态追踪，感知、调度、审核、执行四类 Worker 只处理各自职责内的
Skill。评审可先运行 FastAPI 控制台复现能源业务闭环，再在 AgentTeams quickstart 中加载
`agentteams/agentteams-resources.yaml` 验证角色编排、Skill 包、Worker 包和人工参与边界。
EnergyMesh 自身不构建通用 Agent 底座，而是作为园区微电网调度这个实际行业问题的
AgentTeams 业务团队和工具层。

## 评审核验入口

- **场景价值**：README 第一至四部分说明园区、工业中心和算力中心的真实问题、目标用户、痛点和收益；
  `docs/JUDGING_ALIGNMENT.md` 对应评分矩阵逐项给出证据。
- **外部数据输入**：`GET /api/external/snapshot` 模拟负荷、光伏、储能、电价、变压器、并网限制、
  设备故障和生产计划；`POST /api/external/dispatch` 用这些外部态势触发策略脚本生成和闭环调度。
- **多 Agent 协同**：`agentteams/agentteams-resources.yaml`、`agentteams/team-leader/*`、
  `agentteams/workers/*` 和 `/api/agentteams/manifest` 对应 AgentTeams 的角色编排、任务拆解、
  上下文传递、协同执行与状态追踪。
- **策略脚本信息流**：`docs/STRATEGY_SCRIPT_FLOW.md` 说明 Agent 之间如何传递事实、约束、脚本草案、
  静态审查结果、沙箱回放结果、审批记录和执行证据。
- **Agent Identity**：`docs/AGENT_IDENTITY.md` 说明每个 Agent 的身份、能力边界、输入输出和协同关系。
- **Skill 工程**：`agentteams/skills/*/SKILL.md` 与 `docs/SKILL_CONTRACTS.md` 说明 Skill 的用途、
  输入输出、调用条件、依赖工具、失败处理、安全边界、验证方式和复用价值。
- **MCP / RAG / 可观测 / 云工具链**：`docs/TOOLING_AND_CLOUD_INTEGRATION.md` 说明 FastAPI/OpenAPI
  等价工具契约、后续 MCP 迁移、共享状态、Trace、Metrics、PolarDB、Higress、Nacos、RocketMQ
  和 AgentLoop/LoongSuite 的必要性与替换边界。
- **工程运行与审计**：`make verify`、`tests/`、`runs/`、SQLite 状态、SHA-256 evidence、审批 gate
  和安全回退共同证明 Demo 可运行、动作可追踪、高风险步骤可审计。

## 一键运行

### 本地 Python

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

当前仓库还包含 Vercel Python serverless preview 配置：`api/index.py`、`vercel.json`、
`.python-version` 和 `uv.lock`。Vercel 适合公开演示；长期保存模型密钥、审计证据和运行历史时，
应迁移到 PolarDB for PostgreSQL 或等价外部数据库，而不是依赖 Vercel 的临时 `/tmp` 存储。

### AgentTeams 框架级验证

本地 FastAPI Demo 用于在没有 AgentTeams runtime 的环境中复现业务闭环；AgentTeams quickstart
用于验证协同框架接入，而不是可有可无的展示页。启动 AgentTeams quickstart 后，加载
`agentteams/agentteams-resources.yaml`。其中 `energymesh-local-api` 指向
`http://host.docker.internal:8000`，因此验证前应保持 FastAPI 服务运行，并确认
`GET /api/agentteams/manifest` 可返回 Team、Worker、Skill 和工具入口清单。

### Docker Compose

```bash
docker compose up --build
```

Compose 以非 root、只读根文件系统、无 Linux capabilities 的方式运行服务，并固定：

```text
SIMULATION_MODE=true
ALLOW_PRODUCTION_WRITE=false
```

## 演示流程

1. 页面先读取 `/api/external/snapshot`，模拟 EMS、BMS、PCS、气象和 MES 外部数据。
2. 页面通过 Three.js 加载可旋转、缩放的园区三维沙盘，并展示负荷、光伏、购电与 SOC 的
   96 点实时趋势。
3. 感知 Agent 判断原任务失效，核验双路传感器并重排目标优先级。
4. 系统计算原 EMS 固定策略基线，调度 Agent 再生成经济压力测试、安全均衡和保守保供三套策略
   脚本草案。
5. 审核 Agent 对脚本做静态审查和沙箱回放，独立复算 SOC、功率、变压器、并网、生产计划、
   能量守恒和相对基线收益。
6. 包含柔性负荷响应的安全均衡方案进入人工审批。
7. 批准后，执行 Agent 生成带幂等键的 EMS、PCS 和负荷控制命令，只在模拟器回放并确认 96 个时段。
8. SQLite 保存状态与轨迹，`runs/` 保存带 SHA-256 的 JSON 证据包。
9. 点击“注入变化并重调度”，验证数据变化如何触发一轮独立的新闭环。

测试还覆盖两条失败闭环：双路温度冲突时进入人工接管；模拟执行偏差超过 5% 时进入安全回退。

### Agent 对话规则

- 未选中任何 Agent 时，输入会进入多 Agent 协同模式，界面依次展示感知、调度、审核和执行
  Agent 基于当前场景与任务结果的协商过程。
- 手动选中一个 Agent 后，输入只进入该 Agent 的职责范围；点击“自动协同”或“退出单聊”
  才会恢复多 Agent 模式。
- 未配置模型时，对话能力使用本地、确定性的任务上下文回复，会引用实时点位、优化指标、审核
  结论和执行状态。
- 点击任意 Agent 头像可配置 OpenAI-compatible 模型网关参数：Base URL、API Key 和模型名称。
  API Key 只保存在后端，前端和 manifest 只返回 masked key。配置后，该 Agent 的测试对话和
  单聊可真实调用对应模型。

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
src/energymesh/   领域模型、外部数据模拟、优化、审计、编排、API 与控制台
tests/            优化、安全状态机与 API 测试
runs/             运行时证据包（默认不提交）
docs/             评审对齐、Agent Identity、Skill 契约、工具集成、架构与历史方案材料
```

工程边界与信任关系见 [ARCHITECTURE.md](ARCHITECTURE.md)，安全模型见
[SECURITY.md](SECURITY.md)，实际完成状态与限制见 [STATUS.md](STATUS.md)。参赛评审材料见
[docs/JUDGING_ALIGNMENT.md](docs/JUDGING_ALIGNMENT.md)、[docs/AGENT_IDENTITY.md](docs/AGENT_IDENTITY.md)、
[docs/SKILL_CONTRACTS.md](docs/SKILL_CONTRACTS.md) 与
[docs/TOOLING_AND_CLOUD_INTEGRATION.md](docs/TOOLING_AND_CLOUD_INTEGRATION.md)。前端所含 Three.js
许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
