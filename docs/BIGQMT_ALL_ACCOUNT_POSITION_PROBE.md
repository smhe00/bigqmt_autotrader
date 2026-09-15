# Big QMT all-account position probe

Date: 2026-09-16

This is a one-shot read-only diagnostic for a Galaxy Big QMT terminal where one
fund account is exposed through three broker types:

- `STOCK`
- `HUGANGTONG`
- `SHENGANGTONG`

The probe is `qmt_side/BIGQMT_ALL_ACCOUNT_POSITION_PROBE.py`.

## Safety boundary

The source performs only three calls to:

```python
get_trade_detail_data(account, account_type, "position")
```

It contains no order, cancel, task-control, callback-subscription, thread, or
process operation. A query returning `None` is reported as failure rather than
being interpreted as an empty account. The raw fund account is never printed;
each account type is represented by a SHA-256 fingerprint.

## Run procedure

1. In Big QMT, create a temporary Python strategy from the probe source.
2. Add it to **Model Trading** and bind the ordinary Galaxy stock account.
3. Use simulation-signal mode. The script does not submit signals or orders.
4. Start once and wait for one log line beginning with:

   ```text
   BIGQMT_POSITION_PROBE=
   ```

5. Stop the temporary strategy. Do not leave it running.

The JSON payload reports each account type independently. `status=OK` with
`position_count=0` is a confirmed empty position list. `QUERY_FAILED` is not an
empty account and must be investigated or retried only after the terminal cache
is healthy.

Big QMT documents that `get_trade_detail_data` reads the client-side cache, not
the broker counter synchronously. The observation time and terminal login/cache
health therefore matter when interpreting the result.
