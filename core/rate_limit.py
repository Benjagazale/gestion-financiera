"""Rate limiting in-memory (sliding window) — sin dependencias externas."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from core.config import settings

# bucket por (scope, cliente). Suficiente para una instancia única de Render Free.
_buckets: dict[str, deque] = defaultdict(deque)


def limpiar_buckets() -> None:
    """Para tests: resetea el estado del limitador."""
    _buckets.clear()


def rate_limit(scope: str):
    """Factory de dependencia: limita llamadas por ventana deslizante."""

    def dependency(request: Request) -> None:
        limite = settings.parse_rate_limit
        ventana = settings.rate_window_seconds
        if limite <= 0:
            return  # deshabilitado explícitamente

        host = request.client.host if request.client else "unknown"
        clave = f"{scope}:{host}"
        ahora = time.monotonic()
        bucket = _buckets[clave]

        while bucket and ahora - bucket[0] >= ventana:
            bucket.popleft()

        if len(bucket) >= limite:
            raise HTTPException(
                status_code=429,
                detail=f"Demasiadas solicitudes. Intenta de nuevo en {ventana} segundos.",
                headers={"Retry-After": str(ventana)},
            )
        bucket.append(ahora)

    return dependency
