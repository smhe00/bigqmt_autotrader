CREATE TABLE IF NOT EXISTS order_intents (
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    limit_price TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    PRIMARY KEY(account_fingerprint, client_order_id)
);

CREATE TABLE IF NOT EXISTS broker_orders (
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    filled_quantity INTEGER NOT NULL DEFAULT 0 CHECK(filled_quantity >= 0),
    submit_call_started INTEGER NOT NULL DEFAULT 0 CHECK(submit_call_started IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(account_fingerprint, client_order_id),
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
    reason_code TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    PRIMARY KEY(account_fingerprint, client_order_id),
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE TABLE IF NOT EXISTS order_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    disposition TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE INDEX IF NOT EXISTS idx_order_events_key
ON order_events(account_fingerprint, client_order_id, event_id);

CREATE TABLE IF NOT EXISTS runtime_sessions (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    reconciled_at TEXT
);
