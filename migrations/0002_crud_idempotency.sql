-- FASE 1: CRUD + idempotencia + normalización de moneda
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(64);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount_clp NUMERIC(12, 2);

-- Reintentos seguros: un mismo client_request_id no puede crear duplicados
CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_client_request_id
    ON transactions (client_request_id);
