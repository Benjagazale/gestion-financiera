"""Endpoints de transacciones: listado, resumen, CRUD e IA (borrador+confirm)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from core.config import settings
from core.rate_limit import rate_limit
from core.security import require_api_key
from database import get_db
import models
from schemas.response import Envelope, envelope
from schemas.transaction import (
    ParseDraftData,
    ProcessRequest,
    TransactionCreate,
    TransactionOut,
    TransactionParseRequest,
    TransactionUpdate,
)
from services.summary_service import calculate_financial_summary
from services.transaction_service import (
    actualizar_transaccion,
    eliminar_transaccion,
    extraer_borrador,
    guardar_transaccion,
    obtener_transaccion_o_404,
    validar_categoria,
)

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_api_key)],
)


def _out(tx: models.Transaction) -> dict:
    return TransactionOut.model_validate(tx).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

@router.get("", response_model=Envelope)
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
    return envelope([_out(t) for t in transacciones])


@router.get("/summary", response_model=Envelope)
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


@router.get("/{transaction_id}", response_model=Envelope)
def obtener_transaccion(transaction_id: int, db: Session = Depends(get_db)):
    return envelope(_out(obtener_transaccion_o_404(db, transaction_id)))


# ---------------------------------------------------------------------------
# Escritura: alta manual + confirmación de borradores (idempotentes)
# ---------------------------------------------------------------------------

def _crear(payload: TransactionCreate, response: Response, db: Session) -> dict:
    datos = payload.model_dump()
    datos["category_id"] = validar_categoria(db, datos.get("category_id"))

    tx, creado = guardar_transaccion(db, datos)

    # Reintento idempotente (client_request_id ya registrado) → 200, no 201
    if not creado:
        response.status_code = 200
    return envelope(_out(tx))


@router.post("", response_model=Envelope, status_code=201)
def crear_transaccion(
    payload: TransactionCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """Alta manual. Idempotente si envías client_request_id (UUID)."""
    return _crear(payload, response, db)


@router.post("/confirm", response_model=Envelope, status_code=201)
def confirmar_transaccion(
    payload: TransactionCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """Persiste el borrador devuelto por POST /transactions/parse (o un alta
    manual). Mismo contrato que POST /transactions; idempotente por
    client_request_id."""
    return _crear(payload, response, db)


@router.put("/{transaction_id}", response_model=Envelope)
def editar_transaccion(
    transaction_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
):
    """Actualización parcial de una transacción propia."""
    tx = obtener_transaccion_o_404(db, transaction_id)
    cambios = payload.model_dump(exclude_unset=True)

    # Campos NOT NULL no pueden ponerse en null vía PUT
    cambios = {
        k: v
        for k, v in cambios.items()
        if not (v is None and k in ("amount", "type", "currency", "transaction_date"))
    }
    if cambios.get("category_id") is None and "category_id" in cambios:
        cambios["category_id"] = 7  # null explícito → "Sin Categorizar"

    if "category_id" in cambios:
        cambios["category_id"] = validar_categoria(db, cambios["category_id"])

    if cambios:
        tx = actualizar_transaccion(db, tx, cambios)
    return envelope(_out(tx))


@router.delete("/{transaction_id}", response_model=Envelope)
def borrar_transaccion(transaction_id: int, db: Session = Depends(get_db)):
    tx = obtener_transaccion_o_404(db, transaction_id)
    eliminar_transaccion(db, tx)
    return envelope({"deleted": True, "id": transaction_id})


# ---------------------------------------------------------------------------
# IA: borrador (no persiste) — la escritura ocurre en /confirm
# ---------------------------------------------------------------------------

@router.post("/parse", response_model=Envelope, dependencies=[Depends(rate_limit("parse"))])
def parsear_transaccion(payload: TransactionParseRequest, db: Session = Depends(get_db)):
    """Extrae la transacción del texto con IA y devuelve un borrador para
    revisión. NO guarda: confirma con POST /transactions/confirm."""
    borrador = extraer_borrador(payload.text, db)
    return envelope(ParseDraftData(**borrador).model_dump(mode="json"))


@router.post("/process", response_model=Envelope, dependencies=[Depends(rate_limit("process"))])
def procesar_transaccion(payload: ProcessRequest, db: Session = Depends(get_db)):
    """Alias histórico de /parse (body: {"mensaje": "..."}). Devuelve borrador."""
    borrador = extraer_borrador(payload.mensaje, db)
    return envelope(ParseDraftData(**borrador).model_dump(mode="json"))
