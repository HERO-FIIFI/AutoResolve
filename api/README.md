# REST API

The FastAPI application is `agentictriage.api:app`; its OpenAPI document is generated at runtime.
The Phase 1 endpoint requires tenant, role, correlation, and idempotency headers. Its in-memory
idempotency store is local-only and must be replaced by a transactional database claim before a
multi-replica deployment.

