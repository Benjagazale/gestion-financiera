"""
Pruebas unitarias para los endpoints del Agente Financiero API.

Estrategia de aislamiento de base de datos:
- Se crea una base de datos SQLite en memoria por prueba.
- Se sobreescribe la dependencia `get_db` de FastAPI para que los endpoints
  usen esa sesión de prueba en lugar de la sesión conectada a Supabase.

Endpoints cubiertos:
- GET  /transactions        (paginación y filtros)
- GET  /transactions/summary (ingresos, gastos, saldo neto y desglose)
- POST /transactions/parse   (procesamiento de texto con IA simulada)
"""

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# La raíz del proyecto debe estar en sys.path para poder importar `main`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
import models
from database import Base, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """Sesión de SQLAlchemy sobre SQLite en memoria (una por prueba)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(db_session):
    """TestClient de FastAPI con `get_db` sobrescrito por la sesión de prueba."""

    def override_get_db():
        yield db_session

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


@pytest.fixture()
def fake_ai(monkeypatch):
    """
    Simula `parse_transaction_with_ai` reemplazándolo en el módulo main.

    Uso:
        fake_ai({"type": "gasto", "amount": 1000})  -> devuelve ese JSON
        fake_ai(Exception("IA caída"))               -> lanza la excepción
    """

    def _install(result):
        if isinstance(result, Exception):
            def _raise(_texto, **_kwargs):
                raise result
            monkeypatch.setattr(main, "parse_transaction_with_ai", _raise)
        else:
            payload = json.dumps(result)

            def _return(_texto, **_kwargs):
                return payload
            monkeypatch.setattr(main, "parse_transaction_with_ai", _return)

    return _install


# ---------------------------------------------------------------------------
# Helpers de seeding
# ---------------------------------------------------------------------------

def seed_categories(session):
    """Crea categorías con IDs conocidos (mismos IDs que la base real)."""
    categorias = [
        (1, "Alimentación"),
        (2, "Transporte"),
        (12, "Sueldo y Salario"),
    ]
    for cat_id, nombre in categorias:
        session.add(models.Category(id=cat_id, name=nombre, is_active=True))
    session.commit()


def seed_transaction(session, *, type, amount, category_id=1,
                     user_id="1", description=""):
    """Inserta una transacción de prueba y la devuelve refrescada."""
    transaccion = models.Transaction(
        user_id=user_id,
        type=type,
        amount=amount,
        currency="CLP",
        category_id=category_id,
        description=description,
    )
    session.add(transaccion)
    session.commit()
    session.refresh(transaccion)
    return transaccion


# ===========================================================================
# 1. GET /transactions — paginación y filtros
# ===========================================================================

class TestListTransactions:

    def test_returns_only_default_user(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, user_id="1")
        seed_transaction(db_session, type="gasto", amount=2000, user_id="2")

        response = client.get("/transactions")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert all(t["user_id"] == "1" for t in data)

    def test_default_pagination(self, client, db_session):
        seed_categories(db_session)
        for i in range(5):
            seed_transaction(db_session, type="gasto", amount=100 * (i + 1))

        response = client.get("/transactions")
        assert response.status_code == 200
        # Por defecto: skip=0, limit=100 -> las 5 transacciones
        assert len(response.json()) == 5

    def test_skip_and_limit_partition_results(self, client, db_session):
        seed_categories(db_session)
        for i in range(5):
            seed_transaction(db_session, type="gasto", amount=100 * (i + 1))

        page1 = client.get("/transactions", params={"skip": 0, "limit": 2}).json()
        page2 = client.get("/transactions", params={"skip": 2, "limit": 2}).json()
        page3 = client.get("/transactions", params={"skip": 4, "limit": 2}).json()

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1  # solo queda 1 transacción

        # Sin solapamiento entre páginas
        ids1 = {t["id"] for t in page1}
        ids2 = {t["id"] for t in page2}
        ids3 = {t["id"] for t in page3}
        assert ids1.isdisjoint(ids2)
        assert ids1.isdisjoint(ids3)
        assert ids2.isdisjoint(ids3)

        # La unión de las páginas son las 5 transacciones
        assert ids1 | ids2 | ids3 == {t["id"] for t in client.get("/transactions").json()}

    def test_skip_beyond_total_returns_empty(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000)

        response = client.get("/transactions", params={"skip": 10, "limit": 5})
        assert response.status_code == 200
        assert response.json() == []

    def test_filter_by_type_gasto(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=3500)
        seed_transaction(db_session, type="gasto", amount=1500)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions", params={"type": "gasto"})
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2
        assert all(t["type"] == "gasto" for t in data)

    def test_filter_by_type_ingreso(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=3500)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions", params={"type": "ingreso"})
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "ingreso"
        assert float(data[0]["amount"]) == 50000.0

    def test_filter_by_category_id(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=15000, category_id=1)
        seed_transaction(db_session, type="gasto", amount=2500, category_id=2)
        seed_transaction(db_session, type="gasto", amount=990, category_id=2)

        response = client.get("/transactions", params={"category_id": 2})
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2
        assert all(t["category_id"] == 2 for t in data)

    def test_combined_filters_and_pagination(self, client, db_session):
        seed_categories(db_session)
        for _ in range(4):
            seed_transaction(db_session, type="gasto", amount=100, category_id=1)
        for _ in range(3):
            seed_transaction(db_session, type="gasto", amount=200, category_id=2)
        seed_transaction(db_session, type="ingreso", amount=999, category_id=1)

        response = client.get(
            "/transactions",
            params={"type": "gasto", "category_id": 1, "skip": 1, "limit": 2},
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2  # 4 gastos de categoría 1, con skip=1 quedan 3 -> 2
        assert all(t["type"] == "gasto" and t["category_id"] == 1 for t in data)


# ===========================================================================
# 2. GET /transactions/summary — ingresos, gastos y saldo neto
# ===========================================================================

class TestTransactionsSummary:

    def test_summary_empty_database(self, client, db_session):
        seed_categories(db_session)

        response = client.get("/transactions/summary")
        assert response.status_code == 200

        data = response.json()
        assert set(data.keys()) == {"income", "expenses", "balance"}
        assert float(data["income"]) == 0.0
        assert float(data["expenses"]) == 0.0
        assert float(data["balance"]) == 0.0

    def test_summary_totals_and_net_balance(self, client, db_session):
        seed_categories(db_session)
        # Ingresos: 50000 + 10000 = 60000
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)
        seed_transaction(db_session, type="ingreso", amount=10000, category_id=12)
        # Gastos: 3500 + 1500 = 5000
        seed_transaction(db_session, type="gasto", amount=3500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=1500, category_id=2)

        response = client.get("/transactions/summary")
        assert response.status_code == 200

        data = response.json()
        assert float(data["income"]) == pytest.approx(60000.0)
        assert float(data["expenses"]) == pytest.approx(5000.0)
        # balance = ingresos - gastos
        assert float(data["balance"]) == pytest.approx(55000.0)

    def test_summary_negative_balance(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="ingreso", amount=1000, category_id=12)
        seed_transaction(db_session, type="gasto", amount=3500, category_id=1)

        data = client.get("/transactions/summary").json()
        assert float(data["balance"]) == pytest.approx(-2500.0)

    def test_summary_sums_types_independently(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=3500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=1500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=2500, category_id=2)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions/summary")
        assert response.status_code == 200

        data = response.json()
        assert float(data["expenses"]) == pytest.approx(7500.0)
        assert float(data["income"]) == pytest.approx(50000.0)
        assert float(data["balance"]) == pytest.approx(42500.0)

    def test_summary_ignores_other_users(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, user_id="1")
        seed_transaction(db_session, type="gasto", amount=99999, user_id="2")
        seed_transaction(db_session, type="ingreso", amount=88888, user_id="2")

        data = client.get("/transactions/summary").json()
        assert float(data["expenses"]) == pytest.approx(1000.0)
        assert float(data["income"]) == pytest.approx(0.0)


# ===========================================================================
# 3. POST /transactions/parse — procesamiento de texto con IA (simulada)
# ===========================================================================

class TestParseTransaction:

    def test_parse_success_saves_transaction(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({
            "type": "gasto",
            "amount": 15000,
            "currency": "CLP",
            "category": "Alimentación",
            "description": "Almuerzo",
        })

        response = client.post(
            "/transactions/parse",
            json={"text": "Gasté 15000 en almuerzo"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "guardada" in data["message"]

        # Datos extraídos por la IA
        extracted = data["extracted_data"]
        assert float(extracted["amount"]) == 15000.0
        assert extracted["type"] == "gasto"
        assert extracted["description"] == "Almuerzo"
        # El nombre de categoría se resolvió a su ID
        assert extracted["category_id"] == 1
        assert extracted["category_name"] == "Alimentación"

        # La transacción quedó guardada con el usuario por defecto
        transaccion = data["transaction"]
        assert transaccion["user_id"] == "1"
        assert transaccion["type"] == "gasto"

        # Y realmente existe en la "base de datos" de la prueba
        guardadas = db_session.query(models.Transaction).all()
        assert len(guardadas) == 1
        assert guardadas[0].user_id == "1"

    def test_parse_with_category_id_from_ai(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({
            "type": "ingreso",
            "amount": 50000,
            "category_id": 12,
        })

        response = client.post(
            "/transactions/parse",
            json={"text": "Cobré mi sueldo, 50000"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["extracted_data"]["type"] == "ingreso"
        assert data["extracted_data"]["category_id"] == 12
        assert float(data["extracted_data"]["amount"]) == 50000.0

    def test_parse_unknown_category_defaults_to_7(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({
            "type": "gasto",
            "amount": 990,
            "category": "Categoría Inexistente",
        })

        response = client.post(
            "/transactions/parse",
            json={"text": "Pago misterioso de 990"},
        )
        assert response.status_code == 200
        assert response.json()["extracted_data"]["category_id"] == 7

    def test_parse_invalid_type_returns_422(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "ahorro", "amount": 1000})

        response = client.post(
            "/transactions/parse",
            json={"text": "Ahorro 1000"},
        )
        assert response.status_code == 422
        assert "ahorro" in response.json()["detail"]

    def test_parse_missing_amount_returns_422(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "gasto", "description": "sin monto"})

        response = client.post(
            "/transactions/parse",
            json={"text": "Compré algo pero no recuerdo cuánto"},
        )
        assert response.status_code == 422
        assert "monto" in response.json()["detail"]

        # No debe haber guardado nada
        assert db_session.query(models.Transaction).count() == 0

    def test_parse_ai_failure_returns_502(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai(Exception("Fallo tras 3 intentos"))

        response = client.post(
            "/transactions/parse",
            json={"text": "Gasté 1000 en café"},
        )
        assert response.status_code == 502
        assert "IA" in response.json()["detail"]

        # No debe haber guardado nada
        assert db_session.query(models.Transaction).count() == 0

    def test_parse_requires_text_field(self, client, db_session):
        seed_categories(db_session)

        response = client.post("/transactions/parse", json={})
        assert response.status_code == 422  # validación de Pydantic
