ALTER TABLE broker_orders
ADD COLUMN cancel_call_started INTEGER NOT NULL DEFAULT 0
CHECK(cancel_call_started IN (0, 1));

ALTER TABLE broker_orders
ADD COLUMN cancel_outcome_resolved INTEGER NOT NULL DEFAULT 0
CHECK(cancel_outcome_resolved IN (0, 1));
