# ADR 0001: PostgreSQL row-level security for tenant isolation

Status: Proposed

Use a mandatory `tenant_id` on tenant-owned records and PostgreSQL row-level security policies tied
to a transaction-local tenant context. This offers database-enforced isolation without multiplying
schemas and migration work. Privileged maintenance roles remain separate and audited. Integration
tests must prove cross-tenant reads and writes fail before this becomes Accepted.

