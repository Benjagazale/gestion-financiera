import os
import re

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _normalizar_url(url: str) -> str:
    """Prepara DATABASE_URL para producción (Supabase + Render):

    - Elimina artefactos de copiar-pegar (espacios, saltos de línea,
      comillas, prefijo ``DATABASE_URL=``).
    - SQLAlchemy 2.x exige el esquema ``postgresql://`` (Supabase entrega
      ``postgres://`` en su connection string).
    - Supabase exige SSL: agrega ``sslmode=require`` si no viene explícito.
    """
    url = re.sub(r"\s+", "", url).strip("\"'")
    if url.startswith("DATABASE_URL="):
        url = url[len("DATABASE_URL="):].strip("\"'")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "://" not in url:
        raise RuntimeError(
            "DATABASE_URL no es un connection string válido (se esperaba "
            "postgresql://usuario:password@host:puerto/base). Revisa el valor "
            "en el dashboard de Render."
        )
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Falta la variable de entorno DATABASE_URL "
        "(archivo .env en local, Render Dashboard en producción)."
    )

engine = create_engine(
    _normalizar_url(DATABASE_URL),
    # Supabase cierra conexiones inactivas: verificar antes de usarlas
    # y reciclar cada 30 min evita "server closed the connection".
    pool_pre_ping=True,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Dependencia para obtener la sesión de base de datos en los endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
