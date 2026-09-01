from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from energymesh.api import create_app
from energymesh.model_gateway import normalize_base_url


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


def test_runtime_pipeline_persists_artifacts_and_tool_calls(settings, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append((config.agent_id, message))
        return f"{config.agent_id} acknowledged"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    monkeypatch.setattr("energymesh.runtime.chat_with_agent_config", fake_chat)
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

        response = client.post(
            "/api/runtime/chat",
            json={"message": "生产一区明天增加800kW负荷，你帮我判断是否需要调整能源策略。"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["routed_agents"] == [
            "team_leader",
            "perception_agent",
            "dispatch_agent",
            "audit_agent",
            "team_leader",
        ]
        task_brief = next(item for item in body["artifacts"] if item["name"] == "task_brief.json")
        assert task_brief["payload"]["routing_plan"]["mode"] == "dispatch_closed_loop"
        assert task_brief["payload"]["routing_plan"]["workers"] == [
            "perception_agent",
            "dispatch_agent",
            "audit_agent",
        ]
        artifact_names = [artifact["name"] for artifact in body["artifacts"]]
        assert artifact_names == [
            "task_brief.json",
            "state.json",
            "plan.json",
            "verification.json",
            "final_report.md",
        ]
        state_artifact = next(item for item in body["artifacts"] if item["name"] == "state.json")
        assert state_artifact["payload"]["energy_state"]["current_load_mw"] == 6.8
        assert state_artifact["payload"]["energy_state"]["storage_soc_percent"] == 61

        task_id = body["task_id"]
        tool_calls = client.get(f"/api/runtime/tasks/{task_id}/tool-calls").json()
        assert [call["tool_type"] for call in tool_calls] == ["mcp", "rag", "rag"]
        assert tool_calls[0]["tool_name"] == "energy.get_state"
        assert tool_calls[0]["output_payload"]["current_load_mw"] == 6.8
        assert tool_calls[1]["tool_name"] == "knowledge.search"

        artifacts = client.get(f"/api/runtime/tasks/{task_id}/artifacts").json()
        assert [artifact["name"] for artifact in artifacts] == artifact_names
        assert [agent_id for agent_id, _ in calls] == [
            "team_leader",
            "perception_agent",
            "dispatch_agent",
            "audit_agent",
            "team_leader",
        ]


def test_runtime_stream_emits_progressive_agent_events(settings, monkeypatch) -> None:
    def fake_chat(config, message: str, history=None) -> str:
        return f"{config.agent_id} streamed"

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", fake_chat)
    monkeypatch.setattr("energymesh.runtime.chat_with_agent_config", fake_chat)
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
            json={"message": "明天新增800kW负荷，帮我走完整调度链路。"},
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
        "route_decided",
        "stage_start",
        "agent_step",
        "stage_start",
        "agent_step",
        "stage_start",
        "agent_step",
        "stage_start",
        "agent_step",
        "runtime_completed",
    ]
    assert '"agent_id": "perception_agent"' in body
    assert '"agent_id": "audit_agent"' in body


def test_runtime_leader_only_route_does_not_broadcast_to_workers(settings, monkeypatch) -> None:
    calls: list[str] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append(config.agent_id)
        return f"{config.agent_id} direct"

    monkeypatch.setattr("energymesh.runtime.chat_with_agent_config", fake_chat)
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
    assert body["routed_agents"] == ["team_leader", "team_leader"]
    assert calls == []
    assert [artifact["name"] for artifact in body["artifacts"]] == [
        "task_brief.json",
        "leader_response.md",
    ]
    assert body["artifacts"][0]["payload"]["routing_plan"]["mode"] == "leader_only"


def test_runtime_model_connection_failure_falls_back_to_local_response(
    settings, monkeypatch
) -> None:
    def failing_chat(config, message: str, history=None) -> str:
        raise RuntimeError("Connection error.")

    monkeypatch.setattr("energymesh.api.chat_with_agent_config", lambda config, message: "OK")
    monkeypatch.setattr("energymesh.runtime.chat_with_agent_config", failing_chat)
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
            json={"message": "生产一区明天增加800kW负荷，帮我判断是否需要调整能源策略。"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["routed_agents"] == [
        "team_leader",
        "perception_agent",
        "dispatch_agent",
        "audit_agent",
        "team_leader",
    ]
    assert "Team Leader 汇总" in body["steps"][-1]["response"]
    assert "模型网关暂不可用" not in body["steps"][-1]["response"]
    assert body["artifacts"][-1]["name"] == "final_report.md"


def test_runtime_untested_model_config_uses_local_response(settings, monkeypatch) -> None:
    calls: list[str] = []

    def fake_chat(config, message: str, history=None) -> str:
        calls.append(config.agent_id)
        return "should not be called"

    monkeypatch.setattr("energymesh.runtime.chat_with_agent_config", fake_chat)
    with TestClient(create_app(settings)) as client:
        client.put(
            "/api/agents/team_leader/model",
            json={
                "base_url": "https://api.deepseek.com",
                "api_key": "sk-untested-runtime",
                "model": "deepseek-chat",
            },
        )

        response = client.post("/api/runtime/chat", json={"message": "你好，介绍一下你自己。"})

    assert response.status_code == 200
    assert calls == []
    assert "EnergyMesh Team Leader" in response.json()["steps"][-1]["response"]
    assert "model gateway status" not in response.json()["steps"][-1]["response"]


def test_unknown_task_returns_404(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/tasks/not-found")
    assert response.status_code == 404
