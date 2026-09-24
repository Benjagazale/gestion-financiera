"""Schemas Pydantic: contrato de request/response de la API."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    merchant: Optional[str] = None
    category_id: Optional[int] = None
    description: Optional[str] = None
    transaction_date: date
    created_at: Optional[datetime] = None


class TransactionParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ProcessRequest(BaseModel):
    mensaje: str = Field(min_length=1, max_length=1000)


class ExtractedData(BaseModel):
    amount: float
    type: str
    description: Optional[str] = None
    category_id: int
    category_name: Optional[str] = None
    currency: str
    merchant: Optional[str] = None


class ParseData(BaseModel):
    extracted_data: ExtractedData
    transaction: TransactionOut
