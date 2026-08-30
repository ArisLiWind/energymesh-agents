from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from energymesh.models import (
    DispatchPlan,
    DispatchPoint,
    ForecastPoint,
    PlanMetrics,
    Scenario,
)


@dataclass(frozen=True)
class OptimizationProfile:
    name: str
    min_soc: float
    max_shed_fraction: float
    discharge_factor: float
    rationale: str


PROFILES = (
    OptimizationProfile(
        name="economic_aggressive",
        min_soc=0.15,
        max_shed_fraction=0.12,
        discharge_factor=1.0,
        rationale="压低经济成本的压力测试候选，故意暴露低 SOC 储备风险供独立审计。",
    ),
    OptimizationProfile(
        name="balanced",
        min_soc=0.20,
        max_shed_fraction=0.08,
        discharge_factor=1.0,
        rationale="在电池安全、最大需量与有限柔性负荷响应之间取得平衡。",
    ),
    OptimizationProfile(
        name="conservative",
        min_soc=0.32,
        max_shed_fraction=0.0,
        discharge_factor=0.65,
        rationale="保留更多电池余量且不削减柔性负荷，优先保障连续生产。",
    ),
)


class DispatchOptimizer:
    """Numerical optimization only; it has no execution or approval capability."""

    def rolling_reoptimize(
        self,
        scenario: Scenario,
        current_interval: int,
        actual_soc: float,
        previous_plan: DispatchPlan | None = None,
        robustness_mode: str = "worst_case",
    ) -> DispatchPlan:
        """Re-optimize remaining horizon [current_interval, end] anchored at actual SOC.

        Args:
            scenario: Full scenario with 96-point forecast (including uncertainty bands).
            current_interval: Interval index where rolling optimization starts.
            actual_soc: Measured SOC at the start of current_interval.
            previous_plan: Previously selected plan (to fix executed intervals).
            robustness_mode:
                - worst_case: use load_kw_upper and pv_kw_lower for remaining intervals.
                - expected_value: use nominal load_kw and pv_kw.
                - ignore: same as expected_value.
        """
        site = scenario.site
        total = len(scenario.forecast)
        if current_interval >= total - 1:
            # Nothing left to optimize; return a minimal safe plan.
            return self._safe_fallback_plan(scenario, current_interval, actual_soc)

        remaining = total - current_interval
        dt = site.interval_minutes / 60

        # Build effective forecast for remaining intervals based on robustness mode.
        effective_forecast: list[ForecastPoint] = []
        for idx, point in enumerate(scenario.forecast):
            if idx < current_interval:
                # Executed intervals: keep nominal (not used in optimization variables).
                effective_forecast.append(point)
            else:
                # Remaining intervals: apply uncertainty bounds.
                load_eff = point.load_kw
                pv_eff = point.pv_kw
                if robustness_mode == "worst_case":
                    load_eff = getattr(point, "load_kw_upper", point.load_kw * 1.08)
                    pv_eff = getattr(point, "pv_kw_lower", point.pv_kw * 0.82)
                effective_forecast.append(
                    point.model_copy(
                        update={
                            "load_kw": max(0.0, load_eff),
                            "pv_kw": max(0.0, pv_eff),
                        }
                    )
                )

        # Variables per remaining interval: charge, discharge, grid, curtail, shed.
        charge, discharge, grid, curtail, shed = (i * remaining for i in range(5))
        soc = 5 * remaining
        peak = soc + remaining + 1
        variable_count = peak + 1

        objective = np.zeros(variable_count)
        prices = np.array(
            [p.tariff_yuan_per_kwh for p in effective_forecast[current_interval:]]
        )
        objective[charge : charge + remaining] = site.degradation_yuan_per_kwh * dt
        objective[discharge : discharge + remaining] = (
            site.degradation_yuan_per_kwh * dt
        )
        objective[grid : grid + remaining] = prices * dt
        objective[curtail : curtail + remaining] = 0.01 * dt
        objective[shed : shed + remaining] = 1.2 * dt
        objective[peak] = site.demand_charge_yuan_per_kw

        lower = np.zeros(variable_count)
        upper = np.full(variable_count, np.inf)
        upper[charge : charge + remaining] = site.battery_charge_max_kw
        upper[discharge : discharge + remaining] = site.battery_discharge_max_kw
        upper[grid : grid + remaining] = np.array(
            [
                min(
                    (
                        site.transformer_capacity_kw
                        * site.transformer_hot_derate_factor
                        if (
                            point.transformer_temperature_c
                            >= site.transformer_temperature_limit_c
                            and point.transformer_redundant_temperature_c
                            >= site.transformer_temperature_limit_c
                        )
                        else site.transformer_capacity_kw
                    ),
                    site.grid_interconnection_limit_kw,
                )
                for point in effective_forecast[current_interval:]
            ]
        )
        upper[curtail : curtail + remaining] = np.array(
            [p.pv_kw for p in effective_forecast[current_interval:]]
        )
        upper[shed : shed + remaining] = np.array(
            [
                min(
                    site.flexible_load_kw * 0.10,
                    point.load_kw - point.production_min_load_kw,
                )
                for point in effective_forecast[current_interval:]
            ]
        )
        lower[soc : soc + remaining + 1] = site.safety_min_soc
        upper[soc : soc + remaining + 1] = site.safety_max_soc
        lower[soc] = upper[soc] = actual_soc
        # Penalize ending SOC too far below initial; encourage reserve.
        lower[soc + remaining] = max(site.safety_min_soc, actual_soc - 0.05)

        equality = lil_matrix((2 * remaining, variable_count))
        rhs = np.zeros(2 * remaining)
        for offset, point in enumerate(effective_forecast[current_interval:]):
            equality[offset, grid + offset] = 1
            equality[offset, discharge + offset] = 1
            equality[offset, charge + offset] = -1
            equality[offset, curtail + offset] = -1
            equality[offset, shed + offset] = 1
            rhs[offset] = point.load_kw - point.pv_kw

            row = remaining + offset
            equality[row, soc + offset + 1] = 1
            equality[row, soc + offset] = -1
            equality[row, charge + offset] = (
                -site.battery_efficiency_charge * dt / site.battery_capacity_kwh
            )
            equality[row, discharge + offset] = dt / (
                site.battery_efficiency_discharge * site.battery_capacity_kwh
            )

        peak_constraint = lil_matrix((remaining, variable_count))
        for offset in range(remaining):
            peak_constraint[offset, grid + offset] = 1
            peak_constraint[offset, peak] = -1

        result = milp(
            c=objective,
            integrality=None,
            bounds=Bounds(lower, upper),
            constraints=[
                LinearConstraint(equality.tocsr(), rhs, rhs),
                LinearConstraint(peak_constraint.tocsr(), -np.inf, 0),
            ],
            options={"time_limit": 10.0},
        )
        if not result.success or result.x is None:
            # Optimization failed; fall back to safe baseline for remaining intervals.
            return self._safe_fallback_plan(scenario, current_interval, actual_soc)

        values = result.x
        # Compose full 96-point plan: executed intervals from previous plan,
        # remaining intervals from new optimization.
        points: list[DispatchPoint] = []
        for idx, point in enumerate(scenario.forecast):
            if idx < current_interval and previous_plan is not None:
                # Copy executed interval from previous plan.
                prev = previous_plan.points[idx]
                points.append(prev)
            else:
                offset = idx - current_interval
                points.append(
                    DispatchPoint(
                        interval=idx,
                        timestamp=point.timestamp,
                        load_kw=round(point.load_kw, 4),
                        pv_kw=round(point.pv_kw, 4),
                        charge_kw=round(values[charge + offset], 4),
                        discharge_kw=round(values[discharge + offset], 4),
                        grid_import_kw=round(values[grid + offset], 4),
                        pv_curtailment_kw=round(values[curtail + offset], 4),
                        flexible_load_shed_kw=round(values[shed + offset], 4),
                        soc_start=round(values[soc + offset], 6),
                        soc_end=round(values[soc + offset + 1], 6),
                    )
                )

        metrics = self._calculate_metrics(scenario, points)
        return DispatchPlan(
            plan_id=f"rolling_{uuid4().hex[:12]}",
            profile=f"rolling_{robustness_mode}",
            rationale=f"滚动时域重优化：从第{current_interval}时段锚定实际SOC={actual_soc:.2%}，"
            f"对剩余{remaining}个时段使用{robustness_mode}鲁棒性模式。",
            declared_min_soc=site.safety_min_soc,
            points=points,
            metrics=metrics,
            solver_status=str(result.message),
        )

    def _safe_fallback_plan(
        self, scenario: Scenario, current_interval: int, actual_soc: float
    ) -> DispatchPlan:
        """Construct a zero-battery-dispatch safe plan for remaining intervals."""
        site = scenario.site
        points: list[DispatchPoint] = []
        for idx, forecast in enumerate(scenario.forecast):
            if idx < current_interval:
                # Not used in fallback, but keep structure consistent.
                points.append(
                    DispatchPoint(
                        interval=idx,
                        timestamp=forecast.timestamp,
                        load_kw=forecast.load_kw,
                        pv_kw=forecast.pv_kw,
                        charge_kw=0,
                        discharge_kw=0,
                        grid_import_kw=max(0.0, forecast.load_kw - forecast.pv_kw),
                        pv_curtailment_kw=max(0.0, -forecast.load_kw + forecast.pv_kw),
                        flexible_load_shed_kw=0,
                        soc_start=(
                            actual_soc if idx == current_interval else site.initial_soc
                        ),
                        soc_end=(
                            actual_soc if idx == current_interval else site.initial_soc
                        ),
                    )
                )
            else:
                net_load = forecast.load_kw - forecast.pv_kw
                points.append(
                    DispatchPoint(
                        interval=idx,
                        timestamp=forecast.timestamp,
                        load_kw=forecast.load_kw,
                        pv_kw=forecast.pv_kw,
                        charge_kw=0,
                        discharge_kw=0,
                        grid_import_kw=max(0.0, net_load),
                        pv_curtailment_kw=max(0.0, -net_load),
                        flexible_load_shed_kw=0,
                        soc_start=actual_soc,
                        soc_end=actual_soc,
                    )
                )
        return DispatchPlan(
            plan_id=f"fallback_{uuid4().hex[:12]}",
            profile="safe_fallback",
            rationale="滚动优化失败或已无剩余时段，退回零充放电安全策略。",
            declared_min_soc=site.safety_min_soc,
            points=points,
            metrics=self._calculate_metrics(scenario, points),
            solver_status="deterministic safe fallback",
        )

    def build_baseline(self, scenario: Scenario) -> DispatchPlan:
        """Represents the original EMS policy: PV self-use, no battery dispatch."""
        site = scenario.site
        points: list[DispatchPoint] = []
        for index, forecast in enumerate(scenario.forecast):
            net_load = forecast.load_kw - forecast.pv_kw
            points.append(
                DispatchPoint(
                    interval=index,
                    timestamp=forecast.timestamp,
                    load_kw=forecast.load_kw,
                    pv_kw=forecast.pv_kw,
                    charge_kw=0,
                    discharge_kw=0,
                    grid_import_kw=round(max(0.0, net_load), 4),
                    pv_curtailment_kw=round(max(0.0, -net_load), 4),
                    flexible_load_shed_kw=0,
                    soc_start=site.initial_soc,
                    soc_end=site.initial_soc,
                )
            )
        return DispatchPlan(
            plan_id=f"baseline_{uuid4().hex[:12]}",
            profile="preconfigured_ems_baseline",
            rationale="原 EMS 固定策略：光伏自用、储能不参与动态充放电、生产负荷不调整。",
            declared_min_soc=site.safety_min_soc,
            points=points,
            metrics=self._calculate_metrics(scenario, points),
            solver_status="deterministic preconfigured policy",
        )

    def optimize_candidates(self, scenario: Scenario) -> list[DispatchPlan]:
        return [self.optimize(scenario, profile) for profile in PROFILES]

    def optimize(
        self, scenario: Scenario, profile: OptimizationProfile
    ) -> DispatchPlan:
        site = scenario.site
        count = len(scenario.forecast)
        dt = site.interval_minutes / 60
        # Variables per interval: charge, discharge, grid, PV curtailment, load shed.
        charge, discharge, grid, curtail, shed = (i * count for i in range(5))
        soc = 5 * count
        peak = soc + count + 1
        variable_count = peak + 1

        objective = np.zeros(variable_count)
        prices = np.array([p.tariff_yuan_per_kwh for p in scenario.forecast])
        objective[charge : charge + count] = site.degradation_yuan_per_kwh * dt
        objective[discharge : discharge + count] = site.degradation_yuan_per_kwh * dt
        objective[grid : grid + count] = prices * dt
        objective[curtail : curtail + count] = 0.01 * dt
        objective[shed : shed + count] = 1.2 * dt
        objective[peak] = site.demand_charge_yuan_per_kw

        lower = np.zeros(variable_count)
        upper = np.full(variable_count, np.inf)
        upper[charge : charge + count] = site.battery_charge_max_kw
        discharge_limits = np.full(
            count, site.battery_discharge_max_kw * profile.discharge_factor
        )
        for index, point in enumerate(scenario.forecast):
            if point.battery_temperature_c >= 45:
                discharge_limits[index] *= site.alarm_discharge_derate
        upper[discharge : discharge + count] = discharge_limits
        upper[grid : grid + count] = np.array(
            [
                min(
                    (
                        site.transformer_capacity_kw
                        * site.transformer_hot_derate_factor
                        if (
                            point.transformer_temperature_c
                            >= site.transformer_temperature_limit_c
                            and point.transformer_redundant_temperature_c
                            >= site.transformer_temperature_limit_c
                        )
                        else site.transformer_capacity_kw
                    ),
                    site.grid_interconnection_limit_kw,
                )
                for point in scenario.forecast
            ]
        )
        upper[curtail : curtail + count] = np.array(
            [p.pv_kw for p in scenario.forecast]
        )
        upper[shed : shed + count] = np.array(
            [
                min(
                    site.flexible_load_kw * profile.max_shed_fraction,
                    point.load_kw - point.production_min_load_kw,
                )
                for point in scenario.forecast
            ]
        )
        lower[soc : soc + count + 1] = profile.min_soc
        upper[soc : soc + count + 1] = site.safety_max_soc
        lower[soc] = upper[soc] = site.initial_soc
        lower[soc + count] = max(profile.min_soc, site.initial_soc - 0.03)

        equality = lil_matrix((2 * count, variable_count))
        rhs = np.zeros(2 * count)
        for index, point in enumerate(scenario.forecast):
            equality[index, grid + index] = 1
            equality[index, discharge + index] = 1
            equality[index, charge + index] = -1
            equality[index, curtail + index] = -1
            equality[index, shed + index] = 1
            rhs[index] = point.load_kw - point.pv_kw

            row = count + index
            equality[row, soc + index + 1] = 1
            equality[row, soc + index] = -1
            equality[row, charge + index] = (
                -site.battery_efficiency_charge * dt / site.battery_capacity_kwh
            )
            equality[row, discharge + index] = dt / (
                site.battery_efficiency_discharge * site.battery_capacity_kwh
            )

        peak_constraint = lil_matrix((count, variable_count))
        for index in range(count):
            peak_constraint[index, grid + index] = 1
            peak_constraint[index, peak] = -1

        result = milp(
            c=objective,
            integrality=None,
            bounds=Bounds(lower, upper),
            constraints=[
                LinearConstraint(equality.tocsr(), rhs, rhs),
                LinearConstraint(peak_constraint.tocsr(), -np.inf, 0),
            ],
            options={"time_limit": 10.0},
        )
        if not result.success or result.x is None:
            raise RuntimeError(f"dispatch optimization failed: {result.message}")

        values = result.x
        points: list[DispatchPoint] = []
        for index, forecast in enumerate(scenario.forecast):
            points.append(
                DispatchPoint(
                    interval=index,
                    timestamp=forecast.timestamp,
                    load_kw=round(forecast.load_kw, 4),
                    pv_kw=round(forecast.pv_kw, 4),
                    charge_kw=round(values[charge + index], 4),
                    discharge_kw=round(values[discharge + index], 4),
                    grid_import_kw=round(values[grid + index], 4),
                    pv_curtailment_kw=round(values[curtail + index], 4),
                    flexible_load_shed_kw=round(values[shed + index], 4),
                    soc_start=round(values[soc + index], 6),
                    soc_end=round(values[soc + index + 1], 6),
                )
            )

        metrics = self._calculate_metrics(scenario, points)
        return DispatchPlan(
            plan_id=f"plan_{uuid4().hex[:12]}",
            profile=profile.name,
            rationale=profile.rationale,
            declared_min_soc=profile.min_soc,
            points=points,
            metrics=metrics,
            solver_status=str(result.message),
        )

    @staticmethod
    def _calculate_metrics(
        scenario: Scenario, points: list[DispatchPoint]
    ) -> PlanMetrics:
        site = scenario.site
        dt = site.interval_minutes / 60
        energy_cost = sum(
            point.grid_import_kw * forecast.tariff_yuan_per_kwh * dt
            for point, forecast in zip(points, scenario.forecast, strict=True)
        )
        demand_charge = max(point.grid_import_kw for point in points) * (
            site.demand_charge_yuan_per_kw
        )
        degradation = sum(
            (point.charge_kw + point.discharge_kw) * dt * site.degradation_yuan_per_kwh
            for point in points
        )
        pv_total = sum(point.pv_kw * dt for point in points)
        curtailed = sum(point.pv_curtailment_kw * dt for point in points)
        shed_energy = sum(point.flexible_load_shed_kw * dt for point in points)
        return PlanMetrics(
            energy_cost_yuan=round(energy_cost, 2),
            demand_charge_yuan=round(demand_charge, 2),
            degradation_cost_yuan=round(degradation, 2),
            total_cost_yuan=round(energy_cost + demand_charge + degradation, 2),
            peak_grid_kw=round(max(point.grid_import_kw for point in points), 2),
            pv_self_consumption_ratio=round(
                1 - curtailed / pv_total if pv_total else 1, 4
            ),
            end_soc=round(points[-1].soc_end, 4),
            shed_energy_kwh=round(shed_energy, 2),
        )
