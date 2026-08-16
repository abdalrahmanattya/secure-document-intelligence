from __future__ import annotations

import hashlib
import json
import base64
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "text/plain", "image/png", "image/jpeg"}

def now() -> datetime:
    return datetime.now(timezone.utc)

class DocumentState(str):
    UPLOADED = "UPLOADED"; SCANNING = "SCANNING"; REJECTED = "REJECTED"; OCR = "OCR"
    EXTRACTING = "EXTRACTING"; NEEDS_REVIEW = "NEEDS_REVIEW"; APPROVED = "APPROVED"
    FAILED = "FAILED"; EXPIRED = "EXPIRED"

class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=160)
    content_type: str
    size: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(min_length=64, max_length=64)
    tenant_id: str = Field(default="demo-tenant", min_length=1, max_length=80)
    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if ".." in value or "/" in value or "\\" in value: raise ValueError("filename must not contain path components")
        return value
    @field_validator("content_type")
    @classmethod
    def supported_type(cls, value: str) -> str:
        if value not in ALLOWED_TYPES: raise ValueError("unsupported content type")
        return value
    @field_validator("sha256")
    @classmethod
    def valid_digest(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value): raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return value.lower()

class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    decision: str
    corrections: dict[str, Any] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=2000)
    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"APPROVED", "REJECTED"}: raise ValueError("decision must be APPROVED or REJECTED")
        return value

class Extraction(BaseModel):
    field: str; value: Any; confidence: float = Field(ge=0, le=1); source: str = Field(min_length=1); method: str

class Document(BaseModel):
    id: str; tenant_id: str; filename: str; content_type: str; size: int; state: str
    created_at: datetime; updated_at: datetime; expires_at: datetime; declared_sha256: str = ""; sha256: str | None = None
    extraction: list[Extraction] = Field(default_factory=list); rejection_reason: str | None = None; content: bytes | None = None
    def public(self) -> dict[str, Any]: return self.model_dump(mode="json", exclude={"content"})

class AuditEvent(BaseModel):
    id: str; document_id: str; tenant_id: str; event: str; actor: str; at: datetime; detail: dict[str, Any] = Field(default_factory=dict)

class DocumentStore:
    """Thread-safe local store; AWS adapters implement the same domain contract."""
    def __init__(self, ttl_hours: int = 24, state_path: str | None = None):
        self._documents: dict[str, Document] = {}; self._audit: dict[str, list[AuditEvent]] = {}; self._idempotency: dict[str, str] = {}
        self._lock = threading.RLock(); self.ttl = timedelta(hours=ttl_hours); self.state_path = state_path
        if state_path: self._load()
    def _persist(self) -> None:
        if not self.state_path: return
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        payload = {"documents": [doc.model_dump(mode="json") | {"content": base64.b64encode(doc.content).decode() if doc.content else None} for doc in self._documents.values()],
                   "audit": {key: [event.model_dump(mode="json") for event in events] for key, events in self._audit.items()}, "idempotency": self._idempotency}
        temporary = f"{self.state_path}.tmp"; open(temporary, "w", encoding="utf-8").write(json.dumps(payload)); os.replace(temporary, self.state_path)
    def _load(self) -> None:
        try:
            payload = json.load(open(self.state_path, encoding="utf-8"))
            for raw in payload.get("documents", []):
                content = raw.pop("content", None); raw["content"] = base64.b64decode(content) if content else None
                self._documents[raw["id"]] = Document.model_validate(raw)
            for key, events in payload.get("audit", {}).items(): self._audit[key] = [AuditEvent.model_validate(event) for event in events]
            self._idempotency.update(payload.get("idempotency", {}))
        except FileNotFoundError: return
    def create(self, request: UploadRequest, key: str | None = None) -> Document:
        with self._lock:
            if key and key in self._idempotency: return self._documents[self._idempotency[key]]
            document_id = str(uuid.uuid4()); timestamp = now()
            document = Document(id=document_id, tenant_id=request.tenant_id, filename=request.filename, content_type=request.content_type,
                                size=request.size, state=DocumentState.UPLOADED, created_at=timestamp, updated_at=timestamp, expires_at=timestamp + self.ttl, declared_sha256=request.sha256)
            self._documents[document_id] = document; self._audit[document_id] = []
            if key: self._idempotency[key] = document_id
            self.event(document_id, "UPLOADED", "system", {"filename": request.filename}); self._persist(); return document
    def get(self, document_id: str, tenant_id: str = "demo-tenant") -> Document:
        with self._lock:
            document = self._documents.get(document_id)
            if not document or document.tenant_id != tenant_id: raise KeyError(document_id)
            if document.state not in {DocumentState.EXPIRED, DocumentState.REJECTED} and document.expires_at <= now():
                document.state = DocumentState.EXPIRED; document.updated_at = now(); self.event(document_id, "EXPIRED", "retention", {}); self._persist()
            return document
    def save(self, document: Document) -> Document:
        with self._lock: document.updated_at = now(); self._documents[document.id] = document; self._persist(); return document
    def event(self, document_id: str, event: str, actor: str, detail: dict[str, Any]) -> None:
        doc = self._documents.get(document_id)
        if doc: self._audit.setdefault(document_id, []).append(AuditEvent(id=str(uuid.uuid4()), document_id=document_id, tenant_id=doc.tenant_id, event=event, actor=actor, at=now(), detail=detail)); self._persist()
    def audit(self, document_id: str) -> list[AuditEvent]: return list(self._audit.get(document_id, []))
    def delete(self, document_id: str) -> None:
        with self._lock:
            doc = self._documents.get(document_id)
            if doc:
                self._documents.pop(document_id, None)
                self._audit.pop(document_id, None)
                for key, value in list(self._idempotency.items()):
                    if value == document_id: self._idempotency.pop(key, None)
                self._persist()

def contains_prompt_injection(text: str) -> bool:
    patterns = (r"ignore\s+(all\s+)?previous", r"system\s+prompt", r"developer\s+message", r"reveal\s+(your|the)\s+instructions", r"jailbreak")
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

def extract_fields(text: str, filename: str) -> list[Extraction]:
    if len(text.encode("utf-8")) > MAX_BYTES: raise ValueError("document exceeds extraction limit")
    if contains_prompt_injection(text): raise PermissionError("untrusted document contains an instruction-like payload")
    fields: list[Extraction] = []
    patterns = {"invoice_number": r"(?:invoice\s*(?:number|no|#)?|inv)[\s:#-]*([A-Z0-9][A-Z0-9-]{2,})", "total": r"(?:total|amount\s+due)[\s:$]*([0-9][0-9,]*(?:\.[0-9]{2})?)", "date": r"(?:invoice\s+date|date)[\s:=-]*(\d{4}-\d{2}-\d{2})", "email": r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"}
    for field, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1); source = text[max(0, match.start() - 30): min(len(text), match.end() + 30)].strip()
            fields.append(Extraction(field=field, value=value.replace(",", "") if field == "total" else value, confidence=0.97, source=f"{filename}: {source}", method="deterministic-regex"))
    if not fields: fields.append(Extraction(field="document_type", value="unclassified", confidence=0.45, source=f"{filename}: no supported fields found", method="deterministic-fallback"))
    return fields

def digest(content: bytes) -> str: return hashlib.sha256(content).hexdigest()
