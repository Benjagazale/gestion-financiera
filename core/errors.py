"""Manejadores globales de error: contrato único {"error": {"code", "message"}}.

Nunca se filtran detalles internos (stack traces, secretos, mensajes crudos
de proveedores) al cliente: lo interno va al log.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("agente")

CODIGOS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "AI_BAD_RESPONSE",
    503: "SERVICE_UNAVAILABLE",
}


def _respuesta_error(status: int, code: str, message: str, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )

def register_error_handlers(app: FastAPI) -> None:
    # StarletteHTTPException cubre la subclase de FastAPI (HTTPException de rutas)
    # y además el 404/405 del router, que lanza la clase base de Starlette.
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = CODIGOS.get(exc.status_code, "HTTP_ERROR")
        return _respuesta_error(exc.status_code, code, str(exc.detail), getattr(exc, "headers", None))
    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        errores = exc.errors()
        primero = errores[0] if errores else {}
        loc = ".".join(str(p) for p in primero.get("loc", [])) or "solicitud"
        msg = primero.get("msg", "Datos inválidos")
        return _respuesta_error(422, "VALIDATION_ERROR", f"{loc}: {msg}")

    @app.exception_handler(Exception)
    async def _genérico(request: Request, exc: Exception):
        logger.exception("Error no controlado: %s", exc)
        return _respuesta_error(500, "INTERNAL_ERROR", "Error interno del servidor")
