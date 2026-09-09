# ADR 0002: OpenAI-compatible provider boundary

Status: Proposed

Decision engines depend on an internal `ModelProvider` protocol. LM Studio uses the same HTTP shape
as OpenAI-compatible hosted services, but provider identity, locality, credentials, timeouts, and
tenant permission remain explicit configuration. Locality is not treated as proof of compliance.

