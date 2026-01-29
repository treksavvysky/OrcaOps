# Sprint 06: AI-Driven Optimization & Self-Improvement

**Goal:** Leverage the rich data collected from job executions to automatically optimize performance, predict issues, and provide intelligent recommendations. Make OrcaOps smarter over time.

**Duration:** 3 weeks

**Prerequisites:** Sprint 01-05 complete (especially Sprint 03 observability)

---

## Phase 1: Performance Baseline Engine

### Objectives
- Learn normal performance patterns
- Establish baselines for comparison
- Detect performance regressions automatically

### Tasks

#### 1.1 Baseline Collection
```python
class PerformanceBaseline(BaseModel):
    key: str  # "image:python:3.11|command:pytest"
    sample_count: int
    duration_mean: float
    duration_stddev: float
    duration_p50: float
    duration_p95: float
    duration_p99: float
    memory_mean_mb: int
    memory_max_mb: int
    success_rate: float
    last_updated: datetime
```

- [ ] Create baseline schema
- [ ] Define baseline keys (image + command hash)
- [ ] Collect samples from successful runs
- [ ] Calculate statistical measures
- [ ] Store in `~/.orcaops/baselines.json`

#### 1.2 Baseline Updates
- [ ] Update baselines on successful job completion
- [ ] Use exponential moving average for smooth updates
- [ ] Require minimum samples before establishing baseline
- [ ] Age out stale baselines

```python
def update_baseline(baseline: PerformanceBaseline, new_sample: JobMetrics):
    alpha = 0.1  # Learning rate
    baseline.duration_mean = alpha * new_sample.duration + (1 - alpha) * baseline.duration_mean
    baseline.sample_count += 1
    baseline.last_updated = datetime.now()
```

#### 1.3 Baseline API
- [ ] `GET /orcaops/baselines` - List baselines
- [ ] `GET /orcaops/baselines/{key}` - Get specific baseline
- [ ] `DELETE /orcaops/baselines/{key}` - Reset baseline

### Deliverables
- Baseline collection system
- Statistical calculation
- Baseline management API

---

## Phase 2: Anomaly Detection & Alerting

### Objectives
- Detect significant deviations from baselines
- Classify anomaly severity
- Generate actionable alerts

### Tasks

#### 2.1 Anomaly Detection Engine
```python
class AnomalyDetector:
    def detect(self, job: RunRecord, baseline: PerformanceBaseline) -> List[Anomaly]:
        anomalies = []

        # Duration anomaly
        z_score = (job.duration - baseline.duration_mean) / baseline.duration_stddev
        if abs(z_score) > 2:
            anomalies.append(Anomaly(
                type="duration",
                severity="warning" if abs(z_score) < 3 else "critical",
                expected=baseline.duration_mean,
                actual=job.duration,
                deviation_percent=((job.duration - baseline.duration_mean) / baseline.duration_mean) * 100
            ))

        # Memory anomaly
        if job.memory_peak > baseline.memory_max_mb * 1.5:
            anomalies.append(Anomaly(type="memory", ...))

        return anomalies
```

- [ ] Implement z-score based detection
- [ ] Detect duration anomalies
- [ ] Detect memory anomalies
- [ ] Detect error pattern anomalies
- [ ] Detect flaky job patterns

#### 2.2 Anomaly Classification
```python
class Anomaly(BaseModel):
    id: str
    job_id: str
    type: str  # "duration", "memory", "error", "flaky"
    severity: str  # "info", "warning", "critical"
    title: str
    description: str
    expected: Any
    actual: Any
    deviation_percent: float
    detected_at: datetime
    acknowledged: bool = False
    resolution: Optional[str]
```

- [ ] Define anomaly types
- [ ] Implement severity classification
- [ ] Generate human-readable descriptions
- [ ] Support acknowledgment workflow

#### 2.3 Alerting
- [ ] Store anomalies in `~/.orcaops/anomalies/`
- [ ] API: `GET /orcaops/anomalies` - List anomalies
- [ ] MCP tool: `orcaops_get_anomalies`
- [ ] Include anomalies in job summaries

### Deliverables
- Anomaly detection engine
- Anomaly classification
- Alert management

---

## Phase 3: Intelligent Recommendations

### Objectives
- Analyze patterns to suggest improvements
- Recommend resource right-sizing
- Suggest image optimizations

### Tasks

#### 3.1 Recommendation Engine
```python
class Recommendation(BaseModel):
    id: str
    type: str  # "performance", "cost", "reliability", "security"
    priority: str  # "low", "medium", "high"
    title: str
    description: str
    impact: str  # "Could reduce build time by 30%"
    action: str  # What to do
    evidence: Dict[str, Any]  # Data supporting recommendation
    created_at: datetime
```

- [ ] Create recommendation schema
- [ ] Define recommendation types
- [ ] Implement evidence collection

#### 3.2 Performance Recommendations
```python
def analyze_for_recommendations(jobs: List[RunRecord]) -> List[Recommendation]:
    recommendations = []

    # Image optimization
    if using_large_base_images(jobs):
        recommendations.append(Recommendation(
            type="performance",
            title="Consider using slim base images",
            description="Jobs using python:3.11 take 45s longer than python:3.11-slim on average",
            impact="Could reduce job time by 30%",
            action="Switch from python:3.11 to python:3.11-slim"
        ))

    # Caching opportunity
    if repeated_install_steps(jobs):
        recommendations.append(Recommendation(
            type="performance",
            title="Add dependency caching",
            description="pip install runs in 80% of jobs, taking 60s each time",
            impact="Could save 48 minutes per day",
            action="Use a cached base image with dependencies pre-installed"
        ))

    return recommendations
```

- [ ] Detect slow images with faster alternatives
- [ ] Identify caching opportunities
- [ ] Suggest parallel execution opportunities
- [ ] Recommend timeout adjustments

#### 3.3 Resource Recommendations
- [ ] Detect over-provisioned jobs (using <50% of memory)
- [ ] Detect under-provisioned jobs (OOM or near-limit)
- [ ] Suggest CPU limit adjustments
- [ ] Identify idle sandbox cleanup opportunities

#### 3.4 Recommendations API
- [ ] `GET /orcaops/recommendations` - Get recommendations
- [ ] `POST /orcaops/recommendations/{id}/dismiss` - Dismiss
- [ ] `POST /orcaops/recommendations/{id}/apply` - Mark as applied
- [ ] MCP tool: `orcaops_get_recommendations`

### Deliverables
- Recommendation engine
- Pattern analysis
- Recommendation API

---

## Phase 4: Predictive Capabilities

### Objectives
- Predict job outcomes before completion
- Estimate resource needs
- Forecast capacity requirements

### Tasks

#### 4.1 Duration Prediction
```python
class DurationPredictor:
    def predict(self, job_spec: JobSpec) -> DurationPrediction:
        """Predict job duration based on historical data"""
        baseline = self.get_baseline(job_spec)
        if baseline:
            return DurationPrediction(
                estimated_seconds=baseline.duration_mean,
                confidence=min(baseline.sample_count / 100, 0.95),
                range_low=baseline.duration_p50 * 0.8,
                range_high=baseline.duration_p95
            )
        return DurationPrediction(estimated_seconds=300, confidence=0.1)
```

- [ ] Predict job duration
- [ ] Predict memory requirements
- [ ] Estimate confidence levels
- [ ] Improve predictions over time

#### 4.2 Failure Prediction
- [ ] Track failure patterns by time of day
- [ ] Identify flaky test patterns
- [ ] Detect degrading success rates
- [ ] Alert on increasing failure probability

```python
def predict_failure_risk(job_spec: JobSpec) -> float:
    """Return probability of failure (0.0 - 1.0)"""
    baseline = get_baseline(job_spec)
    if baseline.success_rate < 0.95:
        return 1.0 - baseline.success_rate
    return 0.05  # Default low risk
```

#### 4.3 Capacity Forecasting
- [ ] Analyze job submission patterns
- [ ] Predict peak usage times
- [ ] Recommend capacity adjustments
- [ ] Estimate cost projections

### Deliverables
- Duration predictor
- Failure risk assessment
- Capacity forecasting

---

## Phase 5: Auto-Optimization

### Objectives
- Automatically apply safe optimizations
- Require approval for significant changes
- Track optimization impact

### Tasks

#### 5.1 Auto-Scaling Timeouts
```python
class AutoOptimizer:
    def optimize_timeout(self, job_spec: JobSpec) -> Optional[int]:
        """Suggest optimized timeout based on history"""
        baseline = self.get_baseline(job_spec)
        if baseline and baseline.sample_count > 10:
            # Set timeout to p99 + 50% buffer
            suggested = int(baseline.duration_p99 * 1.5)
            if suggested < job_spec.timeout * 0.5:
                return suggested
        return None
```

- [ ] Auto-adjust timeouts based on history
- [ ] Require minimum samples before optimization
- [ ] Log all auto-optimizations

#### 5.2 Resource Right-Sizing
- [ ] Adjust memory limits based on actual usage
- [ ] Adjust CPU limits based on utilization
- [ ] Apply gradually with monitoring
- [ ] Rollback on degradation

#### 5.3 Pre-warming
- [ ] Predict upcoming job submissions
- [ ] Pre-pull commonly used images
- [ ] Pre-create sandbox containers
- [ ] Reduce cold-start times

### Deliverables
- Auto-timeout optimization
- Resource right-sizing
- Pre-warming system

---

## Phase 6: Knowledge Base & AI Assistant

### Objectives
- Build searchable knowledge base of issues and solutions
- Enable natural language queries
- Support conversational debugging

### Tasks

#### 6.1 Failure Knowledge Base
```python
class FailurePattern(BaseModel):
    id: str
    pattern: str  # Regex or signature
    category: str  # "dependency", "timeout", "oom", "network"
    title: str
    description: str
    solutions: List[str]
    occurrences: int
    last_seen: datetime
```

- [ ] Extract failure patterns from logs
- [ ] Categorize common failures
- [ ] Store solutions and workarounds
- [ ] Link to similar past failures

#### 6.2 Solution Recommendations
```python
def find_solutions(error_log: str) -> List[Solution]:
    """Find solutions for error patterns in log"""
    patterns = match_known_patterns(error_log)
    solutions = []
    for pattern in patterns:
        solutions.extend(pattern.solutions)
    return deduplicate_solutions(solutions)
```

- [ ] Match error logs to known patterns
- [ ] Suggest solutions based on history
- [ ] Track solution effectiveness
- [ ] Learn from user feedback

#### 6.3 AI-Assisted Debugging
- [ ] MCP tool: `orcaops_debug_job` - Analyze failed job
- [ ] Provide step-by-step debugging guidance
- [ ] Suggest log sections to examine
- [ ] Recommend next troubleshooting steps

```python
@mcp_tool
async def orcaops_debug_job(job_id: str) -> DebugAnalysis:
    """Analyze a failed job and provide debugging guidance"""
    job = await get_job(job_id)
    analysis = await analyze_failure(job)
    return DebugAnalysis(
        summary=analysis.summary,
        likely_causes=analysis.causes,
        suggested_fixes=analysis.fixes,
        similar_past_failures=analysis.similar_jobs,
        next_steps=analysis.debugging_steps
    )
```

### Deliverables
- Failure pattern database
- Solution recommendation engine
- AI debugging assistant

---

## Success Criteria

- [ ] Baselines established for common job types
- [ ] Anomalies detected and reported
- [ ] Recommendations generated automatically
- [ ] Duration predictions within 20% accuracy
- [ ] Auto-optimizations applied safely
- [ ] Knowledge base grows with usage
- [ ] AI can assist with debugging via MCP

---

## Technical Notes

### Statistical Methods
```python
# Z-score for anomaly detection
z_score = (value - mean) / std_dev
# |z| > 2: Warning
# |z| > 3: Critical

# Exponential Moving Average for baselines
new_ema = alpha * new_value + (1 - alpha) * old_ema
# alpha = 0.1 for slow learning
# alpha = 0.3 for faster adaptation

# Percentile calculation
import numpy as np
p50, p95, p99 = np.percentile(values, [50, 95, 99])
```

### Pattern Matching for Failures
```python
FAILURE_PATTERNS = {
    r"ModuleNotFoundError: No module named '(\w+)'": {
        "category": "dependency",
        "solution": "Install missing module: pip install {1}"
    },
    r"Cannot connect to (\w+) on port (\d+)": {
        "category": "network",
        "solution": "Check if service {1} is running and accessible on port {2}"
    },
    r"MemoryError|Killed|OOMKilled": {
        "category": "oom",
        "solution": "Increase memory limit or optimize memory usage"
    }
}
```

### Recommendation Prioritization
```python
def prioritize_recommendations(recs: List[Recommendation]) -> List[Recommendation]:
    # Score by impact * frequency * ease of implementation
    for rec in recs:
        rec.score = rec.impact_score * rec.frequency * rec.ease_score
    return sorted(recs, key=lambda r: r.score, reverse=True)
```

---

## Dependencies

- Existing: All previous sprints, especially observability
- New: `numpy` for statistical calculations
- New: `scikit-learn` (optional) for ML-based predictions
- Consideration: Vector DB for semantic search (future)

---

## Future Enhancements

After Sprint 06, consider:

1. **LLM-Powered Analysis** - Use Claude/GPT for deeper log analysis
2. **Semantic Search** - Find similar jobs by embedding similarity
3. **Automated Remediation** - Auto-fix known issues
4. **Cross-Workspace Learning** - Share patterns (anonymized) across users
5. **CI/CD Integration** - Native GitHub Actions, GitLab CI support
6. **Dashboard UI** - Web interface for visualization
