# Retrieval service

Input: redacted ticket, tenant ID, and immutable KB version. Output: ranked chunks including stable
IDs and scores. Storage must enforce tenant isolation. Missing evidence fails to human escalation.
The current BM25-like implementation is a local fixture adapter; production adds pgvector hybrid
ranking behind this contract.

