# Model provider outage

1. Confirm the alert carries tenant ID, correlation ID, provider, and circuit state without ticket
   text or secrets.
2. Disable the affected provider in tenant policy if failures are unsafe or sustained.
3. Confirm secondary-provider traffic and human-escalation queues remain healthy.
4. Do not force-close the circuit or bypass citation/schema validation.
5. Restore in half-open mode and verify a controlled probe succeeds.
6. Record impact, fallback volume, customer-response duplication check, and follow-up actions.

