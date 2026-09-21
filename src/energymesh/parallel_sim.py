from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from energymesh.models import (
    AuditDecision,
    DispatchPlan,
    ExternalDataSnapshot,
    ExternalTelemetryPoint,
    ForecastPoint,
    IntervalHistoryPoint,
    ParallelSimulationState,
    ParallelStepResponse,
    ReoptimizationEvent,
    Scenario,
    TaskState,
)
from energymesh.mcp_auth import ToolCircuitBreaker
from energymesh.observability import SLOMetrics
from energymesh.orchestrator import EnergyMeshOrchestrator
from energymesh.polardb_store import PolarDBStore
from energymesh.rag_engine import RAGEngine
from energymesh.storage import EvidenceStore


class ParallelSimError(ValueError):
    pass


@dataclass
class _IntervalCosts:
    baseline_grid_kwh: float
    baseline_cost_yuan: float
    optimized_grid_kwh: float
    optimized_cost_yuan: float


class ParallelSimulator:
    """Runs a side-by-side comparison: actual CSV baseline vs Agent-optimized dispatch.

    Timeline A (Baseline): uses the actual grid import recorded in the uploaded telemetry.
    Timeline B (Optimized): runs the full AgentTeams workflow (Perception → Dispatch → Audit
    → Auto-approve for demo → Simulated Execution) and computes what the grid import would
    have been under the optimized plan.

    Key feature: monitors forecast deviation at each interval. When actual conditions
    diverge significantly from the plan's assumptions, the system:
    1. Marks the old plan as invalidated
    2. Runs rolling-horizon re-optimization from current interval with actual SOC
    3. Records the re-optimization event with deviation reasons
    4. Continues with the new plan
    """

    # Deviation thresholds for plan invalidation
    PV_DEVIATION_THRESHOLD = 0.18  # 18%
    LOAD_DEVIATION_THRESHOLD = 0.12  # 12%
    SOC_DEVIATION_THRESHOLD = 0.15  # 15% (absolute)

    def __init__(
        self, orchestrator: EnergyMeshOrchestrator, store: EvidenceStore
    ) -> None:
        self.orchestrator = orchestrator
        self.store = store
        self.state = ParallelSimulationState()
        self._lock = threading.Lock()
        self.pdb = PolarDBStore()
        self.rag = RAGEngine()
        self.slo = SLOMetrics()
        self.cb = ToolCircuitBreaker()

    def start(self, snapshot: ExternalDataSnapshot) -> ParallelSimulationState:
        self.state = ParallelSimulationState(
            running=True,
            cursor=0,
            source=snapshot.source,
            snapshot=snapshot,
            speed_mode="virtual",
            interval_ms=1000,
        )
        try:
            self._append_collaboration_trace("team_leader", "delegate", "perception_worker", "读取上传 CSV 形成同一 run_id 的园区状态")
            self._append_collaboration_trace("perception_worker", "ack", "team_leader", "已接入 ExternalDataSnapshot，开始生成 day-ahead 预测")
            planning_scenario = self._planning_scenario(snapshot)
            self._append_collaboration_trace("team_leader", "delegate", "dispatch_worker", "基于历史预测曲线生成 baseline/optimized 候选方案")
            task = self.orchestrator.run(
                planning_scenario,
                trigger="PARALLEL_SIM_OPTIMIZATION",
            )
            task = self._wait_for_task(task.task_id)
            if task.state == TaskState.AWAITING_APPROVAL:
                from energymesh.models import ApprovalRequest

                self._append_collaboration_trace("audit_worker", "submit", "team_leader", "审计通过但需要人工/自动审批后才能执行")
                task = self.orchestrator.approve_only(
                    task.task_id,
                    ApprovalRequest(
                        approved=True,
                        approver="parallel-sim-auto",
                        reason="Parallel simulation auto-approval for cost comparison demo",
                    ),
                )
                self._append_collaboration_trace("approval_gate", "accept", "execution_worker", "审批通过，执行 Worker 获得一次性执行权限")
                task = self.orchestrator.execute_approved(task.task_id)
                task = self._wait_for_task(task.task_id)
            self.state.optimized_task = task
            if task.selected_plan_id and task.plans:
                self.state.optimized_plan = next(
                    (p for p in task.plans if p.plan_id == task.selected_plan_id),
                    None,
                )
            self._append_collaboration_trace("execution_worker", "submit", "team_leader", "执行映射完成，等待回读逐时段校验")
            self.state.agentteams_trace.append(
                {
                    "source": "optimizer_sim",
                    "step": "optimization_complete",
                    "task_id": task.task_id,
                    "plan_id": task.selected_plan_id,
                    "state": task.state.value,
                    "agents": ["perception", "dispatch", "audit", "execution"],
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            self.state.last_event = "AgentTeams优化完成，开始平行对比"
        except Exception as error:
            self.state.last_event = f"AgentTeams优化失败: {error}"
            self.state.agentteams_trace.append(
                {
                    "source": "optimizer_sim",
                    "step": "optimization_failed",
                    "error": str(error),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        return self.state

    def _wait_for_task(self, task_id: str, timeout_s: float = 8.0) -> Any:
        terminal = {
            TaskState.AWAITING_APPROVAL,
            TaskState.APPROVED,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.ROLLBACK,
        }
        deadline = time.time() + timeout_s
        task = self.store.get(task_id)
        while task is not None and task.state not in terminal and time.time() < deadline:
            time.sleep(0.05)
            task = self.store.get(task_id)
        return task or self.store.get(task_id)

    def _planning_scenario(self, snapshot: ExternalDataSnapshot) -> Scenario:
        """Build the plan-time forecast from historical telemetry, then replay actual telemetry.

        This keeps one uploaded dataset as the source of truth while separating what the
        optimizer knew at plan time from what the plant actually did during replay.
        """
        telemetry = snapshot.telemetry
        if not telemetry:
            return snapshot.scenario
        forecast: list[ForecastPoint] = []
        for index, point in enumerate(telemetry):
            lag = telemetry[max(0, index - 4)]
            if index < 24:
                load_kw = point.load_kw
                pv_kw = point.pv_kw
            else:
                load_kw = max(0.0, lag.load_kw)
                pv_kw = max(0.0, lag.pv_kw)
            production_min = min(point.production_min_load_kw, load_kw * 0.72)
            forecast.append(
                ForecastPoint(
                    timestamp=point.timestamp,
                    load_kw=load_kw,
                    pv_kw=pv_kw,
                    production_min_load_kw=production_min,
                    tariff_yuan_per_kwh=point.tariff_yuan_per_kwh,
                    battery_temperature_c=point.transformer_temperature_c,
                    transformer_temperature_c=point.transformer_temperature_c,
                    transformer_redundant_temperature_c=point.transformer_temperature_c,
                )
            )
        return snapshot.scenario.model_copy(
            update={
                "forecast": forecast,
                "description": (
                    f"{snapshot.scenario.description} Plan-time forecast is derived "
                    "from prior observed intervals; actual replay still consumes the uploaded telemetry."
                ),
            }
        )

    def _append_collaboration_trace(
        self, actor: str, step: str, target: str, message: str, **detail: Any
    ) -> None:
        self.state.agentteams_trace.append(
            {
                "source": "backend_run_state",
                "actor": actor,
                "step": step,
                "target": target,
                "message": message,
                "timestamp": datetime.now(UTC).isoformat(),
                **detail,
            }
        )

    def step(self) -> ParallelStepResponse:
        with self._lock:
            return self._step_impl()

    def _step_impl(self) -> ParallelStepResponse:
        if not self.state.running or self.state.snapshot is None:
            raise ParallelSimError("parallel simulation not running")
        telemetry = self.state.snapshot.telemetry
        if self.state.cursor >= len(telemetry):
            self.state.running = False
            self.state.last_event = "平行对比完成"
            return self._build_response()

        point = telemetry[self.state.cursor]

        # Check for forecast deviation and potentially re-optimize
        self._check_and_reoptimize_if_needed(point)

        costs = self._compute_interval_costs(point)

        self.state.baseline_cumulative_cost_yuan += costs.baseline_cost_yuan
        self.state.baseline_cumulative_grid_kwh += costs.baseline_grid_kwh
        self.state.optimized_cumulative_cost_yuan += costs.optimized_cost_yuan
        self.state.optimized_cumulative_grid_kwh += costs.optimized_grid_kwh

        savings = max(
            0,
            self.state.baseline_cumulative_cost_yuan
            - self.state.optimized_cumulative_cost_yuan,
        )
        savings_pct = (
            (savings / self.state.baseline_cumulative_cost_yuan * 100)
            if self.state.baseline_cumulative_cost_yuan > 0
            else 0.0
        )
        self.state.savings_yuan = savings
        self.state.savings_percent = round(savings_pct, 2)

        # Build forecast deviation info
        plan_point = None
        if self.state.optimized_plan and self.state.optimized_plan.points:
            plan_point = next(
                (
                    p
                    for p in self.state.optimized_plan.points
                    if p.interval == point.interval
                ),
                None,
            )

        pv_forecast = plan_point.pv_kw if plan_point else point.pv_kw
        load_forecast = plan_point.load_kw if plan_point else point.load_kw
        pv_dev = (
            ((point.pv_kw - pv_forecast) / pv_forecast * 100)
            if pv_forecast > 0.01
            else 0.0
        )
        load_dev = (
            ((point.load_kw - load_forecast) / load_forecast * 100)
            if load_forecast > 0.01
            else 0.0
        )

        # Determine if this interval had a re-optimization
        reoptimized = False
        plan_invalidated = False
        reoptimize_reason = ""
        new_plan_id = None
        for event in self.state.reoptimization_events:
            if event.interval == self.state.cursor:
                reoptimized = True
                plan_invalidated = True
                reoptimize_reason = event.reason
                new_plan_id = event.new_plan_id

        history_point = IntervalHistoryPoint(
            interval=self.state.cursor,
            timestamp=(
                point.timestamp.isoformat()
                if hasattr(point.timestamp, "isoformat")
                else str(point.timestamp)
            ),
            tariff_yuan_per_kwh=point.tariff_yuan_per_kwh,
            baseline_interval_cost_yuan=round(costs.baseline_cost_yuan, 4),
            optimized_interval_cost_yuan=round(costs.optimized_cost_yuan, 4),
            baseline_cumulative_cost_yuan=round(
                self.state.baseline_cumulative_cost_yuan, 4
            ),
            optimized_cumulative_cost_yuan=round(
                self.state.optimized_cumulative_cost_yuan, 4
            ),
            savings_cumulative_yuan=round(savings, 4),
            actual_load_kw=round(point.load_kw, 2),
            actual_pv_kw=round(point.pv_kw, 2),
            actual_grid_kw=round(getattr(point, "grid_import_kw", 0), 2),
            optimized_grid_kw=round(plan_point.grid_import_kw if plan_point else 0, 2),
            actual_soc=round(point.battery_soc, 4),
            pv_forecast_kw=round(pv_forecast, 2),
            load_forecast_kw=round(load_forecast, 2),
            pv_deviation_percent=round(pv_dev, 2),
            load_deviation_percent=round(load_dev, 2),
            reoptimized=reoptimized,
            plan_invalidated=plan_invalidated,
            reoptimize_reason=reoptimize_reason,
            new_plan_id=new_plan_id,
        )
        self.state.interval_history.append(history_point)

        # Add dispatch detail trace so frontend can show what Agent decided
        self.state.agentteams_trace.append(
            {
                "source": "optimizer_sim",
                "step": "interval_dispatch",
                "interval": point.interval,
                "load_kw": round(point.load_kw, 2),
                "pv_kw": round(point.pv_kw, 2),
                "grid_import_kw": round(getattr(point, "grid_import_kw", 0), 2),
                "optimized_grid_kw": round(
                    plan_point.grid_import_kw if plan_point else 0, 2
                ),
                "optimized_charge_kw": round(
                    plan_point.charge_kw if plan_point else 0, 2
                ),
                "optimized_discharge_kw": round(
                    plan_point.discharge_kw if plan_point else 0, 2
                ),
                "soc_start": (
                    round(plan_point.soc_start, 3)
                    if plan_point
                    else round(point.battery_soc, 3)
                ),
                "soc_end": (
                    round(plan_point.soc_end, 3)
                    if plan_point
                    else round(point.battery_soc, 3)
                ),
                "baseline_cost": round(costs.baseline_cost_yuan, 4),
                "optimized_cost": round(costs.optimized_cost_yuan, 4),
            }
        )

        # Persist to PolarDB + SLO
        if point:
            self.pdb.write_telemetry(self.state.source, point)
            if self.state.optimized_task:
                self.pdb.write_execution(
                    execution_id=f"exec_{self.state.source}_{point.interval}",
                    task_id=self.state.optimized_task.task_id,
                    plan_version_id=(
                        self.state.optimized_plan.plan_id
                        if self.state.optimized_plan
                        else None
                    ),
                    interval=point.interval,
                    actual={
                        "grid_kw": getattr(point, "grid_import_kw", 0),
                        "soc": point.battery_soc,
                    },
                    expected={
                        "grid_kw": plan_point.grid_import_kw if plan_point else 0,
                        "soc": plan_point.soc_end if plan_point else point.battery_soc,
                    },
                    deviation=reoptimized,
                )
        self.slo.record_execution()
        self.slo.record_savings(self.state.savings_yuan)

        self.state.cursor += 1
        if self.state.cursor >= len(telemetry):
            self.state.running = False
            self.state.last_event = "平行对比完成"
        else:
            self.state.last_event = f"时段 {self.state.cursor - 1} 处理完成"

        return self._build_response()

    def _check_and_reoptimize_if_needed(self, point: ExternalTelemetryPoint) -> None:
        """Detect forecast deviation and trigger rolling re-optimization if needed."""
        if not self.state.optimized_plan or not self.state.optimized_plan.points:
            return

        plan_point = next(
            (
                p
                for p in self.state.optimized_plan.points
                if p.interval == point.interval
            ),
            None,
        )
        if not plan_point:
            return

        # Calculate deviations
        pv_forecast = plan_point.pv_kw
        load_forecast = plan_point.load_kw
        pv_dev = (
            abs((point.pv_kw - pv_forecast) / pv_forecast)
            if pv_forecast > 0.01
            else 0.0
        )
        load_dev = (
            abs((point.load_kw - load_forecast) / load_forecast)
            if load_forecast > 0.01
            else 0.0
        )
        soc_dev = abs(point.battery_soc - plan_point.soc_end)

        # Determine if re-optimization is needed
        reasons = []
        if pv_dev > self.PV_DEVIATION_THRESHOLD:
            reasons.append(
                f"PV实际({point.pv_kw:.2f}kW)偏离预测({pv_forecast:.2f}kW) {pv_dev*100:.1f}%"
            )
        if load_dev > self.LOAD_DEVIATION_THRESHOLD:
            reasons.append(
                f"负荷实际({point.load_kw:.2f}kW)偏离预测({load_forecast:.2f}kW) {load_dev*100:.1f}%"
            )
        if soc_dev > self.SOC_DEVIATION_THRESHOLD:
            reasons.append(
                f"SOC实际({point.battery_soc:.1%})偏离计划({plan_point.soc_end:.1%})"
            )

        if not reasons:
            self.state.agentteams_trace.append(
                {
                    "source": "optimizer_sim",
                    "step": "perception_observation",
                    "interval": point.interval,
                    "pv_actual": round(point.pv_kw, 2),
                    "pv_forecast": round(pv_forecast, 2),
                    "pv_deviation_percent": round(pv_dev * 100, 2),
                    "load_actual": round(point.load_kw, 2),
                    "load_forecast": round(load_forecast, 2),
                    "load_deviation_percent": round(load_dev * 100, 2),
                    "soc_actual": round(point.battery_soc * 100, 1),
                    "soc_plan": round(plan_point.soc_start * 100, 1),
                    "soc_deviation_percent": round(soc_dev * 100, 2),
                    "status": "normal",
                }
            )
            return

        # Threshold exceeded - perception reports anomaly
        self.state.agentteams_trace.append(
            {
                "source": "optimizer_sim",
                "step": "perception_observation",
                "interval": point.interval,
                "pv_actual": round(point.pv_kw, 2),
                "pv_forecast": round(pv_forecast, 2),
                "pv_deviation_percent": round(pv_dev * 100, 2),
                "load_actual": round(point.load_kw, 2),
                "load_forecast": round(load_forecast, 2),
                "load_deviation_percent": round(load_dev * 100, 2),
                "soc_actual": round(point.battery_soc * 100, 1),
                "soc_plan": round(plan_point.soc_start * 100, 1),
                "soc_deviation_percent": round(soc_dev * 100, 2),
                "status": "threshold_exceeded",
                "reasons": reasons,
            }
        )

        # Plan invalidated - trigger rolling re-optimization
        old_plan_id = (
            self.state.optimized_plan.plan_id if self.state.optimized_plan else None
        )
        try:
            from energymesh.models import RollingHorizonRequest

            new_task = self.orchestrator.rolling_reoptimize(
                (
                    self.state.optimized_task.task_id
                    if self.state.optimized_task
                    else "unknown"
                ),
                RollingHorizonRequest(
                    current_interval=point.interval,
                    actual_soc=point.battery_soc,
                    robustness_mode="expected_value",
                    trigger=f"forecast_deviation_interval_{point.interval}",
                ),
            )
            # Update the optimized plan
            if new_task.selected_plan_id and new_task.plans:
                new_plan = next(
                    (
                        p
                        for p in new_task.plans
                        if p.plan_id == new_task.selected_plan_id
                    ),
                    None,
                )
                if new_plan:
                    self.state.optimized_plan = new_plan
                    self.state.optimized_task = new_task
                    self.state.plans_invalidated += 1
                    self.state.total_reoptimizations += 1

                    event = ReoptimizationEvent(
                        interval=point.interval,
                        timestamp=(
                            point.timestamp.isoformat()
                            if hasattr(point.timestamp, "isoformat")
                            else str(point.timestamp)
                        ),
                        reason="；".join(reasons),
                        old_plan_id=old_plan_id,
                        new_plan_id=new_plan.plan_id,
                        pv_deviation_percent=round(pv_dev * 100, 2),
                        load_deviation_percent=round(load_dev * 100, 2),
                        soc_deviation_percent=round(soc_dev * 100, 2),
                    )
                    self.state.reoptimization_events.append(event)
                    self.state.agentteams_trace.append(
                        {
                            "source": "optimizer_sim",
                            "step": "plan_invalidated_and_reoptimized",
                            "interval": point.interval,
                            "reasons": reasons,
                            "old_plan_id": old_plan_id,
                            "new_plan_id": new_plan.plan_id,
                            "agents": ["perception", "dispatch", "audit", "execution"],
                        }
                    )
                    self.state.agentteams_trace.append(
                        {
                            "source": "optimizer_sim",
                            "step": "dispatch_reoptimization_complete",
                            "interval": point.interval,
                            "new_plan_id": new_plan.plan_id,
                            "agents": ["perception", "dispatch", "audit"],
                        }
                    )
                    self.state.last_event = f"时段 {point.interval}: 计划失效并重新优化"
        except Exception as error:
            # Re-optimization failed, continue with existing plan but record the event
            self.state.agentteams_trace.append(
                {
                    "source": "optimizer_sim",
                    "step": "reoptimize_failed",
                    "interval": point.interval,
                    "error": str(error),
                }
            )

    def status(self) -> ParallelStepResponse:
        return self._build_response()

    def _compute_interval_costs(self, point: ExternalTelemetryPoint) -> _IntervalCosts:
        dt = (
            self.state.snapshot.scenario.site.interval_minutes / 60
            if self.state.snapshot
            else 0.25
        )
        tariff = point.tariff_yuan_per_kwh

        baseline_grid_kw = getattr(point, "grid_import_kw", None)
        if baseline_grid_kw is None:
            baseline_grid_kw = max(0, point.load_kw - point.pv_kw)
        baseline_grid_kwh = baseline_grid_kw * dt
        baseline_cost = baseline_grid_kwh * tariff

        optimized_grid_kw = baseline_grid_kw
        if self.state.optimized_plan and self.state.optimized_plan.points:
            plan_point = next(
                (
                    p
                    for p in self.state.optimized_plan.points
                    if p.interval == point.interval
                ),
                None,
            )
            if plan_point:
                optimized_grid_kw = plan_point.grid_import_kw
        optimized_grid_kwh = optimized_grid_kw * dt
        optimized_cost = optimized_grid_kwh * tariff

        return _IntervalCosts(
            baseline_grid_kwh=baseline_grid_kwh,
            baseline_cost_yuan=baseline_cost,
            optimized_grid_kwh=optimized_grid_kwh,
            optimized_cost_yuan=optimized_cost,
        )

    def _build_response(self) -> ParallelStepResponse:
        point = None
        if self.state.snapshot and self.state.cursor < len(
            self.state.snapshot.telemetry
        ):
            point = self.state.snapshot.telemetry[self.state.cursor]
        elif self.state.snapshot and self.state.snapshot.telemetry:
            point = self.state.snapshot.telemetry[-1]

        opt_grid_kw = 0.0
        if self.state.optimized_plan and point:
            pp = next(
                (
                    p
                    for p in self.state.optimized_plan.points
                    if p.interval == point.interval
                ),
                None,
            )
            if pp:
                opt_grid_kw = pp.grid_import_kw

        return ParallelStepResponse(
            cursor=self.state.cursor,
            running=self.state.running,
            baseline_cost_yuan=round(self.state.baseline_cumulative_cost_yuan, 2),
            optimized_cost_yuan=round(self.state.optimized_cumulative_cost_yuan, 2),
            savings_yuan=round(self.state.savings_yuan, 2),
            savings_percent=self.state.savings_percent,
            baseline_grid_kwh=round(self.state.baseline_cumulative_grid_kwh, 2),
            optimized_grid_kwh=round(self.state.optimized_cumulative_grid_kwh, 2),
            current_load_kw=round(point.load_kw, 2) if point else 0,
            current_pv_kw=round(point.pv_kw, 2) if point else 0,
            current_grid_kw=(
                round(getattr(point, "grid_import_kw", 0), 2) if point else 0
            ),
            optimized_grid_kw=round(opt_grid_kw, 2),
            current_soc=round(point.battery_soc, 3) if point else 0,
            agentteams_active=self.state.optimized_task is not None,
            task_state=(
                self.state.optimized_task.state.value
                if self.state.optimized_task
                else "none"
            ),
            event=self.state.last_event,
            interval_history=self.state.interval_history,
            reoptimization_events=self.state.reoptimization_events,
            total_reoptimizations=self.state.total_reoptimizations,
            plans_invalidated=self.state.plans_invalidated,
            agentteams_trace=self.state.agentteams_trace,
        )

    def get_slo(self) -> dict[str, object]:
        return self.slo.health()

    def get_rag_insight(self, interval: int | None = None) -> str:
        if not self.state.interval_history:
            return "暂无偏差记录"
        idx = interval if interval is not None else len(self.state.interval_history) - 1
        if idx < 0 or idx >= len(self.state.interval_history):
            return "时段索引越界"
        h = self.state.interval_history[idx]
        event = {
            "pv_deviation_percent": h.pv_deviation_percent,
            "load_deviation_percent": h.load_deviation_percent,
            "soc_deviation_percent": 0,
        }
        return self.rag.get_insight_for_deviation(event)
