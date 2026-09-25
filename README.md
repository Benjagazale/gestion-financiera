# Agente Financiero 💸

**Gestión financiera personal** con extracción de transacciones por IA.
FastAPI + SQLAlchemy + Supabase (Postgres) + Groq · SPA vanilla sin build.

Estado: FASE 0 ✅ · FASE 1 ✅ · FASE 2 ✅ (deploy Render) ·
FASE 3 UI ✅ (pestañas, paleta Fintoc, íconos, registro, vista agrupada) ·
siguiente: multiusuario (Supabase Auth + RLS) y chat con IA.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado (sin API key) |
| GET | `/` | **Interfaz web** (SPA con7 pestañas) |
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

## Interfaz web (FASE 3 UI)

Servida por FastAPI desde `frontend/` — mismo origen, sin CORS, sin build ni
dependencias. Assets: `index.html` · `styles.css` · `icons.js` · `app.js`.

- **7 pestañas** con hash routing (`#resumen` … `#metas`) y carga perezosa:
  Resumen, Ingresos, Gastos, Ahorros, Mis Cuentas, Presupuestos, Metas.
- **Ancho ≥80% del viewport** (`96vw`) con grid de12 columnas y breakpoints
  en1199px /767px /540px (en móvil las columnas colapsan a una).
- **Período global**: el selector de mes filtra todas las secciones.
- **Privacidad**: HTML con `noindex, nofollow`; documentación (`/docs`,
  `/openapi.json`) deshabilitada en producción con `ENABLE_DOCS=false` (default).

### Paleta Fintoc (tokens en `styles.css` → `:root`)

| Token | Valor | Rol |
|---|---|---|
| `--fondo` | `#0A0A0A` | fondo principal |
| `--elevado` | `#121212` | header, toolbar, inputs, botones secundarios |
| `--superficie` | `#1E1E24` | tarjetas y paneles |
| `--texto` | `#FFFFFF` | texto principal |
| `--acento` | `#2563EB` | CTA, tabs activas, barras, focus rings |
| `--borde` | `#27272A` | bordes y separación |
| derivados | `#3B82F6` · `#0055FF` · `#A1A1AA` | hover · activo · texto suave |
| semánticos | `--verde` `#4ADE80` / `--rojo` `#F87171` | **solo dinero** (ingresos/gastos) |

### Íconos por categoría — `frontend/icons.js`

Mapa `ICONOS_CATEGORIA` (id de Supabase → emoji), default `📦`:

| | | | |
|---|---|---|---|
| 1 🥙 Alimentación | 2 🚗 Transporte | 3 🎬 Ocio | 4 🏠 Hogar |
| 5 🥬 Feria | 6 🛒 Supermercado | 7 ⚽ Deporte | 8 🏥 Salud |
| 9 📺 Suscripciones | 10 💡 Servicios | 11 💳 Deudas | 12 💼 Sueldo |
| 13 💻 Freelance | 14 🎁 Regalos | 15 📈 Inversiones | 16 💰 Otros Ingresos |
| 17 📦 Sin Categorizar | | | |

> **Contrato**: al crear una categoría nueva en la base, agregar **una línea**
> al mapa en `icons.js` (si no, se usa el default 📦).

### Registro — `crearPanelRegistro()` en `app.js`

Una sola fuente de markup (Registro rápido con borrador IA + Alta manual)
instanciada **3 veces** vía slots `data-slot` en el HTML: Resumen, Ingresos
(tipo ingreso por defecto) y Gastos (tipo gasto por defecto). Sin IDs
duplicados: markup con `data-role` + referencias por instancia en `REGISTROS`.

### Vista de movimientos

Toggle **[Por categoría | Lista]** en las3 listas (Resumen/Ingresos/Gastos).
La agrupada muestra columnas kanban por categoría — agrupación client-side
por `category_id`, orden por monto total, íconos en los encabezados.
Estado persistido en `localStorage` (`vista_mov`), default agrupado.

## Desarrollo local

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # completar DATABASE_URL y GROQ_API_KEY
python -m uvicorn main:app --reload
python -m pytest tests -q                #68 pruebas
node --check frontend/app.js             # sintaxis JS pre-commit
node --check frontend/icons.js
```

Migraciones SQL: aplicar en Supabase SQL Editor (`migrations/*.sql`, en orden).

## Producción

Ver **[docs/DEPLOY.md](docs/DEPLOY.md)** — Render Free + Supabase + anti-sleep
con GitHub Actions.
