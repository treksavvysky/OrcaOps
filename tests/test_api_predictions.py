"""Tests for prediction API endpoints."""

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from orcaops.schemas import DurationPrediction, FailureRiskAssessment


def _job_payload():
    return {
        "job_id": "pred-test",
        "sandbox": {"image": "python:3.11"},
        "commands": [{"command": "pytest"}],
    }


@patch("orcaops.api.failure_predictor")
@patch("orcaops.api.duration_predictor")
@patch("orcaops.api.docker_manager")
def test_predict_endpoint(mock_dm, mock_dp, mock_fp):
    from main import app
    client = TestClient(app)
    mock_dp.predict.return_value = DurationPrediction(
        estimated_seconds=15.0,
        confidence=0.5,
        range_low=10.0,
        range_high=20.0,
        sample_count=10,
        baseline_key="python:3.11::pytest",
    )
    mock_fp.assess_risk.return_value = FailureRiskAssessment(
        risk_score=0.1,
        risk_level="low",
        factors=["Stable execution."],
        sample_count=10,
    )
    resp = client.post("/orcaops/predict", json=_job_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert data["duration"]["estimated_seconds"] == 15.0
    assert data["failure_risk"]["risk_level"] == "low"


@patch("orcaops.api.failure_predictor")
@patch("orcaops.api.duration_predictor")
@patch("orcaops.api.docker_manager")
def test_predict_no_baseline(mock_dm, mock_dp, mock_fp):
    from main import app
    client = TestClient(app)
    mock_dp.predict.return_value = DurationPrediction(
        estimated_seconds=300.0,
        confidence=0.05,
        range_low=60.0,
        range_high=3600.0,
        sample_count=0,
    )
    mock_fp.assess_risk.return_value = FailureRiskAssessment(
        risk_score=0.1,
        risk_level="low",
        factors=["No data."],
        sample_count=0,
    )
    resp = client.post("/orcaops/predict", json=_job_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert data["duration"]["sample_count"] == 0
