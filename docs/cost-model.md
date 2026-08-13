# Cost model

The default delivery is ephemeral. S3, DynamoDB, SQS, Lambda, API Gateway, and CloudWatch are usage-priced; Textract and Bedrock are per-request/token services. A temporary smoke run should use one small synthetic document and destroy immediately. Review the Terraform plan and the current AWS pricing pages before approval; this repository does not claim a fixed price because account region, free-tier status, model, and retention change the bill.
