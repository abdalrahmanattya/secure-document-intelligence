from __future__ import annotations

import os
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from .adapters import extract_with_policy, scanner, text_extractor
from .domain import ALLOWED_TYPES, MAX_BYTES, DocumentState, DocumentStore, ReviewRequest, UploadRequest, digest
from .queue import Job, JobQueue
from .queue import DynamoJobQueue
from .dynamo_store import DynamoDocumentStore
from .object_store import object_store

app = FastAPI(title="Secure Document Intelligence", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")], allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"])
store = DynamoDocumentStore(ttl_hours=int(os.getenv("RETENTION_HOURS", "24"))) if os.getenv("STORE_BACKEND") == "dynamodb" else DocumentStore(ttl_hours=int(os.getenv("RETENTION_HOURS", "24")), state_path=os.getenv("STATE_PATH"))
queue = DynamoJobQueue() if os.getenv("QUEUE_BACKEND") == "dynamodb" else JobQueue(max_attempts=int(os.getenv("MAX_ATTEMPTS", "3")))
blob_store = object_store()
clean_blob_store = object_store(os.getenv("OBJECT_STORE_CLEAN_BUCKET", "sdi-clean"))

def document_or_404(document_id: str, tenant_id: str):
    try: return store.get(document_id, tenant_id)
    except KeyError: raise HTTPException(status_code=404, detail="document not found")

def delete_object_if_present(configured_store, key: str) -> None:
    if not configured_store:
        return
    try:
        configured_store.delete(key)
    except Exception as exc:
        # S3-compatible adapters normally make DELETE absent-key safe, but
        # tolerate the standard not-found error for alternate implementations.
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"} or getattr(exc, "status_code", None) == 404:
            return
        raise

@app.get("/healthz")
def healthz(): return {"status": "ok", "service": "secure-document-intelligence", "local_mode": True}

@app.post("/v1/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(payload: UploadRequest, idempotency_key: Annotated[str | None, Header()] = None):
    document = store.create(payload, idempotency_key)
    upload = {"method": "PUT", "url": f"/v1/documents/{document.id}/content", "headers": {"content-type": document.content_type, "x-upload-sha256": document.declared_sha256}, "size": document.size, "sha256": document.declared_sha256, "expires_in_seconds": 900}
    return {"document": document.public(), "upload": upload, "upload_url": upload["url"], "expires_in_seconds": 900, "allowed_content_types": sorted(ALLOWED_TYPES), "max_bytes": MAX_BYTES}

@app.put("/v1/documents/{document_id}/content")
async def upload_content(document_id: str, request: Request, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    document = document_or_404(document_id, tenant_id); body = await request.body()
    if len(body) != document.size or len(body) > MAX_BYTES: raise HTTPException(status_code=413, detail="body size does not match bounded upload")
    if digest(body) != document.declared_sha256: raise HTTPException(status_code=422, detail="body sha256 does not match declared upload digest")
    document.content = body; document.sha256 = digest(body); store.save(document); store.event(document_id, "CONTENT_UPLOADED", "user", {"sha256": document.sha256})
    if blob_store: blob_store.put(f"{tenant_id}/{document_id}", body, document.content_type); store.event(document_id, "QUARANTINED", "object-store", {"bucket": os.getenv("OBJECT_STORE_BUCKET", "sdi-quarantine")})
    return {"document_id": document_id, "state": document.state, "sha256": document.sha256}

@app.post("/v1/documents/{document_id}/process")
def process_document(document_id: str, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    document = document_or_404(document_id, tenant_id)
    if not document.content: raise HTTPException(status_code=409, detail="upload content before processing")
    job = queue.enqueue(document_id, tenant_id, idempotency_key=f"process#{document_id}")
    if os.getenv("ASYNC_PROCESSING") != "true": queue.run_once(process_job)
    return document_or_404(document_id, tenant_id).public() | {"job_id": job.id, "job_status": job.status}

def process_job(job: Job) -> None:
    document = document_or_404(job.document_id, job.tenant_id)
    document.state = DocumentState.SCANNING; store.save(document); store.event(job.document_id, "SCANNING", "worker", {})
    clean, signature = scanner().scan(document.content or b"")
    if not clean:
        document.state = DocumentState.REJECTED; document.rejection_reason = "malware signature detected"; store.save(document); store.event(job.document_id, "REJECTED", "clamav", {"signature": signature}); return
    document.state = DocumentState.OCR if document.content_type.startswith(("image/", "application/pdf")) else DocumentState.EXTRACTING; store.save(document); store.event(job.document_id, document.state, "ocr", {"adapter": os.getenv("ADAPTER_MODE", "fixture")})
    try:
        text = text_extractor().text(document.content or b"", document.content_type)
        document.extraction = extract_with_policy(text, document.filename)
        document.state = DocumentState.NEEDS_REVIEW if any(item.confidence < 0.8 for item in document.extraction) else DocumentState.APPROVED
        store.save(document); store.event(job.document_id, document.state, "extractor", {"fields": len(document.extraction)})
    except PermissionError as exc:
        document.state = DocumentState.NEEDS_REVIEW; document.rejection_reason = str(exc); store.save(document); store.event(job.document_id, "NEEDS_REVIEW", "policy", {"reason": str(exc)})
    except Exception as exc:
        document.state = DocumentState.FAILED; document.rejection_reason = str(exc); store.save(document); store.event(job.document_id, "FAILED", "worker", {"retryable": False})

@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    try: job = queue.get(job_id)
    except KeyError: raise HTTPException(status_code=404, detail="job not found")
    return job.__dict__

@app.post("/v1/work/worker")
def run_worker():
    if isinstance(queue, DynamoJobQueue):
        job = queue.claim()
        if not job: return {"processed": None}
        try:
            process_job(job)
            if store.get(job.document_id, job.tenant_id).state == DocumentState.FAILED: raise RuntimeError("document processing failed")
            queue.finish(job)
        except Exception as error: queue.finish(job, str(error))
    else: job = queue.run_once(process_job)
    return {"processed": job.__dict__ if job else None, "dlq_depth": len(queue.dlq)}

@app.get("/v1/work/dlq")
def get_dlq():
    jobs = [queue.get(job_id).__dict__ for job_id in queue.dlq] if isinstance(queue, DynamoJobQueue) else [queue.jobs[job_id].__dict__ for job_id in queue.dlq]
    return {"depth": len(jobs), "jobs": jobs}

@app.get("/v1/documents/{document_id}")
def get_document(document_id: str, tenant_id: Annotated[str, Header()] = "demo-tenant"): return document_or_404(document_id, tenant_id).public()

@app.get("/v1/documents/{document_id}/extractions")
def get_extractions(document_id: str, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    doc = document_or_404(document_id, tenant_id); return {"document_id": document_id, "items": [item.model_dump(mode="json") for item in doc.extraction]}

@app.post("/v1/documents/{document_id}/reviews")
def review(document_id: str, payload: ReviewRequest, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    document = document_or_404(document_id, tenant_id)
    if document.state not in {DocumentState.NEEDS_REVIEW, DocumentState.APPROVED}: raise HTTPException(status_code=409, detail="document is not reviewable")
    by_name = {item.field: item for item in document.extraction}
    for field, value in payload.corrections.items():
        if field in by_name: by_name[field].value = value; by_name[field].confidence = 1.0; by_name[field].source = f"human review: {payload.reviewer}"; by_name[field].method = "human-review"
    document.state = payload.decision; store.save(document)
    if payload.decision == DocumentState.APPROVED and clean_blob_store and document.content:
        clean_blob_store.put(f"{tenant_id}/{document_id}", document.content, document.content_type); store.event(document_id, "PROMOTED_CLEAN", "object-store", {"bucket": os.getenv("OBJECT_STORE_CLEAN_BUCKET", "sdi-clean")})
    store.event(document_id, "REVIEWED", payload.reviewer, {"decision": payload.decision, "comment": payload.comment}); return document.public()

@app.get("/v1/documents/{document_id}/audit-events")
def audit(document_id: str, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    document_or_404(document_id, tenant_id); return {"document_id": document_id, "events": [event.model_dump(mode="json") for event in store.audit(document_id)]}

@app.delete("/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, tenant_id: Annotated[str, Header()] = "demo-tenant"):
    document_or_404(document_id, tenant_id)
    key = f"{tenant_id}/{document_id}"
    try:
        # Remove both representations before deleting metadata. Each backend
        # must treat an absent object as success so retries remain idempotent.
        for configured_store in (blob_store, clean_blob_store):
            delete_object_if_present(configured_store, key)
    except Exception as exc:
        # Keep the document and audit trail intact when either object store
        # cannot be cleaned up; a later request can safely retry the operation.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="object-store deletion failed") from exc
    store.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
