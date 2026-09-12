CREATE TABLE oms_leader (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    session_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch > 0),
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
