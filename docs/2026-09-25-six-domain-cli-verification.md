# 2026-09-25 六域真实 CLI 串行验证报告

## 结论

6 域真实 CLI 串行测试：**5/6 通过（83%）**，1 跑超时（topic5 异常波动诊断，撞 60 分钟上限）。
通过跑全部 exit 0 且产出 PDF（9–15 页）。总跨度 16:59:34 → 20:27:07（3h27m）。

## 测试设置

- 驱动：`/tmp/drive_cli_verify.py`（PTY 驱动，TIMEOUT_SECONDS=3600）；串行脚本 `/tmp/run_multi_topic.sh`
- 环境：`REPORTING_HOST_WORKSPACE_ROOT=/tmp/smart-reporting-cli-verify`，每跑独立 session 目录
- 验收口径：exit 0 + revision-2 PDF 产出 = 通过；超时记 timeout 单独归因；允许 degraded section
- 日志：`/tmp/cli-verify-topic-{1..6}.log`

### 代码版本混杂因素（重要）

PR#3（failure_policy 重试统一、章节 Step 失败关闭等，触及 `failure_policy.py/planning.py/sections.py/protocol.py/toolkit.py` 等 19 文件）于 **19:57:29** 合入本工作区：

- topic1–5（进程启动于 16:59–19:08）：跑 **pre-PR#3** 代码（`1591f18`）
- topic6（进程启动于 20:08:35）：跑 **post-PR#3** 代码（`17ae770`）
- topic5 进程虽跨合并时刻，但其 run_script 子进程只重读未被 PR#3 修改的 `sandbox/matplotlib_defaults.py`，版本一致

因此 **topic6 的"最干净"结果不能单独归因于 PR#3**（主题难度是混杂变量：topic3/4 同为低难度且也干净）。

## 结果总表

| # | 主题 | 开始→结束 | 耗时 | 结局 | PDF | 代码生成次数 |
|---|---|---|---|---|---|---|
| 1 | 门诊/住院服务量与均次费用 | 16:59:34→17:33:17 | 33m43s | ✅ exit 0 | 11 页 | 7 |
| 2 | 药品/卫生材料收入结构 | 17:33:31→18:23:40 | 50m09s | ✅ exit 0 | 11 页 | 10 |
| 3 | 临床科室绩效对比 | 18:23:54→18:42:53 | 18m59s | ✅ exit 0 | 9 页 | 6 |
| 4 | 各院区收入分布 | 18:43:07→19:08:18 | 25m11s | ✅ exit 0 | 9 页 | 5 |
| 5 | **异常波动诊断** | 19:08:32→20:08:01 | **59m29s** | ❌ **timeout** | 无 | 6（被杀时第 7 次在飞） |
| 6 | 门诊/住院结算结构 | 20:08:35→20:27:07 | 18m32s | ✅ exit 0 | 15 页 | 6 |

### 失败族闸门计数（按日志关键字统计）

| # | no_output_write | declared_output_missing | exec_failed 拒收 | edit_invalid | generic_data_helper | rounds_exhausted | binding_autocorr | source_path_invalid | section_degraded |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 11 | — | 8 | 3 | 3 | 0 | 0 | 0 |
| 2 | 16 | 28 | — | 15 | 5 | 3 | 1 | 0 | 0 |
| 3 | 0 | 0 | — | 3 | 0 | 3 | 4 | 0 | 0 |
| 4 | 0 | 0 | — | 13 | 0 | 0 | 7 | 0 | 0 |
| 5 | 7 | 34 | **36** | 2 | 6 | 3 | 2 | 2 | **0** |
| 6 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |

- `rounds_exhausted=3` 为视觉收敛闸门按设计降级（连续 3 轮软告警后放行），非失败。
- `source_invalid` 语法护栏 6 跑仅 topic5 触发 2 次，其余为 0。
- `exec_failed` 列：topic5 的 run_script 拒收码分布为 `report_code_mode_execution_failed=36`、`declared_output_missing=34`、`no_output_write=4`、`edit_not_found=4`、`generic_data_helper=4`、`source_path_invalid=2`、`edit_unchanged=2`、`edit_invalid=2`。

### Coding 成本聚合（该跑全部 coding 任务求和）

| # | modelRequests | inputTokens | cacheReadTokens | outputTokens | reasoningTokens | toolCalls |
|---|---|---|---|---|---|---|
| 1 | 83 | 4.45M | 3.01M | 198k | 122k | 83 |
| 2 | 105 | 5.27M | 3.23M | 365k | 239k | 103 |
| 3 | 41 | 1.13M | 0.46M | 89k | 47k | 41 |
| 4 | 60 | 2.69M | 1.83M | 152k | 104k | 61 |
| 5 | 122 | 9.31M | 6.99M | 428k | 296k | 123 |
| 6 | 31 | 1.43M | 0.63M | 85k | 50k | 31 |

模型全程 `deepseek-v4-flash-0731`（visualization coding effort=low）。通过跑中位耗时 25m11s（区间 18m32s–50m09s）。

### Session 与产物归档

| # | session | 产物 |
|---|---|---|
| 1 | `3bf26df4…bea1cf` | `cli-report-…/revision-2/…门诊与住院服务量…pdf`（11p） |
| 2 | `b564afff…36e6f9` | `…药品收入与卫生材料收入结构…pdf`（11p） |
| 3 | `641f545b…c04aa5` | `…各临床科室医疗收入绩效对比…pdf`（9p） |
| 4 | `d0dfbfc9…f167b` | `…各院区医疗收入分布…pdf`（9p, 2.5M）+ docx（348K） |
| 5 | `4d812715…55d9c` | **无 PDF**；残留 `analysis/charts/section_001/attempt-{1,2,3}` 共 **21 张 PNG**、`chart-inputs` 3 轮、`facts` 6 份 analysis |
| 6 | `6fd88379…e98ea` | `…门诊与住院收入结算结构…pdf`（15p, 3.1M）+ docx（392K） |

（session 根：`/tmp/smart-reporting-cli-verify/sessions/`）

## topic5 超时深度归因

**主题难度最高**：单章节内需可视化 6 份 analysis 的异常波动诊断，chart 密度远超其他主题。

**时间线**：

| 时刻 | 事件 |
|---|---|
| 19:08:32 | 启动 |
| 19:15:22 / 19:16:48 / 19:22:35 / 19:26:37 | coding 任务 4 次完成（chart attempt 1–2 及重试） |
| 19:29:37 / 19:47:18 | planner revision + binding 校验 + chart-inputs 重物化（attempt 2→3） |
| 20:00:20 | 第 6 次 coding 完成（该任务本身横跨 ~34 分钟） |
| 20:01:17 | 又一轮 planner/binding/chart-inputs 校验 |
| 20:07:50–20:08:01 | 第 7 次 coding 推进到 request 22/35，最后一个 run_script 仍因 declared 产物缺失被拒 |
| 20:08:01 | 60 分钟上限杀掉进程，零报告产出 |

**根因（双失败族叠加 + 无预算兜底）**：

1. 模型在诊断类数据上同时大量触发 `exec_failed`（36，多为 findings 结构断言 raise）与 `declared_output_missing`（34）——脚本写了防御性断言，违反即抛错，产物不落盘。
2. **section 级 revision 循环没有预算上限**：6 次 coding 完成 + 多轮 planner 重跑均未触发已存在的 degraded 零图兜底（全程 `section_degraded=0`），最难主题烧完整预算且零交付。这与"允许 degraded section"的验收口径相悖——兜底路径存在但从未被启用。
3. 单次 coding 任务最长拖到 ~34 分钟（请求上限 35 内反复自愈），进一步放大超时风险。

## 质量评估

- **可靠性 5/6（83%）**：失败集中在最难的诊断类主题，且失败模式为"超时零交付"而非"错误交付"——报告内容本身未被污染。
- **性能**：通过跑中位 25 分钟；topic3/4/6 近零失败族，收敛快；topic2（50m）与历史"零产物族自愈 13–20min"一致。
- **交付质量**：5 份 PDF 9–15 页，均含 docx 双产物；topic6 达 15 页。
- **成本**：通过跑 reasoning tokens 47k–239k；topic5 消耗 296k reasoning / 122 请求仍无产出，成本黑洞由超时兜底切断。

## 残余风险与下一步建议

1. **最高价值修复（结构性硬门，符合 AGENTS.md 原则）**：给 section 级 revision 循环加预算上限（如 coding 尝试 ≤4 次或 section 墙钟 ≤25 分钟），超限强制走已存在的 degraded 零图兜底交付。保证最难主题也能在时限内产出可读报告而非零交付。
2. 多 analysis 章节（≥4 份）考虑按 analysis 分批出图或提升章节预算，避免单章节密度过载。
3. 低优先级观察项：`edit_invalid` 仍为最高频偶发族（topic2=15、topic4=13，均自愈）；零产物族自愈时长与静态诊断回执效果继续积累样本；收敛闸门 limit=3 的质量权衡保持 metrics 可审计。

## 附：原始数据位置

- 每跑日志：`/tmp/cli-verify-topic-{1..6}.log`
- 驱动/脚本：`/tmp/drive_cli_verify.py`、`/tmp/run_multi_topic.sh`
- 产物：`/tmp/smart-reporting-cli-verify/sessions/<session>/报表/智能分析/cli-report-<id>/revision-2/`
