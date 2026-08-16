# Gated AWS deployment runbook

AWS is planned, not deployed, in this repository. This runbook describes the exact gated path and does not constitute deployment evidence.

## Prerequisites and ownership

- An approved AWS account, region, service quotas, budget owner, and incident contact.
- Terraform and the repository’s protected workflow reviewed against the [security checklist](../../SECURITY.md) and [cost model](../cost-model.md).
- An encrypted, versioned S3 state bucket and DynamoDB lock table owned by the platform account. Restrict both to the deployment role; never commit state.
- GitHub Actions access to the protected environment and an AWS IAM OIDC role whose trust policy is limited to this repository and approved branch/workflow claims.
- Protected workflow variables: `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_TF_STATE_BUCKET`, `AWS_TF_STATE_KEY`, and `AWS_TF_LOCK_TABLE`. The protected secret `AWS_SMOKE_ID_TOKEN` is required only for `SMOKE`; `action` and `confirmation` are workflow-dispatch inputs. Cognito callback configuration is derived from the Terraform CloudFront output during `APPLY`, not supplied as an input.

The state bucket is the durable owner of Terraform state; the lock table owns concurrent-operation locks. Enable encryption, versioning, access logging, and recovery controls before `PLAN`.

## Gates

1. **PLAN** — select the protected environment, dispatch `PLAN`, inspect Terraform changes, IAM scope, callback URLs, cost assumptions, and outputs. Stop on unexpected resources or policy changes.
2. **APPLY** — after approval, dispatch only `APPLY`. The workflow creates the target resources, derives the CloudFront URL, completes Cognito PKCE callback configuration, builds the UI with same-origin API paths, and uploads it to the private UI bucket.
3. **SMOKE** — dispatch `SMOKE` with a short-lived Cognito ID token and synthetic fixture. Verify exact-size browser-equivalent SHA-256 upload, terminal processing state, citations/confidence, audit, review correction, deletion, and sanitized evidence.
4. **DESTROY** — dispatch `DESTROY`, then verify Terraform state, outputs, temporary buckets/objects, queues, and identities are absent or intentionally retained by policy.

The GuardDuty role follows the [official Malware Protection for S3 IAM prerequisite](https://docs.aws.amazon.com/guardduty/latest/ug/malware-protection-s3-iam-policy-prerequisite.html), including scoped managed EventBridge rule actions, S3 validation/notification/version permissions, and the S3-scoped KMS `ViaService` condition.

## Outputs, rollback, and data loss

Record the CloudFront URL, API/Lambda identifiers, Cognito issuer/client identifiers, bucket names, queue/DLQ names, and sanitized smoke artifact. If `APPLY` fails, preserve the failed plan and workflow logs, correct the configuration, and run a new `PLAN`; do not manually edit state. If smoke fails, stop traffic through the protected workflow path, preserve evidence, and either remediate through a reviewed plan or destroy the ephemeral stack.

`force_destroy` on S3 resources can permanently delete objects. Treat it as an explicit data-loss warning: use it only for approved ephemeral environments after retention, backup, and incident-owner confirmation. Never use it to bypass a failed recovery or deletion review.

No AWS apply, smoke test, destroy, credentials, or account validation has been performed for this repository state.
