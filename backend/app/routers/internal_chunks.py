from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.chunk import get_pending_chunks
from app.models.document_chunk import DocumentChunk

router = APIRouter()


@router.get("/pending")
def read_pending_chunks(
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """
    Get chunks that have not been embedded yet.
    Used by AI worker service.
    """

    chunks = get_pending_chunks(db, limit=limit)

    return [
        {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
        }
        for chunk in chunks
    ]