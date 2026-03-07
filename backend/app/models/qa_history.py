from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.session import Base


class QAHistory(Base):
    __tablename__ = "qa_history"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE")
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE")
    )

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)

    sources = Column(Text, nullable=True)  # optional json string

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    document = relationship("Document")
