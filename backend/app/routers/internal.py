from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import Document

from app.api.internal_deps import verify_internal_token

from app.models.document_summary import DocumentSummary
from pydantic import BaseModel

from app.services.document_state import can_transition

from app.models.document_job import DocumentJob

from datetime import datetime, timedelta
from app.models.worker_status import WorkerStatus



router = APIRouter()

class SummaryPayload(BaseModel):
    summary_short: str | None = None
    summary_medium: str | None = None
    summary_long: str | None = None

class WorkerHeartbeat(BaseModel):
    worker_name: str
    current_job_id: int | None = None


@router.get("/documents/{document_id}")
def get_document_for_ai(
    document_id: int,
    db: Session = Depends(get_db),
     _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(Document.id == document_id,
                Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": document.id,
        "filename": document.filename,
        "raw_text": document.raw_text,
        "status": document.status,
        "user_id": document.user_id,
    }
@router.post("/documents/{document_id}/claim")
def claim_document_for_processing(
    document_id: int,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(Document.id == document_id,
                Document.is_deleted == False
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 🔥 LOCK LOGIC
    if not can_transition(document.status, "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot claim document in status {document.status}"
        )


    document.status = "processing"
    db.commit()
    db.refresh(document)

    return {
        "message": "Document claimed",
        "status": document.status
    }

@router.post("/documents/{document_id}/summary")
def save_summary(
    document_id: int,
    payload: SummaryPayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(Document.id == document_id,
                Document.is_deleted == False
                )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    summary = DocumentSummary(
        document_id=document_id,
        summary_short=payload.summary_short,
        summary_medium=payload.summary_medium,
        summary_long=payload.summary_long,
    )

    db.add(summary)

    # update status -> processed
    document.status = "processed"

    db.commit()

    return {"message": "Summary saved"}

@router.post("/jobs/next")
def get_next_job(
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    job = (
        db.query(DocumentJob)
        .filter(DocumentJob.status == "pending")
        .order_by(DocumentJob.created_at.asc())
        .first()
    )

    if not job:
        return {"message": "No jobs"}

    job.status = "processing"
    job.last_started_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    return {
        "job_id": job.id,
        "document_id": job.document_id
    }



@router.post("/jobs/recover")
def recover_stuck_jobs(
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    timeout_minutes = 10

    stuck_jobs = (
        db.query(DocumentJob)
        .filter(
            DocumentJob.status == "processing",
            DocumentJob.last_started_at < datetime.utcnow() - timedelta(minutes=timeout_minutes),
            DocumentJob.retry_count < 3,
        )
        .all()
    )

    for job in stuck_jobs:
        job.status = "pending"
        job.retry_count += 1

    db.commit()

    return {
        "recovered_jobs": len(stuck_jobs)
    }

@router.post("/workers/heartbeat")
def worker_heartbeat(
    payload: WorkerHeartbeat,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    worker = (
        db.query(WorkerStatus)
        .filter(WorkerStatus.worker_name == payload.worker_name)
        .first()
    )

    if not worker:
        worker = WorkerStatus(
            worker_name=payload.worker_name,
            current_job_id=payload.current_job_id,
        )
        db.add(worker)
    else:
        worker.current_job_id = payload.current_job_id
        worker.last_heartbeat = datetime.utcnow()
        worker.status = "online"

    db.commit()

    return {"message": "heartbeat received"}

@router.get("/workers")
def list_workers(
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    workers = db.query(WorkerStatus).all()

    return workers

@router.get("/system/dashboard")
def system_dashboard(
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    documents_total = db.query(Document).count()

    documents_processing = (
        db.query(Document)
        .filter(Document.status == "processing")
        .count()
    )

    documents_processed = (
        db.query(Document)
        .filter(Document.status == "processed")
        .count()
    )

    queue_pending = (
        db.query(DocumentJob)
        .filter(DocumentJob.status == "pending")
        .count()
    )

    workers_online = (
        db.query(WorkerStatus)
        .count()
    )

    return {
        "documents_total": documents_total,
        "documents_processing": documents_processing,
        "documents_processed": documents_processed,
        "queue_pending": queue_pending,
        "workers_online": workers_online,
    }
