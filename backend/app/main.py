from fastapi import FastAPI
from app.api.v1.api_router import api_router
from app.middlewares.auth_logger import AuthLoggingMiddleware

app = FastAPI()

# Middleware
app.add_middleware(AuthLoggingMiddleware)

# API v1 (DUY NHẤT)
app.include_router(api_router, prefix="/api/v1")
