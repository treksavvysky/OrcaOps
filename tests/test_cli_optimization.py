"""Tests for optimization CLI commands."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from typer.testing import CliRunner

from orcaops.schemas import (
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
    DebugAnalysis,
    FailurePattern,
    JobStatus,
    OptimizationSuggestion,
    PerformanceBaseline,
    Recommendation,
    RecommendationPriority,
    RecommendationType,
    RunRecord,
)


runner = CliRunner()


def _get_app():
    from orcaops.cli_enhanced import app
    from orcaops.cli_optimization import OptimizationCLI
    OptimizationCLI.add_commands(app)
    return app


class TestSuggestCommand:
    @patch("orcaops.cli_optimization._get_baseline_tracker")
    def test_suggest_with_results(self, mock_bt):
        mock_bt.return_value.get_baseline_for_spec.return_value = PerformanceBaseline(
            key="python:3.11::pytest",
            sample_count=20,
            duration_p99=20.0,
            memory_max_mb=200.0,
        )
        app = _get_app()
        result = runner.invoke(app, ["optimize", "suggest", "python:3.11", "pytest"])
        assert result.exit_code == 0

    @patch("orcaops.cli_optimization._get_baseline_tracker")
    def test_suggest_no_results(self, mock_bt):
        mock_bt.return_value.get_baseline_for_spec.return_value = None
        app = _get_app()
        result = runner.invoke(app, ["optimize", "suggest", "python:3.11", "pytest"])
        assert result.exit_code == 0
        assert "No optimization" in result.output


class TestPredictCommand:
    @patch("orcaops.cli_optimization._get_baseline_tracker")
    def test_predict(self, mock_bt):
        mock_bt.return_value.get_baseline_for_spec.return_value = PerformanceBaseline(
            key="python:3.11::pytest",
            sample_count=20,
            duration_ema=15.0,
            duration_p50=14.5,
            duration_p95=18.0,
            success_rate=0.9,
            success_count=18,
            failure_count=2,
        )
        app = _get_app()
        result = runner.invoke(app, ["optimize", "predict", "python:3.11", "pytest"])
        assert result.exit_code == 0
        assert "Duration" in result.output

    @patch("orcaops.cli_optimization._get_baseline_tracker")
    def test_predict_no_baseline(self, mock_bt):
        mock_bt.return_value.get_baseline_for_spec.return_value = None
        app = _get_app()
        result = runner.invoke(app, ["optimize", "predict", "python:3.11", "pytest"])
        assert result.exit_code == 0


class TestDebugCommand:
    @patch("orcaops.cli_optimization._get_run_store")
    def test_debug_found(self, mock_rs):
        mock_rs.return_value.get_run.return_value = RunRecord(
            job_id="fail-1",
            status=JobStatus.FAILED,
            created_at=datetime.now(timezone.utc),
            error="ModuleNotFoundError: No module named 'flask'",
        )
        mock_rs.return_value.list_runs.return_value = ([], 0)
        app = _get_app()
        result = runner.invoke(app, ["optimize", "debug", "fail-1"])
        assert result.exit_code == 0

    @patch("orcaops.cli_optimization._get_run_store")
    def test_debug_not_found(self, mock_rs):
        mock_rs.return_value.get_run.return_value = None
        app = _get_app()
        result = runner.invoke(app, ["optimize", "debug", "nope"])
        assert result.exit_code == 1


class TestAnomaliesCommand:
    @patch("orcaops.anomaly_detector.AnomalyStore")
    def test_anomalies_with_results(self, mock_store_cls):
        mock_store_cls.return_value.query.return_value = (
            [AnomalyRecord(
                anomaly_id="anom_test1",
                job_id="job-1",
                baseline_key="key",
                anomaly_type=AnomalyType.DURATION,
                severity=AnomalySeverity.WARNING,
                title="Test",
                description="desc",
                expected="15s",
                actual="25s",
            )],
            1,
        )
        app = _get_app()
        result = runner.invoke(app, ["optimize", "anomalies"])
        assert result.exit_code == 0

    @patch("orcaops.anomaly_detector.AnomalyStore")
    def test_anomalies_empty(self, mock_store_cls):
        mock_store_cls.return_value.query.return_value = ([], 0)
        app = _get_app()
        result = runner.invoke(app, ["optimize", "anomalies"])
        assert result.exit_code == 0
        assert "No anomalies" in result.output


class TestRecommendationsCommand:
    @patch("orcaops.recommendation_engine.RecommendationStore")
    def test_recommendations_with_results(self, mock_store_cls):
        mock_store_cls.return_value.list_recommendations.return_value = [
            Recommendation(
                recommendation_id="rec_test1",
                rec_type=RecommendationType.PERFORMANCE,
                priority=RecommendationPriority.HIGH,
                title="Test rec",
                description="desc",
                impact="impact",
                action="do something",
            )
        ]
        app = _get_app()
        result = runner.invoke(app, ["optimize", "recommendations"])
        assert result.exit_code == 0

    @patch("orcaops.recommendation_engine.RecommendationStore")
    def test_recommendations_empty(self, mock_store_cls):
        mock_store_cls.return_value.list_recommendations.return_value = []
        app = _get_app()
        result = runner.invoke(app, ["optimize", "recommendations"])
        assert result.exit_code == 0


class TestPatternsCommand:
    def test_patterns_shows_builtins(self):
        app = _get_app()
        result = runner.invoke(app, ["optimize", "patterns"])
        assert result.exit_code == 0
        assert "Failure Patterns" in result.output

    def test_patterns_filter_category(self):
        app = _get_app()
        result = runner.invoke(app, ["optimize", "patterns", "--category", "dependency"])
        assert result.exit_code == 0
