ALTER TABLE broker_evidence_keys ADD COLUMN account_fingerprint TEXT;
ALTER TABLE broker_evidence_keys ADD COLUMN semantic_digest TEXT;

DROP INDEX idx_broker_evidence_source_event_id;
CREATE UNIQUE INDEX idx_broker_evidence_source_account_event_id
ON broker_evidence_keys(source, account_fingerprint, source_event_id)
WHERE source_event_id IS NOT NULL;

ALTER TABLE broker_evidence_observations ADD COLUMN source_kind TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN mapper_profile TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN semantic_digest TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN broker_token TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN order_ref TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN trade_id TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN raw_payload_ref TEXT;
ALTER TABLE broker_evidence_observations ADD COLUMN raw_status_json TEXT;
