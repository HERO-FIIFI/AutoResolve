# AgenticTriage-AI

Production-oriented support-ticket triage with a deterministic risk guard, hybrid retrieval,
schema-constrained decisions, provider fallback, citation verification, and fail-safe human
escalation.

## Local development

Requires Python 3.12. Install with `python -m pip install -e ".[dev]"`, then run:

```console
pytest
agentictriage run --ticket examples/ticket.json
uvicorn agentictriage.api:app --reload
```

LM Studio is supported through its OpenAI-compatible API. Start its local server and configure
`TRIAGE_LMSTUDIO_BASE_URL` (default `http://127.0.0.1:1234/v1`) and
`TRIAGE_LMSTUDIO_MODEL`. Local providers are disabled for regulated tenants unless that tenant's
provider allowlist explicitly enables `lmstudio`.

When the app runs inside Docker Desktop, use
`TRIAGE_LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`. LM Studio must have its local server
enabled and `TRIAGE_LMSTUDIO_MODEL` must match an identifier returned by `/v1/models`. Provider use
is explicit: pass `--allow-lmstudio` to the CLI or enable `lmstudio` and `local` in the tenant's
stored policy through the admin console or `/v1/policy` API. Triage requests cannot override this
server-side policy.

The current milestone is Phase 2 enterprise readiness. See [architecture](docs/architecture.md) and the
[production readiness matrix](PRODUCTION_READINESS.md).

## Local production stack

With LM Studio's server running, start the API, PostgreSQL/pgvector, and operations console with:

```console
docker compose up --build -d
```

The console is available at `http://localhost:3080`, the API at `http://localhost:8080`, and API
documentation at `http://localhost:8080/docs`. Compose credentials are intentionally disposable
local-development values; production deployments must inject database credentials from a secrets
manager.

The local console uses development identity headers for the example tenant. This is deliberately
not a production authentication mechanism; deploy the API only after the Phase 2 OIDC/SAML identity
broker replaces those headers.
