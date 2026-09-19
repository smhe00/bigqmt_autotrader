# Repository Agent Workflow

本目录专门承载 Architect ↔ Agent 的任务交接、执行报告和审计结果。长期设计、正式规范和项目状态仍放在 `docs/`；不得再把临时任务书、Agent implementation report 或 Architect review 混入 `docs/`。

## Directory contract

```text
workflow/
├── tasks/       # Architect 发布的任务 / fix request
├── reports/     # Agent 对应任务的执行报告
├── reviews/     # Architect 对 Agent 报告与代码的独立审计
└── control/
    └── WORKFLOW_STATE.yaml
```

## Task key

每一轮交接使用唯一的：

```text
P<phase>-T<task:03d>-I<iteration:02d>
```

例如：

```text
P6-T001-I01
P6-T001-I02
P6-T002-I01
```

含义：

- `P6`：项目阶段 / Gate；
- `T001`：该阶段第 1 个逻辑任务；
- `I01`：该任务第 1 次实现迭代。

**新逻辑任务**：递增 `Txxx`，iteration 重置为 `I01`。  
**CHANGES_REQUIRED / fix loop**：保持同一 `Txxx`，只递增 `Ixx`。

## Filename matching

同一轮 task / report / review 必须共享完全相同的 task key：

```text
workflow/tasks/P6-T001-I01__live-canary-authority-repair.md
workflow/reports/P6-T001-I01__implementation-report.md
workflow/reviews/P6-T001-I01__architect-review.md
```

匹配规则只认文件名前缀中的完整 `task_key`，不得根据标题、日期或“最新文件”猜测。

## Ordering

所有 task number 和 iteration 都必须零填充，因此普通字典序就是执行顺序：

```text
P6-T001-I01
P6-T001-I02
P6-T002-I01
...
```

不得使用 `T1`、`I2` 等非零填充形式。

## State authority

`workflow/control/WORKFLOW_STATE.yaml` 是当前协作状态的唯一控制入口。

Agent 开始工作前必须同时满足：

1. `owner: agent`；
2. `state: AGENT_READY` 或 `state: CHANGES_REQUIRED`；
3. `task_key` 位于 `authorized_next`；
4. `task_file` 存在；
5. 自己将写入的 report 路径必须与 `expected_report_file` 完全一致。

Agent 完成后：

- 代码和测试正常提交；
- 只创建/更新 `expected_report_file`；
- 不创建 Architect review；
- 不擅自推进下一 task；
- 将控制状态交给 Architect 时，使用新 handoff id / handoff sequence（若 Agent 具备该控制文件写权限）。

Architect 审计后：

- PASS：写对应 `reviews/<task_key>__architect-review.md`，再创建下一 task；
- CHANGES_REQUIRED：同一 `Txxx` 创建下一 `Ixx` task；
- BLOCKED / USER_ESCALATION：停止自动推进。

## Separation rule

`docs/` 只保存具有长期参考价值的产品/架构/验证文档，例如：

- architecture / contract；
- formal verification 说明；
- Gate 的最终结论；
- project overview / project status。

以下内容一律放在 `workflow/`：

- code audit task；
- implementation task；
- fix request；
- Agent implementation report；
- Architect code review；
- task handoff state。

最终 PASS 后，如结论具有长期价值，可以由 Architect 把结论摘要同步进 `docs/`，但 `workflow/` 中的原始任务链仍保留作为审计轨迹。


## Machine-enforced contract

`python tools/verify_workflow_contract.py` is a permanent CI gate.

It verifies:

- every task has exactly one matched implementation report and one matched architect review;
- the three files share the exact same `task_key`;
- task iterations start at `I01` and remain contiguous;
- report `reply_to` and review `review_of` point to the exact paired files;
- `WORKFLOW_STATE.yaml` paths match the active `task_key`;
- state/owner/authorized_next are mutually consistent;
- active report/review frontmatter status agrees with control state.

A workflow commit that breaks these invariants must fail CI instead of relying on human convention.

## State transitions

```text
ARCHITECT_PLANNING
        |
        v
AGENT_READY  ----------------------+
        |                          |
        | Agent completes          | Architect requests fixes
        v                          |
REVIEW_READY                       |
        |                          |
        +--> PASS -----------------+--> next Txxx / I01
        |
        +--> CHANGES_REQUIRED ----------> same Txxx / next Ixx
        |
        +--> BLOCKED / USER_ESCALATION
```

During `AGENT_READY` or `CHANGES_REQUIRED`, `authorized_next` must contain exactly the current
`task_key`. During Architect-owned states it must be empty.


### Agent -> Architect handoff

Agent 完成实现时必须在同一个提交中完成两类 communication 更新：

1. 更新当前 `workflow/reports/<task_key>__implementation-report.md`
   - `status: REVIEW_READY`
   - 填写 implementation/final commit、验证结果与安全声明；
2. 更新 `workflow/control/WORKFLOW_STATE.yaml`
   - `handoff_seq` 递增；
   - 使用新的唯一 `handoff_id`；
   - `state: REVIEW_READY`；
   - `owner: architect`；
   - `report_status: REVIEW_READY`；
   - `review_status: AWAITING_REVIEW`；
   - `authorized_next: []`。

Agent 不得修改对应 `workflow/reviews/` 文件，也不得创建下一任务。

如果只改 report 而不交还 control state，或只改 control state 而不改 report，`verify_workflow_contract.py`
必须使 CI 失败。

`audit_base_commit` 是 Architect 做代码审计时的参考快照，不要求 Agent checkout 到该提交。
Agent 实现时应从收到任务时的最新 `main` 开始，并保留之后已合入的 workflow/文档基础设施。


## Recommended command flow

Agent completes implementation:

    python tools/agent_workflow_handoff.py --implementation-commit <FULL_SHA>
    python tools/verify_workflow_contract.py

Architect completes review body, then records verdict:

    python tools/architect_workflow_verdict.py --verdict PASS
    # or CHANGES_REQUIRED / BLOCKED / USER_ESCALATION
    python tools/verify_workflow_contract.py

For a non-final PASS, the verdict tool enters ARCHITECT_PLANNING. Create and activate the
next logical task:

    python tools/scaffold_workflow_handoff.py \
      --next-task \
      --slug <short-slug> \
      --title "<title>" \
      --audit-base-commit <FULL_SHA>

For CHANGES_REQUIRED, create and activate the next iteration of the same task:

    python tools/scaffold_workflow_handoff.py \
      --next-iteration \
      --slug <short-slug> \
      --title "<fix title>" \
      --audit-base-commit <FULL_SHA>

A final project/Gate PASS can be recorded with:

    python tools/architect_workflow_verdict.py --verdict PASS --final

The scripts deliberately do not commit or push. Git remains the final transaction boundary,
so the operator can inspect the diff before publishing.
