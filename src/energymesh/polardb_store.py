"""PolarDB telemetry snapshot store with a local SQLite fallback.

Set POLARDB_DSN or DATABASE_URL to use PolarDB for PostgreSQL. When no DSN is
configured the same logical schema is created in SQLite for offline demos.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from energymesh.models import ExternalTelemetryPoint


class CursorLike(Protocol):
    def fetchone(self) -> Any: ...


class ConnectionLike(Protocol):
    def close(self) -> None: ...


class PolarDBStore:
    """Stores rolling telemetry, plan versions, and execution results."""

    def __init__(self, db_path: str = ".data/polardb_telemetry.db", dsn: str | None = None) -> None:
        self.backend = "polardb-postgresql" if dsn else "sqlite"
        self._param = "%s" if dsn else "?"
        if dsn:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "POLARDB_DSN is configured but psycopg is not installed. "
                    "Install with `python3 -m pip install -e '.[cloud]'`."
                ) from exc
            self.conn: ConnectionLike = psycopg.connect(
                dsn,
                autocommit=True,
                row_factory=dict_row,
            )
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.conn = conn
        self._init_tables()

    def _init_tables(self) -> None:
        if self.backend == "sqlite":
            conn = self._sqlite_conn()
            conn.executescript("""
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
            CREATE INDEX IF NOT EXISTS idx_telemetry_interval
                ON telemetry_snapshots(source, interval);

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
            conn.commit()
            return

        statements = [
            """
            CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                interval INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                load_kw DOUBLE PRECISION,
                pv_kw DOUBLE PRECISION,
                battery_soc DOUBLE PRECISION,
                grid_import_kw DOUBLE PRECISION,
                tariff_yuan_per_kwh DOUBLE PRECISION,
                transformer_temp_c DOUBLE PRECISION,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_telemetry_interval
                ON telemetry_snapshots(source, interval)
            """,
            """
            CREATE TABLE IF NOT EXISTS plan_versions (
                plan_version_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                interval_from INTEGER NOT NULL,
                interval_to INTEGER NOT NULL,
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                invalidated_reason TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_plan_task ON plan_versions(task_id)",
            """
            CREATE TABLE IF NOT EXISTS execution_results (
                execution_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                plan_version_id TEXT,
                interval INTEGER NOT NULL,
                actual_grid_kw DOUBLE PRECISION,
                actual_soc DOUBLE PRECISION,
                expected_grid_kw DOUBLE PRECISION,
                expected_soc DOUBLE PRECISION,
                deviation_flag INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_exec_task ON execution_results(task_id, interval)",
        ]
        with self._pg_conn().cursor() as cur:
            for statement in statements:
                cur.execute(statement)

    def _sqlite_conn(self) -> sqlite3.Connection:
        if not isinstance(self.conn, sqlite3.Connection):
            raise RuntimeError("SQLite connection requested while using PolarDB backend")
        return self.conn

    def _pg_conn(self) -> Any:
        if isinstance(self.conn, sqlite3.Connection):
            raise RuntimeError("PolarDB connection requested while using SQLite backend")
        return self.conn

    def _execute(self, sql: str, params: tuple[object, ...] = ()) -> CursorLike:
        if self.backend == "sqlite":
            return self._sqlite_conn().execute(sql, params)
        cur = self._pg_conn().cursor()
        converted = sql.replace("INSERT OR REPLACE INTO", "INSERT INTO")
        if (
            "telemetry_snapshots" in converted
            and "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" in converted
        ):
            converted += " ON CONFLICT (snapshot_id) DO UPDATE SET source = EXCLUDED.source"
        if "execution_results" in converted and "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)" in converted:
            converted += " ON CONFLICT (execution_id) DO UPDATE SET task_id = EXCLUDED.task_id"
        cur.execute(converted.replace("?", self._param), params)
        return cur

    def _commit_local(self) -> None:
        if self.backend == "sqlite":
            self._sqlite_conn().commit()

    def health(self) -> dict[str, str]:
        return {"backend": self.backend, "status": "ready"}

    def write_telemetry(self, source: str, point: ExternalTelemetryPoint) -> None:
        self._execute(
            """INSERT OR REPLACE INTO telemetry_snapshots
            (snapshot_id, source, interval, timestamp, load_kw, pv_kw, battery_soc,
             grid_import_kw, tariff_yuan_per_kwh, transformer_temp_c)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"{source}_{point.interval}_{datetime.now(UTC).timestamp()}",
                source,
                point.interval,
                point.timestamp.isoformat()
                if hasattr(point.timestamp, "isoformat")
                else str(point.timestamp),
                point.load_kw,
                point.pv_kw,
                point.battery_soc,
                getattr(point, "grid_import_kw", None),
                point.tariff_yuan_per_kwh,
                point.transformer_temperature_c,
            ),
        )
        self._commit_local()

    def write_plan_version(
        self,
        plan_version_id: str,
        task_id: str,
        plan_id: str,
        interval_from: int,
        interval_to: int,
        valid_from: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO plan_versions (
                plan_version_id, task_id, plan_id, interval_from, interval_to, valid_from
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (plan_version_id, task_id, plan_id, interval_from, interval_to, valid_from),
        )
        self._commit_local()

    def invalidate_plan(self, plan_version_id: str, reason: str) -> None:
        self._execute(
            """
            UPDATE plan_versions
            SET valid_until = ?, invalidated_reason = ?
            WHERE plan_version_id = ?
            """,
            (datetime.now(UTC).isoformat(), reason, plan_version_id),
        )
        self._commit_local()

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
        self._execute(
            """INSERT OR REPLACE INTO execution_results
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
        self._commit_local()

    def get_latest_snapshot(self, source: str, interval: int) -> dict[str, Any] | None:
        row = self._execute(
            """
            SELECT *
            FROM telemetry_snapshots
            WHERE source = ? AND interval = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (source, interval),
        ).fetchone()
        return dict(row) if row else None

    def get_active_plan_at(self, task_id: str, interval: int) -> dict[str, Any] | None:
        row = self._execute(
            """SELECT * FROM plan_versions
            WHERE task_id = ? AND interval_from <= ? AND interval_to >= ?
            AND valid_until IS NULL
            ORDER BY created_at DESC LIMIT 1""",
            (task_id, interval, interval),
        ).fetchone()
        return dict(row) if row else None

    def get_deviation_stats(self, task_id: str) -> dict[str, int]:
        row = self._execute(
            "SELECT COUNT(*) AS total, SUM(deviation_flag) AS deviations "
            "FROM execution_results WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return {"total_executed": 0, "deviations": 0}
        values = dict(row) if isinstance(row, sqlite3.Row) else row
        return {
            "total_executed": int(values["total"] or 0),
            "deviations": int(values["deviations"] or 0),
        }

    def close(self) -> None:
        self.conn.close()
