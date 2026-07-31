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
  playbackIndex: -1,
  playbackTimer: null,
  paused: false,
  campus3d: null,
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
    { label: "负荷", color: "#edf6ff", values: load },
    { label: "光伏", color: "#8ecfff", values: pv },
    { label: "电价", color: "#f2bd5b", values: tariff },
  ];
  const max = Math.max(...series.flatMap((item) => item.values));
  const inset = { left: 30, top: 18, right: 12, bottom: 18 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  context.clearRect(0, 0, width, height);
  context.font = "10px Inter, sans-serif";
  context.strokeStyle = "#2c3a47";
  context.lineWidth = 1;
  for (let row = 0; row <= 4; row += 1) {
    const y = inset.top + (plotHeight * row) / 4;
    context.beginPath();
    context.moveTo(inset.left, y);
    context.lineTo(width - inset.right, y);
    context.stroke();
  }
  const eventX = inset.left + (plotWidth * 56) / 95;
  context.fillStyle = "rgba(239,119,111,.12)";
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
  $("#current-skill").textContent = active?.skill_name || "--";
  $("#evidence-state").textContent = task ? task.state : "IDLE";
  $("#evidence-version").textContent = task ? `V${task.task_version}` : "--";
  $("#context-id").textContent = context?.context_id || "--";
  $("#context-hash").textContent = context?.context_hash ? `${context.context_hash.slice(0, 16)}...` : "--";
  $("#trace-id").textContent = state.run?.trace_id || "--";
  $("#evidence-status").textContent = task?.evidence_sha256 ? "已封存" : state.evidence ? "可查看" : "未生成";
  $("#open-evidence").disabled = !state.task;
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
      <article class="candidate ${rejected ? "rejected" : "approved"}">
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
      </article>
    `;
  }).join("");
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

function openTraceDetail(index) {
  const event = state.events[index];
  if (!event) return;
  $("#trace-dialog-title").textContent = event.event_id;
  $("#trace-json").textContent = JSON.stringify(event, null, 2);
  $("#trace-dialog").showModal();
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

function setupEvents() {
  $("#run-button").addEventListener("click", runDemo);
  $("#approve-b").addEventListener("click", approveCandidateB);
  $("#execute-b").addEventListener("click", executeCandidateB);
  $("#rollback-button").addEventListener("click", runRollback);
  $("#open-evidence").addEventListener("click", openEvidence);
  $("#pause-button").addEventListener("click", () => {
    state.paused = !state.paused;
    $("#pause-button").textContent = state.paused ? "继续播放" : "暂停播放";
  });
  $$("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => $(`#${button.dataset.closeDialog}`).close());
  });
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
  } catch {
    renderTask();
    renderCandidates();
    renderTrace();
  }
}

drawScenarioChart();
setupCampus();
setupEvents();
restoreLatestDemo();
