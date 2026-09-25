# 2026-09-26 AgentOS 形态验证与发布链路修复报告

## 结论

1. **成本效率分析 CLI 跑通过**：exit 0，5 章节 37 页 PDF（47m40s），PR#4 代码。
2. **Report Editor 已接入但仅服务形态生效**：终端 CLI 形态不接 `download_grants/artifact_persistence/editor_grants` 三件套，发布阶段静默跳过 grant 签发，所以 CLI 跑永远无编辑器 URL。
3. **发现并修复 P0**：AgentOS/MCP 形态正式发布 100% 被 `report_editor_scope_mismatch` 失败关闭（commit `450acdb`）。
4. 修复后 AgentOS 形态重跑已提交，结果待补（见文末"待办"）。

## 一、成本效率分析 CLI 跑（基线：PR#4 = b2939ba）

- 输入：`2025年成本效率分析`（无"一个章节"约束，planner 自动规划 **5 章节**）
- 耗时：**47m40s**（01:34:25 → 02:22:05），exit 0
- 产物：37 页 PDF + DOCX + 20 张 PNG/Plotly 图
- 质量警告 17 条（analysis 11 / publication 8），`review_required=2`
- 失败族闸门：代码生成 13 次，no_output_write=6、edit_invalid=9、exec_failed=9、rounds_exhausted=3、binding_autocorr=3——全部自愈，无 source_invalid

产物：`/tmp/smart-reporting-cli-verify/sessions/a385a32d…0adbb9c4/报表/智能分析/cli-report-579cdab3…/revision-2/`
（期间以静态 http 服务 :8123 提供 PDF 预览）

## 二、为什么 CLI 跑没有编辑器 URL（接入链调查）

编辑器本身完整挂载在 FastAPI app（`app.py` → `create_report_editor_router`，`/reports/v1/editor/...`，Milkdown，markdown 为唯一权威内容）。链接在发布阶段签发（`planning.py` 的 `issue_http_publication`），但**前置条件是三件套同时接线**（`download_grants` + `artifact_persistence` + `editor_grants`，缺一即整体跳过）：

| 形态 | 三件套 | 结果 |
|---|---|---|
| AgentOS 服务（`app.py`） | 全接线 | 跑完结果带 `published.editor.openUrl` |
| 终端 CLI（`reporting.cli` → `create_report_runtime(context, settings)`） | 全 None | 静默跳过，只有文件产物 |

此前 R1/R2 六域验证与本跑均用 CLI 形态，故无 URL。另外 CLI 形态的 workspace 只落盘 `report-revision-1.md`，revision-2 的最终 markdown 只在发布流程 transient 存在（服务形态会写入 `revision-{n}/` 目录）。

## 三、P0：AgentOS 形态发布会 100% 失败（已修复）

### 现象

服务形态提交 run（`POST /agents/smart-reporting/runs`，user_id=zhaoxiangjun）：
- 首次提交缺 `user_id` → workflow 作用域校验报 `report_workflow_context_missing`（user_id 空串触发"作用域不完整"）
- 补齐后 run 正常执行 ~53 分钟，5 章节全部生成，**发布步骤失败关闭**：

```
Step 发布门禁与正式发布 failed: report_editor_scope_mismatch: 报告编辑上下文与发布作用域不一致。
（planning.py:388 → Workflow execution failed，Agent Run End 03:27:53）
```

### 根因（两层叠加）

1. 生产环境的 **durable payload 从不固化 `report_workflow_scope`**（全库确认无任何代码把 scope 键写入 durable；现有测试用手搓的 `as_state()` 格式 stored scope，所以测试永远绿）。
2. **第一层**：`issue_http_publication` 重新解析作用域时**未传 `run_context.dependencies`**，resolver 的 fallback 链 `stored.callerThreadId → dependency.threadId → effective_session_id` 一路落空，最终用 workflow 内部会话 id（`report-session-*`）充当 caller thread。
3. **第二层**：`base.py` 传给安全比对的 `thread_id=scope["threadId"]` 实为 `as_state()` 里的 **workspace_key**（`reporting-run-<hash>`，IO 寻址语义），与 caller thread 根本不是同一语义，永不相等。

任一层都足以让 `scope.caller_thread_id != thread_id` 恒成立 → AgentOS/MCP 形态正式发布 100% 失败关闭。两层分别由真实 run 暴露：第一层修复后重跑（03:41 全量版撞上 planner coverage 硬门早夭、03:48 约束版走到发布）立即暴露第二层。

### 修复

**第一层（commit `450acdb`）**：`issue_http_publication` 新增 `dependencies` 参数，base.py 从 `run_context.dependencies` 透传，与 `_scope()` 同源；新增回归测试（durable 无 scope 键 + dependencies 恢复 caller thread → 签发成功；不传则仍失败关闭）。

**第二层（commit `e7c5ab1`）**：`issue_http_publication` 新增 `caller_thread_id` 参数，base.py 显式传 `scope["callerThreadId"]`；安全比对 `scope.caller_thread_id != caller_thread_id`；`thread_id` 仅用于工作区 IO。回归测试中 `thread_id` 与 `caller_thread_id` 取不同值，同时守住两层修复。

**验证**：31/31 定向测试 passed（`test_report_artifact_persistence.py` + `test_reporting_workflow_scope.py`）；ruff check 通过；mypy 改动行零新增（139 个均为 HEAD 存量）；ruff format 报出的 hunks 经 `git show HEAD` 核实全部为存量。

## 四、修复后重跑

| run | 任务 | 结果 |
|---|---|---|
| 全量版（03:41） | 2025年成本效率分析 | 10 分钟死于 `report_analysis_plan_invalid`（见观察项 4），未到发布 |
| 约束版 v1（03:48，修复第一层后） | 同上，一个章节两个分析 | 走到发布，死于第二层 scope_mismatch（4 分钟，验证价值所在） |
| 约束版 v2（03:5x，两层修复后） | 同上 | 进行中，结果待补 |

## 残余观察项

1. AgentOS run 不带 `user_id` 时报错信息有误导性（"作用域不完整"实际指身份缺失）——建议拆 `report_workflow_identity_missing`，低优先级
2. CLI 形态跳过 grant 签发无日志——建议加一条 loguru info，低优先级
3. 历史观察项不变：edit_invalid 偶发自愈、section revision 预算上限继续观察
4. **`report_analysis_plan_invalid`（已批准分析计划没有覆盖全部授权数据集，datasets.py:590）为语义完整性硬门**：planner 未引用某个授权数据集即杀整个 run。03:41 全量版因 planner 方差撞死（同主题 CLI 跑与约束版均通过），符合 AGENTS.md"语义业务校验只需要软告警"的降级候选——建议降级为 planner 反馈软告警，先积累样本再改

## 原始数据

- CLI 跑日志：`/tmp/cli-verify-cost-eff.log`
- 服务日志（两次 run + 失败现场）：会话任务 `bash-8froeeii`（旧服务）、`bash-mcauujw4`（修复后服务）输出
- 修复提交：`450acdb`；重跑结果：`/tmp/agentos-run-r3.json`（待完成）
