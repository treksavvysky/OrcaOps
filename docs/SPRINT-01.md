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
- [x] `POST /orcaops/jobs` - Submit a new job
  - Accept `JobSpec` as request body
  - Validate image references and commands
  - Return `job_id` and initial status
  - Start job execution in background task

#### 1.2 Job Status Endpoint
- [x] `GET /orcaops/jobs/{job_id}` - Get job status and details
  - Return current `RunRecord` state
  - Include step results if available
  - Show cleanup status

#### 1.3 Job Listing Endpoint
- [x] `GET /orcaops/jobs` - List recent jobs
  - Support filtering by status (queued, running, success, failed)
  - Pagination support
  - Sort by created_at descending

#### 1.4 Job Cancellation
- [x] `POST /orcaops/jobs/{job_id}/cancel` - Cancel a running job
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
- [x] Store run records in `~/.orcaops/artifacts/{job_id}/`
- [x] Save each `RunRecord` as `run.json`
- [x] Append step log to `steps.jsonl`
- [x] Include timestamps, duration, fingerprint

#### 2.2 Run Record API
- [x] `GET /orcaops/runs` - List historical runs
- [x] `GET /orcaops/runs/{job_id}` - Get specific run record
- [x] `DELETE /orcaops/runs/{job_id}` - Delete run record

#### 2.3 Run Record Cleanup
- [x] Implement retention policy (default: 30 days)
- [x] `POST /orcaops/runs/cleanup` - Manual cleanup endpoint
- [x] CLI command: `orcaops runs-cleanup --older-than 7d`

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
- [x] Implement `docker cp` wrapper in `DockerManager`
- [x] Support glob patterns for artifact paths
- [x] Calculate SHA256 checksums
- [x] Store in `~/.orcaops/artifacts/{job_id}/`

#### 3.2 Artifact API
- [x] `GET /orcaops/jobs/{job_id}/artifacts` - List artifacts
- [x] `GET /orcaops/jobs/{job_id}/artifacts/{filename}` - Download artifact
- [x] Include size, checksum, and content-type in response

#### 3.3 Artifact Metadata
- [x] Store `ArtifactMetadata` in run record
- [ ] Support artifact retention policies (deferred)
- [ ] Compress large artifacts (deferred)

### Deliverables
- Artifact extraction in `JobRunner`
- Download endpoints in API
- Artifact metadata in run records

---

## Phase 4: Live Log Streaming

### Objectives
- Stream container logs to clients in real-time
- Support SSE (Server-Sent Events) for broad client compatibility
- Enable AI agents to monitor job progress

### Tasks

#### 4.1 SSE Log Streaming
- [x] `GET /orcaops/jobs/{job_id}/logs/stream` - SSE endpoint
- [x] Stream stdout/stderr as job runs
- [x] Send structured JSON messages with timestamps
- [x] Handle connection lifecycle (job completion, client disconnect)
- [x] Support `?tail=N` query parameter

#### 4.2 WebSocket Streaming
- [ ] WebSocket endpoint (deferred — SSE covers all current use cases)

#### 4.3 Log Buffering
- [ ] Buffer recent logs for late-joining clients (deferred)
- [ ] Support `?since=timestamp` parameter (deferred)

### Deliverables
- SSE endpoint for log streaming
- Async bridge from Docker SDK sync streaming to async SSE

---

## Phase 5: CLI Job Commands

### Objectives
- Add CLI commands that mirror the API functionality
- Enable interactive job monitoring from terminal

### Tasks

#### 5.1 Job Submission CLI
- [x] `orcaops run <image> <command>` - Quick job submission
- [x] `orcaops run --spec job.yaml` - Submit from spec file
- [x] Support inline environment variables (`--env`) and artifacts (`--artifact`)

#### 5.2 Job Monitoring CLI
- [x] `orcaops jobs` - List recent jobs
- [x] `orcaops jobs status <job_id>` - Show job status
- [x] `orcaops jobs logs <job_id>` - Show or follow job logs
- [x] `orcaops jobs cancel <job_id>` - Cancel running job

#### 5.3 Artifact CLI
- [x] `orcaops jobs artifacts <job_id>` - List artifacts
- [x] `orcaops jobs download <job_id> <filename>` - Download artifact

### Deliverables
- New CLI commands in `orcaops/cli_jobs.py`
- Interactive log following with rich output
- Job spec YAML support

---

## Security Hardening

- [x] Fix artifact pattern shell injection (`shlex.quote()` in `job_runner.py`)
- [x] Add input validation for `JobSpec` fields (job_id, image, ttl, artifacts)
- [x] Path traversal protection on artifact download
- [x] 22 security-focused unit tests

---

## Success Criteria

- [x] Can submit a job via API and receive job_id
- [x] Can poll job status until completion
- [x] Can retrieve artifacts after job completes
- [x] Can stream logs in real-time (SSE)
- [x] All endpoints documented in OpenAPI schema (auto-generated)
- [x] 80%+ test coverage on new code
- [x] CLI commands work for all API operations

---

## Technical Notes

### Background Task Runner
Implementation uses Python `threading.Thread` with per-job `threading.Lock` for
thread-safe state management. `JobManager` handles in-memory active jobs with
automatic eviction to disk for completed jobs.

### Job State Machine
```
QUEUED -> RUNNING -> SUCCESS
                  -> FAILED
                  -> TIMED_OUT
         CANCELLED (from QUEUED or RUNNING)
```

### API Response Format
All job-related endpoints return consistent structure:
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
- Used: Starlette `StreamingResponse` for SSE (included via FastAPI)
- No new package dependencies required
