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


def test_unknown_task_returns_404(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/tasks/not-found")
    assert response.status_code == 404
