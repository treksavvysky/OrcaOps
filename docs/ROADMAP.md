# OrcaOps Product Roadmap

**Vision:** OrcaOps becomes the trusted execution environment where AI agents can safely take real-world actions - running code, managing infrastructure, and orchestrating complex workflows - with full observability, cost control, and human-in-the-loop when needed.

---

## Roadmap Overview

```
Sprint 01 ──────────────────────────────────────────────────────────────────────►
   Foundation & Job Execution API
   [2 weeks]

           Sprint 02 ──────────────────────────────────────────────────────────►
              MCP Server Integration
              [2 weeks]

                      Sprint 03 ──────────────────────────────────────────────►
                         Observability & Run Records
                         [2 weeks]

                                 Sprint 04 ──────────────────────────────────►
                                    Workflow Engine & Job Chaining
                                    [3 weeks]

                                              Sprint 05 ──────────────────────►
                                                 Multi-Tenant & Security
                                                 [3 weeks]

                                                           Sprint 06 ─────────►
                                                              AI Optimization
                                                              [3 weeks]

Timeline:     Week 1-2    Week 3-4    Week 5-6    Week 7-9    Week 10-12   Week 13-15
              ──────────────────────────────────────────────────────────────────────►
```

**Total Duration:** ~15 weeks (with some parallel work possible)

---

## Sprint Summaries

### Sprint 01: Foundation & Job Execution API
**Goal:** Expose JobRunner through REST API

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | Job API Endpoints | POST/GET /jobs, status, cancel |
| 2 | Run Record Persistence | JSON storage, history queries |
| 3 | Artifact Collection | Extract files, download API |
| 4 | Live Log Streaming | WebSocket/SSE log streaming |
| 5 | CLI Job Commands | `orcaops run`, `orcaops jobs` |

**Exit Criteria:** Can submit job via API, poll status, retrieve artifacts

---

### Sprint 02: MCP Server Integration
**Goal:** Enable Claude Code and AI agents to use OrcaOps

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | MCP Server Foundation | Server setup, tool schemas |
| 2 | Sandbox Management Tools | list, create, start, stop sandboxes |
| 3 | Job Execution Tools | run_job, get_status, get_logs |
| 4 | Container Management Tools | list, inspect, stop containers |
| 5 | Claude Code Integration | Configuration, documentation |
| 6 | Custom GPT Actions (Bonus) | OpenAPI schema for GPT |

**Exit Criteria:** Claude Code can run jobs and manage sandboxes via MCP

---

### Sprint 03: Observability & Intelligent Run Records
**Goal:** Deep visibility into every execution

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | Enhanced Run Records | Resource usage, context capture |
| 2 | Structured Logging | Log parsing, error extraction |
| 3 | AI Summaries | Human-readable job summaries |
| 4 | Metrics & Analytics | Aggregate statistics, trends |
| 5 | Anomaly Detection | Baseline comparison, alerts |
| 6 | Query & Search | Search across run history |

**Exit Criteria:** Every job produces rich, queryable data with anomaly detection

---

### Sprint 04: Workflow Engine & Job Chaining
**Goal:** Multi-step, parallel workflows

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | Workflow Schema | YAML spec, dependencies, conditions |
| 2 | Execution Engine | DAG runner, parallel execution |
| 3 | State & Persistence | Workflow records, resume capability |
| 4 | API & CLI | Workflow endpoints and commands |
| 5 | Service Containers | Background services for jobs |
| 6 | Matrix Builds | Multi-variant job expansion |

**Exit Criteria:** Can define and run complex multi-job workflows with services

---

### Sprint 05: Multi-Tenant Workspaces & Security
**Goal:** Safe multi-user, production-ready deployment

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | Workspace Model | Isolation, hierarchy |
| 2 | Authentication | API keys, permissions |
| 3 | Resource Limits | Quotas, enforcement |
| 4 | Security Policies | Image/command restrictions |
| 5 | Audit Logging | Complete action audit trail |
| 6 | Agent Session Management | Track AI agent sessions |

**Exit Criteria:** Multiple users/agents share OrcaOps safely with proper isolation

---

### Sprint 06: AI-Driven Optimization
**Goal:** Self-improving infrastructure

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| 1 | Performance Baselines | Learn normal patterns |
| 2 | Anomaly Detection | Auto-detect issues |
| 3 | Recommendations | Suggest optimizations |
| 4 | Predictive Capabilities | Duration/failure prediction |
| 5 | Auto-Optimization | Safe automatic improvements |
| 6 | Knowledge Base | Failure patterns, solutions |

**Exit Criteria:** OrcaOps learns from usage and provides intelligent recommendations

---

## Milestone Checkpoints

### M1: API-Ready (End of Sprint 01)
- [ ] Jobs can be submitted and monitored via REST API
- [ ] Artifacts are collected and downloadable
- [ ] Log streaming works

### M2: AI-Accessible (End of Sprint 02)
- [ ] Claude Code can use OrcaOps via MCP
- [ ] Custom GPT can use OrcaOps via API
- [ ] Full documentation for AI integration

### M3: Observable (End of Sprint 03)
- [ ] Rich run records with resource usage
- [ ] Anomaly detection alerts
- [ ] Searchable job history

### M4: Workflow-Capable (End of Sprint 04)
- [ ] Multi-job workflows execute correctly
- [ ] Matrix builds work
- [ ] Service containers integrate

### M5: Production-Ready (End of Sprint 05)
- [ ] Multi-tenant with proper isolation
- [ ] Authentication and authorization
- [ ] Audit logging complete

### M6: Intelligent (End of Sprint 06)
- [ ] Recommendations generated automatically
- [ ] Predictions available
- [ ] Knowledge base grows with usage

---

## Technical Debt & Cleanup

Address during or between sprints:

1. **CLI Consolidation** - Merge cli.py, cli_enhanced.py, cli_utils.py, cli_utils_fixed.py
2. **Template Consolidation** - Remove sandbox_templates.py (keep sandbox_templates_simple.py)
3. **Test Coverage** - Increase coverage on API and new modules
4. **Documentation** - API docs, user guides, architecture docs
5. **Docker Compose Deprecation** - Remove `version` from generated files

---

## Future Considerations (Post-Sprint 06)

- **Web Dashboard** - Visual interface for monitoring
- **GitHub Actions Integration** - Native CI/CD integration
- **Kubernetes Support** - Run jobs on K8s clusters
- **Distributed Execution** - Multi-node job distribution
- **LLM-Powered Analysis** - Deep log analysis with AI
- **Marketplace** - Share templates and workflows

---

## Getting Started

1. Read sprint documentation in order
2. Each sprint builds on previous deliverables
3. Sprints 01-02 are foundational and must complete first
4. Sprints 03-06 have some flexibility in ordering
5. Track progress using the checkboxes in each sprint doc

---

## Contributing

When working on a sprint:

1. Create a feature branch: `git checkout -b sprint-XX-phase-Y`
2. Implement phase tasks
3. Write tests for new functionality
4. Update CLAUDE.md if architecture changes
5. Create PR with sprint/phase reference
