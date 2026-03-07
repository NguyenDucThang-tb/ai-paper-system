from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.db.session import Base
from sqlalchemy.orm import relationship
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    full_name = Column(String)
    is_active = Column(Boolean, default=True)

    role = Column(String, default="user")  

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    documents = relationship(
    "Document",
    back_populates="user",
    cascade="all, delete-orphan"
)
