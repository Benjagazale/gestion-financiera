CREATE INDEX IF NOT EXISTS ix_transactions_user_type ON transactions (user_id, type);
CREATE INDEX IF NOT EXISTS ix_transactions_user_date ON transactions (user_id, transaction_date);
CREATE INDEX IF NOT EXISTS ix_transactions_user ON transactions (user_id);
