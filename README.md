# AutoResolve

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

Ollama and LM Studio are supported through their OpenAI-compatible APIs. Ollama is the default
Docker provider and uses `qwen2.5:7b`; LM Studio remains an optional fallback. Start its local server and configure
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

Start Ollama with GPU access, the API, PostgreSQL/pgvector, worker, and operations console with:

```console
docker compose up --build -d
```

The console is available at `http://localhost:3080`, the API at `http://localhost:8080`, and API
documentation at `http://localhost:8080/docs`. Sign in to the local console with `admin` /
`autoresolve-local`. Change `TRIAGE_ADMIN_PASSWORD` and `TRIAGE_AUTH_SECRET` in `.env` before sharing
the environment. Compose credentials are intentionally disposable local-development values;
production deployments must inject database credentials and signing keys from a secrets manager.

The Compose stack mounts Ollama's model store from `D:/AI/Models/Ollama` by default. Override
`OLLAMA_MODELS_PATH` in `.env` if models live elsewhere. LM Studio runs on Windows rather than in
Compose; enable its local server on port 1234 to make its live status become Ready.

The local console uses a short-lived, signed local session. It removes spoofable browser identity
headers, but it is not enterprise SSO; deploy publicly only after an OIDC/SAML identity broker and
managed secrets replace the local login.
