# Guojin Production Evidence Mapper Preparation

Status: **OBSERVE-ONLY / NO OMS LIFECYCLE AUTHORITY**

The production Guojin mapper now uses the same strict identity engine as the
calibrated simulation mapper, but its profile is deliberately disabled:

```text
profile              = qmt-guojin-prod-calibration-pending-v1
terminal_instance_id = guojin
source               = qmt:guojin
evidence_enabled     = false
```

It may:

- validate pinned production terminal/account identity;
- validate durable OMS broker token, symbol and quantity identity;
- inspect callback and active-query ORDER/DEAL rows;
- record explicit rejection reasons for calibration.

It may **not** emit BrokerEvidenceV1, so it cannot move OMS to
ACKNOWLEDGED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED.

The existing `guojin_sim` profile remains evidence-enabled and unchanged in
its calibrated 50/54/56/57 semantics.

Enabling any production raw-status mapping requires a later independent Gate
using captured production callback/query evidence. This preparation does not
expand production broker mutation authority or LIVE_CANARY authorization.
