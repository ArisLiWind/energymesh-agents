from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from energymesh.model_gateway import StoredModelConfig, mask_api_key
from energymesh.models import (
    AgentHandoff,
    AgentModelConfigPublic,
    ApprovalRecordV2,
    AuditVerdictRecord,
    CandidatePlanRecord,
    ContextSnapshot,
    ExecutionCommandRecord,
    ExecutionReceipt,
    RollbackRecord,
    SkillInvocation,
    TaskEvent,
    TaskRecord,
    VerificationResult,
)

PayloadRow = dict[str, object]
PayloadRows = list[PayloadRow]

DEMO_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS task_events (
        event_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        from_state TEXT,
        to_state TEXT NOT NULL,
        actor TEXT NOT NULL,
        trace_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        input_reference TEXT,
        output_reference TEXT,
        skill_name TEXT,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_snapshots (
        context_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        context_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_handoffs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        from_agent TEXT NOT NULL,
        to_agent TEXT NOT NULL,
        status TEXT NOT NULL,
        input_reference TEXT NOT NULL,
        output_reference TEXT NOT NULL,
        skill_name TEXT,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_invocations (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        agent TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        status TEXT NOT NULL,
        input_reference TEXT NOT NULL,
        output_reference TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        duration_ms INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS candidate_plans (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        context_hash TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        status TEXT NOT NULL,
        cost_yuan REAL NOT NULL,
        max_power_kw REAL NOT NULL,
        soc_min_percent REAL NOT NULL,
        soc_max_percent REAL NOT NULL,
        transformer_load_percent REAL NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(task_id, task_version, candidate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_verdicts (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        context_hash TEXT NOT NULL,
        verdict TEXT NOT NULL,
        reason TEXT NOT NULL,
        transformer_load_percent REAL NOT NULL,
        safety_limit_percent REAL NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(task_id, task_version, candidate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        context_hash TEXT NOT NULL,
        approved INTEGER NOT NULL,
        valid INTEGER NOT NULL,
        approver TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_commands (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        target_system TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        command TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_receipts (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        command_count INTEGER NOT NULL,
        simulated INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_results (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        status TEXT NOT NULL,
        max_deviation_percent REAL NOT NULL,
        evidence_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rollback_records (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_version INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        baseline_restored INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
]


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
            for statement in DEMO_TABLES:
                connection.execute(statement)

    def _insert_payload_row(self, table: str, data: BaseModel, columns: PayloadRow) -> None:
        payload = data.model_dump_json()
        names = [*columns.keys(), "payload"]
        placeholders = ", ".join("?" for _ in names)
        values = [*columns.values(), payload]
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT OR REPLACE INTO {table}({", ".join(names)})
                VALUES ({placeholders})
                """,
                values,
            )

    def _list_payload_rows(
        self, table: str, model: type[BaseModel], task_id: str
    ) -> PayloadRows:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM {table} WHERE task_id = ? ORDER BY created_at, rowid",
                (task_id,),
            ).fetchall()
        return [model.model_validate_json(row["payload"]).model_dump(mode="json") for row in rows]

    def _get_payload_row(
        self, table: str, model: type[BaseModel], where: str, parameters: tuple[object, ...]
    ) -> PayloadRow | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {table} WHERE {where} LIMIT 1", parameters
            ).fetchone()
        return model.model_validate_json(row["payload"]).model_dump(mode="json") if row else None

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

    def reset_demo_records(self, task_id: str) -> None:
        tables = [
            "task_events",
            "context_snapshots",
            "agent_handoffs",
            "skill_invocations",
            "candidate_plans",
            "audit_verdicts",
            "approvals",
            "execution_commands",
            "execution_receipts",
            "verification_results",
            "rollback_records",
        ]
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM audit_events WHERE task_id = ?", (task_id,))
            for table in tables:
                connection.execute(f"DELETE FROM {table} WHERE task_id = ?", (task_id,))

    def save_task_event(self, event: TaskEvent) -> None:
        self._insert_payload_row(
            "task_events",
            event,
            {
                "event_id": event.event_id,
                "task_id": event.task_id,
                "task_version": event.task_version,
                "from_state": event.from_state.value if event.from_state else None,
                "to_state": event.to_state.value,
                "actor": event.actor,
                "trace_id": event.trace_id,
                "reason": event.reason,
                "created_at": event.timestamp.isoformat(),
                "input_reference": event.input_reference,
                "output_reference": event.output_reference,
                "skill_name": event.skill_name,
            },
        )

    def list_task_events(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("task_events", TaskEvent, task_id)

    def save_context_snapshot(self, context: ContextSnapshot) -> None:
        self._insert_payload_row(
            "context_snapshots",
            context,
            {
                "context_id": context.context_id,
                "task_id": context.task_id,
                "task_version": context.task_version,
                "context_hash": context.context_hash,
                "created_at": context.timestamp.isoformat(),
            },
        )

    def get_context_snapshot(self, task_id: str) -> PayloadRow | None:
        return self._get_payload_row(
            "context_snapshots",
            ContextSnapshot,
            "task_id = ? ORDER BY task_version DESC",
            (task_id,),
        )

    def save_agent_handoff(self, handoff: AgentHandoff) -> None:
        self._insert_payload_row(
            "agent_handoffs",
            handoff,
            {
                "id": handoff.id,
                "task_id": handoff.task_id,
                "task_version": handoff.task_version,
                "trace_id": handoff.trace_id,
                "from_agent": handoff.from_agent,
                "to_agent": handoff.to_agent,
                "status": handoff.status,
                "input_reference": handoff.input_reference,
                "output_reference": handoff.output_reference,
                "skill_name": handoff.skill_name,
                "created_at": handoff.created_at.isoformat(),
            },
        )

    def list_agent_handoffs(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("agent_handoffs", AgentHandoff, task_id)

    def save_skill_invocation(self, invocation: SkillInvocation) -> None:
        self._insert_payload_row(
            "skill_invocations",
            invocation,
            {
                "id": invocation.id,
                "task_id": invocation.task_id,
                "task_version": invocation.task_version,
                "trace_id": invocation.trace_id,
                "agent": invocation.agent,
                "skill_name": invocation.skill_name,
                "status": invocation.status,
                "input_reference": invocation.input_reference,
                "output_reference": invocation.output_reference,
                "started_at": invocation.started_at.isoformat(),
                "ended_at": invocation.ended_at.isoformat(),
                "duration_ms": invocation.duration_ms,
                "created_at": invocation.ended_at.isoformat(),
            },
        )

    def list_skill_invocations(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("skill_invocations", SkillInvocation, task_id)

    def save_candidate_plan(self, candidate: CandidatePlanRecord) -> None:
        self._insert_payload_row(
            "candidate_plans",
            candidate,
            {
                "id": candidate.id,
                "task_id": candidate.task_id,
                "task_version": candidate.task_version,
                "trace_id": candidate.trace_id,
                "context_id": candidate.context_id,
                "context_hash": candidate.context_hash,
                "candidate_id": candidate.candidate_id,
                "status": candidate.status,
                "cost_yuan": candidate.cost_yuan,
                "max_power_kw": candidate.max_power_kw,
                "soc_min_percent": candidate.soc_min_percent,
                "soc_max_percent": candidate.soc_max_percent,
                "transformer_load_percent": candidate.transformer_load_percent,
                "created_at": candidate.created_at.isoformat(),
            },
        )

    def list_candidate_plans(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("candidate_plans", CandidatePlanRecord, task_id)

    def save_audit_verdict(self, verdict: AuditVerdictRecord) -> None:
        self._insert_payload_row(
            "audit_verdicts",
            verdict,
            {
                "id": verdict.id,
                "task_id": verdict.task_id,
                "task_version": verdict.task_version,
                "trace_id": verdict.trace_id,
                "candidate_id": verdict.candidate_id,
                "context_hash": verdict.context_hash,
                "verdict": verdict.verdict,
                "reason": verdict.reason,
                "transformer_load_percent": verdict.transformer_load_percent,
                "safety_limit_percent": verdict.safety_limit_percent,
                "created_at": verdict.created_at.isoformat(),
            },
        )

    def list_audit_verdicts(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("audit_verdicts", AuditVerdictRecord, task_id)

    def save_approval_record(self, approval: ApprovalRecordV2) -> None:
        self._insert_payload_row(
            "approvals",
            approval,
            {
                "id": approval.id,
                "task_id": approval.task_id,
                "task_version": approval.task_version,
                "trace_id": approval.trace_id,
                "candidate_id": approval.candidate_id,
                "context_hash": approval.context_hash,
                "approved": int(approval.approved),
                "valid": int(approval.valid),
                "approver": approval.approver,
                "reason": approval.reason,
                "created_at": approval.created_at.isoformat(),
            },
        )

    def list_approvals(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("approvals", ApprovalRecordV2, task_id)

    def save_execution_command(self, command: ExecutionCommandRecord) -> None:
        self._insert_payload_row(
            "execution_commands",
            command,
            {
                "id": command.id,
                "task_id": command.task_id,
                "task_version": command.task_version,
                "trace_id": command.trace_id,
                "candidate_id": command.candidate_id,
                "idempotency_key": command.idempotency_key,
                "target_system": command.target_system,
                "resource_id": command.resource_id,
                "command": command.command,
                "value": command.value,
                "unit": command.unit,
                "status": command.status,
                "created_at": command.created_at.isoformat(),
            },
        )

    def list_execution_commands(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("execution_commands", ExecutionCommandRecord, task_id)

    def save_execution_receipt(self, receipt: ExecutionReceipt) -> None:
        self._insert_payload_row(
            "execution_receipts",
            receipt,
            {
                "id": receipt.id,
                "task_id": receipt.task_id,
                "task_version": receipt.task_version,
                "trace_id": receipt.trace_id,
                "candidate_id": receipt.candidate_id,
                "idempotency_key": receipt.idempotency_key,
                "status": receipt.status,
                "command_count": receipt.command_count,
                "simulated": int(receipt.simulated),
                "created_at": receipt.created_at.isoformat(),
            },
        )

    def get_execution_receipt_by_key(self, idempotency_key: str) -> PayloadRow | None:
        return self._get_payload_row(
            "execution_receipts",
            ExecutionReceipt,
            "idempotency_key = ?",
            (idempotency_key,),
        )

    def list_execution_receipts(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("execution_receipts", ExecutionReceipt, task_id)

    def save_verification_result(self, result: VerificationResult) -> None:
        self._insert_payload_row(
            "verification_results",
            result,
            {
                "id": result.id,
                "task_id": result.task_id,
                "task_version": result.task_version,
                "trace_id": result.trace_id,
                "candidate_id": result.candidate_id,
                "status": result.status,
                "max_deviation_percent": result.max_deviation_percent,
                "evidence_hash": result.evidence_hash,
                "created_at": result.created_at.isoformat(),
            },
        )

    def list_verification_results(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("verification_results", VerificationResult, task_id)

    def save_rollback_record(self, rollback: RollbackRecord) -> None:
        self._insert_payload_row(
            "rollback_records",
            rollback,
            {
                "id": rollback.id,
                "task_id": rollback.task_id,
                "task_version": rollback.task_version,
                "trace_id": rollback.trace_id,
                "reason": rollback.reason,
                "baseline_restored": int(rollback.baseline_restored),
                "created_at": rollback.created_at.isoformat(),
            },
        )

    def list_rollback_records(self, task_id: str) -> PayloadRows:
        return self._list_payload_rows("rollback_records", RollbackRecord, task_id)

    def demo_evidence(self, task_id: str) -> dict[str, object]:
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        evidence: dict[str, object] = {
            "schema_version": "2.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "safety_declaration": {
                "simulation_mode": True,
                "allow_production_write": False,
                "real_devices_contacted": 0,
                "data_source": "Simulation",
            },
            "task_record": task.model_dump(mode="json"),
            "context_snapshot": self.get_context_snapshot(task_id),
            "agent_handoffs": self.list_agent_handoffs(task_id),
            "skill_invocations": self.list_skill_invocations(task_id),
            "candidate_plans": self.list_candidate_plans(task_id),
            "audit_verdicts": self.list_audit_verdicts(task_id),
            "approvals": self.list_approvals(task_id),
            "execution_commands": self.list_execution_commands(task_id),
            "execution_receipts": self.list_execution_receipts(task_id),
            "verification_results": self.list_verification_results(task_id),
            "rollback_records": self.list_rollback_records(task_id),
            "task_events": self.list_task_events(task_id),
        }
        canonical = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        evidence["sha256"] = hashlib.sha256(canonical).hexdigest()
        return evidence

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
