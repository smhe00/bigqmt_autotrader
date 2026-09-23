CREATE TABLE operations_alert_events (
    event_id TEXT PRIMARY KEY,
    alert_key TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('ACTIVE', 'RESOLVED')),
    severity TEXT,
    detail TEXT,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    semantic_digest TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_operations_alert_events_key_time
ON operations_alert_events(alert_key, observed_at);

CREATE INDEX idx_operations_alert_events_key
ON operations_alert_events(alert_key, observed_at, event_id);

CREATE TABLE operations_alert_state (
    alert_key TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'RESOLVED')),
    severity TEXT NOT NULL,
    detail TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    occurrences INTEGER NOT NULL CHECK(occurrences > 0),
    resolved_at TEXT,
    last_event_id TEXT NOT NULL,
    FOREIGN KEY(last_event_id) REFERENCES operations_alert_events(event_id)
);

CREATE INDEX idx_operations_alert_state_status
ON operations_alert_state(status, alert_key);
