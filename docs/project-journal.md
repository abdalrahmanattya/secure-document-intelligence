# Project journal

## 2026-08-13 — local v1 implementation

- Outcome: credential-free API, deterministic extraction/review flow, React review UI, Docker Compose adapters, AWS Terraform review path, public security/runbook/evidence documentation.
- Acceptance evidence: `cd api && pytest -q`; `cd frontend && npm ci && npm test && npm run build`; `terraform fmt -check && terraform validate` under `infra/aws`. CI uses backend-disabled validation; protected apply uses configured remote state.
- Boundaries: no commit, remote, push, deployment, credential use, or cloud apply. The local store is an adapter; AWS resources are not claimed deployed.
- Resume point: run verification, fix failures, inspect full diff, and report exact limitations to the parent agent.

## 2026-08-13 — contract, cloud UI, and diagram remediation

- Upload contract: browser/API/Lambda now require filename, supported MIME, exact size, and client-declared SHA-256; local PUT verifies the body digest, AWS presigned POST carries exact metadata and the worker verifies metadata plus object bytes.
- UI: local auth-disabled mode is explicit on localhost; cloud builds use Cognito authorization-code PKCE, same-origin relative API paths, progress polling, citations/confidence, human correction, approve/reject, audit, security-state warnings, and confirmed deletion.
- AWS graph: CloudFront now fronts both the private UI bucket and API Gateway `/v1/*`; Cognito user-pool domain/client outputs support the protected workflow’s callback configuration. No private-subnet claim remains.
- Diagrams: added polished landscape system/cloud SVGs with numbered flows, trust boundaries, benefits, actual Terraform resources, official AWS Architecture Icons assets, attribution, and an explicit unexecuted-cloud label. PNG renders were captured to `/tmp/secure-document-{system,cloud}-architecture.png` and visually inspected.
- Verification: API `9 passed`; Lambda contract `4 passed`; frontend typecheck, UI contract/E2E checks, and Vite build passed; Compose restart/malware/injection/correction/audit/delete/DLQ lifecycle passed; Terraform format/init-backend=false/validate and Compose config passed.
- Resume point: parent review of the complete uncommitted diff; no cloud apply, credentials, remote, or commit performed.

## 2026-08-13 — cloud diagram accuracy pass

- Corrected `docs/diagrams/cloud-architecture.svg` so the browser reaches CloudFront, CloudFront serves the private UI bucket and routes `/v1/*` to API Gateway/Lambda, while Cognito PKCE remains a browser-to-identity flow.
- Corrected the processing order: browser presigned POST → quarantine S3; S3 `ObjectCreated` → SQS; GuardDuty independently scans/tags; the worker reads SQS and gates on the tag. The diagram now includes the deployed-plan resources for API Lambda, clean promotion, Textract, optional Bedrock, DynamoDB, CloudWatch, and KMS, with a numbered legend and unexecuted-cloud banner.
- Rendered with `qlmanage -t -s 1800` and visually inspected the full SVG at `/tmp/sdi-diagram-preview/cloud-architecture.svg.png`; no clipping or card/text overlap was observed. XML parsing passed.
- Follow-up visual pass made both architecture SVGs standalone with embedded official AWS icon data URIs (the preserved source assets remain under `docs/diagrams/assets/`), and clarified the local diagram as API → durable state/job plus worker ↔ state/quarantine/adapters relationships rather than a misleading linear queue.
- Re-rendered both full canvases with `sips -s format png` to `/tmp/sdi-diagram-full/{system,cloud}-architecture.png`; both were visually inspected for clipping, missing icons, black fills, and legibility. SVG checks confirm XML parses, embedded data URIs exist, and there are no relative `assets/` references.
- Final uniqueness check passed after removing duplicate visible `<use>` groups: both SVGs now have unique element IDs and one intentional visible official-icon layer per architecture.

## Contract follow-up

- Frontend upload now emits lowercase hexadecimal SHA-256, branches on local PUT versus AWS presigned POST FormData, and never sends Authorization to S3. Cognito stores the ID token only after validating its `aud` against the app client; API Gateway is configured for that same audience.
- CloudFront explicitly serves `index.html`; Terraform contract tests assert the SPA root/API behavior. AWS `/process` no longer sends SQS messages because the quarantine S3 notification is the sole enqueue source; Lambda contract tests assert no second send path.
- Quarantine CORS is restricted to the callback origin and POST/x-amz headers; processing/DLQ use SQS-managed SSE so S3 notification delivery is compatible with the queue policy. Worker and GuardDuty roles have scoped documents-CMK GenerateDataKey/Decrypt permissions.
- GuardDuty role remediation now matches the official Malware Protection for S3 prerequisite: managed EventBridge rule actions with `events:ManagedBy`, S3 bucket notification/validation/version permissions, list/get/version scan access, and KMS actions constrained by `kms:ViaService = s3.<region>.amazonaws.com`; the malware plan depends on its inline policy and S3 notification enables EventBridge delivery.

## Verification update

- API: `cd api && /tmp/sdi-venv313b/bin/python -m pytest -q` → `8 passed in 0.31s` (including persistence and retry/DLQ tests).
- Frontend: `npm ci`, `npm test`, and `npm run build` → TypeScript passed; Vite production bundle generated.
- Compose: `docker compose config --quiet` → passed.
- AWS IaC: `terraform fmt -check`, `terraform init -backend=false`, and `terraform validate` → valid; provider lock includes AWS and Archive providers. The backend-disabled init is validation-only; the protected deployment workflow supplies S3/DynamoDB backend configuration.
- Python 3.14 was not used because the pinned Pydantic Core release has no compatible wheel and fails its Rust/PyO3 version check; Python 3.13 passes.
- Compose end-to-end: `docker compose up -d --build` (using `API_PORT=8001 UI_PORT=5174` because local port 8000 was occupied), then synthetic upload → MinIO quarantine → queue worker → extraction → audit → review → delete passed; API returned `APPROVED`, audit contained 6 events, review returned `APPROVED`, and delete returned HTTP 204.
- The first Compose run exposed a non-root named-volume ownership issue and a MinIO KMS incompatibility; the state-init service and local-only SSE behavior now make the integrated path work without weakening production S3 KMS configuration.
- AWS path now has real API/worker Lambda route handling, Cognito JWT authorizer, S3 presign and notification, SQS event source mapping, private UI bucket/OAC CloudFront, and remote-state configuration inputs. AWS remains unexecuted.
- Second Compose evidence: API-only process returned a pending job; the separate worker claimed it from DynamoDB Local and reached `APPROVED`. After API/worker rebuild/restart, the previously pending job completed and a new synthetic job reached `APPROVED` with 6 persisted audit events. DynamoDB Local now uses a named disk volume and bootstraps `sdi-documents`.
- Final verification: API `8 passed`; frontend TypeScript and Vite build passed; Lambda contract `2 passed`; Terraform formatting/validation, Compose config, Python compilation, and smoke-script syntax passed. AWS remains unperformed; the protected workflow is the only intended apply path.
