CREATE TABLE qmt_command_results (
    command_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    qmt_session_id TEXT NOT NULL,
    qmt_sequence INTEGER NOT NULL CHECK(qmt_sequence > 0),
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT,
    command_type TEXT NOT NULL,
    broker_token TEXT,
    result_status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    live_side_effect INTEGER NOT NULL CHECK(live_side_effect IN (0, 1)),
    payload_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(qmt_session_id, qmt_sequence),
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE INDEX idx_qmt_command_results_order
ON qmt_command_results(account_fingerprint, client_order_id, ingested_at);

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

CREATE TABLE qmt_execution_dispatches (
    command_id TEXT PRIMARY KEY,
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    command_type TEXT NOT NULL CHECK(command_type IN ('SUBMIT_LIMIT', 'CANCEL_ORDER')),
    qmt_session_id TEXT NOT NULL,
    broker_token TEXT NOT NULL,
    broker_order_id TEXT,
    frame_digest TEXT NOT NULL,
    frame_blob BLOB NOT NULL,
    dispatch_state TEXT NOT NULL CHECK(dispatch_state IN (
        'PLANNED', 'PUBLISHED', 'OBSERVED_CLAIMED', 'OBSERVED_PROCESSED',
        'OBSERVED_REJECTED', 'UNKNOWN', 'MANUAL_REVIEW'
    )),
    created_ms INTEGER NOT NULL,
    expires_ms INTEGER NOT NULL,
    published_at TEXT,
    UNIQUE(account_fingerprint, client_order_id, command_type),
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE INDEX idx_qmt_execution_dispatch_recovery
ON qmt_execution_dispatches(account_fingerprint, qmt_session_id, dispatch_state, command_id);
