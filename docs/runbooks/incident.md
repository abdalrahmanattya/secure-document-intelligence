# Incident runbook

1. Check API, worker, SQS age, DLQ depth, and CloudWatch alarms.
2. Stop new processing via the protected deployment switch if documents are at risk.
3. Preserve request IDs and audit events; do not download raw customer documents into tickets.
4. Redrive only after the failure mode is understood. Idempotency keys prevent duplicate state transitions.
5. Rotate affected credentials through the protected GitHub environment/OIDC role or the owning AWS service, notify the owner, and record the sanitized evidence bundle. Do not add static credentials to GitHub or the repository.
