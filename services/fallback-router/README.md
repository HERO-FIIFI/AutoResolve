# Fallback router

Input: tenant provider/region policy, ordered providers, ticket, and evidence. Output: the first
schema-valid decision plus provider identity. It applies bounded retries, exponential backoff, and
closed/open/half-open circuit states. Exhaustion always returns human escalation.

