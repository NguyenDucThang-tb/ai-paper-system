import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.api.deps import get_current_user

from app.models.document import Document
from app.models.document_job import DocumentJob
from app.models.qa_history import QAHistory
from app.models.document_summary import DocumentSummary

from app.schemas.document import DocumentStatusUpdate
from app.services.document_state import can_transition
from app.services.event_publisher import publish_document_uploaded

from app.services.file_extractor import (
    extract_text_from_pdf,
    extract_text_from_txt,
    extract_text_from_docx,
)


router = APIRouter()

UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ======================================================
# SCHEMAS
# ======================================================

class QAPayload(BaseModel):
    question: str
    answer: str
    sources: str | None = None


# ======================================================
# UPLOAD DOCUMENT
# ======================================================

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # save file
    file_location = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_location, "wb") as buffer:
        buffer.write(await file.read())

    # create document
    document = Document(
        filename=file.filename,
        file_type=file.content_type,
        user_id=current_user.id,
        status="uploaded",
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # extract text
    if file.filename.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_location)
    elif file.filename.endswith(".txt"):
        raw_text = extract_text_from_txt(file_location)
    elif file.filename.endswith(".docx"):
        raw_text = extract_text_from_docx(file_location)
    else:
        raw_text = ""

    document.raw_text = raw_text
    db.commit()
    db.refresh(document)

    # 🔥 create async job
    job = DocumentJob(document_id=document.id)
    db.add(job)
    db.commit()

    # event publish
    publish_document_uploaded(
        document_id=document.id,
        user_id=current_user.id
    )

    return {
        "message": "Upload successful",
        "document_id": document.id,
    }


# ======================================================
# LIST DOCUMENTS (PAGINATION)
# ======================================================

@router.get("/")
def list_documents(
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if page < 1:
        page = 1

    page_size = min(max(page_size, 1), 50)

    offset = (page - 1) * page_size

    documents = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    total = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .count()
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": documents,
    }


# ======================================================
# DOCUMENT DETAIL
# ======================================================

@router.get("/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return document


# ======================================================
# SOFT DELETE
# ======================================================

@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document.is_deleted = True
    db.commit()

    return {"message": "Document deleted successfully"}


# ======================================================
# STATUS UPDATE (STATE MACHINE)
# ======================================================

@router.patch("/{document_id}/status")
def update_document_status(
    document_id: int,
    payload: DocumentStatusUpdate,
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not can_transition(document.status, payload.status):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: {document.status} -> {payload.status}",
        )

    document.status = payload.status
    db.commit()

    return {"message": "Status updated", "status": document.status}


@router.get("/{document_id}/status")
def get_document_status(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"document_id": document.id, "status": document.status}


# ======================================================
# QA HISTORY
# ======================================================

@router.post("/{document_id}/qa")
def save_qa_history(
    document_id: int,
    payload: QAPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    qa = QAHistory(
        user_id=current_user.id,
        document_id=document_id,
        question=payload.question,
        answer=payload.answer,
        sources=payload.sources,
    )

    db.add(qa)
    db.commit()

    return {"message": "Q&A saved"}


@router.get("/{document_id}/qa")
def get_qa_history(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return (
        db.query(QAHistory)
        .filter(
            QAHistory.document_id == document_id,
            QAHistory.user_id == current_user.id,
        )
        .order_by(QAHistory.created_at.desc())
        .all()
    )


# ======================================================
# TIMELINE
# ======================================================

@router.get("/{document_id}/timeline")
def get_document_timeline(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    timeline = []

    timeline.append({
        "type": "uploaded",
        "timestamp": document.created_at,
        "detail": "Document uploaded"
    })

    summaries = (
        db.query(DocumentSummary)
        .filter(DocumentSummary.document_id == document_id)
        .all()
    )

    for s in summaries:
        timeline.append({
            "type": "summary_generated",
            "timestamp": s.created_at,
            "detail": "Summary generated"
        })

    qa_history = (
        db.query(QAHistory)
        .filter(
            QAHistory.document_id == document_id,
            QAHistory.user_id == current_user.id,
        )
        .all()
    )

    for qa in qa_history:
        timeline.append({
            "type": "qa",
            "timestamp": qa.created_at,
            "detail": qa.question
        })

    timeline.sort(key=lambda x: x["timestamp"])

    return {
        "document_id": document_id,
        "status": document.status,
        "timeline": timeline,
    }
