# Reporting Coding Agent 收敛性与稳健性审查

## 范围与方法

审查对象：

- `smart_reporting/reporting/code_agent/`（`toolkit.py`、`protocol.py`、`context.py`、`lsp.py`、`lsp_process.py`）
- `smart_reporting/reporting/code_mode.py`
- `smart_reporting/reporting/workflow/runtime/code_generation.py`
- `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- `smart_reporting/context_management.py`（投影与 rebase 路径）

方法：静态代码走查 + 调用链追踪。本次审查**不覆盖沙箱隔离与执行面权限**（已确认暂不纳入范围），只关注 Coding Agent 工具循环的收敛性、错误分类保真度和稳健性。

未执行测试：审查环境无 `.venv`、`agno` 未安装，标注「需实测」的条目为基于代码路径的推断，其余均可从源码直接确认。

## 结论摘要

| 编号 | 问题 | 类别 | 严重度 |
| --- | --- | --- | --- |
| C1 | `write_script` 清空视觉审查回执，N 图章节每次改源码都要重审全部图 | 收敛 | P0 |
| C2 | `view_image` 未计入交付额度预留，可视化任务必然无法提交 | 收敛 | P0 |
| C3 | 预留区拒绝不计费，额度不再单调推进，只能靠 model-request 耗尽收场 | 收敛 | P0 |
| C4 | `no_submission` / `model_request_limit` 既不重试也不降级 | 收敛 | P0 |
| C5 | `outputValidation` 为咨询性，`submit_script` 不校验，白跑一次冷启动修复 | 收敛 | P1 |
| C6 | 跨 run 修复诊断丢失全部执行现场（键名与结构不匹配） | 收敛 | P1 |
| R1 | 生成循环第 4 次失败抛裸 `RuntimeError`，根因丢失 | 稳健 | P1 |
| R2 | 工具内终止态无法上抛（`tool_hooks` 未安装） | 稳健 | P1 |
| R3 | `ReportingCodingTaskRegistry` 每次 attempt 新建，互斥形同虚设 | 稳健 | P1 |
| R4 | 脚本子进程退出码未显式校验，存在 fail-open 风险 | 稳健 | P1 |
| R5 | 上下文 rebase 按 `id` 配对、工具结果按 `call_id`，工具历史可能整段丢弃 | 稳健 | P1（需实测） |
| R6 | 探索额度计费、预算不可见、诊断预算分配、LSP 竞态等 | 稳健 | P2 |

C1 + C2 + C3 构成一条完整的「预算被白白烧光 → `no_submission`」链路，叠加 C4 后升级为整份报告硬失败。这是本次审查的主结论。

---

## 收敛性缺陷

### C1. `write_script` 清空视觉审查回执

`context.py:84-86`：

```python
def clear_execution_state(self) -> None:
    self.execution_receipt = None
    self.visual_inspection_receipts.clear()      # ← 问题在这
```

`toolkit.py:1007-1057` 的 `run_script` 已实现**完全正确**的按 sha 保留逻辑：

```python
previous_visual_reviews = dict(self.binding.visual_inspection_receipts)   # 1009
self.binding.clear_execution_state()                                      # 1010
...
self.binding.visual_inspection_receipts.update({                          # 1044
    path: review for path, review in previous_visual_reviews.items()
    if (output := output_by_path.get(path)) is not None
       and review.sha256 == output.sha256 and review.reviewed ...
})
```

但 `toolkit.py:740` 的 `write_script` 已先调用 `clear_execution_state()`。正常流程只能是 `write_script → run_script`，因此第 1009 行快照到的永远是空字典——这段保留逻辑在真实路径上是死代码，只在「不改源码连续 `run_script` 两次」时才生效，而那种情况本身没有意义。

后果：8 图章节中模型只改第 3 张图的配色，重跑后第 1、2、4–8 张图字节完全相同，却全部需要重新 `view_image`。每次源码微调固定消耗 `1(write) + 1(run) + 8(view) = 10` 次工具调用。这是预算被烧光的主因。

修复（正确逻辑已存在，只需停止提前清空）：

```python
# context.py
def clear_execution_receipt(self) -> None:
    """源码变更只失效执行回执；视觉回执由 run_script 按 sha 重新过滤。"""
    self.execution_receipt = None

def clear_execution_state(self) -> None:
    self.clear_execution_receipt()
    self.visual_inspection_receipts.clear()
```

`write_script`（`toolkit.py:740`）与 `restart_code_mode`（`toolkit.py:789`）改调 `clear_execution_receipt()`；`run_script`（`toolkit.py:1010`）保持 `clear_execution_state()` 不变。

安全性不受影响：`submit_script` 仍逐个比对 `reviewed.sha256 != output.sha256`（`toolkit.py:1120-1124`），且 `execution_receipt` 被清空后无法提交。

### C2. `view_image` 未计入交付额度预留

`protocol.py:65-66`：

```python
_DELIVERY_TOOL_NAMES = frozenset({"write_script", "run_script", "submit_script"})
_DELIVERY_TOOL_RESERVE = len(_DELIVERY_TOOL_NAMES)   # 3
```

`protocol.py:588-619` 在 `current_count >= function_call_limit - 3` 之后拒绝一切非交付工具并置 `stopped = True`。

但 `toolkit.py:1105-1134` 要求 `submit_script` 前每一个 declared output 都有通过的视觉审查，而 `view_image` 不在 `_DELIVERY_TOOL_NAMES` 内。可视化交付序列是 `write → run → view_image × N → submit`，需要 `3 + N` 次调用，预留却固定为 3。

触发链：额度进入预留区 → `view_image` 被 `report_code_delivery_budget_reserved` 拒绝 → 模型只能调 write/run/submit → `submit_script` 永远返回 `report_code_visual_review_required` → 死锁 → `report_code_generation_no_submission`。

修复：预留量按声明输出数动态计算，并把 `view_image` 纳入交付集。

```python
# protocol.py
_DELIVERY_TOOL_NAMES = frozenset({"write_script", "run_script", "submit_script", "view_image"})

def configure_code_run(self, tools, *, max_model_requests, delivery_reserve=None):
    ...
    self._code_delivery_reserve = (
        delivery_reserve if delivery_reserve is not None else len(_DELIVERY_TOOL_NAMES)
    )
```

`_ordered_code_calls` 用 `self._code_delivery_reserve` 替换常量；`code_generation.py:177-181` 传 `3 + len(task_context.declared_output_paths)`，analysis 传 3。

补充建议：`view_image` 处于预留区时只拒绝已通过审查路径的重复调用，未审查路径始终放行，避免被自身重试卡死。

### C3. 预留区拒绝不计费，额度不再单调推进

`protocol.py:320-327` 把 `report_code_delivery_budget_reserved` 与 `report_code_batch_stopped` 从额度计费中豁免。豁免意图正确（未执行不应计费），但副作用是额度停止推进：

模型在 17/20 时调 `run_snippet` → 拒绝、不计费 → `current_count` 仍为 17 → 再调 → 再拒绝。唯一兜底是 `protocol.py:339-348` 的 `_consume_code_request`，直到撞上 `report_code_model_request_limit`（`retryable: False`）。

且这类拒绝**不经过 toolkit 的 post_hook**（工具从未执行），因此 `toolkit.py:621-633` 的 `_repeated_failure_count` / `repairHint` 重复失败检测完全看不到它——本该纠偏的机制在此失效。

修复：在 protocol 层为拒绝加计数与升级，第二次起附带终止性指引并正常计费，保证额度单调收敛。

```python
# _ordered_code_calls 命中预留区时
self._code_reserve_rejections = getattr(self, "_code_reserve_rejections", 0) + 1
if self._code_reserve_rejections >= 2:
    payload["message"] = (
        "剩余额度仅供交付；请立即调用 write_script/run_script/submit_script，"
        "不要再调用探索工具。"
    )
    payload["details"]["escalated"] = True
```

并把 `escalated=True` 的拒绝移出 `_is_non_executed_control_result` 豁免。

### C4. `no_submission` 与 `model_request_limit` 既不重试也不降级

`code_generation.py:210-225` 抛出 `report_code_generation_no_submission` 时带 `details={"retryable": False}`；`report_code_model_request_limit`（`protocol.py:344-347`）同样。

两个 workflow 的判定都是「`retryable is False` ⇒ 不可恢复 ⇒ 直接 raise」：

- `visualization_section_workflow.py:220-227`
- `analysis_item_workflow.py:796-800` —— 该 `raise` 位于 `exhausted → _abandon_supplement()` **之前**，因此 analysis 已实现的优雅放弃路径对最常见的失败模式不可达。

`retryable=False` 的本意是「不再花钱重试没收敛的模型」（对应 commit `aa78636`），却被复用为「连降级都不允许」。工具额度耗尽是最常见的收敛失败，结果导致整份报告致命失败。

修复：拆开「不重试」与「不降级」两个判断。

```python
def _is_nonrecoverable(error: Exception) -> bool:
    if not isinstance(error, ReportingError):
        return False
    if error.code in _NON_RECOVERABLE_CODES:
        return True
    details = error.details if isinstance(error.details, Mapping) else {}
    return details.get("retryable") is False and not _is_degradable(error)
```

`_DEGRADABLE_CODES` 增加 `report_code_generation_no_submission`、`report_code_model_request_limit`、`report_code_generation_rate_limited`；analysis 侧把 `retryable is False` 分支改为先判 `exhausted` 再走 `_abandon_supplement()`。

按 `AGENTS.md`「语义业务校验只需要软告警」，零图降级加 `report_visualization_degraded` 告警才是此处应有的落地方式。

### C5. `outputValidation` 为咨询性，`submit_script` 不校验

`toolkit.py:1058-1070`：

```python
result = {"ok": True, "executionReceipt": ...}          # ← 顶层 ok 恒为 True
if self.output_preflight is not None:
    diagnostic = await self.output_preflight(receipt)
    ...
    if diagnostic is not None:
        result["outputValidation"] = _failure(...)       # 仅嵌套告知
```

`toolkit.py:1072-1139` 的 `submit_script` 只校验回执身份、输出身份和视觉审查，从不查 `outputValidation`。且顶层 `ok: True` 使 `protocol.py:629-632` 不会置 `stopped`，因此模型若把 `[run_script, submit_script]` 批在同一响应内，schema 不合规的 evidence 会直接提交成功。

结果：本可在同一 run 内（模型仍持有完整上下文）修好的 schema 问题，被推迟到 workflow 的 `_validate_evidence`，触发一次冷启动修复 run（`add_history_to_context=False`，只带一行诊断）。这是本系统最昂贵的操作。

修复：让 preflight 在 run 内具备阻断力。

```python
# toolkit.py __init__
self.pending_output_validation: dict[str, Any] | None = None

# run_script 成功分支
if diagnostic is not None:
    self.pending_output_validation = _failure(...)
    result["outputValidation"] = self.pending_output_validation
    result["ok"] = False            # 让批次在此停止，模型必须先修
else:
    self.pending_output_validation = None

# submit_script 开头
if self.pending_output_validation is not None:
    return _failure(
        "report_code_output_validation_pending",
        "最近一次执行的输出结构校验未通过；请修复并重新执行后再提交。",
        self.pending_output_validation.get("details"),
    )
```

### C6. 跨 run 修复诊断丢失全部执行现场

两处键名与结构不匹配，导致信息量最高的对象被算出后丢弃：

1. toolkit 经 `_safe_diagnostic_details` 产出 `traceback` / `stderr` / `stdout`（`toolkit.py:326-333`），而 `code_generation.py:268-309` 的 `_short_diagnostic` 与 `visualization_section_workflow.py:88-139` 的 `_repair_diagnostic` 白名单只认 `output`。三个字段全部被过滤掉。
2. `submission_diagnostic()` 构造的 `lastFailure`（含 tool / code / message / details，`toolkit.py:640-656`）是嵌套 dict，既不在 `_short_diagnostic` 白名单内，也不匹配 `_repair_diagnostic` 读取 `error.details["details"]` 的取法（它位于 `lastFailure` 键下）。整体丢弃。

`analysis_item_workflow.py:1111-1120` 的 `_repair_error` 虽原样透传 `error.details`，仍会在 `_short_diagnostic` 处被过滤。

于是每次冷启动修复 run 收到的 `diagnostic` 实际只有 `{code, message, details: {path}}`。模型在没有任何报错现场的情况下重写脚本——这解释了 `repairUnchanged` 检测（`visualization_section_workflow.py:508-518`）为何需要存在。

修复：在两个白名单中加入 `traceback` / `stderr` / `stdout`（各自限长，合计不超过 4 KiB），并把 `lastFailure.code` / `lastFailure.message` / `lastFailure.details` 扁平化后透传。

---

## 稳健性缺陷

### R1. 生成循环第 4 次失败抛裸 `RuntimeError`

`visualization_section_workflow.py:361-431`：`max_attempts = max(_MAX_GENERATE_ATTEMPTS, MAX_VISUALIZATION_EXECUTION_REPAIRS + 1) = 4`，但非降级分支的终止条件写成 `generate_attempt == _MAX_GENERATE_ATTEMPTS - 1`（即 `== 2`）。

当 attempt 0–2 为可降级失败（`continue`）、attempt 3 为「可恢复但不可降级」失败（例如 `report_code_generation_rate_limited`、`report_code_mode_execution_failed`）时，两个 raise 分支均不命中，循环自然结束并抛出 `RuntimeError("可视化脚本生成状态不可达")`，原始异常与诊断全部丢失，上层无法分类也无法降级。

修复：

```python
        if generate_attempt == max_attempts - 1:
            raise
...
if script_file is None or generated_result is None:
    raise generation_failure or ReportingError(
        "report_visualization_section_failed", "可视化脚本生成未产出回执。"
    )
```

### R2. 工具内终止态无法上抛

`toolkit.py:1141-1154` 的 `require_current_receipt` 抛出 `report_phase_artifact_changed`（属 `_NON_RECOVERABLE_CODES`，语义为立即中止整个 task），但它从 `run_script` 的工具入口抛出。`agent.py:274-278` 的注释已记录该约束：「Agno `Function.aexecute` 会把普通异常转换成失败工具消息。只抛出并不足以触发 Agent retry」。

仓库为此准备了 `propagate_reporting_tool_errors` 与 `_record_reporting_tool_run_error`，但 `agent.py:2920-2944` 的 `create_reporting_code_agent_factory` 未安装任何 `tool_hooks`。模型层已有 `_MODEL_RUN_ERROR` / `report_run_error()` 上抛通道，工具层没有对应机制。

修复：与模型层对称，在 toolkit 上记录终止态并由 runner 检查。

```python
# toolkit.py
self.terminal_failure: ReportingError | None = None
# require_current_receipt 与 run_script 的 artifact-changed 分支记录后再抛

# code_generation.py，紧随 report_run_error() 检查之后
if toolkit.terminal_failure is not None:
    raise toolkit.terminal_failure
```

### R3. `ReportingCodingTaskRegistry` 互斥形同虚设

`code_generation.py:103` 为 `self.registry = registry or ReportingCodingTaskRegistry()`，而全仓库无任何调用方传入 `registry`。可视化路径 `analysis.py:746-767` 更把 `code_runner()` 写成工厂函数，每次 attempt 都新建 runner 与 registry。

`context.py:89-118` 声明的不变量是「同一 task 或正式脚本同时只能存在一个活动绑定」，属进程级语义，因此 `report_coding_task_conflict` 实际永不触发，同一 `script_path` 的并发绑定无保护。

修复：与 `code_mode_runtime`、`lsp_manager` 一致，在 `bootstrap.py` 建进程级 registry，经 `ReportWorkflowRuntime` 注入并传入 `ReportingCodeGenerationRunner`；`code_runner()` 改为缓存单实例。

### R4. 脚本子进程退出码未显式校验

`toolkit.py:1021-1022` 只检查 `_cell_field(cell, "status") != "ok"`，从不读退出码。`run_script` 的失败判定完全依赖 IPython `%%bash` 的 `raise_error` 默认为 True（非零退出抛 `CalledProcessError`）。

对比 `phase.py:177-181`：旧执行路径是显式检查 `exitCode` 的，属同仓库内不一致。

风险：若该默认值不成立或被上游改变，一个「先 `savefig` 成功、后抛异常」的脚本会被判为成功并签发回执，静默交付半成品。

修复：在 cell 内回写退出码哨兵并强校验，`status == "ok"` 但缺哨兵同样判失败（fail closed）。

```python
# code_mode.py
def _script_process_cell(script_path: str) -> str:
    command = " ".join((shlex.quote(sys.executable), shlex.quote(script_path)))
    return f"%%bash\nset -o pipefail\n{command}\necho \"__REPORT_EXIT__=$?\" >&2\n"
```

### R5. 上下文 rebase 按 `id` 配对，工具结果按 `call_id`（需实测）

`context_management.py:1094-1106` 的 `_complete_rounds` 用 assistant `tool_calls[*]["id"]` 与 `message.tool_call_id` 配对，只保留 `call_ids.issubset(result_ids)` 的轮次。

Responses 协议下 `id`（item id）与 `call_id` 是两个不同值：`protocol.py:257-270` 刻意同时保留二者，`protocol.py:552` 把 `extra["tool_call_ids"]` 设为 `call_id`，`protocol.py:801-802` 对两种 key 都做了兜底查找。现有 `smart_reporting/tests/test_context_management.py` 全部按 `id == tool_call_id` 构造，仅覆盖 Chat Completions 形态。

若工具结果确实以 `call_id` 落在 `Message.tool_call_id`，则一旦上下文超过 rebase 阈值，Coding Agent 的全部工具轮次都会被判为不完整并整段丢弃，模型只剩 system、首末 user 与 checkpoint。

修复对两种形态均正确：

```python
            call_ids = {
                identity
                for call in assistant.tool_calls
                if isinstance(call, dict)
                for key in ("id", "call_id")
                if isinstance(identity := call.get(key), str)
            }
```

需补一条按 Responses 形态（`id != call_id`）构造的投影回归测试确认。

### R6. 其他

- **探索额度耗尽会计费**：`report_code_exploration_budget_exhausted`（`toolkit.py:752-760`）不在 `_is_non_executed_control_result` 豁免名单内，模型反复试探会直接烧掉全局额度。建议纳入豁免，或与 C3 一并做升级式提示。
- **预算对模型不可见**：除拒绝消息外，没有任何工具结果携带 `{used, limit, remaining}`。建议在每个工具结果中加入 `budget` 字段，这是成本最低、收益最高的收敛改进。
- **诊断预算分配失衡**：`toolkit.py:371-394` 的 `add_tail` 按 `traceback → result → stderr → stdout` 顺序贪心二分，第一个字段会吃满 `MAX_DIAGNOSTIC_BYTES`（8 KiB）。深栈失败时 `stderr`（真正的根因）归零。建议各字段先给下限（`stderr` 优先 3 KiB），再分配余量。取尾部的策略正确，应保留。
- **`finally` 掩盖原始异常**：`code_generation.py:230-231` 若 `ashutdown` 抛异常会覆盖原始 `ReportingError`，建议包 `try/except` 只记日志。
- **LSP 文档版本竞态**：`lsp_process.py:70-90` 的版本分配与 `didOpen` / `didChange` 发送之间无锁，同一 uri 首次并发时可能先发 `didChange`，pylsp 未 open 该文档导致超时并退化为 `report_lsp_unavailable`。建议将「版本分配 + open/change 发送」整体纳入 `state.write_lock`，并以 `uri in state.document_versions` 而非 `version == 1` 判断是否需要 `didOpen`。
- **LSP 读循环异常兜底不全**：`lsp_process.py:245` 只捕获 `(ValueError, json.JSONDecodeError)`，未覆盖 `KeyError`（缺 `content-length`）与 `asyncio.IncompleteReadError`（继承 `EOFError`），reader task 会以未取回异常结束。建议扩为 `(ValueError, KeyError, EOFError, json.JSONDecodeError)`。
- **`synchronize_document` 依赖逐版本 diagnostics**：`lsp_process.py:100-102` 要求 pylsp 为每个 version 都发布 diagnostics，而 pylsp 存在去抖与合并行为，可能只对最新版本发布，导致 hover / definition / references 偶发超时。建议 `synchronize_document` 不等待 diagnostics，仅 `lsp_diagnostics` 工具自身等待。
- **`ANALYSIS_TOOL_CALL_LIMIT = 20` 偏紧**：探索额度 4 次，加 LSP 调用与每轮修复的 write/run（交付类豁免预留门槛但仍计入总额度），两次失败重试即接近耗尽。建议提升至 28–32，或将预留门槛改为「剩余额度 < 交付所需」的动态判断。
- **空 `evidencePath` 错误分类不佳**：`analysis.py:2320-2332` 的 `evidence_path = str(task_facts.get("evidencePath") or "")` 为空串时，会在 `ReportingCodingTaskContext.__post_init__` 由 `normalize_path` 抛出非 `ReportingError`。建议前置校验并抛 `report_phase_contract_invalid`。
- **`max_kernels` 取 max 而非 sum**：`runtime/execution.py:85-88` 使用 `max(analysis_concurrency, section_concurrency)`。若 analysis 与 section 阶段存在重叠，应为两者之和，否则活动 kernel 可能被驱逐并丢失会话状态。

---

## 建议落地顺序

| 批次 | 内容 | 预估 | 收益 |
| --- | --- | --- | --- |
| 1 | C1 + C2 + C4 | ~0.5 天 | 消除「可视化章节必然硬失败」 |
| 2 | C5 + C6 | ~0.5 天 | 省掉最昂贵的冷启动修复循环 |
| 3 | R1 + R2 + R3 + R4 | ~1 天 | 错误分类保真、终止态可上抛、fail closed |
| 4 | C3 + R5 + R6 | ~1 天 | 先补 Responses 形态投影测试以确认 R5 |

C1 是单点收益最高的改动：一行行为变更，且正确的 sha 过滤逻辑已在 `run_script` 中写好。

## 回归测试建议

按 `AGENTS.md`「禁止重复完整测试」，只补定向用例：

1. 含 `view_image` 的交付额度预留：`3 + N` 次交付调用在预留区内不被拒绝。
2. `write_script` 后同 sha 图表免重审：改源码重跑，字节未变的图表保留视觉回执。
3. preflight 未通过时 `submit_script` 被拒：`outputValidation` 失败后提交返回 `report_code_output_validation_pending`。
4. 生成循环末次失败的根因保真：attempt 0–2 可降级、attempt 3 不可降级时抛出原始 `ReportingError` 而非 `RuntimeError`。
5. Responses 形态（`id != call_id`）上下文投影：rebase 后工具轮次不被整段丢弃。
