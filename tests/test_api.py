from __future__ import annotations

import re

from fastapi.testclient import TestClient

from energymesh.api import create_app


def test_health_and_demo_workflow(settings) -> None:
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["simulation_mode"] is True
        assert health.json()["allow_production_write"] is False

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
