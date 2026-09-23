CREATE TABLE runtime_mode_transitions (
    request_id TEXT PRIMARY KEY,
    runtime_session_id TEXT NOT NULL,
    from_mode TEXT NOT NULL,
    to_mode TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE INDEX idx_runtime_mode_transitions_session
ON runtime_mode_transitions(runtime_session_id, changed_at, request_id);
