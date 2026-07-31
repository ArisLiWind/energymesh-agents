import { createCampus3D } from "/static/campus3d.js?v=20260729a";

const state = {
  run: null,
  task: null,
  context: null,
  candidates: [],
  audit: [],
  events: [],
  evidence: null,
  approval: null,
  selectedAgent: "perception_agent",
  modelConfigs: {},
  playbackIndex: -1,
  playbackTimer: null,
  paused: false,
  campus3d: null,
  avatarSelection: {},
  tutorial: { active: false, step: 0, target: null },
};

const agentInfo = {
  perception_agent: {
    name: "感知 Agent",
    skill: "microgrid_context_ingest",
    avatar: "/static/avatars/perception.svg",
    defaultPrompt: "请基于当前CTX解释你发现了哪些异常，以及为什么V1计划失效。",
  },
  dispatch_agent: {
    name: "调度 Agent",
    skill: "dispatch_plan_generate",
    avatar: "/static/avatars/dispatch.svg",
    defaultPrompt: "请说明三套候选方案的差异，以及为什么你不能批准自己的方案。",
  },
  audit_agent: {
    name: "审核 Agent",
    skill: "dispatch_audit_verify",
    avatar: "/static/avatars/audit.svg",
    defaultPrompt: "请解释Candidate A为什么被否决，并列出你独立复算的硬约束。",
  },
  execution_agent: {
    name: "执行 Agent",
    skill: "execution_mapping",
    avatar: "/static/avatars/execution.svg",
    defaultPrompt: "请说明你只能执行已审核且已审批方案的原因，以及幂等键如何使用。",
  },
};

const agentByActor = {
  "Team Leader": "Team Leader",
  "Perception Agent": "Perception Agent",
  "Dispatch Agent": "Dispatch Agent",
  "Audit Agent": "Audit Agent",
  "Human Approval": "Human Approval",
  "Execution Agent": "Execution Agent",
  Verification: "Verification",
};

const avatarOptions = Object.values(agentInfo).map((agent) => agent.avatar);

const tutorialSteps = [
  {
    event: "run",
    target: "#run-button",
    title: "14:00 复合异常",
    story: "生产负荷增加 420 kW，光伏低于预测 18.6%，变压器温度传感器冲突，同时进入峰值电价。原 EMS 基线不能再直接执行。",
    objective: "创建一次安全重新调度任务",
    action: "点击“运行14:00复合变化”。Team Leader 会创建真实任务，并把它交给感知 Agent。",
  },
  {
    event: "context",
    target: "#view-context",
    title: "理解自动交接的感知快照",
    story: "感知 Agent 已自动将 EMS、BMS、PCS、光伏、生产与传感器质量结果固化为同一个 ContextSnapshot，并使 V1 计划失效。",
    objective: "查看 V2 感知快照",
    action: "点击“查看感知快照”。这不会触发交接，交接已经完成；你是在复核调度、审核、审批和执行共同引用的 context_hash。",
  },
  {
    event: "review",
    target: "#review-candidates",
    title: "审查重新调度候选方案",
    story: "Dispatch Agent 已用 V2 上下文生成经济优先、安全均衡和保供优先三套策略，但它没有批准自己的权限。",
    objective: "进入候选方案审查",
    action: "点击“查看方案”，定位到真实的审核结果。",
  },
  {
    event: "candidate-a",
    target: '[data-candidate-id="Candidate-A"]',
    title: "理解审核门禁",
    story: "Audit Agent 独立重算硬约束。经济优先方案的变压器负载率为 103.8%，超过 95% 安全上限，必须否决。",
    objective: "查看被拒绝的 Candidate A",
    action: "点击 Candidate A，查看它为什么不能进入人工审批。",
  },
  {
    event: "approve",
    target: "#approve-b",
    title: "人工确认安全方案",
    story: "Candidate B 通过了 SOC、PCS、变压器、并网和生产约束。高风险执行仍需由人绑定 task_version 与 context_hash 批准。",
    objective: "批准安全均衡方案",
    action: "点击“批准 Candidate B”。未通过审核的方案不会获得这个入口。",
  },
  {
    event: "execute",
    target: "#execute-b",
    title: "映射模拟执行指令",
    story: "Execution Agent 只能把已经审核并批准的方案映射为幂等模拟指令，不能自行改写目标或跳过门禁。",
    objective: "执行获批方案",
    action: "点击“执行获批方案”，进入确定性验证。",
  },
  {
    event: "evidence",
    target: "#open-evidence",
    title: "封存可审计证据",
    story: "验证完成后，状态迁移、交接、Skill 调用、审批与执行回执被纳入同一个证据包。",
    objective: "查看任务证据",
    action: "点击“查看任务证据”，完成本次安全调度任务。",
  },
];

const stateLabels = {
  TASK_RECEIVED: "任务接收",
  SENSING: "感知中",
  CONTEXT_VALIDATED: "上下文已校验",
  REPLANNING_REQUIRED: "需重新规划",
  PLANNING: "规划中",
  AUDITING: "审核中",
  AWAITING_APPROVAL: "等待审批",
  EXECUTING: "执行中",
  VERIFYING: "验证中",
  COMPLETED: "已完成",
  REJECTED: "已拒绝",
  ROLLBACK: "已回滚",
  FAILED: "失败",
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

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

function agentContextPrompt(message) {
  const taskLine = state.task
    ? `当前任务 ${state.task.task_id}/V${state.task.task_version}，状态 ${state.task.state}。`
    : "当前尚未创建任务。";
  const contextLine = state.context
    ? `当前上下文 ${state.context.context_id}，context_hash=${state.context.context_hash}。`
    : "当前尚未生成ContextSnapshot。";
  const candidateLine = state.candidates.length
    ? `候选方案：${state.candidates.map((item) => `${item.candidate_id}:${item.name}`).join("；")}。`
    : "当前尚未生成候选方案。";
  return `${taskLine}\n${contextLine}\n${candidateLine}\n用户问题：${message}`;
}

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  window.setTimeout(() => $("#toast").classList.remove("visible"), 2600);
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
  const canvas = $("#scenario-chart");
  const { context, width, height } = resizeCanvas(canvas);
  const load = seededSeries(96, 760, 210, 0).map((value, index) => index >= 56 ? value + 420 : value);
  const pv = seededSeries(96, 240, 250, 1.7).map((value, index) => index >= 56 && index < 64 ? value * 0.814 : value);
  const tariff = Array.from({ length: 96 }, (_, index) => (index >= 56 && index <= 80 ? 980 : index > 32 && index < 56 ? 620 : 380));
  const series = [
    { label: "负荷", color: "#25272b", values: load },
    { label: "光伏", color: "#438fc8", values: pv },
    { label: "电价", color: "#c68c3d", values: tariff },
  ];
  const max = Math.max(...series.flatMap((item) => item.values));
  const inset = { left: 30, top: 18, right: 12, bottom: 18 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  context.clearRect(0, 0, width, height);
  context.font = "10px Inter, sans-serif";
  context.strokeStyle = "#e2e6ea";
  context.lineWidth = 1;
  for (let row = 0; row <= 4; row += 1) {
    const y = inset.top + (plotHeight * row) / 4;
    context.beginPath();
    context.moveTo(inset.left, y);
    context.lineTo(width - inset.right, y);
    context.stroke();
  }
  const eventX = inset.left + (plotWidth * 56) / 95;
  context.fillStyle = "rgba(218,91,84,.12)";
  context.fillRect(eventX, inset.top, 2, plotHeight);
  series.forEach((item) => {
    context.beginPath();
    item.values.forEach((value, index) => {
      const x = inset.left + (plotWidth * index) / 95;
      const y = inset.top + plotHeight * (1 - value / max);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.strokeStyle = item.color;
    context.lineWidth = 1.8;
    context.stroke();
  });
  series.forEach((item, index) => {
    context.fillStyle = item.color;
    context.fillRect(inset.left + index * 58, 4, 12, 2);
    context.fillText(item.label, inset.left + 17 + index * 58, 8);
  });
}

function updateAssetLabels(labels) {
  Object.entries(labels).forEach(([key, position]) => {
    const element = $(`.asset[data-anchor="${key}"]`);
    if (!element) return;
    element.style.setProperty("--x", `${position.x}px`);
    element.style.setProperty("--y", `${position.y}px`);
    element.dataset.hidden = position.visible ? "false" : "true";
  });
}

function statusClass(value) {
  if (value === "COMPLETED" || value === "approved") return "ok";
  if (value === "ROLLBACK" || value === "rejected") return "danger";
  if (value === "AWAITING_APPROVAL" || value === "audit_approved") return "warn";
  return "info";
}

function renderTask() {
  const task = state.task;
  const context = state.context;
  const active = state.events[Math.max(0, state.playbackIndex)] || state.events.at(-1);
  $("#task-id").textContent = task?.task_id || "未创建";
  $("#task-version").textContent = task ? `V${task.task_version}` : "--";
  $("#task-state").textContent = task ? (stateLabels[task.state] || task.state) : "IDLE";
  $("#task-state").className = statusClass(task?.state);
  $("#current-agent").textContent = active ? agentByActor[active.actor] || active.actor : "--";
  $("#evidence-state").textContent = task ? task.state : "IDLE";
  $("#context-id").textContent = context?.context_id || "--";
  $("#context-hash").textContent = context?.context_hash ? `${context.context_hash.slice(0, 16)}...` : "--";
  $("#trace-id").textContent = state.run?.trace_id || "--";
  $("#evidence-status").textContent = task?.evidence_sha256 ? "已封存" : state.evidence ? "可查看" : "未生成";
  $("#open-evidence").disabled = !state.task;
  $("#view-context").disabled = !state.context;
  $("#review-candidates").disabled = !state.candidates.length;
  renderAgentConsole();
}

function renderCandidates() {
  if (!state.candidates.length) {
    $("#candidate-list").innerHTML = `<p class="empty">点击运行后由 Dispatch Agent 生成三套候选方案。</p>`;
    return;
  }
  $("#candidate-list").innerHTML = state.candidates.map((candidate) => {
    const verdict = state.audit.find((item) => item.candidate_id === candidate.candidate_id);
    const rejected = verdict?.verdict === "rejected";
    const status = verdict ? (rejected ? "审核拒绝" : "审核通过") : "待审核";
    return `
      <button class="candidate ${rejected ? "rejected" : "approved"}" type="button" data-candidate-id="${escapeHTML(candidate.candidate_id)}">
        <div>
          <span>${escapeHTML(candidate.candidate_id)}｜${escapeHTML(candidate.name)}</span>
          <strong>${escapeHTML(candidate.priority)}</strong>
        </div>
        <dl>
          <div><dt>成本</dt><dd>¥${Math.round(candidate.cost_yuan).toLocaleString()}</dd></div>
          <div><dt>最大功率</dt><dd>${Math.round(candidate.max_power_kw)} kW</dd></div>
          <div><dt>SOC</dt><dd>${candidate.soc_min_percent}% - ${candidate.soc_max_percent}%</dd></div>
          <div><dt>变压器</dt><dd>${candidate.transformer_load_percent}%</dd></div>
        </dl>
        <p>${escapeHTML(status)}${verdict ? `：${escapeHTML(verdict.reason)}` : ""}</p>
      </button>
    `;
  }).join("");
  $$(".candidate").forEach((candidate) => {
    candidate.addEventListener("click", () => openCandidateDetail(candidate.dataset.candidateId));
  });
}

function traceText(event) {
  const time = new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour12: false });
  return `${time} ${event.actor} ${event.reason}`;
}

function renderTrace() {
  $("#trace-count").textContent = `${state.events.length} 条事件`;
  if (!state.events.length) {
    $("#trace-list").innerHTML = `<p class="empty">运行后展示真实后端事件记录。</p>`;
    return;
  }
  $("#trace-list").innerHTML = state.events.map((event, index) => `
    <button class="trace-item ${index === state.playbackIndex ? "active" : ""}" type="button" data-index="${index}">
      <i class="${statusClass(event.to_state)}"></i>
      <span>${escapeHTML(traceText(event))}</span>
      <small>${escapeHTML(event.to_state)} · V${event.task_version}</small>
    </button>
  `).join("");
  $$(".trace-item").forEach((item) => {
    item.addEventListener("click", () => openTraceDetail(Number(item.dataset.index)));
  });
}

function renderAgentConsole() {
  const info = agentInfo[state.selectedAgent];
  const config = state.modelConfigs[state.selectedAgent];
  $("#selected-agent-name").textContent = info.name;
  $("#selected-agent-skill").textContent = info.skill;
  $("#conversation-avatar").src = state.avatarSelection[state.selectedAgent] || info.avatar;
  $("#agent-model-status").textContent = config?.connection_status || "未测试";
  $("#agent-chat-input").placeholder = info.defaultPrompt;
  $$(".agent-row").forEach((row) => {
    row.classList.toggle("active", row.dataset.agent === state.selectedAgent);
  });
  $$(".agent-row").forEach((row) => {
    const avatar = row.querySelector(".agent-avatar img");
    if (avatar) avatar.src = state.avatarSelection[row.dataset.agent] || agentInfo[row.dataset.agent].avatar;
  });
}

function restoreAvatarSelection() {
  try {
    const saved = JSON.parse(window.localStorage.getItem("energymesh.agent-avatars") || "{}");
    state.avatarSelection = Object.fromEntries(
      Object.entries(saved).filter(([agentId, avatar]) => agentInfo[agentId] && avatarOptions.includes(avatar)),
    );
  } catch {
    state.avatarSelection = {};
  }
}

function randomizeAgentAvatar() {
  const current = state.avatarSelection[state.selectedAgent] || agentInfo[state.selectedAgent].avatar;
  const alternatives = avatarOptions.filter((avatar) => avatar !== current);
  state.avatarSelection[state.selectedAgent] = alternatives[Math.floor(Math.random() * alternatives.length)];
  window.localStorage.setItem("energymesh.agent-avatars", JSON.stringify(state.avatarSelection));
  renderAgentConsole();
  toast(`${agentInfo[state.selectedAgent].name} 的头像已随机更换`);
}

function addAgentMessage(role, text) {
  const message = document.createElement("article");
  message.className = `agent-message ${role}`;
  message.innerHTML = `<span>${role === "user" ? "用户" : agentInfo[state.selectedAgent].name}</span><p>${escapeHTML(text)}</p>`;
  $("#agent-messages").append(message);
  $("#agent-messages").scrollTop = $("#agent-messages").scrollHeight;
}

async function loadModelConfigs() {
  try {
    const manifest = await request("/api/agentteams/manifest");
    state.modelConfigs = manifest.model_configs || {};
    renderAgentConsole();
  } catch {
    state.modelConfigs = {};
  }
}

function openModelDialog() {
  const info = agentInfo[state.selectedAgent];
  const config = state.modelConfigs[state.selectedAgent];
  $("#model-title").textContent = `${info.name} 模型设置`;
  $("#model-base-url").value = config?.base_url || "https://api.deepseek.com";
  $("#model-api-key").value = "";
  $("#model-name").value = config?.model || "deepseek-chat";
  $("#model-connection-status").textContent = config?.connection_status || "未测试";
  $("#model-error").hidden = true;
  $("#model-dialog").showModal();
}

function selectAgent(agentId) {
  state.selectedAgent = agentId;
  $("#agent-messages").innerHTML = "";
  addAgentMessage(
    "agent",
    `已切换到${agentInfo[agentId].name}。我会带着当前 task_id、task_version 和 context_hash 回答，也会说明我能做什么和不能越过的边界。`,
  );
  renderAgentConsole();
}

async function saveModelConfig() {
  const body = {
    base_url: $("#model-base-url").value,
    api_key: $("#model-api-key").value || null,
    model: $("#model-name").value,
  };
  const saved = await request(`/api/agents/${state.selectedAgent}/model`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  state.modelConfigs[state.selectedAgent] = saved;
  renderAgentConsole();
  toast("模型配置已保存在后端，前端不会回显完整 API Key");
}

async function testModelConnection() {
  try {
    await saveModelConfig();
    const result = await request(`/api/agents/${state.selectedAgent}/model/test`, { method: "POST" });
    $("#model-connection-status").textContent = result.success ? "正常" : "失败";
    $("#model-error").hidden = result.success;
    $("#model-error").textContent = result.error || "";
    await loadModelConfigs();
  } catch (error) {
    $("#model-connection-status").textContent = "失败";
    $("#model-error").hidden = false;
    $("#model-error").textContent = error.message;
  }
}

async function sendAgentChat(message) {
  addAgentMessage("user", message);
  try {
    const result = await request(`/api/agents/${state.selectedAgent}/chat`, {
      method: "POST",
      body: JSON.stringify({ message: agentContextPrompt(message) }),
    });
    addAgentMessage("agent", result.response);
  } catch (error) {
    addAgentMessage("agent", `无法连接模型：${error.message}。请先打开模型设置，保存并测试连接。`);
  }
}

function openTraceDetail(index) {
  const event = state.events[index];
  if (!event) return;
  $("#trace-dialog-title").textContent = event.event_id;
  $("#trace-json").textContent = JSON.stringify(event, null, 2);
  $("#trace-dialog").showModal();
}

function renderContextDashboard(context) {
  const changes = context.changes || {};
  const quality = context.data_quality || {};
  $("#context-summary").innerHTML = `
    <article><span>任务版本</span><strong>V${escapeHTML(context.task_version)}</strong></article>
    <article><span>原计划</span><strong>${context.previous_plan_status === "invalidated" ? "已失效" : escapeHTML(context.previous_plan_status)}</strong></article>
    <article><span>自动化权限</span><strong>${context.automation_permission === "restricted" ? "受限执行" : escapeHTML(context.automation_permission)}</strong></article>
    <article><span>约束版本</span><strong>${escapeHTML(context.constraint_set_version)}</strong></article>
  `;
  const changeCards = [
    ["生产负荷", `+${changes.production_load_added_kw} kW`, "急单插入"],
    ["光伏实际偏差", `${changes.pv_actual_vs_forecast_percent}%`, "低于预测"],
    ["变压器温度", changes.transformer_temperature_conflict ? "数据冲突" : "正常", "需安全降级"],
    ["电价时段", changes.tariff_period === "peak" ? "峰值" : escapeHTML(changes.tariff_period), "需重新评估成本"],
  ];
  $("#context-changes").innerHTML = changeCards.map(([label, value, note]) => `<article><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`).join("");
  const validSources = Object.entries(quality).filter(([, value]) => value === "valid").map(([name]) => name.toUpperCase());
  $("#context-quality").innerHTML = `
    <article class="quality-ok"><span>可信数据源</span><strong>${validSources.join(" · ") || "--"}</strong><small>时间戳与完整性校验通过</small></article>
    <article class="quality-warning"><span>需人工关注</span><strong>变压器传感器冲突</strong><small>两路温度数据不一致，自动化权限已收紧</small></article>
    <article><span>快照标识</span><strong>${escapeHTML(context.context_id)}</strong><small>${escapeHTML(context.context_hash).slice(0, 20)}...</small></article>
  `;
}

function openContext() {
  if (!state.context) return;
  renderContextDashboard(state.context);
  $("#context-json").textContent = JSON.stringify(state.context, null, 2);
  $("#context-dialog").showModal();
}

function openCandidateDetail(candidateId) {
  const candidate = state.candidates.find((item) => item.candidate_id === candidateId);
  const verdict = state.audit.find((item) => item.candidate_id === candidateId);
  if (!candidate) return;
  $("#candidate-dialog-title").textContent = `${candidate.candidate_id}｜${candidate.name}`;
  $("#candidate-json").textContent = JSON.stringify({ candidate, audit_verdict: verdict || null }, null, 2);
  $("#candidate-dialog").showModal();
}

function reviewCandidates() {
  $("#candidate-list").scrollIntoView({ behavior: "smooth", block: "center" });
  tutorialAdvance("review");
}

function clearTutorialTarget() {
  if (state.tutorial.target) state.tutorial.target.classList.remove("tutorial-target");
  state.tutorial.target = null;
}

function positionTutorial() {
  const target = state.tutorial.target;
  if (!target) return;
  const spotlight = $("#tutorial-spotlight");
  const card = $("#tutorial-card");
  const rect = target.getBoundingClientRect();
  spotlight.style.left = `${Math.max(4, rect.left - 6)}px`;
  spotlight.style.top = `${Math.max(4, rect.top - 6)}px`;
  spotlight.style.width = `${rect.width + 12}px`;
  spotlight.style.height = `${rect.height + 12}px`;
  const cardWidth = Math.min(360, window.innerWidth - 32);
  const left = rect.left + rect.width / 2 > window.innerWidth / 2
    ? 16
    : window.innerWidth - cardWidth - 16;
  card.style.left = `${left}px`;
  card.style.top = "auto";
  card.style.bottom = "78px";
}

function showTutorialCompletion() {
  clearTutorialTarget();
  $("#tutorial-overlay").hidden = false;
  $("#tutorial-spotlight").style.cssText = "";
  $("#tutorial-step").textContent = "任务完成";
  $("#tutorial-count").textContent = "07 / 07";
  $("#tutorial-title").textContent = "安全调度闭环已完成";
  $("#tutorial-story").textContent = "你已亲手完成感知、上下文交接、候选方案审计、人工审批、模拟执行与证据封存。每一个关键节点均来自真实后端任务记录。";
  $("#tutorial-objective").textContent = "查看证据并复盘本次任务";
  $("#tutorial-action").textContent = "可重新开始本教程，或继续用 Agent 会话探索当前园区任务。";
  $("#tutorial-restart").hidden = false;
  document.body.classList.add("tutorial-active");
  window.localStorage.setItem("energymesh.tutorial-completed", "true");
}

function showTutorialStep() {
  const step = tutorialSteps[state.tutorial.step];
  if (!step) return showTutorialCompletion();
  const target = $(step.target);
  if (!target) return;
  clearTutorialTarget();
  state.tutorial.target = target;
  target.classList.add("tutorial-target");
  $("#tutorial-overlay").hidden = false;
  $("#tutorial-step").textContent = "安全调度任务";
  $("#tutorial-count").textContent = `${String(state.tutorial.step + 1).padStart(2, "0")} / ${String(tutorialSteps.length).padStart(2, "0")}`;
  $("#tutorial-title").textContent = step.title;
  $("#tutorial-story").textContent = step.story;
  $("#tutorial-objective").textContent = step.objective;
  $("#tutorial-action").textContent = step.action;
  $("#tutorial-restart").hidden = true;
  document.body.classList.add("tutorial-active");
  window.requestAnimationFrame(positionTutorial);
}

function beginTutorial() {
  state.tutorial = { active: true, step: 0, target: null };
  showTutorialStep();
}

function tutorialAdvance(event) {
  if (!state.tutorial.active) return;
  const step = tutorialSteps[state.tutorial.step];
  if (!step || step.event !== event) return;
  state.tutorial.step += 1;
  showTutorialStep();
}

function stopTutorial() {
  state.tutorial.active = false;
  clearTutorialTarget();
  $("#tutorial-overlay").hidden = true;
  document.body.classList.remove("tutorial-active");
}

function startPlayback() {
  window.clearInterval(state.playbackTimer);
  state.playbackIndex = -1;
  state.paused = false;
  $("#pause-button").textContent = "暂停播放";
  state.playbackTimer = window.setInterval(() => {
    if (state.paused) return;
    state.playbackIndex += 1;
    if (state.playbackIndex >= state.events.length - 1) {
      state.playbackIndex = state.events.length - 1;
      window.clearInterval(state.playbackTimer);
    }
    renderTask();
    renderTrace();
  }, 620);
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
  $("#approve-b").disabled = task.state !== "AWAITING_APPROVAL";
  $("#execute-b").disabled = !state.approval || task.state !== "AWAITING_APPROVAL";
  renderTask();
  renderCandidates();
  renderTrace();
}

async function runDemo() {
  try {
    state.approval = null;
    state.run = await request("/api/demo/run", { method: "POST" });
    await refreshTask(state.run.task_id);
    startPlayback();
    toast("14:00复合变化任务已创建，等待人工审批");
    tutorialAdvance("run");
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
        approver: "演示审批员",
        reason: "确认Candidate B已通过Audit Agent硬约束审核，允许模拟执行。",
      }),
    });
    await refreshTask(state.run.task_id);
    $("#execute-b").disabled = false;
    toast("Candidate B 已绑定上下文哈希完成审批");
    tutorialAdvance("approve");
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
    startPlayback();
    toast("执行完成，偏差低于5%，证据已封存");
    tutorialAdvance("execute");
  } catch (error) {
    toast(error.message);
  }
}

async function runRollback() {
  try {
    state.approval = null;
    state.run = await request("/api/demo/run-rollback", { method: "POST" });
    await refreshTask(state.run.task_id);
    startPlayback();
    toast("回滚场景已完成：执行偏差超过5%，恢复安全基线");
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

function setupCampus() {
  const canvas = $("#campus-3d");
  if (!canvas) return;
  state.campus3d = createCampus3D(canvas, updateAssetLabels);
  $("#reset-camera").addEventListener("click", () => {
    if (state.campus3d?.resetCamera) state.campus3d.resetCamera();
    else state.campus3d?.reset?.();
  });
}

function setupPaneResizers() {
  const workspace = $(".workspace");
  const sidebar = $(".agent-sidebar");
  const conversation = $(".conversation-panel");
  if (!workspace || !sidebar || !conversation) return;

  const restoreWidth = (property, fallback) => {
    const saved = Number(window.localStorage.getItem(`energymesh.${property}`));
    workspace.style.setProperty(property, `${Number.isFinite(saved) && saved > 0 ? saved : fallback}px`);
  };
  restoreWidth("--sidebar-width", 260);
  restoreWidth("--conversation-width", 360);

  $$(".pane-resizer").forEach((resizer) => {
    const property = resizer.dataset.resizer === "sidebar" ? "--sidebar-width" : "--conversation-width";
    resizer.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      resizer.setPointerCapture(event.pointerId);
      resizer.classList.add("is-dragging");
      document.body.style.cursor = "col-resize";

      const move = (moveEvent) => {
        const bounds = workspace.getBoundingClientRect();
        const sidebarWidth = sidebar.getBoundingClientRect().width;
        const conversationWidth = conversation.getBoundingClientRect().width;
        const rightMinimum = 390;
        const dividerWidth = 18;
        const value = property === "--sidebar-width"
          ? moveEvent.clientX - bounds.left
          : moveEvent.clientX - bounds.left - sidebarWidth - 9;
        const minimum = property === "--sidebar-width" ? 220 : 300;
        const otherWidth = property === "--sidebar-width" ? conversationWidth : sidebarWidth;
        const maximum = Math.max(minimum, bounds.width - otherWidth - rightMinimum - dividerWidth);
        const width = Math.round(Math.min(Math.max(value, minimum), maximum));
        workspace.style.setProperty(property, `${width}px`);
      };

      const finish = () => {
        resizer.classList.remove("is-dragging");
        document.body.style.cursor = "";
        window.localStorage.setItem(`energymesh.${property}`, `${Math.round(property === "--sidebar-width" ? sidebar.getBoundingClientRect().width : conversation.getBoundingClientRect().width)}`);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish, { once: true });
    });
  });
}

function setupEvents() {
  $("#run-button").addEventListener("click", runDemo);
  $("#approve-b").addEventListener("click", approveCandidateB);
  $("#execute-b").addEventListener("click", executeCandidateB);
  $("#rollback-button").addEventListener("click", runRollback);
  $("#open-evidence").addEventListener("click", openEvidence);
  $("#view-context").addEventListener("click", openContext);
  $("#review-candidates").addEventListener("click", reviewCandidates);
  $("#tutorial-button").addEventListener("click", beginTutorial);
  $("#tutorial-skip").addEventListener("click", stopTutorial);
  $("#tutorial-restart").addEventListener("click", beginTutorial);
  $("#random-avatar-button").addEventListener("click", randomizeAgentAvatar);
  $("#model-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveModelConfig();
      $("#model-dialog").close();
    } catch (error) {
      $("#model-error").hidden = false;
      $("#model-error").textContent = error.message;
    }
  });
  $("#test-model-button").addEventListener("click", testModelConnection);
  $("#agent-chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#agent-chat-input");
    const message = input.value.trim() || agentInfo[state.selectedAgent].defaultPrompt;
    input.value = "";
    await sendAgentChat(message);
  });
  $$(".agent-select").forEach((button) => {
    button.addEventListener("click", () => selectAgent(button.dataset.agent));
  });
  $$(".agent-avatar").forEach((avatar) => {
    avatar.addEventListener("click", () => {
      state.selectedAgent = avatar.dataset.openModel;
      renderAgentConsole();
      openModelDialog();
    });
  });
  $("#pause-button").addEventListener("click", () => {
    state.paused = !state.paused;
    $("#pause-button").textContent = state.paused ? "继续播放" : "暂停播放";
  });
  $$("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => $(`#${button.dataset.closeDialog}`).close());
  });
  $("#context-dialog").addEventListener("close", () => tutorialAdvance("context"));
  $("#candidate-dialog").addEventListener("close", () => tutorialAdvance("candidate-a"));
  $("#evidence-dialog").addEventListener("close", () => tutorialAdvance("evidence"));
  $$(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".segmented button").forEach((item) => item.classList.toggle("active", item === button));
      document.body.dataset.mode = button.dataset.mode;
      if (button.dataset.mode === "audit" && state.task) openEvidence();
    });
  });
  window.addEventListener("resize", () => {
    drawScenarioChart();
    state.campus3d?.resize?.();
    if (state.tutorial.active) positionTutorial();
  });
}

async function restoreLatestDemo() {
  try {
    await refreshTask("TASK-20260731-014");
    state.run = {
      task_id: state.task.task_id,
      task_version: state.task.task_version,
      trace_id: state.task.trace_id,
      state: state.task.state,
      context_id: state.context.context_id,
      context_hash: state.context.context_hash,
    };
    state.playbackIndex = state.events.length - 1;
    renderTask();
    renderTrace();
    if (!$("#agent-messages .agent-message")) {
      addAgentMessage(
        "agent",
        "当前任务已恢复。你可以询问我发现的异常、候选策略、审核结论，或要求我说明下一步应交给哪个角色。",
      );
    }
  } catch {
    renderTask();
    renderCandidates();
    renderTrace();
    if (!$("#agent-messages .agent-message")) {
      addAgentMessage("agent", "我已就绪。运行14:00复合变化后，我会基于同一任务上下文参与协作。");
    }
  }
}

drawScenarioChart();
setupCampus();
setupPaneResizers();
restoreAvatarSelection();
setupEvents();
loadModelConfigs();
restoreLatestDemo();
if (!window.localStorage.getItem("energymesh.tutorial-completed")) {
  window.setTimeout(beginTutorial, 450);
}
