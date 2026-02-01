"""Tests for anomaly MCP tools."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from orcaops.schemas import (
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
)


def _make_anomaly(anomaly_id="anom_test1"):
    return AnomalyRecord(
        anomaly_id=anomaly_id,
        job_id="job-1",
        baseline_key="python:3.11::pytest",
        anomaly_type=AnomalyType.DURATION,
        severity=AnomalySeverity.WARNING,
        title="Test anomaly",
        description="Duration is too long",
        expected="15.0s",
        actual="25.0s",
        z_score=2.5,
        deviation_percent=66.7,
    )


class TestListAnomalies:
    @patch("orcaops.mcp_server._anomaly_store")
    def test_list_anomalies(self, mock_store):
        from orcaops.mcp_server import orcaops_list_anomalies
        mock_store.return_value.query.return_value = ([_make_anomaly()], 1)
        result = json.loads(orcaops_list_anomalies())
        assert result["success"] is True
        assert result["total"] == 1
        assert result["count"] == 1
        assert result["anomalies"][0]["anomaly_id"] == "anom_test1"

    @patch("orcaops.mcp_server._anomaly_store")
    def test_list_empty(self, mock_store):
        from orcaops.mcp_server import orcaops_list_anomalies
        mock_store.return_value.query.return_value = ([], 0)
        result = json.loads(orcaops_list_anomalies())
        assert result["success"] is True
        assert result["total"] == 0
        assert result["count"] == 0

    @patch("orcaops.mcp_server._anomaly_store")
    def test_list_with_type_filter(self, mock_store):
        from orcaops.mcp_server import orcaops_list_anomalies
        mock_store.return_value.query.return_value = ([], 0)
        result = json.loads(orcaops_list_anomalies(anomaly_type="duration"))
        assert result["success"] is True

    def test_list_invalid_type(self):
        from orcaops.mcp_server import orcaops_list_anomalies
        result = json.loads(orcaops_list_anomalies(anomaly_type="bogus"))
        assert result["success"] is False


class TestAcknowledgeAnomaly:
    @patch("orcaops.mcp_server._anomaly_store")
    def test_acknowledge_success(self, mock_store):
        from orcaops.mcp_server import orcaops_acknowledge_anomaly
        mock_store.return_value.acknowledge.return_value = True
        result = json.loads(orcaops_acknowledge_anomaly("anom_test1"))
        assert result["success"] is True

    @patch("orcaops.mcp_server._anomaly_store")
    def test_acknowledge_not_found(self, mock_store):
        from orcaops.mcp_server import orcaops_acknowledge_anomaly
        mock_store.return_value.acknowledge.return_value = False
        result = json.loads(orcaops_acknowledge_anomaly("nope"))
        assert result["success"] is False
