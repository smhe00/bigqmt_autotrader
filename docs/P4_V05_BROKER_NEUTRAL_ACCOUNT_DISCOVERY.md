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

The current OMS callback stream remains single-account. A callback for a
non-selected account type that was positively detected during the current
bridge session is suppressed and counted; it is already represented by the
read-only `account_capabilities` projection and must never be misrouted into the
selected OMS account. An account-ID mismatch or a numeric broker type not seen
by runtime discovery still emits a bridge error and fails closed. Automatic
cross-account ORDER/DEAL routing remains disabled until callback identity has
been calibrated on each target terminal.

## Safety boundary

- `TRADING_ENABLED = False`
- `live_submit = false`
- `live_cancel = false`
- discovered account types never become trading allowlist entries
- no real broker mutation API is added
- SHADOW command semantics are unchanged

## Galaxy runtime calibration (2026-09-16)

Galaxy QMT 2.1.26.1 session `5f675ce73bfe4ee39c67303b5ea7291a`
provided broker-neutral startup evidence for `STOCK`, `HUGANGTONG`, and
`SHENGANGTONG`. All three account records and their positions were observed;
the other four standard candidates remained `UNCONFIRMED`. Host accepted both
`account_capabilities` events and both selected-account snapshots, retained
seven candidate records in the linked-account view, reached
`read_model_healthy=true`, and reported zero transport or semantic quarantine.

The same run showed that Galaxy broadcasts periodic ACCOUNT callbacks for both
linked Stock Connect types to a model bound to STOCK. Build
`p4-shadow-command-spool-5` suppresses these positively detected non-selected
callbacks from the selected OMS stream and counts them for diagnostics. Unknown
types and account-ID mismatches continue to fail closed.
