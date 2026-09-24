"""Endpoint de categorías (lectura)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.security import require_api_key
from database import get_db
import models
from schemas.response import Envelope, envelope
from schemas.transaction import CategoryOut

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(require_api_key)],
)


@router.get("", response_model=Envelope)
def listar_categorias(db: Session = Depends(get_db)):
    categorias = db.query(models.Category).all()
    return envelope([CategoryOut.model_validate(c).model_dump(mode="json") for c in categorias])
