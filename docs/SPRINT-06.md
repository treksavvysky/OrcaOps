# Sprint 06: AI-Driven Optimization & Self-Improvement

**Goal:** Leverage the rich data collected from job executions to automatically optimize performance, predict issues, and provide intelligent recommendations. Make OrcaOps smarter over time.

**Status: COMPLETE**

**Prerequisites:** Sprint 01-05 complete (especially Sprint 03 observability)

---

## Phase 1: Performance Baseline Engine

### Objectives
- Learn normal performance patterns
- Establish baselines for comparison
- Detect performance regressions automatically

### Tasks

#### 1.1 Baseline Collection
- [x] Create baseline schema (`PerformanceBaseline` in `schemas.py`)
- [x] Define baseline keys (image + command hash)
- [x] Collect samples from successful runs
- [x] Calculate statistical measures (mean, stddev, percentiles, memory)
- [x] Store in `~/.orcaops/baselines.json`

#### 1.2 Baseline Updates
- [x] Update baselines on successful job completion
- [x] Use exponential moving average for smooth updates
- [x] Require minimum samples before establishing baseline
- [x] Track success/failure rates for all completed runs

#### 1.3 Baseline API
- [x] `GET /orcaops/baselines` - List baselines
- [x] `GET /orcaops/baselines/{key}` - Get specific baseline
- [x] `DELETE /orcaops/baselines/{key}` - Reset baseline
- [x] MCP tools: `orcaops_list_baselines`, `orcaops_get_baseline`, `orcaops_delete_baseline`
- [x] CLI: `orcaops baselines`, `orcaops baselines-reset`

---

## Phase 2: Anomaly Detection & Alerting

### Objectives
- Detect significant deviations from baselines
- Classify anomaly severity
- Generate actionable alerts

### Tasks

#### 2.1 Anomaly Detection Engine
- [x] Implement z-score based detection (`AnomalyDetector`)
- [x] Detect duration anomalies (|z|>2 WARNING, |z|>3 CRITICAL)
- [x] Detect memory anomalies (>1.5x WARNING, >2x CRITICAL)
- [x] Detect flaky job patterns (success rate 0.3-0.9 with 10+ samples)
- [x] Detect success rate degradation (<0.8 with 5+ samples)

#### 2.2 Anomaly Classification
- [x] Define anomaly types (`AnomalyType` enum with DURATION, MEMORY, FLAKY, SUCCESS_RATE_DEGRADATION)
- [x] Implement severity classification (`AnomalySeverity`: WARNING, CRITICAL)
- [x] Generate human-readable descriptions
- [x] Support acknowledgment workflow

#### 2.3 Alerting
- [x] Store anomalies in `~/.orcaops/anomalies/YYYY-MM-DD.jsonl` (`AnomalyStore`)
- [x] API: `GET /orcaops/anomalies`, `POST /orcaops/anomalies/{id}/acknowledge`
- [x] MCP tools: `orcaops_list_anomalies`, `orcaops_acknowledge_anomaly`
- [x] CLI: `orcaops optimize anomalies`
- [x] Include anomalies in job summaries (wired into `_run_job`)

---

## Phase 3: Intelligent Recommendations

### Objectives
- Analyze patterns to suggest improvements
- Recommend resource right-sizing
- Suggest image optimizations

### Tasks

#### 3.1 Recommendation Engine
- [x] Create recommendation schema (`Recommendation`, `RecommendationType`, `RecommendationPriority`, `RecommendationStatus`)
- [x] Define recommendation types (PERFORMANCE, COST, RELIABILITY, SECURITY)
- [x] Implement evidence collection

#### 3.2 Performance Recommendations
- [x] Detect bloated images (suggest slim/alpine variants)
- [x] Identify caching opportunities (pip install, npm install in 3+ jobs)
- [x] Recommend timeout adjustments (p99 well below default)

#### 3.3 Resource Recommendations
- [x] Detect low memory usage (suggest smaller containers)
- [x] Low success rate detection (reliability recommendations)

#### 3.4 Recommendations API
- [x] `GET /orcaops/recommendations` - List recommendations
- [x] `POST /orcaops/recommendations/generate` - Generate fresh
- [x] `POST /orcaops/recommendations/{id}/dismiss` - Dismiss
- [x] `POST /orcaops/recommendations/{id}/apply` - Mark as applied
- [x] MCP tools: `orcaops_get_recommendations`, `orcaops_generate_recommendations`
- [x] CLI: `orcaops optimize recommendations`

---

## Phase 4: Predictive Capabilities

### Objectives
- Predict job outcomes before completion
- Estimate resource needs

### Tasks

#### 4.1 Duration Prediction
- [x] Predict job duration (`DurationPredictor`) using p50 or EMA
- [x] Estimate confidence levels (scales with sample count, capped at 0.95)
- [x] Provide prediction range (p50*0.8 to p95)
- [x] Fallback for unknown jobs (300s, confidence 0.05)

#### 4.2 Failure Prediction
- [x] Assess failure risk (`FailurePredictor`) based on historical success rate
- [x] Risk levels: low (<0.2), medium (<0.5), high (>=0.5)
- [x] Factor reporting (low success rate, historical failures)

#### 4.3 Prediction API
- [x] `POST /orcaops/predict` with `JobSpec` body
- [x] MCP tool: `orcaops_predict_job`
- [x] CLI: `orcaops optimize predict`

---

## Phase 5: Auto-Optimization

### Objectives
- Suggest safe optimizations
- Track optimization impact

### Tasks

#### 5.1 Auto-Scaling Timeouts
- [x] Suggest p99*1.5 timeout when < current*0.5 (`AutoOptimizer`)
- [x] Require MIN_SAMPLES=10 before suggesting
- [x] Confidence scaling with sample count

#### 5.2 Resource Right-Sizing
- [x] Suggest memory limits based on peak*1.5 headroom

#### 5.3 Optimization API
- [x] `POST /orcaops/optimize` with `JobSpec` body
- [x] MCP tool: `orcaops_optimize_job`
- [x] CLI: `orcaops optimize suggest`

---

## Phase 6: Knowledge Base & AI Assistant

### Objectives
- Build searchable knowledge base of issues and solutions
- Support pattern-based debugging

### Tasks

#### 6.1 Failure Knowledge Base
- [x] 7 built-in patterns: ModuleNotFoundError, npm errors, OOM, connection refused, permission denied, syntax errors, timeouts
- [x] Pattern matching via regex (`FailureKnowledgeBase.match_patterns`)
- [x] Custom pattern support with persistence (`~/.orcaops/failure_patterns.json`)
- [x] Occurrence tracking

#### 6.2 Solution Recommendations
- [x] Match error logs to known patterns
- [x] Suggest solutions based on pattern matches
- [x] Find similar failed jobs

#### 6.3 AI-Assisted Debugging
- [x] Debug analysis for failed jobs (`FailureKnowledgeBase.analyze_failure`)
- [x] Summary, likely causes, suggested fixes, similar jobs, next steps
- [x] `POST /orcaops/debug/{job_id}` API endpoint
- [x] `GET /orcaops/knowledge-base/patterns` API endpoint
- [x] MCP tools: `orcaops_debug_job`, `orcaops_list_failure_patterns`
- [x] CLI: `orcaops optimize debug`, `orcaops optimize patterns`

---

## Implementation Summary

### New Core Modules
| Module | Purpose |
|--------|---------|
| `anomaly_detector.py` | Z-score anomaly detection + JSONL persistence |
| `recommendation_engine.py` | Pattern-based recommendation generation + JSON persistence |
| `predictor.py` | Duration prediction + failure risk assessment |
| `auto_optimizer.py` | Timeout and memory optimization suggestions |
| `knowledge_base.py` | 7 built-in failure patterns + debug analysis |
| `cli_optimization.py` | CLI for all optimization features |

### New API Endpoints (13)
- Baselines: `GET /baselines`, `GET /baselines/{key}`, `DELETE /baselines/{key}`
- Anomalies: `GET /anomalies`, `POST /anomalies/{id}/acknowledge`
- Recommendations: `GET /recommendations`, `POST /recommendations/generate`, `POST /recommendations/{id}/dismiss`, `POST /recommendations/{id}/apply`
- Predictions: `POST /predict`
- Optimization: `POST /optimize`, `POST /debug/{job_id}`, `GET /knowledge-base/patterns`

### New MCP Tools (11)
`orcaops_list_baselines`, `orcaops_get_baseline`, `orcaops_delete_baseline`, `orcaops_list_anomalies`, `orcaops_acknowledge_anomaly`, `orcaops_get_recommendations`, `orcaops_generate_recommendations`, `orcaops_predict_job`, `orcaops_optimize_job`, `orcaops_debug_job`, `orcaops_list_failure_patterns`

### New CLI Commands
- `orcaops baselines [--key FILTER]`
- `orcaops baselines-reset <key>`
- `orcaops optimize suggest <image> <commands>`
- `orcaops optimize predict <image> <commands>`
- `orcaops optimize debug <job_id>`
- `orcaops optimize anomalies [--type] [--severity]`
- `orcaops optimize recommendations [--type]`
- `orcaops optimize patterns [--category]`

### Key Architectural Decisions
1. **No numpy/scikit-learn** — stdlib `statistics` module (mean, stdev, quantiles)
2. **Backward compatible baselines** — Old entries auto-migrated on load
3. **BaselineTracker as constructor param** — Dependency injection for JobManager
4. **JSONL for anomalies** — Date-partitioned, same pattern as audit.py
5. **JSON files for recommendations** — Individual files per recommendation
6. **7 built-in failure patterns** — Ship with OrcaOps, custom patterns addable
7. **Best-effort detection** — Never blocks job execution

### Persistence
- `~/.orcaops/baselines.json` — Enhanced baselines (percentiles, memory, success rate)
- `~/.orcaops/anomalies/YYYY-MM-DD.jsonl` — Date-partitioned anomaly records
- `~/.orcaops/recommendations/{id}.json` — Individual recommendation files
- `~/.orcaops/failure_patterns.json` — Custom failure patterns
