# Failure Matrix (P0)

Status: **normative safety behavior**, executable fault injection begins in P1.

| Failure | Required state/action | Forbidden action |
| --- | --- | --- |
| Intent duplicate key | Reject as duplicate | New submit |
| DB write/commit failure | Stop new orders | Submit before durable state |
| Submit call times out | `UNKNOWN`; reconcile | Automatic submit retry |
| Submit response lost | `UNKNOWN`; reconcile | Infer rejection |
| Duplicate callback | Record evidence; no-op state | Double-count fill/order |
| Late/stale callback | Record evidence; keep monotonic state | State downgrade |
| Callback/query conflict | Preserve both; reconcile | Hide evidence |
| Cannot resolve conflict | `MANUAL_REVIEW`; block related risk | Guess terminal state |
| Cancel timeout | `UNKNOWN`; query original order | Blind repeated cancel loop |
| Market/account data stale | Reject new order | Use last-known as fresh |
| Query returns `None` | Treat as unknown/failure | Treat as empty success |
| Wrong account data | Reject and alarm | Merge into target account |
| QMT reconnect/restart | Stop new orders; full reconcile | Resume from memory only |
| OMS restart | Recover DB; full reconcile | Auto-arm trading |
| Two OMS leaders | Refuse/lose lease | Both submit |
| Disk full/DB read-only | Stop new orders | Continue from RAM |
| Queue full | Explicit rejection/backpressure | Unbounded blocking |
| Clock jump | Fail time checks; investigate | Continue expiry/session logic blindly |
| Human external order | Mark `EXTERNAL`; include in risk | Attribute to strategy |

## Crash boundaries for P1

P1 tests must terminate the process before/after each of:

1. intent insert;
2. risk-decision insert;
3. transition to `SUBMITTING` commit;
4. simulated submit call;
5. response receipt;
6. callback/event write;
7. cancel request write/send boundary;
8. trade write vs derived position update.

Restart always reconciles before accepting new exposure.
