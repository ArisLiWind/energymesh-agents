from __future__ import annotations

from typing import Any
from uuid import uuid4

from energymesh.config import Settings
from energymesh.models import DispatchPlan, ExecutionCommand, Scenario


class SimulationExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        scenario: Scenario,
        plan: DispatchPlan,
        baseline: DispatchPlan,
        approval_id: str | None,
    ) -> dict[str, Any]:
        self.settings.assert_safe_runtime()
        commands = self._map_commands(plan, approval_id)
        forced_deviation = "EXECUTION_DEVIATION" in scenario.simulation_faults
        confirmations = [
            {
                "interval": point.interval,
                "planned_grid_import_kw": point.grid_import_kw,
                "actual_grid_import_kw": round(
                    point.grid_import_kw
                    * (
                        1.12
                        if forced_deviation
                        else 1 + (((point.interval % 5) - 2) * 0.002)
                    ),
                    3,
                ),
                "soc_observed": point.soc_end,
            }
            for point in plan.points
        ]
        deviation_intervals = sum(
            1
            for confirmation in confirmations
            if abs(
                confirmation["actual_grid_import_kw"]
                - confirmation["planned_grid_import_kw"]
            )
            > max(5.0, confirmation["planned_grid_import_kw"] * 0.05)
        )
        confirmed_intervals = len(confirmations) - deviation_intervals
        fallback_activated = deviation_intervals > 0
        return {
            "mode": "simulation",
            "adapters": [
                "simulated_ems_adapter",
                "simulated_pcs_adapter",
                "simulated_flexible_load_adapter",
            ],
            "production_writes_attempted": 0,
            "real_devices_contacted": 0,
            "simulated_commands_dispatched": len(commands),
            "command_targets": sorted({command.target_system for command in commands}),
            "command_sample": [
                command.model_dump(mode="json") for command in commands[:6]
            ],
            "intervals_replayed": len(plan.points),
            "confirmations_received": confirmed_intervals,
            "confirmation_ratio": round(confirmed_intervals / len(plan.points), 4),
            "deviation_intervals": deviation_intervals,
            "safe_fallback_activated": fallback_activated,
            "safe_fallback_policy": (
                {
                    "battery_setpoint_kw": 0,
                    "flexible_load_shed_kw": 0,
                    "control_owner": "human_operator",
                    "reason": "actual result deviated more than 5% from approved plan",
                }
                if fallback_activated
                else None
            ),
            "baseline_peak_kw": baseline.metrics.peak_grid_kw,
            "simulated_peak_kw": plan.metrics.peak_grid_kw,
            "peak_reduction_kw": round(
                baseline.metrics.peak_grid_kw - plan.metrics.peak_grid_kw, 2
            ),
            "baseline_total_cost_yuan": baseline.metrics.total_cost_yuan,
            "simulated_total_cost_yuan": plan.metrics.total_cost_yuan,
            "verified_savings_yuan": round(
                baseline.metrics.total_cost_yuan - plan.metrics.total_cost_yuan, 2
            ),
            "simulated_energy_cost_yuan": plan.metrics.energy_cost_yuan,
            "soc_bounds_held": all(
                scenario.site.safety_min_soc
                <= point.soc_end
                <= scenario.site.safety_max_soc
                for point in plan.points
            ),
            "critical_load_served_ratio": 1.0,
        }

    @staticmethod
    def _map_commands(
        plan: DispatchPlan, approval_id: str | None
    ) -> list[ExecutionCommand]:
        commands: list[ExecutionCommand] = []
        for point in plan.points:
            commands.extend(
                [
                    ExecutionCommand(
                        command_id=f"cmd_{uuid4().hex[:12]}",
                        target_system="EMS",
                        resource_id="park-grid-connection",
                        parameter="grid_import_schedule",
                        value=point.grid_import_kw,
                        unit="kW",
                        idempotency_key=f"{plan.plan_id}:ems:{point.interval}",
                        interval=point.interval,
                        approval_id=approval_id,
                    ),
                    ExecutionCommand(
                        command_id=f"cmd_{uuid4().hex[:12]}",
                        target_system="PCS",
                        resource_id="battery-01",
                        parameter="active_power_setpoint",
                        value=round(point.discharge_kw - point.charge_kw, 4),
                        unit="kW",
                        idempotency_key=f"{plan.plan_id}:pcs:{point.interval}",
                        interval=point.interval,
                        approval_id=approval_id,
                    ),
                    ExecutionCommand(
                        command_id=f"cmd_{uuid4().hex[:12]}",
                        target_system="LOAD_CONTROLLER",
                        resource_id="flexible-load-group-01",
                        parameter="load_shed_setpoint",
                        value=point.flexible_load_shed_kw,
                        unit="kW",
                        idempotency_key=f"{plan.plan_id}:load:{point.interval}",
                        interval=point.interval,
                        approval_id=approval_id,
                    ),
                ]
            )
        return commands
