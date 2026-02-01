"""Tests for optimization/debug MCP tools."""

import json
from unittest.mock import patch, MagicMock

from orcaops.schemas import (
    DebugAnalysis,
    FailurePattern,
    OptimizationSuggestion,
)


class TestOptimizeJob:
    @patch("orcaops.mcp_server._auto_optimizer")
    def test_optimize_with_suggestions(self, mock_ao):
        from orcaops.mcp_server import orcaops_optimize_job
        mock_ao.return_value.suggest_optimizations.return_value = [
            OptimizationSuggestion(
                suggestion_type="timeout",
                current_value="3600s",
                suggested_value="30s",
                reason="p99 is 20s",
                confidence=0.8,
                baseline_key="python:3.11::pytest",
            )
        ]
        result = json.loads(orcaops_optimize_job("python:3.11", "pytest"))
        assert result["success"] is True
        assert result["count"] == 1

    @patch("orcaops.mcp_server._auto_optimizer")
    def test_optimize_no_suggestions(self, mock_ao):
        from orcaops.mcp_server import orcaops_optimize_job
        mock_ao.return_value.suggest_optimizations.return_value = []
        result = json.loads(orcaops_optimize_job("python:3.11", "pytest"))
        assert result["success"] is True
        assert result["count"] == 0


class TestDebugJob:
    @patch("orcaops.mcp_server._knowledge_base")
    @patch("orcaops.mcp_server._run_store")
    def test_debug_found(self, mock_rs, mock_kb):
        from orcaops.mcp_server import orcaops_debug_job
        from orcaops.schemas import RunRecord, JobStatus
        from datetime import datetime, timezone
        mock_rs.return_value.get_run.return_value = RunRecord(
            job_id="fail-1", status=JobStatus.FAILED,
            created_at=datetime.now(timezone.utc),
        )
        mock_kb.return_value.analyze_failure.return_value = DebugAnalysis(
            job_id="fail-1",
            summary="Test",
            likely_causes=["broke"],
            suggested_fixes=["fix"],
            next_steps=["check"],
        )
        result = json.loads(orcaops_debug_job("fail-1"))
        assert result["success"] is True
        assert result["job_id"] == "fail-1"

    @patch("orcaops.mcp_server._run_store")
    def test_debug_not_found(self, mock_rs):
        from orcaops.mcp_server import orcaops_debug_job
        mock_rs.return_value.get_run.return_value = None
        result = json.loads(orcaops_debug_job("nope"))
        assert result["success"] is False


class TestListFailurePatterns:
    @patch("orcaops.mcp_server._knowledge_base")
    def test_list_all(self, mock_kb):
        from orcaops.mcp_server import orcaops_list_failure_patterns
        mock_kb.return_value.list_patterns.return_value = [
            FailurePattern(
                pattern_id="test",
                regex_pattern="error",
                category="test",
                title="Test",
                description="desc",
            )
        ]
        result = json.loads(orcaops_list_failure_patterns())
        assert result["success"] is True
        assert result["count"] == 1
