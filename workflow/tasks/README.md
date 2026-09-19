# Tasks

Architect-only task queue.

Filename:

```text
<task_key>__<short-slug>.md
```

例：`P6-T001-I01__live-canary-authority-repair.md`

新任务递增 `Txxx`；同一任务修复轮次递增 `Ixx`。Agent 不应修改已下发的 task 文件。
