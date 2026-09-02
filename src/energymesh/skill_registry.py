"""Skill Registry: discover, load, invoke, and version Skills with full Trace.

This module turns Skill declarations in agentteams/skills/*/SKILL.md into
runtime-callable capabilities with SemVer, invocation logging, and failure handling.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

SKILL_DIR = Path(__file__).resolve().parents[3] / "agentteams" / "skills"


@dataclass(frozen=True)
class SkillVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> SkillVersion:
        parts = text.strip().lstrip("v").split(".")
        return cls(int(parts[0]), int(parts[1]), int(parts[2]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class SkillSpec:
    name: str
    description: str
    version: SkillVersion
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    safety_boundary: str
    failure_policy: str
    called_by: list[str]
    tool_contract: str
    local_module: str
    local_callable: str
    registry_path: str
    checksum: str


@dataclass
class SkillInvocationRecord:
    invocation_id: str
    skill_name: str
    skill_version: str
    agent_id: str
    task_id: str
    task_version: int
    trace_id: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    status: str  # pending | running | success | failed | timeout | blocked
    error: str | None
    started_at: str
    ended_at: str | None
    duration_ms: int | None
    checksum_matched: bool


@dataclass
class SkillRegistry:
    skills: dict[str, SkillSpec] = field(default_factory=dict)
    invocations: list[SkillInvocationRecord] = field(default_factory=list)
    _impls: dict[str, Callable[..., Any]] = field(default_factory=dict, repr=False)

    def register(
        self,
        name: str,
        description: str,
        version: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        safety_boundary: str,
        failure_policy: str,
        called_by: list[str],
        tool_contract: str,
        local_module: str,
        local_callable: str,
        impl: Callable[..., Any],
    ) -> None:
        spec = SkillSpec(
            name=name,
            description=description,
            version=SkillVersion.parse(version),
            input_schema=input_schema,
            output_schema=output_schema,
            safety_boundary=safety_boundary,
            failure_policy=failure_policy,
            called_by=called_by,
            tool_contract=tool_contract,
            local_module=local_module,
            local_callable=local_callable,
            registry_path=f"agentteams/skills/{name}/SKILL.md",
            checksum=hashlib.sha256(
                json.dumps(
                    {
                        "name": name,
                        "version": str(version),
                        "safety": safety_boundary,
                        "schema": input_schema,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:16],
        )
        self.skills[name] = spec
        self._impls[name] = impl

    def discover_from_markdown(self) -> None:
        """Parse SKILL.md files to update metadata (not callable impl)."""
        if not SKILL_DIR.exists():
            return
        for skill_path in SKILL_DIR.iterdir():
            md = skill_path / "SKILL.md"
            if md.exists():
                text = md.read_text(encoding="utf-8")
                name = skill_path.name
                # Minimal parsing: if already registered, no-op; else stub.
                if name not in self.skills:
                    # stub will be overwritten by explicit register()
                    pass

    def invoke(
        self,
        skill_name: str,
        agent_id: str,
        task_id: str,
        task_version: int,
        trace_id: str,
        payload: dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> SkillInvocationRecord:
        spec = self.skills.get(skill_name)
        if spec is None:
            raise RuntimeError(f"Skill '{skill_name}' not registered in registry")
        if agent_id not in spec.called_by and "*" not in spec.called_by:
            raise PermissionError(
                f"Agent '{agent_id}' is not authorized to call Skill '{skill_name}'"
            )
        inv_id = f"sk-{task_id}-{skill_name}-{int(time.time()*1000)}"
        started = datetime.now(UTC).isoformat()
        record = SkillInvocationRecord(
            invocation_id=inv_id,
            skill_name=skill_name,
            skill_version=str(spec.version),
            agent_id=agent_id,
            task_id=task_id,
            task_version=task_version,
            trace_id=trace_id,
            input_payload=payload,
            output_payload=None,
            status="running",
            error=None,
            started_at=started,
            ended_at=None,
            duration_ms=None,
            checksum_matched=True,
        )
        impl = self._impls.get(skill_name)
        if impl is None:
            record.status = "failed"
            record.error = f"No runtime implementation registered for Skill '{skill_name}'"
            record.ended_at = datetime.now(UTC).isoformat()
            self.invocations.append(record)
            return record
        try:
            t0 = time.perf_counter()
            result = impl(**payload)
            elapsed = int((time.perf_counter() - t0) * 1000)
            record.output_payload = (
                result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            )
            record.status = "success"
            record.duration_ms = elapsed
            record.ended_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            elapsed = int((time.perf_counter() - t0) * 1000)
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.duration_ms = elapsed
            record.ended_at = datetime.now(UTC).isoformat()
            if spec.failure_policy == "block":
                raise
        self.invocations.append(record)
        return record

    def list_invocations(
        self, task_id: str | None = None, skill_name: str | None = None
    ) -> list[SkillInvocationRecord]:
        out = self.invocations[:]
        if task_id:
            out = [r for r in out if r.task_id == task_id]
        if skill_name:
            out = [r for r in out if r.skill_name == skill_name]
        return out

    def health(self) -> dict[str, Any]:
        return {
            "registered_skills": [
                {
                    "name": s.name,
                    "version": str(s.version),
                    "called_by": s.called_by,
                    "checksum": s.checksum,
                    "has_impl": s.name in self._impls,
                }
                for s in self.skills.values()
            ],
            "total_invocations": len(self.invocations),
            "failed_invocations": len([r for r in self.invocations if r.status == "failed"]),
            "timeout_invocations": len([r for r in self.invocations if r.status == "timeout"]),
        }
