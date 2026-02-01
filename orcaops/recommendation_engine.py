"""
Recommendation engine for OrcaOps.

Analyzes job history and baselines to generate actionable recommendations
for performance, cost, reliability, and security improvements.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from orcaops.metrics import BaselineTracker
from orcaops.run_store import RunStore
from orcaops.schemas import (
    PerformanceBaseline,
    Recommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
    RunRecord,
)

# Images that should suggest slim/alpine variants
_BLOATED_IMAGE_RE = re.compile(
    r"^(python:\d+\.\d+|node:\d+|ruby:\d+\.\d+|golang:\d+\.\d+)$"
)

# Commands that indicate cacheable dependency installation
_CACHEABLE_COMMANDS = [
    "pip install",
    "npm install",
    "npm ci",
    "yarn install",
    "apt-get install",
    "apk add",
]


class RecommendationEngine:
    """Generates recommendations by analyzing run history and baselines."""

    def __init__(self, run_store: RunStore, baseline_tracker: BaselineTracker):
        self.run_store = run_store
        self.baseline_tracker = baseline_tracker

    def generate_recommendations(
        self, workspace_id: Optional[str] = None, limit: int = 100,
    ) -> List[Recommendation]:
        recs: List[Recommendation] = []

        records, _ = self.run_store.list_runs(limit=10000)
        if workspace_id:
            records = [r for r in records if r.workspace_id == workspace_id]

        baselines = self.baseline_tracker.list_baselines()

        recs.extend(self._check_image_optimization(records))
        recs.extend(self._check_timeout_optimization(baselines))
        recs.extend(self._check_caching_opportunities(records))
        recs.extend(self._check_resource_right_sizing(records, baselines))
        recs.extend(self._check_reliability(baselines))

        return recs[:limit]

    def _check_image_optimization(self, records: List[RunRecord]) -> List[Recommendation]:
        recs = []
        seen_images = set()
        for r in records:
            img = r.image_ref
            if not img or img in seen_images:
                continue
            seen_images.add(img)
            if _BLOATED_IMAGE_RE.match(img):
                recs.append(Recommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
                    rec_type=RecommendationType.COST,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Use slim/alpine variant for {img}",
                    description=(
                        f"Image '{img}' can be replaced with a slim or alpine variant "
                        f"to reduce pull time and disk usage."
                    ),
                    impact="Reduced image size, faster pull times, lower storage costs.",
                    action=f"Replace '{img}' with '{img}-slim' or '{img}-alpine'.",
                    evidence={"image": img},
                ))
        return recs

    def _check_timeout_optimization(
        self, baselines: List[PerformanceBaseline],
    ) -> List[Recommendation]:
        recs = []
        default_ttl = 3600.0
        for bl in baselines:
            if bl.sample_count < 5:
                continue
            if bl.duration_p99 > 0 and bl.duration_p99 < default_ttl * 0.3:
                suggested = round(bl.duration_p99 * 2, 0)
                recs.append(Recommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
                    rec_type=RecommendationType.PERFORMANCE,
                    priority=RecommendationPriority.LOW,
                    title="Reduce job timeout",
                    description=(
                        f"Jobs with baseline '{bl.key}' have p99 duration of "
                        f"{bl.duration_p99:.1f}s, well below the default {default_ttl:.0f}s timeout."
                    ),
                    impact="Faster failure detection for hung jobs.",
                    action=f"Set ttl_seconds to {suggested:.0f}s (2x p99).",
                    evidence={
                        "baseline_key": bl.key,
                        "p99_seconds": bl.duration_p99,
                        "current_timeout": default_ttl,
                        "suggested_timeout": suggested,
                    },
                ))
        return recs

    def _check_caching_opportunities(
        self, records: List[RunRecord],
    ) -> List[Recommendation]:
        recs = []
        cmd_counts: Dict[str, int] = {}
        for r in records:
            for step in r.steps:
                for cacheable in _CACHEABLE_COMMANDS:
                    if cacheable in step.command:
                        cmd_counts[cacheable] = cmd_counts.get(cacheable, 0) + 1
                        break

        for cmd, count in cmd_counts.items():
            if count >= 3:
                recs.append(Recommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
                    rec_type=RecommendationType.PERFORMANCE,
                    priority=RecommendationPriority.HIGH,
                    title=f"Cache '{cmd}' dependencies",
                    description=(
                        f"Command '{cmd}' appears in {count} job runs. "
                        f"Pre-building dependencies into the image or using a cache volume "
                        f"would reduce execution time."
                    ),
                    impact="Reduced execution time for dependency installation steps.",
                    action=f"Create a custom image with pre-installed dependencies or mount a cache volume.",
                    evidence={"command": cmd, "occurrences": count},
                ))
        return recs

    def _check_resource_right_sizing(
        self,
        records: List[RunRecord],
        baselines: List[PerformanceBaseline],
    ) -> List[Recommendation]:
        recs = []
        for bl in baselines:
            if bl.sample_count < 5:
                continue
            if bl.memory_max_mb > 0 and bl.memory_max_mb < 50:
                recs.append(Recommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
                    rec_type=RecommendationType.COST,
                    priority=RecommendationPriority.LOW,
                    title="Low memory usage detected",
                    description=(
                        f"Baseline '{bl.key}' peak memory is only {bl.memory_max_mb:.0f}MB. "
                        f"Consider using smaller container resources."
                    ),
                    impact="Cost savings from smaller container allocation.",
                    action="Use a memory-constrained container profile.",
                    evidence={
                        "baseline_key": bl.key,
                        "memory_max_mb": bl.memory_max_mb,
                    },
                ))
        return recs

    def _check_reliability(
        self, baselines: List[PerformanceBaseline],
    ) -> List[Recommendation]:
        recs = []
        for bl in baselines:
            total = bl.success_count + bl.failure_count
            if total < 10:
                continue
            if bl.success_rate < 0.9:
                recs.append(Recommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
                    rec_type=RecommendationType.RELIABILITY,
                    priority=RecommendationPriority.HIGH,
                    title="Low success rate",
                    description=(
                        f"Baseline '{bl.key}' has a {bl.success_rate * 100:.0f}% success rate "
                        f"over {total} runs. Investigation is recommended."
                    ),
                    impact="Improved reliability and developer confidence.",
                    action="Review recent failures, check for flaky dependencies or environment issues.",
                    evidence={
                        "baseline_key": bl.key,
                        "success_rate": bl.success_rate,
                        "total_runs": total,
                        "failure_count": bl.failure_count,
                    },
                ))
        return recs


class RecommendationStore:
    """JSON file-based recommendation persistence."""

    def __init__(self, recommendations_dir: Optional[str] = None):
        self.recommendations_dir = recommendations_dir or os.path.expanduser(
            "~/.orcaops/recommendations"
        )
        self._lock = threading.Lock()

    def save(self, rec: Recommendation) -> None:
        with self._lock:
            os.makedirs(self.recommendations_dir, exist_ok=True)
            path = os.path.join(self.recommendations_dir, f"{rec.recommendation_id}.json")
            with open(path, "w") as f:
                f.write(rec.model_dump_json(indent=2))

    def list_recommendations(
        self,
        rec_type: Optional[RecommendationType] = None,
        status: Optional[RecommendationStatus] = None,
        limit: int = 100,
    ) -> List[Recommendation]:
        recs = self._scan_all()
        if rec_type:
            recs = [r for r in recs if r.rec_type == rec_type]
        if status:
            recs = [r for r in recs if r.status == status]
        recs.sort(key=lambda r: r.created_at, reverse=True)
        return recs[:limit]

    def get(self, recommendation_id: str) -> Optional[Recommendation]:
        path = os.path.join(self.recommendations_dir, f"{recommendation_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r") as f:
                return Recommendation.model_validate_json(f.read())
        except Exception:
            return None

    def dismiss(self, recommendation_id: str) -> bool:
        return self._update_status(recommendation_id, RecommendationStatus.DISMISSED)

    def mark_applied(self, recommendation_id: str) -> bool:
        return self._update_status(recommendation_id, RecommendationStatus.APPLIED)

    def _update_status(self, recommendation_id: str, new_status: RecommendationStatus) -> bool:
        with self._lock:
            path = os.path.join(self.recommendations_dir, f"{recommendation_id}.json")
            if not os.path.isfile(path):
                return False
            try:
                with open(path, "r") as f:
                    rec = Recommendation.model_validate_json(f.read())
                rec.status = new_status
                with open(path, "w") as f:
                    f.write(rec.model_dump_json(indent=2))
                return True
            except Exception:
                return False

    def _scan_all(self) -> List[Recommendation]:
        recs: List[Recommendation] = []
        if not os.path.isdir(self.recommendations_dir):
            return recs
        for fname in os.listdir(self.recommendations_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self.recommendations_dir, fname)
            try:
                with open(path, "r") as f:
                    recs.append(Recommendation.model_validate_json(f.read()))
            except Exception:
                continue
        return recs
