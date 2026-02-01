"""Tests for prediction MCP tools."""

import json
from unittest.mock import patch, MagicMock

from orcaops.schemas import DurationPrediction, FailureRiskAssessment


class TestPredictJob:
    @patch("orcaops.mcp_server._failure_predictor")
    @patch("orcaops.mcp_server._duration_predictor")
    def test_predict_with_baseline(self, mock_dp, mock_fp):
        from orcaops.mcp_server import orcaops_predict_job
        mock_dp.return_value.predict.return_value = DurationPrediction(
            estimated_seconds=15.0,
            confidence=0.5,
            range_low=10.0,
            range_high=20.0,
            sample_count=10,
            baseline_key="python:3.11::pytest",
        )
        mock_fp.return_value.assess_risk.return_value = FailureRiskAssessment(
            risk_score=0.1,
            risk_level="low",
            factors=["Stable."],
            sample_count=10,
        )
        result = json.loads(orcaops_predict_job("python:3.11", "pytest"))
        assert result["success"] is True
        assert result["duration"]["estimated_seconds"] == 15.0
        assert result["failure_risk"]["risk_level"] == "low"

    @patch("orcaops.mcp_server._failure_predictor")
    @patch("orcaops.mcp_server._duration_predictor")
    def test_predict_no_baseline(self, mock_dp, mock_fp):
        from orcaops.mcp_server import orcaops_predict_job
        mock_dp.return_value.predict.return_value = DurationPrediction(
            estimated_seconds=300.0,
            confidence=0.05,
            range_low=60.0,
            range_high=3600.0,
            sample_count=0,
        )
        mock_fp.return_value.assess_risk.return_value = FailureRiskAssessment(
            risk_score=0.1,
            risk_level="low",
            factors=["No data."],
            sample_count=0,
        )
        result = json.loads(orcaops_predict_job("python:3.11", "pytest"))
        assert result["success"] is True
        assert result["duration"]["sample_count"] == 0

    @patch("orcaops.mcp_server._failure_predictor")
    @patch("orcaops.mcp_server._duration_predictor")
    def test_predict_multiple_commands(self, mock_dp, mock_fp):
        from orcaops.mcp_server import orcaops_predict_job
        mock_dp.return_value.predict.return_value = DurationPrediction(
            estimated_seconds=30.0,
            confidence=0.3,
            range_low=20.0,
            range_high=40.0,
            sample_count=5,
        )
        mock_fp.return_value.assess_risk.return_value = FailureRiskAssessment(
            risk_score=0.2,
            risk_level="medium",
            factors=["Some failures."],
            sample_count=5,
        )
        result = json.loads(orcaops_predict_job("python:3.11", "pytest|flake8"))
        assert result["success"] is True
