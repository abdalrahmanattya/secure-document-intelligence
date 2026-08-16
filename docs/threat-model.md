# Threat model

| Asset | Threat | Control | Evidence |
| --- | --- | --- | --- |
| Documents | malware or active content | quarantine, MIME/size bounds, AV, no execution | EICAR test |
| Tenant data | cross-tenant read | tenant derived from authenticated identity, scoped keys | isolation test |
| Model context | prompt injection | treat text as data, pattern gate, schema-only output, human review | injection test |
| Credentials | leaked cloud token | GitHub protected environment, short-lived OIDC role session, no static cloud secrets | workflow permissions and environment reviewers |
| Availability | poison message/retry storm | idempotency, bounded retries, SQS DLQ | runbook |
| Retained data | unnecessary exposure | TTL, deletion endpoint, KMS, clean/quarantine lifecycle | deletion test |
