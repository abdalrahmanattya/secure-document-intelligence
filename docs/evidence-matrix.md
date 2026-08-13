# Evidence matrix

| Claim | Local evidence | Cloud evidence required |
| --- | --- | --- |
| bounded upload | `api/tests/test_api.py::test_tenant_isolation_and_bounded_upload` | API Gateway/S3 integration test |
| declared SHA-256 contract | `test_declared_digest_is_required_and_verified`; browser `npm run test:e2e` | presigned POST metadata and Lambda object digest verification |
| malware rejection | `test_malware_marker_rejected_without_clamav` | ClamAV Lambda or managed scanner evidence |
| cited extraction | `test_invoice_happy_path_has_citations_and_audit` | Textract fixture with sanitized output |
| injection defense | `test_prompt_injection_is_routed_to_human_review` | model red-team fixture |
| tenant isolation | `test_tenant_isolation_and_bounded_upload` | Cognito claims and DynamoDB policy test |
| retention deletion | `test_review_correction_and_delete_retention_state` | S3/DynamoDB deletion verification |
| durable local processing | Compose synthetic upload/process after API+worker restart; DynamoDB Local named volume retains job/document/audit state | SQS redrive and Lambda event-source evidence |
| accessible review UI | `frontend/tests/ui-contract.test.mjs`; browser-rendered responsive UI | CloudFront/Cognito PKCE browser walkthrough |
| same-origin cloud UI/API | Terraform CloudFront API origin and ordered `/v1/*` behavior; workflow builds relative API UI | deployed CloudFront/API Gateway smoke evidence |
| AWS delivery | Terraform validate, remote-state init inputs, OIDC protected workflow, synthetic smoke script | approved plan/apply/smoke/destroy evidence and clean post-destroy account check |
