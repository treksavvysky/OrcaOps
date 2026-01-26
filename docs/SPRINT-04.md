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
- [ ] Create `WorkflowSpec` Pydantic model
- [ ] Define job dependencies (`requires`, `after`)
- [ ] Support conditional execution (`if`, `unless`)
- [ ] Enable parallel job groups
- [ ] Add workflow-level settings (timeout, cleanup)

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
- [ ] Detect circular dependencies
- [ ] Validate job references exist
- [ ] Check for unreachable jobs
- [ ] Validate condition syntax

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
- [ ] Build DAG from workflow spec
- [ ] Calculate execution order
- [ ] Identify parallelizable groups
- [ ] Detect critical path

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
- [ ] Create `WorkflowRunner` class
- [ ] Implement job scheduling logic
- [ ] Handle parallel job execution with asyncio
- [ ] Pass artifacts between jobs
- [ ] Evaluate conditions before execution

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
- [ ] Share environment variables across jobs
- [ ] Pass outputs from previous jobs
- [ ] Track workflow-level state
- [ ] Support variable interpolation

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

- [ ] Implement state transitions
- [ ] Track per-job status within workflow
- [ ] Handle workflow-level timeout
- [ ] Support cancellation

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
- [ ] Store in `~/.orcaops/workflows/{workflow_id}.json`
- [ ] Update state as jobs complete
- [ ] Link to individual job run records
- [ ] Support workflow run history queries

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
- [ ] `POST /orcaops/workflows` - Start workflow from spec
- [ ] `GET /orcaops/workflows/{id}` - Get workflow status
- [ ] `GET /orcaops/workflows/{id}/jobs` - List jobs in workflow
- [ ] `POST /orcaops/workflows/{id}/cancel` - Cancel workflow
- [ ] `GET /orcaops/workflows` - List workflow runs

#### 4.2 Workflow CLI
- [ ] `orcaops workflow run <spec.yaml>` - Run workflow
- [ ] `orcaops workflow status <id>` - Check status
- [ ] `orcaops workflow logs <id>` - Combined logs
- [ ] `orcaops workflow cancel <id>` - Cancel
- [ ] `orcaops workflow list` - List runs

#### 4.3 Workflow MCP Tools
- [ ] `orcaops_run_workflow` - Start workflow
- [ ] `orcaops_get_workflow_status` - Check status
- [ ] `orcaops_cancel_workflow` - Cancel workflow

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

- [ ] Parse service definitions
- [ ] Start services before job
- [ ] Wait for health checks
- [ ] Inject service URLs into job environment
- [ ] Clean up services after job

#### 5.2 Service Networking
- [ ] Create workflow-specific Docker network
- [ ] Connect services and job containers
- [ ] Enable service discovery by name
- [ ] Isolate from other workflows

#### 5.3 Service Logs
- [ ] Capture service logs
- [ ] Include in job artifacts
- [ ] Surface errors in job summary

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

- [ ] Parse matrix configuration
- [ ] Generate job variants
- [ ] Handle exclude/include rules
- [ ] Limit concurrency

#### 6.2 Matrix Execution
- [ ] Expand matrix to individual jobs
- [ ] Run matrix jobs in parallel
- [ ] Aggregate results
- [ ] Report per-variant status

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

- [ ] Can define multi-job workflows in YAML
- [ ] Jobs run in correct dependency order
- [ ] Parallel jobs execute concurrently
- [ ] Conditions control job execution
- [ ] Services start and are accessible
- [ ] Matrix builds expand and run
- [ ] Workflow status visible via API/CLI/MCP
- [ ] Can resume failed workflows (future enhancement)

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
