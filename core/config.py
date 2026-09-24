"""Configuración central: lee .env una sola vez y expone `settings`."""
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _csv(nombre: str, default: str) -> list[str]:
    return [o.strip() for o in os.getenv(nombre, default).split(",") if o.strip()]


@dataclass
class Settings:
    # Seguridad
    api_key: Optional[str] = os.getenv("API_KEY")  # None = auth deshabilitada (dev local)

    # Usuario por defecto hasta que llegue Supabase Auth (FASE 3)
    default_user_id: str = os.getenv("DEFAULT_USER_ID", "1")

    # IA
    groq_api_key: Optional[str] = os.getenv("GROQ_API_KEY")

    # Rate limiting (in-memory, sin dependencias pagas)
    parse_rate_limit: int = int(os.getenv("PARSE_RATE_LIMIT", "10"))
    rate_window_seconds: int = int(os.getenv("RATE_WINDOW_SECONDS", "60"))

    # CORS: restringir al dominio del frontend en producción
    cors_origins: list[str] = field(default_factory=lambda: _csv("CORS_ORIGINS", "*"))

    # Tipo de cambio para normalizar USD → CLP (tasa fija configurable;
    # el refresh automático desde una API es una mejora futura)
    fx_usd_clp: Decimal = Decimal(os.getenv("FX_USD_CLP", "950"))


settings = Settings()
