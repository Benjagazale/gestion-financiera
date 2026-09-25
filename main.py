"""Agente Financiero API — aplicación (middleware, error handlers, routers)."""
import logging
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.errors import register_error_handlers
from routers.categories import router as categories_router
from routers.transactions import router as transactions_router
from schemas.response import Envelope, envelope

logger = logging.getLogger("agente")

# Documentación interactiva: off en producción (nada que rastrear/indexar)
DOCS_ON = {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
DOCS_OFF = {"docs_url": None, "redoc_url": None, "openapi_url": None}


def crear_app(enable_docs: Optional[bool] = None) -> FastAPI:
    """Factory testable de la aplicación.

    `enable_docs` controla /docs, /redoc y /openapi.json. Default:
    `settings.enable_docs` (ENABLE_DOCS; off salvo activación explícita).
    """
    mostrar_docs = settings.enable_docs if enable_docs is None else enable_docs
    aplicacion = FastAPI(
        title="Agente Financiero API",
        version="2.1",
        **(DOCS_ON if mostrar_docs else DOCS_OFF),
    )

    aplicacion.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(aplicacion)

    aplicacion.include_router(categories_router)
    aplicacion.include_router(transactions_router)

    @aplicacion.get("/health", response_model=Envelope)
    def health_check():
        """Healthcheck público (exento de API key).

        `api_key_configured` permite verificar a distancia si la variable
        API_KEY llegó al proceso (no expone el valor, solo true/false).
        """
        return envelope({"status": "ok", "api_key_configured": bool(settings.api_key)})

    # Interfaz web (SPA estática) — montada al final para no sombrear rutas de la API.
    # Mismo origen: sin CORS y sin servicio extra (plan Free).
    aplicacion.mount(
        "/",
        StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend"), html=True),
        name="frontend",
    )
    return aplicacion


app = crear_app()
