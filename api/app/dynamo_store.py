from __future__ import annotations

import os
import time
import uuid
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.types import Binary
from botocore.exceptions import ClientError

from .domain import AuditEvent, Document, DocumentState, UploadRequest, now


def _json(value: Any) -> Any:
    if isinstance(value, Binary): return bytes(value)
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, list): return [_json(item) for item in value]
    if isinstance(value, dict): return {key: _json(item) for key, item in value.items()}
    return value

def _ddb(value: Any) -> Any:
    if isinstance(value, float): return Decimal(str(value))
    if isinstance(value, dict): return {key: _ddb(item) for key, item in value.items()}
    if isinstance(value, list): return [_ddb(item) for item in value]
    return value


class DynamoDocumentStore:
    """DynamoDB Local/AWS-compatible document, audit, and idempotency repository."""
    def __init__(self, ttl_hours: int = 24):
        self.table_name = os.getenv("DYNAMODB_TABLE", "sdi-documents")
        self.client = boto3.client("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"), region_name=os.getenv("AWS_REGION", "eu-west-1"), aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "local"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "local"))
        self.table = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"), region_name=os.getenv("AWS_REGION", "eu-west-1"), aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "local"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "local")).Table(self.table_name)
        self.ttl_hours = ttl_hours
        self._bootstrap()

    def _bootstrap(self) -> None:
        try:
            self.client.describe_table(TableName=self.table_name); return
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException": raise
        try: self.client.create_table(TableName=self.table_name, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceInUseException": raise
        self.client.get_waiter("table_exists").wait(TableName=self.table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})

    def create(self, request: UploadRequest, key: str | None = None) -> Document:
        if key:
            existing = self.table.get_item(Key={"id": f"idem#{request.tenant_id}#{key}"}).get("Item")
            if existing: return self.get(existing["document_id"], request.tenant_id)
        document_id = str(uuid.uuid4()); timestamp = now(); document = Document(id=document_id, tenant_id=request.tenant_id, filename=request.filename, content_type=request.content_type, size=request.size, state=DocumentState.UPLOADED, created_at=timestamp, updated_at=timestamp, expires_at=timestamp + __import__("datetime").timedelta(hours=self.ttl_hours), declared_sha256=request.sha256)
        self.table.put_item(Item=_ddb(document.model_dump() | {"id": document_id, "entity": "document", "created_at": timestamp.isoformat(), "updated_at": timestamp.isoformat(), "expires_at": int(document.expires_at.timestamp())}))
        if key: self.table.put_item(Item={"id": f"idem#{request.tenant_id}#{key}", "entity": "idempotency", "document_id": document_id, "tenant_id": request.tenant_id, "expires_at": int(document.expires_at.timestamp())})
        self.event(document_id, "UPLOADED", "system", {"filename": request.filename}); return document

    def get(self, document_id: str, tenant_id: str = "demo-tenant") -> Document:
        item = self.table.get_item(Key={"id": document_id}).get("Item")
        if not item or item.get("tenant_id") != tenant_id: raise KeyError(document_id)
        item = _json(item); item.pop("entity", None); item["created_at"] = item["created_at"]; item["updated_at"] = item["updated_at"]; item["expires_at"] = __import__("datetime").datetime.fromtimestamp(int(item["expires_at"]), __import__("datetime").timezone.utc)
        return Document.model_validate(item)

    def save(self, document: Document) -> Document:
        document.updated_at = now(); self.table.put_item(Item=_ddb(document.model_dump() | {"id": document.id, "entity": "document", "created_at": document.created_at.isoformat(), "updated_at": document.updated_at.isoformat(), "expires_at": int(document.expires_at.timestamp())})); return document

    def event(self, document_id: str, event: str, actor: str, detail: dict[str, Any]) -> None:
        item = self.table.get_item(Key={"id": document_id}).get("Item")
        if not item: raise KeyError(document_id)
        self.table.put_item(Item=_ddb({"id": f"audit#{document_id}#{time.time_ns()}", "entity": "audit", "document_id": document_id, "tenant_id": item["tenant_id"], "event": event, "actor": actor, "at": now().isoformat(), "detail": detail}))

    def audit(self, document_id: str) -> list[AuditEvent]:
        items = self.table.scan(FilterExpression="entity = :entity AND document_id = :document", ExpressionAttributeValues={":entity": "audit", ":document": document_id}).get("Items", [])
        return [AuditEvent(id=item["id"], document_id=document_id, tenant_id=item["tenant_id"], event=item["event"], actor=item["actor"], at=item["at"], detail=_json(item.get("detail", {}))) for item in items]

    def delete(self, document_id: str) -> None:
        document = self.table.get_item(Key={"id": document_id}).get("Item")
        if not document: return
        self.event(document_id, "DELETED", "user", {})
        related = self.table.scan(FilterExpression="document_id = :document", ExpressionAttributeValues={":document": document_id}).get("Items", [])
        for item in related:
            self.table.delete_item(Key={"id": item["id"]})
        for item in self.table.scan(FilterExpression="entity = :entity AND tenant_id = :tenant", ExpressionAttributeValues={":entity": "idempotency", ":tenant": document["tenant_id"]}).get("Items", []):
            if item.get("document_id") == document_id: self.table.delete_item(Key={"id": item["id"]})
        self.table.delete_item(Key={"id": document_id})
