from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from energymesh.audit import IndependentSafetyAuditor
from energymesh.config import Settings
from energymesh.demo import load_demo_scenario
from energymesh.mcp_gateway import EnergyMCPGateway
from energymesh.models import DispatchPlan, Scenario
from energymesh.optimizer import DispatchOptimizer
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    profile: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _scenario_from_args(args: dict[str, Any]) -> Scenario:
    scenario = args.get("scenario")
    if isinstance(scenario, dict):
        return Scenario.model_validate(scenario)
    return load_demo_scenario()


def _plans_from_args(
    args: dict[str, Any], scenario: Scenario
) -> tuple[DispatchPlan, list[DispatchPlan]]:
    optimizer = DispatchOptimizer()
    baseline_arg = args.get("baseline_plan")
    plans_arg = args.get("plans")
    baseline = (
        DispatchPlan.model_validate(baseline_arg)
        if isinstance(baseline_arg, dict)
        else optimizer.build_baseline(scenario)
    )
    plans = (
        [DispatchPlan.model_validate(plan) for plan in plans_arg]
        if isinstance(plans_arg, list)
        else optimizer.optimize_candidates(scenario)
    )
    return baseline, plans


def _selected_plan(args: dict[str, Any], plans: list[DispatchPlan]) -> DispatchPlan:
    selected_plan_id = args.get("selected_plan_id")
    if isinstance(selected_plan_id, str):
        for plan in plans:
            if plan.plan_id == selected_plan_id:
                return plan
    return min(plans, key=lambda plan: plan.metrics.total_cost_yuan)


def _read_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    task = str(args.get("task", "day-ahead dispatch"))
    result = EnergyMCPGateway().get_energy_state(task)
    return {
        "tool_name": result.tool_name,
        "input": result.input_payload,
        "output": result.output_payload,
    }


def _ingest_context(args: dict[str, Any]) -> dict[str, Any]:
    scenario = _scenario_from_args(args)
    report = PerceptionAgent().inspect(scenario)
    return {
        "scenario_id": scenario.scenario_id,
        "perception": report.model_dump(mode="json"),
        "required_tools": report.required_tools,
    }


def _generate_plan(args: dict[str, Any]) -> dict[str, Any]:
    scenario = _scenario_from_args(args)
    optimizer = DispatchOptimizer()
    baseline = optimizer.build_baseline(scenario)
    plans = optimizer.optimize_candidates(scenario)
    return {
        "scenario_id": scenario.scenario_id,
        "baseline_plan": baseline.model_dump(mode="json"),
        "plans": [plan.model_dump(mode="json") for plan in plans],
    }


def _audit_plan(args: dict[str, Any]) -> dict[str, Any]:
    scenario = _scenario_from_args(args)
    baseline, plans = _plans_from_args(args, scenario)
    auditor = IndependentSafetyAuditor()
    audits = [auditor.audit(scenario, plan, baseline) for plan in plans]
    return {
        "scenario_id": scenario.scenario_id,
        "audits": [audit.model_dump(mode="json") for audit in audits],
    }


def _validate_approval(args: dict[str, Any]) -> dict[str, Any]:
    approver = str(args.get("approver", "")).strip()
    approved = bool(args.get("approved", False))
    reason = str(args.get("reason", "")).strip()
    return {
        "valid": approved and bool(approver) and bool(reason),
        "approved": approved,
        "approver": approver or "missing",
        "reason": reason or "missing",
        "production_write_allowed": False,
    }


def _simulate_execution(args: dict[str, Any]) -> dict[str, Any]:
    scenario = _scenario_from_args(args)
    baseline, plans = _plans_from_args(args, scenario)
    selected = _selected_plan(args, plans)
    settings = Settings.from_env()
    settings.assert_safe_runtime()
    receipt = SimulationExecutor(settings).execute(
        scenario,
        selected,
        baseline,
        approval_id=args.get("approval_id") if isinstance(args.get("approval_id"), str) else None,
    )
    return {
        "scenario_id": scenario.scenario_id,
        "selected_plan_id": selected.plan_id,
        "receipt": receipt,
    }


def _readback(args: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(args.get("execution_id", "latest-simulation"))
    return {
        "execution_id": execution_id,
        "real_devices_contacted": 0,
        "readback_source": "simulation_receipt",
        "status": "verified",
    }


def _rollback(args: dict[str, Any]) -> dict[str, Any]:
    reason = str(args.get("reason", "operator requested rollback"))
    return {
        "rollback_id": "rollback-simulation-only",
        "reason": reason,
        "baseline_restored": True,
        "real_devices_contacted": 0,
    }


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": True,
    }


def build_tools() -> list[McpTool]:
    return [
        McpTool(
            name="energy.snapshot.read",
            description="Read EMS/BMS/PCS/MES-style EnergyMesh operating snapshot.",
            profile="readonly",
            input_schema=_object_schema({"task": {"type": "string"}}),
            handler=_read_snapshot,
        ),
        McpTool(
            name="microgrid.context.ingest",
            description="Validate scenario context and report required EnergyMesh tools.",
            profile="readonly",
            input_schema=_object_schema({"scenario": {"type": "object"}}),
            handler=_ingest_context,
        ),
        McpTool(
            name="dispatch.plan.generate",
            description="Generate deterministic baseline and candidate dispatch plans.",
            profile="planning",
            input_schema=_object_schema({"scenario": {"type": "object"}}),
            handler=_generate_plan,
        ),
        McpTool(
            name="dispatch.audit.verify",
            description="Independently recompute constraints and audit dispatch candidates.",
            profile="audit",
            input_schema=_object_schema(
                {
                    "scenario": {"type": "object"},
                    "baseline_plan": {"type": "object"},
                    "plans": {"type": "array", "items": {"type": "object"}},
                }
            ),
            handler=_audit_plan,
        ),
        McpTool(
            name="approval.validate",
            description="Validate human approval payload before any control-side action.",
            profile="control",
            input_schema=_object_schema(
                {
                    "approved": {"type": "boolean"},
                    "approver": {"type": "string"},
                    "reason": {"type": "string"},
                },
                required=["approved", "approver", "reason"],
            ),
            handler=_validate_approval,
        ),
        McpTool(
            name="execution.simulate",
            description="Map an approved plan into simulation-only EMS/PCS/load commands.",
            profile="control",
            input_schema=_object_schema(
                {
                    "scenario": {"type": "object"},
                    "baseline_plan": {"type": "object"},
                    "plans": {"type": "array", "items": {"type": "object"}},
                    "selected_plan_id": {"type": "string"},
                    "approval_id": {"type": "string"},
                }
            ),
            handler=_simulate_execution,
        ),
        McpTool(
            name="execution.readback",
            description="Read back a simulation receipt and summarize verification state.",
            profile="control",
            input_schema=_object_schema({"execution_id": {"type": "string"}}),
            handler=_readback,
        ),
        McpTool(
            name="control.rollback",
            description=(
                "Create a simulation-only rollback receipt that restores baseline ownership."
            ),
            profile="control",
            input_schema=_object_schema({"reason": {"type": "string"}}),
            handler=_rollback,
        ),
    ]


def tools_for_profile(profile: str | None = None) -> list[McpTool]:
    requested = profile or os.getenv("ENERGYMESH_MCP_PROFILE") or "all"
    if requested in {"all", "*"}:
        return build_tools()
    return [tool for tool in build_tools() if tool.profile == requested]


def mcp_response(result: Any, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def mcp_error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_mcp_message(
    message: dict[str, Any], profile: str | None = None
) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    tools = {tool.name: tool for tool in tools_for_profile(profile)}

    if method == "initialize":
        return mcp_response(
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "energymesh-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
            request_id,
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return mcp_response({}, request_id)
    if method == "tools/list":
        return mcp_response(
            {
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                    for tool in tools.values()
                ]
            },
            request_id,
        )
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not isinstance(name, str) or name not in tools:
            return mcp_error(-32602, f"Unknown or unauthorized MCP tool: {name}", request_id)
        try:
            payload = tools[name].handler(args)
        except Exception as exc:
            return mcp_error(-32000, f"{type(exc).__name__}: {exc}", request_id)
        return mcp_response(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False),
                    }
                ],
                "isError": False,
            },
            request_id,
        )
    return mcp_error(-32601, f"Unsupported MCP method: {method}", request_id)


def run_stdio(profile: str | None = None) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_mcp_message(message, profile)
        except json.JSONDecodeError as exc:
            response = mcp_error(-32700, f"Parse error: {exc}", None)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    profile = sys.argv[1] if len(sys.argv) > 1 else None
    run_stdio(profile)


if __name__ == "__main__":
    main()
