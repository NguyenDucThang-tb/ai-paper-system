from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    title = Column(String, nullable=True)
    abstract = Column(Text, nullable=True)
    publication_year = Column(Integer, nullable=True)
    source = Column(String, nullable=True)
    language = Column(String, default="vi")

    authors = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    topics = Column(JSON, default=list)
    methods = Column(JSON, default=list)

    doi = Column(String, nullable=True)
    external_url = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    document = relationship("Document", back_populates="metadata_record")
