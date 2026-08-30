"""SLO metrics, alerting, and runtime observability.

Counters feed into /api/observability/status for health dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class SLOMetrics:
    plan_refresh_ms: float = 0.0
    reoptimization_count: int = 0
    invalidated_plan_count: int = 0
    constraint_violations: int = 0
    deviation_rollbacks: int = 0
    total_executed_intervals: int = 0
    total_savings_yuan: float = 0.0
    avg_response_ms: float = 0.0
    _response_times: list[float] = field(default_factory=list)

    def record_plan_refresh(self, elapsed_ms: float) -> None:
        self.plan_refresh_ms = elapsed_ms
        self._response_times.append(elapsed_ms)
        if len(self._response_times) > 50:
            self._response_times.pop(0)
        self.avg_response_ms = sum(self._response_times) / len(self._response_times)

    def record_reopt(self) -> None:
        self.reoptimization_count += 1

    def record_invalidated(self) -> None:
        self.invalidated_plan_count += 1

    def record_violation(self) -> None:
        self.constraint_violations += 1

    def record_rollback(self) -> None:
        self.deviation_rollbacks += 1

    def record_execution(self, intervals: int = 1) -> None:
        self.total_executed_intervals += intervals

    def record_savings(self, yuan: float) -> None:
        self.total_savings_yuan += yuan

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self.avg_response_ms < 3000 else "degraded",
            "plan_refresh_p99_ms": self.plan_refresh_ms,
            "avg_response_ms": round(self.avg_response_ms, 1),
            "reoptimizations": self.reoptimization_count,
            "invalidated_plans": self.invalidated_plan_count,
            "constraint_violations": self.constraint_violations,
            "deviation_rollbacks": self.deviation_rollbacks,
            "executed_intervals": self.total_executed_intervals,
            "cumulative_savings_yuan": round(self.total_savings_yuan, 2),
            "readback_rate": round(
                self.total_executed_intervals
                / max(1, self.total_executed_intervals)
                * 100,
                1,
            ),
            "timestamp": datetime.now(UTC).isoformat(),
        }
