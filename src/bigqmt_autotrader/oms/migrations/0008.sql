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
