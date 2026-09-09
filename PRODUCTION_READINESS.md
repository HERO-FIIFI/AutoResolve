# Production Readiness

Status reflects repository evidence, not intended future work.

| Requirement | Status | Evidence / gap |
|---|---|---|
| Input sanitization and injection detection | In Progress | Deterministic guard scaffold and tests; policy corpus must expand |
| Secrets manager | Not Started | Interface/deployment selection pending; `.env` is local-only and ignored |
| PII redaction and residency routing | In Progress | Basic redaction and provider allowlist; production DLP not integrated |
| Encryption at rest/in transit | Not Started | Cloud/KMS target pending |
| RBAC on all surfaces | In Progress | API dependency scaffold; enterprise IdP integration pending |
| Immutable access-controlled audit log | In Progress | PostgreSQL append-only application role implemented; external WORM sink pending |
| GDPR export/deletion/retention | Not Started | Data lifecycle design pending |
| Database tenant isolation | In Progress | PostgreSQL RLS schema and policies implemented; adversarial cross-tenant integration gate pending |
| SSO (OIDC/SAML) | Not Started | Identity broker selection pending |
| Per-tenant policy | In Progress | Persistent RLS-backed policy schema; authenticated administration endpoint pending |
| Retry, timeout, and circuit breaker | Done | State machine and chaos tests |
| Fail-safe all-provider behavior | Done | Explicit human escalation path and tests |
| Idempotent processing | Done | PostgreSQL uniqueness and durable result replay verified |
| RPO/RTO and DR runbook | Not Started | Deployment platform and business targets pending |
| Structured telemetry | In Progress | Correlation-aware event contract; OTEL exporter pending |
| Metrics, dashboards, and alerts | Not Started | Backend and SLO targets pending |
| Queue-based processing | Done | PostgreSQL durable jobs with `SKIP LOCKED` worker and fail-safe processing |
| Semantic cache | Not Started | Requires privacy and invalidation design |
| Scalable versioned vector index | In Progress | pgvector decision recorded; implementation pending |
| Infrastructure as code | Not Started | Cloud target pending; Terraform unavailable locally |
| CI quality gates | Done | Backend and frontend lint/build, typing, tests, eval, dependency scans, image build |
| Canary/blue-green deployment | Not Started | Platform pending |
| Unit/integration/eval tests | In Progress | Phase 1 paths covered; live dependencies excluded |
| Load testing | Not Started | SLA/concurrency target pending |
| Chaos testing | In Progress | Provider failure paths covered; infrastructure chaos pending |
| Architecture/OpenAPI/runbooks/ADRs | In Progress | Architecture and initial ADRs present; runbooks incomplete |
| Admin console | In Progress | Functional responsive operations dashboard and dialogs; live records/auth integration pending |
| CLI, REST API, webhooks | In Progress | CLI/API scaffolded; webhook delivery pending |
| Cost governance | Not Started | Token accounting and tenant budget persistence pending |
