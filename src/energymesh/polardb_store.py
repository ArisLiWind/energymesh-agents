"""PolarDB-compatible telemetry snapshot store.

Schema maps 1:1 to PolarDB tables; swap connection string to migrate.
Current: SQLite (local). Production: PolarDB PostgreSQL.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from energymesh.models import ExternalTelemetryPoint


class PolarDBStore:
    """Stores rolling telemetry, plan versions, and execution results."""

    def __init__(self, db_path: str = ".data/polardb_telemetry.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS telemetry_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            interval INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            load_kw REAL,
            pv_kw REAL,
            battery_soc REAL,
            grid_import_kw REAL,
            tariff_yuan_per_kwh REAL,
            transformer_temp_c REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_interval ON telemetry_snapshots(source, interval);

        CREATE TABLE IF NOT EXISTS plan_versions (
            plan_version_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            interval_from INTEGER NOT NULL,
            interval_to INTEGER NOT NULL,
            valid_from TEXT NOT NULL,
            valid_until TEXT,
            invalidated_reason TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_plan_task ON plan_versions(task_id);

        CREATE TABLE IF NOT EXISTS execution_results (
            execution_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            plan_version_id TEXT,
            interval INTEGER NOT NULL,
            actual_grid_kw REAL,
            actual_soc REAL,
            expected_grid_kw REAL,
            expected_soc REAL,
            deviation_flag INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_exec_task ON execution_results(task_id, interval);
        """)
        self.conn.commit()

    def write_telemetry(self, source: str, point: ExternalTelemetryPoint) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO telemetry_snapshots
            (snapshot_id, source, interval, timestamp, load_kw, pv_kw, battery_soc,
             grid_import_kw, tariff_yuan_per_kwh, transformer_temp_c)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"{source}_{point.interval}_{datetime.now(UTC).timestamp()}",
                source,
                point.interval,
                (
                    point.timestamp.isoformat()
                    if hasattr(point.timestamp, "isoformat")
                    else str(point.timestamp)
                ),
                point.load_kw,
                point.pv_kw,
                point.battery_soc,
                getattr(point, "grid_import_kw", None),
                point.tariff_yuan_per_kwh,
                point.transformer_temperature_c,
            ),
        )
        self.conn.commit()

    def write_plan_version(
        self,
        plan_version_id: str,
        task_id: str,
        plan_id: str,
        interval_from: int,
        interval_to: int,
        valid_from: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO plan_versions (plan_version_id, task_id, plan_id, interval_from, interval_to, valid_from) VALUES (?, ?, ?, ?, ?, ?)",
            (plan_version_id, task_id, plan_id, interval_from, interval_to, valid_from),
        )
        self.conn.commit()

    def invalidate_plan(self, plan_version_id: str, reason: str) -> None:
        self.conn.execute(
            "UPDATE plan_versions SET valid_until = ?, invalidated_reason = ? WHERE plan_version_id = ?",
            (datetime.now(UTC).isoformat(), reason, plan_version_id),
        )
        self.conn.commit()

    def write_execution(
        self,
        execution_id: str,
        task_id: str,
        plan_version_id: str | None,
        interval: int,
        actual: dict[str, float],
        expected: dict[str, float],
        deviation: bool = False,
    ) -> None:
        self.conn.execute(
            """INSERT INTO execution_results
            (execution_id, task_id, plan_version_id, interval, actual_grid_kw, actual_soc,
             expected_grid_kw, expected_soc, deviation_flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                execution_id,
                task_id,
                plan_version_id,
                interval,
                actual.get("grid_kw", 0),
                actual.get("soc", 0),
                expected.get("grid_kw", 0),
                expected.get("soc", 0),
                1 if deviation else 0,
            ),
        )
        self.conn.commit()

    def get_latest_snapshot(self, source: str, interval: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM telemetry_snapshots WHERE source = ? AND interval = ? ORDER BY created_at DESC LIMIT 1",
            (source, interval),
        ).fetchone()
        return dict(row) if row else None

    def get_active_plan_at(self, task_id: str, interval: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM plan_versions
            WHERE task_id = ? AND interval_from <= ? AND interval_to >= ?
            AND valid_until IS NULL
            ORDER BY created_at DESC LIMIT 1""",
            (task_id, interval, interval),
        ).fetchone()
        return dict(row) if row else None

    def get_deviation_stats(self, task_id: str) -> dict[str, int]:
        cur = self.conn.execute(
            "SELECT COUNT(*), SUM(deviation_flag) FROM execution_results WHERE task_id = ?",
            (task_id,),
        )
        total, deviations = cur.fetchone()
        return {"total_executed": total or 0, "deviations": deviations or 0}

    def close(self) -> None:
        self.conn.close()
