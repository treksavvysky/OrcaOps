# Sprint 03: Observability & Intelligent Run Records

**Goal:** Build comprehensive observability into OrcaOps, enabling AI agents and humans to understand what happened, why it happened, and what to do next. Every job execution becomes a queryable, analyzable data point.

**Duration:** 2 weeks

**Prerequisites:** Sprint 01 complete, Sprint 02 in progress

---

## Phase 1: Enhanced Run Records

### Objectives
- Capture rich context for every job execution
- Enable post-hoc analysis and debugging
- Support AI-friendly structured data

### Tasks

#### 1.1 Extended RunRecord Schema
- [x] Add `triggered_by` field (user, api, mcp, scheduler)
- [x] Add `intent` field (natural language description of purpose)
- [x] Add `parent_job_id` for chained executions
- [x] Add `tags` for categorization and filtering
- [x] Add `metadata` for custom key-value pairs

```python
class RunRecord(BaseModel):
    job_id: str
    status: JobStatus
    triggered_by: str  # "cli", "api", "mcp:claude-code", "scheduler"
    intent: Optional[str]  # "Run pytest for PR #123"
    parent_job_id: Optional[str]
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
    # ... existing fields
```

#### 1.2 Resource Usage Tracking
- [x] Capture CPU time used
- [x] Capture peak memory usage
- [x] Track network I/O (bytes in/out)
- [x] Record disk usage in container
- [x] Calculate estimated cost (based on resource usage)

```python
class ResourceUsage(BaseModel):
    cpu_seconds: float
    memory_peak_mb: int
    network_rx_bytes: int
    network_tx_bytes: int
    disk_usage_mb: int
    estimated_cost_usd: float
```

#### 1.3 Environment Capture
- [x] Record Docker image digest (immutable reference)
- [x] Capture environment variables (sanitized)
- [x] Store mount configurations
- [x] Record network settings
- [x] Save container configuration snapshot

### Deliverables
- Extended `RunRecord` schema
- `ResourceUsage` model
- Environment capture on job start

---

## Phase 2: Structured Logging

### Objectives
- Parse and structure container output
- Detect errors, warnings, and significant events
- Enable log-based querying

### Tasks

#### 2.1 Log Parser Framework
- [x] Create pluggable log parser interface
- [x] Implement JSON log parser (for structured logs)
- [x] Implement common format parsers (Python, Node.js, Go)
- [x] Detect and extract stack traces
- [x] Identify error patterns

```python
class LogEntry(BaseModel):
    timestamp: datetime
    level: str  # DEBUG, INFO, WARN, ERROR, FATAL
    message: str
    source: str  # stdout, stderr
    line_number: int
    parsed_data: Optional[Dict[str, Any]]  # Extracted structured data
```

#### 2.2 Log Analysis
- [x] Count log entries by level
- [x] Extract first error message
- [x] Identify repeated patterns
- [x] Detect hanging/stalled output
- [x] Calculate output rate (lines/second)

#### 2.3 Log Storage
- [x] Store parsed logs in `{job_id}_logs.jsonl`
- [x] Index by timestamp and level
- [x] Support log rotation for long-running jobs
- [x] Compress archived logs

### Deliverables
- Log parser framework
- Parsed log storage
- Log analysis utilities

---

## Phase 3: AI Summaries

### Objectives
- Generate human-readable summaries of job executions
- Provide actionable insights from logs
- Enable conversational debugging

### Tasks

#### 3.1 Summary Generation
- [x] Create summary template for successful jobs
- [x] Create summary template for failed jobs
- [x] Include key metrics and duration
- [x] Highlight significant events
- [x] Suggest next actions

```python
class JobSummary(BaseModel):
    job_id: str
    one_liner: str  # "Tests passed in 45s, 98% coverage"
    status_emoji: str  # "✅", "❌", "⏱️"
    duration_human: str  # "45 seconds"
    key_events: List[str]
    errors: List[str]
    warnings: List[str]
    suggestions: List[str]
    ai_analysis: Optional[str]  # LLM-generated insight
```

#### 3.2 Failure Analysis
- [x] Categorize failure types (build, test, runtime, timeout)
- [x] Extract root cause from logs
- [x] Link to similar past failures
- [x] Suggest remediation steps

#### 3.3 Summary API
- [x] `GET /orcaops/jobs/{job_id}/summary` - Get job summary
- [x] Include summary in MCP tool responses
- [x] CLI: `orcaops jobs summary <job_id>`

### Deliverables
- `JobSummary` model
- Summary generation logic
- Summary endpoints and CLI

---

## Phase 4: Metrics & Analytics

### Objectives
- Track aggregate metrics across jobs
- Identify trends and anomalies
- Enable capacity planning

### Tasks

#### 4.1 Metrics Collection
- [x] Job success/failure rate over time
- [x] Average job duration by image
- [x] Resource usage trends
- [x] Sandbox utilization rates
- [x] Queue depth and wait times

#### 4.2 Metrics Storage
- [x] Create `~/.orcaops/metrics/` directory
- [x] Store daily aggregates in JSON
- [x] Support time-range queries
- [x] Implement retention policy

#### 4.3 Metrics API
- [x] `GET /orcaops/metrics/jobs` - Job statistics
- [x] `GET /orcaops/metrics/resources` - Resource usage
- [x] `GET /orcaops/metrics/sandboxes` - Sandbox statistics
- [x] Support `?from=` and `?to=` parameters

### Deliverables
- Metrics collection system
- Metrics storage
- Analytics API endpoints

---

## Phase 5: Anomaly Detection

### Objectives
- Learn normal patterns for jobs
- Detect deviations automatically
- Alert on significant anomalies

### Tasks

#### 5.1 Baseline Learning
- [x] Track historical duration per image+command
- [x] Calculate mean and standard deviation
- [x] Store baselines in `~/.orcaops/baselines.json`
- [x] Update baselines on successful runs

#### 5.2 Anomaly Detection
- [x] Flag jobs taking >2x normal duration
- [x] Detect unusual resource usage
- [x] Identify new error patterns
- [x] Track flaky jobs (intermittent failures)

```python
class Anomaly(BaseModel):
    job_id: str
    anomaly_type: str  # "duration", "memory", "error_pattern"
    expected: Any
    actual: Any
    severity: str  # "info", "warning", "critical"
    message: str
```

#### 5.3 Anomaly Reporting
- [x] Include anomalies in run records
- [x] API: `GET /orcaops/anomalies` - Recent anomalies
- [x] CLI: `orcaops anomalies` - List anomalies
- [x] MCP tool: `orcaops_check_anomalies`

### Deliverables
- Baseline tracking system
- Anomaly detection logic
- Anomaly reporting endpoints

---

## Phase 6: Query & Search

### Objectives
- Enable powerful querying of run history
- Support natural language search
- Build foundation for AI-driven insights

### Tasks

#### 6.1 Query Language
- [x] Implement filter syntax for runs
  - `status:failed`
  - `image:python*`
  - `duration:>60`
  - `tag:ci`
  - `after:2024-01-01`
- [x] Support compound queries with AND/OR
- [x] Add full-text search on logs

#### 6.2 Query API
- [x] `GET /orcaops/runs?q=<query>` - Search runs
- [x] `GET /orcaops/runs/search` - Advanced search endpoint
- [x] Return facets (counts by status, image, etc.)

#### 6.3 CLI Search
- [x] `orcaops runs search "status:failed image:python*"`
- [x] Interactive search with filters
- [x] Export results to JSON/CSV

### Deliverables
- Query parser
- Search API
- CLI search command

---

## Success Criteria

- [x] Every job captures resource usage
- [x] Logs are parsed and structured
- [x] Summaries are generated for all jobs
- [x] Metrics are queryable via API
- [x] Anomalies are detected and reported
- [x] Search works across all run history
- [x] AI agents can query job history via MCP

---

## Technical Notes

### Resource Tracking
Use Docker stats API:
```python
container.stats(stream=False)
# Returns CPU, memory, network, block I/O
```

### Log Parsing Patterns
Common error patterns to detect:
```python
ERROR_PATTERNS = [
    r"(?i)error[:\s]",
    r"(?i)exception[:\s]",
    r"(?i)failed[:\s]",
    r"(?i)traceback",
    r"exit code [1-9]",
]
```

### Baseline Calculation
```python
# Exponential moving average for baselines
new_baseline = alpha * latest_value + (1 - alpha) * old_baseline
# alpha = 0.1 for slow adaptation, 0.3 for faster
```

---

## Dependencies

- Existing: RunRecord, JobRunner, Run storage from Sprint 01
- New: `statistics` (stdlib), `re` for parsing
- Optional: `sqlite3` for efficient querying at scale
