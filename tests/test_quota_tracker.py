"""Tests for quota tracker."""

import threading

import pytest

from orcaops.schemas import ResourceLimits
from orcaops.quota_tracker import QuotaTracker


class TestCheckLimits:
    def test_allows_within_limits(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_jobs=5)
        allowed, reason = tracker.check_limits("ws_test", limits)
        assert allowed is True
        assert reason is None

    def test_denies_at_concurrent_limit(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_jobs=2)

        tracker.on_job_start("ws_test", "job-1")
        tracker.on_job_start("ws_test", "job-2")

        allowed, reason = tracker.check_limits("ws_test", limits)
        assert allowed is False
        assert "Concurrent job limit" in reason

    def test_allows_after_job_end(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_jobs=1)

        tracker.on_job_start("ws_test", "job-1")
        tracker.on_job_end("ws_test", "job-1")

        allowed, reason = tracker.check_limits("ws_test", limits)
        assert allowed is True

    def test_daily_limit(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(daily_job_limit=3)

        for i in range(3):
            tracker.on_job_start("ws_test", f"job-{i}")
            tracker.on_job_end("ws_test", f"job-{i}")

        allowed, reason = tracker.check_limits("ws_test", limits)
        assert allowed is False
        assert "Daily job limit" in reason

    def test_daily_limit_none_means_unlimited(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(daily_job_limit=None)

        for i in range(100):
            tracker.on_job_start("ws_test", f"job-{i}")
            tracker.on_job_end("ws_test", f"job-{i}")

        allowed, reason = tracker.check_limits("ws_test", limits)
        assert allowed is True

    def test_sandbox_limits(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_sandboxes=1)

        tracker.on_sandbox_start("ws_test", "sb-1")
        allowed, reason = tracker.check_limits("ws_test", limits, resource_type="sandbox")
        assert allowed is False
        assert "sandbox limit" in reason

    def test_sandbox_allows_after_end(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_sandboxes=1)

        tracker.on_sandbox_start("ws_test", "sb-1")
        tracker.on_sandbox_end("ws_test", "sb-1")
        allowed, reason = tracker.check_limits("ws_test", limits, resource_type="sandbox")
        assert allowed is True

    def test_workspace_isolation(self):
        tracker = QuotaTracker()
        limits = ResourceLimits(max_concurrent_jobs=1)

        tracker.on_job_start("ws_a", "job-1")

        allowed_a, _ = tracker.check_limits("ws_a", limits)
        allowed_b, _ = tracker.check_limits("ws_b", limits)
        assert allowed_a is False
        assert allowed_b is True


class TestGetUsage:
    def test_empty_usage(self):
        tracker = QuotaTracker()
        usage = tracker.get_usage("ws_test")
        assert usage.workspace_id == "ws_test"
        assert usage.current_running_jobs == 0
        assert usage.current_running_sandboxes == 0
        assert usage.jobs_today == 0

    def test_tracks_running(self):
        tracker = QuotaTracker()
        tracker.on_job_start("ws_test", "job-1")
        tracker.on_job_start("ws_test", "job-2")
        tracker.on_sandbox_start("ws_test", "sb-1")

        usage = tracker.get_usage("ws_test")
        assert usage.current_running_jobs == 2
        assert usage.current_running_sandboxes == 1
        assert usage.jobs_today == 2

    def test_jobs_today_counts_all_started(self):
        tracker = QuotaTracker()
        tracker.on_job_start("ws_test", "job-1")
        tracker.on_job_end("ws_test", "job-1")
        tracker.on_job_start("ws_test", "job-2")
        tracker.on_job_end("ws_test", "job-2")

        usage = tracker.get_usage("ws_test")
        assert usage.current_running_jobs == 0
        assert usage.jobs_today == 2


class TestThreadSafety:
    def test_concurrent_start_end(self):
        tracker = QuotaTracker()
        errors = []

        def start_and_end(ws_id, prefix):
            try:
                for i in range(20):
                    jid = f"{prefix}-{i}"
                    tracker.on_job_start(ws_id, jid)
                    tracker.on_job_end(ws_id, jid)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=start_and_end, args=("ws_test", f"t{i}"))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        usage = tracker.get_usage("ws_test")
        assert usage.current_running_jobs == 0
        assert usage.jobs_today == 100  # 5 threads * 20 jobs each

    def test_on_job_end_nonexistent(self):
        """Ending a job that was never started should not error."""
        tracker = QuotaTracker()
        tracker.on_job_end("ws_test", "nonexistent")
        usage = tracker.get_usage("ws_test")
        assert usage.current_running_jobs == 0
