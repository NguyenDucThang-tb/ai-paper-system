from typing import List
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk


def create_chunks(
    db: Session,
    document_id: int,
    chunks: List[str],
) -> List[DocumentChunk]:
    """
    Bulk insert chunks for a document.
    chunks: list of chunk content strings
    """

    db_chunks = []

    for idx, content in enumerate(chunks):
        db_chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=idx,
            content=content,
            token_count=None,
            embedding_status="pending",
        )
        db_chunks.append(db_chunk)

    db.add_all(db_chunks)
    db.commit()

    for chunk in db_chunks:
        db.refresh(chunk)

    return db_chunks
def get_chunks_by_document(
    db: Session,
    document_id: int,
):
    """
    Get all chunks of a document ordered by chunk_index
    """
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
def get_pending_chunks(
    db: Session,
    limit: int = 10,
):
    """
    Get chunks that are waiting for embedding.
    Used by embedding worker.
    """
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.embedding_status == "pending")
        .order_by(DocumentChunk.created_at.asc())
        .limit(limit)
        .all()
    )
def mark_chunk_embedded(
    db: Session,
    chunk_id: int,
    token_count: int | None = None,
):
    """
    Mark a chunk as embedded after vector creation.
    """

    chunk = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.id == chunk_id)
        .first()
    )

    if not chunk:
        return None

    chunk.embedding_status = "embedded"

    if token_count is not None:
        chunk.token_count = token_count

    db.commit()
    db.refresh(chunk)

    return chunk