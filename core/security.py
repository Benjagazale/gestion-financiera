"""Seguridad: API key global por header X-API-Key."""
import secrets

from fastapi import HTTPException, Request

from core.config import settings


async def require_api_key(request: Request):
    """
    Protege todos los endpoints donde se inyecte como dependencia.

    - /health queda excluida (healthcheck de Render / cron anti-sleep no envían key).
    - Si API_KEY no está configurada, la auth queda deshabilitada (modo dev local).
    """
    if request.url.path == "/health":
        return

    esperada = settings.api_key
    if not esperada:
        return

    recibida = request.headers.get("X-API-Key", "")
    if not recibida or not secrets.compare_digest(recibida, esperada):
        raise HTTPException(status_code=401, detail="API key inválida o ausente")
