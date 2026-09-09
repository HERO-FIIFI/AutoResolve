# Ingestion service

Input: authenticated tenant context and a size-limited ticket. Output: normalized, PII-redacted
ticket plus deterministic risk findings. Prompt injection, malformed input, or policy failure emits
an audit event and human escalation; no model is called.

