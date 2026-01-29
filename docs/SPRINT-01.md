# Sprint 01: Foundation & Job Execution API

**Goal:** Expose the existing JobRunner through the REST API, enabling external clients (GPTs, MCP servers, frontends) to submit and monitor jobs programmatically.

**Duration:** 2 weeks

---

## Phase 1: Job API Endpoints

### Objectives
- Create REST endpoints for job submission, status checking, and artifact retrieval
- Ensure jobs run asynchronously with proper status tracking
- Return structured responses suitable for AI consumption

### Tasks

#### 1.1 Job Submission Endpoint
- [ ] `POST /orcaops/jobs` - Submit a new job
  - Accept `JobSpec` as request body
  - Validate image references and commands
  - Return `job_id` and initial status
  - Start job execution in background task

#### 1.2 Job Status Endpoint
- [ ] `GET /orcaops/jobs/{job_id}` - Get job status and details
  - Return current `RunRecord` state
  - Include step results if available
  - Show cleanup status

#### 1.3 Job Listing Endpoint
- [ ] `GET /orcaops/jobs` - List recent jobs
  - Support filtering by status (queued, running, success, failed)
  - Pagination support
  - Sort by created_at descending

#### 1.4 Job Cancellation
- [ ] `POST /orcaops/jobs/{job_id}/cancel` - Cancel a running job
  - Stop container gracefully
  - Update status to cancelled
  - Apply cleanup policy

### Deliverables
- New endpoints in `orcaops/api.py`
- Background task runner for async job execution
- Unit tests for all endpoints

---

## Phase 2: Run Record Persistence

### Objectives
- Persist all job executions to disk for history and debugging
- Enable querying historical runs
- Support both JSON (single record) and JSONL (append log) formats

### Tasks

#### 2.1 Run Record Storage
- [ ] Create `~/.orcaops/runs/` directory structure
- [ ] Save each `RunRecord` as `{job_id}.json`
- [ ] Append to `runs.jsonl` for streaming analysis
- [ ] Include timestamps, duration, resource usage

#### 2.2 Run Record API
- [ ] `GET /orcaops/runs` - List historical runs
- [ ] `GET /orcaops/runs/{job_id}` - Get specific run record
- [ ] `DELETE /orcaops/runs/{job_id}` - Delete run record

#### 2.3 Run Record Cleanup
- [ ] Implement retention policy (default: 30 days)
- [ ] `POST /orcaops/runs/cleanup` - Manual cleanup endpoint
- [ ] CLI command: `orcaops runs cleanup --older-than 7d`

### Deliverables
- `orcaops/run_store.py` - Run record persistence layer
- Updated `JobRunner` to save records automatically
- API endpoints for run history

---

## Phase 3: Artifact Collection

### Objectives
- Extract files from completed containers
- Store artifacts with metadata
- Enable download via API

### Tasks

#### 3.1 Artifact Extraction
- [ ] Implement `docker cp` wrapper in `DockerManager`
- [ ] Support glob patterns for artifact paths
- [ ] Calculate SHA256 checksums
- [ ] Store in `~/.orcaops/artifacts/{job_id}/`

#### 3.2 Artifact API
- [ ] `GET /orcaops/jobs/{job_id}/artifacts` - List artifacts
- [ ] `GET /orcaops/jobs/{job_id}/artifacts/{filename}` - Download artifact
- [ ] Include size, checksum, and content-type in response

#### 3.3 Artifact Metadata
- [ ] Store `ArtifactMetadata` in run record
- [ ] Support artifact retention policies
- [ ] Compress large artifacts (optional gzip)

### Deliverables
- Artifact extraction in `JobRunner`
- Download endpoints in API
- Artifact metadata in run records

---

## Phase 4: Live Log Streaming

### Objectives
- Stream container logs to clients in real-time
- Support both WebSocket and SSE (Server-Sent Events)
- Enable AI agents to monitor job progress

### Tasks

#### 4.1 WebSocket Streaming
- [ ] `WS /orcaops/jobs/{job_id}/logs/stream` - WebSocket endpoint
- [ ] Stream stdout/stderr as job runs
- [ ] Send structured messages with timestamps
- [ ] Handle connection lifecycle

#### 4.2 SSE Alternative
- [ ] `GET /orcaops/jobs/{job_id}/logs/stream` - SSE endpoint
- [ ] For clients that don't support WebSocket
- [ ] Same data format as WebSocket

#### 4.3 Log Buffering
- [ ] Buffer recent logs for late-joining clients
- [ ] Configurable buffer size (default: 1000 lines)
- [ ] Support `?since=timestamp` parameter

### Deliverables
- WebSocket endpoint for log streaming
- SSE fallback endpoint
- Log buffer implementation

---

## Phase 5: CLI Job Commands

### Objectives
- Add CLI commands that mirror the API functionality
- Enable interactive job monitoring from terminal

### Tasks

#### 5.1 Job Submission CLI
- [ ] `orcaops run <image> <command>` - Quick job submission
- [ ] `orcaops run --spec job.yaml` - Submit from spec file
- [ ] Support inline environment variables and mounts

#### 5.2 Job Monitoring CLI
- [ ] `orcaops jobs` - List recent jobs
- [ ] `orcaops jobs status <job_id>` - Show job status
- [ ] `orcaops jobs logs <job_id>` - Stream or show logs
- [ ] `orcaops jobs cancel <job_id>` - Cancel running job

#### 5.3 Artifact CLI
- [ ] `orcaops jobs artifacts <job_id>` - List artifacts
- [ ] `orcaops jobs download <job_id> <path>` - Download artifact

### Deliverables
- New CLI commands in `cli_utils_fixed.py`
- Interactive log streaming with rich output
- Job spec YAML examples

---

## Success Criteria

- [ ] Can submit a job via API and receive job_id
- [ ] Can poll job status until completion
- [ ] Can retrieve artifacts after job completes
- [ ] Can stream logs in real-time
- [ ] All endpoints documented in OpenAPI schema
- [ ] 80%+ test coverage on new code
- [ ] CLI commands work for all API operations

---

## Technical Notes

### Background Task Runner
Consider using:
- `asyncio.create_task()` for simple cases
- `BackgroundTasks` from FastAPI
- Redis + Celery for production scale (future sprint)

### Job State Machine
```
QUEUED -> RUNNING -> SUCCESS
                  -> FAILED
                  -> TIMED_OUT
         CANCELLED (from QUEUED or RUNNING)
```

### API Response Format
All job-related endpoints should return consistent structure:
```json
{
  "job_id": "abc123",
  "status": "running",
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:30:01Z",
  "finished_at": null,
  "steps": [...],
  "artifacts": [...],
  "error": null
}
```

---

## Dependencies

- Existing: `JobRunner`, `DockerManager`, `RunRecord`, `JobSpec`
- New: `websockets` or `starlette` WebSocket support
- Optional: `aiofiles` for async file operations
