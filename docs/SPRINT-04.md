# Sprint 04: Workflow Engine & Job Chaining

**Goal:** Enable complex, multi-step workflows where jobs can depend on each other, run in parallel, and react to outcomes. Transform OrcaOps from a job runner into a workflow orchestrator.

**Duration:** 3 weeks

**Prerequisites:** Sprint 01-03 complete

---

## Phase 1: Workflow Schema Definition

### Objectives
- Define a YAML-based workflow specification
- Support job dependencies and conditions
- Enable parallel execution groups

### Tasks

#### 1.1 Workflow Spec Schema
- [x] Create `WorkflowSpec` Pydantic model
- [x] Define job dependencies (`requires`, `after`)
- [x] Support conditional execution (`if`, `unless`)
- [x] Enable parallel job groups
- [x] Add workflow-level settings (timeout, cleanup)

```yaml
# Example: workflows/ci-pipeline.yaml
name: ci-pipeline
description: Build, test, and deploy application

env:
  APP_VERSION: "1.0.0"
  REGISTRY: "ghcr.io/myorg"

jobs:
  build:
    image: docker:24-dind
    commands:
      - docker build -t $REGISTRY/myapp:$APP_VERSION .
    artifacts:
      - /build/image-digest.txt
    timeout: 600

  test-unit:
    image: python:3.11-slim
    requires: [build]
    commands:
      - pip install -r requirements-test.txt
      - pytest tests/unit -v

  test-integration:
    image: python:3.11-slim
    requires: [build]
    parallel_with: [test-unit]  # Run alongside test-unit
    services:
      - postgres:15
      - redis:7
    commands:
      - pytest tests/integration -v

  deploy-staging:
    image: kubectl:latest
    requires: [test-unit, test-integration]
    if: "${{ github.ref == 'refs/heads/main' }}"
    commands:
      - kubectl apply -f k8s/staging/

  notify:
    image: alpine:latest
    on_complete: always  # Run regardless of success/failure
    commands:
      - ./scripts/notify-slack.sh
```

#### 1.2 Schema Models
```python
class JobDependency(BaseModel):
    job_name: str
    condition: Optional[str]  # "success", "failure", "always"

class WorkflowJob(BaseModel):
    name: str
    image: str
    commands: List[str]
    requires: List[str] = []
    parallel_with: List[str] = []
    if_condition: Optional[str]
    unless_condition: Optional[str]
    services: List[str] = []
    artifacts: List[str] = []
    timeout: int = 300
    on_complete: str = "success"  # "success", "failure", "always"
    env: Dict[str, str] = {}

class WorkflowSpec(BaseModel):
    name: str
    description: Optional[str]
    env: Dict[str, str] = {}
    jobs: Dict[str, WorkflowJob]
    timeout: int = 3600
    cleanup_policy: str = "remove_on_completion"
```

#### 1.3 Workflow Validation
- [x] Detect circular dependencies
- [x] Validate job references exist
- [x] Check for unreachable jobs
- [x] Validate condition syntax

### Deliverables
- `orcaops/workflow_schema.py` with models
- Workflow validation logic
- Example workflow files

---

## Phase 2: Workflow Execution Engine

### Objectives
- Execute workflows according to dependency graph
- Handle parallel execution
- Manage job state transitions

### Tasks

#### 2.1 Dependency Graph
- [x] Build DAG from workflow spec
- [x] Calculate execution order
- [x] Identify parallelizable groups
- [x] Detect critical path

```python
class WorkflowDAG:
    def __init__(self, spec: WorkflowSpec):
        self.nodes = {}  # job_name -> WorkflowJob
        self.edges = {}  # job_name -> [dependent_jobs]

    def get_ready_jobs(self, completed: Set[str]) -> List[str]:
        """Return jobs whose dependencies are all satisfied"""

    def get_parallel_groups(self) -> List[List[str]]:
        """Return groups of jobs that can run in parallel"""
```

#### 2.2 Workflow Runner
- [x] Create `WorkflowRunner` class
- [x] Implement job scheduling logic
- [x] Handle parallel job execution with asyncio
- [x] Pass artifacts between jobs
- [x] Evaluate conditions before execution

```python
class WorkflowRunner:
    async def run(self, spec: WorkflowSpec) -> WorkflowResult:
        """Execute workflow and return results"""

    async def _run_job(self, job: WorkflowJob, context: WorkflowContext):
        """Execute a single job in the workflow"""

    def _evaluate_condition(self, condition: str, context: WorkflowContext) -> bool:
        """Evaluate if/unless conditions"""
```

#### 2.3 Workflow Context
- [x] Share environment variables across jobs
- [x] Pass outputs from previous jobs
- [x] Track workflow-level state
- [x] Support variable interpolation

```python
class WorkflowContext:
    workflow_id: str
    env: Dict[str, str]
    job_outputs: Dict[str, JobOutput]  # job_name -> output
    artifacts: Dict[str, Path]  # artifact_id -> local_path

    def interpolate(self, value: str) -> str:
        """Replace ${{ job.output }} style variables"""
```

### Deliverables
- `orcaops/workflow_runner.py`
- DAG implementation
- Context management

---

## Phase 3: Workflow State & Persistence

### Objectives
- Track workflow execution state
- Enable resume after failure
- Store workflow run history

### Tasks

#### 3.1 Workflow State Machine
```
PENDING -> RUNNING -> SUCCESS
                   -> FAILED
                   -> CANCELLED
                   -> PARTIAL (some jobs succeeded)
```

- [x] Implement state transitions
- [x] Track per-job status within workflow
- [x] Handle workflow-level timeout
- [x] Support cancellation

#### 3.2 Workflow Record
```python
class WorkflowRecord(BaseModel):
    workflow_id: str
    spec_name: str
    status: WorkflowStatus
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    job_statuses: Dict[str, JobStatus]
    job_run_ids: Dict[str, str]  # job_name -> run_id
    error: Optional[str]
```

#### 3.3 Persistence
- [x] Store in `~/.orcaops/workflows/{workflow_id}.json`
- [x] Update state as jobs complete
- [x] Link to individual job run records
- [x] Support workflow run history queries

### Deliverables
- Workflow state management
- Workflow record storage
- State recovery logic

---

## Phase 4: Workflow API & CLI

### Objectives
- Expose workflow operations through API
- Add CLI commands for workflow management
- Enable workflow triggering from MCP

### Tasks

#### 4.1 Workflow API
- [x] `POST /orcaops/workflows` - Start workflow from spec
- [x] `GET /orcaops/workflows/{id}` - Get workflow status
- [x] `GET /orcaops/workflows/{id}/jobs` - List jobs in workflow
- [x] `POST /orcaops/workflows/{id}/cancel` - Cancel workflow
- [x] `GET /orcaops/workflows` - List workflow runs

#### 4.2 Workflow CLI
- [x] `orcaops workflow run <spec.yaml>` - Run workflow
- [x] `orcaops workflow status <id>` - Check status
- [x] `orcaops workflow logs <id>` - Combined logs
- [x] `orcaops workflow cancel <id>` - Cancel
- [x] `orcaops workflow list` - List runs

#### 4.3 Workflow MCP Tools
- [x] `orcaops_run_workflow` - Start workflow
- [x] `orcaops_get_workflow_status` - Check status
- [x] `orcaops_cancel_workflow` - Cancel workflow

### Deliverables
- Workflow API endpoints
- CLI commands
- MCP tools

---

## Phase 5: Service Containers

### Objectives
- Support background services for jobs
- Enable integration testing scenarios
- Manage service lifecycle

### Tasks

#### 5.1 Service Definition
```yaml
jobs:
  integration-tests:
    image: python:3.11
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        health_check:
          test: ["CMD", "pg_isready"]
          interval: 5s
          timeout: 5s
          retries: 5
      redis:
        image: redis:7
```

- [x] Parse service definitions
- [x] Start services before job
- [x] Wait for health checks
- [x] Inject service URLs into job environment
- [x] Clean up services after job

#### 5.2 Service Networking
- [x] Create workflow-specific Docker network
- [x] Connect services and job containers
- [x] Enable service discovery by name
- [x] Isolate from other workflows

#### 5.3 Service Logs
- [x] Capture service logs
- [x] Include in job artifacts
- [x] Surface errors in job summary

### Deliverables
- Service container management
- Health check implementation
- Network isolation

---

## Phase 6: Matrix Builds

### Objectives
- Run same job with different configurations
- Support parallel matrix expansion
- Enable comprehensive testing

### Tasks

#### 6.1 Matrix Syntax
```yaml
jobs:
  test:
    image: python:${{ matrix.python }}
    matrix:
      python: ["3.9", "3.10", "3.11", "3.12"]
      os: ["ubuntu", "alpine"]
    exclude:
      - python: "3.9"
        os: "alpine"
    commands:
      - pytest tests/
```

- [x] Parse matrix configuration
- [x] Generate job variants
- [x] Handle exclude/include rules
- [x] Limit concurrency

#### 6.2 Matrix Execution
- [x] Expand matrix to individual jobs
- [x] Run matrix jobs in parallel
- [x] Aggregate results
- [x] Report per-variant status

#### 6.3 Matrix Results
```python
class MatrixResult(BaseModel):
    job_name: str
    variants: List[Dict[str, str]]  # [{python: "3.9", os: "ubuntu"}, ...]
    results: Dict[str, JobStatus]   # variant_key -> status
    summary: str  # "4/6 passed"
```

### Deliverables
- Matrix expansion logic
- Parallel matrix execution
- Aggregated result reporting

---

## Success Criteria

- [x] Can define multi-job workflows in YAML
- [x] Jobs run in correct dependency order
- [x] Parallel jobs execute concurrently
- [x] Conditions control job execution
- [x] Services start and are accessible
- [x] Matrix builds expand and run
- [x] Workflow status visible via API/CLI/MCP
- [x] Can resume failed workflows (future enhancement)

---

## Technical Notes

### Parallel Execution
```python
async def run_parallel_jobs(jobs: List[WorkflowJob]):
    tasks = [asyncio.create_task(run_job(j)) for j in jobs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### Condition Evaluation
Support simple expression syntax:
```python
def evaluate_condition(expr: str, context: dict) -> bool:
    # "${{ jobs.build.status == 'success' }}"
    # "${{ env.DEPLOY_ENV == 'production' }}"
    # Use safe_eval or simple parser
```

### Service Discovery
Inject environment variables for services:
```
POSTGRES_HOST=workflow-123-postgres
POSTGRES_PORT=5432
REDIS_HOST=workflow-123-redis
REDIS_PORT=6379
```

---

## Dependencies

- Existing: JobRunner, RunRecord, DockerManager
- New: `graphlib` for topological sort (Python 3.9+)
- New: Docker network management
