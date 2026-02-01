"""Tests for baseline MCP tools."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from orcaops.schemas import PerformanceBaseline


def _make_baseline(key="python:3.11::pytest"):
    return PerformanceBaseline(
        key=key,
        sample_count=10,
        duration_ema=15.0,
        duration_mean=14.5,
        duration_stddev=2.3,
        duration_p50=14.0,
        duration_p95=18.0,
        duration_p99=20.0,
        duration_min=10.0,
        duration_max=22.0,
        success_count=9,
        failure_count=1,
        success_rate=0.9,
        last_duration=15.0,
    )


class TestListBaselines:
    @patch("orcaops.mcp_server._baseline_tracker")
    def test_list_baselines(self, mock_bt):
        from orcaops.mcp_server import orcaops_list_baselines
        mock_bt.return_value.list_baselines.return_value = [_make_baseline()]
        result = json.loads(orcaops_list_baselines())
        assert result["success"] is True
        assert result["count"] == 1
        assert result["baselines"][0]["key"] == "python:3.11::pytest"

    @patch("orcaops.mcp_server._baseline_tracker")
    def test_list_empty(self, mock_bt):
        from orcaops.mcp_server import orcaops_list_baselines
        mock_bt.return_value.list_baselines.return_value = []
        result = json.loads(orcaops_list_baselines())
        assert result["success"] is True
        assert result["count"] == 0


class TestGetBaseline:
    @patch("orcaops.mcp_server._baseline_tracker")
    def test_get_baseline(self, mock_bt):
        from orcaops.mcp_server import orcaops_get_baseline
        mock_bt.return_value.get_baseline_by_key.return_value = _make_baseline()
        result = json.loads(orcaops_get_baseline("python:3.11::pytest"))
        assert result["success"] is True
        assert result["key"] == "python:3.11::pytest"

    @patch("orcaops.mcp_server._baseline_tracker")
    def test_get_not_found(self, mock_bt):
        from orcaops.mcp_server import orcaops_get_baseline
        mock_bt.return_value.get_baseline_by_key.return_value = None
        result = json.loads(orcaops_get_baseline("nope"))
        assert result["success"] is False


class TestDeleteBaseline:
    @patch("orcaops.mcp_server._baseline_tracker")
    def test_delete_baseline(self, mock_bt):
        from orcaops.mcp_server import orcaops_delete_baseline
        mock_bt.return_value.delete_baseline.return_value = True
        result = json.loads(orcaops_delete_baseline("python:3.11::pytest"))
        assert result["success"] is True

    @patch("orcaops.mcp_server._baseline_tracker")
    def test_delete_not_found(self, mock_bt):
        from orcaops.mcp_server import orcaops_delete_baseline
        mock_bt.return_value.delete_baseline.return_value = False
        result = json.loads(orcaops_delete_baseline("nope"))
        assert result["success"] is False
