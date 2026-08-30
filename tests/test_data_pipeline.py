from pathlib import Path

from fastapi.testclient import TestClient

from energymesh.api import create_app
from energymesh.data_pipeline import ReplayMonitor, SnapshotFactory
from energymesh.orchestrator import EnergyMeshOrchestrator


def test_opencem_csv_normalizes_to_shared_snapshot() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "opencem" / "2025-07-a.csv"
    snapshot = SnapshotFactory().from_opencem_csv(path.read_bytes(), path.name)

    assert snapshot.source == "opencem_csv_upload"
    assert snapshot.scenario.site.site_id == "cuhk-sz-opencem-campus"
    assert len(snapshot.telemetry) == 96
    assert len(snapshot.scenario.forecast) == 96
    assert snapshot.environment_signals["raw_rows"] == 717
    assert max(point.pv_kw for point in snapshot.telemetry) > 1
    assert snapshot.scenario.production_plan["source"] == "opencem_context_adapter"


def test_monitor_wakes_agents_then_separates_approval_and_execution(settings) -> None:
    with TestClient(create_app(settings)) as client:
        sample = client.get("/api/data/opencem/sample.csv")
        assert sample.status_code == 200
        assert "read_ts" in sample.text

        page = client.get("/")
        assert 'class="data-monitor-panel"' not in page.text
        assert 'id="nav-connect"' in page.text
        assert page.text.count('id="upload-energy-data"') == 1
        assert page.text.count('id="connect-energy-source"') == 1

        blocked = client.post("/api/monitor/start?start_interval=20")
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "no live or uploaded energy data is connected"

        root = Path(__file__).resolve().parents[1]
        path = root / "data" / "opencem" / "2025-07-a.csv"
        uploaded = client.post(
            "/api/data/upload?filename=2025-07-a.csv",
            content=path.read_bytes(),
            headers={"Content-Type": "text/csv"},
        )
        assert uploaded.status_code == 200

        started = client.post("/api/monitor/start?start_interval=20")
        assert started.status_code == 200
        assert started.json()["agentteams_awake"] is False

        status = started.json()
        for _ in range(12):
            status = client.post("/api/monitor/step").json()
            if status["task_id"]:
                break

        assert status["plan_version"] == "V2"
        assert status["agentteams_awake"] is True
        assert any(event["kind"] == "V1_INVALIDATED" for event in status["events"])
        assert any(event["kind"] == "AGENTTEAMS_WOKEN" for event in status["events"])
        task_id = status["task_id"]
        task = client.get(f"/api/tasks/{task_id}").json()
        assert task["trigger"] == "OPENCEM_MONITOR_PLAN_INVALIDATION"
        assert task["state"] == "AWAITING_APPROVAL"
        assert task["execution_summary"] is None

        approved = client.post(
            f"/api/tasks/{task_id}/approval-only",
            json={"approved": True, "approver": "test-operator", "reason": "audit reviewed"},
        )
        assert approved.status_code == 200
        assert approved.json()["approval"]["approved"] is True
        assert approved.json()["execution_summary"] is None

        executed = client.post(f"/api/tasks/{task_id}/execute-approved")
        assert executed.status_code == 200
        assert executed.json()["state"] == "COMPLETED"
        assert executed.json()["execution_summary"]["real_devices_contacted"] == 0
        assert executed.json()["evidence_sha256"]


def test_monitor_can_record_deepseek_rolling_decision(settings) -> None:
    with TestClient(create_app(settings)) as client:
        root = Path(__file__).resolve().parents[1]
        path = root / "data" / "opencem" / "2025-07-a.csv"
        snapshot = SnapshotFactory().from_opencem_csv(path.read_bytes(), path.name)
        orchestrator: EnergyMeshOrchestrator = client.app.state.orchestrator
        monitor = ReplayMonitor(
            orchestrator, lambda payload: f"滚动决策点数 {len(payload['today_so_far'])}"
        )
        monitor.start(snapshot, 20)
        status = {}
        for _ in range(6):
            status = monitor.step()
        assert any(event["kind"] == "DEEPSEEK_DECISION" for event in status["events"])
