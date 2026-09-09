# Knowledge-base re-index

Build a new immutable index version, validate tenant ownership and chunk checksums, run retrieval
and citation evals, then atomically switch the tenant's active version. Retain the prior version for
rollback according to policy. Never mutate the active index in place.

