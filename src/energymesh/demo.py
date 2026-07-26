from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from energymesh.models import ForecastPoint, ReoptimizationRequest, Scenario, SiteConfig


def load_demo_scenario(config_path: Path | None = None) -> Scenario:
    path = config_path or Path(__file__).parent / "data" / "demo_site.json"
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    site = SiteConfig.model_validate(raw["site"])
    start = datetime.fromisoformat(raw["start"]).replace(tzinfo=UTC)
    points: list[ForecastPoint] = []
    interval_hours = site.interval_minutes / 60

    for index in range(24 * 60 // site.interval_minutes):
        hour = index * interval_hours
        production = 230 * math.exp(-(((hour - 8.5) / 1.8) ** 2))
        production += 330 * math.exp(-(((hour - 14.0) / 3.2) ** 2))
        load = 520 + production
        load += 210 * math.exp(-(((hour - 19.0) / 2.0) ** 2))
        load += 35 * math.sin(index * 0.63) + 18 * math.sin(index * 0.17)

        pv = max(0.0, 620 * math.sin(math.pi * (hour - 6.0) / 12.0))
        if 13.5 <= hour < 15.5:
            pv *= 0.65

        if 0 <= hour < 7:
            tariff = 0.38
        elif 10 <= hour < 15 or 18 <= hour < 21:
            tariff = 1.32
        else:
            tariff = 0.76

        temperature = 47.0 if 13.5 <= hour < 16.0 else 28.0
        transformer_temperature = 82.0 if 13.5 <= hour < 17.0 else 57.0
        emergency_production = 13.5 <= hour < 17.0
        minimum_production_load = (
            max(load - 36, 300) if emergency_production else max(load - site.flexible_load_kw, 300)
        )
        points.append(
            ForecastPoint(
                timestamp=start + timedelta(minutes=index * site.interval_minutes),
                load_kw=round(max(load, 300), 3),
                pv_kw=round(pv, 3),
                production_min_load_kw=round(minimum_production_load, 3),
                tariff_yuan_per_kwh=tariff,
                battery_temperature_c=temperature,
                transformer_temperature_c=transformer_temperature,
                transformer_redundant_temperature_c=transformer_temperature - 2,
            )
        )

    return Scenario(
        scenario_id=raw["scenario_id"],
        name=raw["name"],
        description=raw["description"],
        site=site,
        forecast=points,
        alerts=list(raw["alerts"]),
        device_status=dict(raw["device_status"]),
        production_plan=dict(raw["production_plan"]),
    )


def apply_operational_change(scenario: Scenario, request: ReoptimizationRequest) -> Scenario:
    site = scenario.site.model_copy(
        update={
            "initial_soc": min(
                scenario.site.safety_max_soc - 0.01,
                max(
                    scenario.site.safety_min_soc + 0.01,
                    scenario.site.initial_soc + request.soc_delta,
                ),
            ),
            "battery_charge_max_kw": (
                scenario.site.battery_charge_max_kw if request.battery_available else 0.001
            ),
            "battery_discharge_max_kw": (
                scenario.site.battery_discharge_max_kw if request.battery_available else 0.001
            ),
        }
    )
    forecast = [
        point.model_copy(
            update={
                "load_kw": round(point.load_kw * request.load_scale, 3),
                "pv_kw": round(point.pv_kw * request.pv_scale, 3),
                "production_min_load_kw": round(
                    max(
                        point.load_kw * request.load_scale
                        - (36 if request.emergency_production else scenario.site.flexible_load_kw),
                        0,
                    ),
                    3,
                ),
                "transformer_temperature_c": (
                    request.transformer_temperature_c
                    if request.transformer_temperature_c is not None
                    else point.transformer_temperature_c
                ),
                "transformer_redundant_temperature_c": (
                    request.transformer_redundant_temperature_c
                    if request.transformer_redundant_temperature_c is not None
                    else point.transformer_redundant_temperature_c
                ),
            }
        )
        for point in scenario.forecast
    ]
    return scenario.model_copy(
        update={
            "scenario_id": f"{scenario.scenario_id}-changed",
            "name": f"{scenario.name} · 动态重调度",
            "description": f"检测到 {request.trigger}，基于最新数据重新生成并审核策略。",
            "site": site,
            "forecast": forecast,
            "alerts": [*scenario.alerts, request.trigger],
            "device_status": {
                **scenario.device_status,
                "battery": "available" if request.battery_available else "derated",
            },
            "production_plan": {
                **scenario.production_plan,
                "emergency_order": request.emergency_production,
            },
            "simulation_faults": (
                ["EXECUTION_DEVIATION"] if request.simulate_execution_deviation else []
            ),
        }
    )
