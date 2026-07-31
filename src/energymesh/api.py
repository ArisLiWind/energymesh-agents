from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from energymesh.agentteams import AgentTeamsManifest, build_agentteams_manifest
from energymesh.audit import IndependentSafetyAuditor
from energymesh.compound_demo import CompoundChangeDemo, DemoWorkflowError
from energymesh.config import Settings
from energymesh.demo import apply_operational_change, load_demo_scenario
from energymesh.external_data import ExternalDataSimulator
from energymesh.model_gateway import chat_with_agent_config, normalize_agent_id
from energymesh.models import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModelConfigPublic,
    AgentModelConfigRequest,
    AgentModelTestResponse,
    ApprovalDecisionRequest,
    ApprovalRequest,
    DemoRunResponse,
    ExecuteRequest,
    ExecutionReceipt,
    ExternalDataSnapshot,
    ExternalDispatchRequest,
    ReoptimizationRequest,
    Scenario,
    TaskRecord,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.orchestrator import EnergyMeshOrchestrator, WorkflowError
from energymesh.perception import PerceptionAgent
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

    app = FastAPI(
        title="EnergyMesh Agents API",
        version="0.1.0",
        description="Audited 15-minute economic dispatch in simulation mode.",
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.compound_demo = compound_demo
    app.state.orchestrator = orchestrator
    app.state.scenario = scenario
    app.state.external_data = external_data

    def get_orchestrator(request: Request) -> EnergyMeshOrchestrator:
        return cast(EnergyMeshOrchestrator, request.app.state.orchestrator)

    def get_store(request: Request) -> EvidenceStore:
        return cast(EvidenceStore, request.app.state.store)

    def get_compound_demo(request: Request) -> CompoundChangeDemo:
        return cast(CompoundChangeDemo, request.app.state.compound_demo)

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
            reply = chat_with_agent_config(config, body.message)
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return AgentChatResponse(agent_id=normalized, model=config.model, response=reply)

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

    @app.get("/campus3d.js", include_in_schema=False)
    def root_campus_script() -> FileResponse:
        return FileResponse(static_dir / "campus3d.js")

    return app


app = create_app()


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run("energymesh.api:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
