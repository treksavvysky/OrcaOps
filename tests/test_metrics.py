"""Tests for MetricsAggregator on-the-fly metrics computation."""

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from orcaops.metrics import MetricsAggregator
from orcaops.schemas import RunRecord, JobStatus
from orcaops.run_store import RunStore


def _record(job_id, status=JobStatus.SUCCESS, image="python:3.11", duration_secs=30.0,
            created_at=None):
    now = created_at or datetime.now(timezone.utc)
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=now,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
    )


def _mock_store(records):
    store = MagicMock(spec=RunStore)
    store.list_runs.return_value = (records, len(records))
    return store


class TestMetricsEmpty:
    def test_empty_store(self):
        agg = MetricsAggregator(_mock_store([]))
        m = agg.compute_metrics()
        assert m["total_runs"] == 0
        assert m["success_rate"] == 0.0
        assert m["by_image"] == {}


class TestMetricsCounts:
    def test_basic_counts(self):
        records = [
            _record("j1", JobStatus.SUCCESS),
            _record("j2", JobStatus.SUCCESS),
            _record("j3", JobStatus.SUCCESS),
            _record("j4", JobStatus.FAILED),
            _record("j5", JobStatus.FAILED),
        ]
        agg = MetricsAggregator(_mock_store(records))
        m = agg.compute_metrics()
        assert m["total_runs"] == 5
        assert m["success_count"] == 3
        assert m["failed_count"] == 2
        assert m["timed_out_count"] == 0
        assert m["success_rate"] == 0.6

    def test_all_statuses(self):
        records = [
            _record("j1", JobStatus.SUCCESS),
            _record("j2", JobStatus.FAILED),
            _record("j3", JobStatus.TIMED_OUT),
            _record("j4", JobStatus.CANCELLED),
        ]
        agg = MetricsAggregator(_mock_store(records))
        m = agg.compute_metrics()
        assert m["total_runs"] == 4
        assert m["timed_out_count"] == 1
        assert m["cancelled_count"] == 1


class TestMetricsByImage:
    def test_by_image_breakdown(self):
        records = [
            _record("j1", JobStatus.SUCCESS, image="python:3.11", duration_secs=10),
            _record("j2", JobStatus.SUCCESS, image="python:3.11", duration_secs=20),
            _record("j3", JobStatus.FAILED, image="node:18"),
            _record("j4", JobStatus.SUCCESS, image="node:18", duration_secs=40),
        ]
        agg = MetricsAggregator(_mock_store(records))
        m = agg.compute_metrics()
        assert "python:3.11" in m["by_image"]
        assert m["by_image"]["python:3.11"]["count"] == 2
        assert m["by_image"]["python:3.11"]["success"] == 2
        assert m["by_image"]["node:18"]["count"] == 2
        assert m["by_image"]["node:18"]["failed"] == 1


class TestMetricsDateFilter:
    def test_date_range(self):
        now = datetime.now(timezone.utc)
        records = [
            _record("j1", created_at=now - timedelta(days=10)),
            _record("j2", created_at=now - timedelta(days=5)),
            _record("j3", created_at=now - timedelta(days=1)),
        ]
        agg = MetricsAggregator(_mock_store(records))
        m = agg.compute_metrics(from_date=now - timedelta(days=7))
        assert m["total_runs"] == 2


class TestMetricsDuration:
    def test_avg_duration(self):
        records = [
            _record("j1", duration_secs=10),
            _record("j2", duration_secs=20),
            _record("j3", duration_secs=30),
        ]
        agg = MetricsAggregator(_mock_store(records))
        m = agg.compute_metrics()
        assert m["avg_duration_seconds"] == 20.0
        assert m["total_duration_seconds"] == 60.0
