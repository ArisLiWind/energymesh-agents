from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from energymesh.api import create_app


def test_agentteams_resource_assets_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    resources = root / "agentteams" / "agentteams-resources.yaml"
    text = resources.read_text(encoding="utf-8")
    assert "apiVersion: agentteams.io/v1beta1" in text
    assert "kind: Team" in text
    assert "runtime: openclaw" in text
    assert "runtime: copaw" in text
    assert (root / "agentteams" / "team-leader" / "AGENTS.md").exists()


def test_health_and_demo_workflow(settings) -> None:
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["simulation_mode"] is True
        assert health.json()["allow_production_write"] is False
        assert health.json()["agent_framework"] == "agentscope-ai/AgentTeams"

        manifest = client.get("/api/agentteams/manifest")
        assert manifest.status_code == 200
        manifest_body = manifest.json()
        assert manifest_body["framework"] == "agentscope-ai/AgentTeams open-source runtime"
        assert manifest_body["framework_repository"] == "https://github.com/agentscope-ai/AgentTeams"
        assert manifest_body["team_name"] == "energymesh-test-team"
        assert manifest_body["declarative_resources"] == "agentteams/agentteams-resources.yaml"
        assert [worker["worker_id"] for worker in manifest_body["workers"]] == [
            "energymesh_team_leader",
            "perception_worker",
            "dispatch_worker",
            "audit_worker",
            "execution_worker",
        ]

        page = client.get("/")
        assert page.status_code == 200
        assert re.search(r'id="close-dialog"[^>]*type="button"', page.text)
        script = client.get("/static/app.js")
        assert '"#close-dialog").addEventListener("click"' in script.text

        scenario = client.get("/api/demo/scenario")
        assert scenario.status_code == 200
        assert len(scenario.json()["forecast"]) == 96

        snapshot = client.get("/api/external/snapshot")
        assert snapshot.status_code == 200
        snapshot_body = snapshot.json()
        assert snapshot_body["source"] == "simulated_external_feeds"
        assert len(snapshot_body["telemetry"]) == 96
        assert {
            "load_kw",
            "pv_kw",
            "battery_soc",
            "tariff_yuan_per_kwh",
            "transformer_limit_kw",
            "grid_interconnection_limit_kw",
            "fault_code",
            "production_min_load_kw",
        }.issubset(snapshot_body["environment_signals"])
        assert snapshot_body["layer_summary"]["deterministic_verification"]

        external_task = client.post(
            "/api/external/dispatch",
            json={
                "seed": 42,
                "current_interval": 57,
                "fault_mode": "cloud_and_transformer_heat",
            },
        )
        assert external_task.status_code == 201
        external_body = external_task.json()
        assert external_body["trigger"] == "EXTERNAL_DATA_CLOUD_AND_TRANSFORMER_HEAT"
        assert external_body["scenario_snapshot"]["production_plan"]["source"] == "simulated_mes"
        assert any(
            event["action"] == "independent_policy_audit"
            for event in external_body["trace"]
        )

        created = client.post("/api/demo/run")
        assert created.status_code == 201
        task = created.json()
        assert task["state"] == "awaiting_approval"
        assert task["perception"]["original_task_valid"] is False
        assert task["perception"]["recommended_action"] == "redefine_and_optimize"
        assert task["trace"][0]["detail"]["agentteams_worker"] == "energymesh_team_leader"

        completed = client.post(
            f"/api/tasks/{task['task_id']}/approval",
            json={
                "approved": True,
                "approver": "api-test",
                "reason": "integration test approval",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["state"] == "completed"
        assert completed.json()["execution_summary"]["real_devices_contacted"] == 0

        changed = client.post(
            f"/api/tasks/{task['task_id']}/reoptimize",
            json={
                "trigger": "LOAD_FORECAST_CHANGED",
                "load_scale": 1.05,
                "pv_scale": 0.9,
                "soc_delta": -0.03,
                "battery_available": True,
            },
        )
        assert changed.status_code == 201
        changed_task = changed.json()
        assert changed_task["parent_task_id"] == task["task_id"]
        assert changed_task["trigger"] == "LOAD_FORECAST_CHANGED"
        assert changed_task["state"] == "awaiting_approval"


def test_agent_model_config_test_and_chat(settings, monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_chat(config, message: str) -> str:
        calls.append((config.agent_id, config.model, message))
        if message == "Reply with OK.":
            return "OK"
        return f"{config.agent_id}: {message}"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        saved = client.put(
            "/api/agents/perception_agent/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-secret-value",
                "model": "deepseek-chat",
            },
        )
        assert saved.status_code == 200
        saved_body = saved.json()
        assert saved_body["agent_id"] == "perception_agent"
        assert saved_body["api_key_masked"] != "sk-secret-value"
        assert saved_body["connection_status"] == "未测试"

        manifest = client.get("/api/agentteams/manifest").json()
        assert manifest["model_configs"]["perception_agent"]["model"] == "deepseek-chat"
        assert manifest["model_configs"]["perception_agent"]["api_key_masked"] != (
            "sk-secret-value"
        )

        tested = client.post("/api/agents/perception_agent/model/test")
        assert tested.status_code == 200
        assert tested.json() == {"success": True, "model": "deepseek-chat", "error": None}

        chatted = client.post(
            "/api/agents/perception_agent/chat",
            json={"message": "现在储能设备状态怎么样？"},
        )
        assert chatted.status_code == 200
        assert chatted.json()["response"] == "perception_agent: 现在储能设备状态怎么样？"
        assert calls == [
            ("perception_agent", "deepseek-chat", "Reply with OK."),
            ("perception_agent", "deepseek-chat", "现在储能设备状态怎么样？"),
        ]


def test_agent_model_test_returns_real_error(settings, monkeypatch) -> None:
    def failing_chat(config, message: str) -> str:
        raise RuntimeError("Invalid API key")

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", failing_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/audit_agent/model",
            json={
                "base_url": "https://api.anthropic-compatible.example",
                "api_key": "sk-bad",
                "model": "claude-compatible",
            },
        )
        tested = client.post("/api/agents/audit_agent/model/test")
        assert tested.status_code == 200
        assert tested.json() == {"success": False, "model": None, "error": "Invalid API key"}
        manifest = client.get("/api/agentteams/manifest").json()
        assert manifest["model_configs"]["audit_agent"]["connection_status"] == "失败"
        assert manifest["model_configs"]["audit_agent"]["last_error"] == "Invalid API key"


def test_unknown_task_returns_404(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/tasks/not-found")
    assert response.status_code == 404
