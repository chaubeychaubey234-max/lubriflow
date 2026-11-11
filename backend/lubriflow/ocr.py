import re
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .auth import staff, role
from .config import settings
from .db import database
from .domain import require, get
from .repository import tenant_lock, load, save
from .storage import read_document

router = APIRouter(prefix="/api/ocr")


def endpoint():
    cfg = settings()
    require(
        bool(cfg.azure_document_key)
        and bool(
            re.fullmatch(
                r"https://[a-zA-Z0-9-]+\.cognitiveservices\.azure\.com/?", cfg.azure_document_endpoint
            )
        ),
        "Configure the Azure document endpoint and key on the server.",
    )
    return cfg.azure_document_endpoint.rstrip("/")


class OCRRequest(BaseModel):
    document: str
    action: str


@router.get("")
def status(user=Depends(staff), db=Depends(database)):
    role(user, "admin", "finance")
    s = load(db, tenant_lock(db, user.tenant_id))
    return dict(
        configured=bool(settings().azure_document_endpoint and settings().azure_document_key),
        jobs=[
            dict(
                document=d["id"],
                name=d["name"],
                **{k: v for k, v in d.get("ocr", {}).items() if k != "operation"},
            )
            for d in s["attachments"]
        ],
    )


@router.post("")
def capture(body: OCRRequest, user=Depends(staff), db=Depends(database)):
    role(user, "admin", "finance")
    base = endpoint()
    tenant = tenant_lock(db, user.tenant_id)
    s = load(db, tenant)
    doc = get(s, "attachments", body.document)
    headers = {"Ocp-Apim-Subscription-Key": settings().azure_document_key}
    if body.action == "start":
        require(not doc.get("ocr"), "Extraction already started; check its result.")
        # Persist a reservation before an external call. Unknown outcomes are never retried blindly.
        doc["ocr"] = {"status": "Starting"}
        save(db, tenant, s)
        db.commit()
        try:
            response = httpx.post(
                base + "/documentintelligence/documentModels/prebuilt-invoice:analyze?api-version=2024-11-30",
                content=read_document(user.tenant_id, doc["key"]),
                headers={**headers, "Content-Type": doc["type"]},
                timeout=30,
                follow_redirects=False,
            )
            require(response.status_code == 202, "Provider rejected extraction.")
            operation = response.headers.get("operation-location", "")
            parsed = urlparse(operation)
            require(
                parsed.scheme == "https"
                and parsed.netloc == urlparse(base).netloc
                and parsed.path.startswith(
                    "/documentintelligence/documentModels/prebuilt-invoice/analyzeResults/"
                ),
                "Unexpected OCR result location.",
            )
            result = {"status": "Running", "operation": operation}
        except Exception:
            result = {
                "status": "Failed / outcome unknown",
                "error": "Check provider logs before retrying to avoid duplicate charges.",
            }
    else:
        require(body.action == "poll" and doc.get("ocr", {}).get("operation"), "No running extraction found.")
        operation = doc["ocr"]["operation"]
        require(
            operation.startswith(
                base + "/documentintelligence/documentModels/prebuilt-invoice/analyzeResults/"
            ),
            "Invalid OCR result location.",
        )
        response = httpx.get(operation, headers=headers, timeout=15, follow_redirects=False)
        require(
            response.status_code == 200 and len(response.content) <= 5_000_000,
            "OCR result unavailable or too large.",
        )
        out = response.json()
        result = doc["ocr"]
        if out.get("status") == "succeeded":
            documents = out.get("analyzeResult", {}).get("documents", [])
            fields = documents[0].get("fields", {}) if documents else {}
            result = dict(
                status="Ready for review",
                fields={
                    k: dict(
                        value=v.get(
                            "valueString",
                            v.get(
                                "valueDate", v.get("valueCurrency", {}).get("amount", v.get("content", ""))
                            ),
                        ),
                        confidence=v.get("confidence"),
                    )
                    for k, v in fields.items()
                    if k in {"InvoiceId", "InvoiceDate", "DueDate", "VendorName", "InvoiceTotal", "TotalTax"}
                },
            )
        elif out.get("status") == "failed":
            result = {"status": "Failed", "error": "Provider could not extract the document."}
    tenant = tenant_lock(db, user.tenant_id)
    s = load(db, tenant)
    get(s, "attachments", body.document)["ocr"] = result
    save(db, tenant, s)
    db.commit()
    return {k: v for k, v in result.items() if k != "operation"}
