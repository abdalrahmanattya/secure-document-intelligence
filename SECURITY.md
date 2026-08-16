# Security policy and pre-deployment checklist

Do not report real document content, credentials, or personal data in issues. Email the repository owner privately with reproduction steps and sanitized evidence.

Before any AWS `APPLY`, confirm:

- the protected GitHub environment has the intended reviewers, repository/branch restrictions, and an OIDC trust policy limited to this repository;
- Terraform state has an explicitly owned S3 bucket, encryption, versioning, restricted access, and a DynamoDB lock table;
- `PLAN` output, cost assumptions, identity-provider settings, callback URL, and required protected inputs have been reviewed;
- S3, SQS, DynamoDB, KMS, Lambda, API Gateway, CloudFront, GuardDuty, Textract, Bedrock, and CloudWatch permissions match the threat model;
- logging, alarms, retention, deletion, backup, restore, and incident contacts have been tested with synthetic data;
- `SMOKE` evidence is sanitized and `DESTROY` verification confirms temporary resources and outputs are absent.

Local fixture mode is not malware assurance and this repository does not claim AWS deployment. Never commit static credentials, cloud state, real documents, or generated `.env` files.
