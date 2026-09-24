from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from database import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="CLP", nullable=False)
    # Monto normalizado a CLP (para USD se usa la tasa FX_USD_CLP)
    amount_clp = Column(Numeric(12, 2), nullable=True)
    merchant = Column(String(255))
    category_id = Column(Integer, ForeignKey("categories.id"), default=17)  # "Sin Categorizar"
    description = Column(Text)
    transaction_date = Column(Date, server_default=func.current_date(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Idempotencia: reintentos seguros sin duplicar transacciones
    client_request_id = Column(String(64), unique=True, nullable=True)

    # Índices compuestos para las consultas por usuario (listado y resumen)
    __table_args__ = (
        Index("ix_transactions_user_type", "user_id", "type"),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
    )

class ConversationMemory(Base):
    __tablename__ = "conversation_memory"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
