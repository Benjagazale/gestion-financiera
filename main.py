"""Agente Financiero API — aplicación (middleware, error handlers, routers)."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.errors import register_error_handlers
from routers.categories import router as categories_router
from routers.transactions import router as transactions_router
from schemas.response import Envelope, envelope

logger = logging.getLogger("agente")

app = FastAPI(title="Agente Financiero API", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(categories_router)
app.include_router(transactions_router)


@app.get("/health", response_model=Envelope)
def health_check():
    return envelope({"status": "ok"})
