from __future__ import annotations

import threading
import uuid
import os
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Job:
    id: str
    document_id: str
    tenant_id: str
    attempts: int = 0
    status: str = "PENDING"
    error: str | None = None

class JobQueue:
    """Local queue contract mirroring SQS visibility, retries, and a DLQ."""
    def __init__(self, max_attempts: int = 3):
        self.jobs: dict[str, Job] = {}; self.pending: list[str] = []; self.dlq: list[str] = []; self.max_attempts = max_attempts; self.lock = threading.RLock()
    def enqueue(self, document_id: str, tenant_id: str, idempotency_key: str | None = None) -> Job:
        with self.lock:
            if idempotency_key:
                for job in self.jobs.values():
                    if getattr(job, "idempotency_key", None) == idempotency_key: return job
            job = Job(str(uuid.uuid4()), document_id, tenant_id); job.idempotency_key = idempotency_key
            self.jobs[job.id] = job; self.pending.append(job.id); return job
    def run_once(self, handler: Callable[[Job], None]) -> Job | None:
        with self.lock:
            if not self.pending: return None
            job = self.jobs[self.pending.pop(0)]; job.attempts += 1; job.status = "PROCESSING"
        try:
            handler(job); job.status = "SUCCEEDED"
        except Exception as exc:
            job.error = str(exc)
            if job.attempts < self.max_attempts: job.status = "RETRYING"; self.pending.append(job.id)
            else: job.status = "DLQ"; self.dlq.append(job.id)
        return job
    def get(self, job_id: str) -> Job:
        with self.lock: return self.jobs[job_id]

class DynamoJobQueue:
    """Durable SQS-compatible queue contract using DynamoDB Local for Compose."""
    def __init__(self, table_name: str | None = None):
        import boto3
        self.table_name = table_name or os.getenv("DYNAMODB_TABLE", "sdi-documents")
        self.table = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"), region_name=os.getenv("AWS_REGION", "eu-west-1"), aws_access_key_id="local", aws_secret_access_key="local").Table(self.table_name)
    def enqueue(self, document_id: str, tenant_id: str, idempotency_key: str | None = None) -> Job:
        # A stable id makes the idempotency key atomic at the DynamoDB item level;
        # a scan is intentionally not used as a check-then-write race.
        job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sdi-job:{tenant_id}:{idempotency_key}")) if idempotency_key else str(uuid.uuid4())
        job = Job(job_id, document_id, tenant_id); item = {"id": f"job#{job.id}", "entity": "job", "job_id": job.id, "document_id": document_id, "tenant_id": tenant_id, "status": "PENDING", "attempts": 0}
        if idempotency_key: item["idempotency_key"] = idempotency_key
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException": raise
            return self.get(job_id)
        return job
    def get(self, job_id: str) -> Job:
        item = self.table.get_item(Key={"id": f"job#{job_id}"}).get("Item")
        if not item: raise KeyError(job_id)
        return Job(job_id, item["document_id"], item["tenant_id"], int(item.get("attempts", 0)), item.get("status", "PENDING"), item.get("error"))
    @property
    def dlq(self) -> list[str]:
        return [item["job_id"] for item in self.table.scan(FilterExpression="entity = :e AND #status = :dlq", ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":e": "job", ":dlq": "DLQ"}).get("Items", [])]
    def claim(self) -> Job | None:
        from botocore.exceptions import ClientError
        candidates = [item for item in self.table.scan(FilterExpression="entity = :e", ExpressionAttributeValues={":e": "job"}).get("Items", []) if item.get("status") in {"PENDING", "RETRYING"}]
        for candidate in candidates:
            try:
                result = self.table.update_item(
                    Key={"id": candidate["id"]},
                    UpdateExpression="SET #status = :processing ADD attempts :one",
                    ConditionExpression="#status IN (:pending, :retrying)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":processing": "PROCESSING", ":pending": "PENDING", ":retrying": "RETRYING", ":one": 1},
                    ReturnValues="ALL_NEW",
                )
            except ClientError as error:
                if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    continue
                raise
            item = result["Attributes"]
            return Job(item["job_id"], item["document_id"], item["tenant_id"], int(item["attempts"]), item["status"])
        return None
    def finish(self, job: Job, error: str | None = None) -> None:
        item = self.table.get_item(Key={"id": f"job#{job.id}"}).get("Item", {"id": f"job#{job.id}", "entity": "job", "job_id": job.id, "document_id": job.document_id, "tenant_id": job.tenant_id})
        item["status"] = "SUCCEEDED" if not error else ("RETRYING" if job.attempts < 3 else "DLQ"); item["error"] = error or ""; self.table.put_item(Item=item)
