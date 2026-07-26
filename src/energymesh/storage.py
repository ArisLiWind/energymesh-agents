from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from energymesh.models import TaskRecord


class EvidenceStore:
    def __init__(self, db_path: Path, evidence_dir: Path) -> None:
        self.db_path = db_path
        self.evidence_dir = evidence_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    evidence_sha256 TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                )
                """
            )

    def save(self, task: TaskRecord) -> TaskRecord:
        payload = task.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, state, payload, evidence_sha256, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    payload = excluded.payload,
                    evidence_sha256 = excluded.evidence_sha256,
                    updated_at = excluded.updated_at
                """,
                (
                    task.task_id,
                    task.state.value,
                    payload,
                    task.evidence_sha256,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            if task.trace:
                event = task.trace[-1]
                connection.execute(
                    """
                    INSERT OR IGNORE INTO audit_events(
                        task_id, sequence, actor, action, payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        event.sequence,
                        event.actor,
                        event.action,
                        event.model_dump_json(),
                        event.timestamp.isoformat(),
                    ),
                )
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return TaskRecord.model_validate_json(row["payload"]) if row else None

    def list(self, limit: int = 20) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [TaskRecord.model_validate_json(row["payload"]) for row in rows]

    def seal_evidence(self, task: TaskRecord) -> str:
        evidence = {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "safety_declaration": {
                "simulation_mode": True,
                "allow_production_write": False,
                "real_devices_contacted": 0,
            },
            "task": task.model_dump(mode="json", exclude={"evidence_sha256"}),
        }
        canonical = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        evidence["sha256"] = digest
        target = self.evidence_dir / f"{task.task_id}.json"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{task.task_id}-", suffix=".tmp", dir=self.evidence_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(evidence, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return digest
