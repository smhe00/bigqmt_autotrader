# Risk Model (P0 Contract)

Status: contract only; full implementation begins in P2.

## Four levels

### Global

New orders require all of the following:

- runtime mode permits trading;
- QMT, account, market data, OMS and database are healthy;
- startup reconciliation is complete;
- no unresolved blocking ambiguity exists;
- trading date/time is valid;
- daily loss, turnover, order and cancellation limits remain within policy;
- strategy heartbeat and execution lease are valid.

### Account

- deployment account fingerprint matches;
- cash, positions and active orders are fresh;
- maximum exposure and minimum cash buffer are respected;
- one active OMS leader only;
- cross-account data is rejected.

### Strategy

- strategy ID/version is allow-listed;
- capital budget, universe, turnover and position-count limits apply;
- stale strategy heartbeat rejects new intents;
- a new strategy version must re-enter shadow/canary promotion.

### Security / order

- supported market/security and tradability;
- LIMIT only in v1;
- valid tick, price band and deviation;
- valid quantity and lot rules;
- sell <= explicit available quantity and A-share T+1 semantics;
- buy cost + fee buffer <= available cash;
- single-order/security/activity/rate limits;
- `SUBMITTING`/`UNKNOWN` ambiguity blocks potentially duplicative exposure.

## Stable P0 reason-code namespace

Reserved codes:

- `RISK_OK`
- `RISK_MODE_NOT_ARMED`
- `RISK_DATA_STALE`
- `RISK_UNKNOWN_ORDER`
- `RISK_DUPLICATE_CLIENT_ORDER_ID`
- `RISK_ACCOUNT_MISMATCH`
- `RISK_INTENT_EXPIRED`
- `RISK_INVALID_ORDER`
- `RISK_LIMIT_EXCEEDED`
- `RISK_STRATEGY_NOT_ALLOWED`
- `RISK_MARKET_CLOSED`
- `RISK_DATABASE_UNHEALTHY`
- `RISK_LEADER_NOT_HELD`

Codes are append-only once used in an audit record. Their human-readable text may improve; semantic meaning may not silently change.
