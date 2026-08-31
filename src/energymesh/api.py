import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from energymesh.agentteams import AgentTeamsManifest, build_agentteams_manifest
from energymesh.audit import IndependentSafetyAuditor
from energymesh.compound_demo import CompoundChangeDemo, DemoWorkflowError
from energymesh.config import Settings
from energymesh.data_pipeline import EnergyDataError, ReplayMonitor, SnapshotFactory
from energymesh.demo import apply_operational_change, load_demo_scenario
from energymesh.external_data import ExternalDataSimulator
from energymesh.model_gateway import chat_with_agent_config, normalize_agent_id
from energymesh.mcp_gateway import EnergyMCPGateway
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
from energymesh.orchestrator import EnergyMeshOrchestrator, WorkflowError
from energymesh.parallel_sim import ParallelSimError, ParallelSimulator
from energymesh.perception import PerceptionAgent
from energymesh.runtime import AgentRuntimeError, PersistentAgentRuntime
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore, PayloadRow, PayloadRows


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_settings.assert_safe_runtime()
    store = EvidenceStore(active_settings.db_path, active_settings.evidence_dir)
    compound_demo = CompoundChangeDemo(store)
    orchestrator = EnergyMeshOrchestrator(
        perception=PerceptionAgent(),
        optimizer=DispatchOptimizer(),
        auditor=IndependentSafetyAuditor(),
        executor=SimulationExecutor(active_settings),
        store=store,
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

    def current_world_state() -> dict[str, object] | None:
        snapshot: ExternalDataSnapshot | None = app.state.uploaded_snapshot
        status = monitor.status()
        current = status.get("current")
        if current is None and snapshot and snapshot.telemetry:
            index = min(max(snapshot.current_interval, 0), len(snapshot.telemetry) - 1)
            current = snapshot.telemetry[index].model_dump(mode="json")
        if not isinstance(current, dict):
            return None
        load_kw = float(current.get("load_kw") or 0)
        pv_kw = float(current.get("pv_kw") or 0)
        battery_soc = float(current.get("battery_soc") or 0)
        grid_import_kw = max(0.0, load_kw - pv_kw)
        return {
            "current": current,
            "source": status.get("source") or (snapshot.source if snapshot else "uploaded_snapshot"),
            "cursor": status.get("cursor") if status.get("current") else snapshot.current_interval if snapshot else 0,
            "current_load_mw": round(load_kw / 1000, 4),
            "pv_forecast_mw": round(pv_kw / 1000, 4),
            "storage_soc_percent": round(battery_soc * 100, 1),
            "grid_import_mw": round(grid_import_kw / 1000, 4),
            "transformer_load_percent": round(min(100.0, grid_import_kw / 10), 1),
            "available_capacity_mw": round(max(0.0, 10000 - grid_import_kw) / 1000, 4),
            "device_status": {
                "ems": "online",
                "pcs": "from_uploaded_snapshot",
                "bms": "from_uploaded_snapshot",
                "mes": "simulation",
            },
        }

    agent_runtime = PersistentAgentRuntime(
        store,
        mcp_gateway=EnergyMCPGateway(current_world_state),
    )

    app = FastAPI(
        title="EnergyMesh Agents API",
        version="0.1.0",
        description="Audited 15-minute economic dispatch in simulation mode.",
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.compound_demo = compound_demo
    app.state.agent_runtime = agent_runtime
    app.state.orchestrator = orchestrator
    app.state.scenario = scenario
    app.state.external_data = external_data
    app.state.snapshot_factory = snapshot_factory
    app.state.monitor = monitor
    app.state.uploaded_snapshot = None
    app.state.parallel_sim = ParallelSimulator(orchestrator, store)

    def get_orchestrator(request: Request) -> EnergyMeshOrchestrator:
        return cast(EnergyMeshOrchestrator, request.app.state.orchestrator)

    def get_store(request: Request) -> EvidenceStore:
        return cast(EvidenceStore, request.app.state.store)

    def get_agent_runtime(request: Request) -> PersistentAgentRuntime:
        return cast(PersistentAgentRuntime, request.app.state.agent_runtime)

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
        return {
            "status": "ok",
            "version": app.version,
            "simulation_mode": runtime.simulation_mode,
            "allow_production_write": runtime.allow_production_write,
            "agent_framework": "agentscope-ai/AgentTeams",
            "agentteams_enabled": runtime.agentteams_enabled,
            "agentteams_team_name": runtime.agentteams_team_name,
        }

    @app.get("/api/agentteams/manifest", response_model=AgentTeamsManifest)
    def agentteams_manifest(request: Request) -> AgentTeamsManifest:
        runtime: Settings = request.app.state.settings
        store: EvidenceStore = request.app.state.store
        return build_agentteams_manifest(runtime, store.list_public_model_configs())

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

    @app.post(
        "/api/agents/{agent_id}/model/test", response_model=AgentModelTestResponse
    )
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
        return AgentChatResponse(
            agent_id=normalized, model=config.model, response=reply
        )

    @app.post("/api/runtime/chat", response_model=AgentRuntimeChatResponse)
    def chat_with_runtime(
        body: AgentRuntimeChatRequest,
        runtime: Annotated[PersistentAgentRuntime, Depends(get_agent_runtime)],
    ) -> AgentRuntimeChatResponse:
        try:
            return runtime.chat(body.message, body.session_id, body.task_id)
        except AgentRuntimeError as error:
            message = str(error)
            status = 404 if message == "task not found" else 409
            raise HTTPException(status_code=status, detail=message) from error
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/runtime/chat/stream")
    def stream_chat_with_runtime(
        body: AgentRuntimeChatRequest,
        runtime: Annotated[PersistentAgentRuntime, Depends(get_agent_runtime)],
    ) -> StreamingResponse:
        def sse_event(event: dict[str, object]) -> Iterator[str]:
            yield f"event: {event['type']}\n"
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        def events() -> Iterator[str]:
            try:
                for event in runtime.stream_chat(
                    body.message, body.session_id, body.task_id
                ):
                    yield from sse_event(event)
            except AgentRuntimeError as error:
                yield from sse_event({"type": "runtime_error", "detail": str(error)})
            except Exception as error:
                yield from sse_event({"type": "runtime_error", "detail": str(error)})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get(
        "/api/runtime/sessions/{session_id}/messages", response_model=list[AgentMessage]
    )
    def list_runtime_messages(
        session_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
        limit: int = 50,
    ) -> list[AgentMessage]:
        return evidence_store.list_agent_messages(session_id, limit=limit)

    @app.get(
        "/api/runtime/tasks/{task_id}/artifacts", response_model=list[RuntimeArtifact]
    )
    def list_runtime_artifacts(
        task_id: str,
        evidence_store: Annotated[EvidenceStore, Depends(get_store)],
    ) -> list[RuntimeArtifact]:
        return evidence_store.list_runtime_artifacts(task_id)

    @app.get(
        "/api/runtime/tasks/{task_id}/tool-calls", response_model=list[RuntimeToolCall]
    )
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
            raise HTTPException(
                status_code=404, detail="OpenCEM sample CSV is not available"
            )
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
        return snapshot

    @app.get("/api/data/snapshot/current", response_model=ExternalDataSnapshot)
    def current_uploaded_snapshot(request: Request) -> ExternalDataSnapshot:
        snapshot: ExternalDataSnapshot | None = request.app.state.uploaded_snapshot
        if snapshot is None:
            raise HTTPException(
                status_code=404, detail="no normalized Snapshot is loaded"
            )
        return snapshot

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
