"""Schemas Pydantic: contrato de request/response de la API."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

MONEDA = Literal["CLP", "USD"]
TIPO = Literal["gasto", "ingreso"]
IDEMPOTENCIA = r"^[A-Za-z0-9\-_]+$"


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool = True
    created_at: Optional[datetime] = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    type: str
    amount: float
    currency: str
    amount_clp: Optional[float] = None
    merchant: Optional[str] = None
    category_id: Optional[int] = None
    description: Optional[str] = None
    transaction_date: date
    client_request_id: Optional[str] = None
    created_at: Optional[datetime] = None


class CategorySummary(BaseModel):
    """Agregado por categoría para dashboard (top gastos/ingresos)."""

    type: TIPO
    category_id: Optional[int] = None
    category_name: str
    total: float
    count: int


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
    """Alta manual de transacción (también usado por /transactions/confirm)."""

    type: TIPO
    amount: PositiveFloat
    currency: MONEDA = "CLP"
    merchant: Optional[str] = Field(None, max_length=255)
    category_id: Optional[int] = Field(None, ge=1)
    description: Optional[str] = Field(None, max_length=2000)
    transaction_date: Optional[date] = None  # default: hoy en America/Santiago
    client_request_id: Optional[str] = Field(
        None, min_length=8, max_length=64, pattern=IDEMPOTENCIA
    )


class TransactionUpdate(BaseModel):
    """Actualización parcial: solo los campos enviados se modifican."""

    type: Optional[TIPO] = None
    amount: Optional[PositiveFloat] = None
    currency: Optional[MONEDA] = None
    merchant: Optional[str] = Field(None, max_length=255)
    category_id: Optional[int] = Field(None, ge=1)
    description: Optional[str] = Field(None, max_length=2000)
    transaction_date: Optional[date] = None


class TransactionParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ProcessRequest(BaseModel):
    mensaje: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Respuestas de IA (borrador → confirmación)
# ---------------------------------------------------------------------------

class ExtractedData(BaseModel):
    amount: float
    type: str
    description: Optional[str] = None
    category_id: int
    category_name: Optional[str] = None
    currency: str
    merchant: Optional[str] = None


class DraftTransaction(BaseModel):
    """Borrador listo para enviar a POST /transactions/confirm sin re-procesar."""

    type: TIPO
    amount: PositiveFloat
    currency: MONEDA
    amount_clp: float
    merchant: Optional[str] = None
    category_id: int
    category_name: Optional[str] = None
    description: Optional[str] = None
    transaction_date: date


class ParseDraftData(BaseModel):
    extracted_data: ExtractedData
    draft: DraftTransaction
