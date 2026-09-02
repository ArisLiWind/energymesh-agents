"""Skill Registry: discoverable, loadable, invocable Skills with versioning and traceability.

This is the runtime layer that makes Skills real. It replaces direct Python function calls
with explicit Skill discovery, load, invocation, and trace records.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from energymesh.models import SkillInvocation


class SkillStatus(StrEnum):
    READY = "ready"
    LOADING = "loading"
    FAILED = "failed"
    DEPRECATED = "deprecated"


class SkillResultStatus(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    REJECTED = "rejected"
    PARTIAL = "partial"


@dataclass(frozen=True)
class SkillResult:
    status: SkillResultStatus
    payload: dict[str, Any]
    error: str | None = None
    duration_ms: float = 0.0
    version: str = "0.1.0"


class BaseSkill(ABC):
    """Abstract base for all Skills. Every Skill must declare its contract."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    safety_boundary: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2

    @abstractmethod
    def invoke(self, context: dict[str, Any], task_id: str, trace_id: str) -> SkillResult:
        """Execute the Skill. Must be deterministic and safe."""
        ...

    def health(self) -> dict[str, Any]:
        return {
            "skill": self.name,
            "version": self.version,
            "status": SkillStatus.READY,
            "timeout": self.timeout_seconds,
            "max_retries": self.max_retries,
        }


class SkillRegistry:
    """Central registry for Skill discovery, loading, versioning, and invocation.

    - Skills are registered by name with version
    - Each invocation produces a SkillInvocation trace record
    - Failed Skills can be retired; new versions can be registered
    - Circuit breaker pattern per Skill to prevent cascade failures
    """

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._versions: dict[str, str] = {}
        self._circuit_failures: dict[str, int] = {}
        self._circuit_threshold: int = 3
        self._invocation_log: list[SkillInvocation] = []

    def register(self, skill: BaseSkill) -> None:
        name = skill.name
        self._skills[name] = skill
        self._versions[name] = skill.version
        self._circuit_failures[name] = 0

    def discover(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "version": self._versions.get(name, "unknown"),
                "status": (
                    SkillStatus.READY
                    if self._circuit_failures.get(name, 0) < self._circuit_threshold
                    else SkillStatus.FAILED
                ),
                "contract": getattr(skill, "description", ""),
                "safety_boundary": getattr(skill, "safety_boundary", ""),
            }
            for name, skill in self._skills.items()
        ]

    def load(self, name: str) -> BaseSkill | None:
        if name not in self._skills:
            return None
        if self._circuit_failures.get(name, 0) >= self._circuit_threshold:
            return None
        return self._skills[name]

    def invoke(
        self,
        name: str,
        agent_id: str,
        context: dict[str, Any],
        task_id: str,
        task_version: int,
        trace_id: str,
    ) -> SkillResult:
        skill = self.load(name)
        if skill is None:
            return SkillResult(
                status=SkillResultStatus.ERROR,
                payload={},
                error=f"Skill '{name}' not found or circuit open",
                version="unknown",
            )

        started = datetime.now(UTC)
        invocation_id = f"skill_{uuid4().hex[:12]}"
        attempt = 0
        last_error: str | None = None
        result: SkillResult | None = None

        while attempt <= skill.max_retries:
            attempt += 1
            try:
                result = skill.invoke(context, task_id, trace_id)
                break
            except Exception as e:
                last_error = f"[{attempt}/{skill.max_retries + 1}] {type(e).__name__}: {e}"
                if attempt > skill.max_retries:
                    break

        ended = datetime.now(UTC)
        duration_ms = (ended - started).total_seconds() * 1000

        if result is None:
            result = SkillResult(
                status=SkillResultStatus.ERROR,
                payload={},
                error=last_error or "unknown failure",
                duration_ms=duration_ms,
                version=skill.version,
            )
            self._circuit_failures[name] = self._circuit_failures.get(name, 0) + 1
        else:
            if result.status in (SkillResultStatus.ERROR, SkillResultStatus.TIMEOUT):
                self._circuit_failures[name] = self._circuit_failures.get(name, 0) + 1
            else:
                self._circuit_failures[name] = 0

        invocation = SkillInvocation(
            id=invocation_id,
            task_id=task_id,
            task_version=task_version,
            trace_id=trace_id,
            agent=agent_id,
            skill_name=name,
            status=result.status.value,
            input_reference=self._hash_input(context),
            output_reference=self._hash_output(result.payload),
            started_at=started,
            ended_at=ended,
            duration_ms=int(duration_ms),
        )
        self._invocation_log.append(invocation)
        return SkillResult(
            status=result.status,
            payload=result.payload,
            error=result.error,
            duration_ms=duration_ms,
            version=skill.version,
        )

    @staticmethod
    def _hash_input(data: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    @staticmethod
    def _hash_output(data: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def get_invocations(self, task_id: str) -> list[SkillInvocation]:
        return [inv for inv in self._invocation_log if inv.task_id == task_id]

    def reset_circuit(self, name: str) -> None:
        self._circuit_failures[name] = 0


def make_skill_from_callable(
    name: str,
    fn: Callable[..., Any],
    version: str = "0.1.0",
    description: str = "",
    safety_boundary: str = "",
    timeout_seconds: float = 30.0,
    max_retries: int = 2,
) -> BaseSkill:
    """Wrap a callable as a proper Skill for rapid development."""

    _name = name
    _version = version
    _description = description
    _safety_boundary = safety_boundary
    _timeout_seconds = timeout_seconds
    _max_retries = max_retries

    class CallableSkill(BaseSkill):
        name = _name
        version = _version
        description = _description
        safety_boundary = _safety_boundary
        timeout_seconds = _timeout_seconds
        max_retries = _max_retries

        def invoke(self, context: dict[str, Any], task_id: str, trace_id: str) -> SkillResult:
            sig = inspect.signature(fn)
            kwargs: dict[str, Any] = {}
            for param in sig.parameters:
                if param in context:
                    kwargs[param] = context[param]
            result = fn(**kwargs)
            if isinstance(result, SkillResult):
                return result
            return SkillResult(
                status=SkillResultStatus.SUCCESS,
                payload=result if isinstance(result, dict) else {"result": result},
                version=self.version,
            )

    return CallableSkill()
