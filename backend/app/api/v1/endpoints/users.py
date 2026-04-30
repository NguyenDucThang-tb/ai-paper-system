from fastapi import APIRouter, Security
from app.api.deps import get_current_user
from app.models.user import User

from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import Depends

from app.db.session import get_db
from app.models.document import Document

router = APIRouter()


@router.get(
    "/me",
    dependencies=[Security(get_current_user, scopes=["user:read"])]
)
def read_me(current_user: User = Security(get_current_user, scopes=["user:read"])):
    return {
        "email": current_user.email,
        "role": current_user.role
    }
@router.get("/me/dashboard")
def get_user_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Total docs
    total_documents = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .count()
    )

    # Count by status
    processing = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.status == "processing"
        )
        .count()
    )

    processed = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.status == "processed"
        )
        .count()
    )

    uploaded = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.status == "uploaded"
        )
        .count()
    )

    # Recent docs
    recent_documents = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "total_documents": total_documents,
        "processing": processing,
        "processed": processed,
        "uploaded": uploaded,
        "recent_documents": recent_documents,
    }
