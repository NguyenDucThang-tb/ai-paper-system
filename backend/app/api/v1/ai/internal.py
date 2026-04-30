from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from app.db.session import get_db
from app.models.document import Document

from app.api.internal_deps import verify_internal_token

from app.models.document_summary import DocumentSummary
from pydantic import BaseModel, Field
from app.models.document_graph import DocumentGraph
from app.models.document_recommendation import DocumentRecommendation
from app.models.qa_history import QAHistory

from app.services.document_state import can_transition

from app.models.document_job import DocumentJob

from datetime import datetime, timedelta
from app.models.worker_status import WorkerStatus



router = APIRouter()

class SummaryPayload(BaseModel):
    job_id: int | None = None
    summary_short: str | None = None
    summary_medium: str | None = None
    summary_long: str | None = None

class QAResultPayload(BaseModel):
    job_id: int | None = None
    question: str
    answer: str
    sources: list[dict] | None = None

class GraphPayload(BaseModel):
    job_id: int | None = None
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)

class RecommendationItemPayload(BaseModel):
    recommended_document_id: int | None = None
    title: str
    reason: str | None = None
    score: float | None = None
    source: str | None = None
    external_url: str | None = None

class RecommendationsPayload(BaseModel):
    job_id: int | None = None
    items: list[RecommendationItemPayload] = Field(default_factory=list)

class WorkerHeartbeat(BaseModel):
    worker_name: str
    current_job_id: int | None = None

class JobCompletePayload(BaseModel):
    result: dict | None = None

class JobFailPayload(BaseModel):
    error_message: str
    result: dict | None = None


def mark_job_done(db: Session, job_id: int | None, result: dict | None = None):
    if not job_id:
        return None

    job = db.query(DocumentJob).filter(DocumentJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "done"
    job.result = result or {}
    job.completed_at = datetime.utcnow()
    return job


def mark_job_failed(db: Session, job_id: int, error_message: str, result: dict | None = None):
    job = db.query(DocumentJob).filter(DocumentJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "failed"
    job.error_message = error_message
    job.result = result or {}
    job.completed_at = datetime.utcnow()

    document = (
        db.query(Document)
        .filter(Document.id == job.document_id, Document.is_deleted == False)
        .first()
    )
    if document:
        document.status = "failed"

    return job


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
    mark_job_done(
        db,
        payload.job_id,
        {
            "summary_short": payload.summary_short,
            "summary_medium": payload.summary_medium,
            "summary_long": payload.summary_long,
        },
    )

    db.commit()

    return {"message": "Summary saved"}


@router.post("/documents/{document_id}/qa")
def save_qa_answer(
    document_id: int,
    payload: QAResultPayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.is_deleted == False,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    qa = QAHistory(
        user_id=document.user_id,
        document_id=document.id,
        question=payload.question,
        answer=payload.answer,
        sources=json.dumps(payload.sources or []),
    )

    db.add(qa)
    mark_job_done(
        db,
        payload.job_id,
        {
            "qa_history_id": None,
            "question": payload.question,
            "answer": payload.answer,
            "sources": payload.sources or [],
        },
    )
    db.commit()
    db.refresh(qa)

    if payload.job_id:
        job = db.query(DocumentJob).filter(DocumentJob.id == payload.job_id).first()
        if job:
            job.result = {
                "qa_history_id": qa.id,
                "question": payload.question,
                "answer": payload.answer,
                "sources": payload.sources or [],
            }
            db.commit()

    return {"message": "Q&A answer saved", "qa_history_id": qa.id}


@router.post("/documents/{document_id}/graph")
def save_knowledge_graph(
    document_id: int,
    payload: GraphPayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.is_deleted == False,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    graph = (
        db.query(DocumentGraph)
        .filter(DocumentGraph.document_id == document.id)
        .first()
    )

    if not graph:
        graph = DocumentGraph(document_id=document.id)
        db.add(graph)

    graph.nodes = payload.nodes
    graph.edges = payload.edges
    mark_job_done(
        db,
        payload.job_id,
        {"nodes": payload.nodes, "edges": payload.edges},
    )

    db.commit()

    return {"message": "Knowledge graph saved"}


@router.post("/documents/{document_id}/recommendations")
def save_recommendations(
    document_id: int,
    payload: RecommendationsPayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.is_deleted == False,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    (
        db.query(DocumentRecommendation)
        .filter(DocumentRecommendation.document_id == document.id)
        .delete()
    )

    for item in payload.items:
        db.add(
            DocumentRecommendation(
                document_id=document.id,
                recommended_document_id=item.recommended_document_id,
                title=item.title,
                reason=item.reason,
                score=item.score,
                source=item.source,
                external_url=item.external_url,
            )
        )

    mark_job_done(
        db,
        payload.job_id,
        {"count": len(payload.items)},
    )

    db.commit()

    return {
        "message": "Recommendations saved",
        "count": len(payload.items),
    }

@router.post("/jobs/next")
def get_next_job(
    job_type: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    query = db.query(DocumentJob).filter(DocumentJob.status == "pending")

    if job_type:
        query = query.filter(DocumentJob.job_type == job_type)

    job = query.order_by(DocumentJob.created_at.asc()).first()

    if not job:
        return {"message": "No jobs"}

    job.status = "processing"
    job.last_started_at = datetime.utcnow()

    document = (
        db.query(Document)
        .filter(Document.id == job.document_id, Document.is_deleted == False)
        .first()
    )
    if document and document.status in ["uploaded", "failed"]:
        document.status = "processing"

    db.commit()
    db.refresh(job)

    return {
        "job_id": job.id,
        "document_id": job.document_id,
        "job_type": job.job_type,
        "payload": job.payload or {},
    }


@router.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: int,
    payload: JobCompletePayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    job = mark_job_done(db, job_id, payload.result)

    document = (
        db.query(Document)
        .filter(Document.id == job.document_id, Document.is_deleted == False)
        .first()
    )
    if document and job.job_type == "process_document":
        document.status = "processed"

    db.commit()

    return {
        "message": "Job completed",
        "job_id": job.id,
        "status": job.status,
    }


@router.post("/jobs/{job_id}/fail")
def fail_job(
    job_id: int,
    payload: JobFailPayload,
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    job = mark_job_failed(
        db=db,
        job_id=job_id,
        error_message=payload.error_message,
        result=payload.result,
    )
    db.commit()

    return {
        "message": "Job failed",
        "job_id": job.id,
        "status": job.status,
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
