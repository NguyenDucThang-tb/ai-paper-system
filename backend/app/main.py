from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import logging
from app.api.v1.api_router import api_router
from app.middlewares.auth_logger import AuthLoggingMiddleware
from app.core.config import settings

app = FastAPI()
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    same_site="lax",
    https_only=False,
)

# Middleware
app.add_middleware(AuthLoggingMiddleware)

# API v1 (DUY NHẤT)
app.include_router(api_router, prefix="/api/v1")

logger.info(
    "Neo4j config",
    extra={
        "neo4j_uri_exists": bool(settings.NEO4J_URI),
        "neo4j_uri_prefix": settings.NEO4J_URI.split("://")[0] if settings.NEO4J_URI else None,
        "neo4j_user_exists": bool(settings.NEO4J_USERNAME),
        "neo4j_database": settings.NEO4J_DATABASE,
        "neo4j_rec_uri_exists": bool(settings.NEO4J_REC_URI),
        "neo4j_rec_uri_prefix": settings.NEO4J_REC_URI.split("://")[0] if settings.NEO4J_REC_URI else None,
        "neo4j_rec_user_exists": bool(settings.NEO4J_REC_USERNAME),
        "neo4j_rec_database": settings.NEO4J_REC_DATABASE,
    },
)
