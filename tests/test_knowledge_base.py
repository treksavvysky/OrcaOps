"""Tests for the failure knowledge base."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from orcaops.knowledge_base import FailureKnowledgeBase, BUILTIN_PATTERNS
from orcaops.schemas import (
    DebugAnalysis,
    FailurePattern,
    JobStatus,
    RunRecord,
    StepResult,
)


def _make_failed_record(error="", steps_stderr="", **overrides):
    now = datetime.now(timezone.utc)
    steps = [
        StepResult(
            command="pytest",
            exit_code=1,
            stdout="",
            stderr=steps_stderr,
            duration_seconds=5.0,
        ),
    ]
    defaults = dict(
        job_id="fail-job-1",
        status=JobStatus.FAILED,
        created_at=now,
        started_at=now,
        finished_at=now + timedelta(seconds=5),
        image_ref="python:3.11",
        steps=steps,
        error=error,
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


# ===================================================================
# Builtin pattern matching
# ===================================================================


class TestBuiltinPatterns:
    def test_has_7_builtin_patterns(self):
        assert len(BUILTIN_PATTERNS) == 7

    def test_match_module_not_found(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("ModuleNotFoundError: No module named 'flask'")
        ids = [m.pattern_id for m in matches]
        assert "builtin_module_not_found" in ids

    def test_match_oom(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("Container was OOMKilled")
        ids = [m.pattern_id for m in matches]
        assert "builtin_oom" in ids

    def test_match_connection_refused(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("ConnectionRefusedError: [Errno 111] Connection refused")
        ids = [m.pattern_id for m in matches]
        assert "builtin_connection_refused" in ids

    def test_match_permission_denied(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("PermissionError: [Errno 13] Permission denied")
        ids = [m.pattern_id for m in matches]
        assert "builtin_permission_denied" in ids

    def test_match_syntax_error(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("SyntaxError: invalid syntax")
        ids = [m.pattern_id for m in matches]
        assert "builtin_syntax_error" in ids

    def test_match_timeout(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("TimeoutError: operation timed out")
        ids = [m.pattern_id for m in matches]
        assert "builtin_timeout" in ids

    def test_no_match(self):
        kb = FailureKnowledgeBase()
        matches = kb.match_patterns("Everything is fine!")
        assert len(matches) == 0


# ===================================================================
# Debug analysis
# ===================================================================


class TestDebugAnalysis:
    def test_analysis_with_pattern_match(self):
        kb = FailureKnowledgeBase()
        record = _make_failed_record(
            steps_stderr="ModuleNotFoundError: No module named 'flask'",
        )
        analysis = kb.analyze_failure(record)
        assert isinstance(analysis, DebugAnalysis)
        assert len(analysis.matched_patterns) > 0
        assert len(analysis.suggested_fixes) > 0
        assert "flask" in analysis.summary.lower() or "module" in analysis.summary.lower()

    def test_analysis_no_match(self):
        kb = FailureKnowledgeBase()
        record = _make_failed_record(steps_stderr="Unknown error occurred")
        analysis = kb.analyze_failure(record)
        assert len(analysis.matched_patterns) == 0
        assert len(analysis.next_steps) > 0

    def test_analysis_timed_out(self):
        kb = FailureKnowledgeBase()
        record = _make_failed_record(
            status=JobStatus.TIMED_OUT,
            error="Job timed out after 3600s",
        )
        analysis = kb.analyze_failure(record)
        assert any("time limit" in c.lower() for c in analysis.likely_causes)

    def test_analysis_with_similar_jobs(self):
        kb = FailureKnowledgeBase()
        record = _make_failed_record()
        mock_store = MagicMock()
        similar = RunRecord(
            job_id="similar-1",
            status=JobStatus.FAILED,
            created_at=datetime.now(timezone.utc),
            image_ref="python:3.11",
        )
        mock_store.list_runs.return_value = ([similar], 1)
        analysis = kb.analyze_failure(record, run_store=mock_store)
        assert "similar-1" in analysis.similar_job_ids


# ===================================================================
# Custom patterns
# ===================================================================


class TestCustomPatterns:
    def test_add_custom_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "patterns.json")
            kb = FailureKnowledgeBase(custom_patterns_path=path)
            custom = FailurePattern(
                pattern_id="custom_redis_error",
                regex_pattern=r"RedisConnectionError",
                category="network",
                title="Redis connection error",
                description="Cannot connect to Redis.",
                solutions=["Check Redis is running."],
            )
            kb.add_pattern(custom)
            matches = kb.match_patterns("RedisConnectionError: Connection refused")
            ids = [m.pattern_id for m in matches]
            assert "custom_redis_error" in ids

    def test_custom_pattern_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "patterns.json")
            kb = FailureKnowledgeBase(custom_patterns_path=path)
            custom = FailurePattern(
                pattern_id="custom_test",
                regex_pattern=r"CustomError",
                category="custom",
                title="Custom error",
                description="A custom error.",
                solutions=["Fix it."],
            )
            kb.add_pattern(custom)

            # Reload
            kb2 = FailureKnowledgeBase(custom_patterns_path=path)
            matches = kb2.match_patterns("CustomError occurred")
            ids = [m.pattern_id for m in matches]
            assert "custom_test" in ids


# ===================================================================
# Pattern listing & occurrence tracking
# ===================================================================


class TestPatternListing:
    def test_list_all_patterns(self):
        kb = FailureKnowledgeBase()
        patterns = kb.list_patterns()
        assert len(patterns) >= 7

    def test_list_by_category(self):
        kb = FailureKnowledgeBase()
        patterns = kb.list_patterns(category="dependency")
        assert all(p.category == "dependency" for p in patterns)
        assert len(patterns) >= 2  # Python + npm


class TestOccurrenceTracking:
    def test_record_occurrence(self):
        kb = FailureKnowledgeBase()
        original = [p for p in kb.list_patterns() if p.pattern_id == "builtin_oom"][0]
        original_count = original.occurrences
        kb.record_occurrence("builtin_oom")
        updated = [p for p in kb.list_patterns() if p.pattern_id == "builtin_oom"][0]
        assert updated.occurrences == original_count + 1
        assert updated.last_seen is not None

    def test_record_occurrence_not_found(self):
        kb = FailureKnowledgeBase()
        assert kb.record_occurrence("nonexistent") is False
