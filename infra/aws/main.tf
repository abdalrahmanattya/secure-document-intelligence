data "aws_caller_identity" "current" {}

locals {
  ui_allowed_origin = regex("^https?://[^/]+", var.ui_callback_url)
}

data "archive_file" "worker" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  output_path = "${path.module}/worker.zip"
}

resource "aws_kms_key" "documents" {
  description             = "Document encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "documents" {
  name          = "alias/${var.project_name}"
  target_key_id = aws_kms_key.documents.key_id
}

resource "aws_s3_bucket" "quarantine" {
  bucket_prefix = "${var.project_name}-quarantine-"
  force_destroy = true
}

resource "aws_s3_bucket" "clean" {
  bucket_prefix = "${var.project_name}-clean-"
  force_destroy = true
}

resource "aws_s3_bucket" "ui" {
  bucket_prefix = "${var.project_name}-ui-"
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket                  = aws_s3_bucket.ui.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "quarantine" {
  bucket                  = aws_s3_bucket.quarantine.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "clean" {
  bucket                  = aws_s3_bucket.clean.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.documents.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = [local.ui_allowed_origin]
    allowed_headers = ["content-type", "x-amz-*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "clean" {
  bucket = aws_s3_bucket.clean.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.documents.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  rule {
    id     = "expire-quarantine"
    status = "Enabled"
    filter {}
    expiration { days = 1 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "clean" {
  bucket = aws_s3_bucket.clean.id
  rule {
    id     = "expire-clean"
    status = "Enabled"
    filter {}
    expiration { days = 7 }
  }
}

resource "aws_iam_role" "guardduty_malware" {
  name               = "${var.project_name}-guardduty-malware"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "malware-protection-plan.guardduty.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "guardduty_malware" {
  role = aws_iam_role.guardduty_malware.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowManagedRuleToSendS3EventsToGuardDuty"
        Effect    = "Allow"
        Action    = ["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets"]
        Resource  = ["arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"]
        Condition = { StringLike = { "events:ManagedBy" = "malware-protection-plan.guardduty.amazonaws.com" } }
      },
      {
        Sid      = "AllowGuardDutyToMonitorEventBridgeManagedRule"
        Effect   = "Allow"
        Action   = ["events:DescribeRule", "events:ListTargetsByRule"]
        Resource = ["arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"]
      },
      {
        Sid      = "AllowPostScanTag"
        Effect   = "Allow"
        Action   = ["s3:PutObjectTagging", "s3:GetObjectTagging", "s3:PutObjectVersionTagging", "s3:GetObjectVersionTagging"]
        Resource = "${aws_s3_bucket.quarantine.arn}/*"
      },
      {
        Sid      = "AllowEnableS3EventBridgeEvents"
        Effect   = "Allow"
        Action   = ["s3:PutBucketNotification", "s3:GetBucketNotification"]
        Resource = aws_s3_bucket.quarantine.arn
      },
      {
        Sid      = "AllowPutValidationObject"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.quarantine.arn}/malware-protection-resource-validation-object"
      },
      {
        Sid      = "AllowCheckBucketOwnership"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.quarantine.arn
      },
      {
        Sid      = "AllowMalwareScan"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.quarantine.arn}/*"
      },
      {
        Sid       = "AllowDecryptForMalwareScan"
        Effect    = "Allow"
        Action    = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource  = aws_kms_key.documents.arn
        Condition = { StringLike = { "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com" } }
      }
    ]
  })
}

resource "aws_guardduty_malware_protection_plan" "quarantine" {
  role = aws_iam_role.guardduty_malware.arn
  protected_resource {
    s3_bucket {
      bucket_name = aws_s3_bucket.quarantine.bucket
    }
  }
  actions {
    tagging {
      status = "ENABLED"
    }
  }
  depends_on = [aws_iam_role_policy.guardduty_malware]
}

resource "aws_dynamodb_table" "documents" {
  name         = "${var.project_name}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.documents.arn
  }
  point_in_time_recovery {
    enabled = true
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_sqs_queue" "dead_letter" {
  name                    = "${var.project_name}-dlq"
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "processing" {
  name                       = "${var.project_name}-processing"
  visibility_timeout_seconds = 300
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_policy" "processing_events" {
  queue_url = aws_sqs_queue.processing.id
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Sid = "AllowQuarantineS3", Effect = "Allow", Principal = { Service = "s3.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.processing.arn, Condition = { ArnEquals = { "aws:SourceArn" = aws_s3_bucket.quarantine.arn }, StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } } }] })
}

resource "aws_s3_bucket_notification" "quarantine" {
  bucket      = aws_s3_bucket.quarantine.id
  eventbridge = true
  queue {
    queue_arn = aws_sqs_queue.processing.arn
    events    = ["s3:ObjectCreated:Put"]
  }
  depends_on = [aws_sqs_queue_policy.processing_events, aws_guardduty_malware_protection_plan.quarantine]
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/aws/${var.project_name}"
  retention_in_days = 14
  kms_key_id        = aws_kms_key.documents.arn
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "${var.project_name}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cognito_user_pool" "users" {
  name = var.project_name
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 1
  }
}

resource "aws_cognito_user_pool_domain" "web" {
  domain       = "${var.project_name}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.users.id
}

resource "aws_apigatewayv2_api" "api" {
  name          = var.project_name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "worker" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.worker.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /healthz"
  target    = "integrations/${aws_apigatewayv2_integration.worker.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-jwt"
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
  }
}

resource "aws_apigatewayv2_route" "uploads" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "POST /v1/uploads"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "documents" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "ANY /v1/documents/{document_id}/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "document" {
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "ANY /v1/documents/{document_id}"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_iam_role" "worker" {
  name = "${var.project_name}-worker"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "worker" {
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.app.arn}:*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectTagging", "s3:PutObject", "s3:DeleteObject"], Resource = ["${aws_s3_bucket.quarantine.arn}/*", "${aws_s3_bucket.clean.arn}/*"] },
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Scan", "dynamodb:DeleteItem"], Resource = aws_dynamodb_table.documents.arn },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.documents.arn },
      { Effect = "Allow", Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.processing.arn },
      { Effect = "Allow", Action = ["textract:DetectDocumentText", "textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection"], Resource = "arn:aws:textract:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*" },
      { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}" }
    ]
  })
}

resource "aws_lambda_function" "worker" {
  function_name    = "${var.project_name}-worker"
  role             = aws_iam_role.worker.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.worker.output_path
  source_code_hash = data.archive_file.worker.output_base64sha256
  timeout          = 30
  environment { variables = { DOCUMENT_TABLE = aws_dynamodb_table.documents.name, ENABLE_EXPENSIVE_AI = tostring(var.enable_expensive_ai), REQUIRE_MALWARE_TAG = "true", QUARANTINE_BUCKET = aws_s3_bucket.quarantine.bucket, CLEAN_BUCKET = aws_s3_bucket.clean.bucket, PROCESSING_QUEUE_URL = aws_sqs_queue.processing.url } }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

resource "aws_lambda_event_source_mapping" "processing" {
  event_source_arn        = aws_sqs_queue.processing.arn
  function_name           = aws_lambda_function.worker.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.project_name}-web"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email"]
  callback_urls                        = [var.ui_callback_url]
  logout_urls                          = [var.ui_callback_url]
  supported_identity_providers         = ["COGNITO"]
}

resource "aws_cloudfront_distribution" "ui" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "Private UI origin; workflow uploads the built artifact before smoke"
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "private-ui"
    viewer_protocol_policy = "redirect-to-https"
  }
  origin {
    domain_name              = aws_s3_bucket.ui.bucket_regional_domain_name
    origin_id                = "private-ui"
    origin_access_control_id = aws_cloudfront_origin_access_control.ui.id
  }
  origin {
    domain_name = replace(aws_apigatewayv2_api.api.api_endpoint, "https://", "")
    origin_id   = "api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  ordered_cache_behavior {
    path_pattern           = "/v1/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type", "Idempotency-Key", "Tenant-Id"]
      cookies { forward = "all" }
    }
  }
  ordered_cache_behavior {
    path_pattern           = "/healthz"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    forwarded_values {
      query_string = false
      headers      = []
      cookies { forward = "none" }
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_cloudfront_origin_access_control" "ui" {
  name                              = "${var.project_name}-ui-oac"
  description                       = "Private UI bucket access"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.ui.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.ui.arn } }
    }]
  })
}

output "quarantine_bucket" {
  value = aws_s3_bucket.quarantine.bucket
}

output "clean_bucket" {
  value = aws_s3_bucket.clean.bucket
}

output "ui_bucket" { value = aws_s3_bucket.ui.bucket }
output "cloudfront_domain_name" { value = aws_cloudfront_distribution.ui.domain_name }
output "cloudfront_distribution_id" { value = aws_cloudfront_distribution.ui.id }

output "processing_queue" {
  value = aws_sqs_queue.processing.url
}

output "api_url" { value = aws_apigatewayv2_api.api.api_endpoint }
output "user_pool_id" { value = aws_cognito_user_pool.users.id }
output "cognito_client_id" { value = aws_cognito_user_pool_client.web.id }
output "cognito_domain" { value = "https://${aws_cognito_user_pool_domain.web.domain}.auth.${var.aws_region}.amazoncognito.com" }
