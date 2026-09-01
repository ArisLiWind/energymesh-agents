from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from energymesh.agentteams_runtime import (
    LiveAgentTeamsRuntime,
    probe_agentteams_runtime,
    requires_agentteams_workers,
)
from energymesh.api import create_app
from energymesh.model_gateway import normalize_base_url
from energymesh.storage import EvidenceStore


def test_agentteams_resource_assets_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    resources = root / "agentteams" / "agentteams-resources.yaml"
    text = resources.read_text(encoding="utf-8")
    assert "apiVersion: agentteams.io/v1beta1" in text
    assert "kind: Team" in text
    assert text.count("kind: Worker") == 5
    assert "workerMembers:" in text
    assert text.count("role: team_leader") == 1
    assert "leader:" not in text
    assert "workers:" not in text
    assert "runtime: openclaw" in text
    assert "runtime: copaw" in text
    assert (root / "agentteams" / "team-leader" / "AGENTS.md").exists()
    packaged_skills = [
        root / "agentteams" / "team-leader" / "skills" / "microgrid_context_ingest" / "SKILL.md",
        root
        / "agentteams"
        / "workers"
        / "perception"
        / "skills"
        / "microgrid_context_ingest"
        / "SKILL.md",
        root
        / "agentteams"
        / "workers"
        / "dispatch"
        / "skills"
        / "dispatch_plan_generate"
        / "SKILL.md",
        root / "agentteams" / "workers" / "audit" / "skills" / "dispatch_audit_verify" / "SKILL.md",
        root / "agentteams" / "workers" / "execution" / "skills" / "execution_mapping" / "SKILL.md",
    ]
    assert all(skill.exists() for skill in packaged_skills)


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
        assert (
            manifest_body["framework_repository"] == "https://github.com/agentscope-ai/AgentTeams"
        )
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
        assert 'id="ai-chat-form"' in page.text
        assert 'data-day-group="today"' in page.text
        assert 'data-ledger-summary="today"' in page.text
        assert 'data-open-workspace="weather"' in page.text
        assert 'data-open-workspace="context"' not in page.text
        assert 'id="nav-ops"' in page.text
        assert "运行14:00复合变化" not in page.text
        assert 'id="trace-list"' in page.text
        script = client.get("/static/app.js")
        assert "production_load" in script.text
        assert "scenarioConversation" in script.text

        evidence_board = client.get("/api/ops/evidence-board")
        assert evidence_board.status_code == 200
        evidence_body = evidence_board.json()
        assert evidence_body["data_snapshot"]["contract"] == "ExternalDataSnapshot"
        assert evidence_body["closed_loop"]["hitl_gate"]
        assert evidence_body["agentteams"]["team_name"] == "energymesh-test-team"
        assert evidence_body["rag_memory"]["enabled"] is True

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
            event["action"] == "independent_policy_audit" for event in external_body["trace"]
        )

        created = client.post("/api/demo/run")
        assert created.status_code == 201
        created_body = created.json()
        assert created_body["task_id"] == "TASK-20260731-014"
        assert created_body["task_version"] == 2
        assert created_body["state"] == "AWAITING_APPROVAL"
        context = client.get(f"/api/tasks/{created_body['task_id']}/context").json()
        assert context["previous_plan_status"] == "invalidated"
        candidates = client.get(f"/api/tasks/{created_body['task_id']}/candidates").json()
        assert len(candidates) == 3
        audit = client.get(f"/api/tasks/{created_body['task_id']}/audit").json()
        assert audit[0]["verdict"] == "rejected"
        assert audit[0]["transformer_load_percent"] == 103.8

        approval = client.post(
            f"/api/tasks/{created_body['task_id']}/approve",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "approver": "api-test",
                "reason": "integration test approval",
            },
        )
        assert approval.status_code == 200
        completed = client.post(
            f"/api/tasks/{created_body['task_id']}/execute",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "idempotency_key": "IDEMP-API-TEST-B",
            },
        )
        assert completed.status_code == 200
        final_task = client.get(f"/api/tasks/{created_body['task_id']}").json()
        assert final_task["state"] == "COMPLETED"
        assert final_task["execution_summary"]["real_devices_contacted"] == 0

        changed = client.post(
            f"/api/tasks/{created_body['task_id']}/reoptimize",
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
        assert changed_task["parent_task_id"] == created_body["task_id"]
        assert changed_task["trigger"] == "LOAD_FORECAST_CHANGED"
        assert changed_task["state"] == "AWAITING_APPROVAL"


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


def test_team_leader_model_config_and_base_url_normalization(settings, monkeypatch) -> None:
    calls: list[tuple[str, str, str, str]] = []

    def fake_chat(config, message: str) -> str:
        calls.append((config.agent_id, config.base_url, config.model, message))
        return "OK"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        saved = client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.openai.com/v1/chat/completions",
                "api_key": "sk-team-secret",
                "model": "gpt-4o-mini",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["base_url"] == "https://api.openai.com/v1"

        tested = client.post("/api/agents/team_leader/model/test")
        assert tested.status_code == 200
        assert tested.json()["success"] is True

        chatted = client.post(
            "/api/agents/team_leader/chat",
            json={"message": "你好"},
        )
        assert chatted.status_code == 200
        assert calls == [
            ("team_leader", "https://api.openai.com/v1", "gpt-4o-mini", "Reply with OK."),
            ("team_leader", "https://api.openai.com/v1", "gpt-4o-mini", "你好"),
        ]


def test_normalize_model_base_url() -> None:
    assert normalize_base_url("https://api.openai.com") == "https://api.openai.com/v1"
    assert (
        normalize_base_url("https://api.deepseek.com/v1/chat/completions")
        == "https://api.deepseek.com/v1"
    )


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


def test_runtime_normal_chat_persists_direct_leader_artifact(settings, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append((config.agent_id, message))
        return "你好，我是 EnergyMesh Team Leader。普通对话我会直接回答。"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    monkeypatch.setattr("energymesh.direct_runtime.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-shared-runtime",
                "model": "deepseek-chat",
            },
        )
        client.post("/api/agents/team_leader/model/test")
        calls.clear()

        response = client.post("/api/runtime/chat", json={"message": "你好，介绍一下你自己。"})

        assert response.status_code == 200
        body = response.json()
        assert body["routed_agents"] == ["team_leader"]
        assert [artifact["name"] for artifact in body["artifacts"]] == ["leader_response.md"]
        assert body["artifacts"][0]["payload"]["routing_plan"]["workers"] == []
        task_id = body["task_id"]
        tool_calls = client.get(f"/api/runtime/tasks/{task_id}/tool-calls").json()
        assert tool_calls == []
        assert [agent_id for agent_id, _ in calls] == ["team_leader"]


def test_runtime_stream_normal_chat_emits_single_leader_event(settings, monkeypatch) -> None:
    def fake_chat(config, message: str, history=None) -> str:
        return "team_leader streamed"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    monkeypatch.setattr("energymesh.direct_runtime.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-shared-runtime",
                "model": "deepseek-chat",
            },
        )
        client.post("/api/agents/team_leader/model/test")

        with client.stream(
            "POST",
            "/api/runtime/chat/stream",
            json={"message": "你好，介绍一下你自己。"},
        ) as response:
            assert response.status_code == 200
            body = response.read().decode()

    events = [
        line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")
    ]
    assert events == [
        "runtime_started",
        "stage_start",
        "agent_step",
        "runtime_completed",
    ]
    assert '"agent_id": "team_leader"' in body
    assert '"agent_id": "perception_agent"' not in body


def test_runtime_leader_only_route_does_not_broadcast_to_workers(settings, monkeypatch) -> None:
    calls: list[str] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append(config.agent_id)
        return f"{config.agent_id} direct"

    monkeypatch.setattr("energymesh.direct_runtime.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-shared-runtime",
                "model": "deepseek-chat",
            },
        )

        response = client.post("/api/runtime/chat", json={"message": "你好，介绍一下你自己。"})

    assert response.status_code == 200
    body = response.json()
    assert body["routed_agents"] == ["team_leader"]
    assert calls == ["team_leader"]
    assert [artifact["name"] for artifact in body["artifacts"]] == ["leader_response.md"]
    assert body["artifacts"][0]["payload"]["routing_plan"]["mode"] == "leader_only"


def test_live_required_normal_chat_uses_direct_leader_only_route(settings, monkeypatch) -> None:
    live_settings = replace(settings, agentteams_live_required=True)
    calls: list[tuple[str, str]] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append((config.agent_id, message))
        if message == "Reply with OK.":
            return "OK"
        return "你好，我会先正常回答；只有你明确要调度、预览或执行时才进入 Worker。"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    monkeypatch.setattr("energymesh.direct_runtime.chat_with_agent_config", fake_chat)
    with TestClient(create_app(live_settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-shared-runtime",
                "model": "deepseek-chat",
            },
        )
        client.post("/api/agents/team_leader/model/test")
        calls.clear()

        response = client.post("/api/runtime/chat", json={"message": "你好，介绍一下你自己。"})

    assert response.status_code == 200
    body = response.json()
    assert body["routed_agents"] == ["team_leader"]
    assert body["artifacts"][0]["name"] == "leader_response.md"
    assert body["artifacts"][0]["payload"]["routing_plan"]["mode"] == "leader_only"
    assert [agent_id for agent_id, _ in calls] == ["team_leader"]


def test_live_required_dispatch_request_requires_real_agentteams(settings) -> None:
    live_settings = replace(settings, agentteams_live_required=True)
    with TestClient(create_app(live_settings)) as client:
        response = client.post(
            "/api/runtime/chat",
            json={"message": "帮我优化调度，减少购电和能源浪费。"},
        )
    assert response.status_code == 409
    assert "Live AgentTeams is not ready" in response.json()["detail"]


def test_agentteams_worker_intent_classifier_is_explicit() -> None:
    assert requires_agentteams_workers("帮我优化调度，先预览新流向") is True
    assert requires_agentteams_workers("采用这个方案并执行") is True
    assert requires_agentteams_workers("你好，介绍一下你自己") is False
    assert requires_agentteams_workers("现在园区电力状态正常吗？") is False


def test_live_agentteams_matrix_payload_contains_world_state(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("AGENTTEAMS_MATRIX_BASE_URL", "http://matrix.local")
    monkeypatch.setenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN", "token-secret")
    monkeypatch.setenv("AGENTTEAMS_TEAM_ROOM_ID", "!room:agentteams")
    monkeypatch.setenv("AGENTTEAMS_EVENT_STREAM_URL", "http://events.local/sse")
    monkeypatch.setattr("energymesh.agentteams_runtime.urlrequest.urlopen", fake_urlopen)
    runtime = LiveAgentTeamsRuntime(
        EvidenceStore(tmp_path / "energymesh.db", tmp_path / "evidence"),
        "energymesh-test-team",
        lambda: {
            "snapshot_contract": "ExternalDataSnapshot",
            "current_load_mw": 6.8,
            "grid_import_mw": 3.1,
            "optimization_objectives": ["降低购电成本", "降低能源浪费/限发", "降低人工调度成本"],
        },
    )

    world_state = runtime._world_state()
    runtime._send_matrix_message("session-1", "task-1", "请优化调度", world_state)

    payload = captured["payload"]
    assert payload["energymesh"]["world_state"]["current_load_mw"] == 6.8
    assert payload["energymesh"]["required_workers"] == [
        "perception_worker",
        "dispatch_worker",
        "audit_worker",
        "execution_worker",
    ]
    assert "EnergyMesh world_state" in payload["body"]


def test_remote_matrix_agentteams_runtime_ready(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setenv("AGENTTEAMS_RUNTIME_MODE", "remote_matrix")
    monkeypatch.setenv("AGENTTEAMS_MATRIX_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("AGENTTEAMS_MATRIX_ACCESS_TOKEN", "token-secret")
    monkeypatch.setenv("AGENTTEAMS_TEAM_ROOM_ID", "!team:agentteams")
    monkeypatch.setenv("AGENTTEAMS_TEAM_NAME", "energymesh-demo")
    monkeypatch.setenv("AGENTTEAMS_REMOTE_WORKERS", "energy-dispatcher")
    monkeypatch.setattr(
        "energymesh.agentteams_runtime.urlrequest.urlopen",
        lambda req, timeout=0: FakeResponse(),
    )

    status = probe_agentteams_runtime()

    assert status.ready is True
    assert status.mode == "remote_matrix_agentteams"
    assert status.teams == ["energymesh-demo"]
    assert status.workers == ["energy-dispatcher"]


def test_dispatch_request_never_falls_back_to_local_pipeline(settings, monkeypatch) -> None:
    def failing_chat(config, message: str, history=None) -> str:
        raise RuntimeError("Connection error.")

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", lambda config, message: "OK")
    monkeypatch.setattr("energymesh.direct_runtime.chat_with_agent_config", failing_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-shared-runtime",
                "model": "deepseek-chat",
            },
        )
        client.post("/api/agents/team_leader/model/test")

        response = client.post(
            "/api/runtime/chat",
            json={"message": "生产一区明天增加800kW负荷，帮我优化调度并预览方案。"},
        )

    assert response.status_code == 409
    assert "Live AgentTeams is not ready" in response.json()["detail"]


def test_normal_chat_requires_real_model_gateway(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/runtime/chat", json={"message": "你好，介绍一下你自己。"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Team Leader model gateway is not configured."


def test_unknown_task_returns_404(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/tasks/not-found")
    assert response.status_code == 404
