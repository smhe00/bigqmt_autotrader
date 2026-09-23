CREATE TABLE daily_risk_events (
    event_key TEXT PRIMARY KEY,
    account_fingerprint TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('ORDER_SUBMIT', 'CANCEL_REQUEST', 'TRADE')),
    notional TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE INDEX idx_daily_risk_events_account_date
ON daily_risk_events(account_fingerprint, trading_date, event_type, event_key);

CREATE INDEX idx_daily_risk_events_strategy_date
ON daily_risk_events(account_fingerprint, strategy_id, trading_date, event_type, event_key);

CREATE TABLE daily_risk_pnl_snapshots (
    snapshot_key TEXT PRIMARY KEY,
    account_fingerprint TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    daily_pnl TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(account_fingerprint, trading_date, observed_at)
);

CREATE INDEX idx_daily_risk_pnl_account_date
ON daily_risk_pnl_snapshots(account_fingerprint, trading_date, observed_at);
