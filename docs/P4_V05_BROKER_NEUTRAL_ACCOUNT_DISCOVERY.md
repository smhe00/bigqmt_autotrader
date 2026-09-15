# P4 V05 broker-neutral account discovery

Date: 2026-09-16

## Decision

V05 does not identify a terminal as Galaxy, Guojin, or another broker. The QMT
model-trading UI remains the authority for the selected fund account. At startup
and during the 300-second reconciliation cycle, the bridge probes the standard
QMT account-type namespace using that injected account identifier:

- `STOCK`
- `CREDIT`
- `FUTURE`
- `FUTURE_OPTION`
- `STOCK_OPTION`
- `HUGANGTONG`
- `SHENGANGTONG`

This is capability detection, not unrestricted account enumeration. QMT does
not inject every fund account into a model. An account using another fund ID
still requires another explicitly bound model instance.

## Detection contract

For every candidate type V05 queries `ACCOUNT` first. A candidate is detected
only when an account row is observed and its account ID and numeric broker type,
when supplied by QMT, agree with the selected fund account and candidate type.
Only a detected candidate is queried for `POSITION`.

Results are classified as:

- `DETECTED`: account and position cache queries completed;
- `DEGRADED`: the account was identified but its position query failed;
- `UNCONFIRMED`: no valid account evidence was observed.

An empty `ACCOUNT` result, `None`, exception, account mismatch, missing type
evidence for a non-selected candidate, or broker-type mismatch never proves an
empty account. It remains unconfirmed and carries a structured error code.

The bridge emits an `account_capabilities` event before each normal selected-
account snapshot. The event envelope remains pinned to the explicitly selected
OMS account. Child observations contain only SHA-256 account fingerprints,
account types, normalized account rows, positions, and query diagnostics; the
raw fund account ID is not transported.

## Host boundary

Host protocol validation requires:

- unique candidate account types and fingerprints;
- exact agreement between detected records and `detected_account_types`;
- structured account, position, and query-error rows;
- `live_submit=false` and `live_cancel=false`.

The Host stores these observations in a separate read-only linked-account view.
They do not replace the selected account read model and do not change command
identity, risk policy, broker evidence mapping, or OMS authority.

## Callback boundary

The current OMS callback stream remains single-account. When a callback exposes
an account ID or numeric broker type that conflicts with the selected account,
V05 emits a bridge error and refuses to place that callback in the selected
account stream. Automatic cross-account ORDER/DEAL routing remains disabled
until callback identity has been calibrated on each target terminal.

## Safety boundary

- `TRADING_ENABLED = False`
- `live_submit = false`
- `live_cancel = false`
- discovered account types never become trading allowlist entries
- no real broker mutation API is added
- SHADOW command semantics are unchanged
