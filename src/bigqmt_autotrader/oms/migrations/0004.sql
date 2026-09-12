CREATE TABLE broker_evidence_keys (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_event_id TEXT,
    accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
    result_disposition TEXT,
    conflict_reason TEXT,
    first_observed_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_broker_evidence_source_event_id
ON broker_evidence_keys(source, source_event_id)
WHERE source_event_id IS NOT NULL;

CREATE TABLE broker_evidence_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    source TEXT NOT NULL,
    source_event_id TEXT,
    account_fingerprint TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    broker_order_id TEXT,
    requested_status TEXT NOT NULL,
    filled_quantity INTEGER NOT NULL CHECK(filled_quantity >= 0),
    classification TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(account_fingerprint, client_order_id)
      REFERENCES order_intents(account_fingerprint, client_order_id)
);

CREATE INDEX idx_broker_evidence_order
ON broker_evidence_observations(account_fingerprint, client_order_id, observation_id);

CREATE INDEX idx_broker_evidence_fingerprint
ON broker_evidence_observations(fingerprint, observation_id);
