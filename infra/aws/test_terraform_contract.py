from pathlib import Path
import re


ROOT = Path(__file__).parent
MAIN = (ROOT / "main.tf").read_text()
HANDLER = (ROOT / "lambda" / "handler.py").read_text()


def test_private_cloudfront_serves_spa_root_and_api_origin():
    assert 'default_root_object = "index.html"' in MAIN
    assert 'origin_id   = "api"' in MAIN
    assert re.search(r'path_pattern\s*=\s*"/v1/\*"', MAIN)
    assert 'aws_s3_bucket.ui.bucket_regional_domain_name' in MAIN


def test_s3_notification_is_the_single_aws_enqueue_source():
    assert 'aws_s3_bucket_notification" "quarantine"' in MAIN
    assert 'events    = ["s3:ObjectCreated:Put"]' in MAIN
    assert '"s3:ObjectCreated->SQS"' in HANDLER
    assert 'sqs.send_message' not in HANDLER


def test_presigned_post_cors_and_encryption_permissions_are_scoped():
    assert 'resource "aws_s3_bucket_cors_configuration" "quarantine"' in MAIN
    assert 'allowed_origins = [local.ui_allowed_origin]' in MAIN
    assert 'allowed_methods = ["POST"]' in MAIN
    assert 'sqs_managed_sse_enabled    = true' in MAIN
    assert '"kms:Decrypt", "kms:GenerateDataKey"' in MAIN
    assert '"aws:SourceAccount"' in MAIN


def test_guardduty_role_matches_official_malware_protection_prerequisite():
    for action in ("events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets", "events:DescribeRule", "events:ListTargetsByRule", "s3:PutBucketNotification", "s3:GetBucketNotification", "s3:PutObjectVersionTagging", "s3:GetObjectVersionTagging"):
        assert action in MAIN
    assert '"events:ManagedBy"' in MAIN
    assert 'malware-protection-plan.guardduty.amazonaws.com' in MAIN
    assert 'malware-protection-resource-validation-object' in MAIN
    assert '"kms:ViaService"' in MAIN
    assert 'aws_iam_role_policy.guardduty_malware' in MAIN.split('resource "aws_guardduty_malware_protection_plan"', 1)[1]
    assert 'eventbridge = true' in MAIN
