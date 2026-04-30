from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.internal_deps import verify_internal_token

# 🔥 chuyển sang dùng DOMAIN (không dùng CRUD nữa)
from app.domain.document.service import add_chunks

router = APIRouter()


@router.post("/")
def receive_chunks(
    document_id: int,
    chunks: list[dict],
    db: Session = Depends(get_db),
    _=Depends(verify_internal_token),
):
    """
    AI worker gửi chunk về backend
    """

    # 🔥 gọi domain layer
    count = add_chunks(
        db=db,
        document_id=document_id,
        chunks=chunks,
    )

    return {
        "message": "Chunks received",
        "count": count
    }
