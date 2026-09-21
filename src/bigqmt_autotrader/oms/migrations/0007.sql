CREATE TABLE qmt_durable_command_identities (
    command_id TEXT PRIMARY KEY,
    account_fingerprint TEXT NOT NULL,
    qmt_session_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    broker_token TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL CHECK(quantity > 0 AND quantity <= 100),
    limit_price TEXT NOT NULL,
    command_state TEXT NOT NULL CHECK(command_state IN ('processed', 'unknown')),
    command_digest TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    expires_ms INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(account_fingerprint, client_order_id),
    UNIQUE(account_fingerprint, broker_token),
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE INDEX idx_qmt_durable_command_session
ON qmt_durable_command_identities(account_fingerprint, qmt_session_id, command_id);

ALTER TABLE broker_evidence_observations ADD COLUMN route_account_type TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN route_account_fingerprint TEXT;
