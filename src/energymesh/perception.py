from __future__ import annotations

from energymesh.models import PerceptionReport, Scenario


class PerceptionAgent:
    """Validates structured operational context before optimization."""

    def inspect(self, scenario: Scenario) -> PerceptionReport:
        site = scenario.site
        interval_seconds = site.interval_minutes * 60
        timestamps_valid = all(
            int((current.timestamp - previous.timestamp).total_seconds()) == interval_seconds
            for previous, current in zip(scenario.forecast, scenario.forecast[1:], strict=False)
        )
        production_valid = all(
            point.production_min_load_kw <= point.load_kw for point in scenario.forecast
        )
        devices_valid = all(
            scenario.device_status.get(asset) in {"available", "derated"}
            for asset in ("meter", "pv", "battery", "transformer")
        )
        missing_data: list[str] = []
        if not timestamps_valid:
            missing_data.append("continuous quarter-hour timestamps")
        if not production_valid:
            missing_data.append("valid production minimum-load plan")
        if not devices_valid:
            missing_data.append("required device availability")

        anomalies: list[str] = []
        conflicts: list[str] = []
        hot_points = 0
        conflict_points = 0
        for point in scenario.forecast:
            primary_hot = point.transformer_temperature_c >= site.transformer_temperature_limit_c
            redundant_hot = (
                point.transformer_redundant_temperature_c >= site.transformer_temperature_limit_c
            )
            if abs(point.transformer_temperature_c - point.transformer_redundant_temperature_c) > 8:
                conflict_points += 1
            elif primary_hot and redundant_hot:
                hot_points += 1
        if conflict_points:
            conflicts.append(
                f"transformer temperature sensors disagree in {conflict_points} intervals"
            )
        if hot_points:
            anomalies.append(
                f"confirmed transformer over-temperature risk in {hot_points} intervals"
            )
        if any(point.battery_temperature_c >= 45 for point in scenario.forecast):
            anomalies.append("battery temperature requires PCS discharge derating")

        data_complete = not missing_data
        original_task_valid = not scenario.alerts
        if conflicts:
            recommended_action = "human_handoff"
        elif not data_complete:
            recommended_action = "request_missing_data"
        elif not original_task_valid:
            recommended_action = "redefine_and_optimize"
        else:
            recommended_action = "optimize_current_task"
        validated = [
            "park load forecast",
            "PV forecast",
            "battery SOC and temperature",
            "tariff calendar",
            "device availability",
            "production minimum-load plan",
        ]
        constraints = [
            f"SOC {site.safety_min_soc:.0%}-{site.safety_max_soc:.0%}",
            f"PCS charge/discharge {site.battery_charge_max_kw:.0f}/"
            f"{site.battery_discharge_max_kw:.0f} kW",
            f"transformer {site.transformer_capacity_kw:.0f} kW",
            f"grid interconnection {site.grid_interconnection_limit_kw:.0f} kW",
        ]
        if hot_points:
            constraints.append(
                "transformer hot-state capacity "
                f"{site.transformer_capacity_kw * site.transformer_hot_derate_factor:.0f} kW"
            )
        return PerceptionReport(
            data_complete=data_complete,
            quality_score=max(
                0.0,
                1.0 - len(missing_data) * 0.25 - len(conflicts) * 0.15,
            ),
            original_task_valid=original_task_valid,
            recommended_action=recommended_action,
            validated_inputs=validated,
            active_constraints=constraints,
            change_signals=scenario.alerts,
            missing_data=missing_data,
            anomalies=anomalies,
            conflicts=conflicts,
            objective_priority=[
                "production safety",
                "equipment thermal loading",
                "critical-load continuity",
                "electricity cost",
                "PV self-consumption",
            ],
            required_tools=[
                "load_forecast",
                "pv_forecast",
                "sensor_consistency_check",
                "transformer_thermal_derating",
                "economic_dispatch_optimizer",
            ],
        )
