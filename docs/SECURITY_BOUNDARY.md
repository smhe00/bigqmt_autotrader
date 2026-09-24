# Security and Authority Boundary

Updated: 2026-09-25
Status: **normative for all phases**

## Authority separation

### Strategy

May read normalized state and emit `OrderIntent`. It may not receive broker credentials,
call QMT submit/cancel, modify runtime authority or bypass Risk/OMS.

### Production Runtime

Owns strategy admission, production Risk, health, mode and operational policy. It must
fail closed before handing an authorized intent to Core. Configuration cannot invent broker
authority not present in the selected reviewed deployment artifact.

### Execution Core / OMS

Owns durable identity, persist-before-side-effect, single writer/fencing, submit/cancel
reservation, broker evidence, reconciliation, UNKNOWN and restart recovery. Only one valid
leader may represent an account. Control-plane success cannot produce broker lifecycle state.

### QMT Bridge

Runs in constrained Big QMT Python and exposes a fixed file-spool protocol, not generic RPC.
It may perform broker mutation only when the exact deployment build, instance, execution
mode, account fingerprint, current session and command all satisfy a reviewed Gate.

Permanently forbidden:

- arbitrary method dispatch or external `eval`/`exec`;
- externally supplied raw `opType`, `prType` or `quickTrade`;
- transfer/account-configuration APIs;
- cross-instance spool reuse;
- identity/session bypass;
- automatic permission expansion from discovery, broker name or account type;
- blind retry after an unknown submit/cancel outcome.

### Operations

May request audited mode/control actions through Runtime/OMS. It may not call QMT directly or
rewrite durable evidence to force a terminal state.

## Transport and instance boundary

The calibrated transport is a durable local file spool:

```text
D:\BigQMTData\spool\<instance_id>
```

Each instance owns its manifest, session, sequence, event/command directories, archive and
checkpoint. Host discovery treats directory names only as candidates and then validates the
manifest/build/mode/account/session/fingerprint. Malformed, mismatched, uncommitted or
integrity-invalid data fails closed.

## Current mutation boundary

- generic and `galaxy`: SHADOW, zero submit/cancel call surface;
- `guojin_sim`: bounded `simulation_only=true` calibration for one pinned simulated account;
- `guojin`: only the reviewed `p6-guojin-live-canary-7` single case and fuse, not general LIVE.

No migration, environment variable, file copy, instance selection or account discovery may
broaden these boundaries.

## Secrets and durable data

Never commit account numbers/raw identities, passwords, tokens, QMT userdata, broker config,
production logs, databases or spool contents. `.gitignore` is only a baseline, not a secret
manager. Backups must preserve database/WAL consistency and account/instance isolation.

## Restart default

Restart requires identity/session validation and reconciliation before new work. A new QMT
session invalidates stale commands. Ambiguous mutation remains UNKNOWN/RECONCILING or
MANUAL_REVIEW; restart is not permission to retry.
