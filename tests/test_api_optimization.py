"""Tests for optimization/debug API endpoints."""

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from orcaops.schemas import (
    DebugAnalysis,
    FailurePattern,
    OptimizationSuggestion,
)


def _job_payload():
    return {
        "job_id": "opt-test",
        "sandbox": {"image": "python:3.11"},
        "commands": [{"command": "pytest"}],
    }


@patch("orcaops.api.auto_optimizer")
@patch("orcaops.api.docker_manager")
def test_optimize_endpoint(mock_dm, mock_ao):
    from main import app
    client = TestClient(app)
    mock_ao.suggest_optimizations.return_value = [
        OptimizationSuggestion(
            suggestion_type="timeout",
            current_value="3600s",
            suggested_value="30s",
            reason="p99 is 20s",
            confidence=0.8,
            baseline_key="python:3.11::pytest",
        )
    ]
    resp = client.post("/orcaops/optimize", json=_job_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


@patch("orcaops.api.knowledge_base")
@patch("orcaops.api.run_store")
@patch("orcaops.api.docker_manager")
def test_debug_endpoint(mock_dm, mock_rs, mock_kb):
    from main import app
    from orcaops.schemas import RunRecord, JobStatus
    from datetime import datetime, timezone
    client = TestClient(app)
    mock_rs.get_run.return_value = RunRecord(
        job_id="fail-1", status=JobStatus.FAILED,
        created_at=datetime.now(timezone.utc),
    )
    mock_kb.analyze_failure.return_value = DebugAnalysis(
        job_id="fail-1",
        summary="Test summary",
        likely_causes=["Something broke"],
        suggested_fixes=["Fix it"],
        next_steps=["Check logs"],
    )
    resp = client.post("/orcaops/debug/fail-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "fail-1"


@patch("orcaops.api.run_store")
@patch("orcaops.api.docker_manager")
def test_debug_not_found(mock_dm, mock_rs):
    from main import app
    client = TestClient(app)
    mock_rs.get_run.return_value = None
    resp = client.post("/orcaops/debug/nonexistent")
    assert resp.status_code == 404


@patch("orcaops.api.knowledge_base")
@patch("orcaops.api.docker_manager")
def test_list_patterns(mock_dm, mock_kb):
    from main import app
    client = TestClient(app)
    mock_kb.list_patterns.return_value = [
        FailurePattern(
            pattern_id="test",
            regex_pattern="error",
            category="test",
            title="Test",
            description="desc",
        )
    ]
    resp = client.get("/orcaops/knowledge-base/patterns")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
