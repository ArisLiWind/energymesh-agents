import { createCampus3D } from "/static/campus3d.js";

const state = {
  scenario: null,
  task: null,
  selectedAgent: null,
  settingsAgent: null,
  campus3d: null,
  liveInterval: 57,
  modelConfigs: {},
  avatarStyles: {},
};

const agentInfo = {
  perception: { name: "感知Agent", icon: "◎", avatar: "perception", role: "核验负荷、光伏、SOC、设备状态与生产计划" },
  dispatch: { name: "调度Agent", icon: "◔", avatar: "dispatch", role: "调用优化工具生成下一调度周期候选策略" },
  audit: { name: "审核Agent", icon: "◆", avatar: "audit", role: "独立复算安全约束，并验证方案是否优于基线" },
  execute: { name: "执行Agent", icon: "▷", avatar: "execute", role: "在审批门禁后模拟下发，并持续核对计划与实际" },
};

const actionNames = {
  task_received: "接收新调度任务",
  operational_context_validated: "完成数据和生产计划核验",
  candidate_plans_optimized: "生成三套候选调度方案",
  independent_policy_audit: "独立完成硬约束与收益审核",
  audited_plan_selected: "选定通过审核的最优方案",
  human_approval_requested: "请求人工审批柔性负荷响应",
  approval_granted: "人工审批通过",
  approval_rejected: "人工审批拒绝",
  simulation_started: "启动模拟执行",
  post_execution_verification: "完成结果验证与证据封存",
  human_handoff_required: "检测到冲突并交还工程师",
  safe_fallback_activated: "偏差超限，执行安全回退",
};

function $(selector) { return document.querySelector(selector); }
function $$(selector) { return [...document.querySelectorAll(selector)]; }
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function escapeHTML(value) {
  return `${value}`.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function appShell() { return $(".app-shell"); }

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  window.setTimeout(() => $("#toast").classList.remove("visible"), 2600);
}

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

function agentBackendId(agentKey) {
  return {
    perception: "perception_agent",
    dispatch: "dispatch_agent",
    audit: "audit_agent",
    execute: "execution_agent",
  }[agentKey] || agentKey;
}

function loadAvatarStyles() {
  state.avatarStyles = JSON.parse(localStorage.getItem("energymesh-avatar-styles") || "{}");
}

function saveAvatarStyles() {
  localStorage.setItem("energymesh-avatar-styles", JSON.stringify(state.avatarStyles));
}

function avatarStyleClass(agentKey) {
  const index = state.avatarStyles[agentKey];
  return Number.isInteger(index) ? `avatar-style-${index}` : "";
}

function avatarClasses(agentKey) {
  const avatar = agentInfo[agentKey]?.avatar || "perception";
  return `agent-avatar avatar-${avatar} ${avatarStyleClass(agentKey)}`.trim();
}

function syncAvatarStyles() {
  $$(".agent-card").forEach((card) => {
    const avatar = card.querySelector(".agent-avatar");
    if (!avatar) return;
    avatar.className = avatarClasses(card.dataset.agent);
  });
  if (state.selectedAgent) {
    $("#conversation-icon").innerHTML = avatarMarkup(state.selectedAgent);
  }
  if (state.settingsAgent) {
    $("#model-avatar-preview").className = avatarClasses(state.settingsAgent);
  }
}

function currentPoint() {
  if (!state.scenario) return null;
  return state.scenario.forecast[clamp(state.liveInterval, 0, 95)];
}

function selectedPlan() {
  return state.task?.plans.find((plan) => plan.plan_id === state.task.selected_plan_id) || null;
}

function renderLiveData() {
  const point = currentPoint();
  if (!point || !state.scenario) return;
  const plan = selectedPlan();
  const planned = plan?.points[point.interval];
  const site = state.scenario.site;
  const grid = planned?.grid_import_kw ?? Math.max(0, point.load_kw - point.pv_kw);
  const battery = planned ? planned.discharge_kw - planned.charge_kw : 0;
  const soc = planned?.soc_end ?? site.initial_soc;
  const pvEnergy = state.scenario.forecast.reduce((sum, item) => sum + item.pv_kw * .25, 0);
  const peak = plan?.metrics.peak_grid_kw ?? Math.max(...state.scenario.forecast.map((item) => item.load_kw - item.pv_kw));

  $("#factory-power").textContent = `${Math.round(point.load_kw * .62)} kW`;
  $("#solar-power").textContent = `${Math.round(point.pv_kw)} kW`;
  $("#storage-power").textContent = `SOC ${(soc * 100).toFixed(0)}%`;
  $("#grid-power").textContent = `${Math.round(grid)} kW`;
  $("#charge-power").textContent = `${Math.round(point.load_kw * .08)} kW`;
  $("#compute-power").textContent = `${Math.round(point.load_kw * .30)} kW`;
  $("#battery-live").textContent = planned ? `${battery >= 0 ? "+" : ""}${Math.round(battery)} kW` : "待调度";
  $("#soc-live").textContent = `${(soc * 100).toFixed(0)}%`;
  $("#capacity-live").textContent = `${Math.round(site.battery_capacity_kwh * soc)} kWh`;
  $("#pv-live").textContent = `${Math.round(point.pv_kw)} kW`;
  $("#pv-energy").textContent = `${Math.round(pvEnergy)} kWh`;
  $("#self-use-live").textContent = plan ? `${(plan.metrics.pv_self_consumption_ratio * 100).toFixed(1)}%` : "--";
  $("#import-live").textContent = `${Math.round(grid)} kW`;
  $("#load-live").textContent = `${Math.round(point.load_kw)} kW`;
  $("#peak-live").textContent = `${Math.round(peak)} kW`;

  const values = [
    clamp((grid / site.transformer_capacity_kw) * 100, 0, 100),
    soc * 100,
    clamp((grid / site.grid_interconnection_limit_kw) * 100, 0, 100),
  ];
  $$("#constraints > div").forEach((element, index) => {
    element.querySelector("strong").textContent = `${values[index].toFixed(0)}%`;
    element.querySelector("i").style.setProperty("--value", `${values[index]}%`);
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

function setImpactRow(key, before, after, unit, higherIsBetter = false) {
  const row = $(`.impact-row[data-key="${key}"]`);
  const max = Math.max(before, after, 1);
  row.querySelector("span").textContent = `${before.toLocaleString()} → ${after.toLocaleString()} ${unit}`;
  row.querySelector(".bars i").style.setProperty("--bar", `${Math.max(5, before / max * 100)}%`);
  row.querySelector(".bars b").style.setProperty("--bar", `${Math.max(5, after / max * 100)}%`);
  const delta = higherIsBetter ? after - before : before - after;
  const ratio = Math.abs(delta) / Math.max(before, .01) * 100;
  row.querySelector("em").textContent = `${delta >= 0 ? (higherIsBetter ? "↑" : "↓") : (higherIsBetter ? "↓" : "↑")} ${ratio.toFixed(1)}%`;
  row.querySelector("em").style.color = delta >= 0 ? "var(--accent)" : "var(--danger)";
}

function renderImpact() {
  const plan = selectedPlan();
  const baseline = state.task?.baseline_plan;
  if (!plan || !baseline) return;
  const totalEnergy = state.scenario.forecast.reduce((sum, point) => sum + point.load_kw * .25, 0);
  setImpactRow("cost", baseline.metrics.total_cost_yuan, plan.metrics.total_cost_yuan, "元");
  setImpactRow("peak", baseline.metrics.peak_grid_kw, plan.metrics.peak_grid_kw, "kW");
  setImpactRow("solar", baseline.metrics.pv_self_consumption_ratio * 100, plan.metrics.pv_self_consumption_ratio * 100, "%", true);
  setImpactRow("efficiency", baseline.metrics.total_cost_yuan / totalEnergy, plan.metrics.total_cost_yuan / totalEnergy, "元/kWh");
  const audit = state.task.audits.find((item) => item.plan_id === plan.plan_id);
  $("#impact-badge").textContent = `预计节省 ¥${audit.improvement_yuan.toLocaleString()} ↓`;
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

function renderTrendChart() {
  if (!state.scenario) return;
  const canvas = $("#realtime-chart");
  const { context, width, height } = resizeCanvas(canvas);
  const forecast = state.scenario.forecast;
  const plan = selectedPlan();
  const series = [
    { color: "#dbe0dd", values: forecast.map((point) => point.load_kw) },
    { color: "#67d9cf", values: forecast.map((point) => point.pv_kw) },
    {
      color: "#f2bd5b",
      values: plan
        ? plan.points.map((point) => point.grid_import_kw)
        : forecast.map((point) => Math.max(0, point.load_kw - point.pv_kw)),
    },
  ];
  const soc = plan?.points.map((point) => point.soc_end * 100) || [];
  const max = Math.max(...series.flatMap((item) => item.values), 1);
  const inset = { left: 27, right: 9, top: 9, bottom: 7 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  context.clearRect(0, 0, width, height);
  context.lineWidth = 1;
  context.font = "7px Inter, sans-serif";
  for (let row = 0; row <= 3; row += 1) {
    const y = inset.top + plotHeight * row / 3;
    context.strokeStyle = "#343b38";
    context.beginPath();
    context.moveTo(inset.left, y);
    context.lineTo(width - inset.right, y);
    context.stroke();
    context.fillStyle = "#7f8a84";
    context.fillText(`${Math.round(max * (1 - row / 3))}`, 1, y + 2);
  }
  series.forEach((item) => {
    context.beginPath();
    item.values.forEach((value, index) => {
      const x = inset.left + plotWidth * index / (item.values.length - 1);
      const y = inset.top + plotHeight * (1 - value / max);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.strokeStyle = item.color;
    context.lineWidth = 1.6;
    context.stroke();
  });
  if (soc.length) {
    context.beginPath();
    soc.forEach((value, index) => {
      const x = inset.left + plotWidth * index / (soc.length - 1);
      const y = inset.top + plotHeight * (1 - value / 100);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.strokeStyle = "#ef776f";
    context.lineWidth = 1.35;
    context.setLineDash([3, 2]);
    context.stroke();
    context.setLineDash([]);
  }
}

function avatarMarkup(agentKey, user = false) {
  if (user) return `<span class="message-avatar user-avatar">人</span>`;
  return `<span class="message-avatar ${avatarClasses(agentKey)}" aria-hidden="true"><span class="avatar-hair"></span><span class="avatar-face"><span class="avatar-eyes"></span><span class="avatar-mouth"></span></span></span>`;
}

function addMessage(agentKey, text, user = false) {
  const info = user ? { name: "你", icon: "人" } : agentInfo[agentKey];
  const message = document.createElement("div");
  message.className = `message${user ? " user" : ""}`;
  message.innerHTML = `${avatarMarkup(agentKey, user)}<div class="message-body"><span class="message-meta">${escapeHTML(info.name)}</span>${escapeHTML(text)}</div>`;
  $("#messages").append(message);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

function resetConversation() {
  $("#messages").innerHTML = "";
  addMessage("perception", "已接入园区演示数据。当前为本地模拟沙盘，未连接真实EMS、BMS或PCS。");
  addMessage("dispatch", "等待任务。收到变化后，我会调用优化器生成多套策略，而不是直接下发功率。");
  addMessage("audit", "所有候选方案必须通过SOC、功率、变压器、并网和能量守恒复算。");
}

function setChatOpen(open) {
  appShell().classList.toggle("chat-open", open);
  window.requestAnimationFrame(() => {
    renderTrendChart();
    state.campus3d?.resize?.();
  });
}

function selectAgent(agentKey) {
  setChatOpen(true);
  state.selectedAgent = agentKey;
  $$(".agent-card").forEach((card) => card.classList.toggle("selected", card.dataset.agent === agentKey));
  $("#collaboration-mode").classList.remove("active");
  $("#clear-selection").hidden = false;
  const info = agentInfo[agentKey];
  $("#conversation-icon").innerHTML = avatarMarkup(agentKey);
  $("#conversation-title").textContent = `与${info.name}单独对话`;
  $("#conversation-subtitle").textContent = info.role;
  $("#chat-input").placeholder = `发送消息给${info.name}`;
  $("#messages").innerHTML = "";
  addMessage(agentKey, `已进入单独对话。我只从${info.name}的职责边界回答；涉及其他Agent的动作不会自动执行。`);
}

function enableCollaboration(openChat = true) {
  setChatOpen(openChat);
  state.selectedAgent = null;
  $$(".agent-card").forEach((card) => card.classList.remove("selected"));
  $("#collaboration-mode").classList.add("active");
  $("#clear-selection").hidden = true;
  $("#conversation-icon").textContent = "✣";
  $("#conversation-title").textContent = "多智能体协同会话";
  $("#conversation-subtitle").textContent = "四类Agent共享上下文并自动协商";
  $("#chat-input").placeholder = "未选中Agent：发送后由多智能体协同处理";
  resetConversation();
}

function activatePanel(panel) {
  $$(".panel-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.panel === panel));
  $(".operations-panel").classList.toggle("audit-focus", panel === "audit");
  renderTrendChart();
  state.campus3d?.resize?.();
}

function reorderCard(source, target, clientY) {
  if (!source || !target || source === target) return;
  const rect = target.getBoundingClientRect();
  const before = clientY < rect.top + rect.height / 2;
  target.classList.remove("drop-before", "drop-after");
  target.parentNode.insertBefore(source, before ? target : target.nextSibling);
  window.requestAnimationFrame(() => {
    renderTrendChart();
    state.campus3d?.resize?.();
  });
}

function setupCardSorting() {
  let dragged = null;
  let targetCard = null;

  function visibleCards() {
    return $$(".ops-card").filter((card) => card !== dragged && getComputedStyle(card).display !== "none");
  }

  function clearDropState() {
    $$(".ops-card").forEach((card) => card.classList.remove("drop-before", "drop-after"));
  }

  function updateDropTarget(clientY) {
    clearDropState();
    const cards = visibleCards();
    targetCard = cards.find((card) => {
      const rect = card.getBoundingClientRect();
      return clientY >= rect.top && clientY <= rect.bottom;
    });
    if (!targetCard && cards.length) {
      const firstRect = cards[0].getBoundingClientRect();
      targetCard = clientY < firstRect.top ? cards[0] : cards.at(-1);
    }
    if (!targetCard) return;
    const rect = targetCard.getBoundingClientRect();
    const before = clientY < rect.top + rect.height / 2;
    targetCard.classList.toggle("drop-before", before);
    targetCard.classList.toggle("drop-after", !before);
  }

  function endSort(event) {
    if (dragged && targetCard) {
      reorderCard(dragged, targetCard, event.clientY);
    }
    dragged?.classList.remove("dragging-card");
    dragged = null;
    targetCard = null;
    clearDropState();
    document.body.classList.remove("sorting-cards");
    window.removeEventListener("pointermove", moveSort);
    window.removeEventListener("pointerup", endSort);
    window.removeEventListener("pointercancel", endSort);
  }

  function moveSort(event) {
    if (!dragged) return;
    event.preventDefault();
    updateDropTarget(event.clientY);
  }

  $$("[data-drag-handle]").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      dragged = handle.closest(".ops-card");
      if (!dragged) return;
      event.preventDefault();
      dragged.classList.add("dragging-card");
      document.body.classList.add("sorting-cards");
      updateDropTarget(event.clientY);
      window.addEventListener("pointermove", moveSort);
      window.addEventListener("pointerup", endSort);
      window.addEventListener("pointercancel", endSort);
    });
  });
}

function startResize(splitter, event) {
  event.preventDefault();
  const mode = splitter.dataset.resize;
  const shell = appShell();
  const startX = event.clientX;
  const rect = shell.getBoundingClientRect();
  const initialSidebar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"));
  const initialOps = $(".operations-panel").getBoundingClientRect().width;
  splitter.classList.add("dragging");
  document.body.classList.add("resizing");
  splitter.setPointerCapture(event.pointerId);

  function move(pointerEvent) {
    if (mode === "sidebar") {
      const next = clamp(initialSidebar + pointerEvent.clientX - startX, 220, Math.min(380, rect.width * .36));
      document.documentElement.style.setProperty("--sidebar-width", `${next}px`);
    } else {
      const next = clamp(initialOps - (pointerEvent.clientX - startX), 520, Math.max(540, rect.width - 360));
      document.documentElement.style.setProperty("--ops-width", `${next}px`);
      setChatOpen(true);
    }
    renderTrendChart();
    state.campus3d?.resize?.();
  }

  function end() {
    splitter.classList.remove("dragging");
    document.body.classList.remove("resizing");
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
  }

  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
}

async function agentReply(agentKey, input) {
  const modelConfig = state.modelConfigs[agentBackendId(agentKey)];
  if (modelConfig) {
    try {
      const result = await request(`/api/agents/${agentBackendId(agentKey)}/chat`, {
        method: "POST",
        body: JSON.stringify({ message: input }),
      });
      addMessage(agentKey, result.response);
      return;
    } catch (error) {
      addMessage(agentKey, `模型调用失败：${error.message}`);
      return;
    }
  }
  const point = currentPoint();
  const plan = selectedPlan();
  const audit = state.task?.audits.find((item) => item.plan_id === state.task.selected_plan_id);
  const responses = {
    perception: `我刚核对了这个问题。当前时段负荷约${Math.round(point.load_kw)} kW、光伏${Math.round(point.pv_kw)} kW，数据来自演示场景而不是现场表计。${state.task?.perception.anomalies.length ? `我还看到${state.task.perception.anomalies.join("、")}，所以不会把异常值直接交给调度。` : "目前没有发现需要阻断流程的数据冲突。"}你希望我继续看负荷、光伏还是设备温度？`,
    dispatch: plan
      ? `我理解你的关注点。基于审核后的输入，我把成本、需量、电池损耗和生产连续性一起纳入了计算。当前选定方案成本¥${plan.metrics.total_cost_yuan.toLocaleString()}、峰值${plan.metrics.peak_grid_kw} kW。这里我可以解释策略，但不能越过审核Agent直接执行。`
      : "我先等感知Agent把数据质量和约束确认下来。拿到可靠上下文后，我会给出至少三套候选方案，并把每套方案的取舍讲清楚。",
    audit: audit
      ? `我重新算过，不是照抄调度Agent的结果。当前结论是${audit.decision === "requires_approval" ? "硬约束通过，但柔性负荷响应需要人工批准" : "可以通过"}；相对原EMS基线预计改善¥${audit.improvement_yuan.toLocaleString()}。如果你质疑某条约束，我可以按SOC、PCS、变压器、并网或能量守恒逐项说明。`
      : "候选方案还没送到我这里。我不会提前承诺通过；收到后会独立复算SOC、PCS功率、变压器容量、并网限制、生产最低负荷和功率平衡。",
    execute: state.task?.execution_summary
      ? `我已完成本地回放，共处理${state.task.execution_summary.intervals_replayed}个时段，真实设备连接数仍为${state.task.execution_summary.real_devices_contacted}。如果实际偏差超过5%，我会把储能设点归零并把控制权交回人工。`
      : "我现在保持执行门禁关闭。审核和必要审批都完成后，我也只会向本地模拟适配器发送结构化命令，不会连接真实EMS或PCS。",
  };
  window.setTimeout(() => addMessage(agentKey, responses[agentKey]), 260);
}

function setConnectionState(config = null) {
  const status = config?.connection_status || "未测试";
  $("#connection-status").textContent = status;
  $("#connection-status").dataset.state = status;
  $("#connection-error").hidden = !config?.last_error;
  $("#connection-error").textContent = config?.last_error || "";
}

function openModelDialog(agentKey) {
  state.settingsAgent = agentKey;
  const info = agentInfo[agentKey];
  const backendId = agentBackendId(agentKey);
  const config = state.modelConfigs[backendId];
  $("#model-dialog-title").textContent = `${info.name}模型设置`;
  $("#model-agent-name").textContent = info.name;
  $("#model-agent-role").textContent = info.role;
  $("#model-avatar-preview").className = avatarClasses(agentKey);
  $("#model-base-url").value = config?.base_url || "https://api.deepseek.com";
  $("#model-api-key").value = "";
  $("#model-api-key").placeholder = config?.api_key_masked || "•••••••••••••••";
  $("#model-name").value = config?.model || "deepseek-chat";
  $("#model-test-message").value = "请介绍你的职责";
  $("#model-test-reply").textContent = "等待发送";
  setConnectionState(config);
  $("#model-dialog").showModal();
}

function randomizeCurrentAvatar() {
  if (!state.settingsAgent) return;
  const current = state.avatarStyles[state.settingsAgent] ?? -1;
  let next = Math.floor(Math.random() * 6);
  if (next === current) next = (next + 1) % 6;
  state.avatarStyles[state.settingsAgent] = next;
  saveAvatarStyles();
  syncAvatarStyles();
}

function currentModelPayload() {
  return {
    base_url: $("#model-base-url").value.trim(),
    api_key: $("#model-api-key").value.trim() || null,
    model: $("#model-name").value.trim(),
  };
}

async function saveModelConfig() {
  if (!state.settingsAgent) return null;
  const backendId = agentBackendId(state.settingsAgent);
  const config = await request(`/api/agents/${backendId}/model`, {
    method: "PUT",
    body: JSON.stringify(currentModelPayload()),
  });
  state.modelConfigs[backendId] = config;
  $("#model-api-key").value = "";
  $("#model-api-key").placeholder = config.api_key_masked || "•••••••••••••••";
  setConnectionState(config);
  return config;
}

async function testModelConnection() {
  if (!state.settingsAgent) return;
  const button = $("#test-model-button");
  button.disabled = true;
  try {
    const config = await saveModelConfig();
    if (!config) return;
    const result = await request(`/api/agents/${agentBackendId(state.settingsAgent)}/model/test`, {
      method: "POST",
    });
    const next = {
      ...config,
      connection_status: result.success ? "正常" : "失败",
      last_error: result.error || null,
    };
    state.modelConfigs[config.agent_id] = next;
    setConnectionState(next);
    toast(result.success ? "连接正常" : result.error);
  } catch (error) {
    setConnectionState({ connection_status: "失败", last_error: error.message });
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function sendModelTestMessage() {
  if (!state.settingsAgent) return;
  const button = $("#send-model-chat");
  button.disabled = true;
  $("#model-test-reply").textContent = "发送中...";
  try {
    await saveModelConfig();
    const result = await request(`/api/agents/${agentBackendId(state.settingsAgent)}/chat`, {
      method: "POST",
      body: JSON.stringify({ message: $("#model-test-message").value.trim() }),
    });
    $("#model-test-reply").textContent = result.response;
  } catch (error) {
    $("#model-test-reply").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function collaborativeReply(input) {
  const point = currentPoint();
  const sequence = [
    ["perception", `收到。先补充现场上下文：当前时段负荷约${Math.round(point.load_kw)} kW、光伏${Math.round(point.pv_kw)} kW。我会先判断“${input}”是否改变了原任务，并检查数据有没有冲突。`],
    ["dispatch", "我先不急着给结论。等感知核验完成后，我会同时比较安全均衡、经济优先和保守保供方案，把代价和收益摆在一起。"],
    ["audit", "候选方案可以生成，但不能自己证明自己安全。我会独立复算硬约束，并拿原EMS策略做同口径比较。"],
    ["execute", "明白。我先保持待命。只有审核结论和人工门禁都满足，我才会进入模拟执行；真实设备接口目前关闭。"],
  ];
  sequence.forEach(([agent, text], index) => window.setTimeout(() => addMessage(agent, text), 220 + index * 230));
}

function renderTaskConversation() {
  if (!state.task || state.selectedAgent) return;
  $("#messages").innerHTML = "";
  const plan = selectedPlan();
  const audit = state.task.audits.find((item) => item.plan_id === state.task.selected_plan_id);
  addMessage("perception", `已核验${state.scenario.forecast.length}个时段。数据质量评分${(state.task.perception.quality_score * 100).toFixed(0)}%，原任务${state.task.perception.original_task_valid ? "仍有效" : "已因运行变化失效，已重新定义优先级"}。`);
  addMessage("dispatch", `已生成${state.task.plans.length}套候选方案。当前最低合规成本为¥${plan.metrics.total_cost_yuan.toLocaleString()}，峰值购电${plan.metrics.peak_grid_kw} kW。`);
  addMessage("audit", `独立审核结论：${audit.decision === "requires_approval" ? "硬约束通过，但包含柔性负荷响应，必须人工审批" : "方案通过"}。相对原EMS基线预计节省¥${audit.improvement_yuan.toLocaleString()}。`);
  addMessage("execute", state.task.state === "awaiting_approval" ? "执行门禁保持关闭，等待人工审批；当前真实设备连接数为0。" : "已在本地模拟器完成计划回放和结果确认，未发生生产写入。");
}

function renderTrace() {
  if (!state.task) return;
  $("#trace-count").textContent = `${state.task.trace.length} 项`;
  $("#trace").innerHTML = state.task.trace.map((event) =>
    `<div class="trace-event"><i></i><div><strong>${actionNames[event.action] || event.action}</strong><br><span>${event.actor} · ${event.status}</span></div></div>`
  ).join("");
}

function renderAgentState() {
  if (!state.task) return;
  const completed = state.task.state === "completed";
  $$(".agent-card").forEach((card) => {
    const key = card.dataset.agent;
    card.classList.toggle("running", key === "execute" && !completed);
  });
  const statusNames = {
    awaiting_approval: "等待审批", completed: "模拟完成", safe_fallback: "安全回退",
    human_handoff: "人工接管", rejected: "审批拒绝",
  };
  $("#task-state").textContent = statusNames[state.task.state] || state.task.state;
  $("#task-state").className = `status-pill ${completed ? "done" : "pending"}`;
}

function renderDecision() {
  const plan = selectedPlan();
  if (!plan) return;
  const audit = state.task.audits.find((item) => item.plan_id === plan.plan_id);
  $("#decision-status").textContent = audit.decision === "requires_approval" ? "需人工审批" : "审核通过";
  $("#decision-summary").innerHTML = `<div class="decision-metrics">
    <div><span>选定策略</span><strong>${plan.profile === "balanced" ? "安全均衡" : plan.profile}</strong></div>
    <div><span>独立审核</span><strong>${audit.decision === "rejected" ? "已拦截" : "硬约束通过"}</strong></div>
    <div><span>总成本</span><strong>¥${plan.metrics.total_cost_yuan.toLocaleString()}</strong></div>
    <div><span>执行边界</span><strong>仅本地模拟</strong></div>
  </div>`;
}

function renderTask() {
  state.scenario = state.task.scenario_snapshot;
  $("#scenario-name").textContent = state.scenario.name;
  $("#scenario-description").textContent = state.scenario.description;
  renderLiveData();
  renderTrendChart();
  renderImpact();
  renderTrace();
  renderAgentState();
  renderDecision();
  renderTaskConversation();
  $("#reoptimize-button").hidden = !["completed", "safe_fallback", "human_handoff"].includes(state.task.state);
}

function openApproval(message) {
  $("#approval-summary").textContent = message;
  $("#approval-dialog").showModal();
}

async function runDemo() {
  const button = $("#run-button");
  button.disabled = true;
  button.innerHTML = "<span>•••</span>Agent协商中";
  try {
    state.task = await request("/api/demo/run", { method: "POST" });
    enableCollaboration(true);
    renderTask();
    if (state.task.state === "awaiting_approval") {
      const plan = selectedPlan();
      openApproval(`审核Agent已确认硬约束通过，但方案包含${plan.metrics.shed_energy_kwh} kWh柔性负荷响应。批准只会在本地模拟器回放，不连接真实设备。`);
    }
    toast("四类Agent已完成一轮协同决策");
  } catch (error) { toast(error.message); }
  finally {
    button.disabled = false;
    button.innerHTML = "<span>▶</span>重新运行调度";
  }
}

async function submitApproval(approved) {
  if (!state.task) return;
  try {
    state.task = await request(`/api/tasks/${state.task.task_id}/approval`, {
      method: "POST",
      body: JSON.stringify({ approved, approver: $("#approver").value, reason: $("#approval-reason").value }),
    });
    $("#approval-dialog").close();
    renderTask();
    toast(approved ? "本地模拟执行完成，未连接真实设备" : "审批已拒绝，执行门禁保持关闭");
  } catch (error) { toast(error.message); }
}

async function reoptimize() {
  if (!state.task) return;
  const button = $("#reoptimize-button");
  button.disabled = true;
  try {
    state.task = await request(`/api/tasks/${state.task.task_id}/reoptimize`, {
      method: "POST",
      body: JSON.stringify({
        trigger: "WEATHER_AND_PRODUCTION_PLAN_CHANGED", load_scale: 1.06, pv_scale: .78,
        soc_delta: -.04, battery_available: true, transformer_temperature_c: 84,
        transformer_redundant_temperature_c: 82, emergency_production: true,
      }),
    });
    enableCollaboration(true);
    renderTask();
    if (state.task.state === "human_handoff") { toast("数据冲突无法自动消解，已交还工程师"); return; }
    openApproval(`变化已创建新任务${state.task.task_id}。旧审批不会复用，新策略必须重新审批。`);
    toast("变化已触发新一轮感知、调度与审核");
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

async function initialize() {
  try {
    loadAvatarStyles();
    const [scenario, health, manifest] = await Promise.all([
      request("/api/demo/scenario"),
      request("/api/health"),
      request("/api/agentteams/manifest"),
    ]);
    if (!health.simulation_mode || health.allow_production_write) throw new Error("安全配置异常，页面已停止运行");
    state.modelConfigs = manifest.model_configs || {};
    state.scenario = scenario;
    $("#scenario-name").textContent = scenario.name;
    $("#scenario-description").textContent = scenario.description;
    renderLiveData();
    renderTrendChart();
    syncAvatarStyles();
    enableCollaboration(false);
  } catch (error) { toast(error.message); }
}

$$(".agent-card").forEach((card) => {
  card.addEventListener("click", () => selectAgent(card.dataset.agent));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") selectAgent(card.dataset.agent);
  });
});
$$("[data-agent-settings]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openModelDialog(button.dataset.agentSettings);
  });
  button.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.stopPropagation();
    event.preventDefault();
    openModelDialog(button.dataset.agentSettings);
  });
});
$("#collaboration-mode").addEventListener("click", () => enableCollaboration(true));
$("#clear-selection").addEventListener("click", () => enableCollaboration(false));
$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#chat-input").value.trim();
  if (!input) return;
  addMessage(null, input, true);
  $("#chat-input").value = "";
  if (state.selectedAgent) agentReply(state.selectedAgent, input);
  else collaborativeReply(input);
});
$("#run-button").addEventListener("click", runDemo);
$("#reoptimize-button").addEventListener("click", reoptimize);
$("#approval-form").addEventListener("submit", (event) => { event.preventDefault(); submitApproval(true); });
$("#reject-button").addEventListener("click", () => submitApproval(false));
$("#close-dialog").addEventListener("click", () => $("#approval-dialog").close());
$("#close-model-dialog").addEventListener("click", () => $("#model-dialog").close());
$("#model-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveModelConfig();
    toast("模型设置已保存");
  } catch (error) { toast(error.message); }
});
$("#test-model-button").addEventListener("click", testModelConnection);
$("#send-model-chat").addEventListener("click", sendModelTestMessage);
$("#random-avatar-button").addEventListener("click", randomizeCurrentAvatar);
$("#reset-camera").addEventListener("click", () => state.campus3d?.reset());
$$(".panel-tab").forEach((tab) => tab.addEventListener("click", () => activatePanel(tab.dataset.panel)));
$$(".splitter").forEach((splitter) => splitter.addEventListener("pointerdown", (event) => startResize(splitter, event)));
setupCardSorting();
window.addEventListener("resize", renderTrendChart);
state.campus3d = createCampus3D($("#campus-3d"), updateAssetLabels);
initialize();
