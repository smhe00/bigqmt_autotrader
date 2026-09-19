# Reports

Agent implementation reports only.

每个 report 必须与 task 使用相同的 `task_key`：

```text
P6-T001-I01__implementation-report.md
```

没有对应 task key 的 report 视为 orphan report，不进入 Architect Gate。

## Reply-file convention

Architect 在下发 task 时可以同时预创建对应 report 模板。这样 task 与 Agent 回复从任务开始时就形成固定的一一映射：

```text
tasks/P6-T001-I01__*.md
reports/P6-T001-I01__implementation-report.md
```

预创建 report 的顶部状态必须为：

```yaml
status: AWAITING_AGENT
owner: agent
```

Agent 完成后直接更新同一个文件并改为：

```yaml
status: REVIEW_READY
```

不得另建带日期、`latest`、`final` 等无法机械匹配的新报告文件。
