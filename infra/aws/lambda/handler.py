"""API and worker Lambda. Production extraction is deliberately split from API auth."""
import base64
import hashlib
import json
import os
import time
import re
import uuid
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "text/plain", "image/png", "image/jpeg"}

table = boto3.resource("dynamodb").Table(os.environ["DOCUMENT_TABLE"])
s3 = boto3.client("s3")
textract = boto3.client("textract")
bedrock = boto3.client("bedrock-runtime")


def response(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json", "access-control-allow-origin": os.getenv("CORS_ORIGIN", "")}, "body": json.dumps(body)}


def tenant(event):
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {}).get("sub", "anonymous")


def audit(document_id, tenant_id, name, actor, detail=None):
    table.put_item(Item={"id": f"audit#{document_id}#{time.time_ns()}", "document_id": document_id, "tenant_id": tenant_id, "entity": "audit", "event": name, "actor": actor, "at": int(time.time()), "detail": detail or {}})


def api(event):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    if method == "GET" and path == "/healthz": return response(200, {"status": "ok"})
    tid = tenant(event); parts = path.strip("/").split("/")
    if method == "POST" and path == "/v1/uploads":
        body = json.loads(event.get("body") or "{}")
        idem = event.get("headers", {}).get("idempotency-key")
        doc_id = hashlib.sha256(f"{tid}#{idem}".encode()).hexdigest()[:32] if idem else str(uuid.uuid4()); size = int(body["size"]); filename = str(body.get("filename", ""))
        expected_sha256 = str(body.get("sha256", "")).lower(); content_type = str(body.get("content_type", ""))
        if not filename or len(filename) > 160 or any(part in filename for part in ("..", "/", "\\")): return response(422, {"detail": "filename must be a safe leaf name"})
        if size < 1 or size > MAX_BYTES: return response(422, {"detail": "size must be between 1 and 10485760 bytes"})
        if content_type not in ALLOWED_TYPES: return response(422, {"detail": "unsupported content type"})
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256): return response(422, {"detail": "sha256 must be a client-declared 64-character hex digest"})
        item = {"id": doc_id, "entity": "document", "tenant_id": tid, "filename": filename, "content_type": content_type, "size": size, "expected_sha256": expected_sha256, "state": "UPLOADED", "created_at": int(time.time()), "expires_at": int(time.time()) + 86400}
        if idem: item["idempotency_key"] = f"{tid}#{idem}"
        try:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
            item = table.get_item(Key={"id": doc_id}).get("Item", item)
        key = f"{tid}/{doc_id}"; fields = {"Content-Type": content_type, "x-amz-meta-sha256": expected_sha256}; form = s3.generate_presigned_post(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key, Fields=fields, Conditions=[["content-length-range", size, size], {"Content-Type": content_type}, {"x-amz-meta-sha256": expected_sha256}], ExpiresIn=900)
        upload = form | {"method": "POST", "size": size, "sha256": expected_sha256, "expires_in_seconds": 900}; audit(doc_id, tid, "UPLOADED", tid, {"key": key, "expected_size": size, "expected_content_type": content_type, "expected_sha256": expected_sha256}); return response(201, {"document": item, "upload": upload, "expires_in_seconds": 900})
    if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "documents":
        doc_id = parts[2]; item = table.get_item(Key={"id": doc_id}).get("Item")
        if not item or item.get("tenant_id") != tid: return response(404, {"detail": "document not found"})
        if method == "GET" and len(parts) == 3: return response(200, item)
        if method == "GET" and parts[3] == "audit-events": return response(200, {"events": audit_query(doc_id, tid)})
        if method == "GET" and parts[3] == "extractions": return response(200, {"items": item.get("extraction", [])})
        if method == "POST" and parts[3] == "process":
            if item.get("state") in {"SCANNING", "EXTRACTING", "NEEDS_REVIEW", "APPROVED", "REJECTED", "FAILED", "EXPIRED"}:
                return response(202, item)
            # The quarantine S3 ObjectCreated notification is the sole AWS enqueue
            # source. This endpoint is an idempotent UI acknowledgement, avoiding a
            # second SQS record with a different processing owner.
            audit(doc_id, tid, "PROCESS_REQUESTED", tid, {"enqueue": "s3:ObjectCreated->SQS"}); return response(202, item | {"queue": "s3-event", "status": "accepted"})
        if method == "POST" and parts[3] == "reviews":
            review = json.loads(event.get("body") or "{}"); decision = review.get("decision")
            if decision not in {"APPROVED", "REJECTED"}: return response(422, {"detail": "decision must be APPROVED or REJECTED"})
            by_field = {entry.get("field"): entry for entry in item.get("extraction", [])}
            for field, correction in review.get("corrections", {}).items():
                if field not in by_field: continue
                entry = by_field[field]
                entry["value"] = correction.get("value", correction) if isinstance(correction, dict) else correction
                entry["confidence"] = 1.0
                entry["source"] = f"human review: {review.get('reviewer', tid)}"
                entry["method"] = "human-review"
            item["extraction"] = list(by_field.values()); item["state"] = decision; item["review"] = review; table.put_item(Item=item); audit(doc_id, tid, "REVIEWED", tid, review)
            if decision == "APPROVED":
                key = f"{tid}/{doc_id}"
                s3.copy_object(Bucket=os.environ["CLEAN_BUCKET"], Key=key, CopySource={"Bucket": os.environ["QUARANTINE_BUCKET"], "Key": key})
                s3.delete_object(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key); audit(doc_id, tid, "PROMOTED_CLEAN", tid, {"reason": "human approval"})
            return response(200, item)
        if method == "DELETE":
            key = f"{tid}/{doc_id}"
            for bucket in (os.environ["QUARANTINE_BUCKET"], os.environ["CLEAN_BUCKET"]):
                s3.delete_object(Bucket=bucket, Key=key)
            audit(doc_id, tid, "DELETED", tid); delete_related(doc_id, tid); return {"statusCode": 204, "body": ""}
    return response(404, {"detail": "route not found"})


def audit_query(document_id, tenant_id):
    items = table.scan(FilterExpression="document_id = :d AND tenant_id = :t", ExpressionAttributeValues={":d": document_id, ":t": tenant_id}).get("Items", [])
    return [{key: value for key, value in item.items() if key in {"id", "event", "actor", "at", "detail"}} for item in items]


def delete_related(document_id, tenant_id):
    """Remove the document and all tenant-scoped audit/idempotency/job records."""
    items = table.scan(FilterExpression="document_id = :d AND tenant_id = :t", ExpressionAttributeValues={":d": document_id, ":t": tenant_id}).get("Items", [])
    for related in items:
        table.delete_item(Key={"id": related["id"]})
    table.delete_item(Key={"id": document_id})

def deterministic_extract(text, filename):
    if re.search(r"ignore\s+(all\s+)?previous|system\s+prompt|developer\s+message|jailbreak", text, re.I):
        return [], True
    patterns = {"invoice_number": r"(?:invoice\s*(?:number|no|#)?|inv)[\s:#-]*([A-Z0-9][A-Z0-9-]{2,})", "total": r"(?:total|amount\s+due)[\s:$]*([0-9][0-9,]*(?:\.[0-9]{2})?)", "date": r"(?:invoice\s+date|date)[\s:=-]*(\d{4}-\d{2}-\d{2})", "email": r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"}
    output = []
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match: output.append({"field": field, "value": match.group(1).replace(",", "") if field == "total" else match.group(1), "confidence": 0.97, "source": f"{filename}: {match.group(0)}", "method": "deterministic-regex"})
    return output, False


def worker(event):
    """SQS worker boundary with conditional claim and per-record redrive."""
    failures = []
    for record in event.get("Records", []):
      try:
        payload = json.loads(record["body"])
        if payload.get("Records"):
            object_key = unquote_plus(payload["Records"][0]["s3"]["object"]["key"])
            tid, doc_id = object_key.split("/", 1)
        else:
            doc_id = payload["document_id"]; tid = payload["tenant_id"]
        item = table.get_item(Key={"id": doc_id}).get("Item")
        if not item: continue
        if item.get("state") in {"APPROVED", "REJECTED", "NEEDS_REVIEW", "EXPIRED"}: continue
        owner = payload.get("processing_key", f"s3#{doc_id}")
        try:
            claimed = table.update_item(Key={"id": doc_id}, UpdateExpression="SET #state = :extracting, processing_owner = :owner", ConditionExpression="(#state = :uploaded AND attribute_not_exists(processing_owner)) OR (#state = :extracting AND processing_owner = :owner)", ExpressionAttributeNames={"#state": "state"}, ExpressionAttributeValues={":extracting": "EXTRACTING", ":uploaded": "UPLOADED", ":owner": owner}, ReturnValues="ALL_NEW").get("Attributes", {})
            item.update(claimed)
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException": continue
            raise
        key = f"{tid}/{doc_id}"; metadata = s3.head_object(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key); declared_object_sha = metadata.get("Metadata", {}).get("sha256", "").lower()
        if int(metadata.get("ContentLength", -1)) != int(item.get("size", -2)) or metadata.get("ContentType") != item.get("content_type") or declared_object_sha != item.get("expected_sha256", ""):
            item["state"] = "REJECTED"; item["rejection_reason"] = "object size or content type did not match upload contract"; table.put_item(Item=item); continue
        if os.getenv("REQUIRE_MALWARE_TAG", "false").lower() == "true":
            tags = {tag["Key"]: tag["Value"] for tag in s3.get_object_tagging(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key).get("TagSet", [])}
            scan_status = tags.get("GuardDutyMalwareScanStatus")
            if scan_status in {"THREATS_FOUND", "MALICIOUS"}:
                item["state"] = "REJECTED"; item["rejection_reason"] = "GuardDuty malware protection found a threat"; table.put_item(Item=item); continue
            if scan_status != "NO_THREATS_FOUND": raise RuntimeError("malware scan pending")
        raw = s3.get_object(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key)["Body"].read()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if len(raw) != int(item["size"]) or (item.get("expected_sha256") and actual_sha256 != item["expected_sha256"]):
            item["state"] = "REJECTED"; item["rejection_reason"] = "object digest did not match record"; table.put_item(Item=item); continue
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in raw:
            item["state"] = "REJECTED"; item["rejection_reason"] = "malware signature"; table.put_item(Item=item); continue
        item["state"] = "EXTRACTING"; item["sha256"] = actual_sha256
        if os.getenv("ENABLE_EXPENSIVE_AI", "false").lower() == "true":
            if item.get("content_type") in {"image/png", "image/jpeg"}:
                ocr = textract.detect_document_text(Document={"Bytes": raw})
                lines = [block["Text"] for block in ocr.get("Blocks", []) if block.get("BlockType") == "LINE"]
                item["ocr_text"] = "\n".join(lines)
            elif item.get("content_type") == "application/pdf":
                if not item.get("textract_job_id"):
                    job = textract.start_document_text_detection(DocumentLocation={"S3Object": {"Bucket": os.environ["QUARANTINE_BUCKET"], "Name": key}})
                    item["textract_job_id"] = job["JobId"]; table.put_item(Item=item); raise RuntimeError("Textract job started; retry for completion")
                result = textract.get_document_text_detection(JobId=item["textract_job_id"])
                if result.get("JobStatus") != "SUCCEEDED": raise RuntimeError(f"Textract status: {result.get('JobStatus')}")
                blocks = result.get("Blocks", []); token = result.get("NextToken")
                while token:
                    page = textract.get_document_text_detection(JobId=item["textract_job_id"], NextToken=token); blocks.extend(page.get("Blocks", [])); token = page.get("NextToken")
                item["ocr_text"] = "\n".join(block["Text"] for block in blocks if block.get("BlockType") == "LINE")
            model_payload = json.dumps({"input": item.get("ocr_text", ""), "schema": {"invoice_number": "string", "total": "number", "date": "string"}}).encode()
            model = bedrock.invoke_model(modelId=os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"), body=model_payload, contentType="application/json", accept="application/json")
            item["model_output"] = json.loads(model["body"].read())
        extracted, injection = deterministic_extract(item.get("ocr_text", raw.decode("utf-8", "replace")), item.get("filename", "document"))
        item["extraction"] = extracted; item["state"] = "NEEDS_REVIEW" if injection or not extracted else "APPROVED"; table.put_item(Item=item); audit(doc_id, tid, "EXTRACTED", "worker", {"fields": len(extracted), "injection": injection})
        if item["state"] == "APPROVED":
            s3.copy_object(Bucket=os.environ["CLEAN_BUCKET"], Key=key, CopySource={"Bucket": os.environ["QUARANTINE_BUCKET"], "Key": key})
            s3.delete_object(Bucket=os.environ["QUARANTINE_BUCKET"], Key=key); audit(doc_id, tid, "PROMOTED_CLEAN", "worker")
      except Exception:
        failures.append({"itemIdentifier": record.get("messageId", "unknown")})
    return {"batchItemFailures": failures}


def handler(event, context):
    if event.get("Records"): return worker(event)
    return api(event)
