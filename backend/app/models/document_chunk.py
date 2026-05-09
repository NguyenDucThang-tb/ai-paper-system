from sqlalchemy import Column, Integer, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.session import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE")
    )

    chunk_index = Column(Integer)
    content = Column(Text)
    embedding = Column(JSON, nullable=True)

    document = relationship("Document", back_populates="chunks")
