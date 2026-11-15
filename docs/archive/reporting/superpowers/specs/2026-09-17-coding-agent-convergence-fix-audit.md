# Reporting Coding Agent 收敛性修复复审

## 后续实施进展（2026-09-17）

以下是基于当前工作区与定向实跑的更新；下文对 `47d1e2e` 的评审保留为历史记录。

- **A5 已实现**：`execute_script_process` 通过 workspace 内每次执行唯一的
  `.reporting-exits/<uuid>.status` 文件读取退出码，返回 `ScriptProcessResult`。
  继续使用 Agno CodeMode 执行 cell；Agno 的 `CellResult` 没有子进程退出码字段，
  因此只在宿主适配层补充回执。`execute_script` 和 toolkit 不再解析 stdout/stderr
  中的标记；缺失、非法或超长回执无法产生成功执行凭据。非零退出与 cell 失败仍保留
  执行错误分类。回执在 `finally` 中清理，清理失败通过 loguru 记录，不覆盖执行根因。
- **B2 结论修订**：接续的工作区改动恢复 analysis 按已有 generation/repair 预算
  重试到耗尽再软降级，并把阻塞提交的校验根因带到下一轮。轨迹测试已验证此路径；
  下文“首次 no_submission 即降级是有意设计”的结论已被此实现取代。
- **B5 结论修订**：Agno 普通 dict 工具结果确实可采用 Python repr；当前协议层
  附加预算时保留 JSON/repr 各自格式。下文“repr 未见真实触发点”的判断不再适用。
- **A1–A4 已实施**：详见文末第二轮记录；B4、B5、B7-2 的定向边界测试也已补齐。

本轮测试结果见文末追加记录。

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
| B5 | `_attach_tool_budget` 异常捕获不全、重写内容格式、突破 8 KiB 上限 | P2 | 已修复（异常捕获与硬上限；重写内容格式保留，风险已确认低） |
| B6 | `_MAX_GENERATE_ATTEMPTS` 成死常量，非降级类重试从 3 次变 4 次 | P2 | 已修复 |
| B7 | rebase 单一身份、截断标记丢弃、升级计数不复位、诊断缺阻塞原因等 | P2 | 已修复 4/5；探索额度计费复审后确认为有意设计 |

## 本轮处理结果

对 B1、B3、B4、B5、B6、B7（除探索额度计费外）已在代码中修复，改动与新增/更新的测试见
下表。B2 与 B7 的探索额度计费经复审后判定为有意设计而非缺陷，未改动行为。

| 编号 | 改动文件 | 测试 |
| --- | --- | --- |
| B1 | `code_mode.py`（恢复 `exit $report_exit`、双流查找标记）、`toolkit.py`（`run_script` 同步改为标记与 status 交叉校验） | 重写 `test_run_script_fails_closed_on_missing_or_nonzero_process_exit` 为三条定向用例：标记缺失但 status ok 视为成功、标记与 status 冲突视为失败、标记只出现在 stdout 时仍可查找到 |
| B3 | `protocol.py`（`_ordered_code_calls` 内区分「冗余审查」与「真正预算拒绝」，冗余审查不置 `stopped`；新增 `report_code_visual_review_redundant` 并纳入 `_is_non_executed_control_result` 豁免） | 更新 `test_tool_results_include_budget_and_reserved_view_rejects_current_review` 断言新 code；新增 `test_redundant_view_image_rejection_does_not_stop_batch` 验证同批次后续 `submit_script` 仍执行 |
| B4 | `protocol.py`（`requiredNextTools` 改为 `_DELIVERY_TOOL_NAMES & self._code_tool_names`） | 未单独补测试；现有 batch 测试未断言该字段的具体内容，行为改动安全 |
| B5 | `protocol.py`（`_attach_tool_budget` 扩大异常捕获面、加内容长度与编码后字节数上限） | 未单独补测试（异常路径极难自然触发，覆盖成本高于收益；靠代码走查确认） |
| B6 | `visualization_section_workflow.py`（非降级可恢复失败改回按 `_MAX_GENERATE_ATTEMPTS` 独立封顶，不再借用为可降级失败预留的更大 `max_attempts`） | 新增 `test_visualization_recoverable_nondegradable_failure_capped_at_max_generate_attempts` |
| B7-1 | `context_management.py`（`_complete_rounds` 改为按调用分别收集 `call_id`/`id` 身份集合，只要结果覆盖任一身份即视为完成，而不是把两种身份拍平成一个集合再做子集判断——后者对单个调用同时携带两种身份时仍会误判不完整） | 新增 `test_complete_rounds_accepts_result_keyed_by_item_id_instead_of_call_id`、`test_complete_rounds_drops_round_missing_any_call_coverage` |
| B7-2 | `visualization_section_workflow.py`（`_repair_diagnostic` 的 `traceback`/`stderr`/`stdout` 截断补上 `{field}Truncated` 标记，与 `code_generation.py` 的 `_short_diagnostic` 对齐） | 未单独补测试；已有测试未断言该字段缺失 |
| B7-3 | `protocol.py`（成功的交付类工具调用后重置 `_code_reserve_rejections`） | 新增 `test_successful_delivery_call_resets_reserve_rejection_escalation` |
| B7-4 | `toolkit.py`（`submission_diagnostic()` 暴露 `pendingOutputValidation`）、`code_generation.py` 与 `visualization_section_workflow.py`（分别在 `_short_diagnostic`/`_repair_diagnostic` 中让 `pendingOutputValidation` 优先于可能已过期的 `lastFailure`） | 新增 `test_short_diagnostic_prefers_pending_output_validation_over_stale_last_failure`、`test_visualization_repair_diagnostic_prefers_pending_output_validation` |

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

**处理：已修复异常捕获与硬上限**——新增 `_ATTACH_BUDGET_MAX_CONTENT_CHARS`（跳过超大内容，
兼顾防御 `ast.literal_eval` 的病态输入）与 `_ATTACH_BUDGET_MAX_ENCODED_BYTES`（附加 `budget`
后若整体超过该上限则放弃附加）。「把 Python repr 重写为 JSON」一项未改动：复审后确认
`message.content` 在本系统实际路径上始终是 `json.dumps` 产出（`ast.literal_eval` 分支未见
真实触发点），格式不一致风险主要是理论上的，收益不足以再引入一套格式探测/保留逻辑。

### B6. `_MAX_GENERATE_ATTEMPTS` 成死常量

`visualization_section_workflow.py:451` 改为 `generate_attempt == max_attempts - 1`，而
`max_attempts = max(3, 3 + 1)` 恒为 4。R1 的修复顺带把「可恢复但不可降级」类的重试次数
从 3 提到 4，每次失败多一次昂贵模型运行，且常量名与实际行为不符（第 60 行仍写 `= 3`）。

修复建议：明确二者语义。要么该类仍用 `_MAX_GENERATE_ATTEMPTS` 封顶，要么删除该常量并
在注释中注明有效次数为 4。

**处理：已修复**——恢复 `generate_attempt == _MAX_GENERATE_ATTEMPTS - 1`。R1 加的
post-loop 兜底（`raise generation_failure or ReportingError(...)`）继续保留，即使某类
失败在循环内未命中显式 `raise`，也不会丢失根因，所以缩小这个分支的判断范围不会重新
引入 R1 修复前的问题。

### B7. 其余

- **rebase 只取单一身份。** `context_management.py:1094-1100` 使用
  `call.get("call_id") or call.get("id")` 而非两者并集。当前两条路径都能工作（Responses 有
  `call_id`，Chat Completions 回退到 `id`），但若某条结果按另一字段落键仍会整轮丢弃。
  改为并集成本相同且更稳。**处理：已修复。** 注意直接把两种身份拍平成一个集合再做
  `issubset` 判断仍然是错的：单个调用同时携带 `id` 和 `call_id` 时，结果只会用其中一个
  回填 `tool_call_id`，拍平后的集合有 2 个元素但只能匹配到 1 个，`issubset` 依然失败。
  正确做法是按调用分别收集身份集合，只要结果覆盖了某个调用的任一身份就算该调用完成，
  再要求所有调用都完成才算整轮完成（`context_management.py` 的 `call_identity_sets`）。
- **`_repair_diagnostic` 丢弃截断标记。** `visualization_section_workflow.py:143-146` 弃用
  `_truncated`，模型无法判断自己看到的是片段；而 `code_generation.py:331-337` 设置了
  `{field}Truncated`。两处不一致。**处理：已修复**，对齐 `code_generation.py` 的写法。
- **`_code_reserve_rejections` 永不复位。** 模型恢复有效进展后再次进入预留区，第一次拒绝
  即被判 `escalated` 并计费。建议在成功的交付类调用后归零。**处理：已修复**——
  `_ordered_code_calls` 在交付类调用成功执行后将该计数器归零。
- **`submission_diagnostic()` 不暴露 `pending_output_validation`。** `toolkit.py:640-656`
  仍只报 `hasExecutionReceipt: True`，冷启动修复 run 看不到真正的阻塞原因。**处理：已
  修复**——`submission_diagnostic()` 新增 `pendingOutputValidation` 字段；两条下游过滤
  路径（analysis 的 `_short_diagnostic`、visualization 的 `_repair_diagnostic`）都已让
  它优先于可能已被后续无关失败覆盖的 `lastFailure`。
- **探索额度耗尽仍计费。** `report_code_exploration_budget_exhausted` 不在
  `protocol.py:321-323` 的豁免集内。保留可能是刻意的（强制收敛），但与 C3 的升级机制
  存在语义重叠，建议统一。**处理：复审后确认不是缺陷。** 这是一次真实执行的工具调用
  （在 `run_snippet` 的 entrypoint 内部判定，不是协议层的预发拒绝），理应正常计费——
  否则模型可以无限重试探索而不消耗任何额度。与 C3 的「预算记账分散」是同一类架构问题
  （见 A2），但计费方向本身没有错，未改动行为。

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

## 原建议落地顺序（历史评审；当前状态见文首和文末）

| 优先级 | 项目 | 状态 |
| --- | --- | --- |
| P0 | B1 双通道 + 双流查找 | 已修复；轨迹测试原本使用的 fake 不含标记，恢复 `exit $report_exit` 后 `status` 重新权威，无需改动该 fake |
| P1 | B3 不毒化批次、B4 过滤工具名 | 均已修复 |
| — | B2 | 复审后判定为有意设计，未改动行为，仅补注释 |
| P2 | B5、B6、B7-1~4 | 均已修复 |
| — | B7 探索额度计费 | 复审后确认不是缺陷，未改动行为 |
| 架构 | A5 → A2 → A3 → A1 → A4 | 已实施；具体实现取舍与验证见本轮记录 |

## 已完成的回归测试

1. `test_reporting_code_agent_stability.py`：`test_run_script_tolerates_truncated_exit_marker_when_status_ok`
   （标记缺失但 status ok 视为成功）、
   `test_run_script_fails_closed_on_exit_marker_status_mismatch`
   （标记与 status 冲突视为失败，校验 `exitCode`）、
   `test_run_script_finds_exit_marker_in_stdout_when_streams_merged`
   （标记只出现在 stdout 时仍可查找到）。原有的
   `test_run_script_fails_closed_on_missing_or_nonzero_process_exit` 已替换——它原先
   断言的「标记缺失即失败」正是 B1 的回归行为。此外新增
   `test_visualization_recoverable_nondegradable_failure_capped_at_max_generate_attempts`
   （B6）、`test_short_diagnostic_prefers_pending_output_validation_over_stale_last_failure`
   与 `test_visualization_repair_diagnostic_prefers_pending_output_validation`（B7-4）。
2. `test_reporting_code_agent_batches.py`：更新
   `test_tool_results_include_budget_and_reserved_view_rejects_current_review` 的断言为新
   code `report_code_visual_review_redundant`/`skipped` 且不计费；新增
   `test_redundant_view_image_rejection_does_not_stop_batch` 验证同批次内紧随其后的
   `submit_script` 仍会执行；新增
   `test_successful_delivery_call_resets_reserve_rejection_escalation`（B7-3）。
3. `smart_reporting/tests/test_context_management.py`：新增
   `test_complete_rounds_accepts_result_keyed_by_item_id_instead_of_call_id`（B7-1，验证
   单个调用同时携带 `id`/`call_id` 但结果只匹配其中一个时仍判定为完成）、
   `test_complete_rounds_drops_round_missing_any_call_coverage`（确认多调用场景下真正
   缺失覆盖的轮次仍会被正确丢弃，不因放宽单调用判定而误判宽松）。

## 原待办的处理状态

- B4、B5、B7-2 已补充 `test_reporting_code_audit_edges.py` 定向用例。
- A1–A5 均已实施；本记录与代码、定向测试一同纳入本地修复提交。

## 本轮实跑记录

- `test_reporting_script_process.py`、`test_reporting_interactive_code_agent.py`、
  `test_reporting_code_agent_stability.py`、`test_reporting_code_agent_trajectories.py`：
  **128 passed**。覆盖真实 bash/Python 子进程、双流丢弃、非零退出、并发唯一回执、
  缺失/损坏/越界/超长回执、执行后异常清理，以及既有交互与修复轨迹。
- metrics 定向测试已通过；此前两项失败是 stub 保留旧的 21 次请求期望，现按
  当前 analysis 30 次工具预算改为 31 次请求（预留最终模型响应）。
- 上轮 batches、diagnostics、analysis 降级与 evidence 轨迹定向检查已有 40 项通过；
  本轮仅按 A5 影响范围扩大验证，未运行或重复全量测试。
- 未执行真实 provider 请求；shell 测试验证宿主执行契约，不能作为 provider 探针证据。

## 第二轮实施：A1–A4 与剩余测试边界

- **A2**：新增 `code_agent/budget.py`，集中模型请求、交付预留、拒绝升级/复位、
  控制回执豁免及预算快照规则。保留 Agno `Model._limit_charge_for` 作为实际工具计费
  权威，不另建与 Agno 重复的 `used/limit` 累加器；批次从 Agno 传入计数并按其结果
  推进。模型浅复制共享同一个任务预算，新任务配置创建新的预算对象。修复升级拒绝后
  同批次 skipped 回执预算仍显示旧值的问题。
- **A1**：runner 显式注入 `toolkit.has_current_visual_review`；协议层移除
  `source_toolkit` / `entrypoint.__self__` 反射。未注入时不执行冗余审查优化。
- **A3**：新增 `code_agent/failure_policy.py`，用不可变策略表统一两个 workflow 的
  恢复分类与 runner 的 thinking failure kind；保留按任务类型有意存在的分类差异。
- **A4**：`no_submission`、模型请求上限和 rate limit 抛出点显式声明
  `recovery: retry_then_degrade`；消费端统一读取策略，`retryable` 仅保留旧错误的兼容
  解释。选用 `fatal/retry/retry_then_degrade` 三种策略，以明确“先按既有预算修复，
  再降级”，而不是改变既有重试次数。已知任务取消、身份失效等终止态不能被错误详情
  中的恢复字段降级。其他旧抛出点继续由共享表及兼容规则解释，无需一次性迁移所有错误。
- **边界补充**：分析预留提示仅引用已声明交付工具；JSON 深嵌套解析异常也被保护；
  验证 JSON/repr 语法保留、16 KiB wire 附加上限（不同于 8 KiB 诊断字段上限）、
  各 stdout/stderr/traceback 的截断标记。

验证：第一批受影响的 batches/metrics/stability/diagnostics/workflows/trajectories
共 **93 passed**；第二批交互测试和新增策略/边界测试先得到 **87 passed、2 failed**，
两项失败为新测试误用 8 KiB wire 上限，修正到实际 16 KiB 边界后仅重跑这两项，
结果 **2 passed**；本轮共 182 项定向用例通过。`git diff --check` 通过。
未执行全量测试或真实 provider 探针。

## 收尾复核

- 预算附加的异常保护延伸至序列化与 UTF-8 编码阶段：含孤立 surrogate 的 JSON
  保持原始工具结果，不因附加预算失败而中断协议循环。
- `_repair_diagnostic` 和 `_short_diagnostic` 保留上游已设置的各输出流截断标记，
  即使本层接收到的文本已经足够短，也不会把片段误标为完整输出。
- 新增真实 Agno 3.0.9 CodeMode 内核验证：脚本 stdout/stderr 超过 128 字符上限，
  两个流确实被截断，结构化回执仍分别返回 0 / 7，cell 状态分别为 ok / error，
  每次回执均清理。此项为本地内核验证，不涉及模型 provider。
- 本轮定向测试 **16 passed**，包括上述边界和既有 thinking 分类兼容测试；
  修改涉及的 Python 文件通过 Ruff 检查及 `git diff --check`。没有重复全量测试。
