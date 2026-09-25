# Agente Financiero 💸

API REST de **gestión financiera personal** con extracción de transacciones por IA.
FastAPI + SQLAlchemy + Supabase (Postgres) + Groq.

Estado: FASE 0 (endurecimiento) ✅ · FASE 1 (CRUD + idempotencia) ✅ ·
FASE 2 (deploy Render Free) · FASE 3 (multiusuario + chat + frontend).

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado (sin API key) |
| GET | `/` | **Interfaz web** (SPA con pestañas: resumen, ingresos, gastos, ahorros, cuentas, presupuestos, metas) |
| GET | `/transactions` | Listado (`skip`, `limit`, `type`, `category_id`, `?from=&to=`) |
| GET | `/transactions/summary` | `income`/`expenses`/`balance` vía SQL (`?from=&to=`) |
| GET | `/transactions/summary/by-category` | Top por categoría (`?from=&to=&type=`) |
| GET/PUT/DELETE | `/transactions/{id}` | Lectura / edición parcial / borrado |
| POST | `/transactions` | Alta manual (idempotente con `client_request_id`) |
| POST | `/transactions/parse` | IA → **borrador** (no persiste) |
| POST | `/transactions/confirm` | Persiste el borrador (idempotente) |
| GET | `/categories` | Categorías activas |

Respuesta exitosa: `{"data": ..., "meta": {"request_id"}}` ·
Error: `{"error": {"code", "message"}}` ·
Auth: header `X-API-Key` (definida con `API_KEY`; `/health` exenta).

## Desarrollo local

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # completar DATABASE_URL y GROQ_API_KEY
python -m uvicorn main:app --reload
python -m pytest tests -q    # 46 pruebas
```

Migraciones SQL: aplicar en Supabase SQL Editor (`migrations/*.sql`, en orden).

## Producción

Ver **[docs/DEPLOY.md](docs/DEPLOY.md)** — Render Free + Supabase + anti-sleep
con GitHub Actions.
