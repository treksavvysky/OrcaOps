"""Tests for anomaly API endpoints."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from orcaops.schemas import (
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
)


def _make_anomaly(anomaly_id="anom_test1", anomaly_type=AnomalyType.DURATION):
    return AnomalyRecord(
        anomaly_id=anomaly_id,
        job_id="job-1",
        baseline_key="python:3.11::pytest",
        anomaly_type=anomaly_type,
        severity=AnomalySeverity.WARNING,
        title="Test anomaly",
        description="Duration is too long",
        expected="15.0s",
        actual="25.0s",
        z_score=2.5,
        deviation_percent=66.7,
    )


@patch("orcaops.api.anomaly_store")
@patch("orcaops.api.docker_manager")
def test_list_anomalies(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.query.return_value = ([_make_anomaly()], 1)
    resp = client.get("/orcaops/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["anomalies"][0]["anomaly_id"] == "anom_test1"


@patch("orcaops.api.anomaly_store")
@patch("orcaops.api.docker_manager")
def test_list_anomalies_with_filters(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.query.return_value = ([], 0)
    resp = client.get("/orcaops/anomalies?anomaly_type=duration&severity=warning")
    assert resp.status_code == 200
    mock_store.query.assert_called_once()
    call_kwargs = mock_store.query.call_args[1]
    assert call_kwargs["anomaly_type"] == AnomalyType.DURATION
    assert call_kwargs["severity"] == AnomalySeverity.WARNING


@patch("orcaops.api.anomaly_store")
@patch("orcaops.api.docker_manager")
def test_list_anomalies_invalid_type(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    resp = client.get("/orcaops/anomalies?anomaly_type=bogus")
    assert resp.status_code == 400


@patch("orcaops.api.anomaly_store")
@patch("orcaops.api.docker_manager")
def test_acknowledge_anomaly(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.acknowledge.return_value = True
    resp = client.post("/orcaops/anomalies/anom_test1/acknowledge")
    assert resp.status_code == 200
    assert "acknowledged" in resp.json()["message"]


@patch("orcaops.api.anomaly_store")
@patch("orcaops.api.docker_manager")
def test_acknowledge_not_found(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.acknowledge.return_value = False
    resp = client.post("/orcaops/anomalies/nonexistent/acknowledge")
    assert resp.status_code == 404
