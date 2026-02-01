"""Tests for baseline API endpoints."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from orcaops.schemas import PerformanceBaseline


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _make_baseline(key="python:3.11::pytest", sample_count=10):
    return PerformanceBaseline(
        key=key,
        sample_count=sample_count,
        duration_ema=15.0,
        duration_mean=14.5,
        duration_stddev=2.3,
        duration_p50=14.0,
        duration_p95=18.0,
        duration_p99=20.0,
        duration_min=10.0,
        duration_max=22.0,
        memory_mean_mb=256.0,
        memory_max_mb=512.0,
        success_count=9,
        failure_count=1,
        success_rate=0.9,
        recent_durations=[14.0, 15.0, 16.0],
        recent_memory_mb=[256.0, 300.0],
        last_duration=15.0,
        last_updated=datetime.now(timezone.utc),
        first_seen=datetime.now(timezone.utc),
    )


class TestListBaselines:
    @patch("orcaops.api.baseline_tracker")
    def test_list_baselines(self, mock_bt, client):
        mock_bt.list_baselines.return_value = [_make_baseline()]
        resp = client.get("/orcaops/baselines")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["baselines"][0]["key"] == "python:3.11::pytest"

    @patch("orcaops.api.baseline_tracker")
    def test_list_empty(self, mock_bt, client):
        mock_bt.list_baselines.return_value = []
        resp = client.get("/orcaops/baselines")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestGetBaseline:
    @patch("orcaops.api.baseline_tracker")
    def test_get_baseline(self, mock_bt, client):
        mock_bt.get_baseline_by_key.return_value = _make_baseline()
        resp = client.get("/orcaops/baselines/python:3.11::pytest")
        assert resp.status_code == 200
        assert resp.json()["baseline"]["key"] == "python:3.11::pytest"

    @patch("orcaops.api.baseline_tracker")
    def test_get_not_found(self, mock_bt, client):
        mock_bt.get_baseline_by_key.return_value = None
        resp = client.get("/orcaops/baselines/nonexistent")
        assert resp.status_code == 404


class TestDeleteBaseline:
    @patch("orcaops.api.baseline_tracker")
    def test_delete_baseline(self, mock_bt, client):
        mock_bt.delete_baseline.return_value = True
        resp = client.delete("/orcaops/baselines/python:3.11::pytest")
        assert resp.status_code == 200

    @patch("orcaops.api.baseline_tracker")
    def test_delete_not_found(self, mock_bt, client):
        mock_bt.delete_baseline.return_value = False
        resp = client.delete("/orcaops/baselines/nonexistent")
        assert resp.status_code == 404
