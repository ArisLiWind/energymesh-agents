from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from energymesh.api import create_app
from energymesh.mcp_server import handle_mcp_message, tools_for_profile
from energymesh.models import ExternalTelemetryPoint
from energymesh.polardb_store import PolarDBStore


def test_mcp_profiles_expose_least_privilege_tools() -> None:
    assert [tool.name for tool in tools_for_profile("readonly")] == [
        "energy.snapshot.read",
        "microgrid.context.ingest",
    ]
    assert [tool.name for tool in tools_for_profile("planning")] == [
        "dispatch.plan.generate",
    ]
    assert [tool.name for tool in tools_for_profile("audit")] == [
        "dispatch.audit.verify",
    ]
    assert [tool.name for tool in tools_for_profile("control")] == [
        "approval.validate",
        "execution.simulate",
        "execution.readback",
        "control.rollback",
    ]


def test_mcp_jsonrpc_discovery_and_call() -> None:
    listed = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "planning")
    assert listed is not None
    assert listed["result"]["tools"][0]["name"] == "dispatch.plan.generate"

    called = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "energy.snapshot.read", "arguments": {"task": "新增 1MW 负荷"}},
        },
        "readonly",
    )
    assert called is not None
    assert called["result"]["isError"] is False
    assert "current_load_mw" in called["result"]["content"][0]["text"]

    denied = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "execution.simulate", "arguments": {}},
        },
        "readonly",
    )
    assert denied is not None
    assert denied["error"]["code"] == -32602


def test_fastapi_mcp_routes(settings) -> None:
    with TestClient(create_app(settings)) as client:
        tools = client.get("/mcp/control/tools")
        assert tools.status_code == 200
        assert "execution.simulate" in {tool["name"] for tool in tools.json()["tools"]}

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["polardb"]["backend"] == "sqlite"


def test_polardb_store_sqlite_fallback_roundtrip(tmp_path) -> None:
    store = PolarDBStore(str(tmp_path / "polardb_telemetry.db"))
    point = ExternalTelemetryPoint(
        interval=1,
        timestamp=datetime.now(UTC),
        load_kw=600,
        pv_kw=120,
        battery_soc=0.55,
        tariff_yuan_per_kwh=0.82,
        transformer_temperature_c=61,
        transformer_limit_kw=1250,
        grid_interconnection_limit_kw=1100,
        battery_available=True,
        production_min_load_kw=480,
    )
    store.write_telemetry("unit-test", point)
    store.write_plan_version("pv_1", "task_1", "plan_a", 0, 95, point.timestamp.isoformat())
    store.write_execution(
        "exec_1",
        "task_1",
        "pv_1",
        1,
        actual={"grid_kw": 510, "soc": 0.54},
        expected={"grid_kw": 500, "soc": 0.55},
        deviation=True,
    )

    assert store.health()["backend"] == "sqlite"
    assert store.get_latest_snapshot("unit-test", 1)["load_kw"] == 600
    assert store.get_active_plan_at("task_1", 1)["plan_id"] == "plan_a"
    assert store.get_deviation_stats("task_1") == {"total_executed": 1, "deviations": 1}
    store.close()
