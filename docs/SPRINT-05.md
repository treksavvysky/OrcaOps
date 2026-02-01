# Sprint 05: Multi-Tenant Workspaces & Security Policies

**Goal:** Enable multiple users, teams, and AI agents to share OrcaOps safely with proper isolation, resource limits, and security boundaries. Prepare for production deployment.

**Duration:** 3 weeks

**Prerequisites:** Sprint 01-04 complete

**Status: COMPLETE**

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

- [x] Create workspace models
- [x] Implement workspace registry
- [x] Store in `~/.orcaops/workspaces/`

#### 1.2 Workspace Hierarchy
```
/workspaces/
  /{workspace_id}/
    /workspace.json
    /keys/
```

- [x] Implement workspace paths
- [x] Scope all resources to workspace
- [x] Default workspace auto-creation (`ws_default`)

#### 1.3 Workspace Management
- [x] `POST /orcaops/workspaces` - Create workspace
- [x] `GET /orcaops/workspaces` - List workspaces
- [x] `GET /orcaops/workspaces/{id}` - Get workspace
- [x] `PATCH /orcaops/workspaces/{id}` - Update settings
- [x] `DELETE /orcaops/workspaces/{id}` - Archive workspace

### Deliverables
- Workspace data model (`orcaops/schemas.py`)
- Workspace registry (`orcaops/workspace.py`)
- Workspace API endpoints (`orcaops/api.py`)
- CLI workspace commands (`orcaops/cli_workspaces.py`)
- MCP workspace tools (`orcaops/mcp_server.py`)

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

- [x] Generate secure API keys (format: `orcaops_{workspace_id}_{random32}`)
- [x] Implement key validation middleware
- [x] Track key usage (`last_used`)
- [x] Support key rotation

#### 2.2 Permission System
```python
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
```

- [x] Define permission enum (14 permissions)
- [x] Create role templates (admin, developer, viewer, ci)
- [x] Implement permission checking middleware

#### 2.3 Auth Middleware
- [x] Extract API key from `Authorization: Bearer <key>` header
- [x] Validate key and load permissions
- [x] Inject workspace context into request (`AuthContext`)
- [x] Reject unauthorized requests with 401/403

### Deliverables
- API key management (`orcaops/auth.py`)
- Permission system with `WORKSPACE_ADMIN` inheritance
- Auth middleware (`orcaops/auth_middleware.py`)

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
    max_cpu_per_job: float = 4.0
    max_memory_per_job_mb: int = 8192
    max_artifacts_size_mb: int = 1024
    max_storage_gb: int = 50
    daily_job_limit: Optional[int] = None
```

- [x] Define limits schema
- [x] Store limits per workspace
- [x] Implement limit defaults

#### 3.2 Quota Tracking
- [x] Track real-time usage (`QuotaTracker`)
- [x] Update on job start/stop
- [x] Daily job counting

#### 3.3 Limit Enforcement
- [x] Check limits before job creation in `JobManager.submit_job()`
- [x] Return clear error messages
- [x] Workspace isolation (limits per workspace)

### Deliverables
- Resource limits model (`orcaops/schemas.py`)
- Usage tracking (`orcaops/quota_tracker.py`)
- Enforcement in job manager

---

## Phase 4: Security Policies

### Objectives
- Define what can and cannot run
- Prevent dangerous operations
- Enable customizable security rules

### Tasks

#### 4.1 Image Policies
- [x] Validate images before job creation
- [x] Support glob patterns via `fnmatch`
- [x] Check image digest requirements
- [x] Merge workspace-level settings with global policy

#### 4.2 Command Policies
- [x] Exact match blocked commands
- [x] Regex pattern matching for blocked patterns
- [x] Log policy violations to audit log

#### 4.3 Network Policies
- [x] Define `NetworkPolicy` model (allow_internet, allowed_hosts, blocked_ports)

#### 4.4 Policy Engine
- [x] `PolicyEngine.validate_job()` — validates image + all commands
- [x] `PolicyEngine.validate_image()` — fnmatch glob patterns
- [x] `PolicyEngine.validate_command()` — exact + regex matching
- [x] `PolicyEngine.get_container_security_opts()` — Docker security options

#### 4.5 Container Hardening
- [x] Default `cap_drop=["ALL"]`
- [x] Default `security_opt=["no-new-privileges:true"]`
- [x] Security opts injected via `spec.metadata["_security_opts"]`
- [x] Applied in `JobRunner` at container creation

### Deliverables
- Policy models (`orcaops/schemas.py`)
- Policy engine (`orcaops/policy_engine.py`)
- Container security integration in `job_runner.py`

---

## Phase 5: Audit Logging

### Objectives
- Track all significant actions
- Enable security forensics
- Support compliance requirements

### Tasks

#### 5.1 Audit Event Schema
- [x] Define `AuditEvent` model with 16 action types
- [x] Define `AuditOutcome` enum (success, denied, error)
- [x] Include relevant context (actor, resource, details)

#### 5.2 Audit Logging
- [x] Thread-safe JSONL append (`AuditLogger`)
- [x] Date-based file organization (`YYYY-MM-DD.jsonl`)
- [x] Log policy violations in job submission
- [x] Log job completion events

#### 5.3 Audit Storage & Query
- [x] Store in `~/.orcaops/audit/YYYY-MM-DD.jsonl`
- [x] Query with filters (workspace, actor, action, date range)
- [x] Pagination support (limit/offset)
- [x] Cleanup of old audit files (`cleanup(older_than_days)`)

### Deliverables
- Audit event logging (`orcaops/audit.py`)
- Audit query API
- CLI audit query command
- MCP audit query tool

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
    resources_created: List[str]
    metadata: Dict[str, Any]
```

- [x] Create session model
- [x] Associate resources with sessions
- [x] Persist sessions to disk

#### 6.2 Session Lifecycle
- [x] Create session via API/MCP
- [x] Update last_activity via touch
- [x] Expire idle sessions (configurable timeout)
- [x] End session explicitly

#### 6.3 Session API & MCP
- [x] `GET /orcaops/sessions` - List active sessions
- [x] `GET /orcaops/sessions/{id}` - Get session details
- [x] `DELETE /orcaops/sessions/{id}` - End session
- [x] `orcaops_create_session` MCP tool
- [x] `orcaops_get_session` MCP tool
- [x] `orcaops_list_sessions` MCP tool
- [x] `orcaops_end_session` MCP tool

### Deliverables
- Agent session tracking (`orcaops/session_manager.py`)
- Session API endpoints
- Session MCP tools
- CLI sessions command

---

## Success Criteria

- [x] Multiple workspaces can coexist
- [x] API key authentication (opt-in, backward compatible)
- [x] Permissions control access (14 permissions, 4 role templates)
- [x] Resource limits are enforced (concurrent jobs, daily limits)
- [x] Dangerous operations are blocked (image/command policies)
- [x] All actions are audited (JSONL audit log)
- [x] AI sessions are tracked (session manager)
- [x] Container hardening applied (cap_drop, no-new-privileges)

---

## New Files Created

| File | Description |
|------|-------------|
| `orcaops/workspace.py` | Workspace registry with CRUD |
| `orcaops/auth.py` | API key management with bcrypt |
| `orcaops/auth_middleware.py` | FastAPI auth dependencies |
| `orcaops/policy_engine.py` | Security policy validation |
| `orcaops/audit.py` | JSONL audit logging and query |
| `orcaops/quota_tracker.py` | Resource limit enforcement |
| `orcaops/session_manager.py` | Agent session lifecycle |
| `orcaops/cli_workspaces.py` | CLI workspace commands |

## Test Files Created

| File | Tests |
|------|-------|
| `tests/test_workspace.py` | 26 tests |
| `tests/test_auth.py` | 26 tests |
| `tests/test_auth_middleware.py` | 10 tests |
| `tests/test_api_workspaces.py` | 15 tests |
| `tests/test_policy_engine.py` | 17 tests |
| `tests/test_audit.py` | 11 tests |
| `tests/test_quota_tracker.py` | 13 tests |
| `tests/test_integration_security.py` | 8 tests |
| `tests/test_session_manager.py` | 20 tests |
| `tests/test_cli_workspaces.py` | 13 tests |
| `tests/test_mcp_workspaces.py` | 17 tests |
| **Total** | **176 new tests** |

## Dependencies Added

- `bcrypt>=4.0` for API key hashing

## Persistence Paths

- `~/.orcaops/workspaces/{workspace_id}/workspace.json`
- `~/.orcaops/workspaces/{workspace_id}/keys/{key_id}.json`
- `~/.orcaops/audit/YYYY-MM-DD.jsonl`
- `~/.orcaops/sessions/{session_id}.json`
