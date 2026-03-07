from pydantic import BaseModel


class DocumentStatusUpdate(BaseModel):
    status: str
