import re
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

class CleanupStatus(str, Enum):
    DESTROYED = "destroyed"
    LEAKED = "leaked"


# --- Sprint 03: Observability Models ---

class AnomalyType(str, Enum):
    DURATION = "duration"
    MEMORY = "memory"
    ERROR_PATTERN = "error_pattern"
    FLAKY = "flaky"
    SUCCESS_RATE_DEGRADATION = "success_rate_degradation"

class AnomalySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class ResourceUsage(BaseModel):
    """Resource consumption snapshot from Docker container stats."""
    cpu_seconds: float = 0.0
    memory_peak_mb: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0

class EnvironmentCapture(BaseModel):
    """Captured container environment at job start time."""
    image_digest: Optional[str] = None
    env_vars: Dict[str, str] = Field(default_factory=dict)
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    docker_version: Optional[str] = None

class LogAnalysis(BaseModel):
    """Structured analysis of job output logs."""
    error_count: int = 0
    warning_count: int = 0
    first_error: Optional[str] = None
    stack_traces: List[str] = Field(default_factory=list)
    error_lines: List[str] = Field(default_factory=list)

class Anomaly(BaseModel):
    """A detected anomaly for a job run."""
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    expected: str
    actual: str
    message: str

class JobSummary(BaseModel):
    """Deterministic summary of a job execution."""
    job_id: str
    one_liner: str
    status_label: str
    duration_human: str
    step_count: int
    steps_passed: int
    steps_failed: int
    key_events: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    anomalies: List[Anomaly] = Field(default_factory=list)

class JobCommand(BaseModel):
    command: str = Field(..., description="The command to execute")
    cwd: Optional[str] = Field(None, description="Working directory for the command")
    timeout_seconds: int = Field(300, description="Timeout for this specific command")

class SandboxSpec(BaseModel):
    image: str = Field(..., description="Docker image reference (should be pinned)")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    resources: Dict[str, Any] = Field(default_factory=dict, description="Resource limits (e.g. cpu, memory)")
    network_name: Optional[str] = Field(None, description="Docker network to connect the container to")

    @field_validator("image")
    @classmethod
    def validate_image(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._\-/:@]+$', v):
            raise ValueError(f"Invalid Docker image reference: {v}")
        if len(v) > 256:
            raise ValueError("Image reference too long (max 256 chars)")
        return v

class JobSpec(BaseModel):
    job_id: str = Field(..., description="Unique identifier for the job")
    sandbox: SandboxSpec
    commands: List[JobCommand]
    artifacts: List[str] = Field(default_factory=list, description="List of paths/globs to collect")
    ttl_seconds: int = Field(3600, description="Total time to live for the sandbox")
    # Sprint 03: context fields
    triggered_by: Optional[str] = Field(None, description="Trigger source: cli, api, mcp, scheduler")
    intent: Optional[str] = Field(None, description="Natural language description of job purpose")
    parent_job_id: Optional[str] = Field(None, description="Parent job ID for chained executions")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization and filtering")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom key-value metadata")
    workspace_id: Optional[str] = Field(None, description="Workspace this job belongs to")

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$', v):
            raise ValueError("job_id must be alphanumeric with hyphens/underscores")
        if len(v) > 128:
            raise ValueError("job_id too long (max 128 chars)")
        return v

    @field_validator("ttl_seconds")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 10 or v > 86400:
            raise ValueError("ttl_seconds must be between 10 and 86400")
        return v

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, v: List[str]) -> List[str]:
        dangerous = set(';|&$`(){}!')
        for pattern in v:
            if any(c in dangerous for c in pattern):
                raise ValueError(f"Artifact pattern contains disallowed characters: {pattern}")
        return v

class StepResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ArtifactMetadata(BaseModel):
    name: str
    path: str
    size_bytes: int
    sha256: str

class RunRecord(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    sandbox_id: Optional[str] = None
    image_ref: Optional[str] = None
    steps: List[StepResult] = Field(default_factory=list)
    artifacts: List[ArtifactMetadata] = Field(default_factory=list)
    cleanup_status: Optional[CleanupStatus] = None
    ttl_expiry: Optional[datetime] = None
    fingerprint: Optional[str] = None
    error: Optional[str] = None
    # Sprint 03: observability fields
    triggered_by: Optional[str] = None
    intent: Optional[str] = None
    parent_job_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    resource_usage: Optional[ResourceUsage] = None
    environment: Optional[EnvironmentCapture] = None
    log_analysis: Optional[LogAnalysis] = None
    anomalies: List[Anomaly] = Field(default_factory=list)
    workspace_id: Optional[str] = None


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    record: RunRecord


class JobListResponse(BaseModel):
    jobs: List[RunRecord]
    count: int


class JobCancelResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobArtifactListResponse(BaseModel):
    job_id: str
    artifacts: List[ArtifactMetadata]
    count: int


class RunListResponse(BaseModel):
    """Response for listing historical run records."""
    runs: List[RunRecord]
    total: int
    offset: int
    limit: int


class RunDeleteResponse(BaseModel):
    """Response for deleting a run record."""
    job_id: str
    deleted: bool
    message: str


class RunCleanupRequest(BaseModel):
    """Request body for run cleanup."""
    older_than_days: int = Field(30, ge=1, le=365, description="Delete runs older than N days")


class RunCleanupResponse(BaseModel):
    """Response for run cleanup operation."""
    deleted_count: int
    deleted_job_ids: List[str]
    message: str


# API Response Models

class Container(BaseModel):
    """Container summary for list operations"""
    id: str
    names: List[str]
    image: str
    status: str


class ContainerInspect(BaseModel):
    """Detailed container inspection"""
    id: str
    name: str
    image: str
    state: Dict[str, Any]
    network_settings: Dict[str, Any]


class CleanupReport(BaseModel):
    """Report from cleanup operation"""
    stopped: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class Template(BaseModel):
    """Sandbox template definition"""
    name: str
    description: str
    category: str
    services: List[str]


class TemplateList(BaseModel):
    """List of available templates"""
    templates: List[Template]


# Sandbox Registry Models

class SandboxStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"


class Sandbox(BaseModel):
    """Registered sandbox project"""
    name: str
    template: str
    path: str
    created_at: str
    status: str = "stopped"


class SandboxList(BaseModel):
    """List of registered sandboxes"""
    sandboxes: List[Sandbox]
    count: int


class SandboxValidation(BaseModel):
    """Sandbox validation result"""
    name: str
    exists: bool
    has_compose: bool
    has_env: bool


class SandboxActionResult(BaseModel):
    """Result of a sandbox action (up/down)"""
    name: str
    action: str
    success: bool
    message: str


class SandboxCreateRequest(BaseModel):
    """Request to create a new sandbox"""
    template: str = Field(..., description="Template name (web-dev, python-ml, api-testing)")
    name: str = Field(..., description="Sandbox name")
    directory: Optional[str] = Field(None, description="Output directory (defaults to ./{name})")


# Sprint 03: Observability Response Models

class JobSummaryResponse(BaseModel):
    """Response for job summary endpoint."""
    job_id: str
    summary: JobSummary


class MetricsResponse(BaseModel):
    """Response for job metrics endpoint."""
    total_runs: int
    success_count: int
    failed_count: int
    timed_out_count: int
    cancelled_count: int
    success_rate: float
    avg_duration_seconds: float
    total_duration_seconds: float
    by_image: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


# --- Sprint 04: Workflow Models ---

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class ServiceDefinition(BaseModel):
    """A service container to run alongside a workflow job."""
    image: str
    env: Dict[str, str] = Field(default_factory=dict)
    health_check: Optional[Dict[str, Any]] = None
    ports: Dict[str, int] = Field(default_factory=dict)

    @field_validator("image")
    @classmethod
    def validate_service_image(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._\-/:@]+$', v):
            raise ValueError(f"Invalid Docker image reference: {v}")
        return v


class MatrixConfig(BaseModel):
    """Matrix build configuration for a workflow job."""
    parameters: Dict[str, List[str]] = Field(default_factory=dict)
    exclude: List[Dict[str, str]] = Field(default_factory=list)
    include: List[Dict[str, str]] = Field(default_factory=list)


class WorkflowJob(BaseModel):
    """A single job within a workflow definition."""
    name: str = ""
    image: str
    commands: List[str]
    requires: List[str] = Field(default_factory=list)
    if_condition: Optional[str] = Field(None, alias="if")
    on_complete: str = "success"
    services: Dict[str, ServiceDefinition] = Field(default_factory=dict)
    artifacts: List[str] = Field(default_factory=list)
    timeout: int = 300
    env: Dict[str, str] = Field(default_factory=dict)
    matrix: Optional[MatrixConfig] = None

    model_config = {"populate_by_name": True}

    @field_validator("on_complete")
    @classmethod
    def validate_on_complete(cls, v: str) -> str:
        if v not in {"success", "failure", "always"}:
            raise ValueError(f"on_complete must be 'success', 'failure', or 'always', got '{v}'")
        return v


class WorkflowSpec(BaseModel):
    """Complete workflow specification parsed from YAML."""
    name: str
    description: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    jobs: Dict[str, WorkflowJob]
    timeout: int = 3600
    cleanup_policy: str = "remove_on_completion"

    @field_validator("name")
    @classmethod
    def validate_workflow_name(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$', v):
            raise ValueError("Workflow name must be alphanumeric with hyphens/underscores")
        if len(v) > 128:
            raise ValueError("Workflow name too long (max 128 chars)")
        return v


class WorkflowJobStatus(BaseModel):
    """Status of an individual job within a workflow run."""
    job_name: str
    status: JobStatus
    job_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    matrix_key: Optional[str] = None


class WorkflowRecord(BaseModel):
    """Persisted record of a workflow execution."""
    workflow_id: str
    spec_name: str
    status: WorkflowStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    job_statuses: Dict[str, WorkflowJobStatus] = Field(default_factory=dict)
    env: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    triggered_by: Optional[str] = None


class WorkflowSubmitRequest(BaseModel):
    """Request body for submitting a workflow via API."""
    spec: WorkflowSpec
    triggered_by: Optional[str] = None


class WorkflowSubmitResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    created_at: datetime
    message: str


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    record: WorkflowRecord


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowRecord]
    count: int


class WorkflowCancelResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    message: str


class WorkflowJobsResponse(BaseModel):
    workflow_id: str
    jobs: Dict[str, WorkflowJobStatus]
    count: int


# --- Sprint 05: Workspace & Security Models ---

class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class OwnerType(str, Enum):
    USER = "user"
    TEAM = "team"
    AI_AGENT = "ai-agent"


class ResourceLimits(BaseModel):
    """Per-workspace resource constraints."""
    max_concurrent_jobs: int = 10
    max_concurrent_sandboxes: int = 5
    max_job_duration_seconds: int = 3600
    max_cpu_per_job: float = 4.0
    max_memory_per_job_mb: int = 8192
    max_artifacts_size_mb: int = 1024
    max_storage_gb: int = 50
    daily_job_limit: Optional[int] = None


class WorkspaceSettings(BaseModel):
    """Workspace-level configuration."""
    default_cleanup_policy: str = "remove_on_completion"
    allowed_images: List[str] = Field(default_factory=list)
    blocked_images: List[str] = Field(default_factory=list)
    max_job_timeout: int = 3600
    retention_days: int = 30


class Workspace(BaseModel):
    """A workspace providing resource isolation."""
    id: str
    name: str
    owner_type: OwnerType
    owner_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    settings: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE

    @field_validator("id")
    @classmethod
    def validate_workspace_id(cls, v: str) -> str:
        if not re.match(r'^ws_[a-zA-Z0-9]+$', v):
            raise ValueError("workspace id must start with 'ws_' followed by alphanumeric chars")
        if len(v) > 64:
            raise ValueError("workspace id too long (max 64 chars)")
        return v

    @field_validator("name")
    @classmethod
    def validate_workspace_name(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$', v):
            raise ValueError("name must be alphanumeric with hyphens/underscores")
        if len(v) > 64:
            raise ValueError("name too long (max 64 chars)")
        return v


class WorkspaceUsage(BaseModel):
    """Real-time usage snapshot for a workspace."""
    workspace_id: str
    current_running_jobs: int = 0
    current_running_sandboxes: int = 0
    storage_used_mb: int = 0
    jobs_today: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkspaceCreateRequest(BaseModel):
    """Request body for creating a workspace."""
    name: str = Field(..., description="Workspace name")
    owner_type: OwnerType = Field(..., description="Owner type")
    owner_id: str = Field(..., description="Owner identifier")
    settings: Optional[WorkspaceSettings] = None
    limits: Optional[ResourceLimits] = None


class WorkspaceUpdateRequest(BaseModel):
    """Request body for updating a workspace."""
    settings: Optional[WorkspaceSettings] = None
    limits: Optional[ResourceLimits] = None
    status: Optional[WorkspaceStatus] = None


class WorkspaceResponse(BaseModel):
    """Single workspace response."""
    workspace: Workspace
    message: str = ""


class WorkspaceListResponse(BaseModel):
    """List of workspaces response."""
    workspaces: List[Workspace]
    count: int


# --- Sprint 05: Authentication & Authorization Models ---

class Permission(str, Enum):
    SANDBOX_READ = "sandbox:read"
    SANDBOX_CREATE = "sandbox:create"
    SANDBOX_START = "sandbox:start"
    SANDBOX_STOP = "sandbox:stop"
    SANDBOX_DELETE = "sandbox:delete"
    JOB_READ = "job:read"
    JOB_CREATE = "job:create"
    JOB_CANCEL = "job:cancel"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_CANCEL = "workflow:cancel"
    WORKSPACE_ADMIN = "workspace:admin"
    POLICY_ADMIN = "policy:admin"
    AUDIT_READ = "audit:read"


class APIKey(BaseModel):
    """An API key bound to a workspace with specific permissions."""
    key_id: str
    key_hash: str
    name: str
    workspace_id: str
    permissions: List[Permission]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked: bool = False

    @field_validator("key_id")
    @classmethod
    def validate_key_id(cls, v: str) -> str:
        if not re.match(r'^key_[a-zA-Z0-9]+$', v):
            raise ValueError("key_id must start with 'key_' followed by alphanumeric chars")
        return v


class APIKeyCreateRequest(BaseModel):
    """Request body for creating an API key."""
    name: str = Field(..., description="Human-readable name for the key")
    permissions: Optional[List[Permission]] = None
    role: Optional[str] = Field(None, description="Role template: admin, developer, viewer, ci")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)


class APIKeyCreateResponse(BaseModel):
    """Response containing the newly created key (plain key shown once)."""
    key_id: str
    plain_key: str
    name: str
    workspace_id: str
    permissions: List[Permission]
    expires_at: Optional[datetime] = None
    message: str = "Store this key securely — it will not be shown again."


class APIKeyResponse(BaseModel):
    """API key info without the hash."""
    key_id: str
    name: str
    workspace_id: str
    permissions: List[Permission]
    created_at: datetime
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked: bool = False


class APIKeyListResponse(BaseModel):
    """List of API keys."""
    keys: List[APIKeyResponse]
    count: int


# --- Sprint 05: Security Policy Models ---

class PolicyResult(BaseModel):
    """Result of a policy validation check."""
    allowed: bool
    violations: List[str] = Field(default_factory=list)
    policy_name: str = ""


class ImagePolicy(BaseModel):
    """Image allow/block list policy."""
    allowed_images: List[str] = Field(default_factory=list)
    blocked_images: List[str] = Field(default_factory=list)
    require_digest: bool = False


class CommandPolicy(BaseModel):
    """Command blocking policy."""
    blocked_commands: List[str] = Field(default_factory=list)
    blocked_patterns: List[str] = Field(default_factory=list)


class NetworkPolicy(BaseModel):
    """Network access policy."""
    allow_internet: bool = True
    allowed_hosts: List[str] = Field(default_factory=list)
    blocked_ports: List[int] = Field(default_factory=list)


class SecurityPolicy(BaseModel):
    """Combined security policy for a workspace."""
    image_policy: ImagePolicy = Field(default_factory=ImagePolicy)
    command_policy: CommandPolicy = Field(default_factory=CommandPolicy)
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    container_security: Dict[str, Any] = Field(default_factory=lambda: {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": False,
    })


# --- Sprint 05: Audit Logging Models ---

class AuditAction(str, Enum):
    JOB_CREATED = "job.created"
    JOB_CANCELLED = "job.cancelled"
    JOB_COMPLETED = "job.completed"
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_CANCELLED = "workflow.cancelled"
    SANDBOX_CREATED = "sandbox.created"
    KEY_CREATED = "key.created"
    KEY_REVOKED = "key.revoked"
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"
    WORKSPACE_ARCHIVED = "workspace.archived"
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    POLICY_VIOLATION = "policy.violation"
    SESSION_STARTED = "session.started"
    SESSION_EXPIRED = "session.expired"


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class AuditEvent(BaseModel):
    """A single audit log entry."""
    event_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workspace_id: str
    actor_type: str
    actor_id: str
    action: AuditAction
    resource_type: str
    resource_id: str
    details: Dict[str, Any] = Field(default_factory=dict)
    outcome: AuditOutcome
    ip_address: Optional[str] = None


class AuditQueryResponse(BaseModel):
    """Response for audit log queries."""
    events: List[AuditEvent]
    total: int
    offset: int
    limit: int


# --- Sprint 05: Agent Session Models ---

class SessionStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"


class AgentSession(BaseModel):
    """An active MCP agent session with resource tracking."""
    session_id: str
    agent_type: str
    workspace_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: SessionStatus = SessionStatus.ACTIVE
    resources_created: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """Single session response."""
    session: AgentSession
    message: str = ""


class SessionListResponse(BaseModel):
    """List of sessions."""
    sessions: List[AgentSession]
    count: int


# --- Sprint 06: AI-Driven Optimization Models ---

class PerformanceBaseline(BaseModel):
    """Enhanced baseline with statistical measures."""
    key: str
    sample_count: int = 0
    # Duration stats
    duration_ema: float = 0.0
    duration_mean: float = 0.0
    duration_stddev: float = 0.0
    duration_p50: float = 0.0
    duration_p95: float = 0.0
    duration_p99: float = 0.0
    duration_min: float = 0.0
    duration_max: float = 0.0
    # Memory stats
    memory_mean_mb: float = 0.0
    memory_max_mb: float = 0.0
    # Success tracking
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 1.0
    # Rolling window for percentile computation
    recent_durations: List[float] = Field(default_factory=list)
    recent_memory_mb: List[float] = Field(default_factory=list)
    # Metadata
    last_duration: float = 0.0
    last_updated: Optional[datetime] = None
    first_seen: Optional[datetime] = None


class BaselineListResponse(BaseModel):
    """Response for listing baselines."""
    baselines: List[PerformanceBaseline]
    count: int


class BaselineResponse(BaseModel):
    """Response for a single baseline."""
    baseline: PerformanceBaseline


class AnomalyRecord(BaseModel):
    """Persisted anomaly with full context."""
    anomaly_id: str
    job_id: str
    baseline_key: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    title: str
    description: str
    expected: str
    actual: str
    z_score: Optional[float] = None
    deviation_percent: Optional[float] = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False
    resolution: Optional[str] = None


class AnomalyListResponse(BaseModel):
    """Response for listing anomalies."""
    anomalies: List[AnomalyRecord]
    total: int
    offset: int
    limit: int


class RecommendationType(str, Enum):
    PERFORMANCE = "performance"
    COST = "cost"
    RELIABILITY = "reliability"
    SECURITY = "security"


class RecommendationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationStatus(str, Enum):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    APPLIED = "applied"


class Recommendation(BaseModel):
    """An actionable recommendation based on pattern analysis."""
    recommendation_id: str
    rec_type: RecommendationType
    priority: RecommendationPriority
    title: str
    description: str
    impact: str
    action: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    status: RecommendationStatus = RecommendationStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workspace_id: Optional[str] = None


class RecommendationListResponse(BaseModel):
    """Response for listing recommendations."""
    recommendations: List[Recommendation]
    count: int


class DurationPrediction(BaseModel):
    """Predicted job duration with confidence."""
    estimated_seconds: float
    confidence: float
    range_low: float
    range_high: float
    sample_count: int
    baseline_key: Optional[str] = None


class FailureRiskAssessment(BaseModel):
    """Predicted failure risk for a job."""
    risk_score: float
    risk_level: str
    factors: List[str] = Field(default_factory=list)
    historical_success_rate: Optional[float] = None
    sample_count: int = 0
    baseline_key: Optional[str] = None


class PredictionResponse(BaseModel):
    """Combined prediction response."""
    duration: Optional[DurationPrediction] = None
    failure_risk: Optional[FailureRiskAssessment] = None


class OptimizationSuggestion(BaseModel):
    """A specific optimization suggestion for a job."""
    suggestion_type: str
    current_value: str
    suggested_value: str
    reason: str
    confidence: float
    baseline_key: str


class FailurePattern(BaseModel):
    """A known failure pattern with solutions."""
    pattern_id: str
    regex_pattern: str
    category: str
    title: str
    description: str
    solutions: List[str] = Field(default_factory=list)
    occurrences: int = 0
    last_seen: Optional[datetime] = None


class DebugAnalysis(BaseModel):
    """Result of debugging analysis on a failed job."""
    job_id: str
    summary: str
    likely_causes: List[str] = Field(default_factory=list)
    matched_patterns: List[FailurePattern] = Field(default_factory=list)
    suggested_fixes: List[str] = Field(default_factory=list)
    similar_job_ids: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
