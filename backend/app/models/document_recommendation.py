from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.session import Base


class DocumentRecommendation(Base):
    __tablename__ = "document_recommendations"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    recommended_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    source = Column(String, nullable=True)
    external_url = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document")
