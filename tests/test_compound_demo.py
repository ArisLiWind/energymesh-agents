from __future__ import annotations

from fastapi.testclient import TestClient

from energymesh.api import create_app


def test_compound_demo_creates_auditable_task_chain(settings) -> None:
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/demo/run")
        assert created.status_code == 201
        run = created.json()
        task_id = run["task_id"]

        task = client.get(f"/api/tasks/{task_id}").json()
        events = client.get(f"/api/tasks/{task_id}/events").json()
        context = client.get(f"/api/tasks/{task_id}/context").json()
        candidates = client.get(f"/api/tasks/{task_id}/candidates").json()
        audit = client.get(f"/api/tasks/{task_id}/audit").json()

        assert task["task_id"] == "TASK-20260731-014"
        assert task["task_version"] == 2
        assert task["state"] == "AWAITING_APPROVAL"
        assert [event["to_state"] for event in events] == [
            "TASK_RECEIVED",
            "SENSING",
            "REPLANNING_REQUIRED",
            "PLANNING",
            "AUDITING",
            "AWAITING_APPROVAL",
        ]
        assert context["changes"]["transformer_temperature_conflict"] is True
        assert context["previous_plan_status"] == "invalidated"
        assert context["automation_permission"] == "restricted"
        assert len(candidates) == 3
        assert candidates[0]["candidate_id"] == "Candidate-A"
        assert audit[0]["candidate_id"] == "Candidate-A"
        assert audit[0]["verdict"] == "rejected"
        assert audit[0]["transformer_load_percent"] == 103.8
        assert audit[0]["safety_limit_percent"] == 95


def test_compound_demo_enforces_approval_and_execution_gates(settings) -> None:
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/demo/run").json()
        task_id = run["task_id"]
        context = client.get(f"/api/tasks/{task_id}/context").json()

        rejected_approval = client.post(
            f"/api/tasks/{task_id}/approve",
            json={
                "candidate_id": "Candidate-A",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "approver": "test-approver",
                "reason": "should not pass",
            },
        )
        assert rejected_approval.status_code == 409
        assert "has not passed" in rejected_approval.json()["detail"]

        unapproved_execute = client.post(
            f"/api/tasks/{task_id}/execute",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "idempotency_key": "IDEMP-NO-APPROVAL",
            },
        )
        assert unapproved_execute.status_code == 409
        assert "approval is required" in unapproved_execute.json()["detail"]

        stale_version = client.post(
            f"/api/tasks/{task_id}/approve",
            json={
                "candidate_id": "Candidate-B",
                "task_version": 1,
                "context_hash": context["context_hash"],
                "approver": "test-approver",
                "reason": "stale version",
            },
        )
        assert stale_version.status_code == 409
        assert "version" in stale_version.json()["detail"]

        approval = client.post(
            f"/api/tasks/{task_id}/approve",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "approver": "test-approver",
                "reason": "approved for execution",
            },
        )
        assert approval.status_code == 200

        bad_hash = client.post(
            f"/api/tasks/{task_id}/execute",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": "bad-hash",
                "idempotency_key": "IDEMP-BAD-HASH",
            },
        )
        assert bad_hash.status_code == 409
        assert "context hash" in bad_hash.json()["detail"]

        execute = client.post(
            f"/api/tasks/{task_id}/execute",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "idempotency_key": "IDEMP-OK-ONCE",
            },
        )
        assert execute.status_code == 200
        first_commands = client.get(f"/api/tasks/{task_id}/evidence").json()["execution_commands"]
        repeated = client.post(
            f"/api/tasks/{task_id}/execute",
            json={
                "candidate_id": "Candidate-B",
                "task_version": context["task_version"],
                "context_hash": context["context_hash"],
                "idempotency_key": "IDEMP-OK-ONCE",
            },
        )
        assert repeated.status_code == 200
        repeated_commands = client.get(f"/api/tasks/{task_id}/evidence").json()[
            "execution_commands"
        ]
        assert len(repeated_commands) == len(first_commands)
        assert client.get(f"/api/tasks/{task_id}").json()["state"] == "COMPLETED"


def test_compound_demo_rollback_and_evidence_package(settings) -> None:
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/demo/run-rollback")
        assert run.status_code == 201
        task_id = run.json()["task_id"]
        task = client.get(f"/api/tasks/{task_id}").json()
        events = client.get(f"/api/tasks/{task_id}/events").json()
        evidence = client.get(f"/api/tasks/{task_id}/evidence").json()

        assert task["state"] == "ROLLBACK"
        assert events[-3]["to_state"] == "EXECUTING"
        assert events[-2]["to_state"] == "VERIFYING"
        assert events[-1]["to_state"] == "ROLLBACK"
        assert evidence["rollback_records"][0]["baseline_restored"] is True
        assert evidence["verification_results"][0]["max_deviation_percent"] > 5
        assert evidence["context_snapshot"]["context_hash"] == task["context_hash"]
        assert len(evidence["agent_handoffs"]) >= 4
        assert {item["skill_name"] for item in evidence["skill_invocations"]} >= {
            "microgrid_context_ingest",
            "dispatch_plan_generate",
            "dispatch_audit_verify",
            "execution_mapping",
        }
