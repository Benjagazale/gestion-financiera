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
from typing import Optional

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
