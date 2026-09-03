# 完整场景链路验证材料

本证据包用于 GOAI 复赛提交，证明 EnergyMesh 在一次复合园区能源事件中完成了：

真实/公开数据输入 -> 系统读取与事件触发 -> AgentTeams 协作 -> Skill/Tool 调用 -> 方案重算与安全审核 -> 人工审批 -> 模拟执行 -> 回读验证与回滚。

## 核心链路

- 任务编号：`TASK-20260731-014`
- Trace：`TRACE-20260731-014`
- 场景：`pv-drop-hot-battery-peak-tariff`
- 决策快照：`CTX-014-V2`
- Context hash：`9419ec11ef09755dfb3c6984e0dde40b472f3ad5885327ade02de8c896421c20`
- 运行时间：`2026-07-31T14:00:01+08:00` 至 `2026-07-31T14:00:25+08:00`
- 执行模式：`simulation_mode=true`，`real_devices_contacted=0`
- 真实测试效果：原 EMS 固定策略成本 `15616.85` 元，Agent 运行后选中方案成本 `13628.21` 元，预计节省 `1988.64` 元，降幅 `12.7%`。

## 6 类证据

1. `01_真实数据输入/`
   - `emsx_site8_core_upload.csv`：EMSx site 8 处理后的 96 点输入数据。
   - `emsx_metadata.csv`：EMSx 站点容量、功率、效率等元数据。
   - `opencem_2025-07-a.csv` 与 `opencem_data_source.md`：公开 OpenCEM 数据与来源说明。
   - `data_source.md`：本证据包的数据口径说明。

2. `02_事件触发与快照/`
   - `event_snapshot_summary.json`：任务、触发、告警、设备状态、生产计划摘要。
   - `task_events_state_machine.json`：从接收到回滚的状态机事件。
   - `decision_context_snapshot_CTX-014-V2.json`：完整决策上下文快照。

3. `03_AgentTeams协作/`
   - `agent_handoffs.json`：Team Leader 到 Perception/Dispatch/Audit/Execution 的交接记录。
   - `agentteams_collaboration_trace.json`：事件流与 handoff 合并证据。

4. `04_Skill_Tool真调用/`
   - `skill_invocations.json`：`microgrid_context_ingest`、`dispatch_plan_generate`、`dispatch_audit_verify`、`execution_mapping` 的真实调用记录。

5. `05_方案废止_新方案_审批/`
   - `candidate_plans.json`：三套候选方案，含成本、最大功率、SOC、变压器负载率、动作。
   - `safety_audit_verdicts.json`：Candidate A 被安全审核拒绝，Candidate B/C 通过。
   - `human_approval.json`：人工审批绑定 candidate、task version 和 context hash。
   - `old_plan_invalidated_new_plan_selected.json`：V1 失效、V2 重新规划、B 方案被选中的证据。

6. `06_执行回读_前后对比/`
   - `baseline_vs_agent_savings.csv`：最关键表，明确对比原 EMS 固定策略与 Agent 运行后选中方案。
   - `baseline_vs_agent_selected_plan.json`：同一对比的结构化原始证据，来自 `runs/task_0243d286235e.json`。
   - `execution_commands.json`：EMS/BMS/PCS/MES 模拟执行指令。
   - `execution_readback_and_rollback.json`：执行回执、偏差验证、回滚记录、安全声明。
   - `before_after_metrics.csv`：候选方案、执行、回滚关键指标补充对比。

`99_原始完整归档/` 保留未拆分的完整运行归档，供交叉核验。

## 评审读取建议

先读本 README，再按 1 到 6 的目录顺序打开。核心可核验结论是：

- 数据不是页面手填 Demo 数字，而是来自仓内数据集和公开数据回放口径。
- 系统产生了 `REPLANNING_REQUIRED` 事件，不是人工随便点一次重新规划。
- 多 Agent 有明确 handoff，且每一步绑定同一个 `trace_id` 和 `context_hash`。
- Skill 调用有 `started_at`、`ended_at`、`duration_ms`、输入/输出引用。
- Candidate A 因变压器负载率 103.8% 被拒绝，Candidate B 被审核通过并经人工审批。
- 原 EMS 固定策略成本为 15616.85 元；Agent 选中方案成本为 13628.21 元，预计节省 1988.64 元，降幅 12.7%。
- 执行为数字孪生模拟，回读发现 7.8% 偏差超过 5% 阈值，系统进入回滚。
