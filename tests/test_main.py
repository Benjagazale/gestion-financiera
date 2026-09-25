"""
Pruebas unitarias para los endpoints del Agente Financiero API (FASE 1).

Estrategia de aislamiento de base de datos:
- SQLite en memoria por prueba con `get_db` sobrescrito (override de FastAPI).
- IA simulada parcheando `services.ai_service.parse_transaction_with_ai`.

Contrato verificado:
- Éxito:  {"data": ..., "meta": {"request_id": ...}}
- Error:  {"error": {"code": ..., "message": ...}}
- IA:     /parse y /process devuelven BORRADOR (no guardan);
          la persistencia ocurre en POST /transactions/confirm (idempotente).

Endpoints cubiertos:
- GET    /categories, /health
- GET    /transactions, /transactions/summary, /transactions/{id}
- POST   /transactions, /transactions/confirm (alta manual, idempotencia)
- PUT    /transactions/{id}   DELETE /transactions/{id}
- POST   /transactions/parse, /transactions/process (borrador IA)
- Seguridad: API key y rate limiting
"""

import json
import os
import sys
from datetime import date
from decimal import Decimal

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from zoneinfo import ZoneInfo

# La raíz del proyecto debe estar en sys.path para poder importar `main`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.config as app_config
import main
import models
from core import rate_limit as rate_limit_mod
from database import Base, get_db
from services import ai_service

ZONA_CHILE = ZoneInfo("America/Santiago")


def hoy_chile() -> date:
    return datetime.now(ZONA_CHILE).date()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _aislar_estado_global(monkeypatch):
    """Rate limit generoso + auth off + buckets limpios por prueba."""
    monkeypatch.setattr(app_config.settings, "parse_rate_limit", 10_000)
    monkeypatch.setattr(app_config.settings, "api_key", None)
    rate_limit_mod.limpiar_buckets()
    yield
    rate_limit_mod.limpiar_buckets()


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
    Simula `services.ai_service.parse_transaction_with_ai`.

    Uso:
        fake_ai({"type": "gasto", "amount": 1000})  -> devuelve ese JSON
        fake_ai(Exception("IA caída"))               -> lanza la excepción
    """

    def _install(result):
        if isinstance(result, Exception):
            def _raise(_texto, **_kwargs):
                raise result
            monkeypatch.setattr(ai_service, "parse_transaction_with_ai", _raise)
        else:
            payload = json.dumps(result)

            def _return(_texto, **_kwargs):
                return payload
            monkeypatch.setattr(ai_service, "parse_transaction_with_ai", _return)

    return _install


def data_of(response):
    """Extrae `data` del envelope y valida la forma de la respuesta exitosa."""
    body = response.json()
    assert "data" in body, f"Falta 'data' en la respuesta: {body}"
    assert "request_id" in body.get("meta", {}), f"Falta meta.request_id: {body}"
    return body["data"]


def error_of(response):
    """Extrae `error` del envelope de error y valida su forma."""
    body = response.json()
    assert "error" in body, f"Falta 'error' en la respuesta: {body}"
    assert "code" in body["error"] and "message" in body["error"]
    return body["error"]


# ---------------------------------------------------------------------------
# Helpers de seeding
# ---------------------------------------------------------------------------

def seed_categories(session):
    """Crea categorías con IDs conocidos (mismos IDs que la base real)."""
    categorias = [
        (1, "Alimentación"),
        (2, "Transporte"),
        (12, "Sueldo y Salario"),
        (17, "Sin Categorizar"),  # default en producción
    ]
    for cat_id, nombre in categorias:
        session.add(models.Category(id=cat_id, name=nombre, is_active=True))
    session.commit()


def seed_transaction(session, *, type, amount, category_id=1,
                     user_id="1", description="", transaction_date=None):
    """Inserta una transacción de prueba y la devuelve refrescada."""
    campos = dict(
        user_id=user_id,
        type=type,
        amount=amount,
        currency="CLP",
        category_id=category_id,
        description=description,
    )
    if transaction_date is not None:
        campos["transaction_date"] = transaction_date
    transaccion = models.Transaction(**campos)
    session.add(transaccion)
    session.commit()
    session.refresh(transaccion)
    return transaccion


# ===========================================================================
# 0. Salud + contrato (envelope de éxito y de error)
# ===========================================================================

class TestHealthAndContract:

    def test_health_returns_envelope(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = data_of(response)
        assert data["status"] == "ok"
        # Sin API_KEY configurada (modo dev) el flag expone que está abierto
        assert data["api_key_configured"] is False

    def test_404_uses_error_envelope(self, client):
        response = client.get("/ruta-inexistente")
        assert response.status_code == 404
        assert error_of(response)["code"] == "NOT_FOUND"

    def test_validation_error_uses_error_envelope(self, client):
        response = client.post("/transactions/parse", json={})
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"

    def test_categories_endpoint(self, client, db_session):
        seed_categories(db_session)
        response = client.get("/categories")
        assert response.status_code == 200
        data = data_of(response)
        assert {c["name"] for c in data} >= {"Alimentación", "Transporte"}


class TestFrontend:
    """Interfaz web servida desde FastAPI (StaticFiles)."""

    def test_index_served_as_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Agente Financiero" in response.text

    def test_static_assets(self, client):
        for ruta in ("/app.js", "/styles.css"):
            response = client.get(ruta)
            assert response.status_code == 200, ruta

    def test_unknown_path_still_uses_error_envelope(self, client):
        # El mount estático no rompe el contrato de 404
        response = client.get("/pagina-que-no-existe")
        assert response.status_code == 404
        assert error_of(response)["code"] == "NOT_FOUND"

    def test_index_has_tab_navigation(self, client):
        """Navegación por pestañas: las 7 secciones obligatorias existen."""
        response = client.get("/")
        assert response.status_code == 200
        for tab in ("resumen", "ingresos", "gastos", "ahorros", "cuentas",
                    "presupuestos", "metas"):
            assert f'data-tab="{tab}"' in response.text, tab
            assert f'id="vista-{tab}"' in response.text, tab

    def test_styles_use_fintoc_palette(self, client):
        """Sesión A: la hoja de estilos usa la paleta Fintoc y no la azul anterior."""
        response = client.get("/styles.css")
        assert response.status_code == 200
        css = response.text.upper()
        for color in ("#0A0A0A", "#121212", "#1E1E24", "#FFFFFF", "#2563EB", "#27272A"):
            assert color in css, f"Falta el color {color}"
        for viejo in ("#012340", "#0367A6", "#0D8BD9", "#4AA2D9", "#79C4F2"):
            assert viejo not in css, f"Sobrevive la paleta anterior {viejo}"

    def test_icons_served_before_app_and_cover_known_categories(self, client):
        """Sesión B: icons.js se carga antes que app.js y cubre las categorías reales."""
        html = client.get("/").text
        assert html.index("/icons.js") < html.index("/app.js")

        response = client.get("/icons.js")
        assert response.status_code == 200
        js = response.text
        assert "iconoCategoria" in js
        # Pares id → ícono de categorías existentes en Supabase
        pares = {"1": "🥙", "2": "🚗", "7": "⚽", "12": "💼", "17": "📦"}
        for cat_id, ico in pares.items():
            assert f'{cat_id}: "{ico}"' in js, f"Falta el ícono de la categoría {cat_id}"


# ===========================================================================
# 0b. Privacidad: noindex de la UI + docs desactivables (Tanda B)
# ===========================================================================

class TestDocsAndPrivacy:

    def test_index_declares_noindex(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "noindex" in response.text

    def test_docs_disabled_returns_envelope_404(self):
        app_off = main.crear_app(enable_docs=False)
        with TestClient(app_off) as cliente:
            for ruta in ("/docs", "/redoc", "/openapi.json"):
                response = cliente.get(ruta)
                assert response.status_code == 404, ruta
                assert error_of(response)["code"] == "NOT_FOUND"

    def test_docs_enabled_with_flag(self):
        app_on = main.crear_app(enable_docs=True)
        with TestClient(app_on) as cliente:
            response = cliente.get("/docs")
            assert response.status_code == 200
            assert "swagger" in response.text.lower()
            response = cliente.get("/openapi.json")
            assert response.status_code == 200
            assert "openapi" in response.json()


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

        data = data_of(response)
        assert len(data) == 1
        assert all(t["user_id"] == "1" for t in data)

    def test_default_pagination(self, client, db_session):
        seed_categories(db_session)
        for i in range(5):
            seed_transaction(db_session, type="gasto", amount=100 * (i + 1))

        response = client.get("/transactions")
        assert response.status_code == 200
        assert len(data_of(response)) == 5

    def test_skip_and_limit_partition_results(self, client, db_session):
        seed_categories(db_session)
        for i in range(5):
            seed_transaction(db_session, type="gasto", amount=100 * (i + 1))

        page1 = data_of(client.get("/transactions", params={"skip": 0, "limit": 2}))
        page2 = data_of(client.get("/transactions", params={"skip": 2, "limit": 2}))
        page3 = data_of(client.get("/transactions", params={"skip": 4, "limit": 2}))

        assert [len(page1), len(page2), len(page3)] == [2, 2, 1]

        ids1 = {t["id"] for t in page1}
        ids2 = {t["id"] for t in page2}
        ids3 = {t["id"] for t in page3}
        assert ids1.isdisjoint(ids2) and ids1.isdisjoint(ids3) and ids2.isdisjoint(ids3)

        todos = {t["id"] for t in data_of(client.get("/transactions"))}
        assert ids1 | ids2 | ids3 == todos

    def test_skip_beyond_total_returns_empty(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000)

        response = client.get("/transactions", params={"skip": 10, "limit": 5})
        assert response.status_code == 200
        assert data_of(response) == []

    def test_filter_by_type_gasto(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=3500)
        seed_transaction(db_session, type="gasto", amount=1500)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions", params={"type": "gasto"})
        assert response.status_code == 200
        data = data_of(response)
        assert len(data) == 2
        assert all(t["type"] == "gasto" for t in data)

    def test_filter_by_type_ingreso(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=3500)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions", params={"type": "ingreso"})
        assert response.status_code == 200
        data = data_of(response)
        assert len(data) == 1
        assert float(data[0]["amount"]) == 50000.0

    def test_invalid_type_rejected_by_schema(self, client, db_session):
        seed_categories(db_session)
        response = client.get("/transactions", params={"type": "ahorro"})
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"

    def test_filter_by_category_id(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=15000, category_id=1)
        seed_transaction(db_session, type="gasto", amount=2500, category_id=2)
        seed_transaction(db_session, type="gasto", amount=990, category_id=2)

        response = client.get("/transactions", params={"category_id": 2})
        assert response.status_code == 200
        data = data_of(response)
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
        data = data_of(response)
        assert len(data) == 2
        assert all(t["type"] == "gasto" and t["category_id"] == 1 for t in data)


# ===========================================================================
# 1b. Filtros de fecha en lista + resumen por categoría (FASE 3)
# ===========================================================================

class TestDateFiltersAndByCategory:

    def test_list_filters_by_date_range(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000,
                         transaction_date=date(2026, 9, 1))
        seed_transaction(db_session, type="gasto", amount=2000,
                         transaction_date=date(2026, 9, 20))
        seed_transaction(db_session, type="gasto", amount=4000,
                         transaction_date=date(2026, 8, 15))

        response = client.get(
            "/transactions", params={"from": "2026-09-01", "to": "2026-09-15"}
        )
        assert response.status_code == 200
        data = data_of(response)
        assert len(data) == 1
        assert float(data[0]["amount"]) == 1000.0

    def test_list_filters_from_only(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000,
                         transaction_date=date(2026, 9, 1))
        seed_transaction(db_session, type="gasto", amount=2000,
                         transaction_date=date(2026, 9, 20))
        seed_transaction(db_session, type="gasto", amount=4000,
                         transaction_date=date(2026, 8, 15))

        data = data_of(client.get("/transactions", params={"from": "2026-09-01"}))
        assert len(data) == 2

    def test_list_invalid_date_range_422(self, client, db_session):
        seed_categories(db_session)
        response = client.get(
            "/transactions", params={"from": "2026-09-30", "to": "2026-09-01"}
        )
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"

    def test_by_category_totals_ordered_desc(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=2500, category_id=2)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        response = client.get("/transactions/summary/by-category",
                              params={"type": "gasto"})
        assert response.status_code == 200
        data = data_of(response)
        assert [i["category_id"] for i in data] == [2, 1]
        assert data[0]["category_name"] == "Transporte"
        assert float(data[0]["total"]) == pytest.approx(2500.0)
        assert data[0]["count"] == 1
        assert data[1]["category_name"] == "Alimentación"
        assert float(data[1]["total"]) == pytest.approx(2000.0)
        assert data[1]["count"] == 2

    def test_by_category_without_type_includes_ingresos(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=2500, category_id=2)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)

        data = data_of(client.get("/transactions/summary/by-category"))
        assert len(data) == 2
        assert {i["type"] for i in data} == {"gasto", "ingreso"}

    def test_by_category_ignores_other_users(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, user_id="1")
        seed_transaction(db_session, type="gasto", amount=99999, user_id="2")

        data = data_of(client.get("/transactions/summary/by-category"))
        assert len(data) == 1
        assert float(data[0]["total"]) == pytest.approx(1000.0)

    def test_by_category_date_filters(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, category_id=1,
                         transaction_date=date(2026, 9, 1))
        seed_transaction(db_session, type="gasto", amount=2000, category_id=1,
                         transaction_date=date(2026, 9, 20))
        seed_transaction(db_session, type="gasto", amount=4000, category_id=2,
                         transaction_date=date(2026, 8, 15))

        data = data_of(client.get(
            "/transactions/summary/by-category",
            params={"type": "gasto", "from": "2026-09-01", "to": "2026-09-15"},
        ))
        assert len(data) == 1
        assert data[0]["category_id"] == 1
        assert float(data[0]["total"]) == pytest.approx(1000.0)

    def test_by_category_null_category_named_sin_categorizar(self, client, db_session):
        seed_categories(db_session)
        tx = seed_transaction(db_session, type="gasto", amount=700, category_id=1)
        # Fila legada insertada fuera de la app: el default del modelo (17) solo
        # aplica en INSERT, así que un UPDATE deja el NULL real que prueba el coalesce
        db_session.query(models.Transaction).filter(
            models.Transaction.id == tx.id
        ).update({"category_id": None})
        db_session.commit()

        data = data_of(client.get("/transactions/summary/by-category"))
        assert len(data) == 1
        assert data[0]["category_id"] is None
        assert data[0]["category_name"] == "Sin Categorizar"
        assert float(data[0]["total"]) == pytest.approx(700.0)

    def test_by_category_invalid_range_422(self, client, db_session):
        seed_categories(db_session)
        response = client.get(
            "/transactions/summary/by-category",
            params={"from": "2026-09-30", "to": "2026-09-01"},
        )
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"

    def test_by_category_empty_database(self, client, db_session):
        seed_categories(db_session)
        data = data_of(client.get("/transactions/summary/by-category"))
        assert data == []


# ===========================================================================
# 2. GET /transactions/summary — income/expenses/balance (agregación SQL)
# ===========================================================================

class TestTransactionsSummary:

    def test_summary_empty_database(self, client, db_session):
        seed_categories(db_session)
        response = client.get("/transactions/summary")
        assert response.status_code == 200
        data = data_of(response)
        assert set(data.keys()) == {"income", "expenses", "balance"}
        assert float(data["income"]) == 0.0
        assert float(data["expenses"]) == 0.0
        assert float(data["balance"]) == 0.0

    def test_summary_totals_and_net_balance(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="ingreso", amount=50000, category_id=12)
        seed_transaction(db_session, type="ingreso", amount=10000, category_id=12)
        seed_transaction(db_session, type="gasto", amount=3500, category_id=1)
        seed_transaction(db_session, type="gasto", amount=1500, category_id=2)

        data = data_of(client.get("/transactions/summary"))
        assert float(data["income"]) == pytest.approx(60000.0)
        assert float(data["expenses"]) == pytest.approx(5000.0)
        assert float(data["balance"]) == pytest.approx(55000.0)

    def test_summary_negative_balance(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="ingreso", amount=1000, category_id=12)
        seed_transaction(db_session, type="gasto", amount=3500, category_id=1)

        data = data_of(client.get("/transactions/summary"))
        assert float(data["balance"]) == pytest.approx(-2500.0)

    def test_summary_ignores_other_users(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, user_id="1")
        seed_transaction(db_session, type="gasto", amount=99999, user_id="2")
        seed_transaction(db_session, type="ingreso", amount=88888, user_id="2")

        data = data_of(client.get("/transactions/summary"))
        assert float(data["expenses"]) == pytest.approx(1000.0)
        assert float(data["income"]) == pytest.approx(0.0)

    def test_summary_date_filters(self, client, db_session):
        seed_categories(db_session)
        seed_transaction(db_session, type="gasto", amount=1000, category_id=1,
                         transaction_date=date(2026, 9, 1))
        seed_transaction(db_session, type="gasto", amount=2000, category_id=1,
                         transaction_date=date(2026, 9, 20))
        seed_transaction(db_session, type="gasto", amount=4000, category_id=1,
                         transaction_date=date(2026, 8, 15))

        data = data_of(client.get(
            "/transactions/summary", params={"from": "2026-09-01", "to": "2026-09-15"}
        ))
        assert float(data["expenses"]) == pytest.approx(1000.0)

        data = data_of(client.get(
            "/transactions/summary", params={"from": "2026-09-01"}
        ))
        assert float(data["expenses"]) == pytest.approx(3000.0)

        data = data_of(client.get(
            "/transactions/summary", params={"from": "2026-08-01", "to": "2026-08-31"}
        ))
        assert float(data["expenses"]) == pytest.approx(4000.0)

    def test_summary_invalid_date_range(self, client, db_session):
        seed_categories(db_session)
        response = client.get(
            "/transactions/summary",
            params={"from": "2026-09-30", "to": "2026-09-01"},
        )
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"


# ===========================================================================
# 3. CRUD — POST / PUT / DELETE / GET por id + idempotencia
# ===========================================================================

class TestTransactionsCrud:

    def test_create_manual_transaction(self, client, db_session):
        seed_categories(db_session)
        antes = hoy_chile()

        response = client.post("/transactions", json={
            "type": "gasto",
            "amount": 8900,
            "currency": "CLP",
            "category_id": 1,
            "description": "Almuerzo",
        })
        assert response.status_code == 201
        data = data_of(response)
        assert data["user_id"] == "1"  # string
        assert float(data["amount"]) == 8900.0
        assert float(data["amount_clp"]) == 8900.0  # CLP sin conversión
        assert data["currency"] == "CLP"

        # transaction_date = hoy en Chile (no UTC del servidor)
        desde = hoy_chile()
        assert date.fromisoformat(data["transaction_date"]) in (antes, desde)

        assert db_session.query(models.Transaction).count() == 1

    def test_create_usd_converts_to_clp(self, client, db_session, monkeypatch):
        seed_categories(db_session)
        monkeypatch.setattr(app_config.settings, "fx_usd_clp", Decimal("900"))

        response = client.post("/transactions", json={
            "type": "gasto",
            "amount": 100,
            "currency": "USD",
            "category_id": 2,
        })
        assert response.status_code == 201
        data = data_of(response)
        assert data["currency"] == "USD"
        assert float(data["amount"]) == 100.0
        assert float(data["amount_clp"]) == pytest.approx(90000.0)

    def test_create_invalid_currency_rejected(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions", json={
            "type": "gasto", "amount": 1000, "currency": "EUR",
        })
        assert response.status_code == 422
        assert error_of(response)["code"] == "VALIDATION_ERROR"

    def test_create_negative_amount_rejected(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions", json={
            "type": "gasto", "amount": -500,
        })
        assert response.status_code == 422
        assert db_session.query(models.Transaction).count() == 0

    def test_create_unknown_category_rejected(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions", json={
            "type": "gasto", "amount": 1000, "category_id": 999,
        })
        assert response.status_code == 422
        assert "999" in error_of(response)["message"]

    def test_create_without_category_defaults_to_17(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions", json={
            "type": "gasto", "amount": 1000,
        })
        assert response.status_code == 201
        assert data_of(response)["category_id"] == 17  # "Sin Categorizar"

    def test_create_is_idempotent_by_client_request_id(self, client, db_session):
        seed_categories(db_session)
        payload = {
            "type": "gasto",
            "amount": 5000,
            "category_id": 1,
            "client_request_id": "uuid-reintento-0001",
        }

        primera = client.post("/transactions", json=payload)
        assert primera.status_code == 201

        # Reintento (ej: timeout de red) → misma transacción, sin duplicado
        segunda = client.post("/transactions", json=payload)
        assert segunda.status_code == 200

        assert data_of(primera)["id"] == data_of(segunda)["id"]
        assert db_session.query(models.Transaction).count() == 1

    def test_create_invalid_client_request_id_rejected(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions", json={
            "type": "gasto", "amount": 1000, "client_request_id": "abc",
        })
        assert response.status_code == 422  # min_length=8

    def test_get_by_id(self, client, db_session):
        seed_categories(db_session)
        tx = seed_transaction(db_session, type="gasto", amount=2500)

        response = client.get(f"/transactions/{tx.id}")
        assert response.status_code == 200
        assert data_of(response)["id"] == tx.id

    def test_get_by_id_not_found(self, client, db_session):
        seed_categories(db_session)
        response = client.get("/transactions/9999")
        assert response.status_code == 404
        assert error_of(response)["code"] == "NOT_FOUND"

    def test_update_transaction(self, client, db_session):
        seed_categories(db_session)
        tx = seed_transaction(db_session, type="gasto", amount=3500, category_id=1)

        response = client.put(f"/transactions/{tx.id}", json={
            "amount": 4000, "category_id": 2, "description": "Corregido",
        })
        assert response.status_code == 200
        data = data_of(response)
        assert float(data["amount"]) == 4000.0
        assert float(data["amount_clp"]) == 4000.0  # recalculado
        assert data["category_id"] == 2
        assert data["description"] == "Corregido"
        assert data["type"] == "gasto"  # campo no enviado permanece igual

    def test_update_not_found(self, client, db_session):
        seed_categories(db_session)
        response = client.put("/transactions/9999", json={"amount": 100})
        assert response.status_code == 404

    def test_update_invalid_fields_rejected(self, client, db_session):
        seed_categories(db_session)
        tx = seed_transaction(db_session, type="gasto", amount=1000)

        response = client.put(f"/transactions/{tx.id}", json={"type": "ahorro"})
        assert response.status_code == 422

        response = client.put(f"/transactions/{tx.id}", json={"amount": -1})
        assert response.status_code == 422

    def test_delete_transaction(self, client, db_session):
        seed_categories(db_session)
        tx = seed_transaction(db_session, type="gasto", amount=1000)

        response = client.delete(f"/transactions/{tx.id}")
        assert response.status_code == 200
        data = data_of(response)
        assert data["deleted"] is True
        assert data["id"] == tx.id

        # Ya no existe
        assert client.get(f"/transactions/{tx.id}").status_code == 404
        assert db_session.query(models.Transaction).count() == 0

    def test_delete_not_found(self, client, db_session):
        seed_categories(db_session)
        response = client.delete("/transactions/9999")
        assert response.status_code == 404


# ===========================================================================
# 4. IA — borrador (/parse, /process) + confirmación (/confirm)
# ===========================================================================

class TestParseAndConfirm:

    def test_parse_returns_draft_without_saving(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({
            "type": "gasto",
            "amount": 15000,
            "currency": "CLP",
            "category": "Alimentación",
            "description": "Almuerzo",
        })
        antes = hoy_chile()

        response = client.post(
            "/transactions/parse", json={"text": "Gasté 15000 en almuerzo"}
        )
        assert response.status_code == 200

        data = data_of(response)
        extracted = data["extracted_data"]
        assert float(extracted["amount"]) == 15000.0
        assert extracted["type"] == "gasto"
        assert extracted["category_id"] == 1
        assert extracted["category_name"] == "Alimentación"

        draft = data["draft"]
        assert draft["type"] == "gasto"
        assert float(draft["amount_clp"]) == 15000.0
        fecha_draft = date.fromisoformat(draft["transaction_date"])
        assert fecha_draft in (antes, hoy_chile())  # hoy Chile

        # NO persistió: el borrador espera confirmación
        assert db_session.query(models.Transaction).count() == 0

    def test_parse_draft_then_confirm_saves(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({
            "type": "gasto",
            "amount": 12500,
            "currency": "CLP",
            "category_id": 2,
            "description": "Taxi al aeropuerto",
        })

        draft = data_of(
            client.post("/transactions/parse", json={"text": "Gasté 12500 en taxi"})
        )["draft"]
        assert db_session.query(models.Transaction).count() == 0

        # El usuario confirma el borrador
        response = client.post("/transactions/confirm", json={
            "type": draft["type"],
            "amount": draft["amount"],
            "currency": draft["currency"],
            "category_id": draft["category_id"],
            "description": draft["description"],
            "transaction_date": draft["transaction_date"],
            "client_request_id": "confirm-flow-0001",
        })
        assert response.status_code == 201
        guardada = data_of(response)
        assert float(guardada["amount"]) == 12500.0
        assert guardada["category_id"] == 2

        assert db_session.query(models.Transaction).count() == 1

        # Reconfirmar (doble clic / reintento) no duplica
        repetida = client.post("/transactions/confirm", json={
            "type": draft["type"],
            "amount": draft["amount"],
            "currency": draft["currency"],
            "category_id": draft["category_id"],
            "description": draft["description"],
            "transaction_date": draft["transaction_date"],
            "client_request_id": "confirm-flow-0001",
        })
        assert repetida.status_code == 200
        assert db_session.query(models.Transaction).count() == 1

    def test_parse_with_category_id_from_ai(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "ingreso", "amount": 50000, "category_id": 12})

        response = client.post(
            "/transactions/parse", json={"text": "Cobré mi sueldo, 50000"}
        )
        assert response.status_code == 200
        draft = data_of(response)["draft"]
        assert draft["type"] == "ingreso"
        assert draft["category_id"] == 12
        assert float(draft["amount"]) == 50000.0

    def test_parse_unknown_category_defaults_to_17(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "gasto", "amount": 990, "category": "Categoría Inexistente"})

        response = client.post(
            "/transactions/parse", json={"text": "Pago misterioso de 990"}
        )
        assert response.status_code == 200
        assert data_of(response)["draft"]["category_id"] == 17  # "Sin Categorizar"

    def test_parse_invalid_type_returns_422(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "ahorro", "amount": 1000})

        response = client.post("/transactions/parse", json={"text": "Ahorro 1000"})
        assert response.status_code == 422
        assert "ahorro" in error_of(response)["message"]

    def test_parse_missing_amount_returns_422(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "gasto", "description": "sin monto"})

        response = client.post(
            "/transactions/parse", json={"text": "Compré algo y no sé cuánto"}
        )
        assert response.status_code == 422
        assert "monto" in error_of(response)["message"]
        assert db_session.query(models.Transaction).count() == 0

    def test_parse_ai_failure_returns_503(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai(Exception("Timeout tras 2 modelos"))

        response = client.post(
            "/transactions/parse", json={"text": "Gasté 1000 en café"}
        )
        assert response.status_code == 503
        error = error_of(response)
        assert error["code"] == "SERVICE_UNAVAILABLE"
        assert "IA" in error["message"]
        assert response.headers.get("Retry-After") == "30"
        assert db_session.query(models.Transaction).count() == 0

    def test_parse_requires_text_field(self, client, db_session):
        seed_categories(db_session)
        response = client.post("/transactions/parse", json={})
        assert response.status_code == 422

    def test_process_alias_returns_draft(self, client, db_session, fake_ai):
        seed_categories(db_session)
        fake_ai({"type": "gasto", "amount": 3500, "category_id": 2})

        response = client.post(
            "/transactions/process", json={"mensaje": "Pagué 3500 de micro"}
        )
        assert response.status_code == 200
        draft = data_of(response)["draft"]
        assert draft["type"] == "gasto"
        assert draft["category_id"] == 2

        # /process tampoco persiste: solo borradores
        assert db_session.query(models.Transaction).count() == 0


# ===========================================================================
# 5. Seguridad — API key y rate limiting
# ===========================================================================

class TestSecurity:

    def test_api_key_required_when_configured(self, client, db_session, monkeypatch):
        monkeypatch.setattr(app_config.settings, "api_key", "clave-secreta-123")
        seed_categories(db_session)

        response = client.get("/transactions")
        assert response.status_code == 401
        assert error_of(response)["code"] == "UNAUTHORIZED"

        response = client.get(
            "/transactions", headers={"X-API-Key": "clave-secreta-123"}
        )
        assert response.status_code == 200

        response = client.get("/transactions", headers={"X-API-Key": "otra-clave"})
        assert response.status_code == 401

    def test_health_exempt_from_api_key(self, client, monkeypatch):
        monkeypatch.setattr(app_config.settings, "api_key", "clave-secreta-123")
        response = client.get("/health")
        assert response.status_code == 200
        # El health sigue exento, pero reporta que la auth está activa
        assert data_of(response)["api_key_configured"] is True

    def test_rate_limit_returns_429(self, client, db_session, fake_ai, monkeypatch):
        monkeypatch.setattr(app_config.settings, "parse_rate_limit", 2)
        seed_categories(db_session)
        fake_ai({"type": "gasto", "amount": 1000, "category_id": 1})

        payload = {"text": "Gasté 1000"}
        assert client.post("/transactions/parse", json=payload).status_code == 200
        assert client.post("/transactions/parse", json=payload).status_code == 200

        response = client.post("/transactions/parse", json=payload)
        assert response.status_code == 429
        assert error_of(response)["code"] == "RATE_LIMITED"
        assert response.headers.get("Retry-After") == "60"
