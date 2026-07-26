from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from energymesh.audit import IndependentSafetyAuditor
from energymesh.config import Settings
from energymesh.demo import apply_operational_change, load_demo_scenario
from energymesh.models import (
    ApprovalRequest,
    ReoptimizationRequest,
    Scenario,
    TaskRecord,
)
from energymesh.optimizer import DispatchOptimizer
from energymesh.orchestrator import EnergyMeshOrchestrator, WorkflowError
from energymesh.perception import PerceptionAgent
from energymesh.simulator import SimulationExecutor
from energymesh.storage import EvidenceStore


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_settings.assert_safe_runtime()
    store = EvidenceStore(active_settings.db_path, active_settings.evidence_dir)
    orchestrator = EnergyMeshOrchestrator(
        perception=PerceptionAgent(),
        optimizer=DispatchOptimizer(),
        auditor=IndependentSafetyAuditor(),
        executor=SimulationExecutor(active_settings),
        store=store,
    )
    scenario = load_demo_scenario()

    app = FastAPI(
        title="EnergyMesh Agents API",
        version="0.1.0",
        description="Audited 15-minute economic dispatch in simulation mode.",
    )
    app.state.settings = active_settings
    app.state.store = store
    app.state.orchestrator = orchestrator
    app.state.scenario = scenario

    def get_orchestrator(request: Request) -> EnergyMeshOrchestrator:
        return cast(EnergyMeshOrchestrator, request.app.state.orchestrator)

    def get_store(request: Request) -> EvidenceStore:
        return cast(EvidenceStore, request.app.state.store)

    def get_scenario(request: Request) -> Scenario:
        return cast(Scenario, request.app.state.scenario)

    @app.get("/api/health")
    def health(request: Request) -> dict[str, object]:
        runtime: Settings = request.app.state.settings
        return {
            "status": "ok",
            "version": app.version,
            "simulation_mode": runtime.simulation_mode,
            "allow_production_write": runtime.allow_production_write,
        }

    @app.get("/api/demo/scenario", response_model=Scenario)
    def demo_scenario(
        active_scenario: Annotated[Scenario, Depends(get_scenario)],
    ) -> Scenario:
        return active_scenario

    @app.post("/api/demo/run", response_model=TaskRecord, status_code=201)
    def run_demo(
        workflow: Annotated[EnergyMeshOrchestrator, Depends(get_orchestrator)],
        active_scenario: Annotated[Scenario, Depends(get_scenario)],
    ) -> TaskRecord:
        try:
            return workflow.run(active_scenario)
        except WorkflowError as error:
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

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run("energymesh.api:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
