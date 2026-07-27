from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from energymesh.models import (
    ExternalDataSnapshot,
    ExternalTelemetryPoint,
    ForecastPoint,
    Scenario,
    SiteConfig,
)


class ExternalDataSimulator:
    """Deterministic stand-in for EMS/BMS/PCS/weather/MES feeds."""

    def snapshot(
        self,
        seed: int = 42,
        current_interval: int = 57,
        fault_mode: str = "cloud_and_transformer_heat",
    ) -> ExternalDataSnapshot:
        rng = random.Random(seed)
        site = SiteConfig(
            site_id="digital-twin-park-01",
            transformer_capacity_kw=1_250,
            grid_interconnection_limit_kw=1_080,
            battery_capacity_kwh=860,
            battery_charge_max_kw=330,
            battery_discharge_max_kw=330,
            initial_soc=0.58,
            flexible_load_kw=135,
        )
        start = datetime(2026, 7, 28, tzinfo=UTC)
        telemetry: list[ExternalTelemetryPoint] = []
        forecast: list[ForecastPoint] = []
        interval_hours = site.interval_minutes / 60
        soc = site.initial_soc
        alerts: list[str] = []

        for index in range(24 * 60 // site.interval_minutes):
            hour = index * interval_hours
            timestamp = start + timedelta(minutes=index * site.interval_minutes)
            load = self._load_kw(hour, rng)
            pv = self._pv_kw(hour)
            fault_code: str | None = None
            transformer_temperature = 56 + 17 * math.exp(-(((hour - 15.0) / 2.4) ** 2))
            redundant_temperature = transformer_temperature - 1.5
            battery_available = True

            if fault_mode in {"cloud_and_transformer_heat", "storm_front"} and 13.0 <= hour < 15.25:
                pv *= 0.52
                fault_code = "PV_CLOUD_SHADING"
            if fault_mode == "cloud_and_transformer_heat" and 14.0 <= hour < 17.25:
                transformer_temperature += 13.5
                redundant_temperature += 12.0
                fault_code = "TRANSFORMER_HOT_DERATE"
            if fault_mode == "battery_derate" and 18.0 <= hour < 20.0:
                battery_available = False
                fault_code = "BATTERY_PCS_DERATED"

            if hour < 7:
                tariff = 0.36
            elif 10 <= hour < 15 or 18 <= hour < 21:
                tariff = 1.38
            else:
                tariff = 0.78

            emergency_shift = 14.0 <= hour < 17.5
            response_headroom = 36 if emergency_shift else site.flexible_load_kw
            production_min_load = max(load - response_headroom, 320)
            net = load - pv
            if tariff <= 0.4 and soc < 0.82:
                soc += 0.006
            elif tariff >= 1.0 and net > 520 and soc > 0.42:
                soc -= 0.004
            soc = min(site.safety_max_soc - 0.01, max(site.safety_min_soc + 0.01, soc))

            transformer_limit = site.transformer_capacity_kw
            if (
                transformer_temperature >= site.transformer_temperature_limit_c
                and redundant_temperature >= site.transformer_temperature_limit_c
            ):
                transformer_limit *= site.transformer_hot_derate_factor

            if fault_code and fault_code not in alerts:
                alerts.append(fault_code)

            forecast.append(
                ForecastPoint(
                    timestamp=timestamp,
                    load_kw=round(load, 3),
                    pv_kw=round(max(pv, 0), 3),
                    production_min_load_kw=round(production_min_load, 3),
                    tariff_yuan_per_kwh=tariff,
                    battery_temperature_c=48.5 if fault_code == "BATTERY_PCS_DERATED" else 29.0,
                    transformer_temperature_c=round(transformer_temperature, 3),
                    transformer_redundant_temperature_c=round(redundant_temperature, 3),
                )
            )
            telemetry.append(
                ExternalTelemetryPoint(
                    interval=index,
                    timestamp=timestamp,
                    load_kw=round(load, 3),
                    pv_kw=round(max(pv, 0), 3),
                    battery_soc=round(soc, 4),
                    tariff_yuan_per_kwh=tariff,
                    transformer_temperature_c=round(transformer_temperature, 3),
                    transformer_limit_kw=round(transformer_limit, 3),
                    grid_interconnection_limit_kw=site.grid_interconnection_limit_kw,
                    battery_available=battery_available,
                    fault_code=fault_code,
                    production_min_load_kw=round(production_min_load, 3),
                )
            )

        current_interval = min(max(current_interval, 0), len(telemetry) - 1)
        current = telemetry[current_interval]
        scenario = Scenario(
            scenario_id=f"external-sim-{seed}-{current_interval}",
            name="外部数据驱动园区数字孪生",
            description="由模拟EMS/BMS/PCS/气象/MES数据生成，供感知、调度和审核Agent闭环使用。",
            site=site.model_copy(
                update={
                    "initial_soc": current.battery_soc,
                    "battery_charge_max_kw": (
                        site.battery_charge_max_kw if current.battery_available else 0.001
                    ),
                    "battery_discharge_max_kw": (
                        site.battery_discharge_max_kw if current.battery_available else 0.001
                    ),
                }
            ),
            forecast=forecast,
            alerts=alerts,
            device_status={
                "meter": "available",
                "pv": (
                    "derated"
                    if any(item.fault_code == "PV_CLOUD_SHADING" for item in telemetry)
                    else "available"
                ),
                "battery": "available" if current.battery_available else "derated",
                "transformer": (
                    "derated"
                    if current.transformer_limit_kw < site.transformer_capacity_kw
                    else "available"
                ),
            },
            production_plan={
                "source": "simulated_mes",
                "line": "precision-machining-a",
                "minimum_load_policy": "critical process load must be preserved",
                "emergency_order": any(
                    item.production_min_load_kw > item.load_kw - 60 for item in telemetry
                ),
            },
            simulation_faults=[],
        )
        return ExternalDataSnapshot(
            source="simulated_external_feeds",
            generated_at=datetime.now(UTC),
            current_interval=current_interval,
            scenario=scenario,
            telemetry=telemetry,
            current=current,
            environment_signals={
                "load_kw": current.load_kw,
                "pv_kw": current.pv_kw,
                "battery_soc": current.battery_soc,
                "tariff_yuan_per_kwh": current.tariff_yuan_per_kwh,
                "transformer_limit_kw": current.transformer_limit_kw,
                "grid_interconnection_limit_kw": current.grid_interconnection_limit_kw,
                "fault_code": current.fault_code,
                "production_min_load_kw": current.production_min_load_kw,
            },
            layer_summary={
                "environment": [
                    "负荷、光伏、储能SOC、电价、变压器、并网限制、设备故障、生产计划",
                    "来自模拟EMS/BMS/PCS/气象/MES外部数据源",
                ],
                "strategy_generation": [
                    "调度Agent调用 scipy.optimize.milp 产生充电、放电、购电、弃光和柔性负荷动作",
                    "每个候选策略包含96个15分钟动作点和备用SOC策略",
                ],
                "deterministic_verification": [
                    "审核Agent逐点复算SOC边界、功率边界、变压器容量、并网功率、能量守恒和生产约束",
                    "未通过硬约束的候选策略不能进入执行门禁",
                ],
            },
        )

    @staticmethod
    def _load_kw(hour: float, rng: random.Random) -> float:
        base = 500
        morning_shift = 210 * math.exp(-(((hour - 8.7) / 1.7) ** 2))
        afternoon_shift = 360 * math.exp(-(((hour - 14.4) / 3.1) ** 2))
        evening_charge = 165 * math.exp(-(((hour - 19.2) / 1.8) ** 2))
        ripple = 28 * math.sin(hour * 2.8) + 18 * math.sin(hour * 7.1)
        noise = rng.uniform(-12, 12)
        return max(330, base + morning_shift + afternoon_shift + evening_charge + ripple + noise)

    @staticmethod
    def _pv_kw(hour: float) -> float:
        if hour < 6 or hour > 18.4:
            return 0
        return max(0.0, 680 * math.sin(math.pi * (hour - 6.0) / 12.4))
