"""
Servicio de consulta de resumen financiero.

La conexión a Supabase está configurada en `database.py` mediante DATABASE_URL
(Postgres de Supabase) + SQLAlchemy.

El cálculo se hace con agregación SQL (SUM + GROUP BY) en la base de datos:
- 1 sola query ligera (no carga todas las filas a memoria).
- Compatible con filtros de fecha (?from=&to=) sobre America/Santiago
  (las fechas de `transaction_date` ya se calculan en calendario chileno).
"""
from datetime import date
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import models


def calculate_financial_summary(
    db: Session,
    *,
    user_id: str = "1",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict:
    """
    Calcula ingresos, gastos y saldo del usuario consultando "transactions".

    Retorna:
        {"income": float, "expenses": float, "balance": float}
    """
    query = (
        db.query(models.Transaction.type, func.sum(models.Transaction.amount))
        .filter(models.Transaction.user_id == user_id)
    )

    if date_from is not None:
        query = query.filter(models.Transaction.transaction_date >= date_from)
    if date_to is not None:
        query = query.filter(models.Transaction.transaction_date <= date_to)

    filas = query.group_by(models.Transaction.type).all()
    totales = {tipo: float(monto or 0) for tipo, monto in filas}

    income = totales.get("ingreso", 0.0)
    expenses = totales.get("gasto", 0.0)

    return {
        "income": income,
        "expenses": expenses,
        "balance": income - expenses,
    }


def calculate_summary_by_category(
    db: Session,
    *,
    user_id: str = "1",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    type: Optional[str] = None,
) -> List[dict]:
    """
    Totales agrupados por categoría (LEFT JOIN a categories → nombre resuelto),
    ordenados de mayor a menor total. 1 sola query SQL.

    Filas sin categoría → category_id=None y category_name="Sin Categorizar".

    Retorna:
        [{"type", "category_id", "category_name", "total", "count"}, ...]
    """
    query = (
        db.query(
            models.Transaction.category_id,
            models.Transaction.type,
            func.coalesce(models.Category.name, "Sin Categorizar").label("category_name"),
            func.sum(models.Transaction.amount).label("total"),
            func.count(models.Transaction.id).label("count"),
        )
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(models.Transaction.user_id == user_id)
    )

    if date_from is not None:
        query = query.filter(models.Transaction.transaction_date >= date_from)
    if date_to is not None:
        query = query.filter(models.Transaction.transaction_date <= date_to)
    if type is not None:
        query = query.filter(models.Transaction.type == type)

    filas = (
        query.group_by(
            models.Transaction.category_id,
            models.Transaction.type,
            models.Category.name,
        )
        .order_by(func.sum(models.Transaction.amount).desc())
        .all()
    )

    return [
        {
            "type": fila.type,
            "category_id": fila.category_id,
            "category_name": fila.category_name,
            "total": float(fila.total or 0),
            "count": fila.count,
        }
        for fila in filas
    ]
