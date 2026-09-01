import { createCampus3D } from "/static/campus3d.js?v=20260831-wire-anchor-v8";
import { renderMarkdown } from "/static/markdown.js?v=20260806a";

const state = {
  run: null,
  task: null,
  context: null,
  candidates: [],
  audit: [],
  events: [],
  evidence: null,
  approval: null,
  campus3d: null,
  selectedAgent: "team_leader",
  gateways: {},
  language: "en",
  chartTick: 56,
  liveTimer: null,
  replayTimer: null,
  replayCursor: null,
  replayMode: window.localStorage.getItem("energymesh.replayMode") || "real",
  activeHistory: "new",
  activeScenario: null,
  agentThreads: {},
  runtimeSessionId: window.localStorage.getItem("energymesh.runtimeSessionId") || null,
  campusSimulation: {
    optimized: false,
    time: "未接入真实数据",
    balance: "等待 CSV",
    load: "-- kW",
    generation: "-- kW",
    storage: "--",
    storageFlow: "--",
    gridImport: "-- kW",
    todayLoad: 0, todayGen: 0, todayGrid: 0, todayCharge: 0, todayDischarge: 0, todayCost: 0,
    totalLoad: 0, fromGen: 0, fromStorage: 0, fromGrid: 0, toLoad: 0, toStorageCharge: 0, toGridExport: 0,
    wastedKwh: null,
    extraCost: null,
  },
  pendingExecutionScenario: null,
  selectedDeviceId: "pcs",
  selectedDeviceMode: "runtime",
  energySnapshot: null,
  monitor: null,
  monitorTimer: null,
  parallel: null,
  speedMode: "normal",
  parallelTimer: null,
  opsEvidence: null,
  flowPreview: null,
  lastCampusFlow: null,
  planLedger: [],
  agentTeamsTask: {
    taskId: window.localStorage.getItem("energymesh.agentteamsTaskId") || null,
    projectId: null,
    teamRoomId: null,
    taskRoomId: null,
    workerId: null,
    status: "IDLE",
    worldStateLoaded: false,
    events: [],
    completedStages: new Set(),
    activeStage: null,
  },
};

try {
  state.planLedger = JSON.parse(window.localStorage.getItem("energymesh.planLedger") || "[]");
} catch {
  state.planLedger = [];
}

const agentProfiles = {
  team_leader: {
    name: "EnergyMesh Team Leader",
    nameZh: "EnergyMesh Team Leader",
    role: "Tunes the live energy sandbox with you",
    roleZh: "园区调度负责人",
    defaultModel: "deepseek-chat",
    initials: "EM",
    avatar: "/static/avatars/perception.svg",
    tone: "leader",
  },
  perception_agent: {
    name: "Perception Worker",
    nameZh: "感知 Worker",
    role: "Context validation",
    roleZh: "运行上下文校验",
    defaultModel: "deepseek-chat",
    initials: "P",
    avatar: "/static/avatars/perception.svg",
    tone: "perception",
  },
  dispatch_agent: {
    name: "Dispatch Worker",
    nameZh: "调度 Worker",
    role: "Candidate planning",
    roleZh: "候选方案生成",
    defaultModel: "deepseek-chat",
    initials: "D",
    avatar: "/static/avatars/dispatch.svg",
    tone: "dispatch",
  },
  audit_agent: {
    name: "Audit Worker",
    nameZh: "审核 Worker",
    role: "Independent safety audit",
    roleZh: "独立安全审核",
    defaultModel: "deepseek-chat",
    initials: "A",
    avatar: "/static/avatars/audit.svg",
    tone: "audit",
  },
  execution_agent: {
    name: "Execution Worker",
    nameZh: "执行 Worker",
    role: "Approved command mapping",
    roleZh: "获批指令映射",
    defaultModel: "deepseek-chat",
    initials: "E",
    avatar: "/static/avatars/execution.svg",
    tone: "execution",
  },
};

const agentIntroMessages = {
  team_leader: {
    en: "I can chat normally and read the current park state after the model gateway is connected. I will report whether this interval is normal first, then propose a preview only when you ask to change the park.",
    zh: "接入模型网关后，我会像正常 AI 工程师一样和你对话。问园区时我会先汇报当前时段是否正常、发电/储能/用电/购电状态；只有你明确要调整时，才生成新流向预览。",
  },
  perception_agent: {
    en: "I am the Perception Worker. Ask me about load, PV, SOC, tariff, transformer telemetry, device state, or production constraints.",
    zh: "我是感知 Worker。你可以问我负荷、光伏、SOC、电价、变压器遥测、设备状态或生产约束。",
  },
  dispatch_agent: {
    en: "I am the Dispatch Worker. Ask me to compare candidate schedules, flexible-load moves, storage use, or peak-tariff strategies.",
    zh: "我是调度 Worker。你可以让我比较候选调度、柔性负荷迁移、储能使用或峰段电价策略。",
  },
  audit_agent: {
    en: "I am the Audit Worker. Ask me to verify a plan against safety, SOC, transformer, grid-import, and production constraints.",
    zh: "我是审核 Worker。你可以让我按安全、SOC、变压器、购电和生产约束复核方案。",
  },
  execution_agent: {
    en: "I am the Execution Worker. Ask me about approved command mapping, idempotency, execution receipts, verification, or rollback.",
    zh: "我是执行 Worker。你可以问我获批指令映射、幂等性、执行回执、验证或回滚。",
  },
};

const deviceDetails = {
  pcs: {
    name: "PCS-01 储能变流器",
    status: "正常",
    metrics: [
      ["实时功率", "0.00 kW"],
      ["SOC", "55%"],
      ["日充电量", "0.00 kWh"],
      ["日放电量", "0.00 kWh"],
      ["电池温度", "31.6°C"],
      ["可放电功率", "1.10 MW"],
    ],
    runtime: "PCS 在线，BMS 通讯正常，当前处于待命状态，可参与短时削峰和应急缓冲。",
    alerts: ["无活动告警", "SOC 低于 35% 时禁止长时放电"],
    operations: ["01:45 Agent 读取储能状态", "01:45 维持待命，不下发充放电指令"],
  },
  pv: {
    name: "PV-Array-02 光伏阵列",
    status: "低于预测",
    metrics: [
      ["实时功率", "335 kW"],
      ["预测偏差", "-18.6%"],
      ["日发电量", "0.00 kWh"],
      ["月发电量", "4.40 MWh"],
      ["逆变器温度", "42.8°C"],
      ["可用率", "98.7%"],
    ],
    runtime: "光伏出力低于预测，疑似云影遮挡；逆变器在线，未发现脱网。",
    alerts: ["出力低于预测阈值", "建议在调度中降低午后光伏可用假设"],
    operations: ["01:45 感知 Agent 读取光伏预测偏差", "01:46 调度 Agent 下调可用发电曲线"],
  },
  dg: {
    name: "DG-01 发电机",
    status: "待命",
    metrics: [
      ["可用功率", "457.44 kW"],
      ["当前输出", "0.00 kW"],
      ["日发电量", "2,726.00 kWh"],
      ["月发电量", "27.47 MWh"],
      ["缸套水温", "76.2°C"],
      ["燃油余量", "68%"],
    ],
    runtime: "发电机处于热备状态，可在电网受限或储能不足时接入保供。",
    alerts: ["无活动告警", "连续运行超过 4 小时需复核油量"],
    operations: ["01:45 Agent 标记为保供备用", "01:46 审核 Agent 校验启机边界"],
  },
};

const stateLabels = {
  en: {
    TASK_RECEIVED: "Task received",
    SENSING: "Sensing",
    CONTEXT_VALIDATED: "Context validated",
    REPLANNING_REQUIRED: "Replanning required",
    PLANNING: "Planning",
    AUDITING: "Auditing",
    AWAITING_APPROVAL: "Awaiting approval",
    EXECUTING: "Executing",
    VERIFYING: "Verifying",
    COMPLETED: "Completed",
    REJECTED: "Rejected",
    ROLLBACK: "Rollback",
    FAILED: "Failed",
    IDLE: "IDLE",
  },
  zh: {
    TASK_RECEIVED: "任务已接收",
    SENSING: "感知中",
    CONTEXT_VALIDATED: "上下文已校验",
    REPLANNING_REQUIRED: "需要重规划",
    PLANNING: "规划中",
    AUDITING: "审核中",
    AWAITING_APPROVAL: "等待人工审批",
    EXECUTING: "执行中",
    VERIFYING: "验证中",
    COMPLETED: "已完成",
    REJECTED: "已拒绝",
    ROLLBACK: "偏差超限·已回滚保护",
    FAILED: "失败",
    IDLE: "空闲",
  },
};

const actorLabels = {
  en: {
    "Team Leader": "Team Leader",
    "Perception Agent": "Perception Worker",
    "Dispatch Agent": "Dispatch Worker",
    "Audit Agent": "Audit Worker",
    "Human Approval": "Human Operator",
    "Execution Agent": "Execution Worker",
    Verification: "Verification",
  },
  zh: {
    "Team Leader": "Team Leader",
    "Perception Agent": "感知 Worker",
    "Dispatch Agent": "调度 Worker",
    "Audit Agent": "审核 Worker",
    "Human Approval": "人工审批",
    "Execution Agent": "执行 Worker",
    Verification: "结果验证",
  },
};

const translations = {
  en: {
    homeTitle: "All insights",
    homeSubtitle: "Recent tasks",
    homeSearchPlaceholder: "Search tasks",
    historyCritical: "Critical",
    historyHigh: "High",
    historyApproved: "Awaiting approval",
    historyTraceReady: "Trace ready",
    historyRejected: "Rejected",
    historyRollback: "Rollback",
    historyWeatherTitle: "Weather-shock campus redispatch",
    historyWeatherText: "Cloud cover cut PV below forecast, production load rose, and the system invalidated the old plan before producing a safer lower-cost schedule.",
    workspaceTitle: "Energy flow cockpit",
    agentDirectory: "Agent directory",
    workersLabel: "Workers",
    perceptionBrief: "Context validation",
    dispatchBrief: "Candidate planning",
    auditBrief: "Independent safety audit",
    executionBrief: "Approved command mapping",
    operatorPrompt: "When park operating conditions change, determine whether the original dispatch task still holds.",
    diagP1: "The current run indicates the original EMS baseline is no longer reliable. Production load increased, PV output fell below forecast, transformer temperature readings conflict, and the tariff is entering peak period.",
    diagP2: "Team Leader should command the Worker Agents in sequence: validate context first, generate candidates only after the context is trusted, audit every plan independently, then request human approval before execution.",
    step1Strong: "Validate the context:",
    step1Text: "Perception Worker checks load, PV, SOC, tariff, transformer sensors, device state, and MES production constraints before any optimization.",
    step2Strong: "Generate bounded plans:",
    step2Text: "Dispatch Worker authors candidate scripts and 96-point schedules, but does not approve or execute equipment commands.",
    step3Strong: "Audit before action:",
    step3Text: "Audit Worker recomputes SOC, grid import, transformer load, production minimums, and improvement against baseline. Unsafe plans fail closed.",
    step4Strong: "Execute only approved work:",
    step4Text: "Execution Worker maps the approved plan to idempotent simulated EMS / PCS / load-control commands and verifies actual-vs-plan deviation.",
    plotChip: "▥ Plot",
    runButton: "Run 14:00 compound change",
    approveButton: "Approve B",
    executeButton: "Execute",
    rollbackButton: "Rollback scene",
    visualTitle: "Energy flow sandbox",
    visualSubtitle: "",
    taskLabel: "Task",
    plotTitle: "",
    assetFactory: "Factory",
    assetFactoryNote: "MES +420 kW",
    assetPv: "PV",
    assetPvNote: "-18.6% forecast",
    assetStorage: "Storage",
    assetStorageNote: "simulated PCS",
    assetGrid: "Grid",
    assetGridNote: "import limited",
    assetCharge: "Charging",
    assetChargeNote: "flexible load",
    assetCompute: "Compute",
    assetComputeNote: "critical load",
    relatedTitle: "Related insights",
    taskVersionLabel: "Task version",
    riskGateLabel: "Risk gate",
    riskGateText: "High-risk flexible-load actions require Human Operator approval.",
    evidenceLabel: "Evidence",
    evidenceText: "Trace, metrics, execution receipt, and SHA-256 package.",
    candidatePlansTitle: "Candidate plans",
    focusButton: "Focus",
    candidateEmpty: "Run the scenario to generate audited candidates.",
    traceTitle: "Trace",
    evidenceButton: "Evidence",
    traceEmpty: "Backend events will appear here.",
    chatKicker: "Team Leader",
    chatTitle: "AI dispatch conversation",
    chatIntro: "After the model gateway is connected, I can chat normally and read the current park state. I report normal/abnormal operation first, then create a flow preview only when you ask to change the park.",
    chatPlaceholder: "Try: reduce grid import and curtailment, preview the new flow",
    chatSend: "Send",
    chatButton: "Chat",
    gatewayButton: "Gateway",
    gatewayBaseUrl: "Base URL",
    gatewayApiKey: "API Key",
    gatewayModel: "Model",
    gatewayTest: "Test",
    gatewaySave: "Save gateway",
    gatewayStored: "Gateway settings are stored locally for now.",
    you: "You",
    noTask: "not created",
    noCandidates: "no candidates yet",
    waiting: "Waiting",
    needsHuman: "Needs human",
    approved: "Approved",
    notSealed: "Not sealed",
    ready: "Ready",
    sealed: "Sealed",
    pendingAudit: "Pending audit",
    auditPassed: "Audit passed",
    rejected: "Rejected",
    events: "events",
    contextPending: "Context hash pending",
  },
  zh: {
    homeTitle: "全部洞察",
    homeSubtitle: "最近任务",
    homeSearchPlaceholder: "搜索任务",
    historyCritical: "严重",
    historyHigh: "高",
    historyApproved: "等待审批",
    historyTraceReady: "Trace 已就绪",
    historyRejected: "已拒绝",
    historyRollback: "已回滚",
    historyWeatherTitle: "天气突变后的园区重调度",
    historyWeatherText: "云层突变导致光伏低于预测，生产负荷上升，系统废止旧计划并重新生成更低成本的安全方案。",
    workspaceTitle: "能源流动驾驶舱",
    agentDirectory: "Agent 通讯录",
    workersLabel: "Worker Agents",
    perceptionBrief: "运行上下文校验",
    dispatchBrief: "候选方案生成",
    auditBrief: "独立安全审核",
    executionBrief: "获批指令映射",
    operatorPrompt: "当园区运行条件发生变化时，判断原调度任务是否仍然成立。",
    diagP1: "当前运行表明原 EMS 基线已不再可靠。生产负荷增加，光伏出力低于预测，变压器温度读数冲突，并且电价即将进入高峰时段。",
    diagP2: "Team Leader 应按顺序指挥 Worker Agents：先校验上下文，只有上下文可信后才生成候选方案，再独立审核每个计划，最后在执行前请求人工审批。",
    step1Strong: "校验上下文：",
    step1Text: "Perception Worker 在任何优化前检查负荷、光伏、SOC、电价、变压器传感器、设备状态和 MES 生产约束。",
    step2Strong: "生成受限方案：",
    step2Text: "Dispatch Worker 编写候选策略脚本和 96 点调度计划，但不审批、不执行设备命令。",
    step3Strong: "行动前审核：",
    step3Text: "Audit Worker 复算 SOC、购电功率、变压器负载、生产最小负荷和相对基线收益；不安全方案默认关闭。",
    step4Strong: "只执行获批工作：",
    step4Text: "Execution Worker 只把获批计划映射为幂等的模拟 EMS / PCS / 负荷控制命令，并验证计划与实际偏差。",
    plotChip: "▥ 图表",
    runButton: "运行14:00复合变化",
    approveButton: "审批 B",
    executeButton: "执行",
    rollbackButton: "回滚场景",
    visualTitle: "能源流动沙盘",
    visualSubtitle: "",
    taskLabel: "任务",
    plotTitle: "",
    assetFactory: "工厂",
    assetFactoryNote: "MES +420 kW",
    assetPv: "光伏",
    assetPvNote: "较预测 -18.6%",
    assetStorage: "储能",
    assetStorageNote: "模拟 PCS",
    assetGrid: "电网",
    assetGridNote: "购电受限",
    assetCharge: "充电",
    assetChargeNote: "柔性负荷",
    assetCompute: "算力",
    assetComputeNote: "关键负荷",
    relatedTitle: "相关洞察",
    taskVersionLabel: "任务版本",
    riskGateLabel: "风险闸门",
    riskGateText: "高风险柔性负荷动作必须经过人工操作员审批。",
    evidenceLabel: "证据",
    evidenceText: "Trace、Metrics、执行回执与 SHA-256 证据包。",
    candidatePlansTitle: "候选方案",
    focusButton: "聚焦",
    candidateEmpty: "运行场景后生成带审核结论的候选方案。",
    traceTitle: "Trace",
    evidenceButton: "证据",
    traceEmpty: "后端事件会显示在这里。",
    chatKicker: "Team Leader",
    chatTitle: "AI 调度对话",
    chatIntro: "接入模型网关后，我会像正常 AI 工程师一样对话。问园区时先汇报当前时段是否正常、发电/储能/用电/购电状态；明确要调整时，才生成新流向预览。",
    chatPlaceholder: "例如：帮我减少购电和限发，先预览新流向",
    chatSend: "发送",
    chatButton: "对话",
    gatewayButton: "网关",
    gatewayBaseUrl: "Base URL",
    gatewayApiKey: "API Key",
    gatewayModel: "模型",
    gatewayTest: "测试",
    gatewaySave: "保存网关",
    gatewayStored: "网关设置目前保存在本地。",
    you: "你",
    noTask: "未创建",
    noCandidates: "暂无候选方案",
    waiting: "等待",
    needsHuman: "需要人工",
    approved: "已审批",
    notSealed: "未封存",
    ready: "已就绪",
    sealed: "已封存",
    pendingAudit: "等待审核",
    auditPassed: "审核通过",
    rejected: "已拒绝",
    events: "个事件",
    contextPending: "上下文哈希待生成",
  },
};

const historyThreads = {
  weather: {
    taskId: "TASK-20260731-014",
    agentId: "team_leader",
    en: {
      opener: "Open weather-shock redispatch",
      messages: [
        { role: "user", text: "Open the weather-shock redispatch task and show what changed." },
        { role: "agent", agentId: "team_leader", text: "Opened TASK-20260731-014. The old EMS baseline was invalidated after cloud cover reduced PV output, production load increased, and peak tariff pressure started." },
        { role: "agent", agentId: "perception_agent", text: "Perception result: PV is 18.6% below forecast, production demand is 420 kW higher, SOC is 55%, and transformer telemetry needs conservative handling." },
        { role: "agent", agentId: "dispatch_agent", text: "Dispatch result: generated three bounded candidates. Candidate B trades a little cost for transformer headroom, SOC reserve, and production continuity." },
        { role: "agent", agentId: "audit_agent", text: "Audit result: Candidate A was rejected; Candidate B passed safety checks and waits for approval bound to the task version and context hash." },
        { role: "agent", agentId: "team_leader", text: "Outcome visible in the console: compare candidates, inspect trace, approve the safe plan, then execute to seal evidence and verify actual-vs-plan behavior." },
      ],
    },
    zh: {
      opener: "打开天气突变重调度",
      messages: [
        { role: "user", text: "打开天气突变重调度任务，说明过去这次调度发生了什么。" },
        { role: "agent", agentId: "team_leader", text: "已打开 TASK-20260731-014。云层突变让光伏出力低于预测，生产负荷又临时升高，原 EMS 基线计划被判定失效。" },
        { role: "agent", agentId: "perception_agent", text: "感知结果：光伏较预测 -18.6%，生产负荷 +420 kW，储能 SOC 55%，变压器遥测按保守边界处理。" },
        { role: "agent", agentId: "dispatch_agent", text: "调度结果：生成 3 个受约束候选方案。Candidate B 在成本、变压器余量、SOC 保留和生产连续性之间更稳。" },
        { role: "agent", agentId: "audit_agent", text: "审核结果：Candidate A 被拒绝；Candidate B 通过安全审核，等待绑定任务版本和上下文哈希的人工审批。" },
        { role: "agent", agentId: "team_leader", text: "控制台里可以继续查看候选方案、Trace、审批状态和证据包；审批并执行后会封存回执并验证实际与计划偏差。" },
      ],
    },
  },
};

const naturalScenarios = {
  production_load: {
    match: (text) => /生产一区|800\s*kw|800kW|增加.*负荷|能源策略/i.test(text),
    title: "生产一区 800kW 负荷增加评估",
    taskId: "DEMO-PROD-800KW",
    selectedAgent: "team_leader",
    tools: ["get_energy_state", "get_production_rules", "generate_dispatch_plan"],
    endpoint: "GET /energy/state?zone=production-1&date=tomorrow",
    apiResponse: "Current load 6.8MW / Available margin 2.4MW / Storage SOC 61% / Peak tariff 18:00-22:00",
    rag: ["生产一区保供规则", "峰段削峰策略模板", "历史 800kW 增产调度案例"],
    cards: [
      { title: "MCP", text: "读取当前负荷、储能 SOC、光伏预测和明日电价窗口。" },
      { title: "RAG", text: "检索生产一区连续供电规则与增产最低保障约束。" },
      { title: "Agent", text: "调度 Worker 生成移峰填谷方案，审核 Worker 验证变压器与 SOC 安全边界。" },
    ],
    steps: [
      ["Task Understanding", "识别：生产一区明天新增 800kW 负荷，需要判断是否调整能源策略。"],
      ["Tool Selection", "选择工具：get_energy_state、get_production_rules、generate_dispatch_plan。"],
      ["MCP Gateway Request", "GET /energy/state?zone=production-1&date=tomorrow"],
      ["API Response", "可用容量 2.4MW，储能 SOC 61%，18:00 后进入峰段电价。"],
      ["Knowledge Retrieval", "RAG：检索生产规则、峰段调度模板、历史增产案例。"],
      ["Planning Agent", "生成方案：午间提高储能充电，17:30 前完成关键产线预冷和柔性负荷前移。"],
      ["Audit Agent", "验证：变压器负载峰值 86%，SOC 最低 38%，满足生产保供约束。"],
      ["Leader Response", "结论：需要调整能源策略，建议采用受限削峰方案，避免峰段购电增加。"],
    ],
    reply: "我识别到这是“生产负荷变化后的能源策略调整”任务。当前可用容量可以覆盖新增 800kW，但如果不调整策略，18:00 后峰段购电会明显上升。建议：明天中午优先利用光伏给储能补能，17:30 前把可前移负荷完成，峰段由储能承担约 520kW，剩余 280kW 由电网补足。审核结果显示变压器峰值约 86%，SOC 最低约 38%，可以执行，但需要保留生产一区最低供电约束。",
    executionPurpose: "执行方案 B 后，新增 800kW 生产负荷可被纳入明日计划，18:00-22:00 峰段购电被压低，变压器峰值控制在 86% 左右，储能 SOC 最低保持约 38%。",
  },
  ai_center: {
    match: (text) => /AI|算力中心|6\s*mw|6MW|电力.*支持|容量/i.test(text),
    title: "AI 算力中心 6MW 接入评估",
    taskId: "DEMO-AIDC-6MW",
    selectedAgent: "team_leader",
    tools: ["get_power_capacity", "get_transformer_status", "get_storage_status"],
    endpoint: "GET /energy/capacity?load=6MW&type=ai-datacenter",
    apiResponse: "Current Capacity 10MW / Available 3.2MW / Transformer spare 3.6MW / Storage firm support 0.8MW",
    rag: ["数据中心供电标准", "AI 算力中心 N+1 供电建议", "园区历史扩容案例"],
    cards: [
      { title: "MCP", text: "查询总容量、变压器余量、储能可支撑时长和当前负荷曲线。" },
      { title: "RAG", text: "检索数据中心供电规范、N+1 冗余要求和历史扩容案例。" },
      { title: "Agent", text: "规划 Agent 判断 6MW 不能直接接入，需分阶段扩容和配套储能。" },
    ],
    steps: [
      ["Task Understanding", "识别：AI 算力中心新增接入评估，目标负荷 6MW。"],
      ["Tool Selection", "选择工具：get_power_capacity、get_transformer_status、get_storage_status。"],
      ["MCP Gateway Request", "GET /energy/capacity?load=6MW&type=ai-datacenter"],
      ["API Response", "Current Capacity: 10MW；Available: 3.2MW；稳定支撑缺口约 2.8MW。"],
      ["Knowledge Retrieval", "RAG：检索数据中心供电标准、N+1 冗余要求、历史扩容案例。"],
      ["Planning Agent", "生成方案：新增 4MW 变压器容量，配置 2MWh 储能，分两阶段接入算力负荷。"],
      ["Audit Agent", "验证安全约束：现状不支持一次性 6MW 接入；扩容后可满足冗余和峰段约束。"],
      ["Leader Response", "结论：当前园区不支持直接新增 6MW，需要先做电力基础设施扩容。"],
    ],
    reply: "我识别到这是“AI 算力中心接入容量评估”任务。MCP 查询显示园区当前总容量约 10MW，可用余量约 3.2MW；你提出的 6MW 负荷超过当前可用容量，稳定缺口约 2.8MW。结合 RAG 检索到的数据中心供电标准，我不建议直接接入。建议先新增至少 4MW 变压器容量，并配置约 2MWh 储能或等效备用能力，再按 2MW + 4MW 两阶段接入。",
    executionPurpose: "确认后将生成扩容实施任务：新增至少 4MW 变压器容量、配置约 2MWh 储能或备用能力，并把 AI 算力中心接入拆成 2MW + 4MW 两阶段，避免一次性接入造成容量风险。",
  },
  transformer_temperature: {
    match: (text) => /2号变压器|2 号变压器|温度异常|变压器.*异常|发热/i.test(text),
    title: "2号变压器温度异常分析",
    taskId: "DEMO-TR02-TEMP",
    selectedAgent: "team_leader",
    tools: ["get_transformer_status", "get_thermal_history", "get_load_curve"],
    endpoint: "GET /equipment/transformers/TR-02/status",
    apiResponse: "TR-02 temp 92°C / Load 91% / Fan group B offline / Ambient 34°C / Oil temp rising 1.8°C per 10min",
    rag: ["变压器温升故障案例", "风机组异常处置手册", "高温天气降载策略"],
    cards: [
      { title: "MCP", text: "读取 2号变压器温度、负载率、风机组、环境温度与历史曲线。" },
      { title: "RAG", text: "检索历史温升故障、风冷系统处置手册和高温降载策略。" },
      { title: "Agent", text: "感知 Worker 定位风险，审核 Worker 给出处置边界和降载建议。" },
    ],
    steps: [
      ["Task Understanding", "识别：设备异常诊断任务，目标设备为 2号变压器。"],
      ["Tool Selection", "选择工具：get_transformer_status、get_thermal_history、get_load_curve。"],
      ["MCP Gateway Request", "GET /equipment/transformers/TR-02/status"],
      ["API Response", "温度 92°C，负载率 91%，B 组风机离线，油温仍在上升。"],
      ["Knowledge Retrieval", "RAG：检索变压器温升故障、风机组异常和高温天气降载案例。"],
      ["Planning Agent", "生成处理建议：先切换备用风机，10 分钟内将非关键负荷下调 600kW。"],
      ["Audit Agent", "验证：若温升继续超过 95°C，应进入人工确认和保护降载。"],
      ["Leader Response", "结论：高概率为风机组故障叠加高负载导致，应立即降载并派检修。"],
    ],
    reply: "我识别到这是“设备异常诊断与风险处置”任务。MCP 返回显示 2号变压器温度约 92°C、负载率 91%，B 组风机离线，油温仍在上升。结合历史故障 RAG，最可能原因是风冷能力下降叠加高负载。建议立即切换备用风机，并在 10 分钟内下调约 600kW 非关键负荷；如果温度继续接近 95°C，应进入人工确认和保护降载流程。",
    executionPurpose: "确认后将执行安全处置：切换备用风机、下调约 600kW 非关键负荷并创建检修工单，目标是在 10 分钟内阻止温度继续逼近 95°C 保护阈值。",
  },
  storage_status: {
    match: (text) => /储能状态|当前.*储能|查询.*储能|storage status/i.test(text),
    title: "园区储能状态查询",
    taskId: "DEMO-MCP-STORAGE",
    selectedAgent: "team_leader",
    tools: ["get_storage_status"],
    endpoint: "GET /energy/storage/status",
    apiResponse: "SOC 55% / Available discharge 1.1MW / Available charge 0.9MW / PCS healthy / Estimated duration 42min",
    rag: ["储能运行边界", "PCS 健康检查规则"],
    cards: [
      { title: "MCP", text: "基础测试：通过 MCP Gateway 查询当前储能状态。" },
      { title: "RAG", text: "读取储能 SOC 和 PCS 健康边界说明，用于解释查询结果。" },
      { title: "Agent", text: "Leader 返回状态摘要，并说明可放电功率和可支撑时长。" },
    ],
    steps: [
      ["Task Understanding", "识别：基础状态查询，不需要生成调度方案。"],
      ["Tool Selection", "选择工具：get_storage_status。"],
      ["MCP Gateway Request", "GET /energy/storage/status"],
      ["API Response", "SOC 55%，可放电 1.1MW，可充电 0.9MW，PCS healthy。"],
      ["Knowledge Retrieval", "RAG：检索储能运行边界与 PCS 健康检查规则。"],
      ["Leader Response", "结论：储能状态正常，可用于短时削峰，但不建议承担长时间 1MW 以上负荷。"],
    ],
    reply: "我已通过 MCP Gateway 查询当前园区储能状态：SOC 约 55%，PCS 健康，可放电功率约 1.1MW，可充电功率约 0.9MW，按当前状态约可稳定支撑 42 分钟。结论：储能可用于短时削峰或应急缓冲，但不建议在未补能前承担长时间 1MW 以上负荷。",
    executable: false,
  },
};

function $(selector) {
  return document.querySelector(selector);
}

function $$(selector) {
  return [...document.querySelectorAll(selector)];
}

function escapeHTML(value) {
  return `${value ?? ""}`
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function t(key) {
  return translations[state.language]?.[key] || translations.en[key] || key;
}

function agentName(agentId) {
  const profile = agentProfiles[agentId] || agentProfiles.team_leader;
  return state.language === "zh" ? profile.nameZh : profile.name;
}

function agentRole(agentId) {
  const profile = agentProfiles[agentId] || agentProfiles.team_leader;
  return state.language === "zh" ? profile.roleZh : profile.role;
}

function agentProfile(agentId) {
  return agentProfiles[agentId] || agentProfiles.team_leader;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

async function requestAllowingError(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  window.setTimeout(() => $("#toast").classList.remove("visible"), 2400);
}

const agentTeamsStageOrder = [
  "task_created",
  "worker_joined",
  "tool_call",
  "dispatch_plan",
  "audit_verdict",
  "awaiting_approval",
  "execution_receipt",
  "completed",
];

function compactId(value) {
  if (!value) return "--";
  const text = String(value);
  if (text.length <= 22) return text;
  return `${text.slice(0, 10)}...${text.slice(-8)}`;
}

function normalizeAgentTeamsEvent(event = {}) {
  const standard = event.standard_event || event;
  return {
    type: standard.type || event.type || "step_started",
    rawType: standard.raw_type || event.type || "",
    sessionId: standard.session_id || event.session_id || state.runtimeSessionId,
    taskId: standard.task_id || event.task_id || null,
    projectId: standard.project_id || event.project_id || null,
    teamRoomId: standard.team_room_id || event.team_room_id || null,
    taskRoomId: standard.task_room_id || event.task_room_id || null,
    workerId: standard.worker_id || standard.agent_id || event.agent_id || null,
    agentId: standard.agent_id || event.agent_id || "agentteams_manager",
    message: standard.message || event.message || event.stage || event.type || "",
    worldStateLoaded: Boolean(standard.world_state || event.world_state || event.world_state_loaded),
    dispatchPlan: standard.dispatch_plan || event.dispatch_plan || standard.payload?.dispatch_plan || null,
    impact: standard.impact || event.impact || standard.payload?.impact || null,
    payload: standard.payload || event,
    at: standard.observed_at || new Date().toISOString(),
  };
}

function renderAgentTeamsTaskPanel() {
  const panel = $("#agentteams-task-panel");
  if (!panel) return;
  const task = state.agentTeamsTask;
  $("#agentteams-task-title").textContent = task.status === "IDLE" ? "等待调度请求" : "真实 AgentTeams 工作流进行中";
  $("#agentteams-project-id").textContent = compactId(task.projectId);
  $("#agentteams-runtime-task-id").textContent = compactId(task.taskId);
  $("#agentteams-team-room-id").textContent = compactId(task.teamRoomId);
  $("#agentteams-worker-id").textContent = compactId(task.workerId);
  $("#agentteams-world-state").textContent = task.worldStateLoaded ? "已载入" : "等待";
  $("#agentteams-task-status").textContent = task.status;
  $$("#agentteams-stage-list article").forEach((item) => {
    const stage = item.dataset.stage;
    item.classList.toggle("done", task.completedStages.has(stage));
    item.classList.toggle("active", task.activeStage === stage && !task.completedStages.has(stage));
  });
  const timeline = $("#agentteams-timeline");
  timeline.innerHTML = "";
  task.events.slice(-12).forEach((item) => {
    const row = document.createElement("p");
    const time = new Date(item.at).toLocaleTimeString("zh-CN", { hour12: false });
    row.innerHTML = `<strong>${escapeHTML(time)} ${escapeHTML(item.agentId || item.workerId || "AgentTeams")}</strong> ${escapeHTML(item.message).slice(0, 220)}`;
    timeline.append(row);
  });
}

function applyAgentTeamsEvent(event) {
  const normalized = normalizeAgentTeamsEvent(event);
  const task = state.agentTeamsTask;
  if (normalized.taskId) {
    task.taskId = normalized.taskId;
    window.localStorage.setItem("energymesh.agentteamsTaskId", normalized.taskId);
  }
  if (normalized.projectId) task.projectId = normalized.projectId;
  if (normalized.teamRoomId) task.teamRoomId = normalized.teamRoomId;
  if (normalized.taskRoomId) task.taskRoomId = normalized.taskRoomId;
  if (normalized.workerId) task.workerId = normalized.workerId;
  if (normalized.worldStateLoaded) task.worldStateLoaded = true;
  task.status = normalized.type === "failed" ? "FAILED" : normalized.type === "completed" ? "COMPLETED" : "RUNNING";
  task.activeStage = normalized.type;
  const stageIndex = agentTeamsStageOrder.indexOf(normalized.type);
  if (stageIndex >= 0) {
    agentTeamsStageOrder.slice(0, stageIndex).forEach((stage) => task.completedStages.add(stage));
    if (["completed", "execution_receipt"].includes(normalized.type)) task.completedStages.add(normalized.type);
  }
  task.events.push(normalized);
  if (task.events.length > 80) task.events = task.events.slice(-80);
  if (normalized.type === "dispatch_plan" && state.energySnapshot && !state.flowPreview) {
    const flowPreview = previewFlowFromLatestSnapshot();
    if (flowPreview) {
      showCampusPlanPreview(flowPreview.currentFlow, flowPreview.previewFlow, {
        title: "AgentTeams 真实调度方案",
        source: "agentteams",
        reason: agentTeamsPlanReason(normalized) || normalized.message || "Dispatch Worker 已生成方案。",
        impact: normalized.impact,
        dispatchPlan: normalized.dispatchPlan,
      });
    }
  }
  if (normalized.type === "dispatch_plan" && normalized.impact) renderAgentTeamsImpact(normalized.impact);
  if (["execution_receipt", "completed"].includes(normalized.type) && state.flowPreview) {
    clearCampusPlanPreview(true);
  }
  renderAgentTeamsTaskPanel();
}

function agentTeamsPlanReason(event = {}) {
  const impact = event.impact || {};
  const parts = [];
  const saving = Number(impact.purchase_cost_savings_yuan);
  const savingPct = Number(impact.purchase_cost_savings_percent);
  const wasteDrop = Number(impact.energy_waste_reduction_kwh);
  const laborDrop = Number(impact.manual_dispatch_cost_reduction_yuan);
  if (Number.isFinite(saving) && saving > 0) {
    parts.push(`购电成本预计下降 ¥${saving.toFixed(2)}${Number.isFinite(savingPct) && savingPct > 0 ? `（${savingPct.toFixed(1)}%）` : ""}`);
  }
  if (Number.isFinite(wasteDrop) && wasteDrop > 0) parts.push(`能源浪费下降 ${wasteDrop.toFixed(1)} kWh`);
  if (Number.isFinite(laborDrop) && laborDrop > 0) parts.push(`人工调度成本下降 ¥${laborDrop.toFixed(2)}`);
  return parts.length ? `Dispatch Worker 基于真实 world_state 生成：${parts.join("，")}。` : "";
}

function renderAgentTeamsImpact(impact = {}) {
  const baseline = Number(state.parallel?.baseline_cost_yuan || state.campusSimulation?.todayCost || 0);
  const savings = Number(impact.purchase_cost_savings_yuan || 0);
  if (!Number.isFinite(baseline) || baseline <= 0 || !Number.isFinite(savings) || savings <= 0) return;
  const optimized = Math.max(0, baseline - savings);
  const pct = Number(impact.purchase_cost_savings_percent || (savings / baseline * 100));
  $("#cost-baseline").textContent = `¥${baseline.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#cost-optimized").textContent = `¥${optimized.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#cost-savings").textContent = `¥${savings.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#savings-percent").textContent = `节省 ${pct.toFixed(2)}%`;
  $("#parallel-status").textContent = "AgentTeams dispatch_plan 已驱动";
}

async function restoreAgentTeamsTaskMirror() {
  renderAgentTeamsTaskPanel();
  const taskId = state.agentTeamsTask.taskId;
  if (!taskId) return;
  try {
    const artifacts = await request(`/api/runtime/tasks/${encodeURIComponent(taskId)}/artifacts`);
    artifacts
      .filter((artifact) => artifact.artifact_type === "agentteams_task_event")
      .forEach((artifact) => applyAgentTeamsEvent(artifact.payload));
  } catch {
    renderAgentTeamsTaskPanel();
  }
}

function applyLanguage(language) {
  state.language = language;
  const dictionary = translations[language];
  $$("[data-i18n]").forEach((element) => {
    const text = dictionary[element.dataset.i18n];
    if (text) element.textContent = text;
  });
  $$("[data-i18n-placeholder]").forEach((element) => {
    const text = dictionary[element.dataset.i18nPlaceholder];
    if (text) element.placeholder = text;
  });
  const button = $("#translate-button");
  button.classList.toggle("active", language === "zh");
  button.textContent = language === "zh" ? "A" : "文";
  button.title = language === "zh" ? "Switch to English" : "翻译为中文";
  button.setAttribute("aria-label", language === "zh" ? "Switch to English" : "Translate to Chinese");
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  window.localStorage.setItem("energymesh.language", language);
  $$("[data-agent-name]").forEach((element) => {
    element.textContent = agentName(element.dataset.agentName);
  });
  $$("[data-agent-role]").forEach((element) => {
    element.textContent = agentRole(element.dataset.agentRole);
  });
  renderSelectedAgent();
  renderTask();
  renderCandidates();
  renderTrace();
  renderOpsReport();
  renderDailyLedger();
  if (!$(".home-view").hidden) drawHomeCharts();
  if (historyThreads[state.activeHistory]) renderThreadMessages(state.activeHistory);
  else renderAgentThread(state.selectedAgent);
  
}

function toggleLanguage() {
  const next = document.documentElement.lang === "zh-CN" ? "en" : "zh";
  applyLanguage(next);
}

function toggleAgentDirectory() {
  const drawer = $("#agent-directory-drawer");
  const willOpen = drawer.hidden;
  drawer.hidden = !willOpen;
  setActiveRail("nav-agents");
}

function setAgentDirectory(open) {
  $("#agent-directory-drawer").hidden = !open;
}

function setOpsDrawer(open) {
  $("#ops-drawer").hidden = !open;
  if (open) {
    setAgentDirectory(false);
    setActiveRail("nav-ops");
    loadOpsEvidence();
  }
}

function setChatPanel(open) {
  $("#ai-chat-panel").hidden = !open;
}

function setActiveRail(id) {
  $$(".rail-item").forEach((button) => {
    button.classList.toggle("active", button.id === id);
  });
  if (document.documentElement.lang === "zh-CN") $("#translate-button").classList.add("active");
}

function setStationView(view) {
  $$("[data-station-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.stationTab === view);
  });
  $$("[data-station-view]").forEach((panel) => {
    panel.hidden = panel.dataset.stationView !== view;
  });
  if (view === "devices") renderDeviceDetail("pcs");
}

function renderDeviceDetail(deviceId = "pcs") {
  state.selectedDeviceId = deviceId;
  const detail = deviceDetails[deviceId] || deviceDetails.pcs;
  $$("[data-device-id]").forEach((button) => {
    button.classList.toggle("active", button.dataset.deviceId === deviceId);
  });
  const target = $("#device-detail");
  if (!target) return;
  const mode = state.selectedDeviceMode;
  const filteredMetrics = mode === "power" ? detail.metrics.filter(([label]) => /功率|输出|可用/.test(label))
    : mode === "energy" ? detail.metrics.filter(([label]) => /电量|发电量|充电量|放电量/.test(label))
    : mode === "temperature" ? detail.metrics.filter(([label]) => /温度/.test(label))
    : mode === "soc" ? detail.metrics.filter(([label]) => /SOC|可用率|燃油/.test(label))
    : detail.metrics;
  const metrics = filteredMetrics.length ? filteredMetrics : detail.metrics;
  target.innerHTML = `
    <header>
      <div><span>设备详情</span><strong>${escapeHTML(detail.name)}</strong></div>
      <em>${escapeHTML(detail.status)}</em>
    </header>
    <div class="device-metrics">
      ${metrics.map(([label, value]) => `
        <div><span>${escapeHTML(label)}</span><strong>${escapeHTML(value)}</strong></div>
      `).join("")}
    </div>
    <p>${escapeHTML(detail.runtime)}</p>
    <div class="device-log-grid">
      <section><span>${mode === "history" ? "历史数据" : "告警记录"}</span>${(mode === "history" ? [`上一小时平均功率：${metrics[0]?.[1] || "--"}`, "采样周期：15 分钟", "数据源：MCP / station.telemetry"] : detail.alerts).map((item) => `<small>${escapeHTML(item)}</small>`).join("")}</section>
      <section><span>操作记录</span>${detail.operations.map((item) => `<small>${escapeHTML(item)}</small>`).join("")}</section>
    </div>
  `;
}

function setDeviceMode(mode) {
  state.selectedDeviceMode = mode;
  $$("[data-signal-mode], [data-device-view-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.signalMode === mode || button.dataset.deviceViewMode === mode);
  });
  renderDeviceDetail(state.selectedDeviceId);
}

function scrollWithin(element, selector) {
  const target = $(selector);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  element?.focus?.();
}

function ensureAgentThread(agentId = state.selectedAgent) {
  if (!state.agentThreads[agentId]) {
    const intro = agentIntroMessages[agentId] || agentIntroMessages.team_leader;
    state.agentThreads[agentId] = [{
      role: "agent",
      agentId,
      text: state.language === "zh" ? intro.zh : intro.en,
      intro: true,
    }];
  }
  return state.agentThreads[agentId];
}

function appendChatMessage(role, text, agentId = state.selectedAgent, meta = {}) {
  const message = document.createElement("article");
  const profile = agentProfile(agentId);
  message.className = `chat-message ${role} tone-${profile.tone || "leader"}${meta.action ? " actionable" : ""}`;
  const label = role === "user" ? t("you") : agentName(agentId);
  const avatar = document.createElement("div");
  avatar.className = "chat-avatar";
  if (role === "agent" && profile.avatar) {
    const image = document.createElement("img");
    image.src = profile.avatar;
    image.alt = "";
    avatar.append(image);
  } else {
    avatar.textContent = role === "user" ? "你" : profile.initials || "AI";
  }
  const content = document.createElement("div");
  content.className = "chat-content";
  const heading = document.createElement("header");
  heading.className = "chat-message-head";
  if (role === "agent") {
    const labelNode = document.createElement("strong");
    labelNode.className = "chat-speaker";
    labelNode.textContent = label;
    const roleNode = document.createElement("small");
    roleNode.className = "chat-role";
    roleNode.textContent = agentRole(agentId);
    heading.append(labelNode, roleNode);
  }
  const body = document.createElement("div");
  body.className = "chat-message-body";
  if (role === "agent") {
    renderMarkdown(body, text);
  } else {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    body.append(paragraph);
  }
  if (role === "agent") content.append(heading);
  content.append(body);
  message.append(avatar, content);
  if (meta.action === "confirm_execution") {
    const actions = document.createElement("div");
    actions.className = "chat-actions";
    const autoExec = window.localStorage.getItem("energymesh.autoExecute") === "true";
    actions.innerHTML = `
      <button class="chat-action primary" type="button" data-confirm-scenario="${escapeHTML(meta.scenarioKey || "")}">
        ${state.language === "zh" ? "确认执行方案" : "Confirm execution"}
      </button>
      <button class="chat-action" type="button" data-defer-scenario="${escapeHTML(meta.scenarioKey || "")}">
        ${state.language === "zh" ? "暂不执行" : "Defer"}
      </button>
      <label class="auto-exec-label">
        <input type="checkbox" id="auto-exec-check" ${autoExec ? "checked" : ""} />
        <span>${state.language === "zh" ? "下次不再询问，自动执行" : "Auto-execute next time"}</span>
      </label>
    `;
    content.append(actions);
  }
  $("#chat-messages").append(message);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
}

function addChatMessage(role, text, agentId = state.selectedAgent, options = {}) {
  appendChatMessage(role, text, agentId, options.meta || {});
  if (options.persist === false) return;
  ensureAgentThread(agentId).push({ role, text, agentId, meta: options.meta || null });
  try { localStorage.setItem("energymesh.agentThreads", JSON.stringify(state.agentThreads)); } catch(e) {}
}

function renderAgentThread(agentId = state.selectedAgent) {
  const thread = ensureAgentThread(agentId);
  $("#chat-messages").innerHTML = "";
  thread.forEach((message) => {
    if (message.intro) {
      const intro = agentIntroMessages[message.agentId] || agentIntroMessages.team_leader;
      appendChatMessage(message.role, state.language === "zh" ? intro.zh : intro.en, message.agentId);
      return;
    }
    appendChatMessage(message.role, message.text, message.agentId, message.meta || {});
  });
}

function appendRuntimeStatusMessage(agentId, text) {
  addChatMessage("agent", text, agentId, { persist: false });
}

function updateModelStatusFromPublic(config) {
  if (!config?.agent_id) return;
  state.gateways[config.agent_id] = {
    baseUrl: config.base_url,
    apiKey: config.api_key_masked,
    model: config.model,
    connectionStatus: config.connection_status,
    lastError: config.last_error,
  };
  updateChatGatewayGate();
}

async function chatWithConfiguredModel(message) {
  const { ok, body } = await requestAllowingError("/api/runtime/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: state.runtimeSessionId,
      task_id: state.task?.task_id || null,
    }),
  });
  if (!ok) {
    const detail = body.detail || "runtime request failed";
    throw new Error(detail);
  }
  state.runtimeSessionId = body.session_id;
  window.localStorage.setItem("energymesh.runtimeSessionId", body.session_id);
  return body;
}

async function chatWithRuntimeStream(message, handlers = {}) {
  const response = await fetch("/api/runtime/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: state.runtimeSessionId,
      task_id: state.task?.task_id || null,
    }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Runtime stream failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      const event = JSON.parse(dataLine.slice(6));
      applyAgentTeamsEvent(event);
      if (event.type === "runtime_started") {
        state.runtimeSessionId = event.session_id;
        window.localStorage.setItem("energymesh.runtimeSessionId", event.session_id);
        handlers.onStart?.(event);
      } else if (event.type === "agentteams_runtime_check") {
        handlers.onRuntimeCheck?.(event);
      } else if (event.type === "world_state_loaded") {
        handlers.onWorldState?.(event);
      } else if (event.type === "route_decided") {
        handlers.onRoute?.(event);
      } else if (event.type === "stage_start") {
        handlers.onStage?.(event);
      } else if (event.type === "worker_joined") {
        handlers.onWorkerJoined?.(event);
      } else if (event.type === "team_room_message") {
        handlers.onTeamRoomMessage?.(event);
      } else if (event.type === "agent_step") {
        handlers.onStep?.(event);
      } else if (event.type === "runtime_completed") {
        completed = event;
        handlers.onComplete?.(event);
      } else if (event.type === "runtime_error") {
        throw new Error(event.detail || "runtime stream failed");
      }
    }
  }
  return completed;
}

function agentHistoryForRequest(agentId) {
  return ensureAgentThread(agentId)
    .filter((item) => !item.intro && item.text)
    .slice(-12)
    .map((item) => ({
      role: item.role === "user" ? "user" : "assistant",
      content: item.text,
    }));
}

async function chatWithSelectedAgent(agentId, message, history = []) {
  const { ok, body } = await requestAllowingError(`/api/agents/${agentId}/chat`, {
    method: "POST",
    body: JSON.stringify({ message, history }),
  });
  if (!ok) {
    throw new Error(body.detail || "agent chat request failed");
  }
  return body;
}

function agentTeamsRuntimeProblemMessage(error) {
  const detail = error?.message || "Live AgentTeams runtime is not ready.";
  return state.language === "zh"
    ? `真实 AgentTeams 还没有接管这次对话。\n\n${detail}\n\n必须先完成 Docker、官方 AgentTeams、agt apply 和 Team Room bridge 配置；在这些证据都成立前，界面不会再把本地流水线伪装成多 Agent。`
    : `Live AgentTeams has not taken over this turn.\n\n${detail}\n\nDocker, official AgentTeams, agt apply, and Team Room bridge configuration must be ready before the UI can claim multi-agent work.`;
}

function campusPromptContext() {
  const sim = state.campusSimulation || {};
  const hasSnapshot = Boolean(state.energySnapshot);
  const activeFlow = state.flowPreview?.currentFlow || {};
  const previewFlow = state.flowPreview?.previewFlow || null;
  const monitor = state.monitor || {};
  const recentEvents = Array.isArray(monitor.events) ? monitor.events.slice(-5) : [];
  const abnormalEvents = recentEvents.filter((event) => ["V1_INVALIDATED", "AGENTTEAMS_WOKEN", "V2_REPLANNED_AND_AUDITED"].includes(event.kind));
  const curtailKw = Number(activeFlow.curtail || 0);
  const gridKw = Number(activeFlow.grid_load || 0);
  const statusConclusion = hasSnapshot
    ? (abnormalEvents.length ? "状态变化，需要说明异常依据" : "运行正常，当前方案有效，AgentTeams 休眠")
    : "未接入数据，不能判断园区是否正常";
  const flowText = (flow = {}) => (
    `发电到用电 ${Number(flow.solar_load || 0).toFixed(1)} kW；`
    + `发电到储能 ${Number(flow.solar_storage || 0).toFixed(1)} kW；`
    + `储能到用电 ${Number(flow.storage_load || 0).toFixed(1)} kW；`
    + `电网到用电 ${Number(flow.grid_load || 0).toFixed(1)} kW；`
    + `发电上网 ${Number(flow.solar_grid || 0).toFixed(1)} kW；`
    + `限发 ${Number(flow.curtail || 0).toFixed(1)} kW。`
  );
  const lines = [
    "[当前 3D 能源流动沙盘状态]",
    `CSV 数据: ${hasSnapshot ? "已接入" : "未接入"}`,
    `沙盘时间: ${hasSnapshot ? sim.time || "--" : "等待 CSV"}`,
    `发电: ${hasSnapshot ? sim.generation || "--" : "--"}`,
    `用电: ${hasSnapshot ? sim.load || "--" : "--"}`,
    `储能: ${hasSnapshot ? sim.storage || "--" : "--"}`,
    `电网购电: ${hasSnapshot ? sim.gridImport || "--" : "--"}`,
    `SOC: ${hasSnapshot && Number.isFinite(sim.socPercent) ? `${Math.round(sim.socPercent)}%` : "--"}`,
    `状态结论: ${statusConclusion}`,
    `当前方案: ${monitor.plan_version || "V1"} ${abnormalEvents.length ? "需要复核" : "有效"}`,
    `AgentTeams: ${monitor.agentteams_awake ? "已唤醒" : "休眠"}`,
    `最近时段汇报: ${recentEvents.map((event) => `${event.kind}: ${event.detail}`).join(" | ") || "暂无事件"}`,
    `累计未有效利用: ${hasSnapshot && Number.isFinite(sim.wastedKwh) ? `${sim.wastedKwh.toFixed(1)} kWh` : "--"}`,
    `累计额外购电成本: ${hasSnapshot && Number.isFinite(sim.extraCost) ? `¥${sim.extraCost.toFixed(1)}` : "--"}`,
    `当前流向: ${flowText(activeFlow)}`,
  ];
  if (previewFlow) {
    lines.push(`正在预览的新流向: ${flowText(previewFlow)}`);
  } else {
    lines.push("正在预览的新流向: 无。");
  }
  lines.push(`判断提示: 当前购电 ${gridKw.toFixed(1)} kW，限发 ${curtailKw.toFixed(1)} kW。小功率购电或储能充电本身不代表故障；没有异常事件时先说运行正常。`);
  lines.push("回答顺序: 先说园区电力当前会怎样运行，再说是否需要 Worker 或调度；不要把回答写成“你会在沙盘看到什么”的界面说明。");
  lines.push("Worker 触发原则: 普通聊天不触发；询问当前状态只读状态；明确要求优化/模拟/预览/调整/采用/执行时，才建议进入调度或生成预览。");
  lines.push("禁止: 没有数据质量、通信、预测偏差或告警证据时，不要猜测信号接错或设备故障。");
  return lines.join("\n");
}

function messageWithCampusContext(message) {
  return `${message}\n\n${campusPromptContext()}`;
}

function isGatewayMissingError(error) {
  return /model config|gateway|网关|api key|base url|not saved|not configured|未配置|未保存/i.test(error?.message || "");
}

function gatewayFailureMessage(agentId, error) {
  if (isGatewayMissingError(error)) {
    return state.language === "zh"
      ? `还没有为 ${agentName(agentId)} 配置真实模型网关，所以我不能假装已经和 Agent 对话。请在弹出的「模型网关」里填写 Base URL、API Key 和模型名，保存并测试成功后再发送。`
      : `${agentName(agentId)} does not have a real model gateway configured yet. Configure Base URL, API key, and model, then save and test before chatting.`;
  }
  return state.language === "zh"
    ? `模型网关调用失败：${error?.message || "未知错误"}。这条消息没有生成本地假回答，请检查网关地址、模型名、API Key 或服务可用性后重试。`
    : `Model gateway call failed: ${error?.message || "unknown error"}. No local fallback answer was generated. Check the gateway URL, model, API key, or service availability and retry.`;
}

async function revealRuntimeSteps(runtime, runtimeStatus) {
  for (const step of runtime.steps) {
    runtimeStatus.querySelector("span").textContent = state.language === "zh"
      ? `${agentName(step.agent_id)} 正在输出`
      : `${agentName(step.agent_id)} is responding`;
    await sleep(260);
    addChatMessage("agent", step.response, step.agent_id, {
      meta: { model: step.model, runtimeSessionId: runtime.session_id },
    });
    await sleep(420);
  }
}

async function confirmScenarioExecution() {
  const scenario = state.pendingExecutionScenario || state.activeScenario;
  if (!scenario || scenario.executable === false) return;
  const autoExec = $("#auto-exec-check")?.checked;
  if (autoExec !== undefined) window.localStorage.setItem("energymesh.autoExecute", String(autoExec));
  $$("[data-confirm-scenario], [data-defer-scenario]").forEach((b) => b.disabled = true);
  if (state.flowPreview) ledgerRecord("adopted", state.flowPreview.currentFlow, state.flowPreview.previewFlow);
  clearCampusPlanPreview(true);

  const taskId = state.task?.task_id;
  if (!taskId) {
    toast("没有可执行的任务；请先上传历史数据或运行调度场景");
    return;
  }
  try {
    await request(`/api/tasks/${taskId}/approval-only`, {
      method: "POST",
      body: JSON.stringify({ approved: true, approver: "operator", reason: "用户确认执行优化方案" }),
    });
    const executed = await request(`/api/tasks/${taskId}/execute-approved`, { method: "POST" });
    state.task = executed;
    state.approval = executed.approval;
    renderTask(); renderTrace(); renderCandidates(); applySnapshotToCampus();
    const baseline = state.parallel?.baseline_cost_yuan ?? "--";
    const opt = state.parallel?.optimized_cost_yuan ?? "--";
    const save = state.parallel?.savings_yuan ?? "--";
    const msg = state.language === "zh"
      ? `方案已执行。Agent Teams 优化电费 ¥${opt}，比原始策略 ¥${baseline} 节省 ¥${save}。`
      : `Executed. Optimized ¥${opt} vs baseline ¥${baseline}, saved ¥${save}.`;
    addChatMessage("agent", msg, "team_leader");
    addChatMessage("agent", `执行Worker 已完成模拟指令映射与偏差验证。证据包已封存。`, "execution_agent");
  } catch (err) {
    toast(err.message || "执行失败");
    addChatMessage("agent", `执行失败：${err.message || "未知错误"}`, "team_leader");
  }
  state.pendingExecutionScenario = null;
}

async function deferScenarioExecution() {
  const scenario = state.pendingExecutionScenario || state.activeScenario;
  if (!scenario || scenario.executable === false) return;
  const autoExec = $("#auto-exec-check")?.checked;
  if (autoExec !== undefined) window.localStorage.setItem("energymesh.autoExecute", String(autoExec));
  $$("[data-confirm-scenario], [data-defer-scenario]").forEach((b) => b.disabled = true);
  if (state.flowPreview) ledgerRecord("rejected", state.flowPreview.currentFlow, state.flowPreview.previewFlow);

  const taskId = state.task?.task_id;
  if (taskId) {
    try {
      const rej = await request(`/api/tasks/${taskId}/approval-only`, {
        method: "POST",
        body: JSON.stringify({ approved: false, approver: "operator", reason: "用户暂不执行" }),
      });
      state.task = rej; renderTask();
    } catch (e) { /* ignore */ }
  }
  clearCampusPlanPreview(false);
  addChatMessage("agent", "已暂不执行。任务保留在等待人工确认状态。", "team_leader");
  state.pendingExecutionScenario = null;
}

function renderThreadMessages(threadKey = state.activeHistory) {
  const thread = historyThreads[threadKey];
  if (!thread) return;
  const transcript = thread[state.language] || thread.en;
  $("#chat-messages").innerHTML = "";
  transcript.messages.forEach((message) => {
    appendChatMessage(message.role, message.text, message.agentId || thread.agentId);
  });
}

function findNaturalScenario(message) {
  const match = Object.entries(naturalScenarios).find(([, scenario]) => scenario.match(message));
  if (!match) return null;
  const [key, scenario] = match;
  return { ...scenario, key };
}

function buildScenarioEvents(scenario) {
  return scenario.steps.map(([label, detail], index) => ({
    event_id: `STEP-${String(index + 1).padStart(2, "0")}`,
    timestamp: new Date(Date.now() + index * 1000).toISOString(),
    actor: index === 0 || label === "Leader Response" ? "Team Leader"
      : label.includes("Planning") ? "Dispatch Agent"
      : label.includes("Audit") ? "Audit Agent"
      : label.includes("Knowledge") ? "Perception Agent"
      : "Team Leader",
    to_state: index === scenario.steps.length - 1 ? "COMPLETED" : index >= 5 ? "AUDITING" : "SENSING",
    reason: `${label}: ${detail}`,
  }));
}

function applyNaturalScenario(scenario) {
  state.activeScenario = scenario;
  state.activeHistory = "new";
  state.selectedAgent = scenario.selectedAgent || "team_leader";
  state.task = {
    task_id: scenario.taskId,
    task_version: 1,
    state: scenario.executable === false ? "COMPLETED" : "AWAITING_APPROVAL",
    trace_id: `TRACE-${scenario.taskId}`,
    evidence_sha256: scenario.executable === false ? `demo-${scenario.taskId.toLowerCase()}-sha256` : null,
  };
  state.context = {
    context_hash: `ctx-${scenario.taskId.toLowerCase()}-mcp-rag-observable`,
    task_version: 1,
  };
  state.candidates = scenario.cards.map((card, index) => ({
    candidate_id: `Capability-${index + 1}`,
    name: card.title,
    cost_yuan: 0,
    max_power_kw: index === 0 ? 0 : 800 + index * 180,
    soc_min_percent: 38,
    soc_max_percent: 82,
    transformer_load_percent: scenario.taskId.includes("AIDC") ? 96 : 86,
    summary: card.text,
  }));
  state.audit = scenario.cards.map((card, index) => ({
    candidate_id: `Capability-${index + 1}`,
    verdict: "audit_approved",
    reason: card.text,
  }));
  state.events = buildScenarioEvents(scenario);
  state.evidence = {
    task_id: scenario.taskId,
    mcp_gateway: scenario.endpoint,
    api_response: scenario.apiResponse,
    rag_sources: scenario.rag,
    trace_steps: scenario.steps,
  };
  state.approval = scenario.executable === false ? { status: "not_required_for_demo" } : null;
  state.pendingExecutionScenario = scenario.executable === false ? null : scenario;
  setWorkspaceMode("nav-chat");
  renderSelectedAgent();
  renderTask();
  renderCandidates();
  renderTrace();
  renderOpsReport();
  applySnapshotToCampus();
}

function scenarioConversation(scenario) {
  const finalPrompt = scenario.executable === false
    ? "这次是基础查询任务，不需要执行设备策略。我已经把结果写入 Trace 和证据区。"
    : `我建议执行方案 B。目标是：${scenario.executionPurpose}`;
  return [
    {
      agentId: "team_leader",
      text: `Task Received: ${scenario.title}\nTask Type: ${scenario.taskId === "DEMO-TR02-TEMP" ? "Fault diagnosis + emergency dispatch" : scenario.taskId === "DEMO-AIDC-6MW" ? "Capacity planning + infrastructure dispatch" : "Operational dispatch assessment"}\nAssigned Agents: Perception Agent, Knowledge Agent, Planning Agent, Safety Audit Agent, Execution Agent\nCurrent State: ANALYZING`,
    },
    {
      agentId: "team_leader",
      text: `Analysis Complete.\n\n${scenario.reply}\n\nStructured artifacts have been written to State / Constraint / Plan / Action / Evidence. Worker Agents did not produce chat messages; they produced auditable objects.`,
    },
    {
      agentId: "team_leader",
      text: finalPrompt,
      meta: scenario.executable === false ? null : { action: "confirm_execution", scenarioKey: scenario.key },
    },
  ];
}

async function runScenarioConversation(scenario) {
  applyNaturalScenario(scenario);
  addChatMessage("agent", scenario.taskId === "DEMO-MCP-STORAGE"
    ? "Task Received: Storage state query\nCurrent State: COLLECTING_STATE"
    : `Task Received: ${scenario.title}\nCurrent State: COLLECTING_STATE`, "team_leader");
  const messages = scenarioConversation(scenario);
  for (const message of messages) {
    await sleep(420);
    addChatMessage("agent", message.text, message.agentId, { meta: message.meta });
  }
}

function scenarioFollowupConversation(message, scenario) {
  const lower = message.toLowerCase();
  const asksPerception = /@?感知|perception|外部数据|实时|状态|容量|上下文/.test(lower);
  const asksEstimate = /估算|继续|可以|方案|重新|保守|经济|测算|support|支持/.test(lower);
  if (!asksPerception && !asksEstimate) {
    return [
      {
        agentId: "team_leader",
        text: `我会沿用当前任务上下文继续分析：${scenario.title}。当前可用外部数据为演示预设数据：${scenario.apiResponse}。`,
      },
      {
        agentId: "team_leader",
        text: localLeaderReply(message),
      },
    ];
  }
  return [
    {
      agentId: "team_leader",
      text: `Runtime Continue.\n\nState updated by Perception Agent.\nKnowledge constraints applied by Knowledge Agent.\nPlan candidates regenerated by Planning Agent.\nSafety verdict produced by Audit Agent.\nAction object prepared by Execution Agent.\n\n右侧已更新 State / Constraint / Plan / Action / Evidence。`,
    },
    {
      agentId: "team_leader",
      text: `最终建议：采用方案 B。${scenario.executionPurpose}`,
      meta: scenario.executable === false ? null : { action: "confirm_execution", scenarioKey: scenario.key },
    },
  ];
}

function scenarioStrategyCode(scenario) {
  if (scenario.taskId === "DEMO-AIDC-6MW") {
    return `policy "AIDC_6MW_PHASED_ACCESS" {
  require capacity.available >= 3.2MW
  require transformer.add_capacity >= 4MW
  require storage.reserve >= 2MWh

  phase_1 {
    connect_load = 2MW
    reserve_margin >= 20%
  }

  phase_2 {
    connect_load = 4MW
    condition = audit.passed && transformer.temperature < 85C
  }

  fallback {
    shed_flexible_load = 600kW
    notify = HumanOperator
  }
}`;
  }
  if (scenario.taskId === "DEMO-TR02-TEMP") {
    return `policy "TR02_THERMAL_PROTECTION" {
  if transformer.TR02.temperature >= 92C {
    fan.backup = ON
    shed.non_critical_load = 600kW
    create_work_order = true
  }

  if transformer.TR02.temperature >= 95C {
    require HumanOperator.approval
    enter_protection_derating = true
  }
}`;
  }
  return `policy "PRODUCTION_1_800KW_SHIFT" {
  require production.zone == "一区"
  require added_load == 800kW
  charge_storage.window = "11:00-15:30"
  discharge_storage.window = "18:00-22:00"
  discharge_storage.power = 520kW
  shift_flexible_load = 280kW

  constraints {
    transformer.peak_load <= 86%
    storage.soc_min >= 38%
    production_min_load = protected
  }
}`;
}

function scenarioStateObject(scenario) {
  if (scenario.taskId === "DEMO-TR02-TEMP") {
    return {
      asset_id: "TR-02",
      timestamp: "2026-08-06T13:40:00+08:00",
      temperature_c: 92,
      load_ratio: 0.91,
      oil_temp_rise_c_per_10min: 1.8,
      cooling_status: { fan_group_A: "online", fan_group_B: "offline" },
      risk_level: "high",
    };
  }
  if (scenario.taskId === "DEMO-AIDC-6MW") {
    return {
      request_load_mw: 6,
      current_capacity_mw: 10,
      available_capacity_mw: 3.2,
      transformer_spare_mw: 3.6,
      storage_firm_support_mw: 0.8,
      capacity_gap_mw: 2.8,
      risk_level: "high",
    };
  }
  return {
    zone: "production-1",
    added_load_kw: 800,
    current_load_mw: 6.8,
    available_margin_mw: 2.4,
    storage_soc_percent: 61,
    peak_tariff_window: "18:00-22:00",
    risk_level: "medium",
  };
}

function scenarioKnowledgeObject(scenario) {
  if (scenario.taskId === "DEMO-TR02-TEMP") {
    return {
      rule: "Transformer cooling failure",
      source: "Maintenance Manual v3.2",
      constraint: "If oil temperature rising > 1.5C / 10min, avoid overload operation.",
      applied: true,
    };
  }
  if (scenario.taskId === "DEMO-AIDC-6MW") {
    return {
      rule: "AI data center power onboarding",
      source: "Data Center Power Standard v2.1",
      constraint: "Critical compute load requires reserved margin and staged commissioning.",
      applied: true,
    };
  }
  return {
    rule: "Production continuity during peak tariff",
    source: "Production Zone 1 Dispatch Rulebook",
    constraint: "Protect minimum production load and keep storage SOC above emergency reserve.",
    applied: true,
  };
}

function scenarioPlanObject(scenario) {
  if (scenario.taskId === "DEMO-AIDC-6MW") {
    return {
      objective: "Support 6MW AI compute load without violating capacity constraints.",
      selected_plan: "B",
      alternatives: {
        A: "direct connection, rejected",
        B: "4MW transformer expansion + 2MWh storage + phased access",
        C: "larger redundancy, approved but high cost",
      },
    };
  }
  if (scenario.taskId === "DEMO-TR02-TEMP") {
    return {
      objective: "Stop transformer thermal rise while preserving critical load.",
      selected_plan: "B",
      actions: ["turn_on_backup_fan", "shed_non_critical_load_600kw", "create_work_order"],
    };
  }
  return {
    objective: "Minimize peak energy cost while preserving production priority.",
    selected_plan: "B",
    optimization: "0.7 * electricity_price + 0.3 * transformer_temperature_risk",
  };
}

function scenarioActionObject(scenario) {
  if (scenario.executable === false) {
    return { action_required: false, reason: "read-only status query" };
  }
  return {
    approval_required: true,
    execution_mode: "simulated EMS / PCS / load-control command mapping",
    idempotency_key: `IDEMP-${scenario.taskId}-PLAN-B`,
    expected_effect: scenario.executionPurpose,
  };
}

function scenarioEvidenceObject(scenario) {
  return {
    trace_id: `TRACE-${scenario.taskId}`,
    context_hash: `ctx-${scenario.taskId.toLowerCase()}-mcp-rag-observable`,
    mcp_call: scenario.endpoint,
    rag_source_count: scenario.rag.length,
    audit_verdict: scenario.executable === false ? "not_required" : "plan_b_passed",
  };
}

function scenarioAuditReport(scenario) {
  if (scenario.taskId === "DEMO-AIDC-6MW") {
    return "审核报告：A 直接接入未通过，原因是当前可用余量 3.2MW 小于 6MW。B 分阶段扩容通过：新增 4MW 变压器容量与 2MWh 储能后，容量、冗余和峰段约束可满足。C 通过但投资冗余偏高。";
  }
  if (scenario.taskId === "DEMO-TR02-TEMP") {
    return "审核报告：温度 92°C、负载率 91%、B 组风机离线。建议动作不直接越权执行，只允许备用风机切换、非关键负荷下调和检修工单；若接近 95°C 必须进入人工确认。";
  }
  if (scenario.taskId === "DEMO-MCP-STORAGE") {
    return "审核报告：本次为状态查询，没有设备动作，不需要执行审批。储能 SOC 55%、PCS 健康，可支撑短时削峰。";
  }
  return "审核报告：方案 B 通过。容量可覆盖新增 800kW，但峰段成本风险需要削峰；变压器峰值约 86%，SOC 最低约 38%，满足生产一区保供约束。";
}

function scenarioAgentArtifacts(scenario) {
  return [
    ["State", scenarioStateObject(scenario)],
    ["Retrieved Knowledge", scenarioKnowledgeObject(scenario)],
    ["Constraint", {
      soc_min_percent: scenario.taskId === "DEMO-AIDC-6MW" ? 45 : 30,
      transformer_load_max_percent: scenario.taskId === "DEMO-TR02-TEMP" ? 85 : 90,
      production_priority: scenario.taskId === "DEMO-PROD-800KW" ? "HIGH" : "NORMAL",
      human_approval_required: scenario.executable !== false,
    }],
    ["Plan", scenarioPlanObject(scenario)],
    ["Action", scenarioActionObject(scenario)],
    ["Evidence", scenarioEvidenceObject(scenario)],
  ];
}

async function continueScenarioConversation(message) {
  const scenario = state.activeScenario;
  if (!scenario) return false;
  const messages = scenarioFollowupConversation(message, scenario);
  state.pendingExecutionScenario = scenario.executable === false ? null : scenario;
  state.task = {
    ...(state.task || {}),
    state: scenario.executable === false ? "COMPLETED" : "AWAITING_APPROVAL",
  };
  renderTask();
  renderTrace();
  for (const item of messages) {
    await sleep(420);
    addChatMessage("agent", item.text, item.agentId, { meta: item.meta });
  }
  return true;
}

function localLeaderReply(message) {
  const lower = message.toLowerCase();
  const zh = state.language === "zh";
  if (state.activeScenario) {
    if (lower.includes("为什么") || lower.includes("原因") || lower.includes("why")) {
      return `基于刚才这次「${state.activeScenario.title}」的上下文，我的判断依据不是单点数据，而是三类证据：第一，MCP 返回的实时状态是 ${state.activeScenario.apiResponse}；第二，RAG 召回了 ${state.activeScenario.rag.join("、")}；第三，审核 Worker 已经检查容量、设备和安全约束。所以我才给出刚才的建议。`;
    }
    if (lower.includes("风险") || lower.includes("risk")) {
      return `这次任务的主要风险边界有三个：容量余量是否足够、关键设备是否被推到过载区间、策略是否违反生产或运行规则。右侧 Trace 里的 Audit Agent 步骤就是专门用来约束这些风险的。`;
    }
    if (lower.includes("trace") || lower.includes("步骤") || lower.includes("mcp") || lower.includes("rag")) {
      return `这次 Trace 的关键链路是：${state.activeScenario.steps.map(([label]) => label).join(" -> ")}。MCP 请求是 ${state.activeScenario.endpoint}，RAG 来源是 ${state.activeScenario.rag.join("、")}。`;
    }
    return `我还在沿用刚才「${state.activeScenario.title}」的长上下文。你可以继续改约束、追问原因、要求看风险，或让我基于同一上下文重新给一个更保守/更激进的方案。`;
  }
  const taskState = state.task ? stateLabels[state.language][state.task.state] || state.task.state : t("noTask");
  const task = state.task ? `${state.task.task_id} / V${state.task.task_version} / ${taskState}` : t("noTask");
  const candidateSummary = state.candidates.length
    ? state.candidates.map((candidate) => {
      const verdict = state.audit.find((item) => item.candidate_id === candidate.candidate_id);
      const status = verdict?.verdict === "rejected" ? t("rejected") : verdict ? t("auditPassed") : t("pendingAudit");
      return `${candidate.candidate_id} ${candidate.name}: ${status}`;
    }).join("; ")
    : t("noCandidates");
  const profile = agentProfiles[state.selectedAgent] || agentProfiles.team_leader;
  if (lower.includes("mcp") || lower.includes("rag") || lower.includes("观测") || lower.includes("trace") || lower.includes("metrics") || lower.includes("evidence") || lower.includes("报告") || lower.includes("变化")) {
    return zh
      ? `变化报告：MCP 模拟调用读取 EMS 快照、PCS 状态、MES 生产约束和审批证据；RAG 检索相似历史任务、峰段电价策略模板和安全闸门规则；可观测性记录 trace、metrics、context hash 与 evidence SHA。结论是原调度任务不再成立，需要先校验上下文，再生成受限候选方案，独立审核后请求人工审批。当前任务：${task}。`
      : `Change report: simulated MCP calls read EMS snapshots, PCS state, MES constraints, and approval evidence; RAG retrieves similar historical tasks, peak-tariff strategy templates, and safety gate rules; observability records trace, metrics, context hash, and evidence SHA. The original dispatch task no longer holds, so context must be validated before bounded plans, independent audit, and human approval. Current task: ${task}.`;
  }
  if (state.selectedAgent === "perception_agent") {
    return zh
      ? `感知 Worker：我在规划前校验上下文。当前上下文哈希为 ${state.context?.context_hash?.slice(0, 20) || "待生成"}。我检查负荷、光伏、SOC、电价、设备状态、生产约束和传感器冲突。`
      : `Perception Worker view: I validate context before planning. Current context hash is ${state.context?.context_hash?.slice(0, 20) || "pending"}. I check load, PV, SOC, tariff, device state, production constraints, and sensor conflicts.`;
  }
  if (state.selectedAgent === "dispatch_agent") {
    return zh
      ? `调度 Worker：只有上下文可信后，我才生成受限候选方案。当前候选：${candidateSummary}。我不能审批，也不能执行设备命令。`
      : `Dispatch Worker view: I can generate bounded candidate plans after context is trusted. Current candidates: ${candidateSummary}. I cannot approve or execute equipment commands.`;
  }
  if (state.selectedAgent === "audit_agent") {
    return zh
      ? "审核 Worker：我独立复算 SOC、PCS 功率、变压器负载、购电功率、生产最小负荷和相对基线收益。任何不安全或无法验证的候选方案都会默认关闭。"
      : "Audit Worker view: I independently recompute SOC, PCS power, transformer loading, grid import, production minimums, and improvement over baseline. Unsafe or unverifiable candidates fail closed.";
  }
  if (state.selectedAgent === "execution_agent") {
    return zh
      ? "执行 Worker：我只把已审核、已审批的方案映射为幂等的模拟 EMS / PCS / 负荷控制命令。如果实际与计划偏差超过阈值，我会触发安全回退。"
      : "Execution Worker view: I only map audited and approved plans to idempotent simulated EMS / PCS / load-control commands. If actual-vs-plan deviation exceeds threshold, I trigger safe fallback.";
  }
  if (lower.includes("agent") || lower.includes("worker") || lower.includes("职责") || lower.includes("通讯")) {
    return zh
      ? "EnergyMesh Runtime 会把任务分配给自治 Agent：感知产出状态对象，规划产出候选方案，审核产出安全裁决，执行产出动作对象。高风险动作必须经过人工操作员审批。"
      : "EnergyMesh Runtime assigns work to autonomous Agents: Perception produces state objects, Planning produces candidate plans, Audit produces safety verdicts, and Execution produces action objects. Human Operator approval is required for high-risk actions.";
  }
  if (lower.includes("candidate") || lower.includes("方案") || lower.includes("audit") || lower.includes("审核")) {
    return zh
      ? `当前候选状态：${candidateSummary}。审核 Worker 默认关闭风险：变压器、SOC、购电、生产最小负荷和相对基线收益都必须通过，才允许进入执行。`
      : `Current candidate state: ${candidateSummary}. Audit Worker fails closed: transformer, SOC, grid import, production minimum, and improvement over baseline must all pass before execution.`;
  }
  if (lower.includes("rollback") || lower.includes("回滚") || lower.includes("安全")) {
    return zh
      ? "回滚边界：传感器冲突无法消解、审批被拒绝，或执行偏差超过阈值时，系统停止策略，退回安全的零充放/零削减行为，并把控制权交还人工操作员。"
      : "Rollback boundary: if sensor conflict cannot be resolved, approval is rejected, or execution deviation exceeds the threshold, the system stops the strategy, falls back to safe zero-charge/zero-curtailment behavior, and returns control to the Human Operator.";
  }
  if (lower.includes("task") || lower.includes("任务") || lower.includes("context") || lower.includes("上下文")) {
    return zh
      ? `当前任务：${task}。上下文哈希：${state.context?.context_hash?.slice(0, 20) || "待生成"}。在感知 Worker 让运行上下文可信之前，Leader 不应让调度 Worker 开始规划。`
      : `Current task: ${task}. Context hash: ${state.context?.context_hash?.slice(0, 20) || "pending"}. The Leader should not let Dispatch work until Perception has made the operating context trustworthy.`;
  }
  return zh
    ? `我正在以 ${agentName(state.selectedAgent)} 的视角跟踪调度闭环。当前任务是 ${task}。你可以继续问 Agent 职责、候选方案、审核原因、MCP/RAG/可观测性或回滚边界。`
    : `I am tracking the dispatch loop as ${profile.name}. Current task is ${task}. Ask about Agent responsibilities, candidates, audit reasons, MCP/RAG/observability, or rollback if you want a narrower answer.`;
}

async function sendChatMessage(event) {
  event.preventDefault();
  const input = $("#ai-chat-input");
  const sendButton = $("#ai-chat-form button");
  const runtimeStatus = $("#runtime-status");
  const message = input.value.trim();
  if (!message) return;
  const agentId = state.selectedAgent || "team_leader";
  if (!hasReadyAgentGateway(agentId)) {
    toast(state.language === "zh" ? "请先接入并测试模型网关，成功后才能对话" : "Connect and test the model gateway before chatting");
    openGateway(agentId);
    return;
  }
  input.value = "";
  state.activeHistory = "new";
  state.activeScenario = null;
  renderSelectedAgent();
  const history = agentHistoryForRequest(agentId);
  addChatMessage("user", message, agentId);
  input.disabled = true;
  sendButton.disabled = true;
  const routedMessage = messageWithCampusContext(message);
  try {
    runtimeStatus.hidden = false;
    runtimeStatus.querySelector("span").textContent = state.language === "zh" ? `${agentName(agentId)} 正在响应` : `${agentName(agentId)} is responding`;
    let reply = null;
    if (agentId === "team_leader") {
      appendRuntimeStatusMessage("team_leader", state.language === "zh" ? "正在连接真实 AgentTeams Team Room..." : "Connecting to the live AgentTeams Team Room...");
      await chatWithRuntimeStream(routedMessage, {
        onRuntimeCheck: (event) => {
          const ready = event.status?.ready;
          appendRuntimeStatusMessage(
            "team_leader",
            ready
              ? (state.language === "zh" ? "AgentTeams runtime 已就绪，消息已进入真实 Team Room。" : "AgentTeams runtime is ready; the message is entering the real Team Room.")
              : (state.language === "zh" ? "AgentTeams runtime 未就绪；不会使用本地替代 Worker 流程。" : "AgentTeams runtime is not ready; no local Worker substitute will run."),
          );
        },
        onWorldState: (event) => appendRuntimeStatusMessage("team_leader", event.message || "world_state loaded"),
        onStage: (event) => appendRuntimeStatusMessage(event.agent_id || "team_leader", event.message || event.stage || "AgentTeams stage started"),
        onWorkerJoined: (event) => appendRuntimeStatusMessage(event.agent_id || "team_leader", event.message || "Worker joined"),
        onStep: (event) => {
          const step = event.step || {};
          if (step.response) addChatMessage("agent", step.response, step.agent_id || "team_leader", { meta: { model: step.model || "AgentTeams" } });
        },
      });
    } else {
      reply = await chatWithSelectedAgent(agentId, routedMessage, history);
      addChatMessage("agent", reply.response, agentId, {
        meta: { model: reply.model },
      });
    }
    if (agentId === "team_leader" && isFlowTuningRequest(message) && state.energySnapshot) {
      const flowPreview = previewFlowFromLatestSnapshot();
      if (flowPreview) {
        const plan = planNarrativeFromFlow(`${message}\n${reply?.response || ""}`, flowPreview.currentFlow, flowPreview.previewFlow, "llm");
        showCampusPlanPreview(flowPreview.currentFlow, flowPreview.previewFlow, plan);
      }
    }
  } catch (error) {
    const missingGateway = isGatewayMissingError(error);
    addChatMessage("agent", agentId === "team_leader" && /AgentTeams|agt|Docker|Team Room|Matrix|runtime/i.test(error?.message || "")
      ? agentTeamsRuntimeProblemMessage(error)
      : gatewayFailureMessage(agentId, error), agentId);
    toast(missingGateway
      ? (state.language === "zh" ? "请先配置真实模型网关" : "Configure the real model gateway first")
      : (state.language === "zh" ? "真实 AgentTeams 未就绪" : "Live AgentTeams is not ready"));
    if (missingGateway) window.setTimeout(() => openGateway(agentId), 180);
  } finally {
    runtimeStatus.hidden = true;
    updateChatGatewayGate();
    if (!input.disabled) input.focus();
  }
}

function renderSelectedAgent() {
  $("#active-agent-role").textContent = agentName(state.selectedAgent);
  $("#active-agent-name").textContent = agentRole(state.selectedAgent);
  $$("#agent-directory-list article").forEach((row) => {
    row.classList.toggle("active", row.dataset.agentId === state.selectedAgent);
  });
  updateChatGatewayGate();
}

function selectAgent(agentId) {
  state.selectedAgent = agentId;
  state.activeHistory = "new";
  renderSelectedAgent();
  renderAgentThread(agentId);
  setAgentDirectory(false);
  setActiveRail("nav-chat");
  $("#ai-chat-input").focus();
}

function openGateway(agentId = state.selectedAgent) {
  state.selectedAgent = agentId;
  state.activeHistory = "new";
  renderSelectedAgent();
  renderAgentThread(agentId);
  const profile = agentProfiles[agentId] || agentProfiles.team_leader;
  const saved = state.gateways[agentId] || {};
  $("#gateway-title").textContent = `${agentName(agentId)} ${state.language === "zh" ? "模型网关" : "gateway"}`;
  $("#gateway-base-url").value = saved.baseUrl || "https://api.deepseek.com";
  $("#gateway-api-key").value = saved.apiKey || "";
  $("#gateway-model").value = saved.model || profile.defaultModel;
  $("#gateway-status").textContent = saved.model
    ? (state.language === "zh" ? `已载入网关。连接状态：${saved.connectionStatus || "未测试"}。` : `Gateway loaded. Status: ${saved.connectionStatus || "untested"}.`)
    : t("gatewayStored");
  $("#gateway-dialog").showModal();
}

async function saveGatewayConfigFromForm() {
  const profile = agentProfiles[state.selectedAgent] || agentProfiles.team_leader;
  const apiKey = $("#gateway-api-key").value.trim();
  const payload = {
    base_url: $("#gateway-base-url").value.trim(),
    api_key: apiKey && !apiKey.includes("•") ? apiKey : null,
    model: $("#gateway-model").value.trim() || profile.defaultModel,
  };
  const { ok, body } = await requestAllowingError(`/api/agents/${state.selectedAgent}/model`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!ok) {
    throw new Error(body.detail || "Gateway save failed.");
  }
  updateModelStatusFromPublic(body);
  $("#gateway-base-url").value = body.base_url || payload.base_url;
  $("#gateway-api-key").value = body.api_key_masked || "";
  $("#gateway-model").value = body.model || payload.model;
  return body;
}

async function testGatewayConnection() {
  $("#gateway-status").textContent = state.language === "zh"
    ? "正在保存并测试模型连接..."
    : "Saving and testing model connection...";
  try {
    await saveGatewayConfigFromForm();
  } catch (error) {
    $("#gateway-status").textContent = state.language === "zh"
      ? `保存失败：${error.message}`
      : `Save failed: ${error.message}`;
    return;
  }
  const { ok, body } = await requestAllowingError(`/api/agents/${state.selectedAgent}/model/test`, {
    method: "POST",
  });
  if (!ok || !body.success) {
    const error = body.error || body.detail || "Model test failed.";
    $("#gateway-status").textContent = state.language === "zh" ? `连接失败：${error}` : `Connection failed: ${error}`;
    state.gateways[state.selectedAgent] = {
      ...(state.gateways[state.selectedAgent] || {}),
      connectionStatus: "失败",
      lastError: error,
    };
    updateChatGatewayGate();
    return;
  }
  state.gateways[state.selectedAgent] = {
    ...(state.gateways[state.selectedAgent] || {}),
    model: body.model,
    connectionStatus: "正常",
    lastError: null,
  };
  updateChatGatewayGate();
  $("#gateway-status").textContent = state.language === "zh"
    ? `模型接入成功：${body.model}。现在可在聊天中直接使用该模型。`
    : `Model connected: ${body.model}. You can now chat with this model.`;
}

async function saveGateway(event) {
  event.preventDefault();
  const profile = agentProfiles[state.selectedAgent] || agentProfiles.team_leader;
  $("#gateway-status").textContent = state.language === "zh" ? "正在保存模型网关..." : "Saving model gateway...";
  let body;
  try {
    body = await saveGatewayConfigFromForm();
  } catch (error) {
    $("#gateway-status").textContent = error.message;
    return;
  }
  $("#gateway-status").textContent = state.language === "zh"
    ? `${agentName(state.selectedAgent)} 模型网关已保存，状态：${body.connection_status}。`
    : `${profile.name} gateway saved. Status: ${body.connection_status}.`;
  toast(state.language === "zh" ? `${agentName(state.selectedAgent)} 网关已保存` : `${profile.name} gateway saved`);
}

async function loadGateways() {
  try {
    const manifest = await request("/api/agentteams/manifest");
    Object.values(manifest.model_configs || {}).forEach(updateModelStatusFromPublic);
  } catch {
    state.gateways = state.gateways || {};
  }
}

function resizeCanvas(canvas) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { context, width: rect.width, height: rect.height };
}

function seededSeries(count, base, amplitude, phase = 0) {
  return Array.from({ length: count }, (_, index) => {
    const day = Math.sin((index / count) * Math.PI * 2 - Math.PI / 2);
    const ripple = Math.sin(index * 0.73 + phase) * amplitude * 0.18;
    return Math.max(0, base + amplitude * day + ripple);
  });
}

function drawScenarioChart() {
  // Removed: replaced with energy-balance panel
}


function formatSnapshotTime(timestamp) {
  if (!timestamp) return "未接入真实数据";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "未接入真实数据";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

function snapshotAtCurrentCursor() {
  const telemetry = state.energySnapshot?.telemetry;
  if (!Array.isArray(telemetry) || !telemetry.length) return null;
  let cursor;
  if (state.parallel?.running) {
    cursor = Math.max(0, state.parallel.cursor - 1);
  } else if (state.replayCursor != null) {
    cursor = state.replayCursor;
  } else {
    cursor = state.monitor?.cursor ?? state.energySnapshot.current_interval ?? 0;
  }
  return telemetry[Math.min(Math.max(Number(cursor) || 0, 0), telemetry.length - 1)] || null;
}

function gridEnergyUntil(cursor) {
  const telemetry = state.energySnapshot?.telemetry || [];
  const end = Math.min(Math.max(Number(cursor) || 0, 0), telemetry.length - 1);
  return telemetry.slice(0, end + 1).reduce((total, point) => (
    total + Number(point.grid_import_kw || 0) * 0.25
  ), 0);
}

function gridCostUntil(cursor) {
  const telemetry = state.energySnapshot?.telemetry || [];
  const end = Math.min(Math.max(Number(cursor) || 0, 0), telemetry.length - 1);
  return telemetry.slice(0, end + 1).reduce((total, point) => (
    total + Number(point.grid_import_kw || 0) * Number(point.tariff_yuan_per_kwh || 0) * 0.25
  ), 0);
}

function batteryPowerAt(cursor) {
  const telemetry = state.energySnapshot?.telemetry || [];
  const point = telemetry[cursor];
  if (!point) return { label: "待命", kw: 0 };
  const previous = telemetry[Math.max(0, cursor - 1)] || point;
  const capacity = Number(state.energySnapshot?.scenario?.site?.battery_capacity_kwh || 800);
  const deltaKwh = (Number(point.battery_soc || 0) - Number(previous.battery_soc || 0)) * capacity;
  const kw = Math.abs(deltaKwh / 0.25);
  if (kw < 0.01) return { label: "待命", kw: 0 };
  return { label: deltaKwh >= 0 ? "充电" : "放电", kw };
}

function drawMiniChart(canvas, seed = 0) {
  const { context, width, height } = resizeCanvas(canvas);
  const phase = state.chartTick * 0.12 + Number(seed);
  const top = seededSeries(72, 58, 22, phase).map((value, index) => value + Math.sin(index * 0.84 + phase) * 8);
  const bottom = seededSeries(72, 36, 18, phase + 1.4).map((value, index) => value + Math.cos(index * 0.58 + phase) * 7);
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#141519";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "rgba(255,255,255,.06)";
  context.lineWidth = 1;
  for (let row = 1; row < 4; row += 1) {
    const y = (height * row) / 4;
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
  [
    { values: top, color: "#7d80ff", scale: 82 },
    { values: bottom, color: "#4ca3ff", scale: 72 },
  ].forEach((item) => {
    context.beginPath();
    item.values.forEach((value, index) => {
      const x = (width * index) / (item.values.length - 1);
      const y = height - 18 - (value / item.scale) * (height - 34);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.strokeStyle = item.color;
    context.lineWidth = 1.4;
    context.stroke();
  });
}

function drawHomeCharts() {
  $$(".mini-chart").forEach((canvas) => drawMiniChart(canvas, canvas.dataset.seed || 0));
}

function startLiveCharts() {
  if (state.liveTimer) return;
  state.liveTimer = window.setInterval(() => {
    state.chartTick = (state.chartTick + 1) % 96;
    if (!$(".home-view").hidden) drawHomeCharts();
  }, 1200);
}

function startCampusReplay({ reset = false } = {}) {
  const telemetry = state.energySnapshot?.telemetry || [];
  if (!telemetry.length) return;
  if (reset || state.replayCursor == null) {
    state.replayCursor = Math.min(
      Math.max(Number(state.energySnapshot.current_interval) || 0, 0),
      telemetry.length - 1,
    );
  }
  if (state.replayTimer) window.clearInterval(state.replayTimer);
  state.replayTimer = null;
  applySnapshotToCampus();
  renderPowerChart();
  renderDailyLedger();
  renderReplayControl();
  if (state.replayMode === "pause") return;
  const intervalMs = state.replayMode === "real" ? 15 * 60 * 1000 : state.replayMode === "demo" ? 5000 : 800;
  state.replayTimer = window.setInterval(() => {
    if (!state.energySnapshot || state.parallel?.running) return;
    const points = state.energySnapshot.telemetry || [];
    if (!points.length) return;
    state.replayCursor = ((Number(state.replayCursor) || 0) + 1) % points.length;
    state.energySnapshot.current_interval = state.replayCursor;
    state.chartTick = state.replayCursor;
    localStorage.setItem("energymesh.savedSnapshot", JSON.stringify(state.energySnapshot));
    applySnapshotToCampus();
    renderPowerChart();
    renderDailyLedger();
    renderReplayControl();
  }, intervalMs);
}

function setReplayCursor(cursor) {
  const telemetry = state.energySnapshot?.telemetry || [];
  if (!telemetry.length) return;
  state.replayCursor = Math.min(Math.max(Number(cursor) || 0, 0), telemetry.length - 1);
  state.energySnapshot.current_interval = state.replayCursor;
  state.chartTick = state.replayCursor;
  localStorage.setItem("energymesh.savedSnapshot", JSON.stringify(state.energySnapshot));
  applySnapshotToCampus();
  renderPowerChart();
  renderDailyLedger();
  renderReplayControl();
}

function renderReplayControl() {
  const slider = $("#replay-slider");
  const readout = $("#replay-readout");
  const telemetry = state.energySnapshot?.telemetry || [];
  if (slider) {
    slider.max = String(Math.max(0, telemetry.length - 1));
    slider.value = String(Math.min(Number(state.replayCursor) || 0, Math.max(0, telemetry.length - 1)));
    slider.disabled = !telemetry.length;
  }
  if (readout) {
    const point = telemetry[Number(state.replayCursor) || 0];
    const modeText = state.replayMode === "real" ? "真实 24h" : state.replayMode === "demo" ? "演示" : state.replayMode === "fast" ? "快速" : "暂停";
    readout.textContent = point ? `${String(Number(state.replayCursor) + 1).padStart(2, "0")}/${telemetry.length} · ${formatSnapshotTime(point.timestamp)} · ${modeText}` : "等待 CSV";
  }
  $$("[data-replay-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.replayMode === state.replayMode);
  });
}

function updateAssetLabels(labels) {
  $$(".asset").forEach((element) => {
    element.dataset.hidden = "true";
  });
  Object.entries(labels).forEach(([key, position]) => {
    let element = $(`.asset[data-anchor="${key}"]`);
    if (!element) {
      element = document.createElement("article");
      element.className = "asset metric-card";
      element.dataset.anchor = key;
      $(".campus").append(element);
    }
    if (position.title) {
      element.innerHTML = `
        <span>${escapeHTML(position.title)}</span>
        <em>${escapeHTML(position.device || "")}</em>
        <strong>${escapeHTML(position.metric || "")}</strong>
        <small>${escapeHTML(position.note || "")}</small>
      `;
    }
    element.dataset.placement = position.placement || "above";
    element.dataset.selected = position.selected ? "true" : "false";
    element.style.setProperty("--x", `${position.x}px`);
    element.style.setProperty("--y", `${position.y}px`);
    element.dataset.hidden = position.visible ? "false" : "true";
  });
}

function renderCampusSimulation() {
  const sim = state.campusSimulation;
  // Current status (kW)
  $("#campus-balance").textContent = state.energySnapshot ? sim.balance : "等待 CSV";
  $("#campus-load").textContent = sim.load;
  $("#campus-generation").textContent = sim.generation;
  $("#campus-storage").textContent = sim.storage;
  $("#campus-storage-flow").textContent = sim.storageFlow;
  $("#campus-grid-import").textContent = sim.gridImport;
  $("#campus-current-time").textContent = state.energySnapshot ? sim.time : "等待 CSV";
  $("#campus-time-sync").textContent = state.energySnapshot ? "CSV 时间已校对" : "未对时";
  $("#campus-waste-kwh").textContent = sim.wastedKwh == null ? "-- kWh" : `${sim.wastedKwh.toFixed(1)} kWh`;
  $("#campus-extra-cost").textContent = sim.extraCost == null ? "--" : `¥${sim.extraCost.toFixed(1)}`;
  // Today cumulative (度 / kWh)
  $("#today-load").textContent = `${sim.todayLoad.toFixed(1)} 度`;
  $("#today-gen").textContent = `${sim.todayGen.toFixed(1)} 度`;
  $("#today-grid").textContent = `${sim.todayGrid.toFixed(1)} 度`;
  $("#today-charge").textContent = `${sim.todayCharge.toFixed(1)} 度`;
  $("#today-discharge").textContent = `${sim.todayDischarge.toFixed(1)} 度`;
  $("#today-cost").textContent = `¥${sim.todayCost.toFixed(2)}`;
  // Energy balance
  $("#balance-total-load").textContent = sim.totalLoad.toFixed(1);
  $("#balance-from-gen").textContent = `${sim.fromGen.toFixed(1)} 度`;
  $("#balance-from-storage").textContent = `${sim.fromStorage.toFixed(1)} 度`;
  $("#balance-from-grid").textContent = `${sim.fromGrid.toFixed(1)} 度`;
  $("#balance-to-load").textContent = `${sim.toLoad.toFixed(1)} 度`;
  $("#balance-to-storage").textContent = `${sim.toStorageCharge.toFixed(1)} 度`;
  $("#balance-to-grid").textContent = `${sim.toGridExport.toFixed(1)} 度`;
  const exportLabel = $("#balance-export-label");
  if (exportLabel) exportLabel.style.display = sim.toGridExport > 0.01 ? "inline" : "none";
}

function roundPower(value) {
  return Math.max(0, Number(value) || 0);
}

function campusFlowFromPower({ loadKw = 0, pvKw = 0, gridImportKw = 0, batteryPowerKw = 0, batteryMode = "idle", exportKw = 0 }) {
  const load = roundPower(loadKw);
  const pv = roundPower(pvKw);
  const grid = roundPower(gridImportKw);
  const battery = roundPower(batteryPowerKw);
  const charging = batteryMode === "charge";
  const discharging = batteryMode === "discharge";
  const solarStorage = charging ? Math.min(battery, pv) : 0;
  const storageLoad = discharging ? Math.min(battery, load) : 0;
  const gridLoad = Math.min(grid, Math.max(0, load - storageLoad));
  const solarLoad = Math.max(0, Math.min(pv - solarStorage, load - storageLoad - gridLoad));
  const solarGrid = Math.max(0, exportKw);
  const curtail = Math.max(0, pv - solarLoad - solarStorage - solarGrid);
  return {
    solar_load: solarLoad,
    solar_storage: solarStorage,
    storage_load: storageLoad,
    grid_load: gridLoad,
    solar_grid: solarGrid,
    curtail,
  };
}

function previewFlowFromCurrent({ loadKw, pvKw, gridImportKw, batteryPowerKw, batteryMode }) {
  const avoidCurtail = Math.min(Math.max(0, pvKw - loadKw * .55), Math.max(2, pvKw * .32));
  const targetStorage = Math.max(batteryMode === "discharge" ? batteryPowerKw : 0, Math.min(loadKw * .42, gridImportKw + avoidCurtail));
  const targetGrid = Math.max(0, gridImportKw - targetStorage * .78);
  const targetCurtail = Math.max(0, Math.min(0.8, pvKw - loadKw - avoidCurtail));
  return campusFlowFromPower({
    loadKw,
    pvKw,
    gridImportKw: targetGrid,
    batteryPowerKw: targetStorage,
    batteryMode: "discharge",
    exportKw: 0,
  });
}

function formatDelta(before, after, unit = "kW") {
  return `${Number(before || 0).toFixed(1)} → ${Number(after || 0).toFixed(1)} ${unit}`;
}

function planNarrativeFromFlow(message = "", currentFlow = {}, previewFlow = {}, source = "local") {
  const gridDrop = Number(currentFlow.grid_load || 0) - Number(previewFlow.grid_load || 0);
  const storageGain = Number(previewFlow.storage_load || 0) - Number(currentFlow.storage_load || 0);
  const chargeGain = Number(previewFlow.solar_storage || 0) - Number(currentFlow.solar_storage || 0);
  const curtailDrop = Number(currentFlow.curtail || 0) - Number(previewFlow.curtail || 0);
  const asksStorage = /储能|充电|放电|battery|storage/i.test(message);
  const asksCurtail = /限发|浪费|curtail|waste/i.test(message);
  const asksGrid = /购电|电网|grid/i.test(message);
  let title = "动态调度预览";
  if (asksStorage && chargeGain > storageGain) title = "发电补储预览";
  else if (asksStorage) title = "储能接管预览";
  else if (asksCurtail) title = "限发回收预览";
  else if (asksGrid) title = "降购电预览";
  const reasonBits = [];
  if (gridDrop > .05) reasonBits.push(`把电网购电压低 ${gridDrop.toFixed(1)} kW`);
  if (storageGain > .05) reasonBits.push(`让储能多放电 ${storageGain.toFixed(1)} kW 给用电格`);
  if (chargeGain > .05) reasonBits.push(`把发电多送 ${chargeGain.toFixed(1)} kW 进储能格`);
  if (curtailDrop > .05) reasonBits.push(`减少限发 ${curtailDrop.toFixed(1)} kW`);
  if (!reasonBits.length) reasonBits.push("当前时刻约束较紧，先保持主流向，只做小幅调度预演");
  const prefix = source === "llm" ? "LLM 根据当前沙盘和这轮对话生成：" : "真实模型未接入，未生成可采用方案：";
  return {
    title,
    source,
    reason: `${prefix}${reasonBits.join("，")}。`,
  };
}

function renderFlowPreviewCard(currentFlow, previewFlow, plan = {}) {
  const card = $("#flow-preview-card");
  if (!card) return;
  const visible = Boolean(previewFlow);
  card.hidden = !visible;
  if (!visible) return;
  card.querySelector("header strong").textContent = plan.title || "动态调度预览";
  card.querySelector("header span").textContent = plan.source === "agentteams" ? "AgentTeams Worker 真实方案" : plan.source === "llm" ? "LLM 新方案预览" : "等待真实模型方案";
  $("#delta-grid").textContent = formatDelta(currentFlow.grid_load, previewFlow.grid_load);
  $("#delta-storage").textContent = formatDelta(currentFlow.storage_load, previewFlow.storage_load);
  $("#delta-curtail").textContent = formatDelta(currentFlow.curtail, previewFlow.curtail);
  $("#flow-plan-reason").textContent = plan.reason || "根据当前沙盘状态生成新的电流预演。";
}

function showCampusPlanPreview(currentFlow, previewFlow, plan = {}) {
  state.flowPreview = { currentFlow, previewFlow, plan };
  renderFlowPreviewCard(currentFlow, previewFlow, plan);
  state.campus3d?.previewEnergyState?.({ flows: previewFlow });
}

function clearCampusPlanPreview(adopt = false) {
  if (adopt) state.campus3d?.adoptPreview?.();
  state.flowPreview = null;
  renderFlowPreviewCard(null, null);
}

function ledgerRecord(action, currentFlow = {}, previewFlow = {}) {
  const plan = state.flowPreview?.plan || {};
  const now = new Date();
  const record = {
    id: `PLAN-${now.getTime()}`,
    action,
    time: state.campusSimulation?.time || now.toLocaleString("zh-CN", { hour12: false }),
    title: plan.title || "动态调度预览",
    reason: plan.reason || "根据当前沙盘状态生成新的电流预演。",
    expected: {
      grid: formatDelta(currentFlow.grid_load, previewFlow.grid_load),
      storage: formatDelta(currentFlow.storage_load, previewFlow.storage_load),
      waste: formatDelta(currentFlow.curtail, previewFlow.curtail),
    },
  };
  state.planLedger.unshift(record);
  state.planLedger = state.planLedger.slice(0, 12);
  window.localStorage.setItem("energymesh.planLedger", JSON.stringify(state.planLedger));
  renderPlanLedger();
}

function isFlowTuningRequest(message) {
  return /减少|降低|优化|改善|调|方案|预览|购电|限发|浪费|储能|放电|充电|grid|curtail|waste|battery|storage|optimi[sz]e/i.test(message);
}

function isFrustratedChatRequest(message) {
  return /正常说话|不和我对话|有毛病|好好看看|咋回事|为什么没有|能不能|一直没充|一直浪费/i.test(message);
}

function hasReadyTeamLeaderGateway() {
  const gateway = state.gateways?.team_leader || state.gateways?.[state.selectedAgent];
  return Boolean(gateway?.apiKey && gateway.connectionStatus === "正常");
}

function hasReadyAgentGateway(agentId = state.selectedAgent) {
  const gateway = state.gateways?.[agentId] || (agentId !== "team_leader" ? state.gateways?.team_leader : null);
  return Boolean(gateway?.apiKey && gateway.connectionStatus === "正常");
}

function updateChatGatewayGate() {
  const input = $("#ai-chat-input");
  const sendButton = $("#ai-chat-form button");
  if (!input || !sendButton) return;
  const ready = hasReadyAgentGateway(state.selectedAgent);
  input.disabled = !ready;
  sendButton.disabled = !ready;
  input.placeholder = ready
    ? "例如：帮我减少购电和限发，先预览新流向"
    : "请先点齿轮接入模型网关，测试成功后才能对话";
}

function normalizeLegacyUserText(text) {
  return String(text || "")
    .replace(/(?:^|\s)(你\s*){1,3}Operator\s*/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function repairSavedAgentThreads(threads = {}) {
  Object.values(threads).forEach((thread) => {
    if (!Array.isArray(thread)) return;
    thread.forEach((message) => {
      if (message?.role === "user") message.text = normalizeLegacyUserText(message.text);
    });
  });
  return threads;
}

function previewFlowFromLatestSnapshot() {
  const point = snapshotAtCurrentCursor();
  if (!point) return null;
  const telemetry = state.energySnapshot?.telemetry || [];
  const cursor = Math.min(Math.max(Number(point.interval) || 0, 0), telemetry.length - 1);
  const prevPt = cursor > 0 ? telemetry[cursor - 1] : point;
  const capacity = Number(state.energySnapshot?.scenario?.site?.battery_capacity_kwh || 800);
  const dt = 0.25;
  const deltaSoc = (point.battery_soc || 0) - (prevPt.battery_soc || 0);
  const batteryPowerKw = Math.abs(deltaSoc * capacity / dt);
  const batteryMode = deltaSoc >= 0.001 ? "charge" : deltaSoc <= -0.001 ? "discharge" : "idle";
  const gridImportKw = Math.max(0, (point.load_kw || 0) - (point.pv_kw || 0) + deltaSoc * capacity / dt);
  const currentFlow = state.lastCampusFlow || campusFlowFromPower({
    loadKw: point.load_kw || 0,
    pvKw: point.pv_kw || 0,
    gridImportKw,
    batteryPowerKw,
    batteryMode,
    exportKw: Number(point.grid_export_kw || point.export_kw || 0),
  });
  const previewFlow = previewFlowFromCurrent({
    loadKw: point.load_kw || 0,
    pvKw: point.pv_kw || 0,
    gridImportKw,
    batteryPowerKw,
    batteryMode,
  });
  return { currentFlow, previewFlow };
}

function handleLocalFlowTuningRequest(message) {
  if (!isFlowTuningRequest(message) && !isFrustratedChatRequest(message)) return false;
  if (hasReadyTeamLeaderGateway()) return false;
  clearCampusPlanPreview(false);
  const reply = state.energySnapshot
    ? "我看到了右侧 CSV 园区数据，但现在没有通过测试的真实 Team Leader 模型网关，所以我不会生成本地替代方案，也不会改沙盘流向。请先接入并测试 DeepSeek/模型网关；之后调度类请求会进入真实 AgentTeams，普通聊天会由真实模型直接回答。"
    : "右侧还没有上传 CSV，且 Team Leader 模型网关未就绪。我不会生成本地替代方案；先上传园区 CSV 并测试模型网关，之后再让真实 AgentTeams 做调度。";
  addChatMessage("agent", reply, "team_leader");
  return true;
}

function renderPlanLedger() {
  const list = $("#plan-ledger-list");
  if (!list) return;
  if (!state.energySnapshot) {
    state.planLedger = [];
    window.localStorage.removeItem("energymesh.planLedger");
  }
  $("#plan-ledger-count").textContent = `${state.planLedger.length} 条记录`;
  if (!state.planLedger.length) {
    list.innerHTML = `<p class="empty">采用或拒绝 Agent 方案后，会在这里留下方案内容、理由和预期变化。</p>`;
    return;
  }
  list.innerHTML = state.planLedger.map((record) => `
    <article class="plan-ledger-item ${record.action === "adopted" ? "adopted" : "rejected"}">
      <header>
        <div><span>${record.action === "adopted" ? "已采用" : "已拒绝"}</span><strong>${escapeHTML(record.title)}</strong></div>
        <time>${escapeHTML(record.time)}</time>
      </header>
      <p>${escapeHTML(record.reason)}</p>
      <dl>
        <div><dt>电网购电</dt><dd>${escapeHTML(record.expected.grid)}</dd></div>
        <div><dt>储能放电</dt><dd>${escapeHTML(record.expected.storage)}</dd></div>
        <div><dt>限发浪费</dt><dd>${escapeHTML(record.expected.waste)}</dd></div>
      </dl>
    </article>
  `).join("");
}

function applySnapshotToCampus() {
  const telemetry = state.energySnapshot?.telemetry || [];
  const point = snapshotAtCurrentCursor();
  if (!point) {
    renderCampusSimulation();
    state.campus3d?.applyEnergyState?.({
      load: "-- kW",
      generation: "-- kW",
      storage: "SOC --",
      storageFlow: "等待 CSV 接入",
      gridImport: "-- kW",
      noData: true,
      flows: campusFlowFromPower({}),
      previewFlows: null,
    });
    return;
  }
  const cursor = Math.min(Math.max(Number(point.interval) || 0, 0), telemetry.length - 1);
  const storageFlow = batteryPowerAt(cursor);
  const capacity = Number(state.energySnapshot?.scenario?.site?.battery_capacity_kwh || 800);
  const dt = 0.25; // 15 minutes in hours

  // Compute cumulative energy balances from interval 0 to cursor
  let totalLoadKwh = 0;
  let totalGenKwh = 0;
  let totalGridImportKwh = 0;
  let totalGridExportKwh = 0;
  let totalChargeKwh = 0;
  let totalDischargeKwh = 0;
  let totalCost = 0;
  let wastedKwh = 0;
  let extraCost = 0;

  for (let i = 0; i <= cursor; i++) {
    const pt = telemetry[i];
    const prev = i > 0 ? telemetry[i - 1] : pt;
    const loadKwh = (pt.load_kw || 0) * dt;
    const pvKwh = (pt.pv_kw || 0) * dt;
    const deltaSoc = (pt.battery_soc || 0) - (prev.battery_soc || 0);
    const deltaEnergy = deltaSoc * capacity; // kWh charged(+) or discharged(-)

    let chargeKwh = 0;
    let dischargeKwh = 0;
    if (deltaEnergy > 0) chargeKwh = deltaEnergy;
    else dischargeKwh = -deltaEnergy;

    // Grid import = load - pv + charge - discharge (energy balance)
    const netGridKwh = loadKwh - pvKwh + chargeKwh - dischargeKwh;
    const gridImportKwh = Math.max(0, netGridKwh);
    const gridExportKwh = Math.max(0, -netGridKwh);
    const cost = gridImportKwh * (pt.tariff_yuan_per_kwh || 0);

    totalLoadKwh += loadKwh;
    totalGenKwh += pvKwh;
    totalGridImportKwh += gridImportKwh;
    totalGridExportKwh += gridExportKwh;
    totalChargeKwh += chargeKwh;
    totalDischargeKwh += dischargeKwh;
    totalCost += cost;
    wastedKwh += Math.max(0, pvKwh - Math.min(pvKwh, loadKwh + chargeKwh) - gridExportKwh);
    extraCost += gridImportKwh * (pt.tariff_yuan_per_kwh || 0);
  }

  // Current instant power values
  const prevPt = cursor > 0 ? telemetry[cursor - 1] : point;
  const deltaSoc = point.battery_soc - prevPt.battery_soc;
  const batteryPowerKw = Math.abs(deltaSoc * capacity / dt);
  const batteryMode = deltaSoc >= 0.001 ? "charge" : deltaSoc <= -0.001 ? "discharge" : "idle";
  const batteryLabel = batteryMode === "charge" ? "正在充电" : batteryMode === "discharge" ? "正在放电" : "待机";
  const gridImportKw = Math.max(0, (point.load_kw || 0) - (point.pv_kw || 0) + deltaSoc * capacity / dt);
  const exportKw = Number(point.grid_export_kw || point.export_kw || 0);
  const currentFlow = campusFlowFromPower({
    loadKw: point.load_kw || 0,
    pvKw: point.pv_kw || 0,
    gridImportKw,
    batteryPowerKw,
    batteryMode,
    exportKw,
  });
  const previewFlow = previewFlowFromCurrent({
    loadKw: point.load_kw || 0,
    pvKw: point.pv_kw || 0,
    gridImportKw,
    batteryPowerKw,
    batteryMode,
  });
  state.lastCampusFlow = currentFlow;

  // Energy balance decomposition
  const fromGrid = totalGridImportKwh;
  const fromStorage = totalDischargeKwh;
  const fromGen = Math.max(0, totalLoadKwh - fromGrid - fromStorage);
  const toStorageCharge = totalChargeKwh;
  const toGridExport = totalGridExportKwh;
  const toLoad = Math.max(0, totalGenKwh - toStorageCharge - toGridExport);

  state.campusSimulation = {
    // Current status (kW)
    time: formatSnapshotTime(point.timestamp),
    balance: `¥${Math.max(0, 10000 - totalCost).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    load: `${(point.load_kw || 0).toFixed(2)} kW`,
    generation: `${(point.pv_kw || 0).toFixed(2)} kW`,
    storage: `SOC ${((point.battery_soc || 0) * 100).toFixed(0)}%`,
    storageFlow: `${batteryLabel}${batteryPowerKw > 0.01 ? " " + batteryPowerKw.toFixed(2) + " kW" : ""}`,
    gridImport: `${gridImportKw.toFixed(2)} kW`,
    socPercent: (point.battery_soc || 0) * 100,

    // Today cumulative (度)
    todayLoad: totalLoadKwh,
    todayGen: totalGenKwh,
    todayGrid: totalGridImportKwh,
    todayCharge: totalChargeKwh,
    todayDischarge: totalDischargeKwh,
    todayCost: totalCost,

    // Energy balance
    totalLoad: totalLoadKwh,
    fromGen,
    fromStorage,
    fromGrid,
    toLoad,
    toStorageCharge,
    toGridExport,
    wastedKwh,
    extraCost,
  };
  renderCampusSimulation();
  state.campus3d?.applyEnergyState?.({
    optimized: Boolean(state.task?.approval?.approved),
    gridImport: `${gridImportKw.toFixed(2)} kW`,
    generation: `${(point.pv_kw || 0).toFixed(2)} kW`,
    storage: `SOC ${((point.battery_soc || 0) * 100).toFixed(0)}%`,
    storageFlow: state.campusSimulation.storageFlow,
    load: `${(point.load_kw || 0).toFixed(2)} kW`,
    socPercent: (point.battery_soc || 0) * 100,
    flows: currentFlow,
    previewFlows: state.flowPreview ? previewFlow : null,
  });
  if (state.flowPreview) showCampusPlanPreview(currentFlow, previewFlow, state.flowPreview.plan);
  else clearCampusPlanPreview(false);
}

function applyRuntimeToCampus(runtime) {
  const artifacts = runtime?.artifacts || [];
  const stateArtifact = artifacts.find((artifact) => artifact.name === "state.json");
  const planArtifact = artifacts.find((artifact) => artifact.name === "plan.json");
  const verification = artifacts.find((artifact) => artifact.name === "verification.json");
  const energyState = stateArtifact?.payload?.energy_state || {};
  const recommendedPlan = verification?.payload?.recommended_plan_id || "Plan-B";
  const currentLoad = Number(energyState.current_load_mw || 25);
  const pvForecast = Number(energyState.pv_forecast_mw || 10);
  const soc = Number(energyState.storage_soc_percent || 61);
  if (!planArtifact && !verification) return;
  state.campusSimulation = {
    optimized: true,
    time: "2026-07-31 14:00",
    balance: "¥7,000.00",
    load: `${currentLoad.toFixed(1)} MW`,
    generation: `${Math.max(10, pvForecast + 20).toFixed(0)} MW`,
    storage: `SOC ${Math.min(88, soc + 18).toFixed(0)}%`,
    storageFlow: `${recommendedPlan} 调峰中`,
    gridImport: "8.00 MW",
    todayLoad: 0, todayGen: 0, todayGrid: 0, todayCharge: 0, todayDischarge: 0, todayCost: 0,
    totalLoad: 0, fromGen: 0, fromStorage: 0, fromGrid: 0, toLoad: 0, toStorageCharge: 0, toGridExport: 0,
  };
  renderCampusSimulation();
  state.campus3d?.applyEnergyState?.({
    optimized: true,
    storage: state.campusSimulation.storage,
    load: state.campusSimulation.load,
    recommendedPlan,
  });
}

function statusClass(value) {
  if (value === "COMPLETED" || value === "approved") return "ok";
  if (value === "ROLLBACK" || value === "FAILED" || value === "rejected") return "danger";
  if (value === "AWAITING_APPROVAL" || value === "audit_approved") return "warn";
  return "info";
}

function renderTask() {
  const task = state.task;
  const context = state.context;
  $("#task-id").textContent = task?.task_id || t("noTask");
  $("#task-version").textContent = task ? `V${task.task_version}` : "--";
  $("#task-state").textContent = task ? stateLabels[state.language][task.state] || task.state : stateLabels[state.language].IDLE;
  $("#task-state").className = statusClass(task?.state);
  $("#context-hash").textContent = context?.context_hash ? `${context.context_hash.slice(0, 20)}...` : t("contextPending");
  $("#approval-status").textContent = state.approval ? t("approved") : task?.state === "AWAITING_APPROVAL" ? t("needsHuman") : t("waiting");
  $("#evidence-status").textContent = task?.evidence_sha256 ? t("sealed") : state.evidence ? t("ready") : t("notSealed");
  $("#open-evidence").disabled = !state.task;
  $("#review-candidates").disabled = !state.candidates.length;
  if ($("#approve-b")) $("#approve-b").disabled = task?.state !== "AWAITING_APPROVAL";
  if ($("#execute-b")) $("#execute-b").disabled = !state.approval || task?.state !== "AWAITING_APPROVAL";
}

function renderCandidates() {
  if (!state.energySnapshot) {
    $("#candidate-list").innerHTML = `<p class="empty">请先上传 CSV。候选方案只会基于已接入的同一天真实回放数据生成。</p>`;
    $("#review-candidates").disabled = true;
    return;
  }
  if (state.activeScenario) {
    const artifacts = scenarioAgentArtifacts(state.activeScenario);
    $("#candidate-list").innerHTML = `
      <article class="strategy-code">
        <span>策略代码预览</span>
        <pre>${escapeHTML(scenarioStrategyCode(state.activeScenario))}</pre>
      </article>
      <article class="audit-report">
        <span>审核报告</span>
        <p>${escapeHTML(scenarioAuditReport(state.activeScenario))}</p>
      </article>
      <div class="agent-artifacts">
        ${artifacts.map(([artifact, detail]) => `
          <button class="candidate approved structured-artifact" type="button">
            <div>
              <span>${escapeHTML(artifact)}</span>
              <strong>${state.language === "zh" ? "对象已生成" : "Object ready"}</strong>
            </div>
            <pre>${escapeHTML(JSON.stringify(detail, null, 2))}</pre>
          </button>
        `).join("")}
      </div>
    `;
    $$(".candidate").forEach((candidate, index) => {
      candidate.addEventListener("click", () => openTraceDetail(Math.min(index + 1, state.events.length - 1)));
    });
    return;
  }
  if (!state.candidates.length) {
    $("#candidate-list").innerHTML = `<p class="empty">${escapeHTML(t("candidateEmpty"))}</p>`;
    return;
  }
  $("#candidate-list").innerHTML = state.candidates.map((candidate) => {
    const verdict = state.audit.find((item) => item.candidate_id === candidate.candidate_id);
    const rejected = verdict?.verdict === "rejected";
    const status = verdict ? (rejected ? t("rejected") : t("auditPassed")) : t("pendingAudit");
    return `
      <button class="candidate ${rejected ? "rejected" : "approved"}" type="button" data-candidate-id="${escapeHTML(candidate.candidate_id)}">
        <div>
          <span>${escapeHTML(candidate.candidate_id)} · ${escapeHTML(candidate.name)}</span>
          <strong>${escapeHTML(status)}</strong>
        </div>
        <dl>
          <div><dt>${state.language === "zh" ? "成本" : "Cost"}</dt><dd>¥${Math.round(candidate.cost_yuan).toLocaleString()}</dd></div>
          <div><dt>${state.language === "zh" ? "峰值" : "Peak"}</dt><dd>${Math.round(candidate.max_power_kw)} kW</dd></div>
          <div><dt>SOC</dt><dd>${candidate.soc_min_percent}% - ${candidate.soc_max_percent}%</dd></div>
          <div><dt>${state.language === "zh" ? "变压器" : "Transformer"}</dt><dd>${candidate.transformer_load_percent}%</dd></div>
        </dl>
        <p>${verdict ? escapeHTML(verdict.reason) : escapeHTML(state.language === "zh" ? "等待审核结论。" : "Waiting for audit verdict.")}</p>
      </button>
    `;
  }).join("");
  $$(".candidate").forEach((candidate) => {
    candidate.addEventListener("click", () => openCandidateDetail(candidate.dataset.candidateId));
  });
}

function traceText(event) {
  const time = new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour12: false });
  return `${time} · ${actorLabels[state.language][event.actor] || event.actor}`;
}

function renderTrace() {
  $("#trace-count").textContent = state.language === "zh" ? `${state.events.length} ${t("events")}` : `${state.events.length} ${t("events")}`;
  if (!state.energySnapshot) {
    $("#trace-count").textContent = "0 个事件";
    $("#trace-list").innerHTML = `<p class="empty">请先上传 CSV。Trace 只记录真实接入数据触发的感知、调度、审核和执行事件。</p>`;
    $("#open-evidence").disabled = true;
    return;
  }
  if (state.activeScenario) {
    $("#trace-list").innerHTML = state.activeScenario.steps.map(([label, detail], index) => `
      <button class="trace-item" type="button" data-index="${index}">
        <i class="${index === state.activeScenario.steps.length - 1 ? "ok" : "info"}"></i>
        <span>Step ${String(index + 1).padStart(2, "0")} · ${escapeHTML(label)}</span>
        <small>${escapeHTML(detail)}</small>
      </button>
    `).join("");
    $$(".trace-item").forEach((item) => {
      item.addEventListener("click", () => openTraceDetail(Number(item.dataset.index)));
    });
    return;
  }
  if (!state.events.length) {
    $("#trace-list").innerHTML = `<p class="empty">${escapeHTML(t("traceEmpty"))}</p>`;
    return;
  }
  $("#trace-list").innerHTML = state.events.map((event, index) => `
    <button class="trace-item" type="button" data-index="${index}">
      <i class="${statusClass(event.to_state)}"></i>
      <span>${escapeHTML(traceText(event))}</span>
      <small>${escapeHTML(event.reason)} · ${escapeHTML(event.to_state)}</small>
    </button>
  `).join("");
  $$(".trace-item").forEach((item) => {
    item.addEventListener("click", () => openTraceDetail(Number(item.dataset.index)));
  });
}

async function loadOpsEvidence() {
  try {
    state.opsEvidence = await request("/api/ops/evidence-board");
    renderOpsReport();
  } catch (error) {
    state.opsEvidence = null;
    renderOpsReport();
  }
}

function evidenceStatus(value, fallback = "--") {
  if (value === true) return "Ready";
  if (value === false) return "Waiting";
  if (value == null || value === "") return fallback;
  return String(value);
}

function renderOpsReport() {
  const evidence = state.opsEvidence;
  const parallel = state.parallel;
  const uploaded = Boolean(evidence?.data_snapshot?.loaded || state.energySnapshot);
  $("#ops-data-state").textContent = uploaded ? "Loaded" : "Waiting";
  $("#ops-plan-state").textContent = evidence?.closed_loop?.old_plan_status || (parallel ? "tracking" : "--");
  $("#ops-trace-count").textContent = String(evidence?.agentteams?.trace_count || parallel?.agentteams_trace?.length || state.events?.length || 0);

  const comparison = evidence?.comparison || {};
  const loopItems = [
    ["业务输入", evidence?.closed_loop?.business_input || "上传 OpenCEM CSV，或接入 EMS/BMS/PCS 只读快照。"],
    ["上下文快照", uploaded ? `${evidence?.data_snapshot?.telemetry_points || state.energySnapshot?.telemetry?.length || 0} 个 15 分钟点已归一化` : "等待园区数据接入"],
    ["动态重规划", `${evidence?.closed_loop?.replan_count ?? parallel?.total_reoptimizations ?? 0} 次；旧计划 ${evidence?.closed_loop?.old_plan_status || "等待偏差判定"}`],
    ["人工门禁", evidence?.closed_loop?.hitl_gate || "高风险写入和柔性负荷动作必须审批"],
    ["执行回读", `${Math.round((evidence?.closed_loop?.execution_readback_rate || 0) * 100)}% readback；失效计划误执行 ${comparison.invalid_plan_executions ?? 0}`],
    ["完成条件", evidence?.closed_loop?.completion_condition || "跑完 96 点、封存证据、无约束违规"],
  ];
  $("#ops-loop-list").innerHTML = loopItems.map(([label, value], index) => `
    <li>
      <i>${index + 1}</i>
      <div><strong>${escapeHTML(label)}</strong><span>${escapeHTML(value)}</span></div>
    </li>
  `).join("");

  const workers = evidence?.agentteams?.workers || [];
  $("#ops-agent-list").innerHTML = workers.map((worker) => `
    <article>
      <strong>${escapeHTML(worker.display_name)}</strong>
      <span>${escapeHTML(worker.role)}</span>
      <small>${escapeHTML((worker.skills || []).join(" · "))}</small>
    </article>
  `).join("") || "<p class=\"empty\">AgentTeams manifest 未加载。</p>";

  $("#ops-permission-list").innerHTML = workers.map((worker) => `
    <article>
      <div><strong>${escapeHTML(worker.display_name)}</strong><span>${escapeHTML((worker.mcp_servers || []).join(", "))}</span></div>
      <ul>${(worker.permissions || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>
    </article>
  `).join("") || "<p class=\"empty\">等待权限清单。</p>";

  $("#ops-rag-insight").textContent = evidence?.rag_memory?.latest_insight || "等待偏差记录。";
  $("#ops-memory-deviation").textContent = String(evidence?.rag_memory?.writes?.deviation_events || 0);
  $("#ops-memory-human").textContent = String(evidence?.rag_memory?.writes?.human_adjustments || 0);
  $("#ops-memory-outcome").textContent = String(evidence?.rag_memory?.writes?.final_outcomes || 0);

  const slo = evidence?.slo || {};
  const sloItems = [
    ["刷新", evidenceStatus(slo.plan_refresh_p95_ms, "待采样")],
    ["告警", evidenceStatus(slo.alert_state || slo.status, "未触发")],
    ["节省", `¥${Number(comparison.savings_yuan || parallel?.savings_yuan || 0).toFixed(2)}`],
    ["违规", `${comparison.constraint_violations ?? 0}`],
  ];
  $("#ops-slo-list").innerHTML = sloItems.map(([label, value]) => `
    <article><span>${escapeHTML(label)}</span><strong>${escapeHTML(value)}</strong></article>
  `).join("");
}

function renderDailyLedger() {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const snapshot = state.energySnapshot;
  const parallel = state.parallel;
  const hasData = Boolean(snapshot);
  const rawRows = snapshot?.environment_signals?.raw_rows || 0;
  const replayDate = snapshot?.environment_signals?.replay_date;
  const totalLoad = Number(state.campusSimulation?.todayLoad || 0);
  const totalCost = Number(parallel?.baseline_cost_yuan || state.campusSimulation?.todayCost || 0);
  const optimizedCost = Number(parallel?.optimized_cost_yuan || 0);
  const savings = Number(parallel?.savings_yuan || 0);
  $("#today-ledger-date").textContent = `${today} · 今天`;
  $("#today-ledger-status").textContent = hasData ? `${rawRows} rows normalized` : "等待园区接入";
  $("#today-ledger-source").textContent = hasData
    ? `${snapshot.source}${replayDate ? " · " + replayDate : ""}`
    : "No live feed";
  $("#today-ledger-time").textContent = hasData ? "00:00-24:00 · 96 点回放/滚动计划" : "00:00-24:00 · 96 点计划";
  $("#today-ledger-copy").textContent = hasData
    ? "今日运行日已接入数据；控制台会持续比较原始策略与 Agent 优化策略，并在偏差超限时废止旧计划、重调度和记录证据。"
    : "接入真实园区后，这里按天汇总负荷、光伏、储能、购电、成本、偏差、重调度、审批和执行回读。";
  $("#today-ledger-load").textContent = hasData ? `Load ${totalLoad.toFixed(1)} kWh` : "Load --";
  $("#today-ledger-cost").textContent = parallel
    ? `Cost ¥${optimizedCost.toFixed(2)} / save ¥${savings.toFixed(2)}`
    : hasData ? `Cost ¥${totalCost.toFixed(2)}` : "Cost --";
  $("#today-ledger-runs").textContent = parallel ? `${parallel.cursor || 0}/96 intervals` : hasData ? "1 data run" : "0 runs";
}

function setWorkspaceMode(activeRail = "nav-workspace") {
  $(".app-shell").classList.remove("home-mode");
  $("#home-view").hidden = true;
  setActiveRail(activeRail);
}

function openHome() {
  setAgentDirectory(false);
  $("#ops-drawer").hidden = true;
  $(".app-shell").classList.add("home-mode");
  $("#home-view").hidden = false;
  setActiveRail("nav-overview");
  renderDailyLedger();
  drawHomeCharts();
}

function resetLeaderConversation() {
  state.activeHistory = "new";
  state.activeScenario = null;
  state.run = null;
  state.task = null;
  state.context = null;
  state.candidates = [];
  state.audit = [];
  state.events = [];
  state.evidence = null;
  state.approval = null;
  state.selectedAgent = "team_leader";
  state.agentThreads = {};
  state.pendingExecutionScenario = null;
  renderSelectedAgent();
  renderTask();
  renderCandidates();
  renderTrace();
  renderOpsReport();
  renderAgentThread("team_leader");
}

function openNewWorkspace() {
  setAgentDirectory(false);
  $("#ops-drawer").hidden = true;
  setWorkspaceMode("nav-workspace");
  resetLeaderConversation();
  $("#ai-chat-input").focus();
}

function mapActorToAgentId(actor) {
  const map = {
    "Team Leader": "team_leader",
    "Perception Agent": "perception_agent",
    "Dispatch Agent": "dispatch_agent",
    "Audit Agent": "audit_agent",
    "Execution Agent": "execution_agent",
    "Execution Worker": "execution_agent",
    "Human Approval": "team_leader",
    "Human Operator": "team_leader",
    "Verification": "execution_agent",
  };
  return map[actor] || "team_leader";
}

function formatEventChatText(event) {
  const time = new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  let text = `**${event.reason}**\n_(${time} · ${event.to_state})_\n`;

  if ((event.to_state === "SENSING" || event.to_state === "CONTEXT_VALIDATED" || event.to_state === "REPLANNING_REQUIRED") && state.context) {
    text += `\n\`\`\`json\n${JSON.stringify({
      context_id: state.context.context_id,
      context_hash: state.context.context_hash?.slice(0, 16) + "...",
      changes: state.context.changes,
      data_quality: state.context.data_quality,
    }, null, 2)}\n\`\`\``;
  }

  if (event.to_state === "PLANNING" && state.candidates?.length) {
    text += `\n\`\`\`json\n${JSON.stringify(state.candidates.map(c => ({
      id: c.candidate_id,
      name: c.name,
      priority: c.priority,
      cost_yuan: c.cost_yuan,
      peak_kw: c.max_power_kw,
      transformer_pct: c.transformer_load_percent,
      soc_range: `${c.soc_min_percent}%-${c.soc_max_percent}%`,
      status: c.status,
    })), null, 2)}\n\`\`\``;
  }

  if ((event.to_state === "AUDITING" || event.to_state === "AWAITING_APPROVAL") && state.audit?.length) {
    text += `\n\`\`\`json\n${JSON.stringify(state.audit.map(a => ({
      candidate: a.candidate_id,
      verdict: a.verdict,
      reason: a.reason,
      transformer_pct: a.transformer_load_percent,
      safety_limit_pct: a.safety_limit_percent,
      checks: a.checks,
    })), null, 2)}\n\`\`\``;
  }

  if (event.to_state === "EXECUTING" && state.evidence?.trace_steps) {
    text += `\n\`\`\`json\n${JSON.stringify({
      execution_commands: state.evidence.trace_steps?.filter(s => s[0].includes("Execution")),
    }, null, 2)}\n\`\`\``;
  }

  return text;
}

function renderEventsToChat() {
  const container = $("#chat-messages");
  if (!state.events?.length) return;
  if (container.querySelector("[data-run-marker]")) return;

  const marker = document.createElement("div");
  marker.dataset.runMarker = "true";
  marker.hidden = true;
  container.append(marker);

  for (const event of state.events) {
    const agentId = mapActorToAgentId(event.actor);
    addChatMessage("agent", formatEventChatText(event), agentId, { persist: false });
  }

  if (state.task?.state === "AWAITING_APPROVAL") {
    const candidateB = state.candidates.find(c => c.candidate_id === "Candidate-B");
    const auditB = state.audit.find(a => a.candidate_id === "Candidate-B");
    const text = state.language === "zh"
      ? `## 等待人工审批\n\n**${candidateB?.name || "Candidate-B"}** 已通过独立审核，建议执行。\n\n- 成本: ¥${Math.round(candidateB?.cost_yuan || 0).toLocaleString()}\n- 峰值功率: ${Math.round(candidateB?.max_power_kw || 0)} kW\n- 变压器负载: ${candidateB?.transformer_load_percent || "--"}%\n- SOC 范围: ${candidateB?.soc_min_percent || "--"}% - ${candidateB?.soc_max_percent || "--"}%\n\n审核结论: ${auditB?.reason || ""}\n\n请在下方选择操作:`
      : `## Awaiting Human Approval\n\n**${candidateB?.name || "Candidate-B"}** passed independent audit.\n\n- Cost: ¥${Math.round(candidateB?.cost_yuan || 0).toLocaleString()}\n- Peak: ${Math.round(candidateB?.max_power_kw || 0)} kW\n- Transformer: ${candidateB?.transformer_load_percent || "--"}%\n\nPlease choose an action:`;
    addChatMessage("agent", text, "execution_agent", {
      meta: { action: "confirm_execution", scenarioKey: state.run?.task_id || "compound_change" },
      persist: false,
    });
  }

  container.scrollTop = container.scrollHeight;
}

async function refreshTask(taskId) {
  const [task, context, candidates, audit, events, evidence] = await Promise.all([
    request(`/api/tasks/${taskId}`),
    request(`/api/tasks/${taskId}/context`),
    request(`/api/tasks/${taskId}/candidates`),
    request(`/api/tasks/${taskId}/audit`),
    request(`/api/tasks/${taskId}/events`),
    request(`/api/tasks/${taskId}/evidence`),
  ]);
  state.task = task;
  state.context = context;
  state.candidates = candidates;
  state.audit = audit;
  state.events = events;
  state.evidence = evidence;
  renderTask();
  renderCandidates();
  renderTrace();
  loadOpsEvidence();
  renderOpsReport();
  renderDailyLedger();
  renderEventsToChat();
}

async function runDemo() {
  try {
    state.activeScenario = null;
    state.approval = null;
    state.run = await request("/api/demo/run", { method: "POST" });
    await refreshTask(state.run.task_id);
    toast(state.language === "zh" ? "场景已创建，Candidate B 等待人工审批。" : "Scenario created. Candidate B is awaiting human approval.");
  } catch (error) {
    toast(error.message);
  }
}

async function approveCandidateB() {
  if (!state.run || !state.context) return;
  try {
    state.approval = await request(`/api/tasks/${state.run.task_id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        candidate_id: "Candidate-B",
        task_version: state.context.task_version,
        context_hash: state.context.context_hash,
        approver: "Human Operator",
        reason: "Candidate B passed independent audit and remains bound to the current context hash.",
      }),
    });
    await refreshTask(state.run.task_id);
    toast(state.language === "zh" ? "Candidate B 已审批。" : "Candidate B approved.");
  } catch (error) {
    toast(error.message);
  }
}

async function executeCandidateB() {
  if (!state.run || !state.context) return;
  try {
    await request(`/api/tasks/${state.run.task_id}/execute`, {
      method: "POST",
      body: JSON.stringify({
        candidate_id: "Candidate-B",
        task_version: state.context.task_version,
        context_hash: state.context.context_hash,
        idempotency_key: "IDEMP-TASK-014-B-NORMAL",
      }),
    });
    await refreshTask(state.run.task_id);
    toast(state.language === "zh" ? "执行已验证，证据已封存。" : "Execution verified. Evidence sealed.");
  } catch (error) {
    toast(error.message);
  }
}

async function runRollback() {
  try {
    state.activeScenario = null;
    state.approval = null;
    state.run = await request("/api/demo/run-rollback", { method: "POST" });
    await refreshTask(state.run.task_id);
    toast(state.language === "zh" ? "回滚场景已完成。" : "Rollback scenario completed.");
  } catch (error) {
    toast(error.message);
  }
}

async function openEvidence() {
  if (!state.task) return;
  state.evidence = await request(`/api/tasks/${state.task.task_id}/evidence`);
  $("#evidence-json").textContent = JSON.stringify(state.evidence, null, 2);
  $("#evidence-dialog").showModal();
}

function openTraceDetail(index) {
  const event = state.events[index];
  if (!event) return;
  $("#trace-dialog-title").textContent = event.event_id;
  $("#trace-json").textContent = JSON.stringify(event, null, 2);
  $("#trace-dialog").showModal();
}

function openCandidateDetail(candidateId) {
  const candidate = state.candidates.find((item) => item.candidate_id === candidateId);
  const verdict = state.audit.find((item) => item.candidate_id === candidateId);
  if (!candidate) return;
  $("#candidate-dialog-title").textContent = `${candidate.candidate_id} · ${candidate.name}`;
  $("#candidate-json").textContent = JSON.stringify({ candidate, audit_verdict: verdict || null }, null, 2);
  $("#candidate-dialog").showModal();
}

function reviewCandidates() {
  $("#candidate-list").scrollIntoView({ behavior: "smooth", block: "center" });
}

function openTodayLedger() {
  setWorkspaceMode("nav-workspace");
  scrollWithin($("#nav-workspace"), ".cost-compare");
  renderDailyLedger();
}

async function openWorkspaceFromHistory(kind) {
  const thread = historyThreads[kind] || historyThreads.weather;
  state.activeHistory = kind;
  state.activeScenario = null;
  state.selectedAgent = thread.agentId;
  setWorkspaceMode("nav-workspace");
  $$(".history-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.openWorkspace === kind);
  });
  renderSelectedAgent();
  renderThreadMessages(kind);
  if (thread.taskId) {
    try {
      await refreshTask(thread.taskId);
      state.run = {
        task_id: state.task.task_id,
        task_version: state.task.task_version,
        trace_id: state.task.trace_id,
        state: state.task.state,
        context_id: state.context.context_id,
        context_hash: state.context.context_hash,
      };
    } catch (error) {
      toast(error.message);
    }
  }
  $("#ai-chat-input").focus();
}

function setupCampus() {
  const canvas = $("#campus-3d");
  if (!canvas) return;
  state.campus3d = createCampus3D(canvas, updateAssetLabels);
  renderCampusSimulation();
  $("#reset-camera").addEventListener("click", () => {
    state.campus3d?.reset?.();
  });
  $("#campus-edit-layout")?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    const active = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.textContent = active ? "完成布局" : "编辑布局";
    state.campus3d?.setEditMode?.(active);
  });
  $$(".campus-add").forEach((button) => {
    button.addEventListener("click", () => {
      state.campus3d?.addModule?.(button.dataset.campusAdd);
    });
  });
  $("#campus-delete").addEventListener("click", () => {
    state.campus3d?.deleteSelected?.();
  });
}

async function restoreLatestDemo() {
  state.run = null;
  state.task = null;
  state.context = null;
  state.candidates = [];
  state.audit = [];
  state.events = [];
  state.evidence = null;
  renderTask();
  renderCandidates();
  renderTrace();
  renderOpsReport();
}

async function restoreEnergyDataConnection() {
  try {
    state.energySnapshot = await request("/api/data/snapshot/current");
    state.monitor = await request("/api/monitor/status");
    state.chartTick = state.monitor?.cursor ?? state.energySnapshot.current_interval ?? state.chartTick;
    if (state.monitor?.task_id && state.energySnapshot) await loadMonitorTask(state.monitor.task_id);
    renderMonitor();
    applySnapshotToCampus();
  } catch {
    applySnapshotToCampus();
  }
}

function renderMonitor() {
  const monitor = state.monitor;
  if (!monitor) return;
  $("#monitor-state").textContent = monitor.running ? "READING" : "STOPPED";
  $("#monitor-plan").textContent = monitor.plan_version || "V1";
  $("#monitor-agents").textContent = monitor.agentteams_awake ? "AWAKE" : "SLEEPING";
  $("#monitor-interval").textContent = `${String(monitor.cursor).padStart(2, "0")} / 95`;
  $("#monitor-pulse").className = monitor.agentteams_awake ? "alert" : monitor.running ? "live" : "";
  const current = monitor.current;
  $("#monitor-source-note").textContent = current
    ? `Load ${Number(current.load_kw).toFixed(2)} kW · PV ${Number(current.pv_kw).toFixed(2)} kW · SOC ${(Number(current.battery_soc) * 100).toFixed(0)}%`
    : "真实 PV / Load / SOC / Grid · 15分钟 Snapshot";
  const lifecycleKinds = new Set(["V1_INVALIDATED", "AGENTTEAMS_WOKEN", "V2_REPLANNED_AND_AUDITED"]);
  const lifecycle = (monitor.events || []).filter((event) => lifecycleKinds.has(event.kind));
  const recent = (monitor.events || []).filter((event) => !lifecycleKinds.has(event.kind)).slice(-3);
  const visibleEvents = [...lifecycle, ...recent].slice(-7).reverse();
  $("#monitor-event-list").innerHTML = visibleEvents.map((event) => `
    <p><strong>${escapeHTML(event.kind)}</strong> · ${escapeHTML(event.detail)}</p>
  `).join("") || "<p>Monitor 持续读取；异常前不调用 LLM。</p>";
  const approved = Boolean(state.task?.approval?.approved);
  $("#monitor-approve").disabled = !monitor.task_id || approved || state.task?.state !== "AWAITING_APPROVAL";
  $("#monitor-execute").disabled = !approved || Boolean(state.task?.execution_summary);
  $("#monitor-evidence").disabled = !state.task?.evidence_sha256;
  // Rolling reoptimize: enabled when a task exists with selected plan and monitor is running
  $("#monitor-rolling").disabled = !monitor.task_id || !state.task?.selected_plan_id || !monitor.running;

  applySnapshotToCampus();
}

function renderParallel() {
  const p = state.parallel;
  if (!p) return;
  $("#monitor-state").textContent = p.running ? "RUNNING" : "STOPPED";
  $("#monitor-plan").textContent = "PARALLEL";
  $("#monitor-agents").textContent = p.agentteams_active ? "AWAKE" : "SLEEPING";
  $("#monitor-interval").textContent = `${String(p.cursor).padStart(2, "0")} / 95`;
  $("#monitor-pulse").className = p.agentteams_active ? "live" : p.running ? "alert" : "";

  const baselineCost = (p.baseline_cost_yuan ?? p.baseline_cumulative_cost_yuan ?? 0);
  const optimizedCost = adjustedOptimizedCost(p);
  const savingsYuan = (p.savings_yuan ?? (baselineCost - optimizedCost) ?? 0);
  const savingsPct = (p.savings_percent ?? (baselineCost > 0 ? (savingsYuan / baselineCost * 100) : 0) ?? 0);
  $("#cost-baseline").textContent = `¥${baselineCost.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#cost-optimized").textContent = `¥${optimizedCost.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#cost-savings").textContent = `¥${savingsYuan.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
  $("#savings-percent").textContent = `节省 ${savingsPct.toFixed ? savingsPct.toFixed(2) : savingsPct}%`;
  $("#parallel-status").textContent = p.last_event || p.event || "";

  // Deviation metrics
  const lastPoint = p.interval_history?.[p.interval_history.length - 1];
  $("#deviation-pv").textContent = lastPoint ? `${(lastPoint.pv_deviation_percent ?? 0).toFixed(1)}%` : "--%";
  $("#deviation-load").textContent = lastPoint ? `${(lastPoint.load_deviation_percent ?? 0).toFixed(1)}%` : "--%";
  $("#reopt-count").textContent = `${p.total_reoptimizations || 0} 次`;
  const lastReopt = p.reoptimization_events?.[p.reoptimization_events.length - 1];
  $("#reopt-reason").textContent = lastReopt ? (lastReopt.reason || "").substring(0, 30) + "..." : "--";

  const curLoad = p.current_load_kw ?? lastPoint?.actual_load_kw ?? 0;
  const curPv = p.current_pv_kw ?? lastPoint?.actual_pv_kw ?? 0;
  const curSoc = p.current_soc ?? (lastPoint?.actual_soc ?? 0);
  $("#monitor-source-note").textContent = `Load ${(curLoad).toFixed(2)} kW · PV ${(curPv).toFixed(2)} kW · SOC ${((curSoc) * 100).toFixed(0)}%`;
  $("#monitor-approve").disabled = true;
  $("#monitor-execute").disabled = true;
  $("#monitor-evidence").disabled = true;
  $("#monitor-rolling").disabled = true;

  drawCostChart(p);
  drawPowerChart(p);
  renderDailyLedger();
}

function firstReoptInterval(p) {
  const intervals = (p?.reoptimization_events || [])
    .map((event) => Number(event.interval))
    .filter((value) => Number.isFinite(value));
  return intervals.length ? Math.min(...intervals) : null;
}

function adjustedOptimizedAt(point, reoptStart) {
  const baseline = point.baseline_cumulative_cost_yuan ?? 0;
  if (reoptStart == null || Number(point.interval ?? 0) < reoptStart) return baseline;
  return point.optimized_cumulative_cost_yuan ?? baseline;
}

function adjustedOptimizedCost(p) {
  const history = p?.interval_history || [];
  if (!history.length) return p?.optimized_cost_yuan ?? p?.optimized_cumulative_cost_yuan ?? 0;
  const reoptStart = firstReoptInterval(p);
  const last = history[history.length - 1];
  return adjustedOptimizedAt(last, reoptStart);
}

function drawCostChart(p) {
  const canvas = $("#cost-chart");
  if (!canvas || !p?.interval_history?.length) return;
  const { context, width, height } = resizeCanvas(canvas);
  const history = p.interval_history;
  const reoptEvents = p.reoptimization_events || [];

  const inset = { left: 50, top: 16, right: 16, bottom: 28 };
  const plotW = width - inset.left - inset.right;
  const plotH = height - inset.top - inset.bottom;

  // Background
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);

  // Find max cost for scaling
  const maxCost = Math.max(
    ...history.map((h) => h.baseline_cumulative_cost_yuan ?? 0),
    ...history.map((h) => adjustedOptimizedAt(h, firstReoptInterval(p))),
    0.01,
  );

  const count = history.length;
  const totalIntervals = 96;
  const reoptStart = firstReoptInterval(p);

  // Grid lines
  context.strokeStyle = "rgba(148, 163, 184, .2)";
  context.lineWidth = 1;
  for (let row = 0; row <= 4; row++) {
    const y = inset.top + (plotH * row) / 4;
    context.beginPath(); context.moveTo(inset.left, y); context.lineTo(width - inset.right, y); context.stroke();
  }
  for (let col = 0; col <= 4; col++) {
    const x = inset.left + (plotW * col) / 4;
    context.beginPath(); context.moveTo(x, inset.top); context.lineTo(x, height - inset.bottom); context.stroke();
  }

  // Helper: map interval to x
  function xAt(i) { return inset.left + (plotW * i) / (totalIntervals - 1); }
  function yAt(cost) { return inset.top + plotH * (1 - cost / maxCost); }

  // Draw savings area (between curves)
  context.fillStyle = "rgba(127, 197, 139, .18)";
  context.beginPath();
  context.moveTo(xAt(0), yAt((history[0].baseline_cumulative_cost_yuan ?? 0)));
  for (let i = 0; i < count; i++) {
    context.lineTo(xAt(history[i].interval ?? i), yAt((history[i].baseline_cumulative_cost_yuan ?? 0)));
  }
  for (let i = count - 1; i >= 0; i--) {
    context.lineTo(xAt(history[i].interval ?? i), yAt(adjustedOptimizedAt(history[i], reoptStart)));
  }
  context.closePath();
  context.fill();

  // Baseline curve (red)
  context.beginPath();
  context.strokeStyle = "#e07c78";
  context.lineWidth = 2;
  for (let i = 0; i < count; i++) {
    const x = xAt(history[i].interval ?? i);
    const y = yAt((history[i].baseline_cumulative_cost_yuan ?? 0));
    if (i === 0) context.moveTo(x, y); else context.lineTo(x, y);
  }
  context.stroke();

  // Optimized curve (green)
  context.beginPath();
  context.strokeStyle = "#7fc58b";
  context.lineWidth = 2;
  for (let i = 0; i < count; i++) {
    const x = xAt(history[i].interval ?? i);
    const y = yAt(adjustedOptimizedAt(history[i], reoptStart));
    if (i === 0) context.moveTo(x, y); else context.lineTo(x, y);
  }
  context.stroke();

  // Re-optimization markers (yellow diamonds)
  reoptEvents.forEach((event) => {
    const point = history.find((h) => (h.interval ?? -1) === (event.interval ?? -1));
    if (!point) return;
    const x = xAt(event.interval ?? 0);
    const y = yAt((point.optimized_cumulative_cost_yuan ?? 0));
    context.fillStyle = "#d2a457";
    context.beginPath();
    context.moveTo(x, y - 5); context.lineTo(x + 5, y); context.lineTo(x, y + 5); context.lineTo(x - 5, y);
    context.closePath(); context.fill();
  });

  // Y-axis labels
  context.fillStyle = "#6b7280";
  context.font = "10px Inter, sans-serif";
  context.textAlign = "right";
  for (let row = 0; row <= 4; row++) {
    const cost = (maxCost * (4 - row)) / 4;
    const y = inset.top + (plotH * row) / 4;
    context.fillText(`¥${cost.toFixed(1)}`, inset.left - 6, y + 3);
  }

  // X-axis labels (time)
  context.textAlign = "center";
  const times = ["00:00", "06:00", "12:00", "18:00", "24:00"];
  const timeIndices = [0, 24, 48, 72, 95];
  for (let i = 0; i < times.length; i++) {
    const x = xAt(timeIndices[i]);
    context.fillText(times[i], x, height - inset.bottom + 14);
  }

  // Current cursor line
  if (p.cursor > 0 && p.cursor < totalIntervals) {
    const cx = xAt(p.cursor);
    context.strokeStyle = "rgba(43, 191, 208, .34)";
    context.setLineDash([3, 3]);
    context.beginPath(); context.moveTo(cx, inset.top); context.lineTo(cx, height - inset.bottom); context.stroke();
    context.setLineDash([]);
  }
}

function drawPowerChart(p) {
  const canvas = $("#power-chart");
  if (!canvas || !p?.interval_history?.length) return;
  const { context, width, height } = resizeCanvas(canvas);
  const h = p.interval_history;
  const inset = { left: 48, top: 14, right: 14, bottom: 26 };
  const pw = width - inset.left - inset.right;
  const ph = height - inset.top - inset.bottom;
  context.fillStyle = "#ffffff"; context.fillRect(0, 0, width, height);
  const maxP = Math.max(0.01, ...h.map(x => Math.max(x.actual_load_kw || 0, x.actual_pv_kw || 0, x.actual_grid_kw || 0, x.optimized_grid_kw || 0)));
  const xAt = i => inset.left + pw * i / 95;
  const yAt = v => inset.top + ph * (1 - v / maxP);
  // grid
  context.strokeStyle = "rgba(148, 163, 184, .2)";
  for (let r = 0; r <= 4; r++) {
    const y = inset.top + ph * r / 4;
    context.beginPath(); context.moveTo(inset.left, y); context.lineTo(width - inset.right, y); context.stroke();
  }
  function drawLine(arr, key, col) {
    context.beginPath(); context.strokeStyle = col; context.lineWidth = 2;
    for (let i = 0; i < arr.length; i++) {
      const x = xAt(arr[i].interval ?? i); const y = yAt(arr[i][key] || 0);
      if (i === 0) context.moveTo(x, y); else context.lineTo(x, y);
    }
    context.stroke();
  }
  drawLine(h, "actual_load_kw", "#ff5555");
  drawLine(h, "actual_pv_kw", "#ffdd33");
  drawLine(h, "actual_grid_kw", "#ff8822");
  // axes
  context.fillStyle = "#6b7280"; context.font = "10px Inter, sans-serif"; context.textAlign = "right";
  for (let r = 0; r <= 4; r++) context.fillText(`${(maxP * (4 - r) / 4).toFixed(1)}`, inset.left - 6, inset.top + ph * r / 4 + 3);
  context.textAlign = "center";
  const times = ["00:00", "06:00", "12:00", "18:00", "24:00"];
  const idxs = [0, 24, 48, 72, 95];
  for (let i = 0; i < times.length; i++) context.fillText(times[i], xAt(idxs[i]), height - inset.bottom + 14);
  // cursor line
  if (p.cursor > 0 && p.cursor < 96) {
    const cx = xAt(p.cursor); context.strokeStyle = "rgba(43, 191, 208, .34)"; context.setLineDash([3, 3]);
    context.beginPath(); context.moveTo(cx, inset.top); context.lineTo(cx, height - inset.bottom); context.stroke(); context.setLineDash([]);
  }
  loadOpsEvidence();
}

function ensureDayGroup(dateKey, subtitle = "园区日调度") {
  const board = $(".insight-board");
  if (!board) return null;
  let group = board.querySelector(`[data-day-group="${dateKey}"]`);
  if (group) return group;
  group = document.createElement("section");
  group.className = "day-group";
  group.dataset.dayGroup = dateKey;
  group.innerHTML = `
    <header>
      <div><strong>${escapeHTML(dateKey)}</strong><span>${escapeHTML(subtitle)}</span></div>
      <small>运行记录</small>
    </header>`;
  board.prepend(group);
  return group;
}

function historyCardMarkup(title, dateStr, description) {
  return `
    <div class="history-body">
      <div class="history-tags"><span class="tag">已完成</span><span>Trace ready</span></div>
      <h2>${escapeHTML(title)}</h2>
      <time>${escapeHTML(dateStr)}</time>
      <p>${escapeHTML(description)}</p>
      <div class="history-metrics">
        <span>96 intervals</span>
        <span>Evidence linked</span>
        <span>Replay ready</span>
      </div>
    </div>`;
}

async function loadMonitorTask(taskId) {
  const task = await request(`/api/tasks/${taskId}`);
  state.task = task;
  state.run = { task_id: task.task_id, task_version: task.task_version, state: task.state };
  state.context = { context_hash: task.context_hash || "opencem-snapshot-contract" };
  state.approval = task.approval;
  state.candidates = task.plans.map((plan) => ({
    candidate_id: plan.plan_id,
    name: plan.profile,
    cost_yuan: plan.metrics.total_cost_yuan,
    max_power_kw: plan.metrics.peak_grid_kw,
    soc_min_percent: Math.round(Math.min(...plan.points.map((point) => point.soc_end)) * 100),
    soc_max_percent: Math.round(Math.max(...plan.points.map((point) => point.soc_end)) * 100),
    transformer_load_percent: Math.round(plan.metrics.peak_grid_kw / task.scenario_snapshot.site.transformer_capacity_kw * 1000) / 10,
  }));
  state.audit = task.audits.map((audit) => ({
    candidate_id: audit.plan_id,
    verdict: audit.decision === "rejected" ? "rejected" : "audit_approved",
    reason: audit.findings.map((item) => item.message).join("; ") || `Independent checks passed; improvement ¥${audit.improvement_yuan.toFixed(2)}`,
  }));
  state.events = task.trace.map((event) => ({
    timestamp: event.timestamp,
    actor: event.actor,
    reason: event.action,
    to_state: event.status === "blocked" ? "FAILED" : task.state,
    detail: event.detail,
  }));
  renderTask();
  renderCandidates();
  renderTrace();
  applySnapshotToCampus();
}

function formatParallelTrace(t) {
  const step = t.step || "";
  const interval = t.interval != null ? `时段 ${t.interval}` : "";
  if (step === "optimization_complete") return `✅ Agent Teams 初始优化完成 · 方案 ${(t.plan_id || "").slice(-6)} · 状态 ${t.state}`;
  if (step === "optimization_failed") return `❌ 初始优化失败: ${t.error || ""}`;
  if (step === "perception_observation") {
    const lines = [
      `📡 ${interval} · 感知 Agent 数据校验`,
      `   PV 实际=${t.pv_actual}kW 预测=${t.pv_forecast}kW 偏差=${t.pv_deviation_percent}%`,
      `   负荷 实际=${t.load_actual}kW 预测=${t.load_forecast}kW 偏差=${t.load_deviation_percent}%`,
      `   SOC=${t.soc_actual}% 计划=${t.soc_plan != null ? t.soc_plan + "%" : "--"}`,
    ];
    if (t.status === "normal") {
      lines.push(`   ✅ 所有指标在阈值范围内，现在不需要重新制定计划`);
    } else {
      lines.push(`   ⚠️ 检测到数据异常：${(t.reasons || []).join("；")}`);
      lines.push(`   🔄 现在要重新计划！触发调度 Worker 重新优化...`);
    }
    return lines.join("\n");
  }
  if (step === "interval_dispatch") {
    const lines = [
      `📊 ${interval} · Agent 调度决策`,
      `   负荷 ${t.load_kw}kW · 光伏 ${t.pv_kw}kW`,
    ];
    if (t.optimized_discharge_kw > 0.01) lines.push(`   🔋 储能放电 ${t.optimized_discharge_kw.toFixed(2)}kW → 电网购电 ${t.optimized_grid_kw.toFixed(2)}kW`);
    else if (t.optimized_charge_kw > 0.01) lines.push(`   ⚡ 光伏余电充电 ${t.optimized_charge_kw.toFixed(2)}kW → 电网购电 ${t.optimized_grid_kw.toFixed(2)}kW`);
    else lines.push(`   🔌 电网购电 ${t.optimized_grid_kw.toFixed(2)}kW`);
    lines.push(`   SOC ${(t.soc_start * 100).toFixed(1)}% → ${(t.soc_end * 100).toFixed(1)}%`);
    lines.push(`   基线成本 ¥${t.baseline_cost.toFixed(4)} · 优化成本 ¥${t.optimized_cost.toFixed(4)}`);
    return lines.join("\n");
  }
  if (step === "plan_invalidated_and_reoptimized") return `🔄 ${interval} · 旧方案已废止\n   原因: ${(t.reasons || []).join("；")}\n   新方案: ${(t.new_plan_id || "").slice(-6)} · Agent: ${(t.agents || []).join(" → ")}`;
  if (step === "dispatch_reoptimization_complete") return `✅ ${interval} · 调度 Worker 重新优化完成\n   新方案已部署: ${(t.new_plan_id || "").slice(-6)}`;
  if (step === "reoptimize_failed") return `⚠️ ${interval} · 重优化失败: ${t.error || ""}`;
  if (step === "plan_invalidated") return `⛔ ${interval} · 旧方案已废止`;
  return `· ${step}${interval ? " · " + interval : ""}`;
}

let pollRetryCount = 0;
const MAX_POLL_RETRIES = 5;

async function pollParallelStep() {
  try {
    state.parallel = await request("/api/parallel/step", { method: "POST" });
    pollRetryCount = 0;
    state.chartTick = state.parallel.cursor;
    try { renderParallel(); } catch (e) { console.error("renderParallel error:", e); }
    try { applySnapshotToCampus(); } catch (e) { console.error("applySnapshotToCampus error:", e); }
    // Limit left chat messages to avoid DOM bloat causing browser lag
    const chatContainer = $("#chat-messages");
    while (chatContainer && chatContainer.children.length > 40) {
      chatContainer.removeChild(chatContainer.firstChild);
    }
    const traces = state.parallel?.agentteams_trace || [];
    const cursor = state.parallelTraceCursor || 0;
    for (let i = cursor; i < traces.length; i++) {
      try { appendRuntimeStatusMessage("team_leader", formatParallelTrace(traces[i])); } catch (e) {}
    }
    state.parallelTraceCursor = traces.length;
    try { localStorage.setItem("energymesh.parallelState", JSON.stringify(state.parallel)); } catch(e) {}
    if (!state.parallel.running && state.parallelTimer) {
      window.clearInterval(state.parallelTimer);
      state.parallelTimer = null;
      toast("平行对比完成；Agent Teams 决策已跑完全天");
      saveParallelHistory();
    }
  } catch (error) {
    pollRetryCount++;
    console.error("pollParallelStep failed (retry " + pollRetryCount + "/" + MAX_POLL_RETRIES + "):", error);
    if (pollRetryCount >= MAX_POLL_RETRIES && state.parallelTimer) {
      window.clearInterval(state.parallelTimer);
      state.parallelTimer = null;
      toast("轮询连续失败 " + MAX_POLL_RETRIES + " 次，已停止。请刷新后重新上传 CSV。");
    }
  }
}

function saveParallelHistory() {
  const thread = state.agentThreads["team_leader"];
  if (!thread || thread.length < 3) return;
  const key = "parallel_" + new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const messages = thread.filter(m => !m.intro).map(m => ({ role: m.role, text: m.text, agentId: m.agentId || "team_leader" }));
  if (messages.length < 3) return;
  historyThreads[key] = {
    agentId: "team_leader",
    en: { opener: "View parallel simulation", messages },
    zh: { opener: "查看平行时空对比", messages },
  };
  const board = $(".insight-board");
  if (board && !board.querySelector(`[data-open-workspace="${key}"]`)) {
    const card = document.createElement("article");
    card.className = "history-card";
    card.dataset.openWorkspace = key;
    const now = new Date();
    const dayKey = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
    const dateStr = `${dayKey} ${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}`;
    card.innerHTML = historyCardMarkup("平行时空对比 · 全天 Agent 决策", dateStr, "96 个时段完整调度记录，Agent Teams 感知→调度→审核→执行闭环。");
    ensureDayGroup(dayKey)?.append(card);
    card.addEventListener("click", () => openWorkspaceFromHistory(key));
  }
  try {
    const saved = JSON.parse(localStorage.getItem("energymesh.parallelHistory") || "[]");
    if (!saved.some(s => s.key === key)) {
      saved.push({ key, date: Date.now(), messages });
      localStorage.setItem("energymesh.parallelHistory", JSON.stringify(saved));
    }
  } catch(e) {}
}

function restoreParallelHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem("energymesh.parallelHistory") || "[]");
    for (const item of saved) {
      if (historyThreads[item.key]) continue;
      historyThreads[item.key] = {
        agentId: "team_leader",
        en: { opener: "View parallel simulation", messages: item.messages },
        zh: { opener: "查看平行时空对比", messages: item.messages },
      };
      const board = $(".insight-board");
      if (board && !board.querySelector(`[data-open-workspace="${item.key}"]`)) {
        const card = document.createElement("article");
        card.className = "history-card";
        card.dataset.openWorkspace = item.key;
        const d = new Date(item.date);
        const dayKey = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
        const dateStr = `${dayKey} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
        card.innerHTML = historyCardMarkup("平行时空对比 · 全天 Agent 决策", dateStr, "96 个时段完整调度记录，Agent Teams 感知→调度→审核→执行闭环。");
        ensureDayGroup(dayKey)?.append(card);
        card.addEventListener("click", () => openWorkspaceFromHistory(item.key));
      }
    }
  } catch(e) {}
}

async function startParallelSimulation() {
  try {
    if (state.parallelTimer) window.clearInterval(state.parallelTimer);
    state.activeScenario = null;
    state.task = null;
    state.approval = null;
    // Start parallel simulation: runs full AgentTeams workflow once, then steps
    state.parallel = await request("/api/parallel/start", { method: "POST" });
    state.energySnapshot = await request("/api/data/snapshot/current");
    state.parallelTraceCursor = 0;
    renderParallel();
    applySnapshotToCampus();
    const interval = state.speedMode === "normal" ? 15000 : 800;
    state.parallelTimer = window.setInterval(pollParallelStep, interval);
    toast(state.speedMode === "normal" ? "平行对比开始：实时流速（15秒/步）" : "平行对比开始：快速流速（0.8秒/步）");
  } catch (error) {
    toast(error.message);
  }
}

async function uploadEnergyCsv(file) {
  if (!file) return;
  try {
    const response = await fetch(`/api/data/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: await file.arrayBuffer(),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "CSV upload failed");
    state.energySnapshot = body;
    state.replayMode = window.localStorage.getItem("energymesh.replayMode") || "real";
    state.replayCursor = body.current_interval || 0;
    applySnapshotToCampus();
    startCampusReplay({ reset: true });
    renderDailyLedger();
    setConnectorStatus(
      `历史数据已上传：${body.environment_signals.raw_rows} 条测量已归一化，右侧园区已开始按所选速度回放`,
      [{ kind: "TEST_DATA_RUNNING", detail: "CSV 已成为当前 world_state；滑块可选择时段，速度可选真实 24h/演示/快速。" }],
    );
    toast("历史数据已上传，园区开始按 96 时段流动");
  } catch (error) {
    toast(error.message);
  }
}

function setConnectorStatus(text, events = []) {
  const sourceNote = $("#monitor-source-note");
  const eventList = $("#monitor-event-list");
  if (sourceNote) sourceNote.textContent = text;
  if (eventList) {
    eventList.innerHTML = events.length
      ? events.map((event) => `<p><strong>${escapeHTML(event.kind)}</strong> · ${escapeHTML(event.detail)}</p>`).join("")
      : `<p>${escapeHTML(text)}</p>`;
  }
}

async function testDemoDataConnection() {
  try {
    const snapshot = await request("/api/data/snapshot/current");
    state.energySnapshot = snapshot;
    state.replayCursor = snapshot.current_interval || 0;
    setConnectorStatus(
      `测试数据连接成功：${snapshot.source}，${snapshot.telemetry.length} 个 15 分钟时段`,
      [{ kind: "TEST_DATA_CONNECTED", detail: "历史 CSV 已归一化，右侧园区开始全天用电回放。" }],
    );
    applySnapshotToCampus();
    startCampusReplay({ reset: true });
    renderDailyLedger();
    toast("测试数据连接成功，开始全天运行");
    $("#connector-dialog").close();
    await startParallelSimulation();
  } catch {
    setConnectorStatus(
      "测试数据未连接：请先上传历史 CSV",
      [{ kind: "TEST_DATA_MISSING", detail: "没有可用的历史测试数据，无法校验 96 个时段。" }],
    );
    toast("请先上传历史 CSV");
  }
}

async function testLiveDataConnection() {
  try {
    const monitor = await request("/api/monitor/status");
    state.monitor = monitor;
    if (monitor.current) {
      setConnectorStatus(
        `真实园区连接成功：Load ${Number(monitor.current.load_kw).toFixed(2)} kW · PV ${Number(monitor.current.pv_kw).toFixed(2)} kW · SOC ${(Number(monitor.current.battery_soc) * 100).toFixed(0)}%`,
        [{ kind: "LIVE_DATA_CONNECTED", detail: "Monitor 当前有实时/回放遥测，AI 可读取同一份园区状态。" }],
      );
      toast("真实园区连接成功");
      renderMonitor();
      applySnapshotToCampus();
      return;
    }
    setConnectorStatus(
      "真实园区未连接：当前没有 EMS/BMS/PCS 实时遥测",
      [{ kind: "LIVE_DATA_MISSING", detail: "生产环境需要配置园区适配器；演示可先上传历史 CSV。" }],
    );
    toast("真实园区未连接");
  } catch (error) {
    setConnectorStatus(
      "真实园区连接失败：请检查适配器或后端服务",
      [{ kind: "LIVE_DATA_ERROR", detail: error.message || "monitor/status 请求失败。" }],
    );
    toast("真实园区连接失败");
  }
}

async function approveMonitorPlan() {
  if (!state.monitor?.task_id) return;
  try {
    state.task = await request(`/api/tasks/${state.monitor.task_id}/approval-only`, {
      method: "POST",
      body: JSON.stringify({
        approved: true,
        approver: "Human Operator",
        reason: "OpenCEM V2 passed independent audit; approve current Snapshot-bound plan.",
      }),
    });
    state.approval = state.task.approval;
    if (state.flowPreview) ledgerRecord("adopted", state.flowPreview.currentFlow, state.flowPreview.previewFlow);
    clearCampusPlanPreview(true);
    renderTask();
    renderMonitor();
    toast("已采用 Agent 新方案，园区电流切换到优化流向");
  } catch (error) {
    toast(error.message);
  }
}

async function executeMonitorPlan() {
  if (!state.monitor?.task_id) return;
  try {
    state.task = await request(`/api/tasks/${state.monitor.task_id}/execute-approved`, { method: "POST" });
    state.approval = state.task.approval;
    clearCampusPlanPreview(true);
    state.monitor = await request("/api/monitor/status");
    await loadMonitorTask(state.task.task_id);
    renderMonitor();
    toast(state.task.state === "ROLLBACK" ? "偏差超限，已安全回滚" : "V2 模拟执行完成，证据已封存");
  } catch (error) {
    toast(error.message);
  }
}

async function adoptFlowPlan() {
  const preview = state.flowPreview;
  if (preview) ledgerRecord("adopted", preview.currentFlow, preview.previewFlow);
  clearCampusPlanPreview(true);
  if (state.monitor?.task_id && state.task?.state === "AWAITING_APPROVAL" && !state.approval) {
    await approveMonitorPlan();
    return;
  }
  if (state.task?.state === "AWAITING_APPROVAL") {
    state.approval = { approved: true, approver: "Human Operator", reason: "用户采用 Agent 新能源流方案" };
    state.task = { ...state.task, approval: state.approval };
    renderTask();
  }
  toast("已采用方案：虚线预览变为实时电流，限发和购电下降");
}

function rejectFlowPlan() {
  const preview = state.flowPreview;
  if (preview) ledgerRecord("rejected", preview.currentFlow, preview.previewFlow);
  clearCampusPlanPreview(false);
  toast("已拒绝方案：园区保持当前电流方式");
}

async function rollingReoptimizeMonitor() {
  if (!state.monitor?.task_id) return;
  const taskId = state.monitor.task_id;
  const cursor = state.monitor?.cursor ?? 0;
  const point = state.energySnapshot?.telemetry?.[cursor];
  const actualSoc = point ? point.battery_soc : 0.55;
  toast("正在对剩余时段做滚动时域鲁棒重优化...");
  try {
    state.task = await request(`/api/tasks/${taskId}/rolling-reoptimize`, {
      method: "POST",
      body: JSON.stringify({
        current_interval: cursor,
        actual_soc: actualSoc,
        robustness_mode: "worst_case",
        trigger: "monitor_rolling_reoptimize",
      }),
    });
    state.approval = state.task.approval;
    state.monitor = await request("/api/monitor/status");
    await loadMonitorTask(taskId);
    renderMonitor();
    const mode = state.language === "zh" ? "worst_case 鲁棒模式" : "worst_case robust mode";
    toast(`滚动重优化完成 → V${state.task.task_version}；${mode}`);
  } catch (error) {
    toast(error.message);
  }
}

function setupEvents() {
  $("#run-button")?.addEventListener("click", runDemo);
  $("#approve-b")?.addEventListener("click", approveCandidateB);
  $("#execute-b")?.addEventListener("click", executeCandidateB);
  $("#rollback-button")?.addEventListener("click", runRollback);
  $("#upload-energy-data").addEventListener("click", () => $("#energy-csv-file").click());
  $("#energy-csv-file").addEventListener("change", (event) => uploadEnergyCsv(event.target.files?.[0]));
  $("#test-demo-data").addEventListener("click", testDemoDataConnection);
  $("#test-live-data").addEventListener("click", testLiveDataConnection);
  $("#connect-energy-source").addEventListener("click", async () => {
    setConnectorStatus("正在测试真实园区数据连接...", [{ kind: "CONNECTING", detail: "检查 Monitor 当前是否有 EMS/BMS/PCS 遥测。" }]);
    try {
      const resp = await request("/api/monitor/status");
      state.monitor = resp;
      if (resp?.running) {
        setConnectorStatus("真实园区数据连接成功", [{ kind: "LIVE_DATA_CONNECTED", detail: "Monitor 正在读取数据流。" }]);
        toast("真实园区数据连接成功");
      } else {
        setConnectorStatus("真实园区没有运行中的数据流，可先上传历史数据测试", [{ kind: "LIVE_DATA_IDLE", detail: "Monitor 当前未运行。" }]);
        toast("真实园区未连接");
      }
    } catch {
      setConnectorStatus("真实园区连接失败：生产环境需配置 EMS/BMS/PCS 适配器", [{ kind: "LIVE_DATA_ERROR", detail: "演示模式可使用历史回放。" }]);
      toast("真实园区连接失败");
    }
  });
  $("#replay-slider")?.addEventListener("input", (event) => {
    state.replayMode = "pause";
    window.localStorage.setItem("energymesh.replayMode", state.replayMode);
    if (state.replayTimer) window.clearInterval(state.replayTimer);
    state.replayTimer = null;
    setReplayCursor(event.currentTarget.value);
  });
  $$("[data-replay-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.replayMode = button.dataset.replayMode || "real";
      window.localStorage.setItem("energymesh.replayMode", state.replayMode);
      startCampusReplay();
    });
  });
  $("#nav-connect").addEventListener("click", () => {
    setWorkspaceMode("nav-connect");
    $("#connector-dialog").showModal();
  });
  $("#monitor-approve").addEventListener("click", approveMonitorPlan);
  $("#monitor-execute").addEventListener("click", executeMonitorPlan);
  $("#monitor-evidence").addEventListener("click", openEvidence);
  $("#monitor-rolling").addEventListener("click", rollingReoptimizeMonitor);
  $("#adopt-flow-plan").addEventListener("click", adoptFlowPlan);
  $("#reject-flow-plan").addEventListener("click", rejectFlowPlan);
  $("#open-evidence").addEventListener("click", openEvidence);
  $("#review-candidates").addEventListener("click", reviewCandidates);
  $("#translate-button").addEventListener("click", toggleLanguage);
  $("#nav-overview").addEventListener("click", openHome);
  $("#nav-workspace").addEventListener("click", openNewWorkspace);
  $("[data-ledger-summary=\"today\"]").addEventListener("click", openTodayLedger);
  $(".workspace-title").addEventListener("click", openNewWorkspace);
  $("#nav-agents").addEventListener("click", () => {
    setWorkspaceMode("nav-agents");
    setOpsDrawer(false);
    setAgentDirectory($("#agent-directory-drawer").hidden);
    setActiveRail("nav-agents");
  });
  $("#nav-ops").addEventListener("click", () => {
    setWorkspaceMode("nav-ops");
    setOpsDrawer($("#ops-drawer").hidden);
  });
  $("#nav-trace").addEventListener("click", () => {
    setWorkspaceMode("nav-trace");
    scrollWithin($("#nav-trace"), "#trace-list");
  });
  $("#nav-chat").addEventListener("click", () => {
    setWorkspaceMode("nav-chat");
    scrollWithin($("#nav-chat"), "#ai-chat-panel");
    $("#ai-chat-input").focus();
  });
  $("#nav-safety").addEventListener("click", () => {
    setWorkspaceMode("nav-safety");
    runRollback();
  });
  $("#agent-directory-close").addEventListener("click", () => setAgentDirectory(false));
  $("#ops-drawer-close").addEventListener("click", () => setOpsDrawer(false));
  $("#active-agent-gateway").addEventListener("click", () => openGateway());
  $("#ai-chat-form").addEventListener("submit", sendChatMessage);
  $$(".directory-chat").forEach((button) => {
    button.addEventListener("click", () => selectAgent(button.closest("[data-agent-id]").dataset.agentId));
  });
  $$(".directory-gateway").forEach((button) => {
    button.addEventListener("click", () => openGateway(button.closest("[data-agent-id]").dataset.agentId));
  });
  $("#gateway-form").addEventListener("submit", saveGateway);
  $("#gateway-test").addEventListener("click", testGatewayConnection);
  $$("[data-station-tab]").forEach((button) => {
    button.addEventListener("click", () => setStationView(button.dataset.stationTab));
  });
  $$("[data-device-id]").forEach((button) => {
    button.addEventListener("click", () => renderDeviceDetail(button.dataset.deviceId));
  });
  $$("[data-signal-mode]").forEach((button) => {
    button.addEventListener("click", () => setDeviceMode(button.dataset.signalMode));
  });
  $$("[data-device-view-mode]").forEach((button) => {
    button.addEventListener("click", () => setDeviceMode(button.dataset.deviceViewMode));
  });
  $("#chat-messages").addEventListener("click", (event) => {
    const confirmButton = event.target.closest("[data-confirm-scenario]");
    if (confirmButton) {
      if (confirmButton.dataset.confirmScenario === "flow_preview") {
        adoptFlowPlan();
        return;
      }
      confirmScenarioExecution();
      return;
    }
    const deferButton = event.target.closest("[data-defer-scenario]");
    if (deferButton) {
      if (deferButton.dataset.deferScenario === "flow_preview") {
        rejectFlowPlan();
        return;
      }
      deferScenarioExecution();
    }
  });
  $$("[data-open-workspace]").forEach((card) => {
    card.addEventListener("click", () => openWorkspaceFromHistory(card.dataset.openWorkspace));
  });
  $$("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => $(`#${button.dataset.closeDialog}`).close());
  });
  window.addEventListener("resize", () => {
    
    drawHomeCharts();
  });
}


drawHomeCharts();
setupCampus();
setupEvents();
renderDeviceDetail("pcs");
loadGateways();
renderSelectedAgent();
applyLanguage(window.localStorage.getItem("energymesh.language") === "zh" ? "zh" : "en");
restoreLatestDemo();
const savedSnapshot = localStorage.getItem("energymesh.savedSnapshot");
if (savedSnapshot) {
  try {
    state.energySnapshot = JSON.parse(savedSnapshot);
    state.replayCursor = state.energySnapshot.current_interval || 0;
    applySnapshotToCampus();
    startCampusReplay();
  } catch(e) {}
}
restoreEnergyDataConnection();
// Restore parallel simulation from localStorage only after CSV/Snapshot exists.
const savedParallel = localStorage.getItem("energymesh.parallelState");
if (savedParallel && state.energySnapshot) {
  try { state.parallel = JSON.parse(savedParallel); renderParallel(); } catch(e) {}
} else if (!state.energySnapshot) {
  localStorage.removeItem("energymesh.parallelState");
}
renderPlanLedger();
renderReplayControl();
restoreAgentTeamsTaskMirror();
// Restore chat history from localStorage
const savedThreads = localStorage.getItem("energymesh.agentThreads");
if (savedThreads) {
  try {
    state.agentThreads = repairSavedAgentThreads(JSON.parse(savedThreads));
    localStorage.setItem("energymesh.agentThreads", JSON.stringify(state.agentThreads));
    renderAgentThread(state.selectedAgent);
  } catch(e) {}
}
restoreParallelHistory();
startLiveCharts();
