from __future__ import annotations

import csv
import io
import statistics
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from energymesh.models import (
    ExternalDataSnapshot,
    ExternalTelemetryPoint,
    ForecastPoint,
    Scenario,
    SiteConfig,
    TaskRecord,
)
from energymesh.orchestrator import EnergyMeshOrchestrator

OPEN_CEM_DATASET_URL = "https://github.com/OpenCEM-platform/opencem-dataset"
OPEN_CEM_PAPER_URL = "https://arxiv.org/abs/2604.05429"


class EnergyDataError(ValueError):
    pass


def _number(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _mean(values: list[float], default: float) -> float:
    return statistics.fmean(values) if values else default


class SnapshotFactory:
    """Normalizes uploaded public energy datasets into EnergyMesh snapshots."""

    required_columns = {"read_ts", "inverter", "outsumw", "pv1power", "battsoc"}
    emsx_columns = {"timestamp", "site_id", "actual_consumption", "actual_pv"}

    def from_opencem_csv(
        self,
        content: bytes,
        filename: str,
        current_interval: int = 20,
    ) -> ExternalDataSnapshot:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise EnergyDataError("CSV must be UTF-8 encoded") from error
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if reader.fieldnames is None or not self.required_columns.issubset(
            reader.fieldnames
        ):
            if reader.fieldnames is not None and self.emsx_columns.issubset(
                reader.fieldnames
            ):
                return self._from_emsx_rows(
                    list(reader), filename, current_interval=current_interval
                )
            missing = sorted(self.required_columns.difference(reader.fieldnames or []))
            raise EnergyDataError(f"OpenCEM CSV missing columns: {', '.join(missing)}")
        rows = list(reader)
        if not rows:
            raise EnergyDataError("CSV contains no measurement rows")

        rows_by_day: dict[date, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            raw_timestamp = _number(row, "read_ts")
            if raw_timestamp is None:
                continue
            measured_at = datetime.fromtimestamp(raw_timestamp, UTC)
            rows_by_day[measured_at.date()].append(row)
        if not rows_by_day:
            raise EnergyDataError("CSV contains no valid read_ts measurements")

        replay_day = max(
            rows_by_day,
            key=lambda item: len(
                {
                    (
                        datetime.fromtimestamp(float(row["read_ts"]), UTC).hour * 60
                        + datetime.fromtimestamp(float(row["read_ts"]), UTC).minute
                    )
                    // 15
                    for row in rows_by_day[item]
                }
            ),
        )
        day_rows = rows_by_day[replay_day]
        bucket_rows: dict[int, dict[str, list[dict[str, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in day_rows:
            measured_at = datetime.fromtimestamp(float(row["read_ts"]), UTC)
            interval = (measured_at.hour * 60 + measured_at.minute) // 15
            bucket_rows[interval][row["inverter"]].append(row)

        raw_points: list[dict[str, float] | None] = []
        for interval in range(96):
            inverter_groups = bucket_rows.get(interval)
            if not inverter_groups:
                raw_points.append(None)
                continue
            load_kw = 0.0
            pv_kw = 0.0
            grid_kw = 0.0
            soc_values: list[float] = []
            temperature_values: list[float] = []
            battery_power_kw = 0.0
            for inverter_rows in inverter_groups.values():
                loads = [
                    value for row in inverter_rows if (value := _number(row, "outsumw"))
                ]
                pvs = [
                    value
                    for row in inverter_rows
                    if (value := _number(row, "pv1power"))
                ]
                grids = [
                    value
                    for row in inverter_rows
                    if (value := _number(row, "gridpowerw_a")) is not None
                ]
                battery_powers = [
                    value
                    for row in inverter_rows
                    if (value := _number(row, "battchgpower")) is not None
                ]
                load_kw += max(0.0, _mean(loads, 0.0) / 1000)
                pv_kw += max(0.0, _mean(pvs, 0.0) / 1000)
                grid_kw += max(0.0, _mean(grids, 0.0) / 1000)
                battery_power_kw += _mean(battery_powers, 0.0) / 1000
                soc_values.extend(
                    value
                    for row in inverter_rows
                    if (value := _number(row, "battsoc")) is not None
                )
                temperature_values.extend(
                    value
                    for row in inverter_rows
                    if (value := _number(row, "temper1")) is not None
                )
            raw_points.append(
                {
                    "load_kw": load_kw,
                    "pv_kw": pv_kw,
                    "grid_kw": grid_kw,
                    "soc": _mean(soc_values, 55.0) / 100,
                    "temperature_c": _mean(temperature_values, 35.0),
                    "battery_power_kw": battery_power_kw,
                }
            )

        available = [point for point in raw_points if point is not None]
        if len(available) < 48:
            raise EnergyDataError(
                "CSV needs at least 48 populated quarter-hour intervals"
            )
        first = available[0]
        last = first
        normalized: list[dict[str, float]] = []
        for point in raw_points:
            if point is not None:
                last = point
            normalized.append(dict(last))

        peak_load = max(point["load_kw"] for point in normalized)
        transformer_capacity = max(12.0, peak_load * 1.55)
        grid_limit = max(10.0, peak_load * 1.35)
        initial_soc = min(0.90, max(0.30, normalized[current_interval]["soc"]))
        site = SiteConfig(
            site_id="cuhk-sz-opencem-campus",
            transformer_capacity_kw=transformer_capacity,
            grid_interconnection_limit_kw=grid_limit,
            battery_capacity_kwh=20.48,
            battery_charge_max_kw=16.0,
            battery_discharge_max_kw=16.0,
            initial_soc=initial_soc,
            safety_min_soc=0.20,
            safety_max_soc=0.95,
            flexible_load_kw=min(1.2, max(0.2, peak_load * 0.12)),
            demand_charge_yuan_per_kw=8.0,
        )
        start = datetime(replay_day.year, replay_day.month, replay_day.day, tzinfo=UTC)
        telemetry: list[ExternalTelemetryPoint] = []
        forecast: list[ForecastPoint] = []
        for interval, point in enumerate(normalized):
            timestamp = start + timedelta(minutes=interval * 15)
            tariff = self._shenzhen_demo_tariff(timestamp.hour)
            production_min = point["load_kw"] * 0.65
            temperature = min(74.0, max(-20.0, point["temperature_c"]))
            forecast.append(
                ForecastPoint(
                    timestamp=timestamp,
                    load_kw=point["load_kw"],
                    pv_kw=point["pv_kw"],
                    production_min_load_kw=production_min,
                    tariff_yuan_per_kwh=tariff,
                    battery_temperature_c=temperature,
                    transformer_temperature_c=temperature,
                    transformer_redundant_temperature_c=temperature,
                )
            )
            telemetry.append(
                ExternalTelemetryPoint(
                    interval=interval,
                    timestamp=timestamp,
                    load_kw=point["load_kw"],
                    pv_kw=point["pv_kw"],
                    battery_soc=min(1.0, max(0.0, point["soc"])),
                    tariff_yuan_per_kwh=tariff,
                    transformer_temperature_c=temperature,
                    transformer_limit_kw=transformer_capacity,
                    grid_interconnection_limit_kw=grid_limit,
                    battery_available=True,
                    production_min_load_kw=production_min,
                )
            )

        current_interval = min(max(current_interval, 0), 95)
        current = telemetry[current_interval]
        scenario = Scenario(
            scenario_id=f"opencem-{replay_day.isoformat()}",
            name="OpenCEM CUHK-Shenzhen 真实校园微电网回放",
            description=(
                "OpenCEM 双逆变器实测数据按15分钟聚合；电价为可替换的演示配置，"
                "不伪装为 OpenCEM 实测字段。"
            ),
            site=site,
            forecast=forecast,
            alerts=[],
            device_status={
                "meter": "available",
                "pv": "available",
                "battery": "available",
                "transformer": "available",
            },
            production_plan={
                "source": "opencem_context_adapter",
                "policy": "65% measured load protected for replay audit",
            },
            simulation_faults=[],
        )
        return ExternalDataSnapshot(
            source="opencem_csv_upload",
            generated_at=datetime.now(UTC),
            current_interval=current_interval,
            scenario=scenario,
            telemetry=telemetry,
            current=current,
            environment_signals={
                "load_kw": current.load_kw,
                "pv_kw": current.pv_kw,
                "battery_soc": current.battery_soc,
                "grid_import_kw": normalized[current_interval]["grid_kw"],
                "battery_power_kw": normalized[current_interval]["battery_power_kw"],
                "raw_rows": len(day_rows),
                "replay_date": replay_day.isoformat(),
                "filename": Path(filename).name,
            },
            layer_summary={
                "environment": [
                    "OpenCEM CUHK-Shenzhen campus PV + battery microgrid",
                    f"{len(day_rows)} real measurements normalized to 96 quarter-hour snapshots",
                ],
                "strategy_generation": [
                    "Monitor reads continuously; AgentTeams sleeps while V1 remains valid",
                    "Only a material measured deviation wakes Perception, Dispatch "
                    "and Audit Workers",
                ],
                "deterministic_verification": [
                    "CSV and future read-only connectors share this ExternalDataSnapshot contract",
                    "Simulation-only execution, rollback and SHA-256 evidence remain enforced",
                ],
            },
        )

    def _from_emsx_rows(
        self,
        rows: list[dict[str, str]],
        filename: str,
        current_interval: int = 20,
    ) -> ExternalDataSnapshot:
        if not rows:
            raise EnergyDataError("EMSx CSV contains no rows")
        rows_by_day: dict[date, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            timestamp = row.get("timestamp", "").strip()
            if not timestamp:
                continue
            try:
                measured_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            rows_by_day[measured_at.date()].append(row)
        complete_days = {
            day: day_rows for day, day_rows in rows_by_day.items() if len(day_rows) >= 96
        }
        if not complete_days:
            raise EnergyDataError("EMSx CSV needs at least one complete 96-point day")
        replay_day = max(
            complete_days,
            key=lambda day: sum(
                max(0.0, _number(row, "actual_consumption") or 0.0)
                + max(0.0, _number(row, "actual_pv") or 0.0)
                for row in complete_days[day][:96]
            ),
        )
        day_rows = sorted(complete_days[replay_day], key=lambda row: row["timestamp"])[:96]
        site_id = day_rows[0].get("site_id", "emsx-site")
        load_values = [
            max(0.0, (_number(row, "actual_consumption") or 0.0) * 4.0)
            for row in day_rows
        ]
        pv_values = [
            max(0.0, (_number(row, "actual_pv") or 0.0) * 4.0)
            for row in day_rows
        ]
        peak_load = max(load_values)
        battery_capacity = _number(day_rows[0], "battery_capacity_kwh") or max(
            400.0, peak_load * 1.6
        )
        battery_power = (_number(day_rows[0], "battery_power_kwh_per_interval") or 100.0) * 4.0
        initial_soc = min(0.90, max(0.30, (_number(day_rows[0], "battery_soc") or 62.0) / 100))
        transformer_capacity = max(peak_load * 1.28, peak_load + battery_power * 0.35)
        grid_limit = max(peak_load * 1.05, peak_load + battery_power * 0.15)
        site = SiteConfig(
            site_id=f"emsx-industrial-site-{site_id}",
            transformer_capacity_kw=transformer_capacity,
            grid_interconnection_limit_kw=grid_limit,
            battery_capacity_kwh=battery_capacity,
            battery_charge_max_kw=battery_power,
            battery_discharge_max_kw=battery_power,
            battery_efficiency_charge=_number(day_rows[0], "charge_efficiency") or 0.95,
            battery_efficiency_discharge=(
                _number(day_rows[0], "discharge_efficiency") or 0.95
            ),
            initial_soc=initial_soc,
            safety_min_soc=0.20,
            safety_max_soc=0.92,
            flexible_load_kw=min(peak_load * 0.18, battery_power * 0.55),
            demand_charge_yuan_per_kw=12.0,
        )
        telemetry: list[ExternalTelemetryPoint] = []
        forecast: list[ForecastPoint] = []
        for interval, row in enumerate(day_rows):
            timestamp = datetime.fromisoformat(
                row["timestamp"].strip().replace("Z", "+00:00")
            )
            load_kw = load_values[interval]
            pv_kw = pv_values[interval]
            load_forecast_kw = max(0.0, (_number(row, "load_00") or load_kw / 4.0) * 4.0)
            pv_forecast_kw = max(0.0, (_number(row, "pv_00") or pv_kw / 4.0) * 4.0)
            tariff = self._industrial_demo_tariff(timestamp.hour)
            production_min = load_kw * (0.72 if 8 <= timestamp.hour < 20 else 0.45)
            temperature = min(74.0, 38.0 + load_kw / transformer_capacity * 32.0)
            forecast.append(
                ForecastPoint(
                    timestamp=timestamp,
                    load_kw=load_forecast_kw,
                    pv_kw=pv_forecast_kw,
                    production_min_load_kw=production_min,
                    tariff_yuan_per_kwh=tariff,
                    battery_temperature_c=temperature,
                    transformer_temperature_c=temperature,
                    transformer_redundant_temperature_c=temperature,
                )
            )
            telemetry.append(
                ExternalTelemetryPoint(
                    interval=interval,
                    timestamp=timestamp,
                    load_kw=load_kw,
                    pv_kw=pv_kw,
                    battery_soc=initial_soc,
                    tariff_yuan_per_kwh=tariff,
                    transformer_temperature_c=temperature,
                    transformer_limit_kw=transformer_capacity,
                    grid_interconnection_limit_kw=grid_limit,
                    battery_available=True,
                    production_min_load_kw=production_min,
                )
            )

        current_interval = min(max(current_interval, 0), 95)
        current = telemetry[current_interval]
        return ExternalDataSnapshot(
            source="emsx_industrial_site_upload",
            generated_at=datetime.now(UTC),
            current_interval=current_interval,
            scenario=Scenario(
                scenario_id=f"emsx-site-{site_id}-{replay_day.isoformat()}",
                name=f"EMSx 工业站点 {site_id} 真实负荷/光伏回放",
                description=(
                    "Schneider Electric EMSx 匿名工业站点数据；实际负荷/光伏与"
                    " 96 点预测来自公开数据，电价和生产保护约束为 EnergyMesh 运行配置。"
                ),
                site=site,
                forecast=forecast,
                alerts=[],
                device_status={
                    "meter": "available",
                    "pv": "available",
                    "battery": "metadata_capacity_available",
                    "transformer": "derived_from_peak_load",
                },
                production_plan={
                    "source": "energymesh_industrial_replay_policy",
                    "policy": "business hours protect 72% measured load",
                },
                simulation_faults=[],
            ),
            telemetry=telemetry,
            current=current,
            environment_signals={
                "load_kw": current.load_kw,
                "pv_kw": current.pv_kw,
                "battery_soc": current.battery_soc,
                "grid_import_kw": max(0.0, current.load_kw - current.pv_kw),
                "raw_rows": len(rows),
                "replay_date": replay_day.isoformat(),
                "filename": Path(filename).name,
                "site_id": site_id,
            },
            layer_summary={
                "environment": [
                    "EMSx Schneider Electric anonymized industrial site",
                    f"{len(day_rows)} quarter-hour rows selected from site {site_id}",
                ],
                "strategy_generation": [
                    "Actual load/PV and one-step-ahead forecasts are both available",
                    "Industrial tariff and protected-load constraints create dispatch conflict",
                ],
                "deterministic_verification": [
                    "Mapped into ExternalDataSnapshot for the same AgentTeams workflow",
                    "RAG explains deviations; optimizer and audit recompute dispatch",
                ],
            },
        )

    @staticmethod
    def _shenzhen_demo_tariff(hour: int) -> float:
        if 0 <= hour < 8:
            return 0.32
        if 10 <= hour < 12 or 14 <= hour < 19:
            return 1.18
        return 0.68

    @staticmethod
    def _industrial_demo_tariff(hour: int) -> float:
        if 0 <= hour < 7:
            return 0.28
        if 9 <= hour < 12 or 17 <= hour < 21:
            return 1.35
        return 0.74


class ReplayMonitor:
    """Deterministic monitor: reads telemetry continuously and wakes agents on invalidation."""

    def __init__(
        self,
        orchestrator: EnergyMeshOrchestrator,
        decision_callback: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.decision_callback = decision_callback
        self.snapshot: ExternalDataSnapshot | None = None
        self.cursor = 0
        self.running = False
        self.task: TaskRecord | None = None
        self.events: list[dict[str, Any]] = []

    def start(
        self, snapshot: ExternalDataSnapshot, start_interval: int = 20
    ) -> dict[str, Any]:
        self.snapshot = snapshot
        self.cursor = min(max(start_interval, 1), 94)
        self.running = True
        self.task = None
        self.events = []
        self._event("MONITOR_STARTED", "V1 baseline active; AgentTeams sleeping")
        return self.status()

    def step(self) -> dict[str, Any]:
        if self.snapshot is None or not self.running:
            raise EnergyDataError("replay is not running")
        previous = self.snapshot.telemetry[self.cursor - 1]
        current = self.snapshot.telemetry[self.cursor]
        signals: list[str] = []
        if previous.pv_kw >= 0.5 and current.pv_kw < previous.pv_kw * 0.45:
            signals.append(
                f"PV output dropped {100 * (1 - current.pv_kw / previous.pv_kw):.1f}%"
            )
        if previous.load_kw >= 0.25 and current.load_kw > previous.load_kw * 1.55:
            signals.append(
                f"load increased {100 * (current.load_kw / previous.load_kw - 1):.1f}%"
            )

        if signals and self.task is None:
            self._event(
                "DEEPSEEK_ROLLING_CONTEXT", self._rolling_context(current, signals)
            )
            decision = self._ask_deepseek(current, signals)
            if decision:
                self._event("DEEPSEEK_DECISION", decision)
            scenario = self.snapshot.scenario.model_copy(
                update={"alerts": ["V1 plan invalidated by Monitor", *signals]}
            )
            self._event("V1_INVALIDATED", "; ".join(signals))
            self._event(
                "AGENTTEAMS_WOKEN", "Monitor handed trusted Snapshot to Team Leader"
            )
            self.task = self.orchestrator.run(
                scenario,
                trigger="OPENCEM_MONITOR_PLAN_INVALIDATION",
            )
            self.task.task_version = 2
            self.orchestrator.store.save(self.task)
            self._event(
                "V2_REPLANNED_AND_AUDITED",
                f"{self.task.selected_plan_id} awaiting human approval",
            )
        else:
            self._event(
                "SNAPSHOT_READ",
                (
                    f"interval {self.cursor:02d}: V1 valid; AgentTeams sleeping"
                    if self.task is None
                    else f"interval {self.cursor:02d}: V2 gate remains {self.task.state.value}"
                ),
            )

        self.cursor += 1
        if self.cursor >= len(self.snapshot.telemetry):
            self.running = False
        return self.status()

    def refresh_task(self) -> None:
        if self.task is not None:
            refreshed = self.orchestrator.store.get(self.task.task_id)
            if refreshed is not None:
                self.task = refreshed

    def status(self) -> dict[str, Any]:
        self.refresh_task()
        current = None
        if self.snapshot is not None:
            current = self.snapshot.telemetry[min(self.cursor, 95)].model_dump(
                mode="json"
            )
        return {
            "running": self.running,
            "source": self.snapshot.source if self.snapshot else None,
            "cursor": self.cursor,
            "speed": "1 second = 15 minutes",
            "plan_version": "V2" if self.task else "V1",
            "agentteams_awake": self.task is not None,
            "task_id": self.task.task_id if self.task else None,
            "task_state": self.task.state.value if self.task else None,
            "selected_plan_id": self.task.selected_plan_id if self.task else None,
            "evidence_sha256": self.task.evidence_sha256 if self.task else None,
            "current": current,
            "events": self.events[-30:],
        }

    def _event(self, kind: str, detail: str) -> None:
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "kind": kind,
                "detail": detail,
            }
        )

    def _rolling_context(
        self, current: ExternalTelemetryPoint, signals: list[str]
    ) -> str:
        today = self.snapshot.telemetry[: current.interval + 1] if self.snapshot else []
        grid_kw = max(current.load_kw - current.pv_kw, 0)
        grid_kwh = sum(max(point.load_kw - point.pv_kw, 0) * 0.25 for point in today)
        return (
            f"today intervals=0-{current.interval}; time={current.timestamp.isoformat()}; "
            f"load={current.load_kw:.2f}kW; pv={current.pv_kw:.2f}kW; "
            f"soc={current.battery_soc:.0%}; grid={grid_kw:.2f}kW; "
            f"grid_today={grid_kwh:.2f}kWh; signals={'; '.join(signals)}"
        )

    def _ask_deepseek(
        self, current: ExternalTelemetryPoint, signals: list[str]
    ) -> str | None:
        if self.decision_callback is None:
            return "未配置 DeepSeek 网关；使用确定性优化器继续 V2 重规划。"
        today = self.snapshot.telemetry[: current.interval + 1] if self.snapshot else []
        payload = {
            "current": current.model_dump(mode="json"),
            "signals": signals,
            "today_so_far": [point.model_dump(mode="json") for point in today],
        }
        try:
            return self.decision_callback(payload)
        except Exception as error:
            return f"DeepSeek 决策失败：{error}；使用确定性优化器继续 V2 重规划。"
