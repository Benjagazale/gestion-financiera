"""Agente Financiero API — capa de rutas delgada (solo HTTP + Depends).

Lógica de negocio en services/, contratos en schemas/, infra en core/.
"""
import json
import logging
from datetime import date
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from core.config import settings
from core.errors import register_error_handlers
from core.rate_limit import rate_limit
from core.security import require_api_key
from database import get_db
import models
from schemas.response import Envelope, envelope
from schemas.transaction import (
    CategoryOut,
    ParseData,
    ProcessRequest,
    TransactionOut,
    TransactionParseRequest,
)
from services.ai_service import parse_transaction_with_ai
from services.summary_service import calculate_financial_summary

logger = logging.getLogger("agente")

app = FastAPI(title="Agente Financiero API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

AUTH = [Depends(require_api_key)]


@app.get("/health", response_model=Envelope)
def health_check():
    return envelope({"status": "ok"})


@app.get("/categories", response_model=Envelope, dependencies=AUTH)
def listar_categorias(db: Session = Depends(get_db)):
    categorias = db.query(models.Category).all()
    return envelope([CategoryOut.model_validate(c).model_dump(mode="json") for c in categorias])


@app.get("/transactions", response_model=Envelope, dependencies=AUTH)
def listar_transacciones(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    type: Optional[Literal["gasto", "ingreso"]] = None,
    category_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    query = db.query(models.Transaction).filter(
        models.Transaction.user_id == settings.default_user_id
    )

    if type is not None:
        query = query.filter(models.Transaction.type == type)

    if category_id is not None:
        query = query.filter(models.Transaction.category_id == category_id)

    transacciones = query.order_by(models.Transaction.id).offset(skip).limit(limit).all()
    return envelope([TransactionOut.model_validate(t).model_dump(mode="json") for t in transacciones])


@app.get("/transactions/summary", response_model=Envelope, dependencies=AUTH)
def obtener_resumen_financiero(
    fecha_desde: Optional[date] = Query(None, alias="from"),
    fecha_hasta: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    """Resumen financiero vía agregación SQL. Filtros de fecha opcionales
    en calendario Chile (?from=YYYY-MM-DD&to=YYYY-MM-DD)."""
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise HTTPException(status_code=422, detail="'from' no puede ser posterior a 'to'")

    resumen = calculate_financial_summary(
        db,
        user_id=settings.default_user_id,
        date_from=fecha_desde,
        date_to=fecha_hasta,
    )
    return envelope(resumen)


def _extraer_y_guardar(texto: str, db: Session) -> dict:
    """Flujo compartido por /parse y /process: IA → validar → persistir."""
    # 1. Categorías activas (para inyectar al prompt y resolver nombres → IDs)
    categorias = db.query(models.Category).filter(models.Category.is_active == True).all()
    categorias_por_nombre = {c.name.strip().lower(): c.id for c in categorias}
    cats_prompt = [{"id": c.id, "name": c.name} for c in categorias]

    # 2. Extracción con IA (timeout + fallback de modelo + schema validation)
    try:
        resultado_json_str = parse_transaction_with_ai(texto, categorias=cats_prompt)
        datos = json.loads(resultado_json_str)
    except Exception as e:
        logger.error("Fallo del servicio de IA: %s", e)
        raise HTTPException(
            status_code=503,
            detail="El servicio de IA no está disponible temporalmente. Reintenta en unos segundos.",
            headers={"Retry-After": "30"},
        )

    # 3. Validación defensiva de los datos extraídos
    monto = datos.get("amount")
    tipo = str(datos.get("type", "")).strip().lower()

    if monto is None:
        raise HTTPException(status_code=422, detail="La IA no pudo extraer un monto válido del texto.")
    if tipo not in ("gasto", "ingreso"):
        raise HTTPException(
            status_code=422,
            detail=f"Tipo inválido extraído por la IA: '{tipo}'. Debe ser 'gasto' o 'ingreso'.",
        )

    # 4. Resolver categoría: ID de la IA → nombre → default 7 ("Sin Categorizar")
    category_id = datos.get("category_id")
    category_nombre = datos.get("category")

    if category_id is None and category_nombre:
        category_id = categorias_por_nombre.get(str(category_nombre).strip().lower())
    if category_id is None:
        category_id = 7
    try:
        category_id = int(category_id)
    except (TypeError, ValueError):
        category_id = 7

    # 5. Persistir (user_id SIEMPRE string desde settings, nunca int del body)
    nueva_transaccion = models.Transaction(
        user_id=settings.default_user_id,
        type=tipo,
        amount=float(monto),
        currency=datos.get("currency", "CLP"),
        merchant=datos.get("merchant"),
        category_id=category_id,
        description=datos.get("description") or texto,
    )

    try:
        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)
    except Exception as e:
        db.rollback()
        logger.error("Error al guardar la transacción: %s", e)
        raise HTTPException(status_code=500, detail="Error al guardar la transacción.")

    return ParseData(
        extracted_data={
            "amount": float(monto),
            "type": tipo,
            "description": datos.get("description") or texto,
            "category_id": category_id,
            "category_name": next((c.name for c in categorias if c.id == category_id), None),
            "currency": datos.get("currency", "CLP"),
            "merchant": datos.get("merchant"),
        },
        transaction=TransactionOut.model_validate(nueva_transaccion),
    ).model_dump(mode="json")


@app.post(
    "/transactions/parse",
    response_model=Envelope,
    dependencies=AUTH + [Depends(rate_limit("parse"))],
)
def parsear_transaccion(payload: TransactionParseRequest, db: Session = Depends(get_db)):
    """Extrae una transacción de lenguaje natural con IA y la guarda."""
    return envelope(_extraer_y_guardar(payload.text, db))


@app.post(
    "/transactions/process",
    response_model=Envelope,
    dependencies=AUTH + [Depends(rate_limit("process"))],
)
def procesar_y_guardar_transaccion(payload: ProcessRequest, db: Session = Depends(get_db)):
    """Alias histórico de /parse (body: {"mensaje": "..."})."""
    return envelope(_extraer_y_guardar(payload.mensaje, db))
