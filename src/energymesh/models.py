from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskState(StrEnum):
    RECEIVED = "received"
    CONTEXT_READY = "context_ready"
    PLANS_GENERATED = "plans_generated"
    AUDITED = "audited"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    SAFE_FALLBACK = "safe_fallback"
    HUMAN_HANDOFF = "human_handoff"
    FAILED = "failed"


class AuditDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRES_APPROVAL = "requires_approval"


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str = "demo-park-01"
    interval_minutes: int = Field(default=15, ge=5, le=60)
    transformer_capacity_kw: float = Field(default=1_250, gt=0)
    transformer_temperature_limit_c: float = Field(default=75, ge=20, le=120)
    transformer_hot_derate_factor: float = Field(default=0.68, gt=0, le=1)
    grid_interconnection_limit_kw: float = Field(default=1_100, gt=0)
    battery_capacity_kwh: float = Field(default=800, gt=0)
    battery_charge_max_kw: float = Field(default=320, gt=0)
    battery_discharge_max_kw: float = Field(default=320, gt=0)
    battery_efficiency_charge: float = Field(default=0.95, gt=0, le=1)
    battery_efficiency_discharge: float = Field(default=0.95, gt=0, le=1)
    initial_soc: float = Field(default=0.55, ge=0, le=1)
    safety_min_soc: float = Field(default=0.20, ge=0, le=1)
    safety_max_soc: float = Field(default=0.90, ge=0, le=1)
    demand_charge_yuan_per_kw: float = Field(default=8.0, ge=0)
    degradation_yuan_per_kwh: float = Field(default=0.08, ge=0)
    flexible_load_kw: float = Field(default=120, ge=0)
    alarm_discharge_derate: float = Field(default=0.35, gt=0, le=1)

    @model_validator(mode="after")
    def validate_soc_bounds(self) -> SiteConfig:
        if not self.safety_min_soc < self.initial_soc < self.safety_max_soc:
            raise ValueError("initial_soc must be inside the safety SOC range")
        return self


class ForecastPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    load_kw: float = Field(ge=0)
    pv_kw: float = Field(ge=0)
    production_min_load_kw: float = Field(ge=0)
    tariff_yuan_per_kwh: float = Field(ge=0)
    battery_temperature_c: float = Field(default=27, ge=-30, le=100)
    transformer_temperature_c: float = Field(default=55, ge=-30, le=150)
    transformer_redundant_temperature_c: float = Field(default=54, ge=-30, le=150)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str
    description: str
    site: SiteConfig
    forecast: list[ForecastPoint]
    alerts: list[str] = Field(default_factory=list)
    device_status: dict[str, str] = Field(default_factory=dict)
    production_plan: dict[str, Any] = Field(default_factory=dict)
    simulation_faults: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_horizon(self) -> Scenario:
        expected = 24 * 60 // self.site.interval_minutes
        if len(self.forecast) != expected:
            raise ValueError(f"forecast must contain exactly {expected} intervals")
        return self


class ExternalTelemetryPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: int
    timestamp: datetime
    load_kw: float = Field(ge=0)
    pv_kw: float = Field(ge=0)
    battery_soc: float = Field(ge=0, le=1)
    tariff_yuan_per_kwh: float = Field(ge=0)
    transformer_temperature_c: float = Field(ge=-30, le=150)
    transformer_limit_kw: float = Field(gt=0)
    grid_interconnection_limit_kw: float = Field(gt=0)
    battery_available: bool
    fault_code: str | None = None
    production_min_load_kw: float = Field(ge=0)


class ExternalDataSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    generated_at: datetime
    current_interval: int = Field(ge=0)
    scenario: Scenario
    telemetry: list[ExternalTelemetryPoint]
    current: ExternalTelemetryPoint
    environment_signals: dict[str, Any]
    layer_summary: dict[str, list[str]]


class ExternalDispatchRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=10_000)
    current_interval: int = Field(default=57, ge=0, le=95)
    fault_mode: str = Field(
        default="cloud_and_transformer_heat",
        min_length=2,
        max_length=80,
    )


class DispatchPoint(BaseModel):
    interval: int
    timestamp: datetime
    load_kw: float
    pv_kw: float
    charge_kw: float
    discharge_kw: float
    grid_import_kw: float
    pv_curtailment_kw: float
    flexible_load_shed_kw: float
    soc_start: float
    soc_end: float


class PlanMetrics(BaseModel):
    energy_cost_yuan: float
    demand_charge_yuan: float
    degradation_cost_yuan: float
    total_cost_yuan: float
    peak_grid_kw: float
    pv_self_consumption_ratio: float
    end_soc: float
    shed_energy_kwh: float


class PerceptionReport(BaseModel):
    data_complete: bool
    quality_score: float = Field(ge=0, le=1)
    original_task_valid: bool
    recommended_action: str
    validated_inputs: list[str]
    active_constraints: list[str]
    change_signals: list[str]
    missing_data: list[str]
    anomalies: list[str]
    conflicts: list[str]
    objective_priority: list[str]
    required_tools: list[str]


class DispatchPlan(BaseModel):
    plan_id: str
    profile: str
    rationale: str
    declared_min_soc: float
    points: list[DispatchPoint]
    metrics: PlanMetrics
    solver_status: str


class AuditFinding(BaseModel):
    code: str
    severity: str
    message: str
    interval: int | None = None


class AuditReport(BaseModel):
    plan_id: str
    decision: AuditDecision
    findings: list[AuditFinding]
    checked_rules: list[str]
    baseline_total_cost_yuan: float
    improvement_yuan: float
    improvement_ratio: float


class ApprovalRecord(BaseModel):
    approval_id: str
    task_id: str
    approved: bool
    approver: str
    reason: str
    created_at: datetime


class TraceEvent(BaseModel):
    sequence: int
    timestamp: datetime
    actor: str
    action: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ExecutionCommand(BaseModel):
    command_id: str
    target_system: str
    resource_id: str
    interval: int
    parameter: str
    value: float
    unit: str
    idempotency_key: str
    approval_id: str | None = None


class TaskRecord(BaseModel):
    task_id: str
    scenario_id: str
    scenario_snapshot: Scenario
    state: TaskState
    created_at: datetime
    updated_at: datetime
    trigger: str = "day_ahead_schedule"
    parent_task_id: str | None = None
    perception: PerceptionReport | None = None
    baseline_plan: DispatchPlan | None = None
    plans: list[DispatchPlan] = Field(default_factory=list)
    audits: list[AuditReport] = Field(default_factory=list)
    selected_plan_id: str | None = None
    approval: ApprovalRecord | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    execution_summary: dict[str, Any] | None = None
    human_handoff_reason: str | None = None
    evidence_sha256: str | None = None


class ApprovalRequest(BaseModel):
    approved: bool
    approver: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=2, max_length=500)


class ReoptimizationRequest(BaseModel):
    trigger: str = Field(min_length=2, max_length=100)
    load_scale: float = Field(default=1.0, ge=0.5, le=1.8)
    pv_scale: float = Field(default=1.0, ge=0.0, le=1.5)
    soc_delta: float = Field(default=0.0, ge=-0.3, le=0.3)
    battery_available: bool = True
    transformer_temperature_c: float | None = Field(default=None, ge=-30, le=150)
    transformer_redundant_temperature_c: float | None = Field(default=None, ge=-30, le=150)
    emergency_production: bool = False
    simulate_execution_deviation: bool = False


class AgentModelConfigRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=120)


class AgentModelConfigPublic(BaseModel):
    agent_id: str
    base_url: str
    api_key_masked: str
    model: str
    connection_status: str
    last_error: str | None = None


class AgentModelTestResponse(BaseModel):
    success: bool
    model: str | None = None
    error: str | None = None


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class AgentChatResponse(BaseModel):
    agent_id: str
    model: str
    response: str
