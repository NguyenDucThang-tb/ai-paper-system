from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.session import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # pdf, docx, txt

    raw_text = Column(Text, nullable=True)
    status = Column(String, default="uploaded")


    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE")
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="documents")

    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan"
    )
    is_deleted = Column(Boolean, default=False)

    summaries = relationship(
        "DocumentSummary",
        back_populates="document",
        cascade="all, delete-orphan"
    )

    metadata_record = relationship(
        "DocumentMetadata",
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )
