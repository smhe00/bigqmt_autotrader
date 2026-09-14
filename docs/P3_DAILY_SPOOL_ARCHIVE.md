# P3 Daily Spool Archive Contract

Updated: 2026-09-14

## Purpose

The Guojin QMT P3 transport uses durable small files because the calibrated built-in CPython 3.6.8 runtime cannot load `_socket`. Small files are a short-lived cross-process mailbox and crash-recovery buffer, not the long-term event database.

Production retention policy:

```text
QMT event
  -> inbox/*.json                  atomic publication
  -> Host validation/ingestion
  -> processed/*.json              durable until daily archive commits
  -> archive/YYYY-MM-DD_events.jsonl.gz
     + archive/YYYY-MM-DD_manifest.json
     + checkpoints/YYYY-MM-DD.json
  -> delete only the exact archived processed/*.json source files
```

Malformed/protocol-invalid files go to `quarantine/` and are never silently deleted.

## Trading-day convention

Archive day classification is explicitly UTC+08:00 (A-share local time), independent of the Windows Host timezone.

## Default automatic schedule

`python -m bigqmt_autotrader.qmt.host` defaults to:

- file-spool transport;
- automatic daily archive enabled;
- today's archive is eligible after `16:10` UTC+08:00;
- five-minute quiet period (`300 s`);
- archive eligibility rechecked every `30 s`;
- compact Host status summary every `60 s`;
- historical unarchived days are retried on Host startup.

CLI overrides:

```text
--no-auto-archive
--archive-after HH:MM
--archive-quiet-seconds SECONDS
--archive-check-interval SECONDS
--status-summary-interval SECONDS
```

## Commit gate

A day is not considered archived merely because a gzip file exists. Before source-file deletion, all of the following must hold:

1. no same-day file remains in `inbox/`;
2. no same-day file is present in `quarantine/`;
3. a clean full `snapshot` with `query_errors=[]` remains the final broker-state convergence baseline;
4. the quiet period has elapsed from the last material broker-state event; when only identical ACCOUNT heartbeats follow the final clean snapshot, the snapshot timestamp remains the quiet-period anchor;
5. all selected events use one account fingerprint;
6. sequence numbers have no internal gap inside each QMT session;
7. after the final clean snapshot, only ACCOUNT callbacks whose payload is exactly identical to the snapshot ACCOUNT row are permitted;
8. any changed ACCOUNT fact, POSITION, ORDER, DEAL, bridge error, or other event after the clean snapshot blocks commit until a newer clean snapshot arrives;
9. the gzip archive is written and atomically published;
10. the manifest is written and atomically published;
11. gzip is re-opened and every JSON line is decoded and validated;
12. compressed archive SHA-256, uncompressed event-stream SHA-256, event count and trading day all match the manifest;
13. a `COMMITTED` checkpoint containing archive and manifest hashes is durably written;
14. the committed archive set is verified again.

Only after step 14 may the exact source small files listed in the manifest be deleted.

This deliberately tolerates the calibrated Guojin behavior where an unchanged ACCOUNT heartbeat may arrive every approximately 300 seconds after the final clean snapshot. Such a heartbeat neither invalidates the clean snapshot nor resets the quiet timer. Real broker-state changes still require a newer clean snapshot.

## Daily outputs

For trading day `2026-09-14`:

```text
archive/2026-09-14_events.jsonl.gz
archive/2026-09-14_manifest.json
checkpoints/2026-09-14.json
```

The gzip contains the original validated transport JSON lines in chronological order. The manifest records:

- trading day;
- account fingerprint;
- event count;
- first/last timestamp;
- quiet-period anchor timestamp;
- per-session first/last sequence and event count;
- final clean snapshot identity;
- number of trailing identical ACCOUNT heartbeats;
- archive SHA-256;
- uncompressed event-stream SHA-256;
- exact source filenames and source-file-set SHA-256.

## Host logging policy

Normal production logging is intentionally compact:

- always log ready, snapshot, ORDER, DEAL, bridge/resync/error, quarantine and archive state changes;
- log ACCOUNT when its semantic value changes;
- suppress per-event logs for semantically duplicate ACCOUNT callbacks and routine POSITION backlog events;
- keep protocol sequence processing unchanged even when the per-event console line is suppressed;
- emit a compact cumulative `summary` every 60 seconds by default.

This is console-log suppression only. It does not discard already published spool evidence.

## Host restart recovery

`processed/` is also the durable restart journal for the current unarchived period. A Host-only restart performs a read-only replay from the newest clean snapshot in `processed/`, then continues with new `inbox/` events. Replay never moves, rewrites, or deletes source files. Session changes, sequence gaps, account mismatches, corruption, and downstream ingestion failures remain fail-closed.

This is required because a daily-bar QMT model can keep emitting ACCOUNT callbacks after market close without generating another periodic full snapshot. Host health therefore must not depend on restarting QMT whenever the Host process restarts.

## Crash recovery

The design is idempotent around the commit boundary:

- crash before checkpoint: source small files remain; archive can be rebuilt/reverified;
- crash after checkpoint but before cleanup: Host verifies archive + manifest + checkpoint, then resumes deletion of only the manifest-listed source files;
- corrupt archive/manifest/checkpoint: cleanup is blocked and recoverable source files remain;
- new late event after a committed day: status becomes `late_events`; the new file is retained for operator/reconciliation handling and is not silently appended or deleted.

## Quarantine

`quarantine/` is for malformed or protocol-invalid transport files. Presence of a same-day quarantine file blocks daily archive commit for that day. This prevents an apparently clean archive from hiding evidence loss.

Historical quarantine is intentionally not auto-deleted. It must be inspected or explicitly reconciled before the day can commit.

ORDER/DEAL semantic quarantine inside Host ingestion is a separate mechanism: those broker facts remain fail-closed until Guojin order/deal status mapping is calibrated.

## Safety scope

This archive subsystem is read-only infrastructure. It has no broker command channel and grants no trading authority. P4 submit/cancel remains unimplemented and unauthorized.
