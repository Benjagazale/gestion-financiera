"""Envelope estándar de respuestas: {"data": ..., "meta": {"request_id": ...}}."""
import uuid
from typing import Any

from pydantic import BaseModel


class Meta(BaseModel):
    request_id: str


class Envelope(BaseModel):
    data: Any
    meta: Meta


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


def envelope(data: Any) -> dict:
    return {"data": data, "meta": {"request_id": str(uuid.uuid4())}}
