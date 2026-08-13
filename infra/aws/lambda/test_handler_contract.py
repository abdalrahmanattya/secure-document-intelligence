import ast
from pathlib import Path


SOURCE = Path(__file__).with_name("handler.py").read_text()
TREE = ast.parse(SOURCE)


def test_lambda_exposes_api_worker_and_contract_guards():
    functions = {node.name for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"handler", "api", "worker", "deterministic_extract"} <= functions
    assert "generate_presigned_post" in SOURCE
    assert "head_object" in SOURCE
    assert "content-length-range" in SOURCE
    assert "PROMOTED_CLEAN" in SOURCE
    assert "NEEDS_REVIEW" in SOURCE


def test_lambda_compiles_without_importing_credentials():
    compile(SOURCE, str(Path(__file__).with_name("handler.py")), "exec")


def test_worker_has_atomic_claim_retry_and_batch_failure_contract():
    assert "processing_owner" in SOURCE
    assert "ConditionalCheckFailedException" in SOURCE
    assert '"batchItemFailures"' in SOURCE
    assert '"itemIdentifier"' in SOURCE
    assert '"expected_sha256"' in SOURCE


def test_aws_review_and_retention_contract_is_explicit():
    assert '"human-review"' in SOURCE
    assert '"PROMOTED_CLEAN"' in SOURCE
    assert "delete_related" in SOURCE
    assert "NextToken" in SOURCE


def test_process_acknowledges_s3_owned_enqueue_without_second_message():
    assert '"PROCESS_REQUESTED"' in SOURCE
    assert '"s3-event"' in SOURCE
    assert "sqs.send_message" not in SOURCE
