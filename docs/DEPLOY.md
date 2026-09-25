# Deploy en Render Free (FASE 2)

Guía paso a paso para publicar la API en **Render Free** ($0, sin tarjeta) usando
**Supabase** como base de datos.

> ⚠️ No usar el Postgres Free de Render: caduca a los 30 días y borra los datos.
> Supabase (ya configurado) es la BD permanente.

## 1. Variables de entorno necesarias

| Variable | Valor | Origen |
|---|---|---|
| `DATABASE_URL` | String de conexión de Supabase **+ `?sslmode=require`** | Supabase → Connect → Connection string (modo **Session**, puerto 6543) |
| `GROQ_API_KEY` | Clave de Groq | [console.groq.com/keys](https://console.groq.com/keys) |
| `API_KEY` | Clave aleatoria larga para el header `X-API-Key` | Generar: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `FX_USD_CLP` | `950` (ya en `render.yaml`) | — |

Generar `DATABASE_URL` de Render a partir de la de `.env`:

```bash
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
u = os.getenv('DATABASE_URL')
print(u + ('' if 'sslmode' in u else '?sslmode=require'))"
```

## 2. Crear el servicio en Render

1. Crear cuenta gratis en [render.com](https://render.com) (sin tarjeta).
2. **New + → Blueprint** → conectar el repo de GitHub (`Benjagazale/gestion-financiera`).
3. Render detecta `render.yaml` automáticamente. Rama: **`dev`**.
4. En el paso de *Environment*, completar los 3 secretos (`DATABASE_URL`,
   `GROQ_API_KEY`, `API_KEY`).
5. Apply → el build instala dependencias y **corre los 46 tests**; un commit con
   pruebas rojas no llega a producción.
6. Esperar el primer deploy (~2-3 min). URL esperada:
   `https://agente-financiero.onrender.com`.

## 3. Verificación post-deploy

```bash
BASE=https://agente-financiero.onrender.com
API_KEY=...   # la definida en Render

curl -s $BASE/health                      # data.status = ok (sin API key)
curl -s $BASE/transactions/summary        # 401 (auth activa en prod)
curl -s $BASE/transactions/summary -H "X-API-Key: $API_KEY"   # income/expenses/balance
curl -s -X POST $BASE/transactions/parse -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" -d '{"text":"Pague 4500 en la micro"}'
```

El primer request tras inactividad tarda ~60 s (cold start) — es esperado.

## 4. Anti-sleep (GitHub Actions)

`.github/workflows/keep-awake.yml` hace ping a `/health` cada 10 min (Render
duerme a los 15 min). Repo público → costo $0.

1. En GitHub: **Settings → Secrets and variables → Actions → Variables**
2. Agregar `RENDER_URL` = `https://agente-financiero.onrender.com`
3. Probar: pestaña **Actions → Keep Render Awake → Run workflow**

Notas:
- GitHub desactiva los cron de repos con 60 días sin commits → mantener actividad.
- Servicio siempre despierto consume ~744 de las 750 hrs/mes gratis (cubre un
  solo servicio; un segundo servicio gratuito no tendría horas).
- Si se duerme igual (caída de GitHub Actions), la API sigue funcionando con
  cold start de ~1 min — aceptado por el plan.

## 5. Migraciones SQL

La BD no se migra automáticamente. Aplicar manualmente en **Supabase → SQL
Editor** los archivos de `migrations/` en orden (ya aplicados: `0001`, `0002`).
Nuevo schema → agregar `migrations/000N_*.sql` + aplicar **antes** del deploy
que lo usa.

## 6. Seguridad en producción

- `API_KEY` **siempre definido** en Render (si se vacía, la API queda abierta).
- `ENABLE_DOCS` **sin definir** en Render → `/docs`, `/redoc` y `/openapi.json` responden 404
  (el contrato de la API no queda expuesto). Para activarlos en local: `ENABLE_DOCS=true` en `.env`.
- `.env` nunca se sube al repo (solo `.env.example` con placeholders).
- Cuando exista frontend: restringir `CORS_ORIGINS` al dominio real
  (actualmente `*`, aceptable mientras no haya navegador exponiendo claves).
- Rotar `GEMINI_API_KEY` vieja en Google AI Studio (pendiente manual).

## 7. Operación

- **Logs**: Dashboard → Render → Logs (últimos 7 días en plan gratis).
- **Deploy automático**: cada push a `dev` dispara build + tests + deploy.
- **Rollback**: Dashboard → Deploys → Deploy anterior → Rollback.
- **Cuenta de límites**: Dashboard → Billing (750 hrs, 500 min de build, 5 GB egress/mes).
