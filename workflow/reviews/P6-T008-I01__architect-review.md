---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I01
task_key: P6-T008-I01
review_of: workflow/reports/P6-T008-I01__implementation-report.md
task_file: workflow/tasks/P6-T008-I01__guojin-sim-oms-hgt-linked-fill.md
status: CHANGES_REQUIRED
owner: architect
---

# P6-T008-I01 Architect Review

## Gate verdict

**CHANGES_REQUIRED**

The linked-route mutation was correctly blocked before submit. The task did not establish the HGT fill invariant, but it exposed a separate read-only prerequisite defect.

## Verified blocker

- startup subscribes/probes the bounded instrument set;
- tick callbacks update in-memory evidence, but instrument_tick_capabilities is published only on the first observed callback;
- the current full-tick probe skips a symbol once tick_observed is already true;
- REQUEST_SNAPSHOT refreshes account capabilities and account/order/deal snapshot only;
- therefore Host can receive fresh account/route state while the latest published exact-symbol tick remains stale.

The 2026-09-22 HGT preflight correctly refused to treat yesterday's exact tick or today's position last_price as fresh exact-route tick evidence. Zero broker mutation occurred.

## Required next iteration

Create a narrow read-only fix: REQUEST_SNAPSHOT on guojin_sim must force a fresh bounded exact-symbol tick poll and publish a new timestamped instrument_tick_capabilities event.

Requirements:
1. no new broker mutation authority;
2. re-poll previously observed symbols instead of skipping them;
3. exact-symbol validation remains mandatory;
4. preserve broker tick time and local observation time;
5. stale/unparseable tick remains fail-closed at the consumer;
6. regression proves a second request can replace an old tick with a newer tick;
7. deployment consistency and CI remain green.

After this prerequisite passes and is deployed locally, rerun the HGT fill as the next small iteration.

No production/live authority is granted.
