from fastapi import FastAPI
from app.api.v1.api_router import api_router
from app.middlewares.auth_logger import AuthLoggingMiddleware
app = FastAPI()
app.add_middleware(AuthLoggingMiddleware)
app.include_router(api_router, prefix="/api/v1")
from app.db.base import Base
from app.db.session import engine
from app.routers import documents
from app.routers import internal

app.include_router(
    documents.router,
    prefix="/api/v1/documents",
    tags=["Documents"]
)
app.include_router(
    internal.router,
    prefix="/api/v1/internal",
    tags=["Internal"]
)

Base.metadata.create_all(bind=engine)
