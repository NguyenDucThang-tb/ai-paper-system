from app.core.database import engine, Base
from app.models import user, document
from app.models.document_summary import DocumentSummary


print("⏳ Creating tables...")
Base.metadata.create_all(bind=engine)
print("✅ Tables created successfully!")
