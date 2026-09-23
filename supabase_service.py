"""
Servicio de consulta de resumen financiero.

La conexión a Supabase está configurada en `database.py` mediante DATABASE_URL
(Postgres de Supabase) + SQLAlchemy; este módulo encapsula la lógica de
consulta y cálculo sobre la tabla "transactions".
"""
from decimal import Decimal

from sqlalchemy.orm import Session

import models


def calculate_financial_summary(db: Session) -> dict:
    """
    Consulta la tabla "transactions" y calcula el resumen financiero.

    - Suma por separado los totales de "ingreso" y "gasto".
    - Calcula el saldo neto restando gastos a ingresos.

    Retorna:
        {"income": float, "expenses": float, "balance": float}
    """
    transacciones = (
        db.query(models.Transaction)
        .filter(models.Transaction.user_id == "1")
        .all()
    )

    total_income = sum(
        [t.amount for t in transacciones if t.type == "ingreso"], Decimal("0")
    )
    total_expenses = sum(
        [t.amount for t in transacciones if t.type == "gasto"], Decimal("0")
    )
    balance = total_income - total_expenses

    return {
        "income": float(total_income),
        "expenses": float(total_expenses),
        "balance": float(balance),
    }
