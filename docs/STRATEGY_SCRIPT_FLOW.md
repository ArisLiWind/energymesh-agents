# 策略脚本与 Agent 信息流

EnergyMesh Agents 的核心不是让 Agent 在几套预置策略中做选择，而是在负荷、光伏、储能、电价、
变压器状态、并网限制、设备故障或生产计划发生变化时，由多 Agent 协作生成一段新的、可解释、
可审计、可回放的策略脚本。

## 1. 为什么是脚本

园区能源调度经常遇到未提前枚举的新情况。例如生产计划临时插入、变压器热态降额、光伏预测失真、
储能 SOC 低于预期、并网功率受限同时发生。此时只调整参数或选择已有策略模板，容易漏掉新的业务
约束和风险优先级。

因此调度 Agent 的职责应是生成策略脚本草案。脚本使用不需要编译器的受限 DSL，可采用 Python/Lua
风格表达式，但运行环境必须被沙箱约束：

- 不允许导入系统库。
- 不允许网络访问。
- 不允许文件读写。
- 不允许直接写 EMS、PCS、BMS、SCADA 或继电保护设备。
- 只能读取由感知 Agent 提供的可信上下文。
- 只能输出结构化调度动作，例如 charge_kw、discharge_kw、grid_import_kw、reserve_soc、shed_kw。

## 2. Agent 间信息流

```text
外部事件 / 人工需求
  -> Team Leader
  -> 感知 Agent
       输出：可信上下文、异常、冲突、目标优先级、可用工具
  -> 调度 Agent
       输入：可信上下文、目标优先级、站点约束、原 EMS 基线
       输出：策略脚本草案、脚本说明、预期指标、依赖假设
  -> 审核 Agent
       输入：策略脚本草案、可信上下文、基线策略、站点硬约束
       输出：静态审查结果、沙箱回放结果、约束复算、收益对比、审批要求
  -> Human Operator
       输入：需要审批的负荷削减、生产影响或风险动作
       输出：批准 / 拒绝 / 接管
  -> 执行 Agent
       输入：获批脚本的确定性输出、审核结论、审批记录
       输出：幂等执行命令、执行确认、偏差检测、安全回退
  -> Evidence Store
       保存：脚本版本、输入快照、回放指标、审批记录、执行证据、SHA-256
```

## 3. 各 Agent 的边界

### Team Leader

- 接收外部变化或人工策划需求。
- 判断旧任务是否失效。
- 生成新的 task_id，重新分派 Worker。
- 不写策略脚本，不直接执行设备动作。

### 感知 Agent

- 把原始 EMS/BMS/PCS/气象/MES 数据整理为可信上下文。
- 输出目标优先级，例如“生产安全优先于经济性”。
- 标记缺失、冲突和不可自动处理的数据。
- 不生成策略脚本。

### 调度 Agent

- 根据可信上下文写策略脚本草案。
- 脚本只表达调度逻辑和动作输出，不表达设备私有协议。
- 必须同时输出脚本说明、依赖假设和预期指标。
- 不拥有审批权和执行权。

### 审核 Agent

- 对脚本做静态审查，拦截越权语句、未知变量、未声明工具和不确定行为。
- 在沙箱中用相同输入回放脚本。
- 独立复算 SOC、功率、变压器容量、并网功率、生产约束和能量守恒。
- 经济收益不能覆盖硬安全约束。

### 执行 Agent

- 只消费审核通过并已审批的脚本输出。
- 把结构化动作映射为 EMS、PCS 和负荷控制系统的幂等命令。
- 当前 MVP 只进入本地模拟适配器。
- 偏差超过阈值时执行安全回退并交还人工。

## 4. 策略脚本示例

```python
# restricted EnergyMesh DSL, no imports, no device writes
for slot in horizon:
    reserve_soc = 0.35 if transformer_temp_c[slot] > 82 else 0.25
    if price[slot] >= peak_price and soc[slot] > reserve_soc:
        discharge_kw[slot] = min(pcs_limit_kw, load_kw[slot] * 0.22)
    elif pv_kw[slot] > load_kw[slot] and soc[slot] < 0.9:
        charge_kw[slot] = min(pcs_limit_kw, pv_kw[slot] - load_kw[slot])
    else:
        charge_kw[slot] = 0
        discharge_kw[slot] = 0

    if production_must_run[slot]:
        shed_kw[slot] = 0
```

这段脚本本身不能下发设备。它只产生 96 个 15 分钟动作点；审核 Agent 必须复算每个动作点是否满足
硬约束，执行 Agent 才能把通过审核的动作映射为模拟命令。

## 5. 审计证据

每次策略脚本闭环应至少保存：

- 输入外部数据快照。
- 感知 Agent 的可信上下文和目标优先级。
- 调度 Agent 生成的脚本草案、版本和说明。
- 审核 Agent 的静态审查结果。
- 沙箱回放后的 96 点动作、SOC 和功率曲线。
- 人工审批记录。
- 执行 Agent 的幂等命令和确认结果。
- evidence SHA-256。

这使策略生成从“Agent 说了算”变成“Agent 写脚本，程序可验证，人类可审批，结果可审计”。
