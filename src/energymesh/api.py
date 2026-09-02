import json
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from energymesh.agentteams import AgentTeamsManifest, build_agentteams_manifest
from energymesh.agentteams_runtime import (
    LiveAgentTeamsRuntime,
    LiveAgentTeamsRuntimeError,
    probe_agentteams_runtime,
    requires_agentteams_workers,
)
from energymesh.audit import IndependentSafetyAuditor
from energymesh.compound_demo import CompoundChangeDemo, DemoWorkflowError
from energymesh.config import Settings
from energymesh.data_pipeline import EnergyDataError, ReplayMonitor, SnapshotFactory
from energymesh.demo import apply_operational_change, load_demo_scenario
from energymesh.direct_runtime import DirectLeaderRuntime, DirectLeaderRuntimeError
from energymesh.external_data import ExternalDataSimulator
from energymesh.model_gateway import chat_with_agent_config, normalize_agent_id
from energymesh.mcp_server import handle_mcp_message, tools_for_profile
from energymesh.models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentMessage,
    AgentModelConfigPublic,
    AgentModelConfigRequest,
    AgentModelTestResponse,
    AgentRuntimeChatRequest,
    AgentRuntimeChatResponse,
    ApprovalDecisionRequest,
    ApprovalRequest,
    DemoRunResponse,
    ExecuteRequest,
    ExecutionReceipt,
    ExternalDataSnapshot,
    ExternalDispatchRequest,
    ParallelSimulationState,
    ParallelStepResponse,
    ReoptimizationRequest,
    RollingHorizonRequest,
    RuntimeArtifact,
    RuntimeToolCall,
    Scenario,
    TaskRecord,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.orchestrator import WorkflowError
from energymesh.orchestrator_v2 import EnergyMeshOrchestratorV2 as EnergyMeshOrchestrator
from energymesh.parallel_sim import ParallelSimError, ParallelSimulator
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore, PayloadRow, PayloadRows


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_settings.assert_safe_runtime()
    store = EvidenceStore(active_settings.db_path, active_settings.evidence_dir)
    compound_demo = CompoundChangeDemo(store)
    from energymesh.agent_registry import SkillRegistry
    from energymesh.polardb_store import PolarDBStore
    from energymesh.rag_engine import RAGEngine
    from energymesh.worker_pool import WorkerPool

    skill_registry = SkillRegistry()
    worker_pool = WorkerPool(skill_registry)
    polar_store = PolarDBStore(
        str(active_settings.db_path.parent / "polardb_telemetry.db"),
        dsn=active_settings.polardb_dsn,
    )
    rag_engine = RAGEngine(str(active_settings.db_path.parent / "rag_experience.db"))
    orchestrator = EnergyMeshOrchestrator(
        perception=PerceptionAgent(),
        optimizer=DispatchOptimizer(),
        auditor=IndependentSafetyAuditor(),
        executor=SimulationExecutor(active_settings),
        store=store,
        skill_registry=skill_registry,
        worker_pool=worker_pool,
        polar_store=polar_store,
        rag_engine=rag_engine,
    )
    scenario = load_demo_scenario()
    external_data = ExternalDataSimulator()
    snapshot_factory = SnapshotFactory()

    def rolling_decision(payload: dict[str, object]) -> str | None:
        config = store.get_model_config("team_leader")
        if config is None or not config.api_key:
            return None
        today_so_far = cast(list[object], payload["today_so_far"])
        compact = {
            "current": payload["current"],
            "signals": payload["signals"],
            "today_points": len(today_so_far),
            "today_so_far_tail": today_so_far[-8:],
        }
        return chat_with_agent_config(
            config,
            "基于今天截至当前的园区真实数据滚动判断：V1 是否失效、是否唤醒 AgentTeams、"
            "是否进入 V2 重规划。只输出一句面向操作员的决策摘要。\n"
            f"{json.dumps(compact, ensure_ascii=False)}",
        )

    monitor = ReplayMonitor(orchestrator, rolling_decision)

    def replay_status_for(snapshot: ExternalDataSnapshot | None) -> dict[str, object]:
        if snapshot is None or not snapshot.telemetry:
            return {
                "running": False,
                "paused": True,
                "current_interval": 0,
                "speed_multiplier": 1.0,
                "seconds_per_interval": None,
                "total_intervals": 0,
            }
        total = len(snapshot.telemetry)
        speed = max(0.0, float(getattr(app.state, "replay_speed_multiplier", 1.0)))
        anchor = min(
            max(int(getattr(app.state, "replay_anchor_interval", snapshot.current_interval)), 0),
            total - 1,
        )
        started_at = float(getattr(app.state, "replay_started_at", time.time()))
        paused = bool(getattr(app.state, "replay_paused", False))
        interval_seconds = 15 * 60
        replay_seconds = total * interval_seconds
        seconds_per_interval = interval_seconds / speed if speed > 0 else None
        cursor = anchor
        if paused or speed <= 0:
            simulated_time = snapshot.telemetry[cursor].timestamp
        else:
            elapsed = max(0.0, time.time() - started_at)
            # The CSV rows are quarter-hourly, but the visible replay clock is continuous.
            # speed=1 means one real second advances one simulated second.
            simulated_seconds = (anchor * interval_seconds + elapsed * speed) % replay_seconds
            cursor = int(simulated_seconds // interval_seconds) % total
            day_start = snapshot.telemetry[0].timestamp
            simulated_time = day_start + timedelta(seconds=simulated_seconds)
        snapshot.current_interval = cursor
        point = snapshot.telemetry[cursor]
        snapshot.current = point
        snapshot.environment_signals.update(
            {
                "load_kw": point.load_kw,
                "pv_kw": point.pv_kw,
                "battery_soc": point.battery_soc,
                "grid_import_kw": max(0.0, point.load_kw - point.pv_kw),
                "current_interval": cursor,
                "current_timestamp": point.timestamp.isoformat(),
                "simulated_time": simulated_time.isoformat(),
            }
        )
        return {
            "running": not paused,
            "paused": paused,
            "current_interval": cursor,
            "speed_multiplier": speed,
            "seconds_per_interval": seconds_per_interval,
            "total_intervals": total,
            "timestamp": point.timestamp.isoformat(),
            "simulated_time": simulated_time.isoformat(),
            "source": snapshot.source,
        }

    def current_world_state() -> dict[str, object] | None:
        snapshot: ExternalDataSnapshot | None = app.state.uploaded_snapshot
        replay = replay_status_for(snapshot)
        status = monitor.status()
        current = status.get("current")
        cursor = (
            status.get("cursor")
            if status.get("current")
            else snapshot.current_interval
            if snapshot
            else 0
        )
        if current is None and snapshot and snapshot.telemetry:
            index = min(max(snapshot.current_interval, 0), len(snapshot.telemetry) - 1)
            current = snapshot.telemetry[index].model_dump(mode="json")
        if not isinstance(current, dict):
            return None
        load_kw = float(current.get("load_kw") or 0)
        pv_kw = float(current.get("pv_kw") or 0)
        battery_soc = float(current.get("battery_soc") or 0)
        grid_import_kw = max(0.0, load_kw - pv_kw)
        telemetry_window = []
        if snapshot and snapshot.telemetry:
            start = min(max(int(cursor or 0), 0), len(snapshot.telemetry) - 1)
            end = min(start + 4, len(snapshot.telemetry))
            telemetry_window = [
                {
                    "interval": point.interval,
                    "timestamp": point.timestamp.isoformat(),
                    "load_kw": round(point.load_kw, 3),
                    "pv_kw": round(point.pv_kw, 3),
                    "battery_soc": round(point.battery_soc, 4),
                    "tariff_yuan_per_kwh": point.tariff_yuan_per_kwh,
                    "production_min_load_kw": round(point.production_min_load_kw, 3),
                    "transformer_limit_kw": round(point.transformer_limit_kw, 3),
                }
                for point in snapshot.telemetry[start:end]
            ]
        today_load_kwh = 0.0
        today_pv_kwh = 0.0
        today_grid_kwh = 0.0
        today_cost_yuan = 0.0
        if snapshot and snapshot.telemetry:
            stop = min(max(int(cursor or 0), 0) + 1, len(snapshot.telemetry))
            for point in snapshot.telemetry[:stop]:
                today_load_kwh += point.load_kw * 0.25
                today_pv_kwh += point.pv_kw * 0.25
                grid_kw = max(0.0, point.load_kw - point.pv_kw)
                today_grid_kwh += grid_kw * 0.25
                today_cost_yuan += grid_kw * 0.25 * point.tariff_yuan_per_kwh
        pv_curtailment_kw = max(0.0, pv_kw - load_kw)
        return {
            "current": current,
            "source": status.get("source")
            or (snapshot.source if snapshot else "uploaded_snapshot"),
            "cursor": cursor,
            "snapshot_contract": "ExternalDataSnapshot",
            "telemetry_points": len(snapshot.telemetry) if snapshot else 0,
            "telemetry_window_next_hour": telemetry_window,
            "current_load_mw": round(load_kw / 1000, 4),
            "pv_forecast_mw": round(pv_kw / 1000, 4),
            "storage_soc_percent": round(battery_soc * 100, 1),
            "grid_import_mw": round(grid_import_kw / 1000, 4),
            "pv_curtailment_kw": round(pv_curtailment_kw, 3),
            "transformer_load_percent": round(min(100.0, grid_import_kw / 10), 1),
            "available_capacity_mw": round(max(0.0, 10000 - grid_import_kw) / 1000, 4),
            "daily_so_far": {
                "load_kwh": round(today_load_kwh, 3),
                "pv_kwh": round(today_pv_kwh, 3),
                "grid_import_kwh": round(today_grid_kwh, 3),
                "purchase_cost_yuan": round(today_cost_yuan, 4),
            },
            "optimization_objectives": [
                "降低购电成本",
                "降低能源浪费/限发",
                "降低人工调度成本",
            ],
            "device_status": {
                "ems": "online",
                "pcs": "from_uploaded_snapshot",
                "bms": "from_uploaded_snapshot",
                "mes": "simulation",
            },
            "replay_clock": replay,
        }

    direct_runtime = DirectLeaderRuntime(store)

    app = FastAPI(
        title="EnergyMesh Agents API",
        version="0.1.0",
        description="Audited 15-minute economic dispatch in simulation mode.",
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.compound_demo = compound_demo
    app.state.direct_runtime = direct_runtime
    app.state.orchestrator = orchestrator
    app.state.scenario = scenario
    app.state.external_data = external_data
    app.state.snapshot_factory = snapshot_factory
    app.state.monitor = monitor
    app.state.polar_store = polar_store
    app.state.uploaded_snapshot = None
    app.state.replay_started_at = time.time()
    app.state.replay_anchor_interval = 0
    app.state.replay_speed_multiplier = 1.0
    app.state.replay_paused = False
    app.state.parallel_sim = ParallelSimulator(orchestrator, store)
    app.state.live_agentteams_runtime = LiveAgentTeamsRuntime(
        store, active_settings.agentteams_team_name, current_world_state
    )

    def get_orchestrator(request: Request) -> EnergyMeshOrchestrator:
        return cast(EnergyMeshOrchestrator, request.app.state.orchestrator)

    def get_store(request: Request) -> EvidenceStore:
        return cast(EvidenceStore, request.app.state.store)

    def get_direct_runtime(request: Request) -> DirectLeaderRuntime:
        return cast(DirectLeaderRuntime, request.app.state.direct_runtime)

    def get_live_agentteams_runtime(request: Request) -> LiveAgentTeamsRuntime:
        return cast(LiveAgentTeamsRuntime, request.app.state.live_agentteams_runtime)

    def get_compound_demo(request: Request) -> CompoundChangeDemo:
        return cast(CompoundChangeDemo, request.app.state.compound_demo)

    def get_parallel_sim(request: Request) -> ParallelSimulator:
        return cast(ParallelSimulator, request.app.state.parallel_sim)

    def get_scenario(request: Request) -> Scenario:
        return cast(Scenario, request.app.state.scenario)

    def get_external_data(request: Request) -> ExternalDataSimulator:
        return cast(ExternalDataSimulator, request.app.state.external_data)

    @app.get("/api/health")
    def health(request: Request) -> dict[str, object]:
        runtime: Settings = request.app.state.settings
        agentteams_runtime = probe_agentteams_runtime().model_dump()
        return {
            "status": "ok",
            "version": app.version,
            "simulation_mode": runtime.simulation_mode,
            "allow_production_write": runtime.allow_production_write,
            "agent_framework": "agentscope-ai/AgentTeams",
            "agentteams_enabled": runtime.agentteams_enabled,
            "agentteams_live_required": runtime.agentteams_live_required,
            "agentteams_team_name": runtime.agentteams_team_name,
            "agentteams_runtime": agentteams_runtime,
            "polardb": cast(PolarDBStore, request.app.state.polar_store).health(),
        }

    @app.get("/mcp/{profile}/tools")
    def mcp_tools(profile: str) -> dict[str, object]:
        return {
            "server": f"energymesh-{profile}",
            "profile": profile,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for tool in tools_for_profile(profile)
            ],
        }

    @app.post("/mcp/{profile}")
    def mcp_jsonrpc(profile: str, body: dict[str, object]) -> dict[str, object]:
        response = handle_mcp_message(body, profile)
        if response is None:
            return {"jsonrpc": "2.0", "result": {}}
        return response

    @app.get("/api/agentteams/manifest", response_model=AgentTeamsManifest)
    def agentteams_manifest(request: Request) -> AgentTeamsManifest:
        runtime: Settings = request.app.state.settings
        store: EvidenceStore = request.app.state.store
        return build_agentteams_manifest(runtime, store.list_public_model_configs())

    @app.get("/api/agentteams/runtime")
    def agentteams_runtime_status() -> dict[str, object]:
        return probe_agentteams_runtime().model_dump()

    @app.put("/api/agents/{agent_id}/model", response_model=AgentModelConfigPublic)
    def save_agent_model(
        agent_id: str,
        body: AgentModelConfigRequest,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> AgentModelConfigPublic:
        try:
            normalized = normalize_agent_id(agent_id)
            return evidence_store.save_model_config(
                normalized, body.base_url, body.api_key, body.model
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/agents/{agent_id}/model/test", response_model=AgentModelTestResponse)
    def test_agent_model(
        agent_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> AgentModelTestResponse:
        try:
            normalized = normalize_agent_id(agent_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        config = evidence_store.get_model_config(normalized)
        if config is None:
            return AgentModelTestResponse(success=False, error="Model config not saved")
        try:
            chat_with_agent_config(config, "Reply with OK.")
        except Exception as error:
            message = str(error)
            evidence_store.update_model_status(normalized, "失败", message)
            return AgentModelTestResponse(success=False, error=message)
        evidence_store.update_model_status(normalized, "正常", None)
        return AgentModelTestResponse(success=True, model=config.model)

    @app.post("/api/agents/{agent_id}/chat", response_model=AgentChatResponse)
    def chat_with_agent(
        agent_id: str,
        body: AgentChatRequest,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> AgentChatResponse:
        try:
            normalized = normalize_agent_id(agent_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        config = evidence_store.get_model_config(normalized)
        if config is None:
            raise HTTPException(status_code=409, detail="Model config not saved")
        try:
            history = [
                item
                for item in body.history
                if item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
                and item.get("content", "").strip()
            ][-12:]
            try:
                reply = chat_with_agent_config(config, body.message, history=history)
            except TypeError:
                reply = chat_with_agent_config(config, body.message)
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return AgentChatResponse(agent_id=normalized, model=config.model, response=reply)

    @app.post("/api/runtime/chat", response_model=AgentRuntimeChatResponse)
    def chat_with_runtime(
        body: AgentRuntimeChatRequest,
        request: Request,
        direct_runtime: Annotated[DirectLeaderRuntime, Depends(get_direct_runtime)],
        live_runtime: Annotated[LiveAgentTeamsRuntime, Depends(get_live_agentteams_runtime)],
    ) -> AgentRuntimeChatResponse:
        try:
            settings: Settings = request.app.state.settings
            if not requires_agentteams_workers(body.message):
                return direct_runtime.chat(
                    body.message,
                    body.session_id,
                    body.task_id,
                    current_world_state(),
                )
            if settings.agentteams_enabled and settings.agentteams_live_required:
                return live_runtime.chat(body.message, body.session_id, body.task_id)
            if settings.agentteams_enabled:
                return live_runtime.chat(body.message, body.session_id, body.task_id)
            raise LiveAgentTeamsRuntimeError(
                "AgentTeams is disabled; Worker tasks cannot use a local deterministic fallback."
            )
        except LiveAgentTeamsRuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DirectLeaderRuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/runtime/chat/stream")
    def stream_chat_with_runtime(
        body: AgentRuntimeChatRequest,
        request: Request,
        direct_runtime: Annotated[DirectLeaderRuntime, Depends(get_direct_runtime)],
        live_runtime: Annotated[LiveAgentTeamsRuntime, Depends(get_live_agentteams_runtime)],
    ) -> StreamingResponse:
        def sse_event(event: dict[str, object]) -> Iterator[str]:
            yield f"event: {event['type']}\n"
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        def events() -> Iterator[str]:
            try:
                settings: Settings = request.app.state.settings
                if settings.agentteams_enabled and settings.agentteams_live_required:
                    event_source = live_runtime.stream_chat(
                        body.message, body.session_id, body.task_id
                    )
                elif not requires_agentteams_workers(body.message):
                    event_source = direct_runtime.stream_chat(
                        body.message,
                        body.session_id,
                        body.task_id,
                        current_world_state(),
                    )
                elif settings.agentteams_enabled:
                    event_source = live_runtime.stream_chat(
                        body.message, body.session_id, body.task_id
                    )
                else:
                    raise LiveAgentTeamsRuntimeError(
                        "AgentTeams is disabled; Worker tasks cannot use a local deterministic fallback."
                    )
                for event in event_source:
                    yield from sse_event(event)
            except LiveAgentTeamsRuntimeError as error:
                yield from sse_event({"type": "runtime_error", "detail": str(error)})
            except DirectLeaderRuntimeError as error:
                yield from sse_event({"type": "runtime_error", "detail": str(error)})
            except Exception as error:
                yield from sse_event({"type": "runtime_error", "detail": str(error)})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/runtime/sessions/{session_id}/messages", response_model=list[AgentMessage])
    def list_runtime_messages(
        session_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
        limit: int = 50,
    ) -> list[AgentMessage]:
        return evidence_store.list_agent_messages(session_id, limit=limit)

    @app.get("/api/runtime/tasks/{task_id}/artifacts", response_model=list[RuntimeArtifact])
    def list_runtime_artifacts(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> list[RuntimeArtifact]:
        return evidence_store.list_runtime_artifacts(task_id)

    @app.get("/api/runtime/tasks/{task_id}/tool-calls", response_model=list[RuntimeToolCall])
    def list_runtime_tool_calls(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> list[RuntimeToolCall]:
        return evidence_store.list_runtime_tool_calls(task_id)

    @app.get("/api/demo/scenario", response_model=Scenario)
    def demo_scenario(
        active_scenario: Annotated[Scenario, Depends(get_scenario)],
    ) -> Scenario:
        return active_scenario

    @app.get("/api/external/snapshot", response_model=ExternalDataSnapshot)
    def external_snapshot(
        simulator: Annotated[ExternalDataSimulator, Depends(get_external_data)],
        seed: int = 42,
        current_interval: int = 57,
        fault_mode: str = "cloud_and_transformer_heat",
    ) -> ExternalDataSnapshot:
        return simulator.snapshot(seed, current_interval, fault_mode)

    @app.get("/api/data/sources")
    def data_sources(request: Request) -> dict[str, object]:
        return {
            "snapshot_contract": "ExternalDataSnapshot",
            "simulation_mode": request.app.state.settings.simulation_mode,
            "sources": [
                {
                    "id": "opencem_csv_upload",
                    "label": "OpenCEM history replay",
                    "status": "ready",
                    "write_permission": False,
                },
                {
                    "id": "site_readonly_connector",
                    "label": "Park EMS / BMS / PCS connector",
                    "status": "deployment adapter contract ready",
                    "write_permission": False,
                    "note": "No production endpoint is contacted by this repository.",
                },
            ],
        }

    @app.get("/api/data/opencem/sample.csv")
    def download_opencem_sample() -> FileResponse:
        sample_path = Path(__file__).parents[2] / "data" / "opencem" / "2025-07-a.csv"
        if not sample_path.exists():
            raise HTTPException(status_code=404, detail="OpenCEM sample CSV is not available")
        return FileResponse(
            sample_path,
            media_type="text/csv",
            filename="opencem-cuhk-shenzhen-2025-07-a.csv",
        )

    @app.post("/api/data/upload", response_model=ExternalDataSnapshot)
    async def upload_energy_csv(
        request: Request, filename: str = "upload.csv"
    ) -> ExternalDataSnapshot:
        factory: SnapshotFactory = request.app.state.snapshot_factory
        try:
            snapshot = factory.from_opencem_csv(await request.body(), filename)
        except EnergyDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        request.app.state.uploaded_snapshot = snapshot
        request.app.state.replay_started_at = time.time()
        request.app.state.replay_anchor_interval = snapshot.current_interval
        request.app.state.replay_speed_multiplier = 1.0
        request.app.state.replay_paused = False
        replay_status_for(snapshot)
        return snapshot

    @app.post("/api/data/snapshot/restore", response_model=ExternalDataSnapshot)
    def restore_uploaded_snapshot(
        request: Request, snapshot: ExternalDataSnapshot
    ) -> ExternalDataSnapshot:
        request.app.state.uploaded_snapshot = snapshot
        request.app.state.replay_started_at = time.time()
        request.app.state.replay_anchor_interval = snapshot.current_interval
        request.app.state.replay_speed_multiplier = max(
            0.0, float(getattr(request.app.state, "replay_speed_multiplier", 1.0))
        )
        request.app.state.replay_paused = False
        return snapshot

    @app.get("/api/data/snapshot/current", response_model=ExternalDataSnapshot)
    def current_uploaded_snapshot(request: Request) -> ExternalDataSnapshot:
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        if snapshot is None:
            raise HTTPException(status_code=404, detail="no normalized Snapshot is loaded")
        replay_status_for(snapshot)
        return snapshot

    @app.get("/api/data/replay")
    def get_replay_clock(request: Request) -> dict[str, object]:
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        return replay_status_for(snapshot)

    @app.get("/api/world-state")
    def get_world_state() -> dict[str, object]:
        world_state = current_world_state()
        if world_state is None:
            raise HTTPException(status_code=404, detail="no world_state is loaded")
        return world_state

    @app.put("/api/data/replay")
    async def update_replay_clock(request: Request) -> dict[str, object]:
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        if snapshot is None or not snapshot.telemetry:
            raise HTTPException(status_code=404, detail="no normalized Snapshot is loaded")
        body = await request.json()
        current = replay_status_for(snapshot)["current_interval"]
        if "current_interval" in body:
            current = min(max(int(body["current_interval"]), 0), len(snapshot.telemetry) - 1)
        if "speed_multiplier" in body:
            request.app.state.replay_speed_multiplier = max(0.0, float(body["speed_multiplier"]))
        if "paused" in body:
            request.app.state.replay_paused = bool(body["paused"])
        request.app.state.replay_anchor_interval = int(current)
        request.app.state.replay_started_at = time.time()
        snapshot.current_interval = int(current)
        return replay_status_for(snapshot)

    @app.post("/api/monitor/start")
    def start_monitor(request: Request, start_interval: int = 20) -> dict[str, object]:
        active_monitor: ReplayMonitor = request.app.state.monitor
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        if snapshot is None:
            raise HTTPException(
                status_code=409,
                detail="no live or uploaded energy data is connected",
            )
        return cast(dict[str, object], active_monitor.start(snapshot, start_interval))

    @app.post("/api/monitor/step")
    def step_monitor(request: Request) -> dict[str, object]:
        active_monitor: ReplayMonitor = request.app.state.monitor
        try:
            return cast(dict[str, object], active_monitor.step())
        except EnergyDataError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/monitor/status")
    def monitor_status(request: Request) -> dict[str, object]:
        active_monitor: ReplayMonitor = request.app.state.monitor
        return cast(dict[str, object], active_monitor.status())

    @app.post("/api/parallel/start", response_model=ParallelSimulationState)
    def start_parallel(
        request: Request,
        simulator: Annotated[ParallelSimulator, Depends(get_parallel_sim)],
    ) -> ParallelSimulationState:
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        if snapshot is None:
            raise HTTPException(
                status_code=409,
                detail="no uploaded energy data; upload CSV first",
            )
        return simulator.start(snapshot)

    @app.post("/api/parallel/step", response_model=ParallelStepResponse)
    def step_parallel(
        simulator: Annotated[ParallelSimulator, Depends(get_parallel_sim)],
    ) -> ParallelStepResponse:
        try:
            return simulator.step()
        except ParallelSimError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/parallel/status", response_model=ParallelStepResponse)
    def status_parallel(
        simulator: Annotated[ParallelSimulator, Depends(get_parallel_sim)],
    ) -> ParallelStepResponse:
        return simulator.status()

    @app.get("/api/parallel/slo")
    def slo_parallel(
        simulator: Annotated[ParallelSimulator, Depends(get_parallel_sim)],
    ) -> dict[str, object]:
        return simulator.get_slo()

    @app.get("/api/parallel/rag")
    def rag_parallel(
        simulator: Annotated[ParallelSimulator, Depends(get_parallel_sim)],
        interval: int | None = None,
    ) -> dict[str, str]:
        return {"insight": simulator.get_rag_insight(interval)}

    @app.get("/api/ops/evidence-board")
    def ops_evidence_board(request: Request) -> dict[str, object]:
        runtime: Settings = request.app.state.settings
        store: EvidenceStore = request.app.state.store
        simulator: ParallelSimulator = request.app.state.parallel_sim
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        manifest = build_agentteams_manifest(runtime, store.list_public_model_configs())
        parallel = simulator.status()
        has_upload = snapshot is not None
        current_interval = parallel.cursor
        latest_reopt = (
            parallel.reoptimization_events[-1] if parallel.reoptimization_events else None
        )
        latest_history = parallel.interval_history[-1] if parallel.interval_history else None
        trace_count = len(parallel.agentteams_trace)
        readback_rate = 1.0 if latest_history is not None else 0.0
        return {
            "run_id": f"parallel-{current_interval:02d}",
            "decision_point": current_interval,
            "data_snapshot": {
                "loaded": has_upload,
                "contract": "ExternalDataSnapshot",
                "source": snapshot.source if snapshot else "waiting_for_upload",
                "telemetry_points": len(snapshot.telemetry) if snapshot else 0,
                "snapshot_version": "opencem-normalized-v1",
                "polardb_mapping": [
                    "telemetry_quality",
                    "load_pv_forecast",
                    "tariff",
                    "storage_state",
                    "production_constraints",
                    "dispatch_versions",
                    "execution_receipts",
                ],
            },
            "closed_loop": {
                "business_input": "Upload OpenCEM CSV or connect park EMS/BMS/PCS snapshot.",
                "active_plan": "PARALLEL" if parallel.agentteams_active else "none",
                "old_plan_status": (
                    "invalidated" if parallel.plans_invalidated else "valid_until_deviation"
                ),
                "replan_count": parallel.total_reoptimizations,
                "hitl_gate": "required_before_write_or_flexible_load_action",
                "execution_readback_rate": readback_rate,
                "completion_condition": (
                    "96 intervals replayed, final receipt sealed, no invalid plan executed."
                ),
                "latest_reason": latest_reopt.reason if latest_reopt else parallel.event,
            },
            "comparison": {
                "baseline_cost_yuan": parallel.baseline_cost_yuan,
                "optimized_cost_yuan": parallel.optimized_cost_yuan,
                "savings_yuan": parallel.savings_yuan,
                "savings_percent": parallel.savings_percent,
                "invalid_plan_executions": 0,
                "constraint_violations": 0,
            },
            "agentteams": {
                "framework_repository": manifest.framework_repository,
                "runtime_mode": manifest.runtime_mode,
                "team_name": manifest.team_name,
                "workers": [worker.model_dump() for worker in manifest.workers],
                "mcp_servers": manifest.mcp_servers,
                "trace_count": trace_count,
            },
            "rag_memory": {
                "enabled": True,
                "policy": (
                    "RAG explains prior deviations and human adjustments; optimizer "
                    "and safety rules still recompute every dispatch."
                ),
                "latest_insight": simulator.get_rag_insight(current_interval - 1),
                "writes": {
                    "deviation_events": parallel.total_reoptimizations,
                    "human_adjustments": 0,
                    "final_outcomes": 1 if not parallel.running and trace_count else 0,
                },
            },
            "slo": simulator.get_slo(),
        }

    @app.post("/api/external/dispatch", response_model=TaskRecord, status_code=201)
    def dispatch_from_external_data(
        body: ExternalDispatchRequest,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
        simulator: Annotated[ExternalDataSimulator, Depends(get_external_data)],
    ) -> TaskRecord:
        snapshot = simulator.snapshot(body.seed, body.current_interval, body.fault_mode)
        try:
            return workflow.run(
                snapshot.scenario,
                trigger=f"EXTERNAL_DATA_{body.fault_mode.upper()}",
            )
        except WorkflowError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/demo/run", response_model=DemoRunResponse, status_code=201)
    def run_demo(
        demo: Annotated[CompoundChangeDemo, Depends(get_compound_demo)],
    ) -> DemoRunResponse:
        try:
            return demo.run()
        except DemoWorkflowError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/demo/run-rollback", response_model=DemoRunResponse, status_code=201)
    def run_demo_rollback(
        demo: Annotated[CompoundChangeDemo, Depends(get_compound_demo)],
    ) -> DemoRunResponse:
        try:
            return demo.run_rollback()
        except DemoWorkflowError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/tasks/{task_id}/approval", response_model=TaskRecord)
    def decide_approval(
        task_id: str,
        body: ApprovalRequest,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
    ) -> TaskRecord:
        try:
            return workflow.decide(task_id, body)
        except WorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post("/api/tasks/{task_id}/approval-only", response_model=TaskRecord)
    def approve_without_execution(
        task_id: str,
        body: ApprovalRequest,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
    ) -> TaskRecord:
        try:
            return workflow.approve_only(task_id, body)
        except WorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post("/api/tasks/{task_id}/execute-approved", response_model=TaskRecord)
    def execute_approved_task(
        task_id: str,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
    ) -> TaskRecord:
        try:
            return workflow.execute_approved(task_id)
        except WorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post("/api/tasks/{task_id}/approve")
    def approve_demo_task(
        task_id: str,
        body: ApprovalDecisionRequest,
        demo: Annotated[CompoundChangeDemo, Depends(get_compound_demo)],
    ) -> dict[str, object]:
        try:
            return demo.approve(task_id, body).model_dump(mode="json")
        except DemoWorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post("/api/tasks/{task_id}/execute", response_model=ExecutionReceipt)
    def execute_demo_task(
        task_id: str,
        body: ExecuteRequest,
        demo: Annotated[CompoundChangeDemo, Depends(get_compound_demo)],
    ) -> ExecutionReceipt:
        try:
            return demo.execute(task_id, body)
        except DemoWorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post(
        "/api/tasks/{task_id}/rolling-reoptimize",
        response_model=TaskRecord,
        status_code=201,
    )
    def rolling_reoptimize(
        task_id: str,
        body: RollingHorizonRequest,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
    ) -> TaskRecord:
        try:
            return workflow.rolling_reoptimize(task_id, body)
        except WorkflowError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error

    @app.post(
        "/api/tasks/{task_id}/reoptimize",
        response_model=TaskRecord,
        status_code=201,
    )
    def reoptimize(
        task_id: str,
        body: ReoptimizationRequest,
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> TaskRecord:
        parent = evidence_store.get(task_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="task not found")
        changed = apply_operational_change(parent.scenario_snapshot, body)
        try:
            return workflow.run(
                changed,
                trigger=body.trigger,
                parent_task_id=parent.task_id,
            )
        except WorkflowError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/tasks", response_model=list[TaskRecord])
    def list_tasks(
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
        limit: int = 20,
    ) -> list[TaskRecord]:
        return evidence_store.list(min(max(limit, 1), 100))

    @app.get("/api/tasks/{task_id}", response_model=TaskRecord)
    def get_task(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> TaskRecord:
        task = evidence_store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return task

    @app.get("/api/tasks/{task_id}/events")
    def get_task_events(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> PayloadRows:
        if evidence_store.get(task_id) is None:
            raise HTTPException(status_code=404, detail="task not found")
        return evidence_store.list_task_events(task_id)

    @app.get("/api/tasks/{task_id}/context")
    def get_task_context(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> PayloadRow:
        context = evidence_store.get_context_snapshot(task_id)
        if context is None:
            raise HTTPException(status_code=404, detail="context snapshot not found")
        return context

    @app.get("/api/tasks/{task_id}/candidates")
    def get_task_candidates(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> PayloadRows:
        if evidence_store.get(task_id) is None:
            raise HTTPException(status_code=404, detail="task not found")
        return evidence_store.list_candidate_plans(task_id)

    @app.get("/api/tasks/{task_id}/audit")
    def get_task_audit(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> PayloadRows:
        if evidence_store.get(task_id) is None:
            raise HTTPException(status_code=404, detail="task not found")
        return evidence_store.list_audit_verdicts(task_id)

    @app.get("/api/tasks/{task_id}/evidence")
    def get_task_evidence(
        task_id: str,
        demo: Annotated[CompoundChangeDemo, Depends(get_compound_demo)],
    ) -> dict[str, object]:
        try:
            return demo.evidence(task_id)
        except (DemoWorkflowError, KeyError) as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/styles.css", include_in_schema=False)
    def root_styles() -> FileResponse:
        return FileResponse(static_dir / "styles.css")

    @app.get("/app.js", include_in_schema=False)
    def root_app_script() -> FileResponse:
        return FileResponse(static_dir / "app.js")

    return app


app = create_app()


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run("energymesh.api:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
