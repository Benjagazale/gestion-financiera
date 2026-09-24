"""
Lógica de negocio de transacciones: borradores IA, persistencia e idempotencia.

Reglas de negocio:
- Fechas: `transaction_date` SIEMPRE explícita, con default = hoy en
  America/Santiago (calendario chileno), nunca el current_date UTC del servidor.
- Moneda: CLP/USD; `amount_clp` normaliza a pesos con la tasa configurable FX_USD_CLP.
- Idempotencia: `client_request_id` único — reintentos no duplican registros.
"""
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from core.config import settings

logger = logging.getLogger("agente")

ZONA_CHILE = ZoneInfo("America/Santiago")
CATEGORIA_DEFAULT = 17  # "Sin Categorizar" (id real en la BD)
MONEDAS_VALIDAS = ("CLP", "USD")


def hoy_chile() -> date:
    """Fecha de hoy en el calendario de Chile (America/Santiago)."""
    return datetime.now(ZONA_CHILE).date()


def calcular_amount_clp(amount, currency: str) -> Decimal:
    """Normaliza el monto a CLP (USD se multiplica por la tasa configurable)."""
    monto = Decimal(str(amount))
    if currency == "USD":
        monto = monto * settings.fx_usd_clp
    return monto.quantize(Decimal("0.01"))


def validar_categoria(db: Session, category_id: Optional[int]) -> int:
    """Categoría inexistente o inactiva → 422 (para altas/ediciones manuales)."""
    if category_id is None:
        return CATEGORIA_DEFAULT
    existe = (
        db.query(models.Category.id)
        .filter(
            models.Category.id == category_id,
            models.Category.is_active == True,  # noqa: E712
        )
        .first()
    )
    if existe is None:
        raise HTTPException(
            status_code=422,
            detail=f"La categoría {category_id} no existe o está inactiva.",
        )
    return category_id


def obtener_transaccion_o_404(db: Session, transaction_id: int) -> models.Transaction:
    tx = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.id == transaction_id,
            models.Transaction.user_id == settings.default_user_id,
        )
        .first()
    )
    if tx is None:
        raise HTTPException(
            status_code=404, detail=f"Transacción {transaction_id} no encontrada"
        )
    return tx


def extraer_borrador(texto: str, db: Session) -> dict:
    """
    IA → borrador estructurado. NO persiste: la escritura ocurre en
    POST /transactions/confirm (flujo de confirmación del usuario).
    """
    # 1. Categorías activas (prompt + resolución nombre→id)
    categorias = db.query(models.Category).filter(models.Category.is_active == True).all()
    por_id = {c.id: c.name for c in categorias}
    por_nombre = {c.name.strip().lower(): c.id for c in categorias}
    cats_prompt = [{"id": c.id, "name": c.name} for c in categorias]

    # 2. Extracción con IA (timeout + fallback de modelo + schema en el servicio)
    try:
        bruto = _parse_con_ia(texto, cats_prompt)
        datos = json.loads(bruto)
    except Exception as e:
        logger.error("Fallo del servicio de IA: %s", e)
        raise HTTPException(
            status_code=503,
            detail="El servicio de IA no está disponible temporalmente. Reintenta en unos segundos.",
            headers={"Retry-After": "30"},
        )

    # 3. Validación defensiva
    monto = datos.get("amount")
    tipo = str(datos.get("type", "")).strip().lower()

    if monto is None:
        raise HTTPException(status_code=422, detail="La IA no pudo extraer un monto válido del texto.")
    try:
        amount = float(monto)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="La IA no pudo extraer un monto válido del texto.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="El monto extraído debe ser positivo.")
    if tipo not in ("gasto", "ingreso"):
        raise HTTPException(
            status_code=422,
            detail=f"Tipo inválido extraído por la IA: '{tipo}'. Debe ser 'gasto' o 'ingreso'.",
        )

    # 4. Moneda: solo CLP/USD; lo desconocido se normaliza a CLP
    currency = datos.get("currency", "CLP")
    if currency not in MONEDAS_VALIDAS:
        currency = "CLP"

    # 5. Categoría: ID válido de la IA → nombre → default 7
    category_id = datos.get("category_id")
    try:
        category_id = int(category_id) if category_id is not None else None
    except (TypeError, ValueError):
        category_id = None
    if category_id not in por_id:
        category_id = por_nombre.get(str(datos.get("category") or "").strip().lower())
    if category_id is None:
        category_id = CATEGORIA_DEFAULT

    descripcion = datos.get("description") or texto

    # 6. Borrador con fecha = hoy en Chile y monto normalizado
    draft = {
        "type": tipo,
        "amount": amount,
        "currency": currency,
        "amount_clp": float(calcular_amount_clp(amount, currency)),
        "merchant": datos.get("merchant"),
        "category_id": category_id,
        "category_name": por_id.get(category_id),
        "description": descripcion,
        "transaction_date": hoy_chile(),
    }

    return {
        "extracted_data": {
            "amount": amount,
            "type": tipo,
            "description": descripcion,
            "category_id": category_id,
            "category_name": por_id.get(category_id),
            "currency": currency,
            "merchant": datos.get("merchant"),
        },
        "draft": draft,
    }


def guardar_transaccion(db: Session, datos: dict) -> tuple[models.Transaction, bool]:
    """
    Inserta una transacción de forma idempotente.

    Retorna (transaccion, creado):
    - creado=True: se insertó un registro nuevo (HTTP 201).
    - creado=False: ya existía un registro con ese client_request_id
      (reintento seguro → HTTP 200, sin duplicados).
    """
    payload = dict(datos)
    client_request_id = payload.pop("client_request_id", None)

    # FASE 3 lo reemplazará por el user_id de Supabase Auth (multiusuario + RLS)
    payload["user_id"] = settings.default_user_id

    # Defaults de negocio
    if not payload.get("transaction_date"):
        payload["transaction_date"] = hoy_chile()
    if payload.get("category_id") is None:
        payload.pop("category_id", None)  # aplica default 7 del modelo
    payload["amount_clp"] = calcular_amount_clp(
        payload["amount"], payload.get("currency", "CLP")
    )

    # Reintento idempotente: ¿ya existe este client_request_id?
    if client_request_id:
        existente = (
            db.query(models.Transaction)
            .filter(models.Transaction.client_request_id == client_request_id)
            .first()
        )
        if existente is not None:
            return existente, False

    nueva = models.Transaction(client_request_id=client_request_id, **payload)
    try:
        db.add(nueva)
        db.commit()
        db.refresh(nueva)
        return nueva, True
    except IntegrityError:
        # Carrera entre reintentos: gana el primero; devolvemos el existente
        db.rollback()
        if client_request_id:
            existente = (
                db.query(models.Transaction)
                .filter(models.Transaction.client_request_id == client_request_id)
                .first()
            )
            if existente is not None:
                return existente, False
        logger.error("Integridad al crear transacción (crid=%s)", client_request_id)
        raise HTTPException(status_code=500, detail="Error al guardar la transacción.")


def actualizar_transaccion(
    db: Session, tx: models.Transaction, cambios: dict
) -> models.Transaction:
    """Actualización parcial; recalcula amount_clp si cambió monto o moneda."""
    for campo, valor in cambios.items():
        setattr(tx, campo, valor)

    if "amount" in cambios or "currency" in cambios:
        tx.amount_clp = calcular_amount_clp(tx.amount, tx.currency)

    try:
        db.commit()
        db.refresh(tx)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error al actualizar la transacción.")
    return tx


def eliminar_transaccion(db: Session, tx: models.Transaction) -> None:
    try:
        db.delete(tx)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error al eliminar la transacción.")


# Indirecto para que los tests parcheen services.ai_service.parse_transaction_with_ai
from services import ai_service as _ai_service  # noqa: E402


def _parse_con_ia(texto: str, categorias: list[dict]) -> str:
    return _ai_service.parse_transaction_with_ai(texto, categorias=categorias)
