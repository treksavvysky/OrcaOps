# Sprint 02: MCP Server Integration

**Goal:** Expose OrcaOps as an MCP (Model Context Protocol) server, enabling Claude Code and other MCP clients to execute jobs, manage sandboxes, and retrieve results through the standardized protocol.

**Duration:** 2 weeks

**Prerequisites:** Sprint 01 complete (Job API functional)

---

## Phase 1: MCP Server Foundation

### Objectives
- Set up MCP server infrastructure
- Define tool schemas for OrcaOps capabilities
- Implement basic tool handlers

### Tasks

#### 1.1 MCP Server Setup
- [ ] Add `mcp` package dependency
- [ ] Create `orcaops/mcp_server.py` - Main MCP server module
- [ ] Configure server metadata and capabilities
- [ ] Set up stdio transport for Claude Code integration

#### 1.2 Server Configuration
- [ ] Create `mcp_config.json` for server settings
- [ ] Support environment variable configuration
- [ ] Implement graceful startup/shutdown
- [ ] Add health check mechanism

#### 1.3 Tool Schema Definitions
- [ ] Define JSON schemas for all tools
- [ ] Include detailed descriptions for AI understanding
- [ ] Add parameter validation
- [ ] Document expected outputs

### Deliverables
- Working MCP server that starts and responds to capability queries
- Configuration file template
- Server entry point script

---

## Phase 2: Sandbox Management Tools

### Objectives
- Expose sandbox operations as MCP tools
- Enable AI to create, start, stop, and query sandboxes

### Tasks

#### 2.1 Sandbox Tools
- [ ] `orcaops_list_sandboxes` - List all registered sandboxes
  ```json
  {
    "name": "orcaops_list_sandboxes",
    "description": "List all registered sandbox projects with their status",
    "inputSchema": {
      "type": "object",
      "properties": {
        "validate": {"type": "boolean", "description": "Check if directories exist"}
      }
    }
  }
  ```

- [ ] `orcaops_create_sandbox` - Create sandbox from template
  ```json
  {
    "name": "orcaops_create_sandbox",
    "description": "Create a new sandbox from a template (web-dev, python-ml, api-testing)",
    "inputSchema": {
      "type": "object",
      "properties": {
        "template": {"type": "string", "enum": ["web-dev", "python-ml", "api-testing"]},
        "name": {"type": "string"},
        "directory": {"type": "string"}
      },
      "required": ["template", "name"]
    }
  }
  ```

- [ ] `orcaops_start_sandbox` - Start a sandbox (docker-compose up)
- [ ] `orcaops_stop_sandbox` - Stop a sandbox (docker-compose down)
- [ ] `orcaops_get_sandbox` - Get details about a specific sandbox

#### 2.2 Template Tools
- [ ] `orcaops_list_templates` - List available templates
- [ ] `orcaops_get_template` - Get template details and services

### Deliverables
- All sandbox management tools implemented
- Tool handlers connected to existing sandbox registry
- Tests for each tool

---

## Phase 3: Job Execution Tools

### Objectives
- Enable AI to submit, monitor, and retrieve job results
- Provide structured output suitable for AI reasoning

### Tasks

#### 3.1 Job Submission Tool
- [ ] `orcaops_run_job` - Submit a job for execution
  ```json
  {
    "name": "orcaops_run_job",
    "description": "Run a command in a Docker container and return results",
    "inputSchema": {
      "type": "object",
      "properties": {
        "image": {"type": "string", "description": "Docker image (e.g., python:3.11-slim)"},
        "command": {"type": "array", "items": {"type": "string"}},
        "timeout": {"type": "integer", "default": 300},
        "env": {"type": "object", "additionalProperties": {"type": "string"}},
        "working_dir": {"type": "string"}
      },
      "required": ["image", "command"]
    }
  }
  ```

#### 3.2 Job Monitoring Tools
- [ ] `orcaops_get_job_status` - Check job status
- [ ] `orcaops_get_job_logs` - Retrieve job output
- [ ] `orcaops_list_jobs` - List recent jobs
- [ ] `orcaops_cancel_job` - Cancel a running job

#### 3.3 Artifact Tools
- [ ] `orcaops_list_artifacts` - List job artifacts
- [ ] `orcaops_get_artifact` - Retrieve artifact content (base64 for binary)

### Deliverables
- Complete job execution toolset
- Synchronous and async execution modes
- Artifact retrieval with proper encoding

---

## Phase 4: Container Management Tools

### Objectives
- Expose direct container operations
- Enable troubleshooting and debugging capabilities

### Tasks

#### 4.1 Container Tools
- [ ] `orcaops_list_containers` - List Docker containers
- [ ] `orcaops_get_container_logs` - Get container logs
- [ ] `orcaops_inspect_container` - Get detailed container info
- [ ] `orcaops_stop_container` - Stop a container
- [ ] `orcaops_remove_container` - Remove a container

#### 4.2 System Tools
- [ ] `orcaops_system_info` - Get Docker and system status
- [ ] `orcaops_cleanup` - Clean up stopped containers

### Deliverables
- Container management tools
- System information tool for diagnostics

---

## Phase 5: Claude Code Integration

### Objectives
- Enable seamless integration with Claude Code
- Document installation and usage
- Provide example workflows

### Tasks

#### 5.1 Installation Package
- [ ] Create `orcaops-mcp` CLI command to start server
- [ ] Add to `pyproject.toml` as entry point
- [ ] Support `--port` and `--host` options
- [ ] Add `--debug` mode for troubleshooting

#### 5.2 Claude Code Configuration
- [ ] Document MCP server configuration for Claude Code
- [ ] Create example `claude_code_config.json`
- [ ] Test integration end-to-end
- [ ] Handle permission prompts gracefully

#### 5.3 Usage Documentation
- [ ] Write MCP integration guide
- [ ] Provide example prompts and workflows
- [ ] Document tool capabilities and limitations
- [ ] Add troubleshooting section

### Deliverables
- `orcaops-mcp` command
- Claude Code configuration guide
- Example workflow documentation

---

## Phase 6: Custom GPT Actions (Bonus)

### Objectives
- Generate OpenAPI schema suitable for Custom GPT Actions
- Enable ChatGPT integration via API

### Tasks

#### 6.1 OpenAPI Enhancement
- [ ] Ensure all endpoints have detailed descriptions
- [ ] Add example requests/responses
- [ ] Generate `openapi.json` for GPT import
- [ ] Validate schema with GPT Actions validator

#### 6.2 Authentication
- [ ] Implement API key authentication
- [ ] Support Bearer token in headers
- [ ] Add rate limiting for external access

### Deliverables
- GPT-compatible OpenAPI schema
- API key authentication
- GPT Actions setup guide

---

## Success Criteria

- [ ] MCP server starts and responds to tool discovery
- [ ] Claude Code can list sandboxes via MCP
- [ ] Claude Code can run a job and get results
- [ ] All tools have proper error handling
- [ ] Documentation enables self-service setup
- [ ] GPT Actions work with API (bonus)

---

## Technical Notes

### MCP Protocol Basics
```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("orcaops")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="orcaops_run_job",
            description="Run a command in a Docker container",
            inputSchema={...}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "orcaops_run_job":
        result = await run_job(arguments)
        return [TextContent(type="text", text=json.dumps(result))]
```

### Tool Naming Convention
- Prefix all tools with `orcaops_`
- Use snake_case
- Verb first: `orcaops_run_job`, `orcaops_list_sandboxes`

### Error Handling
Tools should return structured errors:
```json
{
  "success": false,
  "error": {
    "code": "SANDBOX_NOT_FOUND",
    "message": "Sandbox 'my-app' not found",
    "suggestion": "Use orcaops_list_sandboxes to see available sandboxes"
  }
}
```

---

## Dependencies

- New: `mcp` (Model Context Protocol SDK)
- Existing: All Sprint 01 deliverables
- Optional: `python-jose` for JWT authentication
