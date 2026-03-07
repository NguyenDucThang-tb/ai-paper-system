from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from app.db.session import Base


class WorkerStatus(Base):
    __tablename__ = "worker_status"

    id = Column(Integer, primary_key=True, index=True)

    worker_name = Column(String, unique=True)
    status = Column(String, default="online")

    current_job_id = Column(Integer, nullable=True)

    last_heartbeat = Column(DateTime(timezone=True), server_default=func.now())
