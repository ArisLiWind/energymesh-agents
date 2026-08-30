"""Local RAG engine for historical deviation patterns.

Production: swap to PolarDB RAG vector extension.
Current: cosine similarity over JSON vectors in SQLite.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1
    nb = math.sqrt(sum(x * x for x in b)) or 1
    return dot / (na * nb)


def _encode(deviation: dict[str, Any]) -> list[float]:
    """Encode a deviation event into a 6-dim vector."""
    return [
        deviation.get("pv_deviation_percent", 0) / 100,
        deviation.get("load_deviation_percent", 0) / 100,
        deviation.get("soc_deviation_percent", 0) / 100,
        1.0 if deviation.get("pv_deviation_percent", 0) > 15 else 0,
        1.0 if deviation.get("load_deviation_percent", 0) > 10 else 0,
        1.0 if deviation.get("soc_deviation_percent", 0) > 10 else 0,
    ]


class RAGEngine:
    """Stores and retrieves historical confirmed deviations for decision explanation."""

    def __init__(self, db_path: str = ".data/rag_experience.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interval INTEGER,
            source TEXT,
            vector TEXT NOT NULL,
            event_json TEXT NOT NULL,
            reason TEXT,
            outcome TEXT,
            operator_adjustment TEXT,
            final_savings_yuan REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """)
        self.conn.commit()

    def add(
        self,
        interval: int,
        source: str,
        event: dict[str, Any],
        reason: str,
        outcome: str,
        operator_adjustment: str = "",
        savings: float = 0,
    ) -> None:
        vec = _encode(event)
        self.conn.execute(
            "INSERT INTO experiences (interval, source, vector, event_json, reason, outcome, operator_adjustment, final_savings_yuan) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                interval,
                source,
                json.dumps(vec),
                json.dumps(event),
                reason,
                outcome,
                operator_adjustment,
                savings,
            ),
        )
        self.conn.commit()

    def query_similar(
        self, current_event: dict[str, Any], top_k: int = 3
    ) -> list[dict[str, Any]]:
        target = _encode(current_event)
        rows = self.conn.execute(
            "SELECT id, interval, vector, event_json, reason, outcome, operator_adjustment, final_savings_yuan FROM experiences ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        scored = []
        for r in rows:
            vec = json.loads(r["vector"])
            sim = _cosine(target, vec)
            if sim > 0.3:
                scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "similarity": round(sim, 3),
                "interval": r["interval"],
                "reason": r["reason"],
                "outcome": r["outcome"],
                "operator_adjustment": r["operator_adjustment"],
                "savings_yuan": r["final_savings_yuan"],
            }
            for sim, r in scored[:top_k]
        ]

    def get_insight_for_deviation(self, event: dict[str, Any]) -> str:
        sims = self.query_similar(event, top_k=2)
        if not sims:
            return "历史库暂无相似偏差记录；本次由结构化优化器重新计算。"
        lines = ["历史经验检索："]
        for s in sims:
            lines.append(
                f"- 相似度 {s['similarity']} · 曾发生「{s['reason']}」→ {s['outcome']}"
            )
            if s["operator_adjustment"]:
                lines.append(f"  调度员当时调整：{s['operator_adjustment']}")
        return "\n".join(lines)
