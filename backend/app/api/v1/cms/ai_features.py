from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_graph import DocumentGraph
from app.models.document_job import DocumentJob
from app.models.document_recommendation import DocumentRecommendation
from app.models.document_summary import DocumentSummary
from app.schemas.cms_ai import (
    GraphResponse,
    JobRequestResponse,
    JobStatusResponse,
    QARequest,
    QARequestResponse,
    RecommendationItem,
    RecommendationResponse,
    SearchRequest,
    SearchRequestResponse,
    SearchResponse,
    SearchResult,
    SummaryRequest,
    SummaryResponse,
)


router = APIRouter()


def get_owned_document(db: Session, document_id: int, user_id: int) -> Document:
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.is_deleted == False,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return document


def get_latest_summary(db: Session, document_id: int) -> DocumentSummary | None:
    return (
        db.query(DocumentSummary)
        .filter(DocumentSummary.document_id == document_id)
        .order_by(DocumentSummary.created_at.desc())
        .first()
    )


def create_ai_job(
    db: Session,
    document: Document,
    user_id: int,
    job_type: str,
    payload: dict | None = None,
) -> DocumentJob:
    job = DocumentJob(
        document_id=document.id,
        job_type=job_type,
        requested_by_user_id=user_id,
        payload=payload or {},
    )
    db.add(job)

    if document.status in ["uploaded", "failed"]:
        document.status = "processing"

    db.commit()
    db.refresh(job)
    return job


def create_global_ai_job(
    db: Session,
    user_id: int,
    job_type: str,
    payload: dict | None = None,
) -> DocumentJob:
    job = DocumentJob(
        document_id=None,
        job_type=job_type,
        requested_by_user_id=user_id,
        payload=payload or {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def serialize_job(job: DocumentJob) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        document_id=job.document_id,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        error_message=job.error_message,
        retry_count=job.retry_count or 0,
        created_at=job.created_at,
        last_started_at=job.last_started_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/documents/{document_id}/process/request",
    response_model=JobRequestResponse,
)
def request_document_processing(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)
    job = create_ai_job(
        db=db,
        document=document,
        user_id=current_user.id,
        job_type="process_document",
        payload={"document_id": document.id},
    )

    return {
        "document_id": document.id,
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "message": "Document processing queued for AI worker",
    }


@router.post(
    "/documents/{document_id}/summary/request",
    response_model=QARequestResponse,
)
def request_summary(
    document_id: int,
    payload: SummaryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)
    job = create_ai_job(
        db=db,
        document=document,
        user_id=current_user.id,
        job_type="summary",
        payload={"level": payload.level},
    )

    return {
        "document_id": document.id,
        "question": f"summary:{payload.level}",
        "status": "accepted",
        "job_id": job.id,
        "message": "Summary request queued for AI service",
    }


@router.get("/documents/{document_id}/summary", response_model=SummaryResponse)
def get_summary(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)
    summary = get_latest_summary(db, document.id)

    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")

    return {
        "document_id": document.id,
        "summary_short": summary.summary_short,
        "summary_medium": summary.summary_medium,
        "summary_long": summary.summary_long,
        "created_at": summary.created_at,
    }


@router.post("/documents/{document_id}/qa/request", response_model=QARequestResponse)
def request_qa_answer(
    document_id: int,
    payload: QARequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)
    job = create_ai_job(
        db=db,
        document=document,
        user_id=current_user.id,
        job_type="qa",
        payload={"question": payload.question},
    )

    return {
        "document_id": document.id,
        "question": payload.question,
        "status": "accepted",
        "job_id": job.id,
        "message": "Question accepted; AI service should answer via internal contract",
    }


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_ai_job_status(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = (
        db.query(DocumentJob)
        .join(Document, Document.id == DocumentJob.document_id)
        .filter(
            DocumentJob.id == job_id,
            Document.user_id == current_user.id,
            Document.is_deleted == False,
        )
        .first()
    )

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return serialize_job(job)


@router.post("/documents/{document_id}/search", response_model=SearchResponse)
def search_document(
    document_id: int,
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document.id,
            DocumentChunk.content.ilike(f"%{payload.query}%"),
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(payload.limit)
        .all()
    )

    return {
        "query": payload.query,
        "items": [
            SearchResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=None,
                embedding_available=chunk.embedding is not None,
            )
            for chunk in chunks
        ],
    }


@router.post(
    "/documents/{document_id}/search/request",
    response_model=SearchRequestResponse,
)
def request_document_search(
    document_id: int,
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)
    job = create_ai_job(
        db=db,
        document=document,
        user_id=current_user.id,
        job_type="search",
        payload={
            "query": payload.query,
            "limit": payload.limit,
            "document_id": document.id,
        },
    )

    return {
        "query": payload.query,
        "status": job.status,
        "message": "Search request queued for AI worker",
        "job_id": job.id,
        "job_type": job.job_type,
    }


@router.post("/search", response_model=SearchResponse)
def search_my_documents(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    chunks = (
        db.query(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.user_id == current_user.id,
            Document.is_deleted == False,
            DocumentChunk.content.ilike(f"%{payload.query}%"),
        )
        .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(payload.limit)
        .all()
    )

    return {
        "query": payload.query,
        "items": [
            SearchResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=None,
                embedding_available=chunk.embedding is not None,
            )
            for chunk in chunks
        ],
    }


@router.post("/search/request", response_model=SearchRequestResponse)
def request_search_my_documents(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = create_global_ai_job(
        db=db,
        user_id=current_user.id,
        job_type="search",
        payload={
            "query": payload.query,
            "limit": payload.limit,
            "user_id": current_user.id,
        },
    )

    return {
        "query": payload.query,
        "status": job.status,
        "message": "Search request queued for AI worker",
        "job_id": job.id,
        "job_type": job.job_type,
    }


@router.get("/documents/{document_id}/graph", response_model=GraphResponse)
def get_knowledge_graph(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)

    graph = (
        db.query(DocumentGraph)
        .filter(DocumentGraph.document_id == document.id)
        .first()
    )

    if not graph:
        return {
            "document_id": document.id,
            "nodes": [],
            "edges": [],
            "updated_at": None,
        }

    return {
        "document_id": document.id,
        "nodes": graph.nodes or [],
        "edges": graph.edges or [],
        "updated_at": graph.updated_at,
    }


@router.get(
    "/documents/{document_id}/recommendations",
    response_model=RecommendationResponse,
)
def get_recommendations(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    document = get_owned_document(db, document_id, current_user.id)

    recommendations = (
        db.query(DocumentRecommendation)
        .filter(DocumentRecommendation.document_id == document.id)
        .order_by(DocumentRecommendation.score.desc().nullslast())
        .all()
    )

    return {
        "document_id": document.id,
        "items": [
            RecommendationItem(
                id=item.id,
                recommended_document_id=item.recommended_document_id,
                title=item.title,
                reason=item.reason,
                score=item.score,
                source=item.source,
                external_url=item.external_url,
            )
            for item in recommendations
        ],
    }
