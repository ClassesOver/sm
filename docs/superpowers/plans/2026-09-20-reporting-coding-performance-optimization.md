# 报表 Coding 性能与一次成功率优化实施计划

> **执行说明：** 由主 agent 使用 `superpowers:executing-plans` 按任务逐项实施并负责最终判断、冲突检查和计划更新；边界清晰、互不修改同一文件或共享运行状态的只读调查、测试审计和独立实现可交给同模型子 agent 同时进行。存在数据依赖、共享 provider 配额、同一冻结样本或同一文件写入的任务继续串行。以“本轮重新规划”的 R1–R7 为性能主线；下文 C1–C4 是与其共用指标和回放的 CodeMode 优化任务，按依赖和收益推进。原任务 1–10 保留为历史实现与验收记录，不按旧优先级重复实施。步骤使用复选框（`- [ ]`）跟踪。

**唯一核心目标：** 减少分析与可视化 Coding 的 reasoning 时间及长尾，并降低包含上游规划在内的任务总耗时；保留首轮 reasoning、首次成功率、精准局部 patch 和报表质量。章节任务范围、输入压缩、计划字段、缓存和 effort 都只是实现手段，不以输入更短、首个工具更早返回或架构重构本身作为成功标准。

**最新执行约束（2026-09-22）：** 用户明确仅使用 `reasoning.effort=high`，后续不开展 medium/low/off 对照。已确认误启动的 medium 回放进程退出，未产生结果文件，不计入性能样本。优化集中在 high 下的任务输入与重复推理。

**输入精简实验结论：** 曾尝试首轮省略 `outputContract.example`，保留 schema、rules、全部业务事实与任务 actions。high 回放 `/tmp/reporting-analysis-high-noexample-20260922.json` 首轮仍为 `577.237s / 42,445 reasoning tokens`，总 Coding `587.808s / 42,715 reasoning tokens`，虽一次通过但相较目标没有性能收益；示例仅减少约 278 字节，不能解决长推理。因此已撤销该改动，避免削弱输出契约的示例参照。后续不再做类似表面删提示实验，转向动态 `codingRequirements` 是否能减少模型自行规划的单变量评估。

**动态要求 high 对照已完成：** 同一 `/tmp/reporting-r7-analysis-v2`、模型、`high`、summary=auto、enable_thinking=true、parallel_tool_calls=true 下，仅将 evidence planner 输出的动态 `codingRequirements` 投影给 Coding，结果 `/tmp/reporting-analysis-high-candidate-20260922.json`：首轮 `207.725s / 16,395 reasoning tokens`，总 Coding `214.629s / 16,430 reasoning tokens`，`write_script → run_script → submit_script` 一次通过，`rawProtocolCorrect=true`。相对历史 legacy 样本 `577.237s / 42,445` 有明显性能信号，但两者不是严格同版本配对，不将 64.0%/61.4% 作为发布承诺；结论限定为“动态要求显著降低本次 high 样本的首轮推理”。

**生产切换：** evidence planner 默认 schema 改为 `AnalysisEvidenceDecision`，默认指令要求签发 `codingRequirements`；无显式 benchmark projection 时，分析 Coding facts 默认投影动态要求，且脚本 Agent 使用对应的 `codingRequirements` 指令。显式 `BenchmarkVariant.LEGACY` 仍保留给历史回放。动态要求只引用当前授权 dataset、字段、计算说明和输出名，主题、维度与指标仍由当前任务 planner 决定，不固化收入算法。受影响契约测试通过；较大 planner 测试文件仍有既有 `SimpleNamespace` 缺少 `session_state` 的替身阻断，未修改生产代码迁就。

**candidate 质量复核：** warning 指令后的 `/tmp/reporting-analysis-high-candidate-warning-20260922.json` 工作区 `/tmp/reporting-visualization-replay-k0lwm62h` 的两份 CSV 与冻结数据一致；按原始 CSV 独立聚合动态维度和总体结果，核对 `754` 个数值、覆盖集合和 null，全部一致；10 个 reconciliation 全部为 true；日间治疗中心、脑病中心、财务处三类单侧缺失均出现在 warnings。该样本首轮 `231.939s / 19,399 reasoning tokens`，总 Coding `238.797s / 19,417`，仍一次成功；相对 candidate 基线有 provider 波动，但仍保留明显低于 legacy 的信号，不把单次差异当作新收益。

**架构：** 按章节确定 Coding 任务范围，分析与可视化仍是分开的阶段；保留分析项的事实、证据和验收身份。沿用现有每个 Coding task 绑定一份正式脚本的宿主契约，不开展多脚本规划或改造。保留 Agno 负责模型请求、消息回放和工具协议映射；Reporting 宿主负责脚本身份、SHA、patch 原子应用、工具调用校验和交付状态。provider 可以一次返回多个结构化工具调用，宿主先整体校验，再按 provider 返回顺序执行。

**收尾校正：** warning 样本实际有 9 项 reconciliation（上文 10 项为旧样本数），均为 true；独立复算为 754 个数值/null 检查，类别覆盖另行核对。其 planner 耗时 `69.414s`、reasoning `5,573`，加 Coding 后总回放 `308.259s`、累计 reasoning `24,990`，不能仅以 Coding 的 `238.797s / 19,417` 宣称整个流程已达到 300 秒/20k 目标。两次 candidate 回放重新运行了 planner，facts 指纹不同；warning 提示效果也不是严格单变量证据。保留性能改善信号，跨主题稳定性和同版本配对仍待验证。

**可视化 critical-only high 验证：** 已修复 `_visual_review_model_receipt()` 的可选建议泄漏：未关联 critical issue 的 `suggestions` 保留完整审计回执，不再发送给 Coding 模型。定向交付测试 `30 passed`。使用 `/tmp/reporting-visualization-v2-Pfuhj1/repair/payload.json` 和 manifest 自动加载 seed，在 `high/summary=auto/enable_thinking=true/parallel_tool_calls=true` 下真实回放 `/tmp/reporting-visual-high-critical-only-20260922.json`：6 张图批量审查后一次 `read_script → edit_script`，再运行并提交；`firstPatchApplied=true`、`firstRepairSuccess=true`、`criticalVisualDefect=false`，Coding `191.400s / 9,830 reasoning tokens`，8 次 `view_image` 审查耗时 `34.621s`。最大请求为 edit 轮 `9,166 reasoning tokens`，说明视觉阶段剩余主要瓶颈是局部修复推理；本样本无同版本未修复回执的严格 A/B，不能宣称固定降幅。

**严格 Coding-only 对照能力：** 回放脚本新增 `--freeze-coding`，可在一次真实 candidate planner 后固化实际 Coding payload、授权输入身份、benchmark manifest SHA、variant 和指令 SHA；后续用 `--coding-only-payload` 跳过 planner，仅重复 Coding。candidate 与 legacy 均保留严格的基础 payload、输入路径/大小/SHA、脚本身份校验；candidate 必须携带动态 `codingRequirements`，不得回退到 `evidenceDecision`。结果额外记录 `codingPayloadSha256` 和 `instructionsSha256`，用于证明同一输入对照。定向回放测试 `55 passed`，Ruff 与 `git diff --check` 通过。该能力只解决后续同输入配对测量，不把历史不同输入样本追认成严格 A/B，也不证明 planner 输出来源的密码学真实性。

**视觉提示去重单图探针：** 在同一图片 SHA、同一视觉模型 `qwen3.6-flash` 下，仅比较完整 user 规则与短 user 指令；baseline `1263` 字节、`3414` input tokens、`4.826s`，candidate `69` 字节、`3165` input tokens、`2.783s`。两次均 `reasoning_tokens=0`、无 critical 缺陷，但返回的 warning 文本不同，因此只记录为输入/耗时改善信号，不宣称视觉质量等价或稳定收益；后续仍以逐图质量和总流程指标验收。视觉提示回归测试已锁定短 user 指令。

**缺失产物失败回执修正：** `report_code_declared_output_missing` 现在明确说明“声明产物不存在，不代表脚本不存在”，并指示根据 `details.path` 使用 `edit_script` 局部修复后再 `run_script`，禁止调用 `write_script` 整段重写。未声明工具调用仍由协议层 fail-closed 拒绝；该修正减少工具语义歧义，不宣称能保证模型不再返回错误工具。

**技术栈：** Python、Agno、Responses API、free-form custom tool、Lark grammar、loguru、pytest、Ruff。

## B0：当前生产基线（2026-09-22）

**并行收尾：** 已修复 planner 测试替身与现有执行器接口不一致：运行上下文补 `session_state`，成功结果补 `model_request_count`；原先失败的 5 项定向测试全部通过，未修改生产逻辑。历史阻断记录保留为当时状态，不能再把这 5 项列为当前未解决失败。

**2026-09-22 主题无关性修正：** 通用分析指令不再强制所有同比按月份聚合；期间对齐遵循当前任务的时间粒度和比较窗口。legacy 指令仅在月度同比时要求按月份对齐，保留跨年 YYYYMM 不直接求交集、单侧缺失使用 null 和软告警的约束，并将收入特定措辞“金额”改为“指标”。未新增任务 schema 字段，未改变首轮 reasoning、工具协议或精准 patch 校验。相关指令定向测试 `3 passed`，目标文件 Ruff 通过；本轮没有重复真实模型回放，不能据此认定 reasoning 长尾改善。

本节是后续优化的唯一对照基线。除非明确标记为新的单变量实验，不得把不同模型、不同数据快照、不同章节输入或删失样本混入 B0。

**冻结任务：** `2025年收入趋势分析，一个章节`；固定数据快照、章节输入、图片验收条件和宿主环境。

**冻结请求配置：** `deepseek-v4-flash-0731`、`reasoning.effort=high`、`reasoning.summary=auto`、`enable_thinking=true`、`parallel_tool_calls=true`、`tool_choice=auto`、`max_output_tokens=65536`。首轮 reasoning 保留；不使用 `thinking_budget`。

**最近完整真实样本：**

| 指标 | B0 值 |
| --- | ---: |
| 总耗时 | 456.167 秒 |
| Coding/Planner 请求数 | 14 |
| 累计 reasoning tokens | 34,747 |
| `read_script` | 4 |
| `edit_script` | 3 |
| `run_script` | 4 |
| `view_image` | 9 |
| `write_script` | 0 |
| 首次 patch 应用 | 成功 |
| 首次运行 | 失败 |
| 最终运行 | 成功 |
| 最终 critical 视觉缺陷 | 0 |

该样本证明精准局部 patch 可用，但不证明首次修复成功；删失、超时、usage 缺失样本不得填零或纳入 P50/P95。

**每次 baseline/candidate 必须采集：** `workflow_duration_ms`、分阶段 `model_request_count`、`reasoning_tokens`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`visual_review_duration_ms`、工具计数、`first_patch_applied`、`first_run_success`、`first_repair_success`、`final_success` 和 `critical_visual_defect`。未知 usage 保持 `unknown`。

**首阶段验收目标（不改变模型和 reasoning 档位）：** 模型请求数不高于 8，累计 reasoning 不高于 20,000，任务总耗时不高于 300 秒；首次 patch、最终成功率和 critical 视觉缺陷率不得劣化。目标是减少无效模型往返，不是通过放宽 patch 校验或增加重试达成。

**单变量实验顺序：**

| 版本 | 唯一变化 | 验收重点 |
| --- | --- | --- |
| B1 | 压缩 Coding/修复上下文 | 首次运行与首次修复成功率 |
| B2 | B1 + Code Mode 一次编排读/编辑/运行 | 请求数和 reasoning |
| B3 | B2 + 只读工具批量并发 | 工具耗时和顺序正确性 |
| B4 | B3 + 增量续接与稳定缓存前缀 | 重复 input 和 cache 命中 |
| B5 | B4 + 视觉 critical-only 修复回执 | 视觉修复长尾 |

每个版本使用同一冻结任务至少取得 5 个非删失样本；报告 P50/P95、原始样本和失败原因。任何版本首次运行率或最终质量下降，立即停止推广，不把多个变量合并后继续比较。

**2026-09-22 baseline 落地进度：** B0 配置、指标字段、首阶段目标和 B1–B5 单变量顺序已冻结。已确认现有 `record_coding_metrics`、逐请求 `modelRequestMetrics`、工具计数和视觉审查字段可承载 baseline，不新增指标框架。针对视觉 critical-only 回执、交付状态和指标 unknown 语义运行定向回归：`83 passed`。该结果只证明观测与回执链路可用，不计作 reasoning 或总耗时收益。

**本轮最小兼容修复：** Coding runner 在测试替身未提供 `delivery_state()` 时回退为空状态，不改变生产宿主状态机；指标断言同步新增 `firstScriptFailureCode` 字段。不得借此放宽工具协议或改变真实请求行为。

**2026-09-22 B1 输入投影已实现：** 当 Coding 进入修复轮时，`ReportingCodeGenerationRunner` 只保留脚本/证据路径、输出契约、`existingFacts`、`codingRequirements`、授权数据集的 `datasetId/path/columns`、分析身份和视觉修复所需的结构化契约；移除重复的 `visualizationFacts`、`visualizationPlan`、工作区元数据及数据行。首轮 payload 保持不变，宿主仍保存完整 facts。新增投影回归，`test_reporting_code_input.py` 为 `61 passed`。尚未取得同一冻结任务的 B1 provider 样本，因此不宣称 reasoning 或总耗时已改善。

**2026-09-22 B1 首次真实回放：** 复用 `/tmp/reporting-r7-analysis-v2`、candidate variant、`deepseek-v4-flash-0731`、high、summary=auto、enable_thinking=true、parallel_tool_calls=true；结果 `/tmp/reporting-b1-analysis-candidate.json` 为 `passed`，但该样本不能作为推广证据：总 Coding 耗时 `246.998s`，8 次请求，累计 reasoning `18,585`，首次写入请求 `177.037s / 14,046 reasoning tokens`；工具为 `write_script=1、run_script=3、read_script=1、edit_script=2、submit_script=1`；首次运行失败，首次 patch 应用成功但首次修复未成功，最终提交通过；原始协议 `rawProtocolCorrect=false`，发生一次 edit 信封规范化。首轮 `inputTokens=4,209`，后续修复请求输入随工具历史增至约 `27k–35k`；该样本没有同条件 legacy 配对，也不能证明 B1 投影减少了 provider 输入或 reasoning。保留为 B1 非删失观测样本，但验收状态为“未通过推广门槛”。

**2026-09-22 B1 配对对照补充：** 同一 `/tmp/reporting-r7-analysis-v2`、模型、high、summary、enable_thinking、parallel_tool_calls 和 wall-timeout 下执行 legacy variant，结果 `/tmp/reporting-b1-analysis-legacy.json`：`409.928s`、5 次请求、`32,745` reasoning tokens，首次写入 `383.883s / 31,100 tokens`，首次运行失败后首次修复成功，原始协议正确，最终提交通过。candidate 相比 legacy 的描述性差异为 `246.998s / 18,585 tokens`，但 candidate 同时启用了 `codingRequirements` benchmark variant，且候选的首次修复失败、原始协议错误；因此该配对不是 B1 单变量实验，只能记录为“候选路径有性能信号但质量门槛未过”，不得归因于 `_repair_task_facts()` 投影，也不得推广 candidate variant。

**组合回归阻断记录：** 将 B1 与旧 planner/visualization 稳定性文件组合运行时有 7 个失败，分别来自旧测试替身缺少 `session_state`（5 个）及冻结图表绑定契约在进入 Coding 前失败（2 个）；与 B1 投影无调用路径关系，未修改生产代码迁就这些失败。取得 B1 真实样本前，保留该阻断并单独运行受影响文件。

**依据：** 本文直接落实本轮已确认要求：重点降低两类任务的 reasoning 时间，按章节确定 Coding 范围，分析与可视化分开；2026-09-21 起不考虑多脚本，沿用现有单脚本绑定。现有收敛背景见 `docs/superpowers/plans/2026-09-18-code-agent-convergence.md`。复选框只按测试和真实回放证据更新；代码已落地不等于 reasoning 已改善。

**CodeMode 补充依据：** 2026-09-20 对本地安装的 Agno 3.0.9 `agno/tools/code/{code_mode,kernel,bridge,snapshot}.py` 与项目适配层的只读核对。此次补充落实“给出 CodeMode 优化方案并整理到本文件”，不视为已经授权执行全部架构迁移。目标是减少必要探索、工具往返和数据搬运成本，不以启用全部框架功能作为验收标准。

## 全局约束

### 2026-09-22 首轮基准纠偏与最小提示修正

- 已修复 `replay_instructions("analysis")` 默认错误选择 candidate 指令的问题：未显式选择 candidate 时使用生产 legacy 指令。此前 `/tmp/reporting-compact-analysis.json` 的 v1 facts 仅含 `evidenceDecision.missingFacts`，却被要求执行不存在的 `codingRequirements`；该 329 秒结果只保留为错配探索样本，不作为生产基线或提速证据。显式 candidate 与可视化指令选择保持原契约。定向验证 `5 passed`，Ruff 和 diff 检查通过。
- 对照 `/tmp/reporting-analysis-legacy-instructions.json`：同一 v1 payload、high/summary=auto/enable_thinking/parallel_tool_calls/max_output_tokens，facts 指纹完全相同；使用修正后的 legacy 指令，Coding 耗时 `542.148s`，3 次请求、`41,142` reasoning tokens，最终协议失败。compact 开关开启但 `compactContinuationApplied=false`。该样本在下述提示修正前启动。
- 首轮 `137.795s / 11,322 reasoning tokens / 849 visible tokens`，写出的源码仅加载数据、打印概览，并输出“数据加载概览（探索阶段，后续替换）”；收入结构及同比缺口未实现。run_script 通过执行与结构校验后，工具范围收敛为 submit_script。第三次请求耗时 `399.927s / 29,810 reasoning tokens`，返回未声明的 function 型 write_script，宿主正确拒绝，未执行整段重写。
- 复核 `/tmp/reporting-analysis-semantic-constraints.json` 后纠正原因：第二次 `write_script` 不是模型重复规划，而是首轮源码触发 `report_python_source_path_invalid`，随后以 `85` reasoning tokens 重新写入；该样本的 `firstScriptSuccess=false`、`firstRunSuccess=true`、`rawProtocolCorrect=false`，工具计数为 `write_script=2/run_script=1/submit_script=1`。错误码本身过去未保存 details，不能从 code 猜出具体违规路径。
- 协议归因纠正：路径错误不会修改 `rawProtocolCorrect`；它独立统计 provider 原始 custom 前缀与工具声明/身份等协议违规。历史样本同时存在路径拒绝与原始协议错误，不能推断两者有因果关系，也不能仅凭 false 判断是哪类信封。新增请求级 `firstToolFailure={toolName,code}`，在现有 Agno 顺序执行批次中记录第一个实际失败，后续跳过调用不覆盖它，后续请求不继承它。指标只保留这两个有界字段，不保存源码或任意 details。真实 Agno Agent + 模拟 provider 的闭环已验证：同一路径拒绝在标准 custom 输入下原始协议为 true，在单层 data 信封下为 false。该改动只补齐观测，不宣称降低 reasoning。
- 独立数值验收补齐：对 `/tmp/reporting-analysis-semantic-constraints.json` 对应 workspace `/tmp/reporting-visualization-replay-rgpap4_a`，使用标准库 CSV + Decimal 从原始数据复算，未调用生成脚本的筛选、聚合或对账函数。两份 CSV SHA 与冻结 payload 一致；按任务指定的两年 1–11 月窗口直接求和，2025 年为 `11,123,541,503`，2024 年为 `10,475,201,732`。核对总体、11 个月及四个维度的金额、占比、差额、同比和 null，共 `493` 个数值/null 检查无差异（显示值允许两位小数舍入误差），各维度类别集合与原始数据双侧并集一致。上海市高血压研究所上年有 2 行、合计为 0，不是缺失；日间治疗中心、脑病中心上年无行；财务处当年无行、上年 1 行为 `-11,796`，结果 null 均正确。
- 该样本仍未通过完整质量验收：生成脚本的 `only24 = sorted(set(b24) - set(b24) - set())` 恒为空，遗漏“财务处仅存在于上年”的 warning。数值正确和所有 reconciliations=true 不能证明告警完整。保留原始脚本及 evidence 作为冻结失败证据，不事后修补基线冒充首次成功；后续配对回放同时检查两个方向的缺失类别告警。这是该样本的具体缺陷，不将收入字段或科室名称写入通用生产规则，也不增加模型重试或语义硬门禁。
- 已收紧 `write_script` 工具描述与路径错误回执：明确 `unsignedPaths` 表示未签发路径、`forbiddenPathOperations` 表示目录推导操作；要求直接使用 task 签发路径，禁止 cwd、`__file__`、父目录拼接和 `os.path.dirname`。路径校验仍是硬失败。定向路径/工具协议测试 `4 passed`，Ruff 和 diff 检查通过。
- 已将生产 legacy 首句局部替换为明确的完整实现要求：首轮 write_script 实现所有可计算 missingFacts、输出 findings 和对账，禁止探索占位脚本或以字段/行数概览代替业务事实。不增加提示规划轮次、不关闭 reasoning、不扩大工具范围、不增加重试，也不把业务完整性改为硬失败。
- 待验证：新提示的真实首次完整实现率及累计 reasoning；当前尚无收益证据。后续必须同时核对业务缺口覆盖和结构/执行结果，不能把较短首轮、firstRunSuccess=true 或 schema 通过当作完整交付。本次不继续盲目复跑；下一次单变量实验仅改变上述首句，并使用同一冻结任务。

2026-09-22 首句单变量实验已完成：`/tmp/reporting-analysis-direct-implementation.json`，facts 指纹与上一条完全一致，high/summary/工具配置保持一致，compact 未触发。Coding `475.631s`、5 次请求、`37,555` reasoning tokens；首轮 `387.542s / 32,329 reasoning tokens`，直接生成完整计算脚本，未生成探索占位。首次运行失败：将当期与上年同期的 `year*100+month` 直接求交集，导致不同年份必然无共同月份；一次精准 patch 后运行及提交通过，原始协议正确。最终 evidence 包含总体、门诊/住院、收入类型、院区、科室及月度同比，月份覆盖差异保持软告警。但科室单侧缺失按 0 处理仍与不补齐缺失值约束冲突，未通过业务质量验收。相比上一条失败样本，累计耗时约下降 12.3%、reasoning 约下降 8.7%，但首次写入 reasoning 明显上升；单次样本且质量未达标，不宣称性能优化成立。下一步优先明确同比月份对齐与单侧缺失语义，保持精准 patch 和业务软告警，不增加重试。首句改动保留为待验证修改，尚未提交或认定已推广。

**2026-09-22 宿主预执行样本验收补齐：** 最近 582.529 秒样本的六图文件身份与终态审查回执一致，seed 与首次失败全文快照一致；AST 仅结构图和异常月份图两个函数变化，未整段重写或改金额/同比公式。人工检查终态两张结构图关键文字可辨认，合计分项及异常图密集标签问题仍保留；8 条 warning 不因自动门禁通过而消失。真实首次修复成功率仍未改善。阶段边界历史整理仍待用户确认，未修改生产上下文策略。

**2026-09-22 上下文增长定位（待批准实验，不改生产）：** `_project()` 复用的窗口重建是容量保护。当前 deepseek-v4 已验证窗口为 262144 tokens，输出预留 65536，默认输入 hard cap 196608、0.75 重建阈值约 147456（本地估算，不等于 provider 实际 token 数）；最新续修 provider 输入从 10386 增至 74711，低于该默认阈值，因此不能期待现有容量保护主动消除早期修复历史。工具声明按阶段收敛不等于历史消息已压缩。原始 reasoning item 随保留的完整工具轮次回放，不能任意剪掉 item 内部内容或伪造摘要。

同样不能把长推理全部归因于输入长度：请求 3 输入 17856、reasoning 11916、135.687 秒；请求 5 输入增至 32767，但 reasoning 3157、30.075 秒。下一候选为独立实验中的阶段边界历史整理：执行通过转入视觉阶段后，仅压缩已解决的旧失败轮次，保留任务约束、当前源码身份、未解决问题、最近完整工具轮次及原调用结果配对；不增加摘要模型、不关闭首轮思考、不降低输出上限。必须先验证最新源码可恢复及错误状态不丢失，再做同 seed 的单变量对照。该候选尚未实现或批准，不将诊断结果标成性能改进。

**2026-09-22 首次修复上下文补正：** 失败回执原来把错误前后 12 行同时当作展示范围和允许修改范围，可能把真实根因排除在外。现通过 AST 定位最内层所属函数：函数不超过 1800 bytes 时返回完整函数，否则保留函数内有界错误片段；允许修改范围按函数标注，SHA 和精准 patch 校验不变。此改动只消除错误指引，不等于真实首次修复率已提高。

**2026-09-22 修复状态传递补正：** 后续核对发现长函数片段不完整时仍只推荐直接 edit，而且交付状态摘要丢失了函数修改范围。现对不完整片段补充 readRange 和 read_script 指引，交付状态保留 errorType、allowedEditRegion、readRange（保留结构化行号，不拼成字符串）。短函数完整片段仍可直接编辑，不强制额外读取。两个新断言先复现缺失，修正后连同失败摘要、源码片段与状态重建相关用例 6 passed；未新增 provider 请求，不宣称首次修复率或 reasoning 改善。

**2026-09-22 确定性首轮运行：** runner 已接入已有脚本的宿主预执行，只在没有传入诊断、没有执行回执或失败、状态唯一要求 run_script 时执行一次。复用注册工具的 Agno FunctionCall 与执行钩子，保留首次失败快照、源码和输出校验、结构预检、视觉与提交门禁；不自动重试，不伪造 provider 调用消息。宿主占一次任务执行额度，模型初始与 continuation 共用扣减后的额度；未提交诊断分别记录宿主、provider 和总次数。取消时无结果不记为首次成功。成功、失败、取消、诊断传递和预算耗尽已有离线定向证据，真实冻结样本的总耗时与首次修复收益仍待验证。当前仅省去首次已有脚本的确定性运行请求，未接管每次 edit 后的运行，不宣称全部确定性往返均已消除。
**2026-09-22 确定性首轮真实复测：** 同一冻结候选脚本启用宿主预执行后，首个模型请求为 read_script，3.782 秒、25 reasoning tokens；宿主没有伪造 provider 工具消息，失败诊断 SHA、函数范围和 sidecar 一致。完整续修总耗时 582.529 秒、17 请求、45,623 reasoning tokens，5 次局部 patch、write 0、首次修复仍失败；主要长尾转移到 patch 请求，不能宣称总耗时改善。该样本不是无预执行样本的单变量 A/B，输入状态和模型轨迹不同；它证明首轮确定性等待已被移除，未证明首次修复率或 P95 改善。详见同日冻结与修复报告。

**2026-09-22 复杂续修验证：** candidate 现存六图脚本以 high 完成独立续修，456.167 秒、34,747 reasoning tokens，3 次精准 patch、0 次 write；首次 patch 后仍运行失败，最终六图自动审查无 critical，但仍有可读性与业务软告警。一次 edit 使用单层解包，原始协议并非全部正确。已修复普通 payload 回放未自动加载冻结 seed 的入口缺陷，以及 traceback 错取外层调用点的问题；首次失败全文 sidecar 已真实验证。误走整段写入的中止样本已明确排除。本次使用重新审核的计划，不计入原 A/B 收益。仅 run_script 的首请求仍耗时 85.613 秒、7,269 reasoning tokens，后续优先检查确定性阶段模型往返与修复上下文增长；详细证据见同日冻结与修复报告，不宣称长推理解决。

**2026-09-22 修复反馈验证：** 已修正 stderr 真实异常被外层 traceback 覆盖、错误推荐完整写入两类反馈问题。真实小型局部修复探针以 high 完成 run→edit→run→submit，12.032 秒、129 reasoning tokens，仅一处 patch；未复现复杂可视化的非法调用，不视为性能验收通过。详细证据见同日可视化冻结与修复报告。

**2026-09-22 观测补齐：** 协议拒绝前保存 provider 响应 ID 与可用 usage，类型/声明错误附脱敏调用身份；失败任务不再把部分用量当总量。回放新增首个运行失败的 SHA 校验源码 sidecar，生产默认不启用全文存储。旧样本缺失信息无法追回，非法调用的模型/网关根因仍未确认；下一步基于新证据做定向诊断，不扩大重试或工具权限。

**2026-09-22 真实对照结果：** 高优先级 2 的新六图 v2 输入已冻结并通过 SHA/绑定审核；高优先级 3 的已有脚本局部修复闭环通过，276.595 秒、一次精准 patch、六图最终无 critical，无 write_script。revision-3 仅补齐静态模式，两侧均通过 planner 路径门禁：legacy 547.741 秒交付通过但有业务软告警；candidate 545.423 秒因 provider 返回未声明且类型不符的 edit_script 失败，未交付。candidate 首写 reasoning 降低，但 planner 增耗，到首写累计仅节省约 18 秒，不能作为完整成功提速证据，不推广。后续观测修复见上文；历史缺失数据不补造。详见 `docs/superpowers/reports/2026-09-22-visualization-freeze-and-repair.md`。ToolBridge/ResultStore、缓存、多图审查的并行离线复核分别记录在同日报告，未满足上线门禁，不默认启用。

- `write_script`、`edit_script`、`run` 保持 provider wire 层原生 free-form custom tool；`run_script`、`read_script`、`submit_script` 等保持当前 function tool 契约。本文历史记录中将 `run_script` 与 free-form 输入并列的表述不代表其真实 wire 类型，也不授权更改该类型。
- free-form 工具只接受 provider 返回的结构化 `custom_tool_call`；已声明的 function 工具按其原生结构化调用处理，支持混合批次。不得解析 assistant 正文中的 Markdown、DSML 或伪工具调用。
- `parallel_tool_calls=True` 固定开启，允许 provider 在一次响应中最大化返回结构化工具调用；宿主不得人为设置单调用上限、因调用数大于 1 拒绝整批，或把该参数误解为工具已经并行执行。
- 多调用先整体校验调用身份、类型和工具范围，再按 provider 返回顺序逐个委托执行；有状态的读/写/运行/提交链路不得并行。只有经独立契约证明互不依赖的只读调用，才可在宿主调度层并行，且必须保持原调用 ID 和回放顺序。
- 前序调用失败或提交后停止执行后续调用，但必须补齐与原调用身份匹配的未执行回执。
- 业务语义问题只做软告警；源码身份、patch 唯一匹配、输出产物身份和协议错误仍为硬失败。
- 日志使用 loguru；不要重复运行完整报表，优先使用冻结 payload、回放脚本和定向测试。
- 不增加盲目重试次数，不放宽精确 patch 校验，不用整段源码重写替代局部 patch。
- 首轮保留 reasoning；保留 Responses 支持的 `reasoning.effort` 与 `reasoning.summary`，并按 provider 能力投影 `enable_thinking`。`summary` 只用于模型摘要和可观测性，不是推理预算；Responses 请求、bundle、日志和验收均不得出现 `thinking_budget`。任何 provider 不支持的扩展字段必须省略或在请求前硬失败。
- 不通过新增工具调用次数或输出 token 上限压缩耗时；不人为限制 provider 单次响应中的工具数量。现存交付预算也不能与必要的读取、编辑和执行动作冲突。
- 分析与可视化不合并；章节确定任务范围，不改变现有每个 Coding task 绑定一份脚本的契约。已有脚本不得用新文件名完整重写来绕过局部 patch。
- 优先复用 Agno、现有 Coding runner、事实投影和运行环境能力，不新建通用调度框架；先验证减少推理的收益，再扩大改动范围。

## 本轮重新规划：降低分析与可视化的 reasoning 长尾

### 事实、假设与当前能力边界

| 证据 | 可以得出的结论 | 不能据此断言 |
| --- | --- | --- |
| 可视化 `medium-3` 的已观察首轮约 573 秒，input=14284、output=49222、reasoning=41267、visible=7955、cache read=1024 | 该请求的输出主要消耗在 reasoning；`medium` 没有形成硬 token 上限 | 不能把所有 reasoning 都算作浪费，也不能推算输入减半就能让推理减半 |
| `medium-3` 首次写入和运行成功，随后六张图出现中文方框，进程后续消失且未生成最终结果 JSON | 首轮数据和字体缺陷可作为局部证据 | 不是完整成功样本；不能推算全任务 usage、总耗时或最终质量 |
| 分析 v2 high-effort A/B 已取得 3 组样本，candidate 的 Coding reasoning 下降，但 planner reasoning 上升且首次运行率下降 | 必须按 planner + Coding 累计指标和质量共同判断 | 不能把 planner 增长归因于输入长度，也不能据 3 组样本宣称稳定 P95 改善 |
| 优化前 `AnalysisEvidenceDecision.missingFacts` 是文字数组，且 `_script_task_facts()` 没有携带已有 `deterministicFacts` 或其文件引用 | 分析 Coding 可能自行补齐计算方式和对账依据；R3 已先补入紧凑 `existingFacts` | R3 不能替代结构化计算要求，也不能因此全量重复注入事实 |
| `ChartDraft` 有图表身份、标题、指标、期间和输出路径，缺少明确的图型、数据定位及轴/系列映射 | 可视化 Coding 仍有实现前的设计决策 | 补齐所有布局参数并不必然更快，不能先扩建复杂规划系统 |
| `_INTERACTIVE_CODE_INSTRUCTIONS` 已要求不重复规划，仍观察到长推理 | 单纯继续添加“少思考、直接写代码”提醒证据不足 | 不能据此归因于 Agno SDK，也不能证明 provider 忽略了 effort |
| `_bootstrap_cell()` 只设置工作目录和 Agg；正式脚本由独立 Python 进程执行 | 字体配置需要覆盖正式执行进程 | 仅在交互 kernel 设置 `rcParams` 不能保证正式脚本继承 |

### 2026-09-20 本轮新增基线

| 阶段 | 结果 | 总耗时 | 首次写入请求 | 累计 reasoning | 结论边界 |
| --- | --- | ---: | ---: | ---: | --- |
| 可视化，`medium`，精简指令后 | 失败，未提交 | 851.383 秒 | 466.945 秒 / 25,651 tokens | 40,575 tokens | 首轮仍是长尾；正式脚本子进程因 Workspace cwd 下无法导入 `smart_reporting`，4 次 `run_script` 被宿主错误拒绝，样本不能用于最终质量或总耗时收益比较 |
| 可视化，`medium`，修复子进程后 | 通过 | 756.781 秒 | 441.368 秒 / 31,037 tokens | 46,713 tokens | 宿主导入故障消除，首次运行、局部修复、视觉审查和提交通过；首轮与累计 reasoning 仍高，不能归因于输入精简已解决 |
| 可视化，`medium`，紧凑 Coding facts | 通过 | 423.772 秒 | 309.541 秒 / 24,073 tokens | 24,354 tokens | 同一冻结任务中 facts 从 34,356 bytes 降至 22,609 bytes；首次运行、6 图审查和提交通过，`critical=0`，该次原始协议不正确 |
| 可视化，`medium`，紧凑 Coding facts，第 2 次 | 通过 | 509.258 秒 | 387.645 秒 / 31,603 tokens | 32,660 tokens | 首次运行和 6 图审查通过，`critical=0`；首个 `write_script` 因路径规则被拒，第二次写入经单层信封规范化后成功 |
| 可视化，`medium`，紧凑 Coding facts，第 3 次 | 通过 | 726.632 秒 | 371.917 秒 / 29,078 tokens | 56,296 tokens | 首次写入、首次运行均成功，原始协议正确；首次视觉审查发现 2 项 critical，修复请求消耗 263.177 秒 / 26,742 reasoning tokens，最终 6 图通过 |
| 分析，`medium`，历史冻结 payload | 通过 | 187.771 秒 | 第 4 个请求，153.284 秒 / 11,948 tokens | 12,523 tokens | 写入后首次运行和提交均成功；历史 payload 没有新增的 `existingFacts`，因此这是 R3 前基线，不是 R3 收益证明 |
| 分析，`medium`，加入签发紧凑 `existingFacts` | 通过 | 130.352 秒 | 第 4 个请求，55.139 秒 / 3,947 tokens | 8,650 tokens | 同一任务和模型下累计 reasoning 减少约 30.9%，总耗时减少约 30.6%；仍有一次信封规范化，不能把协议正确率视为通过 |
| 分析，`medium`，加入签发紧凑 `existingFacts`，第 2 次 | 通过 | 183.239 秒 | 60.836 秒 / 3,946 tokens | 11,620 tokens | 首次完整写入 reasoning 与第 1 次几乎一致；任务仍有探索、两次局部编辑和三次运行，累计耗时存在波动 |

可视化失败已定位为 R4 子进程启动缺陷，而非模型脚本错误：启动命令从临时 Workspace 执行 `python -c`，项目包不在 `sys.path`，导致 `ModuleNotFoundError: smart_reporting`。宿主现按当前已加载包位置注入 import root，并新增项目目录外 cwd 的真实子进程回归。该修复用于消除无效修复 reasoning，不能解释或宣称首轮 25,651 tokens 已解决。

两个分析 `existingFacts` 样本的首次完整写入 reasoning 分别为 3,947 和 3,946 tokens，说明减少重复推导对这一请求已有稳定信号；两次任务总耗时分别为 130.352 和 183.239 秒，累计 reasoning 分别为 8,650 和 11,620 tokens，探索与运行修复仍会放大整体波动。

三个紧凑可视化 facts 样本均最终交付、首次运行成功且 `critical=0`。描述性总耗时 P50/P95 为 509.258/726.632 秒，累计 reasoning P50/P95 为 32,660/56,296 tokens，首次写入 reasoning P50/P95 为 29,078/31,603 tokens。相对修复后单样本基线 31,037 tokens，不能声称首次写入 reasoning P95 已改善；第三次样本的视觉修复请求单独消耗 26,742 reasoning tokens，是当前更明确的长尾来源。

该视觉修复长尾并非质量门禁本身造成：宿主只因 2 项 critical 要求修复，但 `view_image` 将其他图片的 summary、warning issues、warnings 和 suggestions 全量回放给 Coding 模型，模型随后生成 8 个 patch 块并处理大量非阻断 warning。完整审查结果必须继续保存在宿主以供审计和最终交付，但模型可见工具回执应只包含是否需修改及与 critical 直接相关的上下文。

### 当前实施顺序与职责

| 顺序 | 任务 | 可独立验收的结果 |
| --- | --- | --- |
| P0 / R1 | 补齐两类任务的首轮观测和冻结基线 | 区分规划、首次写入前请求、后续修复及工具执行耗时 |
| P0 / R2 | 精简公共指令和阶段输入 | 删除重复和不适用约束，必要信息、工具协议及行为保持完整 |
| P0 / R3 | 补齐分析 Coding 所需的现成事实 | 当前缺口对应的数据、口径和对账基准可直接使用 |
| P0 / R4 | 减少可视化运行环境与已知设计决策 | 正式脚本字体可靠；复用现有图表计划而非重复设计 |
| 已实现、待实测 / R4.1 | 压缩视觉工具的模型可见回执 | 非阻断 warning 不进入修复上下文；critical 修复只看到直接相关问题 |
| P0 / R7 | 按章节冻结必要实现决策 | 分析与可视化分别减少 Coding 重复规划，且规划加 Coding 的累计 reasoning 下降 |
| P1 / R6 | 健康探针成功后做两阶段真实冻结对照 | 成功率和质量不下降，推理及总耗时有可追溯改善 |

R1 已将阶段 recorder 和生产 receipt 接线，但历史分析 Coding 的 Agno run metrics 仍有持久化缺口；R2–R4.1 的代码改动和定向测试已经完成，R4.1 的真实收益尚未通过单变量对照验收，不再盲目重试。历史三个可视化成功样本的首次写入 reasoning 为 24,073–31,603 tokens；R7.1、R7.2 的结构契约已经完成。分析 high-effort A/B 已完成 3 组，candidate 有累计 reasoning 收益但质量门槛未过；planner-medium 单变量诊断也未显示累计收益，因此不推广。可视化可信输入已就绪，revision-3 完整尝试为 legacy 交付通过、candidate 协议失败，尚无成功配对收益；R5 多脚本基础设施已退出本轮范围。首次失败快照虽已接线，本轮回放产物仍只有摘要，须核实持久化链路，不能从最终脚本反推失败源码。R7 必须复用现有规划调用，分析与可视化分开实施，不增加 planner 轮次。

原任务 6、10 尚未完成的真实 A/B 与冻结集验收统一由 R1、R6 承接，不重复组织另一套测试；原任务 8 的多图单请求调查保留为后续优化，不阻塞当前 reasoning 目标。

### R1：取得分析与可视化各自的真实基线

**涉及文件：**

- 修改：`smart_reporting/reporting/workflow/runtime/code_generation.py`、`smart_reporting/reporting/code_agent/metrics.py`。
- 修改：`scripts/replay_visualization_task.py`，保留现有可视化命令兼容；增加 analysis payload 分支，复用生产的分析指令与 evidence 预检，禁止测试脚本复制一套简化协议。
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py`、`smart_reporting/reporting/tests/test_replay_visualization_task.py`。
- 记录：`docs/superpowers/reports/2026-09-20-reporting-coding-performance-ab.md`。

**输入/输出：** 消费实际 provider 请求、usage、现有 recorder 和冻结 payload；在现有样本上增加阶段、章节/分析项归属、首轮至首次 `write_script` 的耗时及对应 reasoning tokens。沿用 `unknown` 缺失值语义，不从响应总时间估算纯思考秒数。

- [x] 增加定向用例：首轮请求、写入前额外探索、后续修复分别归属；usage 缺失不记 0；阶段不同不混算成功率；验证用例先失败再最小实现。
- [x] 区分 provider 可直接观测的 reasoning tokens、请求总耗时与首个可见输出时间。只有流式事件确实提供时间边界时才报告 reasoning 阶段时长；否则记为不可独立观测。
- [x] 记录公共指令、阶段指令、task、facts、diagnostic、工具声明的字节数与哈希；token 数只使用真实 tokenizer 或 provider usage，不能把字符数标作 token。
- [x] 每个 provider 请求保留有序、有界的 `toolCalls[{id,name}]` 与 `toolCallCount`，同名调用不去重；兼容字段 `toolNames` 继续作为去重集合。该字段已穿透 Coding 样本和生产 `modelMetricsByStage.coding.requestMetrics`，不记录参数、源码或结果。
- [x] 已冻结真实分析补证任务和已有六图章节的 Coding 阶段输入文件身份、模型配置、请求版本与验收结果。样本包含输出结构与业务对账预期，不能只留 prompt。
- [x] 分析已从 planner 前冻结章节输入生成并校验 v2 bundle，完成 3 组 high-effort 对照；Coding-only bundle 不冒充完整两阶段基线。
- [x] 2026-09-22 从 SHA 核验的 9 份实际文件走当前生产投影，取得六图 `dataDescriptors`、逐图 acceptance 和 v2 bundle：`/tmp/reporting-visualization-v2-Pfuhj1/revision-2/bundle`。这是本次新冻结输入，不补造历史 trace；真实 planner+Coding A/B 仍待执行。
- [x] 回放分析任务必须运行生产 `validate_supplemental_evidence()`；业务对账不通过保留软告警，结构或文件身份错误仍失败。人工终止或进程消失保留已观察事件，不伪造完整结果。
- [x] 修复成功任务仍保留已解决历史错误码的指标污染：最终交付成功时 `failureCode` 为 `unknown`；终止异常优先，未解决工具失败仍进入最终失败分类，历史工具错误继续保留在事件轨迹中。
- [x] 运行：`.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py smart_reporting/reporting/tests/test_replay_visualization_task.py`。

**验收：** 可分别回答“分析/可视化第一次写入前花了多久、用了多少 reasoning、是否把耗时转到规划或后续修复”；不为取得基线重复完整报表。

### R2：精简首轮任务定义和重复约束

2026-09-21 追加真实分析验证：修复 supplemental evidence wire schema 漏声明 reconciliation `name`/`passed` 的契约缺口，并明确 legacy Coding 只实现缺口、无法从授权数据获得的部分记 warnings。原脚本通过局部 patch 后运行和生产结构校验通过。相同 trace 输入的独立回放首次写入/运行/提交全部一次通过：首轮 208.677 秒、17,839 reasoning tokens，相对原首轮 254.626 秒、21,417 tokens 分别下降约 18.0%/16.7%；完整 Coding 216.235 秒。单样本尚不构成稳定收益结论。详见 `docs/superpowers/reports/2026-09-21-analysis-first-write-contract.md`。

同一冻结输入补充 Coding medium 对照：首轮 265.610 秒、23,839 reasoning tokens，累计 24,189，Coding 指标耗时 306.753 秒；首次写入拒绝，第二次信封规范化后成功，随后运行/提交通过。输入组件哈希及除 effort 外的首轮参数一致，缓存状态不同。相比 high 未见收益，不修改生产 high 默认值。两轮总额、逐月及收入构成已独立重算；medium 合计行把整体结构移动量填入占比差列，记录业务软告警，不修改原始样本。原始协议正确率、稳定成功率和 P95 仍需更多证据，不能据最终提交通过标记全部完成。

补齐上述回放暴露的观测缺口：新增 `firstScriptFailureCode`，由现有 Agno post hook 记录并进入最终 Coding 指标，后续成功不覆盖首次失败；INFO 工具进度显示有界错误代码。8 个定向用例通过，未追加真实模型请求。旧样本未保存拒绝详情，原因继续标为未确认；该改动不计作推理耗时收益。

**涉及文件：**

- 修改：`smart_reporting/reporting/agent.py` 中 `_INTERACTIVE_CODE_INSTRUCTIONS` 与工厂的指令装配。
- 修改：`smart_reporting/reporting/workflow/runtime/base.py` 的分析 Coding instructions、`smart_reporting/reporting/bootstrap.py` 的可视化 instructions。
- 修改：`smart_reporting/reporting/workflow/runtime/code_generation.py` 的模型输入投影；宿主完整 `ReportingCodingTaskContext` 不随 prompt 精简而丢失。
- 测试：`smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`、`smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`、`smart_reporting/reporting/tests/test_reporting_code_input.py`。

**输入/输出：** 输入仍来自受信任务上下文；输出为按阶段组装的紧凑请求。保留现有 Runner 和 Agno Agent，不增加摘要模型。

| 信息 | 唯一主要归属 | 精简要求 |
| --- | --- | --- |
| 当前职责、数据真实性、授权边界 | 公共 instructions | 表述一次；分析请求不注入看图、字体、布局等专属规则 |
| 原始代码/patch 格式、grammar、拒绝信封 | 对应工具描述 | system 仅保留交互原则，不再次复述完整工具手册 |
| 输出 JSON 的字段、null 与行编码规则 | 分析 `outputContract` | instructions 引用该契约；明确这是脚本产物而非工具输入格式 |
| 图表数据语义、渲染方式 | 可视化 instructions 与 plan | 仅投影实际适用的规则，不移除百分比、nullable 和分组身份要求 |
| 当前可执行动作 | `REPORTING_CODE_DELIVERY_STATE` | 不再泛化要求已有脚本一律先读；已有最新源码与 SHA 时允许直接精确编辑 |
| 路径、来源、期间、目标与缺口 | 当前任务 payload | 相同值去重；保留对应关系，不让模型从路径或标题猜测身份 |

- [x] 增加行为用例：分析请求不含视觉专属义务；可视化仍须审图；evidence JSON 与 free-form 输入无冲突；基于最新 `savedSource` 或失败 excerpt/SHA 的 patch 无需多余读取。
- [x] 在相同冻结输入上比较投影前后大小与字段覆盖，先确认必要字段缺失会使测试失败，再精简实际装配。压缩不按固定比例硬截断，不删除全部库能力或数据口径说明。
- [x] 去掉工具协议、路径与输出格式的重复文本，删除失效工具指引；冻结 facts、必要日期语义和单位规则保留明确来源。
- [x] 运行：`.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_code_input.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`。

**验收：** 请求更紧凑且原始协议正确率、首次运行成功率不下降；不能仅以文本缩短宣称 reasoning 已下降。

#### R2.1：收敛剩余固定重复，不扩大动态投影范围

2026-09-21 只读审计确认，公共指令、阶段指令、输出契约、动态交付状态和 wire 工具描述仍有少量重复。静态估算显示，低风险收敛约可减少分析任务 `400–550` tokens、可视化任务 `150–220` tokens；这只是输入解释变量，不能替代 reasoning 与质量实测。历史 `existingFacts` 样本在输入变大时仍显著降低首次写入 reasoning，说明优先目标仍是消除重复推导，而不是追求最短 prompt。

- [x] 公共 instructions 只保留“遵循当前 `nextTools` 与工具声明”，删除已经由动态交付状态和 free-form wire 描述完整表达的固定调用顺序、JSON 信封和 Markdown 围栏复述；工具描述继续作为输入协议唯一权威来源。
- [x] 分析 `outputContract` 以 JSON Schema 为结构权威来源，只额外保留 schema 无法表达的“业务对账失败为软告警”和紧凑写入语义；已删除重复根键列表和 example，保留 reconciliation、null、等长行编码和有限数值契约。
- [x] 公共层统一禁止 cwd、`__file__` 和目录推导；分析/可视化 stage 只声明各自使用哪些已签发路径字段，避免三处重复相同路径规则。
- [x] 合并公共与阶段层的“不重新规划、直接实现”提醒：公共层保留首轮 reasoning 聚焦实现，阶段层只保留具体事实/计划字段绑定。
- [x] 已增加固定指令字节/token 预算和必要语义行为测试，并保留 free-form wire、混合工具顺序、分析/可视化隔离及 replay/production 一致性回归；分析固定指令与 outputContract 合计从 `5219 bytes / 1533 cl100k tokens` 降至 `3511 bytes / 1042 tokens`，可视化固定指令从 `4748 bytes / 1475 tokens` 降至 `4427 bytes / 1380 tokens`，定向组合 `219 passed`，补充契约组合 `19 passed, 1 skipped`。真实 reasoning 收益仍需进入 R6 单变量对照，不能与 C2、effort 同时改变。
- [x] 第二阶段已把完整内部 `ReportingCodingTaskContext` 投影为脚本实现所需的六个模型可见字段，并按 `dataBindings` 裁剪 candidate/生产可视化 descriptors；宿主授权读取路径仍由完整 facts 决定。完整任务身份只进入独立 trace metadata，提取冻结 bundle 时与模型 task 逐字段核对后恢复；legacy 继续使用未按 binding 裁剪的原紧凑 facts。定向边界已通过，真实 reasoning 和首次成功率收益仍由 R6 单变量验收，不能仅凭输入缩短推广。

### R3：分析 Coding 复用必要事实，减少重新推导

**涉及文件：**

- 修改：`smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py::_script_task_facts()`。
- 修改：`smart_reporting/reporting/workflow/runtime/analysis.py` 中分析事实投影及 `run_code()` 的授权输入绑定。
- 修改：`smart_reporting/reporting/workflow/runtime/base.py` 的分析阶段职责说明。
- 测试：`smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`、`smart_reporting/reporting/tests/test_reporting_code_diagnostics.py`。

**输入/输出：** 消费已有 `currentAnalysis`、`evidenceDecision`、`datasets` 和受信 `deterministicFacts`；给 Coding 提供当前缺口必要的既有事实、单位、期间、字段映射及对账基准，不重复完整事实文件。

- [x] 写用例覆盖：两个数据集同名/不同名字段、已有总量对账、合法 null、比较期间不一致。断言基准来自当前分析项，不能借用其他分析项或 Dataset 的数值。
- [x] 优先确定性投影上游已经明确的数据集/字段/聚合/期间信息；不能根据 `missingFacts` 文本猜测公式。缺失信息保留为具体未决项，必要时针对该项读取或核对。
- [x] 已有事实只用于缺口计算与验证；不因提供摘要而禁止真正需要的补证计算。需要读取事实文件时同步签发其身份和授权路径，不能只在 prompt 加路径。
- [x] `outputContract` 保持唯一完整结构说明；对账差异写 `passed=false` 和 warnings，不诱导模型反复修到数值相等。
- [x] 用例先验证缺口上下文不完整或身份错配能被识别，再最小实现投影。运行：`.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_code_diagnostics.py`。

**验收：** 分析 Coding 能直接使用已确定的口径和基准；真实回放确认规划加 Coding 的累计 reasoning/耗时改善，不能仅把复杂计算描述前移给 evidence 决策模型。

### R4：可视化减少环境与已有设计决策

**涉及文件：**

- 修改：`smart_reporting/reporting/code_mode.py`；复用 `smart_reporting/sandbox/matplotlib_defaults.py`。
- 修改：`smart_reporting/reporting/workflow/runtime/analysis.py` 的 `facts_payload` 投影、`smart_reporting/reporting/bootstrap.py` 的可视化 instructions。
- 测试：`smart_reporting/tests/sandbox/test_matplotlib_defaults.py`、`smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`、`smart_reporting/reporting/tests/test_visualization_read_paths.py`。

**输入/输出：** 消费冻结章节图表计划、所引用的 facts descriptors 和现有字体 bootstrap；输出可靠的正式执行环境及仅包含必要绘图信息的请求。

- [x] 先增加真实子进程用例，重现“kernel 设置字体但正式脚本未获得字体配置”；修复必须覆盖 `_script_process_cell()` 启动的 Python 执行路径，不能只验证内存中的 `rcParams`。
- [x] 复用现有中文字体和 Agg 配置，验证正式脚本绘制中文无需自行枚举字体；提示中的“字体已配置”须与执行环境一致。
- [x] 复用已经存在的图表标题、指标、期间、renderer 和输出身份；Coding facts 仅保留本章需要的 facts descriptors、nullable/rowEncoding/单位信息及必要关系，规划输入保持不变。
- [x] 数据定位无法从现有受信信息唯一确定时，保留原有候选 descriptor 及其 `metricIndex`/`findingIndex`，不凭标题重新猜测。新增图型/系列等计划字段仍放到 R7，依据重复回放决定。
- [x] 运行：`.venv/bin/python -m pytest -q smart_reporting/tests/sandbox/test_matplotlib_defaults.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_visualization_read_paths.py`。

**验收：** 正式执行进程可正确显示中文；必要事实完整，首轮推理与后续视觉修复分别计量。三个紧凑 facts 样本均交付成功，但首次写入 reasoning P95 未显示明确改善，累计 reasoning 又受视觉修复长尾放大，因此仍不能认定长尾目标完成；字体修复本身只减少返工，不计作首轮 reasoning 收益。

### R4.1：压缩视觉修复的模型可见上下文

**涉及文件：**

- 修改：`smart_reporting/reporting/code_agent/toolkit.py`，增加视觉审查结果的模型可见投影；宿主保存的 `ChartVisualInspectionReceipt` 保持完整。
- 测试：`smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`；按现有职责需要补充 `smart_reporting/reporting/tests/test_reporting_visual_repair_diagnostic.py`。

**输入/输出：** 输入仍是完整视觉审查 receipt。宿主继续将完整 receipt 写入 `binding.visual_inspection_receipts`，用于最终报告、质量审计和提交校验；`view_image` 返回给模型的 `receipt` 改为紧凑投影。不得改变 critical/warning/info 的判定，也不得跳过任何图片的视觉审查。

- [x] 先写失败用例：仅含 warning 的完整 receipt 仍保存在 binding，但模型可见回执不包含 warning 描述、summary、warnings 或 suggestions，只返回路径、SHA、状态、`reviewed=true`、`requiresRevision=false`、`warningCount` 和“无需修改”的固定消息。
- [x] 写失败用例：同时含 critical 与 warning 时，模型可见回执只包含 critical 的 `category`、`severity`、`description`。当前 receipt 的 suggestions 没有 issue 身份；只有全部 issue 均为 critical 时才保留 suggestions，混合严重级别时省略，不能猜测归属。
- [x] 写失败用例：缓存命中与新审查使用同一投影，不能因第二次 `view_image` 把完整 warning 重新注入模型历史。
- [x] 写兼容用例：`_update_tool_result()` 仍能从紧凑 receipt 识别 `requiresRevision`；binding 仍完整保存原始审查结果。
- [x] 补齐最终 Runner 结果用例：同步测试入口使用 `asyncio.run()`，预置完整 receipt，验证模型可见回执经过压缩，同时 `CodeGenerationResult.visual_inspection_receipts` 仍包含完整的 summary、warnings 和原始问题。
- [x] 在 `delivery.py` 增加单一 `_visual_review_model_receipt()` 投影函数，供 `toolkit.py` 与交付状态共用，避免循环依赖和两套过滤规则。`requiresRevision=false` 时只给状态和 warning 数量；`requiresRevision=true` 时只给 critical 问题及可确定归属的建议。
- [x] `REPORTING_CODE_DELIVERY_STATE.visualFailures` 和外层 `_visual_repair_diagnostic()` 同样只投影 critical，避免 warning 从后续 system 状态或章节重试再次进入修复上下文。
- [x] 在生产与回放共用的可视化 Coding 指令中明确修复边界：critical 只允许修改直接相关局部代码；warning/info 不驱动修复；禁止插入临时诊断、`raise`、打印、探针数据或整段重写。新增回放指令契约测试，防止后续回归。
- [x] 视觉诊断和交付状态定向用例共 `35 passed`，回放工具定向用例 `11 passed`；后续交互代理视觉/回执筛选回归为 `27 passed, 57 deselected`。模型可见 `visualFailures` 只保留 critical issue，完整 summary/warnings/suggestions 仍保存在 binding receipt。目标文件 Ruff、compileall 和 `git diff --check` 通过。原 AnyIO 用例在该文件内卡住，因此只调整测试入口，不修改生产代码迎合测试。
- [ ] 使用产生两项 critical 的同一冻结可视化任务做一次单变量回放，保持模型、effort、facts、图片和验收条件不变。记录视觉修复请求耗时、reasoning tokens、patch 块数、首次修复成功率和最终 critical 数量。

- [x] 回放 CLI 增加可选 `--wall-timeout-seconds`（默认不设置）：只对 benchmark 的 planner/Coding 阶段施加显式整轮 wall-timeout，超时写出 `status=timed_out`、`report_replay_wall_timeout`、`censored=true`、阶段（`setup`/`planner`/`coding`）、已采集 metrics 和 workspace；不改变生产模型请求 timeout、不增加重试、不把删失样本计入成功率或 P50/P95。新增异步挂起与超时结果结构定向测试 `2 passed`。该能力只改善长尾回放的可观测终止，不等同于 R4.1 真实收益验收，也不提供中途 checkpoint/resume。

2026-09-20 首次 R4.1 真实回放使用同一冻结 payload、`deepseek-v4-flash-0731` 和 `medium`，在宿主 900 秒上限退出，未生成结果 JSON，未观察到工具调用或 provider usage。该样本只能记为首轮请求删失，`modelRequests`、`reasoningTokens`、`toolCalls` 均为 `unknown`；它没有进入视觉修复轮，不能评价 R4.1 收益，也不纳入 P50/P95。不得自动重试掩盖该长尾，后续先把首次写入请求与视觉修复请求分开重放或提供可恢复的首轮脚本快照。

为隔离修复轮，回放工具已增加 `--initial-script`：把已签发脚本复制到临时 Workspace，清除旧图片，保持默认未传参时删除脚本的原行为。两个文件准备用例先失败后通过，`test_replay_visualization_task.py` 全部 `11 passed`，Ruff 与 `git diff --check` 通过。历史 `compact-facts-3` 的 8 块 patch 已使用项目精确 patch 解析器反向应用，恢复脚本 SHA 为 `ae28295fe8d1e927708d12aa721a8240775222615a936bc811aa17da2321acc9`，与历史修复前 SHA 完全一致。

使用该脚本的聚焦回放仍在 900 秒上限退出，首个 `run_script` 未发生，结果 JSON 和 provider usage 均缺失。连续两次请求都没有 provider 响应，因此不能仅凭超时区分模型 reasoning 长尾、网关或网络状态；按“不增加重试”约束停止调用。R4.1 真实收益继续保持未验收；执行前健康探针成功后优先复用该聚焦命令，不再重跑完整脚本生成。

2026-09-21 在收紧 critical-only suggestions 投影后，复用同一 payload、seed SHA、模型和 `medium` effort 的单次聚焦回放再次以 `900.055s` 超时，结果为 `status=timed_out`、`phase=coding`、`censored=true`，`modelMetrics=[]`、`codingMetrics=[]`、`requestMetrics=[]`，未发生可观测工具调用。该样本仍为首个 Coding 响应删失，不能评价 R4.1、不能纳入 reasoning/成功率/P50/P95，也不增加重试；宿主侧 warning suggestion 泄漏修复已有定向回归，但真实收益验收继续阻断。

R4.1 的本地交付回归进一步补充了实际 Responses 请求历史断言：第一次 critical 审查同时带有独立 warning、summary 和 suggestion 哨兵，后续模型输入必须只保留 critical 描述；既有 AnyIO 端到端入口在当前环境超过观察窗口且不留下 pytest 进程，不能标记为通过。另增加了不依赖 Workspace/Kernel 的 `_project()` wire 投影测试，已验证 DELIVERY 序列化不包含三个非 critical 哨兵；端到端 function-call-output 加下一轮完整 Runner 的验收仍保持未完成，不以静态断言替代运行证据。

随后修复回放失败分支的指标选择：当 Coding 模型是 `ReplayObservedOpenAIChat` 或其浅复制时，优先读取 provider 边界的逐请求 sink；只有没有该观测时才回退到旧的 `code_run_request_metrics`。这不会改写上述已落盘的删失结果，也不改变生产请求或重试策略；Coding 超时回执和 Planner 超时回执组合 `2 passed`，确保后续 Coding wall-timeout 至少保留 `started` 状态。

回放成功结果现在也持久化同一 `requestMetrics` 字段，和失败结果使用相同的 provider-level 观测来源；没有该观测时保持空数组，不把缺失 usage 写成零。Coding-only 成功回归覆盖该字段，连同超时观测定向组合 `2 passed`。

2026-09-21 使用新增结构化 wall-timeout 再次执行同一聚焦回放：冻结 payload 校验通过，seed SHA 仍为 `ae28295fe8d1e927708d12aa721a8240775222615a936bc811aa17da2321acc9`；结果在 `900.045` 秒后以 `status=timed_out`、`code=report_replay_wall_timeout`、`phase=coding`、`censored=true` 落盘，`modelMetrics=[]`、`codingMetrics=[]`，且未发生工具调用。该样本严格记为首个 Coding 响应删失，不计入 reasoning、成功率或 P50/P95；它只证明复用修复前 seed 仍未消除首响应长尾，不能评价 critical-only 回执收益，也不能据此归因于模型、网关或 Agno。按单次调用、不盲目重试约束停止该侧真实调用。

后续补齐了取消路径的请求观测：实际 Coding Responses 模型在发请求前记录 `status=started`，回放超时时从该模型读取并写入 `requestMetrics`；指标归一化保留 `started`，未知 usage 仍为 `unknown`。超时集成用例验证了 JSON 中的开始记录。这不会补填上述旧样本，也不把删失样本纳入成功率或分位数。

随后一次复用同一脚本 SHA、payload、模型和 `medium` effort 的聚焦回放已观察到 provider 正常响应：首轮 `run_script` 成功，之后逐图 `view_image` 继续审查，并发现 critical `text_overlap` 后按压缩回执请求 `read_script` 和局部 `edit_script`。已观测请求包含 `reasoning_tokens=5007`、`11888`、`7482` 等值，说明本次确实进入了目标修复轮；但模型在进一步诊断时又插入了临时诊断 patch，宿主会话在生成结构化结果 JSON 前结束。该样本记为“进入修复轮但未闭环”的删失样本：不计入首次修复成功率、最终 critical 数量或 P50/P95，只证明 critical-only 回执路径和局部工具链已被真实触发。不得据此宣称 R4.1 已验收；后续应优先改进回放的可恢复终止和修复轮上限，而不是增加 provider 重试次数。

**通过条件：** 非阻断问题仍完整记录但不驱动 Coding 修改；critical 修复上下文准确且最小。相对现有 `263.177 秒 / 26,742 reasoning tokens / 8 个 patch 块` 样本，修复请求 reasoning 和无关 patch 范围下降，首次修复成功率与最终视觉质量不下降。一次正向样本只作为收益信号，不能据此宣称 P95 已稳定改善。

### R5：沿用现有单脚本身份契约（范围已收口）

章节只确定本次 Coding 的工作范围；分析与可视化各自执行，章内分析项仍保留 `analysisId`、证据归属和逐项验收，不强迫一次读完本章所有数据。2026-09-21 决定不考虑多脚本：不增加脚本规划、跨文件依赖、多个脚本目标或多脚本提交能力，R5 不再有待实施项。

现有 `ReportingCodingTaskContext.script_path` 是唯一源码目标，`ExecutionReceipt` 只有一个 `sourceFile`；工具由服务端绑定目标，提交前比较当前源码与输出 SHA。已有脚本继续只允许精准局部 patch。离线单脚本身份、精准编辑和交付边界已有 `51 passed` 的历史记录；这不作为 reasoning 收益证据。

### R6：以两类真实任务对照验收推理收益

**涉及文件：** R1 的回放脚本与指标模块；更新 `docs/superpowers/reports/2026-09-20-reporting-coding-performance-ab.md` 和 `docs/superpowers/reports/2026-09-20-reporting-coding-benchmark.md`。

- [x] 已冻结分析补证章节场景并完成 v2 输入身份校验；分析覆盖多数据集字段对应、期间比较、null 和分项总量对账，已有复杂 patch/混合工具用例继续作为协议回归。
- [x] 六图可视化章节的新 v2 冻结输入及绑定审核已完成，覆盖五个分析项、九份事实/evidence 文件。异常图包含四维贡献，旧版遗漏科室的输入废弃；详见 `docs/superpowers/reports/2026-09-22-visualization-freeze-and-repair.md`。
- [x] R6 公共执行和统计协议已落实：R4.1、R7.1、R7.2、缓存与 effort 分别登记自己的 baseline/candidate，单次实验只改变一个变量，不跨实验复用 A/B 名称。R7.1 的 baseline 已包含紧凑 `existingFacts`，只缺 `codingRequirements`；R7.2 的 baseline 已包含紧凑 visualization facts，只缺 `visualForm/dataBindings`。尚未取得的可视化样本由其独立复选框跟踪，不再把公共协议误标为未完成。
- [x] 分析 R7 high-effort A/B 已取得 3 组可比较样本；candidate 有性能收益但首次运行率下降，暂不推广。planner-medium 单变量诊断已完成且未显示累计收益；可视化待可信冻结输入后再对照，不同时改变模型或计划字段。
- [x] 分析对照固定 provider、模型、effort、summary 设置、数据身份及验收要求，并按 legacy/candidate 交替串行运行；可视化尚未满足同任务输入门禁，不执行伪对照。
- [x] 分析样本记录首轮至首次写入耗时、累计 reasoning tokens、请求次数、上游规划耗时、Coding 总耗时、修复耗时和质量；主指标为 `planner.reasoningTokens + coding.reasoningTokens`，缺失 usage 保持 `unknown`，不使用 completion/output tokens 或 `modelDurationMs` 推算。分析后置 `summary` 单列但计入端到端总墙钟。
- [ ] 可视化尚未取得可前瞻采集的 planner 与 Coding 阶段 receipt，因此不填补缺失 reasoning、不计算其累计指标。
- [x] 分析已按阶段和配置报告样本数、失败/终止数、P50/P95 及原始样本；P95 仅作当前小样本描述，未据此宣称稳定尾延迟改善。
- [ ] 可视化 revision-3 已取得 legacy 完整样本，candidate 协议失败，成功配对验收未完成；保留全部失败与删失记录，不美化总耗时。
- [x] 分析成功率同时按原始协议、首次 patch、首次运行、首次修复和最终交付统计；结果结构/证据身份正确，业务对账按软告警处理。candidate 因首次运行率下降未推广。
- [ ] 可视化单次已有脚本修复样本已取得首次 patch、首次运行、首次修复和最终六图结果；完整生成 A/B 的质量率仍缺样本，不能以该修复样本替代。

本地准备进展：回放脚本已支持 Coding-only v1 的 `--prepare-only`/`--validate-only`，并支持 planner + Coding v2 的显式 prepare/validate。prepare 只复制签发的 `authorized_read_paths`、规范化 payload 和可选初始脚本种子，并记录 SHA；validate 在模型构造前校验 payload、输入集合和文件身份。历史 analysis/visualization v1 bundle 仍只用于 Coding 输入身份回归；分析 v2 bundle `/tmp/reporting-r7-analysis-v2` 已按 planner 前章节输入生成并验证。可视化 v2 已完成可信输入冻结，当前静态对照位于 `/tmp/reporting-visualization-v2-Pfuhj1/revision-3/bundle`。

生产 Task receipt 已在保留原 `modelMetrics` 总量的同时增加 `modelMetricsByStage`，分开记录 `planner`、`coding` 和分析后置 `summary`；任一实际请求 usage 缺失或只有 Agno 默认全零指标时，该阶段 token 保持 `unknown`。这补齐了 R7.3 的观测前提；分析 3 组 provider 样本已据此分阶段落盘，但 candidate 因首次运行率下降仍不能推广。

历史 visualization A 的 trace 已按 agent span 的直属模型子 span 精确归属，避免混入 13 次视觉 reviewer：planner 直属模型调用 `1` 次、模型耗时约 `60,787 ms`；Coding 直属模型调用 `19` 次、模型耗时合计约 `784,415 ms`。全部请求状态为 `OK`，但 trace 只完整持久化 prompt/completion/total；planner 与 Coding 均没有 reasoning 字段，cache read 也有请求缺失，严格口径均为 `unknown`。不能用 completion tokens 反推 reasoning，也不能把缺失 cache 记为 `0`。两个历史 bundle 只冻结 Coding 阶段输入，没有执行上游 planner。因此它们可用于输入身份、协议和 Coding 回放，但不能作为 R7.3“planner + Coding 累计 reasoning”的严格 A/B 基线。

历史 analysis A 也只能部分恢复：evidence planner 的 5 次模型调用共 `6,357` reasoning tokens，后置 summary 的 5 次调用共 `13,926`；analysis Coding 的 4 个 agent span 共 26 次 Responses 调用，但对应 Agno run 没有持久化 Coding metrics/reasoning。顶层 `run-coding-analysis` 的 `134,405` reasoning tokens 混合了其他阶段，不能拆给 Coding；其 prompt/completion/cache 或模型耗时同样不能推算 reasoning。因此历史 analysis trace 只能用于 planner/summary 和请求树边界校验。严格的 planner + Coding A/B 必须以前瞻采集为准；前置验收应以阶段 receipt 能完整保存 Coding usage 为准，Agno trace 缺失只降低历史可追溯性，不单独触发生产架构改动。

**通过条件：** 在可比较样本中，累计 reasoning 和规划加 Coding 的总耗时有一致改善，质量指标不下降。若只有输入 token 或首轮等待减少，标为局部收益而非总目标完成。阶段策略可不同，不要求分析与可视化使用同一拆分方式。

### R7：按章节冻结必要实现决策，再评估缓存与 reasoning 档位

**目的：** 当前长尾主要发生在 Coding 首次写入前。R7 不增加 planner，不建设通用分析或图表 DSL，只把现有 planner 已经做出的必要决策以可校验字段传给 Coding，避免 Coding 再做一遍数据选择、计算设计和图表设计。任务范围仍按章节确定；分析 Coding 与可视化 Coding 分开运行，沿用每个 Coding task 的现有单脚本契约。

**涉及文件：**

- 分析决策与投影：`smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`、`smart_reporting/reporting/workflow/runtime/base.py`。
- 可视化计划与校验：`smart_reporting/reporting/workflow/runtime/phase_models.py`、`smart_reporting/reporting/workflow/runtime/analysis.py`、`smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`。
- 结构化生成器指令：`smart_reporting/reporting/agent.py`、`smart_reporting/reporting/instructions.py`。
- 测试：`smart_reporting/reporting/tests/test_reporting_phase_models.py`、`smart_reporting/reporting/tests/test_reporting_planner_contracts.py`、`smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`、`smart_reporting/reporting/tests/test_visualization_read_paths.py`。
- 性能验收：`scripts/replay_visualization_task.py`、`smart_reporting/reporting/tests/test_reporting_code_reasoning_replay.py`、`smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py` 和 R6 报告。

#### R7.1：分析 Coding 直接接收已决定的计算要求

**契约：** 保留 `AnalysisEvidenceDecision.missingFacts` 供解释和审计；仅在 `requiresSupplementalEvidence=true` 时增加结构化 `codingRequirements`。每项只描述当前缺口所需的 `datasetId`、`fields`、`calculation` 和 `outputName`，不包含 Python、SQL 或脚本路径。`datasetId` 必须来自当前分析项授权数据集，`fields` 必须是该数据集已声明字段的非空子集；业务公式无法确定时不得编造，继续以明确缺口失败或软告警处理。

- [x] 先在 `test_reporting_fixed_phase_workflows.py` 写失败用例：合法 requirement 可进入 `_script_task_facts()`；未知 dataset、跨数据集字段、当前分析项未授权 dataset、空字段、重复 outputName 和 `requiresSupplementalEvidence=false` 却携带 requirement 均被拒绝。
- [x] 在 `analysis_item_workflow.py` 为现有 decision 增加最小结构化 requirement，并在 decision 产出后、启动 Coding 前用当前 `currentAnalysis.datasetIds` 与 `datasets[].columns` 做交叉校验。没有从 `missingFacts` 文本解析字段或计算，也没有增加第二次决策调用。
- [x] evidence planner 请求增加现有签发 `datasets` 投影，使模型可以逐字选择 datasetId 和 fields；`_script_task_facts()` 只向 Coding 投影顶层 `codingRequirements`、紧凑 `existingFacts`、授权 datasets 和唯一 `outputContract`，不回放 decision 的 reason/missingFacts 叙述。
- [x] 更新 `base.py` 的 planner 与 Coding 指令：planner 必须声明 `codingRequirements`；Coding 直接实现这些要求，不得重新选择数据集、字段或计算目标，局部变量和具体 Python 写法仍由 Coding 决定。
- [x] 定向验证：R7.1 新契约节点 `8 passed`，分析诊断相关节点 `3 passed`，`test_reporting_v1_workflows.py` `13 passed`；目标文件 Ruff、compileall 和 `git diff --check` 通过。大型混合 AnyIO 组合在已有卡点无新增输出后停止，未用其替代定向证据。

R7.1 的结构契约与定向测试已完成。3 组 high-effort 对照显示 candidate Coding reasoning 下降，但 planner reasoning 上升，累计 reasoning 仍有描述性收益；由于首次运行率从 `3/3` 降至 `2/3`，该字段扩展未通过推广门槛。生产默认已回退为 legacy evidence planner/schema/Coding projection，不再要求 `codingRequirements`；candidate schema、指令、交叉校验和 Coding projection 只保留在显式 benchmark `variant=candidate` 路径，供后续同任务实验使用。planner 增量更可能来自 `codingRequirements` 的语义拆解，不能归因于输入长度。

- [x] 分析 Coding 共用指令已明确“只执行上游签发的事实缺口和计算要求”，禁止重新规划、重新选择字段或为了验证假设读取未签发数据；新增 benchmark 指令契约测试，减少分析项 Coding 首轮的重复推理空间。该提示收敛不等同于 provider reasoning 硬上限，仍需真实分析回放验证累计收益。
- [x] 新指令后的同 bundle legacy/high 单样本已通过：总耗时 `182.748s`，planner `647`、Coding `12,341`、累计 `12,988` reasoning tokens；首次写入为第 4 次请求，`74.688s / 6,223 tokens`，首次运行成功。前三轮探索请求合计约 `86.55s / 6,093 reasoning tokens`，仍与写入阶段相当，因此单纯追加“不重复规划”提示没有消除探索往返，不能宣称 reasoning 已改善。该样本的逐请求快照确认 `summary=auto`、顶层 `enable_thinking=true`、`max_output_tokens=65536`、`parallel_tool_calls=true` 均实际进入请求。

- [x] 按质量门槛回退分析生产默认：`_analysis_evidence_agent` 使用 `LegacyAnalysisEvidenceDecision` 和 legacy 指令，生产 `_script_task_facts()` 默认只投影 `evidenceDecision.missingFacts`；显式 candidate benchmark 仍投影已校验的 `codingRequirements`。受影响组合回归 `124 passed`，Ruff 与 compileall 通过。

#### R7.2：可视化 Coding 直接接收图型意图和受信数据绑定

**契约：** `ChartDraft` 只增加 `visualForm` 和 `dataBindings`。`visualForm` 是简短图型描述，不规定配色、尺寸、标注位置或具体绘图库 API。每个 binding 仅含 `analysisId`、`factPath`、`dataPath`、`fields` 和 `role`，必须逐字引用本轮 `visualizationFacts` 已存在的 descriptor；不得由 planner 自由生成文件路径或 JSON 路径。所有可绑定 descriptor 必须显式声明自己的字段集合，宿主不得根据路径名称或事实内容猜测字段。

- [x] 先在 `test_reporting_phase_models.py` 写 schema 失败用例，要求每张图具有非空 `visualForm` 和至少一个 binding；拒绝空字段和重复 binding；未知 descriptor 字段由 Coding 前的确定性交叉校验拒绝。保持 renderer、输出路径、标题、期间、citation、metric 和 comparability 的现有行为。
- [x] 确认现有可视化规划请求携带完整 facts descriptors。由 `analysis.py` 的确定性投影为 metric、derivedMetric、comparison 和 supplemental finding 的每个可绑定 `dataPath` 明确列出 `fields`；生成器指令只能从 descriptor 复制 `analysisId`、事实文件 path、`dataPath` 和 `fields`，不能猜测。
- [x] 在 `visualization_section_workflow.py` 增加纯确定性交叉校验：`factPath` 必须等于当前分析项 `factFile.path` 或其 `supplementalEvidenceSources[].sourceFile.path`；`dataPath` 必须等于对应 descriptor 声明的路径；`fields` 必须是该 descriptor 显式 `fields` 的非空子集；任何不匹配在 Coding 启动前以契约错误拒绝。
- [x] 在 `analysis.py` 保证 `visualization_coding_facts()` 保留 binding 所引用的 descriptor 和文件身份，但不重新加入 summary、warnings、规划叙述或未引用的完整事实数据。计划和 Coding facts 使用相同受信来源，避免模型按标题二次定位；提交注册时剥离 `visualForm` 和 `dataBindings`，不扩展严格交付契约。
- [x] 更新可视化 Coding 指令：逐图实现 `visualForm` 和 `dataBindings`；Coding 仍自行决定布局细节和函数组织，沿用宿主签发的单脚本身份契约。不得把 `role` 扩展成通用 Vega/Plotly DSL。
- [x] 定向验证：phase schema、读取路径、渲染注册、V1 workflow 和 repair knowledge 合计 `84 passed`；无效 binding 与生成器指令节点 `5 passed`；目标文件 Ruff、compileall 和 `git diff --check` 通过。

R7.2 的结构契约与定向测试已完成，但这只证明 Coding 收到现有 planner 已决定的图型意图和受信数据定位，不能证明 reasoning 已下降。下一次受控真实回放必须按 R7.3 比较 visualization planner、首次写入和后续修复的累计 reasoning；若累计 reasoning 或总耗时没有下降，回退这些新增规划字段，不以 Coding 单阶段 token 下降作为保留依据。

#### R7.3：先验收累计 reasoning，再调整缓存和 effort

- [x] 已完成 schema、确定性交叉校验、分阶段 usage 观测、Coding-only v1 可携带 bundle、planner+Coding v2 bundle 契约/校验器和定向测试；已从真实 planner 前章节输入确定性提取并验证分析 v2 bundle `/tmp/reporting-r7-analysis-v2`。此前两个 900 秒删失样本仍不计入 P50/P95；可视化 v2 bundle 仍因缺少可信 `dataDescriptors` 和审核过的 `visualForm/dataBindings` 而阻断。
- [x] 已增加受签名的 analysis Coding-only 联结入口：同时校验 v1/v2 bundle、基础 facts 与授权输入 SHA，复用 v2 modelConfig 和 legacy Coding 指令，结果明确标记 `benchmarkMode=coding-only` 且不伪造 planner metrics。新范围收敛后的单次真实 Coding-only 回放未在观察窗口内产生结果 JSON/usage，记为删失样本，不计入 reasoning 或成功率；不能把该次等待归因于 provider、Agno 或工具范围。
- [x] 分析已从 planner 前的同一冻结章节输入建立 legacy/candidate A/B，固定模型、`reasoning.effort`、`reasoning.summary`、`enable_thinking` 投影、facts 身份、单脚本身份和验收条件；A/B 在 planner 构造前分叉，未从 candidate 输出事后删除字段伪造 legacy。
- [ ] 可视化 revision-3 两侧已通过规划路径门禁，但 candidate 在修复后收到非法工具调用而失败，仍缺成功两阶段配对；协议拒绝请求的 usage 缺失不填 0，不拼接其他修复样本。
- [x] 分析 Coding agent 的 Responses usage 已按本次 Coding invocation 写入阶段 recorder/receipt；Agno trace 父级只作为附加诊断。缺失 usage 保持 `unknown`，未用顶层混合 metrics 回填。
- [x] 分析样本记录 planner reasoning、Coding 首次写入 reasoning、修复 reasoning、累计 reasoning、总耗时和质量；主指标严格为 `planner.reasoningTokens + coding.reasoningTokens`，分析后置 `summary` 单列并计入任务墙钟。candidate 虽有累计下降，但首次运行率退化，因此不保留为生产默认。
- [ ] 可视化尚未有可配对的 planner + Coding 阶段 receipt；不得使用历史 trace 的 completion 或模型耗时补填 reasoning。
- [ ] 计划字段收益确认后，再保持 payload 不变评估稳定前缀缓存。公共 instructions、工具声明和 schema 保持确定性，动态章节身份放在请求后部；只按 provider 的 `cached_tokens` 报告缓存收益，不扩大 prompt 凑缓存。
- [x] 已对 planner 长推理单独比较 provider 明确支持的 effort 档位；Coding effort、payload、schema、验收保持不变，首轮 reasoning 保持开启并保留 `reasoning.summary`。未添加 Responses 不支持的 `thinking_budget`，未使用输出 token 截断、超时或重试伪装改善。planner-medium 诊断未显示累计收益，不推广该配置。

**当前下一步：** 分析 high-effort legacy/candidate 已完成 3 组串行对照；candidate 有累计 reasoning 与总耗时收益，但首次运行率下降，已经从生产默认回退为显式 benchmark 实验。planner-medium 单变量诊断已完成，Coding 始终保持 `high`；该配置的累计 reasoning 与总耗时 P50 均未改善，因此不推广。单脚本身份边界已完成离线审计，后续不开展多脚本改造。可视化新冻结输入已审核，下一步定位 planner 输出路径漂移并取得完整配对样本，不扩展授权或自动修改路径。真实 provider 对照继续串行，子 agent 只并行做不共享 provider 配额的测试、trace 和计划审计。

**并行实施边界：** 分析链路审计、可视化链路审计、阶段指标测试和计划一致性审查可以同时进行，因为它们不共享 provider 请求、冻结 workspace 或可变输出。真实 `legacy/candidate` 请求必须按分析/可视化分别串行，并交替运行以降低缓存和服务负载偏差。每次 Responses 请求固定 `parallel_tool_calls=True`，允许 provider 在单次响应中最大化返回结构化工具调用；宿主不得把返回批次截成一个调用、设置人为调用上限或因多调用直接重试。宿主先整体校验，再按 provider 返回顺序逐个委托；前序失败或提交后停止实际执行，并按原调用 ID 补齐未执行回执。只有独立只读调用经过契约证明后，才允许调度层并行，不能改变有状态链路的顺序。

**同时推进的工作波次：**

1. **波次 A（可并行、无 provider 请求）：** 分析失败遥测审计、可视化 v2 输入审计、指标/receipt 接线审计、计划与测试契约审查同时进行。各任务只能读取自己的证据和测试输出，不修改同一生产文件或共享冻结 workspace。
2. **波次 B（可并行、离线验证）：** 分别验证分析章节与可视化章节的 schema、facts projection、脚本身份和 `parallel_tool_calls=True` 批次回放；分析与可视化仍使用不同的 planner/Coding 契约，不合并成一次模型调用。
3. **波次 C（共享 provider 配额，必须串行）：** 健康探针通过后，分析 legacy/candidate 交替串行；可视化只有在获得可信 `dataDescriptors`、逐图 acceptance 和 v2 bundle 后才串行执行。任何一侧 usage 缺失、输入身份不一致或质量门槛失败，都停止该侧推广，不用另一侧结果填补。
4. **波次 D（条件项）：** 只有 R6/R7 证明 CodeMode 开销显著，才按 C1–C4 的各自门禁推进；不得与真实 A/B 同时改变工具桥接、缓存或 effort。R5 多脚本改造已退出范围。

**执行门禁顺序：**

1. 先完成 benchmark-only variant 选择和离线契约测试；失败时不调用 provider。
2. 再确认分析、可视化两条路径的阶段 receipt 都能保存 Coding usage；任一阶段缺失时只保留协议/质量结果。
3. 健康探针成功后，按分析、可视化分别串行执行 legacy/candidate；不复用另一类任务的结果。
4. 只有 planner + Coding reasoning 可观测且质量不退化，才推广计划字段、缓存或 effort；若质量门槛未过，只允许为定位长尾做严格单变量诊断。
5. CodeMode C1–C4 不得提前改变主线；除非测量证明执行开销显著，否则保持未实施。

**R7.3 variant 责任矩阵：**

| 层次 | `legacy` | `candidate` | 禁止做法 |
| --- | --- | --- | --- |
| planner schema/instructions | R7 新字段之前的 legacy schema 与指令；分析生产默认当前也使用该契约 | 实验性 `AnalysisEvidenceDecision`/`ChartDraft` 及新增指令 | candidate 返回后删除字段伪造 legacy |
| Coding facts projection | 保留 R3 紧凑既有事实，不投影 R7 新字段 | 在相同既有事实基础上增加 `codingRequirements` 或 `visualForm/dataBindings` | 用标题、路径或模型猜测绑定 |
| 宿主校验与交付 | 使用同一文件身份、SHA、工具协议和输出验收 | 使用同一文件身份、SHA、工具协议和输出验收 | 为 legacy 放宽 strict schema、patch 或路径校验 |
| 指标归属 | 同样记录 planner、coding、summary 和 unknown | 同样记录 planner、coding、summary 和 unknown | 用总任务 metrics、completion 或耗时补齐缺失 reasoning |

**R7.3 执行拆分：**

**可提交批次：**

1. **批次 A：variant 选择与投影。** 只修改 benchmark 入口、两套 schema/adapter 和两类 facts projection；strict schema 与工具协议不变。验收是离线快照能证明 legacy/candidate 在 planner 构造前分叉，且既有文件身份与脚本路径完全相同。该批次完成时未改变生产默认；后续因 candidate 质量门槛失败，生产分析默认已另行回退为 legacy。
2. **批次 B：阶段 receipt 归属。** 只修改 settlement/recorder 接线和契约测试；不改变 planner 输出字段或 Coding 指令。验收是 planner、coding、summary 分区可回放，缺失 usage 为 `unknown`，不读取顶层混合 metrics 回填。
3. **批次 C：真实对照。** 只使用已通过 A/B 的入口和冻结输入，串行执行分析与可视化各自的 legacy/candidate；不在该批次修改 schema、提示词、effort 或缓存。验收是保存原始 receipt、请求参数、失败轨迹和质量结果，并按主指标计算累计 reasoning。

**批次 A 的最小接口契约：**

```python
@dataclass(frozen=True, slots=True)
class BenchmarkPlannerSpec:
    task_kind: Literal["analysis", "visualization"]
    variant: BenchmarkVariant
    output_schema: type[BaseModel]
    instructions: tuple[str, ...]
    project_coding_facts: Callable[[Mapping[str, Any]], Mapping[str, Any]]
```

- `build_benchmark_planner_spec(...)` 必须在创建 planner Agent、结构化 executor 或发送首个请求之前调用；调用时显式传入两套 `output_schema`、两套 `instructions` 和两套 `project_coding_facts`，不得在函数内部从 candidate schema 裁剪 legacy。
- `legacy` 的 `output_schema` 和 `instructions` 必须是不含 R7 新字段的 benchmark-only 契约；不得复用 candidate schema 后在响应返回后删除字段。
- `candidate` 使用显式实验 schema 和新增 R7 指令；两种变体的 `model`、`reasoning.effort`、`reasoning.summary`、`enable_thinking`、`parallel_tool_calls=True`、授权文件身份、脚本路径和验收契约必须相同。
- `project_coding_facts` 只能改变 R7 新字段；不得改变 `analysisId`、dataset/fact 文件 SHA、输出路径、工具协议或 patch 校验。
- planner 失败、schema 校验失败或 provider usage 缺失时，benchmark 入口必须返回结构化失败/`unknown`，不得回退到另一变体，也不得调用第二个 planner 伪造对照。

该接口只属于冻结 benchmark harness，不作为生产 runtime 的常驻 feature flag；当前已有 Coding-only bundle 不能直接传入该接口冒充 planner+Coding 基准。

- [x] 已新增 benchmark-only variant/schema/adapter 契约、version 2 冻结 planner+Coding bundle 校验和执行 harness；该结果只证明入口已接线，不代表真实 A/B 已执行。
- [x] 分析 `_script_task_facts()` 已增加可选 benchmark projection；legacy 不投影 R7 `codingRequirements`、保留 R3 `existingFacts`，candidate 保留 `codingRequirements`。质量门槛失败后，默认生产调用已切回 legacy 行为。
- [x] 分析固定 workflow 已增加可选 `benchmark_projection` 传递到 Coding facts；冻结入口会在 planner 构造前选择 legacy/candidate，并将对应 planner 输出投影给现有 Coding runner。
- [x] 可视化已增加可选 `visualization_coding_plan()` projection；legacy 会隐藏 R7 `visualForm/dataBindings`，candidate 保留完整计划，宿主内部仍执行当前 `ChartDraft` strict 校验。
- [x] 可视化固定 workflow 已增加可选 `benchmark_projection` 到 Coding facts 的传递；冻结入口会先运行对应 planner，再将投影结果交给现有 Coding runner。
- [x] `_ReportWorkflowRuntimeBase._benchmark_planning_agent()` 已提供 benchmark-only 的 planner 构造入口，使用 `BenchmarkPlannerSpec` 在首次请求前选择 schema/instructions；生产初始化不调用该入口。

- [x] 冻结基准 CLI 已增加 `--benchmark-bundle DIR --variant legacy|candidate`；variant 只作用于 benchmark invocation，并在 planner 构造前选择 output schema、planner instructions 和 Coding facts 投影。legacy 保留 R3 已验证的紧凑 `existingFacts`/紧凑 visualization facts，不从 candidate planner 输出事后删字段。benchmark variant 不改变生产配置；生产分析默认的后续回退由质量门槛单独决定。
- [x] 已定义 version 2 冻结 bundle：同一份 manifest 固定 planner request、execution context、acceptance、全部输入文件 SHA，以及 Coding Responses 的 model/effort/summary/enable_thinking/max_output_tokens/`parallel_tool_calls=True`/`tool_choice=auto`；不记录、不接受 `thinking_budget`。planner 若使用 Agno Chat 路径，只投影其实际支持的字段，不把 Coding Responses 的 summary 伪装成 Chat 参数。variant 不得写入 bundle，必须由运行命令外部选择。篡改输入或内嵌 variant 会在创建模型前失败。
- [x] 已增加 `prepare_frozen_planner_coding_bundle()`：显式消费 planner request、variant-neutral Coding payload、acceptance 和模型快照，复制并哈希全部授权输入，将 `workspace_root` 固定为 bundle 内的 `workspace`，写完后调用同一 validator 回读。基础 facts 若已含 `evidenceDecision`、`codingRequirements` 或 `visualizationPlan` 会提前拒绝。
- [x] 已修复 benchmark 模型装配阻断：不再向 Agno 3.0.9 `OpenAIChat` 传入其不支持的 `reasoning` 对象；冻结的 `reasoning.summary` 显式传给 Coding Responses 模型，planner Chat 只使用其支持的投影。`maxOutputTokens=null` 保持省略而不回退环境上限。`toolChoice` 仅允许 `auto`、`parallelToolCalls` 仅允许 `true`；thinking 位置与 provider 不一致或开关与 effort 不一致时在请求前拒绝，`thinking_budget` 一律拒绝。
- [x] replay CLI 已增加显式文件 version 2 prepare：`--planner-request` 必须同时提供 `--coding-payload`、`--acceptance`、`--model-config` 和 `--prepare-benchmark`；该路径不加载环境模型设置、不创建模型、不调用 provider。现有 `--prepare-only` 仍只生成 Coding-only v1 bundle，二者不混用。
- [x] 已增加历史 trace 自动配对入口：`--trace-id --trace-identity --extract-benchmark` 从 Agno agent spans 按分析 `analysisId` 或可视化 `sectionCode` 配对 planner/Coding；分析要求 planner 含 `datasets`，可视化要求 `dataDescriptors`，并按图表输出路径唯一匹配 Coding。配对后只移除已验证的 planner 产物字段，不调用 provider。
- [x] trace 提取明确拒绝不可重放历史输入：可视化 planner 缺少 `dataDescriptors` 或缺少结构化输出直接失败；可视化 acceptance 仍由调用方显式提供，不能从旧 planner 输出猜造 `visualForm/dataBindings`。分析 planner 缺少 `datasets` 时，只有同 trace 的 planner/Coding `currentAnalysis` 完全一致、补证决策经 legacy schema 归一化后完全一致、Coding datasets 非空且路径唯一、路径集合与 `authorized_read_paths` 完全一致时，才允许确定性投影，并记录 planner/Coding span provenance。
- [x] 分析 benchmark planner 返回 `requiresSupplementalEvidence=false` 时在 planner→Coding 投影前硬失败，禁止启动不必要的补证 Coding 阶段；legacy/candidate 两套 schema 均覆盖该门禁。
- [x] 已创建并接入 legacy planner schema：分析模型不含 `codingRequirements`，在 candidate 质量门槛失败后恢复为生产默认；可视化旧计划外壳不含 `visualForm/dataBindings`，仍只由冻结 benchmark 入口使用，不能直接替代生产可视化 strict 模型。
- [x] 可视化旧计划已从宽泛字典收紧为 `LegacyChartDraft`：保留 R7 前的图表身份、路径、renderer、指标、期间、数据集和粒度字段，并继续校验安全输出路径、Plotly 配套产物、比较期间及唯一图表身份；仅缺少 R7 的 `visualForm/dataBindings`。
- [x] benchmark projection 是宿主控制参数，已从模型 facts 分离并在初次生成、生成重试和提交后修复中保持同一 variant；legacy 不会因修复轮意外转入 candidate 的 binding 裁剪，也不会把不可 JSON 序列化的控制对象送进 prompt。trace 的完整任务身份与模型可见最小 task 分离，冻结 bundle 提取时核对并恢复宿主身份。此项只修复对照有效性，不作为真实 A/B 收益证据。
- [x] 结构化 generator 已复用相同的可视化共同指令；legacy 与 candidate 都约束输出根路径、`sourceDatasetId`、renderer 和 Plotly 配套产物，只有 candidate 增加 `visualForm/dataBindings` 指令。离线测试逐项断言该差异。
- [x] 可视化章节执行入口已支持 benchmark harness 显式注入旧 planner、旧 output type 和确定性 adapter；legacy projection 缺少任一项时会在 provider 请求前硬失败。adapter 返回值仍必须是当前 `VisualizationPlanDraft`，随后执行既有完整 binding 校验。
- [x] 已完成并接入 legacy schema 到当前 workflow 内部对象的显式 adapter：分析保留旧 planner 缺口语义且不伪造 `codingRequirements`；可视化用冻结的逐 chart 验收决策补齐内部 strict 对象，随后执行原完整 binding 校验，并在 legacy Coding 投影前再次移除 `visualForm/dataBindings`。
- [x] 分析固定 workflow 支持 `LegacyAnalysisEvidenceDecision` 作为生产默认及 legacy benchmark 决策输入，在 Coding facts 中保留缺口语义、明确不生成伪造 `codingRequirements`；可视化使用独立的旧计划 adapter，二者不共享一次模型结果。
- [x] 分析执行入口已支持 benchmark harness 显式注入 `evidence_planner` 与 `evidence_output_type`；legacy benchmark projection 若未同时提供匹配 planner 和 `LegacyAnalysisEvidenceDecision`，会在任何 provider 请求前硬失败。生产初始化当前直接构造 legacy evidence planner；显式 candidate benchmark 注入 candidate planner/schema。
- [x] 已完成分析路径 `base.py`、`analysis_item_workflow.py`、`analysis.py` 与可视化路径 `agent.py`、`bootstrap.py`、`visualization_section_workflow.py`、`analysis.py` 的最小传递链；分析与可视化分别构造 planner、分别验证，不共享 variant 结果或合并模型调用。legacy/candidate 的 Coding instructions 也已分开，只有共同约束复用。
- [x] 在 `smart_reporting/reporting/workflow/execution.py` 的阶段 settlement 增加请求级 stage/agent 归属记录：Coding runner 将本轮新增的请求指标交给 settlement，按 `requestIndex + providerRequestId` 去重后写入阶段 receipt；索引、provider ID、耗时和状态均做有界规范化，缺失 usage 保留 `unknown`，不从 `agno_runs` 顶层混合指标回填。定向指标回归 `26 passed`。
- [x] Coding Responses 的每请求 metrics 已保留 provider 返回的 response id（失败或 provider 未暴露时为 `unknown`），进入 `modelRequestMetrics[].providerRequestId`，并持久化到 `modelMetricsByStage.<stage>.requestMetrics[]`；该列表只含请求索引、provider ID、耗时和状态，不包含 prompt、密钥或完整响应。
- [x] Task receipt 已增加严格派生字段 `plannerCodingReasoningTokens`：仅当 planner、coding 两阶段 `reasoningTokens` 都是可观测非负整数时求和，任一缺失即为 `unknown`；summary 保持在 `modelMetricsByStage.summary` 单列，不计入该字段。
- [x] 生产阶段 recorder 已绑定稳定 `agentRole`：分析 evidence planner/Coding/summary 与可视化 planner/Coding 分开归属；同一 stage 混入不同 role 会在结算前硬失败。阶段仍保留 Agno run 聚合指标，同时 Coding 请求级 provider ID 已通过 `requestMetrics` 持久化；真实 provider A/B 的端到端覆盖仍由下一项负责。
- [x] 已新增 `smart_reporting/reporting/tests/test_reporting_benchmark_variants.py` 定向契约测试：A/B 的模型、effort、summary、enable_thinking、parallel_tool_calls、输入文件 SHA、单脚本身份和验收条件相同；只允许 schema/instructions/Coding projection 三项变化。测试失败时不得调用 provider。
- [x] 分析已在契约测试和健康探针通过后串行运行 legacy/candidate；原始请求、阶段 receipt、失败/终止信息和质量结果均落盘。缺失 reasoning 的样本只作协议/质量回归，不进入累计比较。2026-09-21 健康探针在关闭控制改为 `reasoning.effort=none` 后整体 `passed=true`；分析 high-effort A/B 已完成 3 组。
- [ ] 可视化输入门禁已通过并尝试真实对照；两侧均在 planner 输出路径与授权集合不一致处停止，完整 A/B 未完成。不猜造字段，不修正模型路径来绕过门禁。

**R7.3 定向验证命令：**

```bash
.venv/bin/python -m pytest -q \
  smart_reporting/reporting/tests/test_replay_visualization_task.py \
  smart_reporting/reporting/tests/test_reporting_benchmark_variants.py \
  smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py
```

该命令只验证 variant 契约和阶段 receipt，不调用 provider；真实 A/B 命令必须在上述测试通过且健康探针成功后单独执行。

2026-09-21 已运行包含 replay CLI 的组合定向命令，最新结果 `82 passed`。该证据覆盖 variant/schema/adapter、version 2 prepare/validate、显式文件和历史 trace 提取入口、冻结模型参数装配、planner→Coding harness、CLI 参数约束、阶段分区、agentRole 冲突拒绝、累计 reasoning 的 `unknown` 传播和 summary 分离；请求级 provider ID 的本地 settlement 持久化另由指标模块 `25 passed` 覆盖，尚未覆盖真实 provider A/B 的端到端落盘。

**本轮验证记录（2026-09-21）：**

- [x] 按最新范围决定收口 R5：沿用每个 Coding task 一份正式脚本的现有宿主契约，不再规划、实现或验收多脚本能力；相关实施波次、发布门槛和最终验收已移除多脚本依赖，章节任务范围与分析/可视化分阶段原则不变。
- [x] 统一审查修复冻结基准的四个可信度缺口：分析 trace 现在要求已有 planner datasets 与 Coding facts 逐项一致且都存在；可视化 trace 配对同时包含静态 `sourcePath` 和 Plotly `interactivePath`；可视化 candidate replay 复用生产 `visualization_coding_facts(..., plan=plan)` 按绑定裁剪 descriptors；从生产 candidate trace 提取 bundle 时，先校验历史 Coding facts 精确等于 planner facts 的 candidate 投影，再把同一 planner facts 的紧凑全量投影保存为 variant-neutral 基础，避免 legacy 继承 candidate 已删除的 descriptors。
- [x] planner 已在最终 `OpenAIChat.ainvoke` provider 调用边界记录逐请求状态，并由浅复制模型共享同一指标 sink：发出前记 `started`，正常响应结算 `completed`，普通异常结算 `failed`，wall-timeout 取消保留 `started`；每条记录独立保存请求序号、provider request ID、耗时和 input/output/reasoning/cache usage，缺失值保持 `unknown`。完整 benchmark 的成功、Coding 失败和 planner 外层失败结果均通过独立 `plannerRequestMetrics` 字段持久化，不与聚合 `plannerMetrics` 或 Coding `requestMetrics` 混淆，不增加重试。provider 边界取消、完成/失败及 planner timeout JSON 接线定向组合 `5 passed`。
- [x] 生产 workflow 的 `_run_planner()` 已接入 Chat 模型调用观测：每次调用的 `started/completed/failed`、响应 ID、耗时、input/output/reasoning/cache usage 和脱敏请求参数写入 `session_state["planner_request_metrics"]`，最多保留最近 128 条。started 在调用期间即可见，取消保留 started 并标记删失，缺失 usage 保持 unknown；只有实际 wire 参数包含 summary 才认为已发送。这里计时覆盖 Agno `aresponse`，不是独立 HTTP 网络耗时；session 内存更新不保证进程强杀前落库。定向测试 `5 passed`，正确提交的真实 CLI 已验证 planner 输出与 step 请求计数。
- [x] 本轮修复后的分析数据身份、可视化 neutral/candidate facts、Plotly 双产物、正常/失败 planner 指标、Coding started、trace metadata 和修复投影边界定向组合 `15 passed`；目标 Ruff 与 `git diff --check` 通过。未调用 provider，未运行完整测试或完整报表。
- [x] planner-medium 诊断后补齐独立 planner effort 的配置门禁和失败耗时观测：planner/Coding 不得在共享 `enable_thinking` 下跨越 `none` 边界；planner 异常样本也会保存 `durationMs` 和失败状态。replay、benchmark variant、Coding metrics、delivery 四个受影响测试文件组合回归 `124 passed`；目标文件 Ruff、compileall、bundle validate 和 `git diff --check` 通过。
- [x] 首次 `run_script` 失败新增一次性有界 `firstRunFailure` 快照：保留错误码、异常类型、路径、行号、退出码、失败时源码 SHA 和诊断字节数；后续修复不会覆盖，完整 traceback、源码和 patch 不进入长期指标。旧回放未保存这些字段时保持 `unknown`，不从最终脚本、最终 SHA 或后续成功结果反推。受影响回归最新为 `125 passed`。
- [x] Coding 指标汇总新增 `firstRunFailureCodes` 有界错误码计数，仅统计显式错误码，不把缺失或 `unknown` 当作失败；受影响组合回归最新为 `126 passed`。
- [x] 回退生产分析默认后，指标与交付门禁组合回归 `55 passed`；首次失败快照、后续修复保留、输出提交校验和指标 unknown 语义均保持通过。Ruff 通过，仅有第三方 `imghdr` 弃用警告。
- [x] 目标文件 Ruff 检查通过，`git diff --check` 通过。
- [x] replay CLI、benchmark variant 和阶段指标组合测试最新通过：`82 passed`；另一次聚焦筛选结果为 `41 passed, 66 deselected`。该结果证明冻结章节入口、version 2 prepare/validate、历史 trace 提取、无需 Coding 的 planner 门禁、请求级 provider id 诊断和 planner→Coding harness 已接线，但不证明真实 provider A/B 的 reasoning 收益。
- [x] 已对历史 trace `a4c8f0e11484a4bf5defca69610f0506` 完成分析 v2 bundle 确定性提取：planner span `24e28bc27c229ed8` 与 Coding span `7d183474d73e92c6` 的分析身份和补证决策一致，两个 dataset 路径、size、SHA 与授权输入及 bundle 实际文件一致。bundle `/tmp/reporting-r7-analysis-v2` 已通过 `--validate-only`。可视化仍因旧 planner 缺少 `dataDescriptors` 而拒绝。
- [x] 多工具批次、轨迹回放、阶段指标和 Coding 输入契约通过：`102 passed`；其中 `parallel_tool_calls=True` 的 provider 多调用回放仍由宿主按返回顺序执行，未放宽前序失败/提交后停止规则。
- [x] 分析项 high-effort 真实 provider A/B 已基于同一 v2 bundle 串行完成 3 组。描述性 P50/P95：总耗时 legacy `167.509/194.534s`、candidate `145.234/183.030s`；planner reasoning legacy `806/1,251`、candidate `4,140/5,824`；Coding reasoning legacy `11,486/14,416`、candidate `5,870/8,845`；累计 reasoning legacy `11,767/15,667`、candidate `10,010/12,792`；首次写入时延 legacy `80,014/144,558ms`、candidate `39,972/62,586ms`；首次写入 reasoning legacy `6,397/13,426`、candidate `1,992/4,395`。candidate 的累计 reasoning P50/P95 分别下降约 `14.9%/18.4%`，总耗时分别下降约 `13.3%/5.9%`；但首次运行率由 legacy `3/3` 降至 candidate `2/3`，两侧原始协议正确率均仅 `1/3`。因此这是收益信号，不是稳定 P95 结论，且 candidate 未达到质量推广门槛。
- [x] candidate planner-medium 单变量诊断已串行完成 3 组，只改变 planner effort，Coding 保持 high。描述性 P50/P95：总耗时 `162.739/169.719s`，planner reasoning `4,050/6,643`，Coding reasoning `8,496/9,374`，累计 reasoning `12,940/13,424`，首次写入时延 `57,928/68,642ms`，首次写入 reasoning `4,778/5,582`。相对 candidate-high，planner reasoning P50 仅下降约 `2.2%`、P95 上升约 `14.1%`，累计 reasoning P50/P95 分别上升约 `29.3%/4.9%`，总耗时 P50 上升约 `12.1%`。medium 三次首次运行和原始协议均成功，但样本量不足以把质量差异归因于 effort；由于核心推理指标未改善，不推广 medium。high 样本采集时尚未记录 planner `durationMs`，不得伪造该项时延对照。
- [x] candidate planner reasoning 明显高于 legacy。现有证据更支持额外 `codingRequirements`（`datasetId`、`fields`、`calculation`、`outputName`）带来的语义拆解开销，不能归因于输入长度本身。
- [x] 追加 candidate planner 样本在 `4.228s/141 reasoning tokens` 后返回无需补证，按 `report_benchmark_coding_not_required` 门禁停止；该样本不进入 Coding 累计 reasoning 或首次运行率，但作为 planner gate failure 保留，证明 candidate planner 决策稳定性仍未达到推广要求。
- [x] 同 bundle legacy 配对样本正常进入 Coding（planner `728`、Coding `8,837` reasoning，首次运行成功），candidate 则在 planner gate 停止；该配对仅作为决策稳定性诊断，不改动三组主 A/B 统计。
- [x] planner replay 指标现在持久化 analysis 决策摘要（`requiresSupplementalEvidence`、`codingRequirementCount`），不保存 reason/missingFacts 原文；后续 gate failure 可直接统计决策分布。
- [ ] 可视化真实 provider A/B 已尝试但未进入 Coding；新冻结输入见 2026-09-22 报告，路径漂移的具体原因仍待有差集的失败样本确认。单独 legacy planner 后续通过不代表两阶段收益验收。

2026-09-21 CLI 探针记录纠正：已确认后续 20/55/360 秒探针只输入任务正文，遗漏 `/run`，实际停留在输入阶段，不能归为 planner 请求删失或 provider 长尾。更早的 150/300 秒记录也缺少有效提交及请求发出的证据，撤回其 planner 超时归因，全部排除出模型指标。23:07 正确发送 `/run` 后，PTY 正常输出 workflow/provider 日志，请求解析与数据理解分别约 2.3/6.5 秒，step 的 `request_count=1` 已在真实运行中确认。

2026-09-21 生产 planner 观测补正：started 记录在请求开始时直接加入 session 内存状态，取消保留 started 并标记 `censored=true`；该行为不代表进程强制退出前已经落库。响应身份按 Agno 的 `ModelResponse.provider_data.id` 读取，耗时使用单调时钟。观测定向测试 `5 passed`，Ruff 通过；完整可视化冻结输入与性能验收仍未完成。

2026-09-21 正确提交的 360 秒诊断（run `cli-report-23c8952b881743bdbe4792fc8de232ba`）：7 次前置 planner 调用完成，最长为分析规划约 20.3 秒。首个分析 Coding 请求耗时 254,626ms，input=3,999、output=26,504、reasoning=21,417、visible=5,087、cache_read=1,024 tokens；原始协议正确，`write_script` 一次成功。第二个 Coding 请求刚开始时外部窗口到期，SIGINT 正常取消并清理 workspace；整轮为删失样本，首次执行/最终交付仍 unknown。保留已完成首请求的实测数据，不据此计算完整任务成功率或 P50/P95。该样本确认首写长尾出现在 Coding 请求，不是工具格式重试；reasoning 占输出 token 约 80.8%，不能直接换算为纯推理时间占比。

当前宿主指标证据：阶段分区、缺失 usage/Agno 默认全零识别、receipt 向后兼容和请求级 provider ID 持久化已通过；指标模块完整定向回归为 `26 passed`。分析 v2 bundle 已生成、校验并完成 3 组 high-effort A/B 与 3 组 planner-medium 单变量诊断；现有可视化 trace 仍缺少可信 `dataDescriptors`，且没有审核过的 `visualForm/dataBindings` acceptance，因此可视化 v2 bundle 和真实 A/B 继续阻断。

**验收：** 分析与可视化各自证明规划加 Coding 的累计 reasoning 和总耗时下降，首次运行成功率、精准 patch、证据身份和视觉 critical 质量不下降。章节只决定 Coding 范围，沿用现有单脚本身份；任何没有累计收益的字段、缓存重排或 effort 调整都不推广。

## CodeMode 优化规划：按实际收益利用原生能力

### 源码结论与方案修正

| 当前实现及证据 | 实际含义 | 优化决策 |
| --- | --- | --- |
| `reporting/code_mode.py::create_reporting_code_mode_runtime()` 与 `runtime/execution.py` 分别创建 CodeMode，均未传 `tools`/`fs` 且设置 `snapshot=False` | 已使用原生 kernel 管理，未接入业务 ToolBridge 和跨进程变量恢复；OS/CLI 存在两处构造 | 先统一构造，再按证据选择桥接；不直接打开 snapshot |
| `ReportingCodeModeRuntime.execute()` 调用 `arun(session_id, code)` | 同任务探索变量可复用；这个开发者入口不携带 Agent 的 RunContext/ResultStore | 原生上下文接入须通过公开接口验证，不能只给构造器增加 `tools=` |
| `ReportingCodeModeToolkit.run()` 返回有界 stdout/stderr/result/truncated | 没有透传 `CellResult.images`，也没有把完整截断输出存入可回读存储 | 只在实际需要预览或回读时接入对应能力，不把二次截断后的文本当完整结果 |
| `protocol.py::get_request_params()` 对 visualization 使用 `nextTools` 过滤，`delivery.py` 的常规图表路径没有 `run` | 工具注册并不等于模型在该阶段能调用；当前图表流程主要直接写脚本 | 不为使用 CodeMode 强制插入探索轮次；分析任务先试点 |
| `_script_process_cell()` 用 `%%bash` 启动 `python -u script.py` | 正式脚本有独立变量空间，不继承探索 DataFrame；kernel cwd/env 仍可能被子进程继承 | 保持正式脚本可独立重跑；执行前恢复明确工作目录和渲染配置 |
| `code_generation.py` 在任务 finally 中 shutdown；未接入 `variables/avariables` | 持久化范围是当前任务；官方变量接口只能读取 kernel 顶层状态 | 不能用 `avariables()` 填充正式子进程的异常 locals；现有 unknown 语义保留 |
| `max_kernels` 配为阶段并发数之和 | Agno 所有 kernel 忙时允许暂时超过此值，它不是严格并发信号量 | 使用现有 Workflow 并发控制；不宣称该参数提供硬资源上限 |

上一轮“ToolBridge 是最大缺口”仅表示框架能力尚未接入，不是已证实的性能瓶颈。现有证据主要指向首次写入前的 provider reasoning 长尾；没有工具往返的请求不会因工具桥接自动变快。当前 Workspace 文件已经让原始数据留在上下文之外，ResultStore 是否有增量收益要单独验证。

目标执行边界：

```text
provider 结构化 custom/function 调用
  -> 现有协议整体校验、顺序执行及交付状态
     -> run：任务内持久 CodeMode，按需探索
        -> 原生 ToolBridge：经授权的只读工具（C3 验证后）
        -> 原生 ResultStore：有界回读大工具结果（C4 验证后）
     -> write_script / edit_script：绑定路径、源码 SHA、精确编辑
     -> run_script：独立 Python 子进程、退出回执、输出校验
     -> view_image / submit_script：现有视觉验收与交付
```

这是一套业务执行边界，不是操作系统沙箱。CodeMode 本身拥有宿主进程权限；task ID、工具白名单和 AST 规则不能被描述为不可信 Python 的完整隔离机制。

### 优先级与依赖

| 优先级 | 任务 | 与 R1–R7 的关系 | 推进条件 |
| --- | --- | --- | --- |
| P2 条件观测 | C1：统一运行时并观测 CodeMode 开销 | R7/R6 后复用现有 metrics/recorder | 只有指标证明执行开销是总耗时显著项时推进 |
| P1 | C2：完善任务内探索和状态诊断 | 结合 R2/R3，保持现有单脚本正式文件身份 | 只服务实际需要探索的任务，先验收状态正确性 |
| P1 条件试点 | C3：原生上下文与只读 ToolBridge | 使用 R6 的分析样本 | 样本存在可消除的多轮只读工具往返 |
| P2 条件试点 | C4：原生 ResultStore 回读 | 依赖 C3，复用 R6 | 存在 Workspace 文件路径尚未解决的大工具结果 |

C1 不抢占 R7/R6 的 reasoning 优化主线；只有现有指标证明 kernel/执行开销是总耗时显著项时才推进。C2 不阻塞 R2–R4；C3/C4 不阻塞 reasoning 优化主线。每次只改变一个变量并使用 R6 记录收益，不另外重复完整报表或建设第二套基准工具。

### C1：统一 OS/CLI 初始化，测量执行开销

**2026-09-21 审计结论：** 当前不存在同一进程重复创建两套 CodeMode/monitor/LSP；CLI 的 `create_execution_context()` 只是重复实现了 AgentOS 已使用的工厂参数。真正的生命周期缺口是 AgentOS 退出时未显式关闭 CodeMode runtime 与 LSP。多 worker 下每个进程独立持有一套资源，容量为 `workers * (analysis_concurrency + section_concurrency)`。工厂收敛和退出关闭只记维护与资源正确性收益，不宣称降低 reasoning；执行耗时未证明为显著项前，不调整 bootstrap、monitor 或 kernel 数量。

工厂参数已在 OS/CLI 入口统一，AgentOS lifespan 现按 runtime、LSP、Workspace 顺序关闭且单个资源失败不跳过后续清理；定向工厂/生命周期节点通过。C1 下列复选框仍未整体完成：尚无 bootstrap/monitor/cell/正式脚本/shutdown 的分段计时，真实 kernel 仅有既存的单任务状态复用与 shutdown 清空测试，跨任务隔离、重建和正式子进程矩阵未完成。扩展真实 kernel 测试曾连续 120 秒无终态并已中止，不能当作通过或性能数据。

**涉及文件：**

- 修改：`smart_reporting/runtime/execution.py`、`smart_reporting/reporting/code_mode.py`。
- 按观测需要修改：`smart_reporting/reporting/code_agent/metrics.py`、`smart_reporting/reporting/workflow/runtime/code_generation.py`。
- 测试：`smart_reporting/tests/test_execution_context.py`、`smart_reporting/reporting/tests/test_reporting_script_process.py`、`smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py`。

**接口：** 两入口共用现有 `create_reporting_code_mode_runtime(workspace_root, *, analysis_concurrency, section_concurrency, timeout)`。沿用 `execute()`、`execute_script_process()`、`shutdown()` 和 `ScriptProcessResult`，不增加第二个执行引擎。

- [x] OS/CLI 已统一使用现有工厂的 timeout、cwd 和 kernel 数量配置；AgentOS lifespan 已按 runtime、LSP、Workspace 顺序关闭，且单个资源关闭失败不跳过后续清理。该项只记维护与资源正确性收益，不宣称降低 reasoning。
- [ ] 用真实 kernel 补齐关闭执行上下文后无存活 task kernel、shutdown 后重建和跨 task 隔离验证；既有扩展测试曾 120 秒无终态，后续只能做有界定向验证，不以盲目延长等待通过。

- [x] 在现有 loguru/recorder 中增加任务级执行计时：bootstrap（含惰性启动）、monitor 同步、cell、正式脚本调用和 shutdown。分别记录跨度，不将重叠的父子跨度相加；不能分离的 kernel 启动时间记 unknown，不从首个 cell 时间推算。`ReportingCodeModeRuntime` 按 session 暂存并一次性 drain 五类跨度，单阶段保留最近 64 次，Coding sample 以 `executionSpans` 持久化，汇总器按阶段输出 P50/P95；纯归一化、runtime drain 和汇总定向测试覆盖负值过滤、unknown 语义和五类跨度身份。真实 kernel 生命周期矩阵仍未验收。
- [ ] 用真实本地 kernel 验证两个 cell 的变量复用、不同 task 的命名空间隔离、shutdown 后重建以及正式脚本不继承探索变量。示例先 `run("probe = 41")` 再 `run("probe + 1")` 返回 42；新 session 不存在 `probe`；正式文件引用未定义 `probe` 应失败。
- [ ] 先保留每次执行前的 cwd/Agg 设置；只有计时证明 bootstrap/monitor 显著占用时才减少重复操作。若采用初始化缓存，必须在 restart、idle eviction 和内核重建后失效，不能只按曾见过的 session ID 跳过初始化。
- [ ] 定向运行上述测试文件中新增/受影响节点，检查退出回执在输出截断、异常、并发和取消后仍可靠。通过后独立提交本任务，避免混入其他工作区变更。

**验收：** OS/CLI 行为一致；真实持久状态测试通过；可区分模型等待和执行开销。单纯工厂去重只记维护收益，不宣称已降低 reasoning。

**2026-09-21 当前验证记录：** C1 的纯 runtime span drain 与指标归一化定向用例通过，编译和 `git diff --check` 通过；真实 Agno kernel 的输出截断用例及完整视觉 Runner 用例在有界 35–70 秒门禁内未终止，因此不把它们记为通过，也不增加重试或伪造 kernel 生命周期数据。

### C2：保留按需探索，补齐状态可观测性

**涉及文件：**

- 修改：`smart_reporting/reporting/code_mode.py`、`smart_reporting/reporting/code_agent/toolkit.py`、`smart_reporting/reporting/agent.py`。
- 仅需开放特定探索状态时修改：`smart_reporting/reporting/code_agent/delivery.py`、`smart_reporting/reporting/code_agent/protocol.py`。
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_stability.py`、`smart_reporting/reporting/tests/test_reporting_code_input.py`、`smart_reporting/reporting/tests/test_reporting_script_process.py`。

**接口：** 探索继续使用原始 free-form `run(code)`；官方 `CodeMode.avariables(session_id) -> dict[str, str]` 仅供探索诊断。新增回执字段拟为 `explorationVariables`，不得复用正式脚本的 `variableSummary` 字段混淆来源。

- [x] 用失败用例明确“探索 kernel 变量”和“正式脚本 locals”两种来源：前者返回最多 32 个经过名称和类型限制的 `explorationVariables`，并与 stdout/stderr/result 共用 8 KiB 诊断预算；后者无执行器证据时继续 `variableSummary.status=unknown`。不调用 `avalue()`，变量值和完整 DataFrame 不进入回执或日志。
- [x] 每个探索 `run` 的 cell 完成后才通过公开 `avariables()` 查询，使成功回执也能证明后续可复用的变量；查询有 2 秒上限，接口缺失、超时或异常不阻断原执行。失败回执使用同一有界状态，不在持有 session lock 时重入。
- [x] 重启回执明确返回 `variablesCleared=true` 与空 `explorationVariables`；已保存脚本仍按现有行为保留。真实 Agno kernel 测试已验证 DataFrame/import 跨 cell 复用、shutdown 后状态清空。
- [x] `run` 工具描述明确 `explorationVariables` 仅含变量名和类型，后续探索应复用现有变量而不是重复读取同一文件；已知输入/字段/目标仍直接写正式脚本，不因该能力强制增加探索轮次。
- [x] 分析与图表任务均按宿主签发的 `nextTools` 过滤模型可见工具；初始写入允许 `write_script -> run_script -> submit_script` 的同轮有序正式链，但不默认开放探索 `run`。空 `nextTools` fail-closed；若冻结故障样本证明必须探索，仍需新增可追踪诊断分支，不得全局放开 `run` 或按固定次数截断必要诊断。
- [x] 已完成变量重置、状态摘要总大小、执行包装失败、变量查询异常/超时取消、已知 aborted/KernelBusyError 跳过变量查询和真实持久状态定向验证；忙内核恢复依赖 Agno 现有 wait policy，不自动 restart。当前受影响组合为 `64 passed, 78 deselected`，另有 busy 分支定向回归 `3 passed`。首次真实 `legacy/high` 回放在 planner 约 5 秒后返回 `requiresSupplementalEvidence=false`，以 `report_benchmark_coding_not_required` 停止，未进入 Coding；该结果只记 planner gate failure，不作为 C2 性能样本，也不盲目重试。后续真实性能对照仍合并到 R6。

**验收：** 必要探索能复用状态；无需探索的成功路径不增加模型往返；正式脚本独立执行与 unknown locals 契约不变。内联图片暂不扩展；现有 `view_image` 已负责正式图表验收。

### C3：验证公开执行接口，再试点原生只读 ToolBridge

**涉及文件：**

- 新建定向集成测试：`smart_reporting/reporting/tests/test_reporting_code_mode_bridge.py`。
- 验证通过后修改：`smart_reporting/reporting/code_mode.py`、`smart_reporting/reporting/code_agent/toolkit.py`、`smart_reporting/reporting/workflow/runtime/code_generation.py`。
- 最小只读适配放入新文件：`smart_reporting/reporting/code_agent/readonly_tools.py`，仅当原生 Workspace/现有服务不能直接满足任务授权时创建。
- 协议回归：`smart_reporting/reporting/tests/test_reporting_code_agent_batches.py`、`smart_reporting/reporting/tests/test_reporting_code_agent_scope.py`、`smart_reporting/reporting/tests/test_reporting_code_reasoning_replay.py`。

**先验边界：** Agno 3.0.9 的公开 `aexecute(run_context, code, agent=None, team=None)` 会绑定上下文并返回 `ToolResult`；`arun(session_id, code)` 返回结构化 `CellResult`，但不绑定调用者上下文。这两条路径不能直接互换，否则会丢失现有 status、truncated 和退出诊断契约。

**2026-09-21 兼容性结论：** 公开接口审计已确认 3.0.9 无法同时满足完整任务 `RunContext` 和现有结构化 `CellResult` 回执。`aexecute` 能传上下文但只返回格式化 `ToolResult`；`arun` 保留 `status/truncated/stdout/stderr/result/traceback`，却不传调用者上下文。不得解析 `ToolResult.content` 或使用私有 `_aexecute_impl/_arun_impl/_sessions/bridge` 绕过。C3 试点暂缓，优先等待或验证提供所需公开契约的官方版本。

- [ ] 先做真实 kernel、无外部模型请求的兼容性用例，覆盖成功、Python 异常、超时、输出截断、图片、重启、异步工具抛错及两个并发任务。桥接测试使用注入 `RunContext` 的只读测试函数，返回 task/session/user 身份供断言；不只 mock `arun`。
- [x] 已完成公开接口源码级兼容性审计，确认 3.0.9 存在上述接口缺口，因此按门禁暂缓 C3/C4；未调用私有接口、未解析人类可读字符串重建执行状态。真实 kernel 的完整桥接矩阵仍保留为未来版本升级的兼容门禁，不视为当前实现项。
- [ ] 外层模型调用仍为 `run` custom tool；Agno 的 `execute` 仅作为宿主内部委托目标，不能把官方默认 JSON 工具声明直接暴露给 provider，不能从 assistant 正文提取代码。
- [ ] 由服务器构造任务级 RunContext：保留真实 user/run 标识，session 使用 `code_mode_session_id`，在 dependencies 中绑定受信任务与 Workspace。核对与 Coding Agent/ResultStore 使用的身份是否一致；缺少身份或绑定时只读桥接拒绝调用，不接受模型补传 tenant/task/path 授权。
- [ ] 首批只选当前冻结分析样本确实反复调用的只读能力，例如现有 Knowledge 检索与授权文件分页读取。复用原生 ToolBridge 和现有服务；文件工具校验已签发路径及文件身份。知识检索结果只能提供实现参考，不能替代冻结业务事实。
- [ ] 共享 CodeMode 的 `tools` 注册在构造时稳定；每次调用从注入上下文解析绑定，不能把 task A 的 Toolkit 闭包挂到全局后供 task B 复用。只读调用纳入现有工具计量，区分 provider 外层调用与桥接内部调用，记录 task 身份、耗时和结果大小，不记录原始数据。
- [ ] 使用 Agno 原生 connect/aclose 管理异步服务生命周期，验证桥接在创建客户端的宿主事件循环执行；一个任务取消/结束不能关闭另一个任务仍使用的连接。后台调用结束后的过期绑定必须拒绝，不能借用下一个任务的权限。
- [ ] 不桥接 `run`/`run_script` 等会再次进入同一 kernel 的工具，避免递归执行和锁等待；不桥接 write/edit/submit、视觉审查或其他状态变更操作。原 provider 混合多调用的整体校验、顺序执行、失败/提交后停止与回放测试必须继续通过。
- [ ] 用 R6 做 A 现有独立只读调用、B 原生桥接的单变量对照；无必要只读往返的任务也纳入对照，确认没有额外探索开销。测累计 reasoning、模型往返、工具总耗时、首轮/最终成功率，而不是只计算工具数量下降。

**验收：** 公开接口契约完整，任务身份不串用，异步连接不跨错事件循环；真实样本显示规划加 Coding 总耗时改善且交付质量不下降后才推广。接口验证不通过时，报告“试点暂缓”而非将任务勾选为实现完成。

### C4：按需接入原生 ResultStore，避免重复存储 Workspace 数据

**涉及文件：**

- 修改：`smart_reporting/reporting/agent.py` 的 Coding Agent 工厂、`smart_reporting/reporting/code_mode.py` 和 `smart_reporting/reporting/code_agent/toolkit.py`。
- 测试：C3 的 `smart_reporting/reporting/tests/test_reporting_code_mode_bridge.py`、现有 `smart_reporting/reporting/tests/test_reporting_code_output_truncation.py`。
- 指标与回放：复用 R1/R6，不新建通用缓存系统。

**接口：** 使用 Agno 原生结果卸载及 kernel 的 `result_store.get/read/search/ids`。接线依赖 C3 的公开上下文接口验证；不能只打开 Agent 的开关就宣称 kernel 能访问结果。

**2026-09-21 收益审计：** 当前未启用 Agno ResultStore；现有大型工具回执走项目 `outputHandle`。历史临时 Workspace 中同一 task 内没有重复内容哈希，尚无“同任务大回执被重复存储并再次局部读取”的证据。跨 task 重复内容不能由按 session/run/call 存储且不做内容去重的 ResultStore 解决。Agno 3.0.9 还要求同步 `PostgresDb/SqliteDb`，并禁止同时启用 `compress_tool_results` 与 `offload_tool_results`。因此 C4 保持未实施，只有 C3 公开接口门禁通过且真实轨迹出现大桥接回执二次读取时才做单变量试点。

- [ ] 用大工具结果、异用户、异任务、结果过期、存储不可用的行为测试明确读取边界。结果 session ID 必须与 C3 的任务 CodeMode session 一致，不能把原报表会话 ID 下的结果静默迁移成所有任务可见。
- [ ] 已有授权 CSV/事实文件继续按路径读取，不将相同内容再写一份 ResultStore。首批仅处理桥接工具确有大回执且模型需要再次局部读取的场景。
- [ ] 采用 Agno 自带卸载配置和接口；优先 read/search 局部处理。`get` 将完整 payload 加载到 kernel 内存，应受原生存储大小限制，不能宣称卸载消除了内存成本。
- [ ] 明确两条截断链：ToolBridge 大结果可由原生 ResultStore 卸载；Jupyter stdout 超过内核 cap 后丢弃的部分无法事后找回。需要完整诊断时由正式脚本进程在截断前写任务授权日志文件，再按范围读取，不能存储截断文本后标记为完整日志。
- [ ] ResultStore 不可用时明确返回可恢复的错误或已知截断状态，不增加静默重跑大查询的逻辑。原始数据不进入 loguru 或模型全文回执。
- [ ] R6 分开比较 C3 和 C3+C4；记录实际回传模型的内容大小、input tokens、内存/读取开销和任务总耗时。没有增量收益则保留 Workspace 路径方案，不默认开启新的存储链。

**验收：** 模型可从引用定位到当前任务的真实结果；越权/过期请求被拒绝；大结果不必全文进入上下文，且交付成功率与总耗时不退化。

### 明确暂不推进及验收衔接

- 继续 `snapshot=False`，任务结束关闭 kernel；恢复以脚本、Workspace、数据库和 Workflow checkpoint 为准。只有出现跨进程恢复探索状态的实际需求才另行设计 snapshot，不把 dill 快照当业务产物持久层。
- 正式脚本保持独立 Python 进程；不为复用 DataFrame 改成 `%run -i` 或 `exec`，不让隐藏探索变量决定正式产物。
- 不用 kernel 的 `avariables/avalue` 假装读取已退出脚本的 locals；需要正式异常现场时单独设计执行器支持，不混入本次性能试点。
- 不为充分使用 CodeMode 添加 planner、强制探索、无用途的预加载或另一套自制 ToolBridge/ResultStore。
- C1/C2 做本地行为验证；C3/C4 先完成公开接口兼容性与作用域测试，再进入 R6 的真实冻结对照。使用同一批次的最新有效测试结果，不重复完整测试。
- C2 已完成离线实现与定向验证，但尚未完成真实冻结样本性能对照；C1 只完成生命周期审计，C3/C4 因公开接口与收益门禁暂缓。只读调查和离线测试都不能证明节省比例、kernel 利用率或生产成功率。最终报告分别列出维护改进、运行时开销改进和模型推理改进。

## 历史已完成基线（保留，不代表本轮重新验收）

- [x] `write_script` 首轮直接开放，脚本不存在时不再先发一次 `read_script`。
- [x] `write_script` 在 Ruff 格式化后返回 `savedSource`，提示后续 patch 以实际落盘源码为准。
- [x] `edit_script` 支持 SHA 绑定、SEARCH/REPLACE 精确匹配和原子提交。
- [x] `nullableFields` 已投影到可视化 supplemental evidence，并在 Coding instructions 中说明合法 `null` 不能替换为 0 或空字符串。
- [x] 失败 traceback 优先定位业务调用点，不再只定位到通用 helper。
- [x] `visualFailures.issues` 已结构化为 category、severity、description。
- [x] 交付状态已按 `nextTools` 驱动，已有脚本不再推荐完整 `write_script`。
- [x] 协议层已设置 `parallel_tool_calls=True`；现有单脚本多调用顺序与回放已有任务 7 的验收记录。
- [x] 历史定向回归曾达到 `177 passed`；不将历史数字当成本轮实测结果，不得通过删除测试降低门槛。

## 历史性能证据

- 历史完整报表耗时：52 分 55 秒。
- 此前完整报表耗时：约 35 分 14 秒，相较历史减少约 17 分 41 秒；不是本轮计划的优化结果。
- 原始流程仅 `read_script` 往返累计约 571 秒。
- 真实重放首轮 `write_script` 成功，但请求约 501 秒。
- 首轮观测：`reasoning_tokens=29851`、`visible_output_tokens=8143`。
- Responses 推理统一使用 `reasoning.effort`、`reasoning.summary`；`thinking_budget` 不是本路径支持的硬上限。DashScope 当前仍兼容顶层 `enable_thinking`，但已声明后续不再支持；vLLM 不接受顶层字段，显式开关放入 `chat_template_kwargs.enable_thinking`。
- 因此当前最大瓶颈是 provider/model reasoning 长尾，不是前三次 patch 格式拒绝。

## 历史推进记录

- [x] Responses Coding 请求已清理 `thinking_budget`，保留 `reasoning.effort`、`reasoning.summary`，并按 provider 投影 `enable_thinking`：DashScope 顶层、vLLM `chat_template_kwargs`、其他端点不发送扩展字段。真实参数探针确认 DashScope 关闭 reasoning 必须显式发送 `reasoning.effort=none`；仅省略 reasoning 或仅发送 `enable_thinking=false` 均不足。Coding Responses 的显式关闭决策已按此投影，首轮开启 reasoning 的路径不变。
- [x] 新增 Responses wire 回归断言，确认请求不再携带 `thinking_budget`。
- [x] Responses/free-form 定向测试：`63 passed`。
- [x] 模型投影与推理传输定向测试：`46 passed, 2 skipped`。
- [x] `write_script`/`edit_script` 回执统一补充 `sourceSha256`、`sourceBytes`、变更摘要；SHA 冲突回执补充当前/期望 SHA、`action=read_script` 和读取范围。
- [x] 源码身份与精准编辑定向测试：`55 passed`。
- [x] Responses 最终请求参数日志已接入：记录 `reasoning.effort`、`reasoning.summary`、`enable_thinking` 的有效位置/值（顶层、`chat_template_kwargs` 或 `omitted`）、`extra_body` 键名、`max_output_tokens`、`parallel_tool_calls` 和 `tool_choice`，不记录完整 prompt 或密钥；provider 不支持时省略，不为 A/B 强行发送。
- [x] Responses 请求最终出口再次清理 `thinking_budget`，并完成 `enable_thinking` provider-aware 投影；协议、reasoning 回放与回放脚本定向测试：`52 passed`。
- [x] 多工具批次与轨迹回放已按真实工具状态验证：批次 `18 passed`，轨迹 `10 passed`；修复回放使用带当前 SHA 的 `edit_script`，不再在已有脚本上伪造 `write_script`。
- [x] 失败诊断补充异常类型、允许编辑区域和禁止编辑区域；交付/视觉定向测试分别通过 `32 passed` 和 `22 passed`。
- [x] 已完成真实 Responses `reasoning.effort` 对照探针（`high`/`medium` 各 3 次）；原始数据写入 `docs/superpowers/reports/2026-09-20-reporting-coding-performance-ab.md`。结果显示明显长尾，暂不据此改变默认档位。
- [x] 同一冻结 visualization payload 已完成 `low`、`medium`、`high` 各一次真实回放；`medium`/`high` 均通过且 `critical=0`，但单次样本不足以选择默认档位。
- [x] 统一样本已补充首次脚本成功、首次运行成功、input/output/cache token、provider/Agno cost 和视觉审查耗时；cost 缺失时保留 `unknown`，不由宿主估价。
- [x] `medium-2` 真实回放暴露交付状态与预算闸门冲突：`nextTools` 要求 `read_script`，预留区却把它当探索工具拒绝，导致模型反复读取直至工具预算耗尽。已改为仅在当前交付状态要求读取时把 `read_script` 纳入正式交付工具；批次、交付、编辑和 continuation 定向回归 `96 passed`。

## 原任务记录：源码身份、协议语义和失败上下文

### 任务 1：完成实际源码身份闭环

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/toolkit.py`
- 修改：`smart_reporting/reporting/code_agent/delivery.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_formatting.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_edit.py`

- [x] 为 `write_script` 和 `edit_script` 的成功回执统一增加 `sourceSha256`、`sourceBytes`、`formatted`、`savedSource`（仅格式化发生时）和局部变更摘要。
- [x] 为 SHA 冲突回执增加 `currentSha256`、`expectedSha256`、`action=read_script` 和建议读取范围；不得只返回泛化重试提示。
- [x] 确认 `savedSource`、最新 `read_script` 和当前 SHA 在交付状态中使用同一份实际落盘文本。
- [x] 增加测试：格式化后 patch 基于 `savedSource` 一次应用；旧 SHA 被拒绝；冲突回执不开放 `write_script`。
- [x] 运行：`.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_code_formatting.py smart_reporting/reporting/tests/test_reporting_code_edit.py`，结果 `55 passed`。

### 任务 2：统一 free-form 工具描述

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/protocol.py`
- 修改：`smart_reporting/reporting/code_agent/toolkit.py`
- 修改：`smart_reporting/reporting/agent.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_input.py`

- [x] 为每个工具明确三件事：原始输入格式、禁止的外层信封、宿主如何返回执行结果。
- [x] `write_script` 明确输入为 Python 源码原文；禁止 JSON、`{"source": ...}` 和 Markdown code fence。
- [x] `edit_script` 明确输入为原始 patch 文本；禁止 `{"data": ...}`、字符串转义和 code fence；要求带当前源码 SHA。
- [x] `run` 接受原始 free-form 代码文本；`run_script` 保持结构化 function 参数。两者都只执行 provider 返回的结构化 tool call，不得从 assistant 正文提取伪工具调用。
- [x] 保留 grammar 校验；拒绝多层 envelope，不通过增加重试弥补协议错误。
- [x] 测试 JSON envelope、双层 envelope、Markdown fence、合法 free-form 和混合 custom/function 调用。

### 任务 3：压缩失败修复上下文

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/toolkit.py`
- 修改：`smart_reporting/reporting/code_agent/delivery.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_diagnostics.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_visual_repair_diagnostic.py`

- [x] 失败回执固定包含异常类型、业务函数/行号、错误附近源码、当前 SHA、唯一允许修改区域和禁止修改区域；变量摘要只透传执行器明确提供的结构化内容。
- [x] traceback 保留精简根因；源码 excerpt 默认上下各 12 行，遵守既有 UTF-8 总预算。
- [x] `run_script` 失败优先推荐 `edit_script`；只有 SHA 不一致才推荐 `read_script`。
- [x] 视觉失败只携带对应图片、category、severity、description 和建议，不携带无关全量脚本。
- [x] 测试 helper 异常定位到业务调用点、结构化变量摘要/unknown 降级、视觉 warning/critical 分级。

> 变量类型和值摘要没有来自 Agno/CodeMode 的安全 locals 接口时，宿主固定返回
> `{"status":"unknown","reason":"runtime_did_not_expose_locals"}`，不从 traceback 或源码猜测变量值。

### 任务 4：清理工具白名单冲突

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/protocol.py`
- 修改：`smart_reporting/reporting/code_agent/delivery.py`
- 修改：`smart_reporting/reporting/agent.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_delivery.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`

- [x] 脚本不存在时只开放 `write_script`、必要的运行/提交工具。
- [x] 脚本存在时移除 `write_script`，开放 `read_script`、`edit_script`、`run_script`。
- [x] 输出预检失败时只开放修复链路，不重新开放完整写入。
- [x] 已提交状态不再发送任何继续模型请求。
- [x] 测试工具范围与 `nextTools` 始终一致，且不因历史错误回执恢复过期工具。

## 原任务记录：请求观测、reasoning A/B 与并发调度

### 任务 5：记录最终 provider 请求和原始 usage

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/protocol.py`
- 修改：`smart_reporting/reporting/code_agent/metrics.py`
- 修改：`smart_reporting/reporting/model_policy.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_phase_models.py`

- [x] 用 loguru 记录脱敏后的 `model`、`reasoning.effort`、`reasoning.summary`、`enable_thinking` 的有效位置/值（或 `omitted`）、`extra_body` 键名、`max_output_tokens`、`parallel_tool_calls`、`tool_choice`。
- [x] 记录 provider 原始 `input_tokens`、`output_tokens`、`reasoning_tokens`、`cached_tokens` 和请求耗时。
- [x] 区分 Agno 投影参数、最终 HTTP 参数和 provider usage；Responses API 传递 `reasoning.effort`、`reasoning.summary`，不得发送或依赖 `thinking_budget`；`enable_thinking` 仅按 DashScope/vLLM 的公开契约投影。
- [x] 对敏感值只记录字段存在性、数值和哈希，不记录 API key、完整 prompt 或完整源码。
- [x] 测试日志字段完整、Responses 请求中不存在 `thinking_budget`、不同 provider 的 `enable_thinking` 位置正确、usage 缺失时软降级。
- [x] Coding 阶段的逐请求 `modelRequestMetrics` 现在同时持久化脱敏 `requestParams` 快照（model、effort、summary、enable_thinking 的位置和值、max_output_tokens、parallel_tool_calls、tool_choice、extra body 键名），并保留原始 usage 的 `unknown` 语义；同一快照已穿透生产 `modelMetricsByStage.coding.requestMetrics`，不会只停留在 debug 日志或回放 JSON。定向测试覆盖请求投影、指标归一化和阶段 settlement。
- [x] 增加最终 wire 的连续 system 前缀、实际工具声明和 text format schema 的 SHA-256/UTF-8 字节数指纹；`previous_response_id` 排除未发送的历史 system，空值标记 `unknown`。脱敏归一化只保留合法哈希和字节数，不记录原文。该项只提供缓存诊断，不改变请求顺序、schema 或缓存策略；缓存收益仍待 R7.3 的真实 provider usage。

### 任务 6：保留首轮 reasoning，建立真实 A/B

**涉及文件：**
- 修改：`scripts/replay_visualization_task.py`
- 新建：`docs/superpowers/reports/2026-09-20-reporting-coding-performance-ab.md`

- [x] 使用冻结 visualization payload 和临时 workspace，避免影响正式报告；回放失败时保留 workspace，并可通过 `--output` 写出不受控制台日志污染的结构化结果。
- [x] `scripts/replay_visualization_task.py` 支持 `--payload` 临时 payload、临时 workspace 和显式 `--reasoning-effort`；Responses 路径不再接受 `thinking_budget`。
- [x] 首轮保留 reasoning，比较 `high`、`medium` 和 provider 明确支持的低档配置；不直接把 `off` 设为默认。
- [ ] 每种配置记录首次脚本通过率、首次 patch 应用率、首次运行成功率、critical 视觉缺陷率、总耗时、P50/P95 reasoning token、成本。
- [ ] 至少覆盖空值同比、格式化后源码、复杂局部 patch、视觉文字遮挡和工具失败恢复。
- [x] 已根据 provider usage 比较不同 `reasoning.effort` 的真实推理 token 和耗时：包含分析 high A/B、planner-medium 单变量诊断及可视化 low/medium/high 历史样本；现有证据不支持降低默认 effort。Responses API 的配置和验收均不再使用 `thinking_budget`。

`medium-2` 在 1402.453 秒后因宿主观察窗口到期人工终止；样本记录了 `firstScriptSuccess=true`、
`firstRunSuccess=false`、`firstPatchApplied=true`、`firstRepairSuccess=false`、
`rawProtocolCorrect=false` 和 `criticalVisualDefect=true`。人工终止后的 usage 与请求数为
`unknown`，不得用于 reasoning token 或模型请求数汇总。

2026-09-21 失败冻结集只读审计结论：Ruff 格式化、复杂多块局部 patch、视觉遮挡分级、SHA/CAS 冲突以及普通批次的前序失败/提交后停止已有充分定向覆盖，不新增重复测试。已补证 evidence validator 对合法 JSON `null` 的正向校验，以及混合 `custom/function/custom` 批次在前序失败时的实际执行/回执匹配；两项均通过定向测试。该离线证据只证明协议和宿主顺序不变量，不宣称真实 provider 成功率或 reasoning 改善。

### 任务 7：允许 provider 最大化返回多工具调用，但宿主严格顺序执行

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/protocol.py`
- 修改：`smart_reporting/reporting/code_agent/toolkit.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_batches.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_trajectories.py`

- [x] 保持请求参数 `parallel_tool_calls=True`，不人为限制 provider 一次响应只能包含一个调用。
- [x] 模型工具声明按宿主 `nextTools` 收敛：初始写入保留正式 `write_script -> run_script -> submit_script` 链，探索 `run` 不默认暴露，空状态 fail-closed；该范围过滤不改变 provider 多调用返回和宿主顺序执行。
- [x] provider 返回后先整体校验所有调用的 type、name、tool call id、工具范围和 grammar 身份。
- [x] 将调用分类为：无依赖只读调用、源码依赖调用、执行/产物依赖调用、提交调用。
- [x] 所有调用按 provider 返回顺序逐个执行；`read_script -> edit_script -> run_script -> submit_script` 以及 `view_image` 均不得并行执行。
- [x] 前序调用失败或已提交后停止实际执行后续调用，并按原 call id 补齐未执行回执。
- [x] 不把 `parallel_tool_calls=False` 当成顺序保证，也不因调用数大于 1 直接拒绝整轮。
- [x] 测试混合 custom/function 调用、多个调用、前序失败、提交后停止、结果回放和调用顺序；补充 `custom -> function -> custom` 实际解析顺序回归；本轮组合定向回归 `4 passed`，继续确认 `parallel_tool_calls=True` 只放宽 provider 批量返回，宿主仍按顺序执行。

### 阶段边界压缩实验（benchmark-only）

- [x] `ReportingCodeGenerationRunner` 增加显式 `compact_continuation` 开关。2026-09-22 复核修正：使用同一 Agent 的原生 `arun(add_history_to_context=False)` 建立新 run，携带任务边界、修复 facts、diagnostic 和当前交付状态；保留同一模型实例的预算、原始协议状态和完整逐请求指标。
- [x] 撤销实验额外增加的第三轮；与对照保持相同的一次补交付机会和累计工具/请求预算。默认关闭，生产 workflow 不传入该开关。预算耗尽、请求指标完整性、历史隔离定向验证 `16 passed`。
- [ ] 适用边界已纠正：这里只在模型正常结束但未提交时触发，并非每次 run_script 失败后的修复边界；同一 arun 内工具循环仍携带历史。因此不能把它描述为已解决常规修复历史增长，更不能据此解释首轮 reasoning 长尾。
- [x] 回放 CLI 增加 `--compact-continuation`，仅用于冻结 benchmark 对照；定向回归覆盖禁止调用 `acontinue_run`、工具身份和最终提交。
- [ ] 尚无真实 provider 配对数据，不能宣称 reasoning 或总耗时改善。推广前必须在同一 bundle、模型、effort、summary、工具和验收条件下比较 continuation/compact 的 input tokens、reasoning tokens、首次修复成功率和 P95 总耗时。

2026-09-22 真实探索样本：`/tmp/reporting-compact-analysis.json`，输入为 v1 `/tmp/reporting-r6-analysis-bundle.eQ5R4A/payload.json`，启动代码为 `a83118b`，high/summary=auto/enable_thinking=true/parallel_tool_calls=true。Coding `329.197s`，3 次请求、累计 `22,862` reasoning tokens；首轮 write_script `322.023s / 22,832 tokens`，后续 run_script 与 submit_script 分别 `1.828s / 9 tokens`、`2.152s / 21 tokens`；首次运行通过，原始协议正确。模型一次 arun 内完成提交，compact 分支未触发，故不作为压缩收益或修正后实现的验收证据。首轮占 Coding 耗时约 97.8%，输入仅 3,621 tokens；后续输入虽增至约 37k，推理却很短。本样本不支持“历史变长必然造成长推理”的归因。优先级回到首轮任务决策范围；补交付压缩仅保留实验。新回放结果补充 compact 开关及实际触发状态，防止把未触发样本算作实验收益。

## 原任务记录：视觉审查分级

### 任务 8：只对 critical 视觉问题触发修复

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/delivery.py`
- 修改：`smart_reporting/reporting/workflow/runtime/analysis.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_delivery.py`
- 测试：`smart_reporting/reporting/tests/test_reporting_visual_repair_diagnostic.py`

- [x] `critical` 触发 Coding 修复；`warning` 记录并继续交付；`info` 只写报告。
- [x] 多图明显相同问题通过 `merge_visual_failures` 合并路径、问题和建议，只向后续修复上下文提供一份统一反馈；未启用未经验证的多图视觉单请求。
- [ ] 多图单请求已完成接口调查，暂不启用；仍需实际验证逐图身份映射、失败隔离、输入大小和总耗时，当前单图接口不能证明批量方案必然失败或更慢。
- [x] 保留质量门禁，不把“脚本运行成功”当作“报表视觉可交付”；warning 仅记录并继续，critical 才进入修复链路。

## 原任务记录：指标、冻结集和发布门槛

### 任务 9：建立四项核心指标

**涉及文件：**
- 修改：`smart_reporting/reporting/code_agent/metrics.py`
- 修改：`smart_reporting/reporting/code_agent/delivery.py`
- 新建：`docs/superpowers/reports/2026-09-20-reporting-coding-metrics.md`
- 测试：`smart_reporting/reporting/tests/test_reporting_code_agent_metrics.py`

- [x] 核心指标已接线：`firstRepairSuccess` 仅在修复后的运行、输出预检、视觉审查和最终提交闭环通过后判真；修复失败或第二个 patch 判假。原始协议指标覆盖输入解包、未声明/类型不匹配调用、重复身份和正文伪工具调用。相关 delivery/scope/metrics/interactive/batch/trajectory 定向回归 `149 passed`。
- [x] 生产样本记录模型请求数、reasoning token、工具调用数量、`read_script`/`write_script`/`edit_script` 次数、失败代码、critical 视觉缺陷和视觉审查耗时。
- [x] `group_coding_metrics` 已按任务、模型、reasoning 档位和 provider 分组，并复用 P50/P95 汇总；不能只看平均值。
- [x] 指标缺失时标记 `unknown`，不填 0，避免把观测缺失误判为性能提升。

已实现基础汇总器 `smart_reporting.reporting.code_agent.metrics`，并有定向测试覆盖
成功率、最近秩 P50/P95 和 `unknown`。Runner 已将单任务样本写入 loguru 并支持 recorder；
按任务、模型、reasoning 档位和 provider 的批量分组汇总已接线；视觉审查耗时按实际
reviewer 调用累计，缓存命中不重复计时，并进入 P50/P95 汇总。

### 任务 10：固定复杂任务回放集

**涉及文件：**
- 修改：`scripts/replay_visualization_task.py`
- 新建：`docs/superpowers/reports/2026-09-20-reporting-coding-benchmark.md`

- [ ] 固定真实失败上下文：合法 null、Ruff 格式化、多个 patch 块、视觉遮挡、混合工具调用、前序失败、复杂局部编辑和过期 SHA。已有宿主定向基线 `21 passed`；nullable 投影和简单局部替换测试不能替代真实 null 异常修复、复杂图表编辑回放。
- [x] 已建立冻结场景清单 `docs/superpowers/reports/2026-09-20-reporting-coding-benchmark.md`，并将可视化回放改为可读取临时 payload。
- [x] 每次真实回放复制原始事实数据到独立临时 workspace，成功/失败均可写结构化 JSON，失败 workspace 保留，不改正式报告。
- [x] 运行顺序固定为定向协议测试、冻结回放、必要时单次完整 CLI 验证；禁止无目的重复完整报表。
- [ ] 每个配置的发布门槛为：协议错误不增加、首次 patch 应用率不下降、critical 视觉缺陷率不升高、P95 总耗时有可解释改善。

## 不实施的方案

- 不增加盲目重试次数；此前三次格式拒绝只增加约 15 秒，不是主要长尾来源。
- 不放宽 SHA、唯一匹配、局部 patch 和原子写入校验。
- 不直接关闭首轮 reasoning；先减少重复决策和无关输入，再单独比较不同 `reasoning.effort`。
- 不解析 assistant 正文中的伪工具调用。
- 不把所有视觉 warning 变成修复任务。
- 不把 `parallel_tool_calls=True` 解释成所有工具都可同时执行。
- 不开展多脚本改造，不为了更早调用工具而交付不可运行骨架，也不增加规划调用掩盖累计推理增长。
- 不把可视化样本当成分析样本，不把缓存命中低直接定性为长推理根因。

## 测试与验收顺序

1. R1–R4.1 已完成的代码只保留现有定向证据；不重复运行未受影响的完整测试或完整报表。
2. 对代码改动运行 `git diff --check` 和目标文件 Ruff；本轮仅更新 Markdown 时只核对文档差异、路径和方案一致性。
3. 先按 R7.1、R7.2 分别完成 schema、确定性交叉校验和定向测试；分析与可视化不得合并成一个契约或一次模型调用。
4. 执行前健康探针成功后，按 R7.3、R6 从 planner 前的冻结章节输入开始做分析与可视化各自的单变量对照，保存原始 usage、样本版本和失败信息；现有 Coding payload 仅用于身份/质量回归，连续超时期间不盲目重试。
5. 沿用 R5 记录的单脚本身份契约；涉及任务/脚本身份或协议变化时运行受影响的混合工具、作用域和精确编辑测试，确认整体校验、顺序执行、失败停止和回执回放。
   CodeMode 的 C1–C4 使用同一套记录：C3 的公开上下文/结构化结果契约验证是桥接和 ResultStore 上线前置条件；若不满足则停止该分支，R1–R7 继续。
6. 定向指标通过后，仅在需要验证集成时做一次完整 CLI；不重复完整报表作为日常性能探针。

最终验收必须同时满足：

- 首轮脚本仍可直接 `write_script`，不产生无效 `read_script` 往返。
- 已有脚本只走精准 `edit_script`，不能退回完整重写。
- 记录未经宿主修正的 free-form 原始协议正确率，并确认其相较当前基线不下降；错误信封不得触发额外模型重试。
- provider 多调用可被完整接收；所有调用按 provider 返回顺序执行。
- patch 冲突能给出当前/期望 SHA 和明确 `read_script` 动作。
- 首次修复成功率、critical 视觉质量和 P95 总耗时均有可追踪证据。
- 分析与可视化分别有实测证据；按章节确定任务范围，沿用宿主签发的单脚本身份、输出和 patch 契约，原分析项和产物身份始终保持准确。
- 验收包含上游规划及 Coding 的累计 reasoning 与总耗时，不能只缩短首轮或把长推理转移到另一阶段。
- 核心结论以 reasoning tokens 及其长尾为主；缓存命中、输入字节数、工具数量和首个工具时间只作为解释变量，不能替代目标指标。
