from __future__ import annotations

import os
from typing import Protocol

class ObjectStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...

class BotoObjectStore:
    def __init__(self, bucket: str | None = None) -> None:
        import boto3
        self.bucket = bucket or os.getenv("OBJECT_STORE_BUCKET", "sdi-quarantine")
        self.client = boto3.client("s3", endpoint_url=os.getenv("OBJECT_STORE_ENDPOINT"), aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"), aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"), region_name=os.getenv("AWS_REGION", "eu-west-1"))
    def put(self, key: str, content: bytes, content_type: str) -> None:
        options = {"Bucket": self.bucket, "Key": key, "Body": content, "ContentType": content_type}
        if not os.getenv("OBJECT_STORE_ENDPOINT", "").startswith("http://minio"):
            options["ServerSideEncryption"] = "aws:kms"
        self.client.put_object(**options)
    def get(self, key: str) -> bytes: return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

def object_store(bucket: str | None = None) -> ObjectStore | None:
    return BotoObjectStore(bucket) if os.getenv("OBJECT_STORE_ENDPOINT") else None
