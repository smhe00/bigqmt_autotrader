# Security and Authority Boundary (P0)

Status: **normative for all phases**

## Authority separation

### Strategy Service

May:

- read normalized market/portfolio state;
- emit `OrderIntent`.

May not:

- receive a QMT credential/token;
- call QMT order/cancel APIs;
- change live runtime mode.

### Execution / OMS Service

Future unique external holder of trading authority. It owns:

- durable order state;
- pre-trade risk;
- reconciliation;
- leases and runtime mode;
- audit trail.

Only one OMS leader may represent an account.

### QMT-side bridge

Runs in the constrained Big QMT Python environment. It will eventually expose a fixed whitelist, not a generic RPC/eval surface.

Forbidden permanently:

- arbitrary method dispatch;
- `eval` / `exec` from external input;
- raw externally supplied `opType/prType/quickTrade`;
- transfer/account-configuration methods;
- hidden bypass around OMS/risk.

P0 bridge capability is intentionally limited to `ping` and `capabilities`; submit/cancel entry points throw `E_TRADING_DISABLED`.

### Operations Console

May request mode changes, stop-new-order, audited cancel and later manual reconciliation actions. It may not call QMT directly.

## Network boundary

The first implementation target is localhost-only (`127.0.0.1`) framed JSON. No Redis/ZMQ/network-wide listener is required for v1.

Future messages must include protocol version, request ID, OMS instance ID, account fingerprint, method, deadline and authentication material; trading requests additionally carry `client_order_id`.

## Secrets

Never commit:

- account number or raw identity;
- password, token or auth material;
- QMT userdata path;
- local broker configuration;
- live logs/databases containing account data.

The repository `.gitignore` contains baseline exclusions but is not considered a secret-management system.

## Runtime default

Every restart defaults to non-trading (`DISABLED`/`OBSERVE`) until reconciliation and explicit later-phase unlock conditions succeed.
