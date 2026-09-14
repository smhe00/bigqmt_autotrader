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
