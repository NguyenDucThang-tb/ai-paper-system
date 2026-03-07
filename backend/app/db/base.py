from app.db.session import Base

# IMPORT TẤT CẢ MODEL Ở ĐÂY
from app.models.user import User
from app.models.document import Document
from app.models.refresh_token import RefreshToken
from app.models.document_chunk import DocumentChunk
from app.models.document_job import DocumentJob
from app.models.document_summary import DocumentSummary
from app.models.qa_history import QAHistory