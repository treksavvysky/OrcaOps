from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field

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

class JobCommand(BaseModel):
    command: str = Field(..., description="The command to execute")
    cwd: Optional[str] = Field(None, description="Working directory for the command")
    timeout_seconds: int = Field(300, description="Timeout for this specific command")

class SandboxSpec(BaseModel):
    image: str = Field(..., description="Docker image reference (should be pinned)")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    resources: Dict[str, Any] = Field(default_factory=dict, description="Resource limits (e.g. cpu, memory)")

class JobSpec(BaseModel):
    job_id: str = Field(..., description="Unique identifier for the job")
    sandbox: SandboxSpec
    commands: List[JobCommand]
    artifacts: List[str] = Field(default_factory=list, description="List of paths/globs to collect")
    ttl_seconds: int = Field(3600, description="Total time to live for the sandbox")

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
