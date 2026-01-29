# Sprint 05: Multi-Tenant Workspaces & Security Policies

**Goal:** Enable multiple users, teams, and AI agents to share OrcaOps safely with proper isolation, resource limits, and security boundaries. Prepare for production deployment.

**Duration:** 3 weeks

**Prerequisites:** Sprint 01-04 complete

---

## Phase 1: Workspace Model

### Objectives
- Define workspace concept for resource isolation
- Support personal and team workspaces
- Enable workspace-scoped operations

### Tasks

#### 1.1 Workspace Schema
```python
class Workspace(BaseModel):
    id: str  # "ws_abc123"
    name: str  # "acme-corp-dev"
    owner_type: str  # "user", "team", "ai-agent"
    owner_id: str
    created_at: datetime
    settings: WorkspaceSettings
    limits: ResourceLimits
    status: str  # "active", "suspended", "archived"

class WorkspaceSettings(BaseModel):
    default_cleanup_policy: str
    allowed_images: List[str]  # Glob patterns
    blocked_images: List[str]
    max_job_timeout: int
    retention_days: int
```

- [ ] Create workspace models
- [ ] Implement workspace registry
- [ ] Store in `~/.orcaops/workspaces/`

#### 1.2 Workspace Hierarchy
```
/workspaces/
  /personal/
    /george/
      /sandboxes/
      /jobs/
      /artifacts/
  /teams/
    /acme-corp/
      /dev/
      /staging/
      /prod/
  /agents/
    /claude-code-session-xyz/
```

- [ ] Implement hierarchical workspace paths
- [ ] Scope all resources to workspace
- [ ] Enable workspace switching

#### 1.3 Workspace Management
- [ ] `POST /orcaops/workspaces` - Create workspace
- [ ] `GET /orcaops/workspaces` - List workspaces
- [ ] `GET /orcaops/workspaces/{id}` - Get workspace
- [ ] `PATCH /orcaops/workspaces/{id}` - Update settings
- [ ] `DELETE /orcaops/workspaces/{id}` - Archive workspace

### Deliverables
- Workspace data model
- Workspace registry
- Workspace API endpoints

---

## Phase 2: Authentication & Authorization

### Objectives
- Implement API authentication
- Define role-based access control
- Support multiple auth methods

### Tasks

#### 2.1 API Key Authentication
```python
class APIKey(BaseModel):
    key_id: str  # "key_abc123"
    key_hash: str  # bcrypt hash
    name: str  # "CI Pipeline Key"
    workspace_id: str
    permissions: List[str]
    created_at: datetime
    last_used: Optional[datetime]
    expires_at: Optional[datetime]
```

- [ ] Generate secure API keys
- [ ] Implement key validation middleware
- [ ] Track key usage
- [ ] Support key rotation

#### 2.2 Permission System
```python
class Permission(str, Enum):
    # Sandbox permissions
    SANDBOX_READ = "sandbox:read"
    SANDBOX_CREATE = "sandbox:create"
    SANDBOX_START = "sandbox:start"
    SANDBOX_STOP = "sandbox:stop"
    SANDBOX_DELETE = "sandbox:delete"

    # Job permissions
    JOB_READ = "job:read"
    JOB_CREATE = "job:create"
    JOB_CANCEL = "job:cancel"

    # Workflow permissions
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_CANCEL = "workflow:cancel"

    # Admin permissions
    WORKSPACE_ADMIN = "workspace:admin"
    POLICY_ADMIN = "policy:admin"
```

- [ ] Define permission enum
- [ ] Create role templates (admin, developer, viewer, ci)
- [ ] Implement permission checking middleware

#### 2.3 Auth Middleware
- [ ] Extract API key from `Authorization: Bearer <key>` header
- [ ] Validate key and load permissions
- [ ] Inject workspace context into request
- [ ] Reject unauthorized requests with 401/403

### Deliverables
- API key management
- Permission system
- Auth middleware

---

## Phase 3: Resource Limits & Quotas

### Objectives
- Prevent resource exhaustion
- Enable fair sharing between workspaces
- Track and enforce limits

### Tasks

#### 3.1 Resource Limits Model
```python
class ResourceLimits(BaseModel):
    max_concurrent_jobs: int = 10
    max_concurrent_sandboxes: int = 5
    max_job_duration_seconds: int = 3600
    max_cpu_per_job: float = 4.0  # cores
    max_memory_per_job_mb: int = 8192
    max_artifacts_size_mb: int = 1024
    max_storage_gb: int = 50
    daily_job_limit: Optional[int] = None
```

- [ ] Define limits schema
- [ ] Store limits per workspace
- [ ] Implement limit defaults

#### 3.2 Quota Tracking
```python
class WorkspaceUsage(BaseModel):
    workspace_id: str
    current_running_jobs: int
    current_running_sandboxes: int
    storage_used_mb: int
    jobs_today: int
    cpu_seconds_today: float
    updated_at: datetime
```

- [ ] Track real-time usage
- [ ] Update on job start/stop
- [ ] Persist usage metrics

#### 3.3 Limit Enforcement
- [ ] Check limits before job creation
- [ ] Return clear error messages
- [ ] Queue jobs when at limit (optional)
- [ ] Cleanup to reclaim resources

### Deliverables
- Resource limits model
- Usage tracking
- Enforcement logic

---

## Phase 4: Security Policies

### Objectives
- Define what can and cannot run
- Prevent dangerous operations
- Enable customizable security rules

### Tasks

#### 4.1 Image Policies
```yaml
# policies/image-policy.yaml
allowed_images:
  - "python:*"
  - "node:*"
  - "golang:*"
  - "postgres:*"
  - "redis:*"
  - "ghcr.io/myorg/*"

blocked_images:
  - "*:latest"  # Require pinned versions
  - "docker:*-dind"  # No Docker-in-Docker

require_digest: true  # Require image@sha256:...
```

- [ ] Parse image policy configuration
- [ ] Validate images before job creation
- [ ] Support glob patterns
- [ ] Check image digest requirements

#### 4.2 Command Policies
```yaml
# policies/command-policy.yaml
blocked_commands:
  - "rm -rf /"
  - "curl * | bash"
  - "wget * | sh"
  - ":(){:|:&};:"  # Fork bomb

blocked_patterns:
  - ".*--privileged.*"
  - ".*--net=host.*"
  - ".*--pid=host.*"
```

- [ ] Parse command policies
- [ ] Check commands before execution
- [ ] Log policy violations

#### 4.3 Network Policies
```yaml
# policies/network-policy.yaml
allow_internet: false  # Default deny

allowed_hosts:
  - "pypi.org"
  - "npmjs.com"
  - "github.com"
  - "*.githubusercontent.com"

blocked_ports:
  - 22  # SSH
  - 3389  # RDP
```

- [ ] Implement network restrictions
- [ ] Use Docker network policies
- [ ] Log blocked connections

#### 4.4 Policy Engine
```python
class PolicyEngine:
    def __init__(self, policies_dir: Path):
        self.image_policy = load_image_policy(policies_dir)
        self.command_policy = load_command_policy(policies_dir)
        self.network_policy = load_network_policy(policies_dir)

    def validate_job(self, spec: JobSpec) -> PolicyResult:
        """Check if job complies with all policies"""

    def validate_image(self, image: str) -> PolicyResult:
        """Check if image is allowed"""

    def validate_command(self, command: str) -> PolicyResult:
        """Check if command is allowed"""
```

### Deliverables
- Policy definition schemas
- Policy validation engine
- Pre-execution policy checks

---

## Phase 5: Audit Logging

### Objectives
- Track all significant actions
- Enable security forensics
- Support compliance requirements

### Tasks

#### 5.1 Audit Event Schema
```python
class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime
    workspace_id: str
    actor_type: str  # "user", "api_key", "system"
    actor_id: str
    action: str  # "job.created", "sandbox.started", "policy.violated"
    resource_type: str
    resource_id: str
    details: Dict[str, Any]
    outcome: str  # "success", "denied", "error"
    ip_address: Optional[str]
```

- [ ] Define audit event schema
- [ ] Create audit event types enum
- [ ] Include relevant context

#### 5.2 Audit Logging
- [ ] Log all API requests
- [ ] Log job lifecycle events
- [ ] Log policy violations
- [ ] Log authentication events
- [ ] Log administrative actions

#### 5.3 Audit Storage & Query
- [ ] Store in `~/.orcaops/audit/YYYY-MM-DD.jsonl`
- [ ] API: `GET /orcaops/audit` - Query audit log
- [ ] Support filtering by actor, action, resource
- [ ] Retention policy for audit logs

### Deliverables
- Audit event logging
- Audit log storage
- Audit query API

---

## Phase 6: Agent Session Management

### Objectives
- Track AI agent sessions
- Attribute actions to sessions
- Enable session-scoped cleanup

### Tasks

#### 6.1 Agent Session Model
```python
class AgentSession(BaseModel):
    session_id: str
    agent_type: str  # "claude-code", "custom-gpt", "automation"
    workspace_id: str
    started_at: datetime
    last_activity: datetime
    status: str  # "active", "idle", "expired"
    resources_created: List[str]  # job_ids, sandbox_ids
    metadata: Dict[str, Any]
```

- [ ] Create session model
- [ ] Track session in MCP context
- [ ] Associate resources with sessions

#### 6.2 Session Lifecycle
- [ ] Create session on first MCP call
- [ ] Update last_activity on each call
- [ ] Expire idle sessions (configurable timeout)
- [ ] Cleanup session resources on expiry

#### 6.3 Session API
- [ ] `GET /orcaops/sessions` - List active sessions
- [ ] `GET /orcaops/sessions/{id}` - Get session details
- [ ] `DELETE /orcaops/sessions/{id}` - End session

### Deliverables
- Agent session tracking
- Session-based resource attribution
- Session cleanup

---

## Success Criteria

- [ ] Multiple workspaces can coexist
- [ ] API requires authentication
- [ ] Permissions control access
- [ ] Resource limits are enforced
- [ ] Dangerous operations are blocked
- [ ] All actions are audited
- [ ] AI sessions are tracked
- [ ] No cross-workspace data leakage

---

## Technical Notes

### API Key Format
```
orcaops_key_<workspace_id>_<random_32_chars>
```

### Permission Inheritance
```
workspace:admin -> includes all workspace permissions
job:create -> requires sandbox:read (to validate sandbox)
workflow:create -> requires job:create
```

### Docker Security
Apply security options to containers:
```python
security_opt = [
    "no-new-privileges:true",
]
cap_drop = ["ALL"]
cap_add = []  # Only add what's needed
read_only = True  # Where possible
```

### Audit Log Format (JSONL)
```json
{"event_id":"evt_123","timestamp":"2024-01-15T10:30:00Z","workspace_id":"ws_abc","actor_type":"api_key","actor_id":"key_xyz","action":"job.created","resource_type":"job","resource_id":"job_456","outcome":"success"}
```

---

## Dependencies

- Existing: All previous sprints
- New: `bcrypt` for password/key hashing
- New: `python-jose` for JWT (optional future use)
- New: Docker security configuration
