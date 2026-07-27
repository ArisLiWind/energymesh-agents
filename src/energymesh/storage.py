from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from energymesh.model_gateway import StoredModelConfig, mask_api_key
from energymesh.models import AgentModelConfigPublic, TaskRecord


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_model_configs (
                    agent_id TEXT PRIMARY KEY,
                    base_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    connection_status TEXT NOT NULL,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
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

    def save_model_config(
        self,
        agent_id: str,
        base_url: str,
        api_key: str | None,
        model: str,
    ) -> AgentModelConfigPublic:
        current = self.get_model_config(agent_id)
        if api_key is None or not api_key.strip() or "•" in api_key:
            if current is None:
                raise ValueError("api_key is required")
            saved_key = current.api_key
        else:
            saved_key = api_key.strip()
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_model_configs(
                    agent_id, base_url, api_key, model, connection_status, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    base_url = excluded.base_url,
                    api_key = excluded.api_key,
                    model = excluded.model,
                    connection_status = excluded.connection_status,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (agent_id, base_url.strip(), saved_key, model.strip(), "未测试", None, now),
            )
        stored = self.get_model_config(agent_id)
        if stored is None:
            raise RuntimeError("model config was not saved")
        return self.public_model_config(stored)

    def get_model_config(self, agent_id: str) -> StoredModelConfig | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT agent_id, base_url, api_key, model, connection_status, last_error
                FROM agent_model_configs WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredModelConfig(
            agent_id=row["agent_id"],
            base_url=row["base_url"],
            api_key=row["api_key"],
            model=row["model"],
            connection_status=row["connection_status"],
            last_error=row["last_error"],
        )

    def update_model_status(
        self, agent_id: str, connection_status: str, last_error: str | None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_model_configs
                SET connection_status = ?, last_error = ?, updated_at = ?
                WHERE agent_id = ?
                """,
                (connection_status, last_error, datetime.now(UTC).isoformat(), agent_id),
            )

    def public_model_config(self, config: StoredModelConfig) -> AgentModelConfigPublic:
        return AgentModelConfigPublic(
            agent_id=config.agent_id,
            base_url=config.base_url,
            api_key_masked=mask_api_key(config.api_key),
            model=config.model,
            connection_status=config.connection_status,
            last_error=config.last_error,
        )

    def list_public_model_configs(self) -> dict[str, AgentModelConfigPublic]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT agent_id, base_url, api_key, model, connection_status, last_error
                FROM agent_model_configs ORDER BY agent_id
                """
            ).fetchall()
        configs: dict[str, AgentModelConfigPublic] = {}
        for row in rows:
            stored = StoredModelConfig(
                agent_id=row["agent_id"],
                base_url=row["base_url"],
                api_key=row["api_key"],
                model=row["model"],
                connection_status=row["connection_status"],
                last_error=row["last_error"],
            )
            configs[stored.agent_id] = self.public_model_config(stored)
        return configs

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
