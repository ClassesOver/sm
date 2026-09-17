# Reporting Coding Agent 收敛性修复复审

## 范围与方法

复审对象：commit `47d1e2e` "fix(reporting): harden coding agent convergence"，即对
[2026-09-17-coding-agent-convergence-review.md](2026-09-17-coding-agent-convergence-review.md)
中 C1–C6、R1–R6 十二项结论的修复。

审查范围仅限 Coding Agent，不含沙箱隔离与执行面权限。

方法：对 `47d1e2e` 逐文件走查 diff，追踪每项修复的实际行为，并检查修复自身引入的缺陷。

未执行测试：审查环境无 `.venv`、`agno` 未安装。B1 中「轨迹测试已变红」为静态推断，推断链确定但需实跑确认。

## 原结论的修复状态

| 原编号 | 状态 | 备注 |
| --- | --- | --- |
| C1 视觉回执被提前清空 | 已修复 | `clear_execution_receipt()` 拆分正确，`run_script` 的按 sha 过滤逻辑现已生效 |
| C2 `view_image` 未计入交付预留 | 已修复 | 纳入 `_DELIVERY_TOOL_NAMES`，`delivery_reserve` 按声明输出数动态传入 |
| C3 预留区拒绝不计费 | 已修复 | 引入 `escalated` 升级与豁免解除，额度恢复单调；但见 B3、B7 |
| C4 既不重试也不降级 | 已修复 | 两个 workflow 均改为「`retryable is False` ∧ 非可降级」；但见 B2 |
| C5 `outputValidation` 为咨询性 | 已修复 | `result["ok"] = False` + `pending_output_validation` 阻断 `submit_script` |
| C6 修复诊断丢失执行现场 | 已修复 | `traceback`/`stderr`/`stdout` 与 `lastFailure` 均已透传；但见 B7 |
| R1 末次失败抛裸 `RuntimeError` | 已修复 | 改为重抛 `generation_failure`；但见 B6 |
| R2 工具内终止态无法上抛 | 已修复 | `toolkit.terminal_failure` + runner 检查，与模型层对称 |
| R3 registry 互斥形同虚设 | 已修复 | bootstrap 建进程级 registry，`code_runner()` 已缓存单实例 |
| R4 退出码未显式校验 | **引入回归** | 见 B1 |
| R5 rebase 身份配对 | 部分修复 | 取 `call_id or id` 单一身份而非并集，见 B7 |
| R6 其他 | 大部分已修复 | 诊断预算下限、`max_kernels` 求和、`finally` 兜底、空 `evidencePath`、LSP 均已处理；探索额度计费未动 |

## 新引入缺陷摘要

| 编号 | 问题 | 严重度 | 处理 |
| --- | --- | --- | --- |
| B1 | 退出码检测变成单一脆弱通道，且已让现有轨迹测试变红 | P0 | 已修复 |
| B2 | analysis 与 visualization 收敛策略「不对称」 | P1 | 复审后确认为有意设计，非缺陷 |
| B3 | 冗余 `view_image` 拒绝会毒化整个批次 | P1 | 已修复 |
| B4 | `requiredNextTools` 向 analysis 任务通告不存在的 `view_image` | P1 | 已修复 |
| B5 | `_attach_tool_budget` 异常捕获不全、重写内容格式、突破 8 KiB 上限 | P2 | 未处理 |
| B6 | `_MAX_GENERATE_ATTEMPTS` 成死常量，非降级类重试从 3 次变 4 次 | P2 | 未处理 |
| B7 | rebase 单一身份、截断标记丢弃、升级计数不复位、诊断缺阻塞原因等 | P2 | 未处理 |

## 本轮处理结果

对 B1、B3、B4 三项已在代码中修复，改动与新增/更新的测试见下表。B2 经复审后判定为有意
设计而非缺陷，未改动生产代码。

| 编号 | 改动文件 | 测试 |
| --- | --- | --- |
| B1 | `code_mode.py`（恢复 `exit $report_exit`、双流查找标记）、`toolkit.py`（`run_script` 同步改为标记与 status 交叉校验） | 重写 `test_run_script_fails_closed_on_missing_or_nonzero_process_exit` 为三条定向用例：标记缺失但 status ok 视为成功、标记与 status 冲突视为失败、标记只出现在 stdout 时仍可查找到 |
| B3 | `protocol.py`（`_ordered_code_calls` 内区分「冗余审查」与「真正预算拒绝」，冗余审查不置 `stopped`；新增 `report_code_visual_review_redundant` 并纳入 `_is_non_executed_control_result` 豁免） | 更新 `test_tool_results_include_budget_and_reserved_view_rejects_current_review` 断言新 code；新增 `test_redundant_view_image_rejection_does_not_stop_batch` 验证同批次后续 `submit_script` 仍执行 |
| B4 | `protocol.py`（`requiredNextTools` 改为 `_DELIVERY_TOOL_NAMES & self._code_tool_names`） | 未单独补测试；现有 batch 测试未断言该字段的具体内容，行为改动安全 |

### B2 复审结论：不是缺陷

`analysis_item_workflow.py` 对 `no_submission` 等可降级 code 首次出现即调用
`_abandon_supplement(state)`，起初被判定为「收敛策略不对称」。复审代码后发现：

- `_abandon_supplement` 只追加一条软告警（`report_analysis_supplement_abandoned`），
  退回到仅用确定性事实完成分析，不是致命失败——补充 evidence 本身是可选增强。
- 现有测试 `test_analysis_v1_degrades_after_no_submission`
  （`test_reporting_v1_workflows.py`）显式断言 `run_count == 1`，即首次
  `no_submission` 就应放弃重试并完成分析，这是既有且经过测试验证的设计。

对一份可选产物，首次失败即放弃、避免为它烧一轮全新工具预算是合理选择；这与
visualization 对必需图表先重试到 `MAX_VISUALIZATION_EXECUTION_REPAIRS` 才降级的策略
不同，是刻意的不对称，不是遗漏。已在 `analysis_item_workflow.py` 对应位置补充注释
说明该设计意图，未改变行为。

---

## 新引入缺陷

### B1. 退出码检测变成单一脆弱通道

`code_mode.py:38-45`：

```python
"%%bash\n"
"set +e\n"          # ← 关掉了 IPython 的非零退出传播
f"{command}\n"
"report_exit=$?\n"
f'echo "{_SCRIPT_EXIT_MARKER}$report_exit" >&2\n'    # ← 最后一条命令必然成功
```

`set +e` 之后 cell 的最后一条命令是 `echo`，因此 `cell.status` 恒为 `"ok"`。原先由 IPython
`raise_error=True` 提供的独立失败信号被主动废除，失败判定完全依赖从 stderr 文本正则出
`__REPORT_EXIT__=N`（`code_mode.py:47-52`）。

三个具体失败模式：

1. **stderr 被截断导致成功脚本误判失败。** CodeMode 确实会截断——`toolkit.py:808` 的
   `_cell_field(cell, "truncated", ())` 即为此存在。matplotlib 向 stderr 写警告很常见，一旦
   尾部标记被截掉，`exit_code is None` 即判失败，白烧一整轮修复预算。
2. **stderr 与 stdout 若被合并，则每次 `run_script` 都失败。** 标记只写 stderr，也只从
   stderr 读，没有回退到 stdout。
3. **失去第二通道。** 缺少 `exit $report_exit`，`status` 与标记不再互为校验。

已可确认的证据：`smart_reporting/reporting/tests/test_reporting_code_agent_trajectories.py:109-112`
的 fake 返回的 `CellResult` 不含标记，而该文件不在 `47d1e2e` 的改动列表内。该文件第 146 行
确实驱动 `run_script`，因此这些轨迹测试按代码推断必然失败。请实跑确认。

修复建议：双通道 + 双流查找。

```python
def _script_process_cell(script_path: str) -> str:
    command = " ".join((shlex.quote(sys.executable), shlex.quote(script_path)))
    return (
        "%%bash\n"
        "set +e\n"
        f"{command}\n"
        "report_exit=$?\n"
        f'echo "{_SCRIPT_EXIT_MARKER}$report_exit" >&2\n'
        "exit $report_exit\n"          # ← 恢复 status 通道
    )


def script_process_exit_code(cell: Any) -> int | None:
    for name in ("stderr", "stdout"):          # ← 两个流都查找
        text = _cell_field(cell, name, "")
        if isinstance(text, str) and (matches := list(_SCRIPT_EXIT_PATTERN.finditer(text))):
            return int(matches[-1].group(1))
    return None
```

并把「标记丢失」与「脚本失败」拆成两个 code（例如 `report_code_exit_marker_missing`），
否则运维无法区分这两类。同时更新轨迹测试的 fake。

根治方案见 A5。**处理：已修复**——`code_mode.py` 恢复 `exit $report_exit`
并让 `script_process_exit_code` 同时查找 stderr 与 stdout；`toolkit.py` 与
`code_mode.py` 的两处调用点都改为「标记缺失视为成功（信任已恢复的 status），
标记与 status 冲突才拒绝」。

### B2. analysis 与 visualization 收敛策略「不对称」——复审后确认为有意设计

`analysis_item_workflow.py:818`：

```python
if exhausted or error.code in _DEGRADABLE_CODES:
    return self._abandon_supplement(state)
```

`no_submission` 第一次出现即放弃补充分析，零重试；而 visualization 侧对同一批 code
是先重试到 `MAX_VISUALIZATION_EXECUTION_REPAIRS` 才降级。初审时判定为不对称缺陷。

复审后发现 `_abandon_supplement` 只追加一条软告警，退回到仅用确定性事实完成分析——
补充 evidence 本身是可选增强，不是致命失败。且现有测试
`test_analysis_v1_degrades_after_no_submission`（`test_reporting_v1_workflows.py`）
显式断言 `run_count == 1`，即首次失败就应放弃重试。对一份可选产物，首次失败即放弃、
不为它烧一轮全新工具预算是合理选择，这与 visualization 对必需图表的策略不同，是
刻意的不对称。**处理：不是缺陷，未修改行为**，仅在原位置补充说明该设计意图的注释。

### B3. 冗余 `view_image` 拒绝会毒化整个批次

`protocol.py:656-700`：命中预留区的冗余 `view_image` 被拒绝后同样置 `stopped = True`，
导致同一响应内后续调用全部跳过——而其中可能正是尚未审查的 `view_image(B)` 或 `submit_script`。

冗余调用不是失败，不应终止批次。

修复建议：拒绝冗余调用时 `continue` 但不置 `stopped`；只有真正的预算拒绝才置 `stopped = True`。

**处理：已修复**——`_ordered_code_calls` 拆出 `is_redundant_review` 分支，命中时产出新的
`report_code_visual_review_redundant`/`skipped` 控制结果并 `continue`，不设置 `stopped`，
也纳入 `_is_non_executed_control_result` 豁免（不计费）。同批次内后续调用（例如尚未审查
的 `view_image` 或 `submit_script`）会继续正常执行。

### B4. `requiredNextTools` 向 analysis 任务通告不存在的 `view_image`

`protocol.py:684` 使用 `sorted(_DELIVERY_TOOL_NAMES)`，而 `view_image` 只在
`task_kind == "visualization"` 时注册（`toolkit.py:547-566`）。

若 analysis 的模型照提示调用该工具，`protocol.py:527-528` 会抛
`report_code_custom_tool_protocol_error`（`retryable: False`，且不在 `_DEGRADABLE_CODES`），
导致整个 task 硬失败。一句无害引导被升级为致命错误。

修复建议：

```python
"requiredNextTools": sorted(
    _DELIVERY_TOOL_NAMES & (getattr(self, "_code_tool_names", None) or frozenset())
),
```

**处理：已修复**——按上述代码原样应用。

### B5. `_attach_tool_budget` 的三个问题

`protocol.py:344-361`：

- `ast.literal_eval` 只捕获 `(SyntaxError, ValueError)`，深嵌套输入会抛 `RecursionError`
  甚至 `MemoryError` 并逃逸到模型调用栈。
- 把 Python repr 重写为 JSON，同一会话内工具结果格式在不同轮次间不一致。
- 在 `_safe_diagnostic_details` 刚精确塞满 `MAX_DIAGNOSTIC_BYTES`（8 KiB）之后追加 `budget`
  键，突破刚建立的硬上限。

修复建议：捕获面扩为 `(SyntaxError, ValueError, RecursionError, MemoryError)`；为 `budget`
预留字节数（例如把 `_safe_diagnostic_details` 的有效上限降为 `MAX_DIAGNOSTIC_BYTES - 64`）。

### B6. `_MAX_GENERATE_ATTEMPTS` 成死常量

`visualization_section_workflow.py:451` 改为 `generate_attempt == max_attempts - 1`，而
`max_attempts = max(3, 3 + 1)` 恒为 4。R1 的修复顺带把「可恢复但不可降级」类的重试次数
从 3 提到 4，每次失败多一次昂贵模型运行，且常量名与实际行为不符（第 60 行仍写 `= 3`）。

修复建议：明确二者语义。要么该类仍用 `_MAX_GENERATE_ATTEMPTS` 封顶，要么删除该常量并
在注释中注明有效次数为 4。

### B7. 其余

- **rebase 只取单一身份。** `context_management.py:1094-1100` 使用
  `call.get("call_id") or call.get("id")` 而非两者并集。当前两条路径都能工作（Responses 有
  `call_id`，Chat Completions 回退到 `id`），但若某条结果按另一字段落键仍会整轮丢弃。
  改为并集成本相同且更稳。
- **`_repair_diagnostic` 丢弃截断标记。** `visualization_section_workflow.py:143-146` 弃用
  `_truncated`，模型无法判断自己看到的是片段；而 `code_generation.py:331-337` 设置了
  `{field}Truncated`。两处不一致。
- **`_code_reserve_rejections` 永不复位。** 模型恢复有效进展后再次进入预留区，第一次拒绝
  即被判 `escalated` 并计费。建议在成功的交付类调用后归零。
- **`submission_diagnostic()` 不暴露 `pending_output_validation`。** `toolkit.py:640-656`
  仍只报 `hasExecutionReceipt: True`，冷启动修复 run 看不到真正的阻塞原因。
- **探索额度耗尽仍计费。** `report_code_exploration_budget_exhausted` 不在
  `protocol.py:321-323` 的豁免集内。保留可能是刻意的（强制收敛），但与 C3 的升级机制
  存在语义重叠，建议统一。

---

## 架构与设计缺陷

### A1. 协议层通过 `__self__` 反射伸进业务层

`protocol.py:363-373`：

```python
owner = getattr(call.function, "source_toolkit", None) or getattr(entrypoint, "__self__", None)
checker = getattr(owner, "has_current_visual_review", None)
```

wire 协议层依靠「猜 Agno `Function` 是否有 `source_toolkit`」、「绑定方法反射」、「鸭子类型
方法名」三级兜底获取业务状态。任何一环变化都会静默退化为「不判冗余」，且完全不可观测。

建议改为显式注入：

```python
configure_code_run(
    toolkit.tool_functions,
    max_model_requests=...,
    delivery_reserve=...,
    redundant_call_check=toolkit.has_current_visual_review,
)
```

### A2. 预算记账分散在三处，各有独立复位语义

| 位置 | 计数 | 复位 |
| --- | --- | --- |
| `protocol.py:326-333` `_limit_charge_for` | 豁免未执行回执 | — |
| `protocol.py:656-700` `_ordered_code_calls` | 预留门禁与升级计数 | 永不 |
| `protocol.py:392-401` `_consume_code_request` | 模型请求数 | 每 task |

C3 的「仅 escalated 计费」本质是补丁：因为豁免让计数非单调，才需要另造升级开关把单调性
找回来。三个计数器交互后的行为已难以静态推演，B3 与 B7 的两个问题均源于此。

建议抽出单一 `CodeBudget` 值对象，持有 `used` / `limit` / `reserve` / `rejections`，把
「是否计费」「是否进入预留」「是否升级」实现为显式状态转移，协议层只调用它。

### A3. 失败分类表三处重复，需手工保持同步

- `visualization_section_workflow.py:48-70` —— `_NON_RECOVERABLE_CODES` 与 `_DEGRADABLE_CODES`
- `analysis_item_workflow.py:40-56` —— 同名两张表，内容不同
- `code_generation.py:59-77` —— `_code_failure_kind` 第三套映射

本次修复不得不同时改动三处才能保持三张表语义一致，即便最终结论是其中一处的
「不对称」本就是有意为之（见 B2），排查这一点仍然消耗了完整的一轮复审。这正是
重复定义的代价：正确性判断必须靠人工比对三张表，而不能从单一权威定义直接得出。

建议新建 `code_agent/failure_policy.py`，以 `{code: (recoverable, degradable, thinking_kind)}`
单表驱动，两个 workflow 与 runner 共同消费。

### A4. `retryable: False` 语义进一步过载

修复后其实际含义变为「不可重试，除非同时可降级」——一个跨两个文件、由「布尔字段 ∧ 集合
成员」表达的合取条件（`visualization_section_workflow.py:246-253`、
`analysis_item_workflow.py:802-807`）。抛错点无法表达自身的恢复意图，只能靠下游两张表反推。

建议在抛出处直接声明恢复策略，例如 `details={"recovery": "retry" | "degrade" | "fatal"}`，
下游只读该字段，`retryable` 保留兼容映射。

### A5. 退出码契约是隐式文本协议，且解析点分散

正则匹配 stderr 文本本身即脆弱契约（见 B1），且当前有三个解析点：`code_mode.py:150` 的
`execute_script`、`code_mode.py:47` 的 `script_process_exit_code` 调用方、以及
`toolkit.py:1055` 的 `run_script`。

建议将脚本退出码写入 workspace 内的哨兵文件（例如 `.report_exit`），由
`execute_script_process` 统一读取并返回结构化字段，上层只消费该字段。既免疫截断与流合并，
也把契约收敛到一处。

---

## 建议落地顺序（已完成 B1、B3、B4；B2 判定为非缺陷；B5–B7 待处理）

| 优先级 | 项目 | 状态 |
| --- | --- | --- |
| P0 | B1 双通道 + 双流查找 | 已修复；轨迹测试原本使用的 fake 不含标记，恢复 `exit $report_exit` 后 `status` 重新权威，无需改动该 fake |
| P1 | B3 不毒化批次、B4 过滤工具名 | 均已修复 |
| — | B2 | 复审后判定为有意设计，未改动行为，仅补注释 |
| P2 | B5–B7 | 未处理，留待下一轮 |
| 架构 | A5 → A2 → A3 → A1 → A4 | 未处理；A5（哨兵文件）会让 B1 的双通道文本解析彻底成为历史 |

## 已完成的回归测试

1. `test_reporting_code_agent_stability.py`：`test_run_script_tolerates_truncated_exit_marker_when_status_ok`
   （标记缺失但 status ok 视为成功）、
   `test_run_script_fails_closed_on_exit_marker_status_mismatch`
   （标记与 status 冲突视为失败，校验 `exitCode`）、
   `test_run_script_finds_exit_marker_in_stdout_when_streams_merged`
   （标记只出现在 stdout 时仍可查找到）。原有的
   `test_run_script_fails_closed_on_missing_or_nonzero_process_exit` 已替换——它原先
   断言的「标记缺失即失败」正是 B1 的回归行为。
2. `test_reporting_code_agent_batches.py`：更新
   `test_tool_results_include_budget_and_reserved_view_rejects_current_review` 的断言为新
   code `report_code_visual_review_redundant`/`skipped` 且不计费；新增
   `test_redundant_view_image_rejection_does_not_stop_batch` 验证同批次内紧随其后的
   `submit_script` 仍会执行。

## 待办

- B4 未单独补测试：现有 batch 测试未对 `requiredNextTools` 的具体内容做断言，行为改动
  本身安全，但建议后续补一条 analysis 任务下该字段不含 `view_image` 的定向用例。
- B5、B6、B7 与全部架构项（A1–A5）未处理，按原建议顺序留待下一轮。
