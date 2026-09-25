# 报表 Coding 性能与一次成功率优化实施计划

> **执行说明：** 由主 agent 使用 `superpowers:executing-plans` 按任务逐项实施并负责最终判断、冲突检查和计划更新；边界清晰、互不修改同一文件或共享运行状态的只读调查、测试审计和独立实现可交给同模型子 agent 同时进行。存在数据依赖、共享 provider 配额、同一冻结样本或同一文件写入的任务继续串行。以“本轮重新规划”的 R1–R7 为性能主线；下文 C1–C4 是与其共用指标和回放的 CodeMode 优化任务，按依赖和收益推进。原任务 1–10 保留为历史实现与验收记录，不按旧优先级重复实施。步骤使用复选框（`- [ ]`）跟踪。

**唯一核心目标：** 减少分析与可视化 Coding 的 reasoning 时间及长尾，并降低包含上游规划在内的任务总耗时；保留首轮 reasoning、首次成功率、精准局部 patch 和报表质量。章节任务范围、输入压缩、计划字段、缓存和 effort 都只是实现手段，不以输入更短、首个工具更早返回或架构重构本身作为成功标准。

**最新执行约束（2026-09-23）：** Coding 默认 low，取代此前仅用 high 的要求。生产 `analysis_script` 与 `visualization_script` 默认 `reasoning.effort=low`，思考保持开启；已有编译、执行及视觉失败恢复策略仍升级 high。用户补充允许 planner 使用 low：`AGENT_REPORT_PLANNER_REASONING_EFFORT` 支持 `low/high/max`，未显式设置时仍默认 high，不将“允许 low”解释为强制切换默认值。Responses 保留 `reasoning.summary=auto` 和 `parallel_tool_calls=true`，不添加 `thinking_budget`。此前阶段策略测试 55 passed、Responses wire 测试 8 passed 是历史验证记录，不作为本次 planner low 的验收。历史 high 样本保留；low 诊断不是严格单变量 A/B，不据此宣称稳定收益。

### 当前配置与文档对齐（2026-09-23）

| 配置或阶段 | 当前约定 |
| --- | --- |
| Coding | 默认 low；首轮思考保持开启 |
| `_run_planner` 路径的 Workflow planner | 可配置 low/high/max；默认 high；启用思考的首轮使用配置值 |
| 请求标准化、提纲等初始 off 阶段 | 保留 off，不因 planner 配置 low 而开启思考 |
| 失败恢复 | 命中既有恢复条件时仍采用阶段 high/max 策略；不增加重试次数 |
| Chat budget 与 Responses | 保留既有 Chat 阶段预算逻辑；不把它写成 Responses 参数或已验证的 reasoning token 硬上限 |

### 已落地的 reasoning 长尾控制机制（2026-09-23 汇总）

以下 P0 机制已代码落地并通过定向测试。真实 provider 效果仍需冻结回放的配对 A/B 验证。

| 机制 | 位置 | 作用 | 测试状态 |
| --- | --- | --- | --- |
| Coding 默认 `reasoning.effort=low` | `runtime/settings.py`、`model_policy.py` | 减少首轮和常规轮次的推理量 | thinking policy 58 passed + settings 50 passed |
| Planner effort 可配置 | `base.py`、`settings.py` | 支持 `AGENT_REPORT_PLANNER_REASONING_EFFORT=low` 切换，默认 high | planner contracts 127 passed |
| Compact continuation | `code_generation.py`、分析/可视化路径均开启 | 修复轮用干净会话重连，不携带完整历史 | code continuation 定向测试通过 |
| 视觉修复 critical-only 回执 | `code_agent/delivery.py` | 非阻断 warning 不进入修复上下文，减少 patch 范围 | delivery 测试通过 |
| 修复轮 facts 投影（B1） | `code_generation.py::_repair_task_facts` | 修复轮只保留脚本路径、输出契约、必要 facts | code input 61 passed |
| 动态 `codingRequirements` | `analysis_item_workflow.py`、默认 candidate | evidence planner 签发计算要求，Coding 直接实现 | fixed phase workflows 测试通过 |
| 错误回执 AST 函数级定位 | toolkit | 失败时给出函数级修改范围和源码片段 | code diagnostics 测试通过 |
| 确定性首轮预执行 | `code_generation.py` | 已有脚本先宿主运行一次，省一轮模型请求 | 定向测试通过 |
| `parallel_tool_calls=true` | protocol、默认开启 | 允许 provider 最大化批量返回工具调用 | mixed call 测试 4 passed |
| `view_image` 关闭 thinking | `vision.py` | 视觉审查用 Chat + no thinking | vision 集成验证通过 |
| Context 压缩保护 incomplete batch 与失败身份 | `context_management.py`、`code_agent/protocol.py`、`toolkit.py`、`delivery.py`（2026-09-23 新增） | 部分完成的工具调用批次不被压缩删除；未解决失败 callId 与代表当前源码的 read 轮次受保护，结果 SHA 已过时的 read_script 轮次被丢弃 | context 57 passed + agent projection 35 passed + 失败身份定向 3 passed |
| 同一 arun 确定性历史摘要与元数据预算 | `context_management.py`（2026-09-23 新增） | 旧 custom 调用改写为固定结构摘要（tool/status/code/SHA/bytes/callId/nextTools），单摘要 8 KiB、整批 32 KiB 两级预算，0.60 token 门禁先于 0.75 窗口重建触发 | context + reasoning replay 77 passed，相邻文件 180 passed |
| 视觉审查阶段开放 submit_script | `delivery.py`、`toolkit.py`（2026-09-23 新增） | 审查最后一张图后模型可直接提交，省一轮 view_image→submit 的模型往返 | delivery 测试通过 |

如需 planner low，在 `.env` 中设置 `AGENT_REPORT_PLANNER_REASONING_EFFORT=low`；`.env.example` 继续展示默认 high。本轮不自动修改用户的 planner 环境配置。

- 配置链路：环境配置 → runtime 构造校验 → planner 的 `ThinkingPolicyConfig` → 每次调用的 `ThinkingRequest` → 阶段决策 → Chat 请求参数。修复此前构造参数只校验、不参与调用级 effort 决策的问题。本轮覆盖请求标准化、数据理解、指标语义、提纲、分析计划、分析补证、分析摘要与 SQL 规划的八个 Agent；2026-09-23 复核确认可视化规划（`analysis.py`）与章节规划（`sections.py`）的 `ThinkingRequest` 构造路径同样已接入该配置。
- 验收：配置与请求链路定向测试 17 passed，思考策略回归 58 passed；覆盖 low/high/max 的首轮请求参数、已有 schema 失败恢复，以及初始 off/全局关闭策略。离线测试仅证明参数传递和策略，不证明 provider 已接受或性能改善。
- 范围边界：可视化规划与章节规划路径已接入同一 planner effort 配置并有请求级定向测试；默认仍为 high，不把“已接入”写成“全部 planner 已切换 low”，真实收益仍待配对回放。
- 待完成：冻结同一输入，保持 Coding 配置不变，仅改变 planner effort，采集完整成功回放与实际 usage、总耗时、首次成功率；未取得配对样本前，不宣称 planner low 已解决 reasoning 长尾。

**输入精简实验结论：** 曾尝试首轮省略 `outputContract.example`，保留 schema、rules、全部业务事实与任务 actions。high 回放 `/tmp/reporting-analysis-high-noexample-20260922.json` 首轮仍为 `577.237s / 42,445 reasoning tokens`，总 Coding `587.808s / 42,715 reasoning tokens`，虽一次通过但相较目标没有性能收益；示例仅减少约 278 字节，不能解决长推理。因此已撤销该改动，避免削弱输出契约的示例参照。后续不再做类似表面删提示实验，转向动态 `codingRequirements` 是否能减少模型自行规划的单变量评估。

**动态要求 high 对照已完成：** 同一 `/tmp/reporting-r7-analysis-v2`、模型、`high`、summary=auto、enable_thinking=true、parallel_tool_calls=true 下，仅将 evidence planner 输出的动态 `codingRequirements` 投影给 Coding，结果 `/tmp/reporting-analysis-high-candidate-20260922.json`：首轮 `207.725s / 16,395 reasoning tokens`，总 Coding `214.629s / 16,430 reasoning tokens`，`write_script → run_script → submit_script` 一次通过，`rawProtocolCorrect=true`。相对历史 legacy 样本 `577.237s / 42,445` 有明显性能信号，但两者不是严格同版本配对，不将 64.0%/61.4% 作为发布承诺；结论限定为“动态要求显著降低本次 high 样本的首轮推理”。

**生产切换：** evidence planner 默认 schema 改为 `AnalysisEvidenceDecision`，默认指令要求签发 `codingRequirements`；无显式 benchmark projection 时，分析 Coding facts 默认投影动态要求，且脚本 Agent 使用对应的 `codingRequirements` 指令。显式 `BenchmarkVariant.LEGACY` 仍保留给历史回放。动态要求只引用当前授权 dataset、字段、计算说明和输出名，主题、维度与指标仍由当前任务 planner 决定，不固化收入算法。受影响契约测试通过；较大 planner 测试文件仍有既有 `SimpleNamespace` 缺少 `session_state` 的替身阻断，未修改生产代码迁就。

**candidate 质量复核：** warning 指令后的 `/tmp/reporting-analysis-high-candidate-warning-20260922.json` 工作区 `/tmp/reporting-visualization-replay-k0lwm62h` 的两份 CSV 与冻结数据一致；按原始 CSV 独立聚合动态维度和总体结果，核对 `754` 个数值、覆盖集合和 null，全部一致；10 个 reconciliation 全部为 true；日间治疗中心、脑病中心、财务处三类单侧缺失均出现在 warnings。该样本首轮 `231.939s / 19,399 reasoning tokens`，总 Coding `238.797s / 19,417`，仍一次成功；相对 candidate 基线有 provider 波动，但仍保留明显低于 legacy 的信号，不把单次差异当作新收益。

**架构：** 按章节确定 Coding 任务范围，分析与可视化仍是分开的阶段；保留分析项的事实、证据和验收身份。沿用现有每个 Coding task 绑定一份正式脚本的宿主契约，不开展多脚本规划或改造。保留 Agno 负责模型请求、消息回放和工具协议映射；Reporting 宿主负责脚本身份、SHA、patch 原子应用、工具调用校验和交付状态。provider 可以一次返回多个结构化工具调用，宿主先整体校验，再按 provider 返回顺序执行。

## Codex 源码复核：reasoning 长尾的实际控制机制

2026-09-23 对 `/home/junge/pros/codex/codex-rs` 进行了源码复核。以下结论来自实际源码，不是根据 CLI 表现推测：

| Codex 源码位置 | 已确认机制 | 对本项目的直接含义 |
| --- | --- | --- |
| `core/src/session/context_window.rs` | 统计 `active_context_tokens`，按 `model_auto_compact_token_limit` 和完整模型窗口分别判断阈值；支持按完整上下文或 compaction 窗口前缀之后计数 | Coding 请求必须在 provider 调用前测量累计输入，而不是等模型长推理后再处理 |
| `core/src/compact.rs` | 自动 compaction 以独立任务运行，生成 `ContextCompactionItem`，替换历史后继续原任务；中途 compaction 会重新注入必要初始上下文 | 不能只把 `compact_continuation` 放在外层第二轮；同一 Coding run 也要有阈值触发的精简 continuation |
| `core/src/compact_token_budget.rs` | 达到 token budget 时可以直接建立新的 context window，不必再次调用模型总结；仍执行 compaction 生命周期和 hooks | 对固定结构的 Coding 历史，可先使用确定性摘要；只有无法安全摘要时才调用摘要模型 |
| `core/src/session/auto_compact_window.rs`、`core/src/session/mod.rs` | compaction window 有 window id、prefill token、previous/current window 状态，可恢复和审计 | 每次压缩需记录窗口编号、压缩前后 token、源码 SHA、任务状态，避免旧回执混入新窗口 |
| `protocol/src/models/executed_tool_calls.rs` | 工具调用参数单项有 8 KiB 上限；完整执行元数据有 32 KiB 上限；超限按“结果元数据 → 来源证据 → 调用细节”顺序降级，并可优先保留最近调用 | `write_script/edit_script/read_script/run_script` 的历史正文不能无限回放；需保留当前/最近失败调用原文，旧调用改为 SHA、字节数、状态和 reload hint |
| `core/src/tools/executed_tool_calls/request_metadata.rs` | 在请求组装阶段统一附加并再次执行元数据预算，工具执行本身与请求预算分离 | 压缩必须发生在 provider 请求组装层，不应改变工具真实执行或交付校验 |
| `core/src/session/step_settings.rs`、`protocol/src/config_types.rs` | reasoning effort 是独立请求配置，可按会话/阶段覆盖；没有以 `thinking_budget` 作为通用硬上限 | 继续使用 `reasoning.effort` 与 `reasoning.summary`；不引入 Responses 不支持的 `thinking_budget` |
| `protocol/src/models.rs`、`core/src/compact.rs` | compaction 作为结构化历史项保存，保留响应/工具身份和恢复信息 | 不得删除 reasoning item、custom/function call identity 或伪造工具结果来“压缩”上下文 |

### 源码确认后的实现方案

当前真实回放已经从 `552.446s / 28 requests / 30,486 reasoning tokens` 降到 `423.057s / 20 requests / 25,569 reasoning tokens`，但仍出现单请求 `15,717 reasoning tokens`。原因是现有 compact continuation 只覆盖外层第二次 Agent run；同一 `arun()` 内部的 custom tool 历史仍逐请求增长。后续实现按 Codex 的边界补齐：

1. **请求前 token 门禁。** 在 `smart_reporting/reporting/code_agent/protocol.py` 的 Coding 请求投影完成后，计算当前输入 token 和工具元数据字节数；达到 Coding 专用阈值时，禁止继续携带完整旧历史，先进入压缩流程。阈值必须低于 provider 的硬窗口，初始值通过冻结回放校准，不把模型上下文上限直接当业务阈值。
2. **确定性历史摘要。** 在 `smart_reporting/reporting/code_agent/protocol.py` 或独立的同目录小模块中，对已完成的旧 custom 工具调用生成固定结构摘要：`tool`、`status`、`code`、`sourceSha256`、`patchSha256`、`bytes`、`callId`、`nextTools`。当前调用、最近一次未解决失败、最新 `read_script` 结果保留原文；旧的完整源码、patch、stdout/stderr 只保留在 Workspace 和审计文件中。
3. **新窗口 continuation。** 在 `smart_reporting/reporting/workflow/runtime/code_generation.py` 中复用现有 `compact_continuation` 机制，增加“同一 run 内压缩后重新 arun”的状态；新请求只携带任务边界、最新 facts/diagnostic、当前源码 SHA、压缩摘要和 delivery state。不得调用 `acontinue_run` 回放完整旧历史。
4. **调用身份完整性。** 压缩历史仍保留原 `call_id`、工具名、执行状态和结果匹配关系；前序失败时继续补齐未执行调用的结果，不执行伪造的副作用。Responses reasoning item 只在 provider 要求的调用链中保留，不能简单删除。
5. **工具元数据预算。** 对齐 Codex 的两级预算：单个旧工具参数摘要上限 8 KiB，整批 Coding 历史元数据上限 32 KiB。超过预算时优先丢弃已解决结果的 stdout/stderr 和来源证据，最后才缩减旧调用摘要；当前失败和最近源码身份不得丢弃。
6. **阶段级 effort。** Coding 默认继续 `low` 且首轮保持 thinking；planner、复杂首次规划和明确升级的修复阶段按现有策略运行。`view_image` 保持关闭 thinking。不要用提高/降低 effort 替代上下文压缩，也不要新增 `thinking_budget`。

**2026-09-23 实施状态：** 第 1、2、5 项已在 `context_management.py` 落地（子 agent 实现，主 agent 复核）：`project_with_metrics` 在窗口重建前增加 0.60 token 门禁（`CODING_CUSTOM_HISTORY_TOKEN_THRESHOLD`，取 0.75 重建阈值与 0.50 rebase target 的中位，未经冻结回放校准），命中后先把已完成的旧 `write_script`/`edit_script`/`run` 调用改写为固定结构摘要（`tool/status/code/sourceSha256/patchSha256/bytes/callId/nextTools`，stdout/stderr 与源码证据只留 Workspace），并执行两级元数据预算（单摘要 8 KiB、整批 32 KiB；降级顺序为结果回执 → `nextTools` → 从旧到新削 `code`/SHA）；摘要后回落到 0.75 以下则不再整轮丢弃。当前调用、`protected_call_ids`（未解决失败与当前 read）、incomplete 调用保留原文；call identity、reasoning item 与 canonical 历史不变，wire 仍为原生 `custom_tool_call`。新增 `metadata_bytes`、`truncated_calls`、`compaction_tokens_before/after` metrics。自有测试文件 77 passed，相邻受影响文件 180 passed，ruff 与 diff 检查通过。极端情形（>约 110 个旧调用）下摘要最小体积本身会超 32 KiB，如实记录后交既有 0.75 重建兜底。

**2026-09-23 第 3 项已落地（子 agent 实现）：** `code_generation.py` 的同 run 压缩 continuation 作为现有 `compact_continuation` 开关（默认关闭、生产不传入）的自然扩展：窗口结束后用该窗口逐请求指标评估触发（任一请求 `inputTokens` ≥ 默认 hard cap × 0.60，或防御性消费投影层压缩标记），重连走同一 Agent `arun(add_history_to_context=False)`，任何路径不调用 `acontinue_run`；重连次数封顶 2 次，预算/工具数兜底；payload 含任务边界、`_repair_task_facts`、diagnostic、delivery state 与 `compaction` 块（windowId/beforeTokens/sourceSha256/summarizedToolCalls/nextTools）；验收字段 `compactionTriggered/BeforeTokens/AfterTokens/WindowId/retainedCallCount/truncatedCallCount` 已写入 coding metrics 与失败 details，unknown 语义保持。新增 5 用例 + 定向回归 127 passed；HEAD 既有 4 个 seed 预执行失败经 HEAD 版本对照确认无关。已知缺口：重连只能发生在 arun 交还控制权的边界（单次 arun 内逐请求增长由投影层 0.60 门禁负责）。**第 4 项四组真实对照仍未实施**。

**2026-09-23 接线与门禁校准已完成（主 agent 实施）：** 此前两个缺口均已闭环——
- 投影 metrics 接线：`protocol._project` 每轮把有界投影快照（`compaction_triggered/compacted_calls/metadata_bytes/truncated_calls/compaction_tokens_before/after/projected_estimated_tokens/window_rebased/dropped_complete_rounds`，全部 int/bool）暂存并在下一次请求的 requestMetric 中一次性消费（同步 invoke 路径丢弃，不错误归属）；run 级压缩信号与 `truncatedCallCount` 的防御性消费自此生效，回放结果 JSON 的逐请求 requestMetrics 也会携带这些字段。边界：阶段 settlement 的 requestMetrics 归一化是白名单（requestIndex/providerRequestId/durationMs/status/toolCalls 等），投影字段不进入 `modelMetricsByStage` 持久化，属有意保持的有界契约。
- 门禁校准：校准分析（子 agent 只读报告）显示 25 请求样本输入 min 7,816 / 中位 16,252 / p90 21,207 / max 30,640，锯齿缓升且由投影剪枝收敛，**input 与 reasoning 的 Pearson 相关 −0.057（无相关）——压缩解决的是历史体积与协议安全，不能宣称降低 reasoning**；历史最差续修观测 74,711。按比例派生的 0.60×hard_cap≈118K 永不触发。据此新增绝对门禁 `CODING_COMPACTION_INPUT_TOKEN_GATE = 20_000`（取样本 p75–p90 下沿，长修复链后半程触发、首轮与短任务不触发，安全下界 18K、≤16K 否决），实际门禁取 `min(hard_cap × 0.60, 20_000)`，小窗口模型仍受比例约束；`code_generation.py` 的 `RUN_COMPACTION_INPUT_TOKEN_THRESHOLD` 同步为同一值。在该样本上触发率为 7/25（第 15 轮起）。接线与阈值新增 3 个定向用例，合并回归 85 passed，ruff 与 diff 检查通过。20,000 为单一长链样本校准的初始值，需四组对照按首次 patch 应用率与 P50/P95 再微调。

### Codex 对齐方案的验收标准

**2026-09-23 四组对照战役已完成（25 次真实回放、23 个非删失样本、0 真删失，产物在 `.local/reporting-validation/compaction-ab-20260923/`）。** 执行中修正了两处实验口径：删失判定改为"仅 wall-timeout/无完整结果"（exit 1 + 完整 metrics 记为非删失失败样本）；G1 基线语义修复为 B0 生产的强制 rebase（修复前的 g1-1..3 改记为 `aux-never-compact-*` 辅助样本）。结果与结论：

| 组 | 交付率 | 峰值输入形态 | 备注 |
| --- | --- | --- | --- |
| G1 真基线（强制 rebase） | **0/5** | 11–24K 振荡、峰值 ~15–40K | 旧生产行为在本任务上本身脆弱 |
| G2 仅摘要 | 2/5 | P50 峰值 ~51–59K | |
| G3 摘要+continuation | 2/5 | 同上 | continuation 零覆盖（见下） |
| G4 全量 | 2/5 | 峰值最高 144,951 | 元数据预算无可分辨效果 |
| aux 永不压缩（辅助） | **3/3** | 61–87K | 输入最大却全部通过 |

- **验收逐条对照：** 压缩后下一请求确实只含摘要+当前上下文（字节层 33KB→6–7KB/次、truncated_calls 恒 0，达标）；压缩前后 call_id/工具名/状态/SHA 一致、无伪调用（达标）；质量四指标 G2–G4 相对 G1 不劣化（patch 1–2/5 vs 2/5、首跑 0 vs 0、交付 2/5 vs 0/5、critical 1–2/5 vs 2/5，噪声级，按门槛通过）；四组 ×5 样本已采集（达标）；验收字段齐全（达标）。
- **但核心结论是否定性能预期：** ① provider 实际输入在摘要组仍线性增长（g2-4：7.8K→109,483，33 次压缩无效），因为 DeepSeek 契约要求的 reasoning 回放与图像 token 不在摘要作用域——**摘要压住了 custom history 字节，压不住 provider 输入**；② 输入大小与交付成败无同向关系（aux 输入最大却 3/3 通过，真基线输入最小却 0/5），与校准报告的 input↔reasoning 无相关结论互证；③ 失败模式（custom_tool_protocol_error×6、model_request_limit×4、script_edit_invalid×3、no_submission×1，四组均有）是模型协议行为长尾，与摘要触发无时间序关联。**因此压缩机制不推广为性能手段，保留为协议安全网（窗口保护、调用链完整性）；性能主线回到首轮重复规划（动态 requirements 方向）与 low 档方差治理。**
- **战役暴露的口径问题（后续验收采纳）：** continuation 在 10 个 G3/G4 样本中 `compactContinuationApplied` 全 false——所有失败都是错误终止而非"模型干净提前结束"，该特性价值本战役无法评价；`firstRunSuccess` 全 23 样本 false（首跑系统性命中 declared_output_missing 软拒绝），不宜作验收门禁；n=5 且组内方差极大（G1 同组 508s/22K reasoning 到 887s/49K），所有性能数字仅描述性。**`rawProtocolCorrect` 恒 false 已按口径 (c) 修复（2026-09-23）：** 战役量化显示 166 次信封归一化（97% 集中在 edit_script 大 payload、首轮从不出现），其中 17/23 样本的 false 完全由单层 data 信封兼容解封造成，仅 6 个样本有真违规（阶段范围 declaration mismatch，G4 占 3 个——被淹没的真实信号）。现将信封解封从协议违规拆分为独立指标 `envelopeNormalizedInputs`（budget/模型访问器/codingMetrics 透出），`rawProtocolCorrect` 只统计真违规（未声明/类型不符/重复身份/伪调用/多层信封仍记 false）；解封边界不变（仅单层、键恰为 `{"data"}`、内层带合法前缀），不引入 DashScope 会 400 的请求侧加固。测试锁定：metrics 49 passed + interactive/scope 定向通过。

- 同一冻结任务中，连续请求输入 token 不得线性增长到完整源码大小；触发压缩后下一请求必须只包含摘要和当前必要上下文。
- 压缩前后 `call_id`、工具名、成功/失败状态、源码 SHA 和交付状态一致；不得出现伪工具调用、重复副作用或协议回放错误。
- 首次 patch 应用率、首次运行成功率、最终交付成功率和 critical 视觉缺陷率不得下降。
- 至少比较四组同输入回放：当前基线、仅请求前摘要、摘要加新 continuation、摘要加新 continuation 加元数据预算；每组至少 5 个非删失样本，记录 P50/P95 的总耗时、请求数、输入 token、reasoning token 和压缩次数。
- 失败时报告 `compactionTriggered`、`compactionBeforeTokens`、`compactionAfterTokens`、`compactionWindowId`、`retainedCallCount` 和 `truncatedCallCount`；未知 usage 保持 `unknown`。

### 不采用的伪对齐方案

- 不把 `reasoning.summary` 当作 reasoning token 上限；它只影响摘要输出。
- 不把 `parallel_tool_calls=True` 当作执行并行保证；顺序敏感链路仍由宿主串行执行。
- 不直接删除所有旧消息、reasoning item 或 tool call output；这会破坏 Responses 调用链。
- 不把 Codex 的远程 compaction 实验接口直接移植到 Agno；先实现本地确定性摘要和已有 runner continuation。
- 不用更大的 tool/request limit 掩盖上下文增长；预算扩大只会增加长尾。

**收尾校正：** warning 样本实际有 9 项 reconciliation（上文 10 项为旧样本数），均为 true；独立复算为 754 个数值/null 检查，类别覆盖另行核对。其 planner 耗时 `69.414s`、reasoning `5,573`，加 Coding 后总回放 `308.259s`、累计 reasoning `24,990`，不能仅以 Coding 的 `238.797s / 19,417` 宣称整个流程已达到 300 秒/20k 目标。两次 candidate 回放重新运行了 planner，facts 指纹不同；warning 提示效果也不是严格单变量证据。保留性能改善信号，跨主题稳定性和同版本配对仍待验证。

**可视化 critical-only high 验证：** 已修复 `_visual_review_model_receipt()` 的可选建议泄漏：未关联 critical issue 的 `suggestions` 保留完整审计回执，不再发送给 Coding 模型。定向交付测试 `30 passed`。使用 `/tmp/reporting-visualization-v2-Pfuhj1/repair/payload.json` 和 manifest 自动加载 seed，在 `high/summary=auto/enable_thinking=true/parallel_tool_calls=true` 下真实回放 `/tmp/reporting-visual-high-critical-only-20260922.json`：6 张图批量审查后一次 `read_script → edit_script`，再运行并提交；`firstPatchApplied=true`、`firstRepairSuccess=true`、`criticalVisualDefect=false`，Coding `191.400s / 9,830 reasoning tokens`，8 次 `view_image` 审查耗时 `34.621s`。最大请求为 edit 轮 `9,166 reasoning tokens`，说明视觉阶段剩余主要瓶颈是局部修复推理；本样本无同版本未修复回执的严格 A/B，不能宣称固定降幅。

**严格 Coding-only 对照能力：** 回放脚本新增 `--freeze-coding`，可在一次真实 candidate planner 后固化实际 Coding payload、授权输入身份、benchmark manifest SHA、variant 和指令 SHA；后续用 `--coding-only-payload` 跳过 planner，仅重复 Coding。candidate 与 legacy 均保留严格的基础 payload、输入路径/大小/SHA、脚本身份校验；candidate 必须携带动态 `codingRequirements`，不得回退到 `evidenceDecision`。结果额外记录 `codingPayloadSha256` 和 `instructionsSha256`，用于证明同一输入对照。定向回放测试 `55 passed`，Ruff 与 `git diff --check` 通过。该能力只解决后续同输入配对测量，不把历史不同输入样本追认成严格 A/B，也不证明 planner 输出来源的密码学真实性。

**视觉提示去重单图探针：** 在同一图片 SHA、同一视觉模型 `qwen3.6-flash` 下，仅比较完整 user 规则与短 user 指令；baseline `1263` 字节、`3414` input tokens、`4.826s`，candidate `69` 字节、`3165` input tokens、`2.783s`。两次均 `reasoning_tokens=0`、无 critical 缺陷，但返回的 warning 文本不同，因此只记录为输入/耗时改善信号，不宣称视觉质量等价或稳定收益；后续仍以逐图质量和总流程指标验收。视觉提示回归测试已锁定短 user 指令。

**缺失产物失败回执修正：** `report_code_declared_output_missing` 现在明确说明“声明产物不存在，不代表脚本不存在”，并指示根据 `details.path` 使用 `edit_script` 局部修复后再 `run_script`，禁止调用 `write_script` 整段重写。未声明工具调用仍由协议层 fail-closed 拒绝；该修正减少工具语义歧义，不宣称能保证模型不再返回错误工具。

**严格同输入 Coding-only 重放：** 使用 candidate planner + Coding 首次回放固化 `/tmp/reporting-r7-analysis-candidate-frozen-20260922`，随后以相同 `codingPayloadSha256=5b6c84e9af2bb302c6b4bac776ed7f06559df72391f9a4e2ef8a17adafa627f1` 和指令 SHA 做 Coding-only 重放。首次样本 Coding `232.166s / 19,074 reasoning tokens`，重放 `456.673s / 37,490 reasoning tokens`；两次均一次 `write_script → run_script → submit_script`、首次运行成功，重放 cached tokens 为 `9,216`。同输入仍出现显著 provider 长尾，说明缓存命中和动态 requirements 不能保证 reasoning 稳定下降；不追加盲目重放，也不把单次收益写成 P95 改善。

**同输入脚本复杂度漂移（口径修正）：** 慢样本首轮总 output tokens 为 42,165，其中 reasoning 37,419、可见输出 4,746；快样本分别为 21,660、19,021、2,639。总 output tokens 不能当作工具参数长度。慢样本包含更多日期解析、校验和比较输出，但仅两次观察不能证明代码复杂度导致 reasoning 长尾。后续只按证据评估签发计算范围的歧义，不新增未经验证的规划字段或固定主题算法。

**DeepSeek 官方参数核对与 low 诊断：** 官方 Responses 文档确认 `reasoning.effort` 支持 `none/low/high/max`，思考模式默认 high；`thinking_budget` 不属于 Responses 参数；工具调用思考模式要求后续请求完整回传 reasoning 内容；`parallel_tool_calls` 在 DeepSeek Responses 中被忽略且始终开启。当前实际回放 endpoint 为 DashScope，保留已验证的 custom tool wire 适配，不直接套用 DeepSeek 官方对 custom 工具名称的限制。使用同一 candidate payload 做 low 诊断（该次仍带未提交的 requirements 文案实验，故不作严格 A/B）：Coding `75.771s / 3,383 reasoning tokens`，首轮 `69.042s / 3,377`，一次成功。该段原有“high 默认保持不变”结论已被 2026-09-22 用户确认的 Coding 默认 low 决策取代；planner 仍保持 high。

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
- [x] 可视化尚未取得可前瞻采集的 planner 与 Coding 阶段 receipt，因此不填补缺失 reasoning、不计算其累计指标。（**2026-09-24 已推进：** frozen-visual-v3 首个非删失 passed 样本已前瞻采集双侧 receipt——planner 1 请求 163.1s/13,298 reasoning，Coding 331.9s/12 请求/14,951 reasoning；n=1，仍不计算累计 P50/P95，不填补缺失样本。）
- [x] 分析已按阶段和配置报告样本数、失败/终止数、P50/P95 及原始样本；P95 仅作当前小样本描述，未据此宣称稳定尾延迟改善。
- [ ] 可视化 revision-3 已取得 legacy 完整样本，candidate 协议失败，成功配对验收未完成；保留全部失败与删失记录，不美化总耗时。（**2026-09-24：** 该 revision-3 指 /tmp 旧 bundle，已随清理不可恢复并废弃；frozen-visual-v3 取代为新基线，acceptance={} 仅支持 candidate，首个 passed 样本已取得，legacy 配对在 v3 上不可得，"成功配对验收"口径需重新定义后另行验收。）
- [x] 分析成功率同时按原始协议、首次 patch、首次运行、首次修复和最终交付统计；结果结构/证据身份正确，业务对账按软告警处理。candidate 因首次运行率下降未推广。
- [ ] 可视化单次已有脚本修复样本已取得首次 patch、首次运行、首次修复和最终六图结果；完整生成 A/B 的质量率仍缺样本，不能以该修复样本替代。（**2026-09-24：** frozen-visual-v3 取得首个完整生成 candidate 样本（总 495.062s、`rawProtocolCorrect=true`、`criticalVisualDefect=false`、首跑失败后精准修复闭环），完整生成质量率仍只有 n=1 且无配对。同日第 2 个完整生成样本为非删失失败（47/47 请求耗尽，详见上方 2026-09-24 失败登记），passed 样本数仍为 n=1。）

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

R7.1 的结构契约与定向测试已完成。3 组 high-effort 对照显示 candidate Coding reasoning 下降，但 planner reasoning 上升，累计 reasoning 仍有描述性收益；由于首次运行率从 `3/3` 降至 `2/3`，该字段扩展未通过推广门槛。当时曾将生产默认回退为 legacy evidence planner/schema/Coding projection，candidate 只保留在显式 benchmark 路径。**口径修正（2026-09-23）：该回退已被后续决定取代——`eea91c3` 起 candidate 已是生产默认**（`_analysis_evidence_agent` 使用 `AnalysisEvidenceDecision` 与 candidate 指令，`_script_task_facts()` 默认 `BenchmarkProjection.for_variant(CANDIDATE)`；legacy 仅保留给显式 benchmark 回放）。当日 low 档配对（见 R6/R7.3 记录）显示 candidate 首跑率 3/3 vs legacy 0/3、主指标 P50 约 legacy 53%，与 high 档"首跑率下降"形态相反，支持现行默认；正式确认仍需扩样本与独立数值复算。**追加（2026-09-23 晚）：扩样 8 对与独立数值复算已完成，结论见 R7.3 末节"扩样 8 对 + 独立数值复算 + planner-low 配对"——主指标 P50 candidate 约为 legacy 71%、首跑率 7/8 vs 0/7、6,096 单元格零数值错误，维持 candidate 默认。**planner 增量更可能来自 `codingRequirements` 的语义拆解，不能归因于输入长度。

- [x] 分析 Coding 共用指令已明确“只执行上游签发的事实缺口和计算要求”，禁止重新规划、重新选择字段或为了验证假设读取未签发数据；新增 benchmark 指令契约测试，减少分析项 Coding 首轮的重复推理空间。该提示收敛不等同于 provider reasoning 硬上限，仍需真实分析回放验证累计收益。
- [x] 新指令后的同 bundle legacy/high 单样本已通过：总耗时 `182.748s`，planner `647`、Coding `12,341`、累计 `12,988` reasoning tokens；首次写入为第 4 次请求，`74.688s / 6,223 tokens`，首次运行成功。前三轮探索请求合计约 `86.55s / 6,093 reasoning tokens`，仍与写入阶段相当，因此单纯追加“不重复规划”提示没有消除探索往返，不能宣称 reasoning 已改善。该样本的逐请求快照确认 `summary=auto`、顶层 `enable_thinking=true`、`max_output_tokens=65536`、`parallel_tool_calls=true` 均实际进入请求。

- [x] 按质量门槛回退分析生产默认：`_analysis_evidence_agent` 使用 `LegacyAnalysisEvidenceDecision` 和 legacy 指令，生产 `_script_task_facts()` 默认只投影 `evidenceDecision.missingFacts`；显式 candidate benchmark 仍投影已校验的 `codingRequirements`。受影响组合回归 `124 passed`，Ruff 与 compileall 通过。（**已被取代：** `eea91c3` 起生产默认恢复为 candidate，见上一条的 2026-09-23 口径修正。）

#### R7.2：可视化 Coding 直接接收图型意图和受信数据绑定

**契约：** `ChartDraft` 只增加 `visualForm` 和 `dataBindings`。`visualForm` 是简短图型描述，不规定配色、尺寸、标注位置或具体绘图库 API。每个 binding 仅含 `analysisId`、`factPath`、`dataPath`、`fields` 和 `role`，必须逐字引用本轮 `visualizationFacts` 已存在的 descriptor；不得由 planner 自由生成文件路径或 JSON 路径。所有可绑定 descriptor 必须显式声明自己的字段集合，宿主不得根据路径名称或事实内容猜测字段。

- [x] 先在 `test_reporting_phase_models.py` 写 schema 失败用例，要求每张图具有非空 `visualForm` 和至少一个 binding；拒绝空字段和重复 binding；未知 descriptor 字段由 Coding 前的确定性交叉校验拒绝。保持 renderer、输出路径、标题、期间、citation、metric 和 comparability 的现有行为。
- [x] 确认现有可视化规划请求携带完整 facts descriptors。由 `analysis.py` 的确定性投影为 metric、derivedMetric、comparison 和 supplemental finding 的每个可绑定 `dataPath` 明确列出 `fields`；生成器指令只能从 descriptor 复制 `analysisId`、事实文件 path、`dataPath` 和 `fields`，不能猜测。
- [x] 在 `visualization_section_workflow.py` 增加纯确定性交叉校验：`factPath` 必须等于当前分析项 `factFile.path` 或其 `supplementalEvidenceSources[].sourceFile.path`；`dataPath` 必须等于对应 descriptor 声明的路径；`fields` 必须是该 descriptor 显式 `fields` 的非空子集。**2026-09-23 契约变更（用户拍板）：不匹配从 `report_phase_contract_invalid` 硬错误改为 loguru 软告警**（`report_visualization_binding_mismatch`，携带 chartId/绑定身份/declaredFields），对齐 AGENTS.md"语义业务校验只需要软告警"；文件访问授权仍由执行层 AST 字面路径白名单硬校验。契约测试已同步为"不抛出 + 恰好一条 WARNING + 身份可审计"（benchmark_variants 45 passed）。
- [x] 在 `analysis.py` 保证 `visualization_coding_facts()` 保留 binding 所引用的 descriptor 和文件身份，但不重新加入 summary、warnings、规划叙述或未引用的完整事实数据。计划和 Coding facts 使用相同受信来源，避免模型按标题二次定位；提交注册时剥离 `visualForm` 和 `dataBindings`，不扩展严格交付契约。
- [x] 更新可视化 Coding 指令：逐图实现 `visualForm` 和 `dataBindings`；Coding 仍自行决定布局细节和函数组织，沿用宿主签发的单脚本身份契约。不得把 `role` 扩展成通用 Vega/Plotly DSL。
- [x] 定向验证：phase schema、读取路径、渲染注册、V1 workflow 和 repair knowledge 合计 `84 passed`；无效 binding 与生成器指令节点 `5 passed`；目标文件 Ruff、compileall 和 `git diff --check` 通过。

R7.2 的结构契约与定向测试已完成，但这只证明 Coding 收到现有 planner 已决定的图型意图和受信数据定位，不能证明 reasoning 已下降。下一次受控真实回放必须按 R7.3 比较 visualization planner、首次写入和后续修复的累计 reasoning；若累计 reasoning 或总耗时没有下降，回退这些新增规划字段，不以 Coding 单阶段 token 下降作为保留依据。

#### R7.3：先验收累计 reasoning，再调整缓存和 effort

- [x] 已完成 schema、确定性交叉校验、分阶段 usage 观测、Coding-only v1 可携带 bundle、planner+Coding v2 bundle 契约/校验器和定向测试；已从真实 planner 前章节输入确定性提取并验证分析 v2 bundle `/tmp/reporting-r7-analysis-v2`。此前两个 900 秒删失样本仍不计入 P50/P95；可视化 v2 bundle 仍因缺少可信 `dataDescriptors` 和审核过的 `visualForm/dataBindings` 而阻断。
- [x] 已增加受签名的 analysis Coding-only 联结入口：同时校验 v1/v2 bundle、基础 facts 与授权输入 SHA，复用 v2 modelConfig 和 legacy Coding 指令，结果明确标记 `benchmarkMode=coding-only` 且不伪造 planner metrics。新范围收敛后的单次真实 Coding-only 回放未在观察窗口内产生结果 JSON/usage，记为删失样本，不计入 reasoning 或成功率；不能把该次等待归因于 provider、Agno 或工具范围。
- [x] 分析已从 planner 前的同一冻结章节输入建立 legacy/candidate A/B，固定模型、`reasoning.effort`、`reasoning.summary`、`enable_thinking` 投影、facts 身份、单脚本身份和验收条件；A/B 在 planner 构造前分叉，未从 candidate 输出事后删除字段伪造 legacy。
- [ ] 可视化 revision-3 两侧已通过规划路径门禁，但 candidate 在修复后收到非法工具调用而失败，仍缺成功两阶段配对；协议拒绝请求的 usage 缺失不填 0，不拼接其他修复样本。（**2026-09-24：** 该非法 `edit_script` 失败样本随 /tmp 清理不可恢复，根因已由 H1 时序重建离线确认；frozen-visual-v3 candidate 已完成首个成功两阶段样本，但 v3 不支持 legacy variant，"成功配对"仍缺。）
- [x] 分析 Coding agent 的 Responses usage 已按本次 Coding invocation 写入阶段 recorder/receipt；Agno trace 父级只作为附加诊断。缺失 usage 保持 `unknown`，未用顶层混合 metrics 回填。
- [x] 分析样本记录 planner reasoning、Coding 首次写入 reasoning、修复 reasoning、累计 reasoning、总耗时和质量；主指标严格为 `planner.reasoningTokens + coding.reasoningTokens`，分析后置 `summary` 单列并计入任务墙钟。candidate 虽有累计下降，但首次运行率退化，因此不保留为生产默认。
- [ ] 可视化尚未有可配对的 planner + Coding 阶段 receipt；不得使用历史 trace 的 completion 或模型耗时补填 reasoning。（**2026-09-24：** frozen-visual-v3 candidate 侧已具备可重复采样的 planner+Coding receipt 基线（首个样本累计 reasoning 28,249）；legacy 侧在 v3 不可得，"可配对"验收需先决定对照口径。）
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
- [ ] 可视化输入门禁已通过并尝试真实对照；两侧均在 planner 输出路径与授权集合不一致处停止，完整 A/B 未完成。不猜造字段，不修正模型路径来绕过门禁。2026-09-23 只读诊断（子 agent）：生产链路签发路径直接由 planner 输出派生，无漂移可能；漂移只发生在冻结 benchmark 门禁（`prepare_benchmark_coding_payload` 的 `_visualization_paths` 含 interactivePath 与冻结 `declared_output_paths` 严格集合相等）。最强假设为 revision-2 未声明 `visualizationMode`，`auto` 模式下 planner 选 plotly 附加 6 个 `.plotly.json` 与纯静态冻结集合不符（revision-3 补 `static` 后两侧即过门禁，方向一致但不能反推旧失败根因）；次强假设为 planner 文件名自由生成（schema 与指令均未要求逐字复制 requiredCharts 路径）。判别标准已明确：`unexpectedPaths` 全为 `.plotly.json` 且 `missingPaths` 为空即确认前者；出现改名 png 对则是后者。差集落盘机制已就位。2026-09-23 真实 planner 判别采样（探针先行、单次串行、candidate、planner 53.0s/3,836 reasoning）：差集为 missingPaths=全部 6 个签发静态 PNG、unexpectedPaths=8 个通用改名 PNG + 1 个 `.plotly.json`——**P1 不满足，P2 符合**（图表全部改名且 6→8 张，身份自由发挥），仅带 P1 弱迹象。边界：新 bundle 无历史 `requiredCharts` 身份约束（旧 prepare.py 丢失、形状未知、未伪造），改名漂移可能是无约束的直接后果，不能据此确认历史 revision-2 失败根因；n=1。新持久冻结输入已建于 `.local/reporting-validation/frozen-visual-v2/`（version 2 bundle、3 份授权 facts 原始字节、validate-only 通过；支持 candidate planner 单变量 A/B 与输出形态重复采样；不支持 legacy variant、不与旧 revision 直接配对）。完整链四组回放仍需先重新定义并审核等价的图表身份约束，否则门禁必然拦截。（**2026-09-24 收口：** 等价身份约束已以 requiredCharts 形状首次定义并审核，契约生效验证、v2 删失根因闭合与 v3 重建及首个 passed 样本见下方两段 2026-09-24 记录；本行保留为诊断历史，"完整 A/B 未完成"状态不变。）

**2026-09-24 requiredCharts 身份约束契约已落地（新形状首次定义，非恢复旧形状）：** 形状 `{"chartId", "sourcePath", "interactivePath"}`，从冻结 `declared_output_paths` 确定性派生（chartId=文件名 stem；本 bundle 全静态 PNG 故 interactivePath=null），审核记录见 `.local/reporting-validation/frozen-visual-v2/NOTES.md`。实施点全部为 benchmark-only（生产链路授权集合由 planner 输出派生，无漂移，不注入）：bundle 完整性校验 `benchmark_bundle.py::_validate_required_charts`（validate-only 即生效）；可视化 benchmark planner 双 variant 身份约束指令 `_VISUALIZATION_BENCHMARK_IDENTITY_INSTRUCTIONS`；签发后绑定级校验 `benchmark_execution.py::_validate_required_charts_identity`（chartId 集合相等 + 逐 chart 路径逐字相等，在既有 declared_output_paths 差集门禁之前，改名即拒并落盘 missingChartIds/unexpectedChartIds/pathMismatches）。frozen-visual-v2 bundle 已重建（旧件保留 `bundle-no-requiredcharts/`），validate-only 通过；定向测试新增 10 用例，228 passed + ruff clean。**真实全链验证（candidate，单次串行不重试）：planner 1 请求 158.5s/12,973 reasoning 逐字签发 6 个冻结图表身份，两道门禁全部通过、进入 Coding——契约生效证实**。Coding 首写成功（383.8s/31,103 reasoning）但脚本引用 bundle 未包含的 `evidence/analysis_003/attempt-1/supplement.json`（物理字节不可恢复，NOTES 已记录）触发 FileNotFoundError，模型按"不得以占位数据替代"fail-closed，15 请求修复未果，wall-timeout 1041.5s 删失（censored=true，phase=coding，rawProtocolCorrect=true）。删失根因是冻结输入不含 supplement 字节（已知边界），与身份契约无关；后续完整链 A/B 需先决定 Coding 数据源口径（facts 内联数据足够时指令约束脚本不得读 supplement，或接受该删失率）。（**2026-09-24 补充：** requiredCharts 仅适用于 visualization bundle，analysis bundle 携带即在 `_validate_required_charts` 直接拒绝；回放路径接线（planner_request 透传与身份门禁生效）、interactivePath 非空正反向、legacy variant 门禁、门禁顺序与执行层畸形条目均已补定向测试，组合 135 passed。）

**2026-09-24 数据源口径决策与 frozen-visual-v3 重建（用户拍板：重新 harvest 完整输入）：** v2 删失根因调查已证据闭合——planner-request 的 `visualizationFacts` 声明 analysis_001/003 两个 `supplementalEvidenceSources`（完整院区/科室/收入构成/门诊住院聚合 findings 描述符），但这些文件物理字节不在 bundle 且已确认不可恢复；planner 按 R7.2 契约把图表 1–4 绑到 supplement（对比/结构图最丰富的合法描述符），图表 5/6 绑到 facts；Coding fail-closed 拒伪造（运行日志含模型完整推理证实其正确识别绑定权威与不得伪造的矛盾）。计划的"facts 内联足够→指令约束"分支被证伪：3 份 facts 只有 periodValues（仅支撑趋势/拐点图）、月份×全维度复合 top-10 字符串（非干净维度聚合）、各 1 条 comparison。因此按用户决策在真实运行产物全部在场时重建：真实运行 `cli-report-65e6e54e87a4480a9e531e1bae69464c`（"2025年收入趋势分析，一个章节"，planner high/Coding low 生产默认，`REPORTING_HOST_WORKSPACE_ROOT` 指向仓库持久目录），5 份 facts + 5 份 supplement 全部在场；section 经历多轮 revision 后用户主动停止（span 与 workspace 已持久）。harvest 选 revision-3 配对（planner span `2801fbf6ef94993f` + Coding span `411ea4cc04f47ede`），走 `extract_benchmark_trace_inputs` 严格校验，`verify_facts_identities()` 对全部 factFile+supplementalEvidenceSources 做逐字节 SHA 自检且与 authorized_read_paths 集合严格相等（v2 缺失的自洽保证）；requiredCharts 从真实 declared_output_paths 派生 10 图（chart_001..010 生产 planner 真实命名，7 图带 plotly interactivePath）；model-config 冻结 Coding low/planner high（对齐 2026-09-23 生产默认）；acceptance={} 仅支持 candidate。validate-only 通过，manifest sha256 `4c27385a382220ab51c8db6ce0f6dc0aa2075c4019fe22aac0b3ad64bd5999c4`，审核记录见 `.local/reporting-validation/frozen-visual-v3/NOTES.md`。**全链 candidate 回放（单次串行不重试）首次非删失通过：`status=passed`、总 495.062s；planner 1 请求 163.1s/13,298 reasoning（requiredCharts 身份约束下逐字签发 10 图、两道门禁全过）；Coding 331.9s/12 请求/14,951 reasoning，`rawProtocolCorrect=true`、`criticalVisualDefect=false`；链路 write_script → run_script（首跑失败 `report_code_mode_execution_failed`/ValueError）→ 2 次 edit + 3 次 read 精准修复 → run_script 通过 → 10 图 view_image 审查（2 请求批量）→ submit_script。累计 planner+Coding reasoning 28,249，仍高于 20,000 首阶段目标；n=1，不宣称稳定收益。该样本证明自洽 bundle 解除可视化完整链删失，R6/R7.3 可视化侧自此具备可重复采样的真实基线；同 bundle 重复采样与配对对照可继续。真实 run 中 section 多轮 revision（4 次 attempt）本身是 planner/Coding 稳定性的新观测信号，待分析。**

**2026-09-24 可视化收敛根因分析与反占位指令修复（证据：`.local/reporting-validation/e2e-20260924.log` 全量事件审计）：** 真实 run `cli-report-65e6e54e87a4480a9e531e1bae69464c`（01:25–02:39，约 74 分钟、4 次 attempt）可视化收敛慢的直接根因已闭合：① attempt-1 模型首轮写出的是纯探索脚本——exit 0、stdout 全是 `FACTS ... keys/comparisons` 结构打印、零图表产物，宿主按 `report_code_declared_output_missing` 软拒绝（该错误全日志 32 次拒绝，构成重试主体；错误回执已正确区分"声明产物缺失≠脚本缺失"并指引 edit_script 局部修复，协议侧无缺陷）；② 模型使用 `fig.write_image()` 触发 Kaleido 缺失 ValueError，尽管公共指令已明确禁止（v3 回放首跑失败同因）；③ 分析侧无此模式——`base.py` 在 2026-09-22 已加"首轮直接实现全部缺口、禁止探索占位脚本"条款，可视化公共指令缺等价条款，两侧指令不对称是本轮回放与真实运行共同暴露的系统性诱因。修复：`bootstrap.py` 可视化公共指令追加反占位条款（首轮 write_script 直接完整实现全部图表并写出所有签发产物；禁止探索占位脚本或以打印 facts 结构、字段概览代替绘图），legacy/candidate 双 variant 均继承；指令预算测试随证据从 4500/1400 上调至 4700/1460，双 variant 契约断言已锁定。该改动为提示层修复，真实收敛收益需下轮可视化回放验证，不预先宣称；若首轮占位仍复现，再评估结构预检层对"零写出脚本"的快速拒绝。

**2026-09-24 Kaleido 依赖落地（用户拍板安装）：** `pyproject.toml` 新增 `kaleido>=1.4.0`（uv.lock 同步；连带 choreographer/logistro/orjson/simplejson），并经 `choreo_get_chrome` 下载专用 Chrome（`~/.local/share/choreographer/deps/chrome-linux64/chrome`；系统 snap chromium 无法启动已绕过）。真实验证：`fig.write_image()` 英文与中文标题 PNG 导出均成功且中文渲染无方框。可视化公共指令同步更新为"Plotly 的静态图使用 fig.write_image()（Kaleido 已随环境提供），交互产物使用 fig.write_json()"（原"不要依赖未提供的 Kaleido"条款已过期删除）；指令预算内（4618 bytes / 1451 tokens）。该变更消除了首跑 kaleido ValueError 这一类确定性失败，与反占位条款共同作用于下轮可视化回放验收。

**2026-09-24 反占位+kaleido 修复后首轮验证回放失败（frozen-visual-v3 全链 candidate 第 2 个样本，非删失失败，如实登记）：** `full-chain-candidate-2.json`，`status=failed`、总 1101.8s、失败码 `report_code_model_request_limit`（47/47 请求耗尽；可视化预算 = VISUALIZATION_TOOL_CALL_BASE + 17 declared）。Coding 47 请求/66,600 reasoning，toolCounts {edit:17, read:14, run:13, write:2}，`rawProtocolCorrect=true`、`criticalVisualDefect=false`，从未到达 view_image/submit。根因分解（证据：requestMetrics 逐请求轨迹、first-run-failure 边车源码、回放工作区现场、最终脚本手动复跑）：① **首写臆造数据契约**——首轮 write_script 即完整实现 10 图（11,484 字节，非占位脚本，反占位条款按预期生效），但无视 task 签发的 `authorized_read_paths`/`factFile` 路径，自行猜测 `input.json/source.json/data.json/raw.json` 候选文件，首跑 `FileNotFoundError`（line 29）；对照 candidate-1 首写在同一指令下直接使用签发 facts 路径，属模型采样方差而非指令缺口；② **declared_output_missing 长循环（req12–44）**——转向真实 `facts/revision-1/*.json` 后，9 次 run 全部 exit 0 但零产物，13 次 run 的 script span 均 ~3.9s，而最终脚本手动复跑（kaleido 真实渲染 10 图）需 ~183s 且产物齐全、回放前工作区零 PNG → 循环期间脚本从未真正写出任何文件；是顶层调用缺失还是图表函数静默吞错，现有证据无法区分——**回放只持久化 `firstToolFailure.code`，不落 `missingPaths/presentPaths/stdout/stderr` 与后续失败源码快照，这是已确认的观测缺口**；期间 edit 3 次 `not_found`、2 次 `invalid`，模型在 14 次 read 间空转；③ **req47 边界瞬时失败**——预算最后一次 run_script 0ms `tool_error`（Agno 层 tool_call_error、无 code，未执行），随后 request_limit 终止；replay 硬编码 cell timeout=120s < 完整脚本实际 ~183s（生产 DEFAULT_TERMINAL_TIMEOUT=900s），即使 req47 正常执行也会撞回放侧超时，回放与生产保真度不一致。结论：反占位与 kaleido 两项修复均按预期生效（首写即完整实现、最终脚本可渲染），失败源于数据契约臆测 + 修复循环空转这一不同维度；n=1 对 n=1（candidate-1 12 请求/332s passed vs 本轮 47 请求/1102s failed）方差极大，不据此宣称退化或改善。候选后续方向（未实施，先取证再动手）：失败回执详情与后续失败源码快照持久化（观测缺口）、指令显式禁止猜测未签发数据文件、replay cell timeout 对齐生产 900s、req47 边界 tool_error 无 code 的小调查。（**2026-09-24 后续：两项已实施。** ① 观测缺口闭合一半——`protocol.py` 的 `firstToolFailure` 新增有界 `diagnostics` 子字典（白名单：path/errorType/errorLine/exitCode/missingPaths≤20/presentPaths≤20/stdoutTail/stderrTail 各≤1000 字符，拒绝源码与参数），`metrics.py` 归一化层二次有界透传，下一轮回放即可直接看到 declared_output_missing 的差集与输出尾；后续失败源码快照仍未持久化，保持开放。② replay cell timeout 从硬编码 120s 对齐生产 `DEFAULT_TERMINAL_TIMEOUT`（900s，经 `smart_reporting.task_execution` 惰性导入，消除回放/生产保真度分裂）。测试：`test_reporting_code_agent_metrics.py` 51 passed（含新增归一化边界用例与 declared_output_missing 轨迹用例），`test_replay_visualization_task.py`+`test_reporting_interactive_code_agent.py` 153 passed、唯一失败为既有 `test_interactive_v1_end_to_end_responses_loop`（干净 HEAD 同失败），变更文件 ruff 全绿。指令禁猜数据文件与 req47 无 code 调查仍未实施。）

**2026-09-24 candidate-3 样本（带 diagnostics 观测 + 900s cell timeout 后首个回放）失败，根因闭合为"占位脚本 × 禁止重写"死局：** `full-chain-candidate-3.json`，`status=failed`、总 983.7s、同码 `report_code_model_request_limit`（47/47）。toolCounts {edit:23, read:10, run:11, write:2}。新观测层直接给出证据链：① req1 首写被 `report_python_source_path_invalid` 拒绝（源码引用未签发字面路径）；② req2 模型退化为**纯探索脚本**（os.walk 风格 ENTRY 打印 + facts/supplement 结构打印，诊断 stdoutTail 实证），此后 11 次 run 全部 exit 0、零产物、`missingPaths` 17 项全缺——`declared_output_missing` 软拒按设计工作，但回执"不得调用 write_script 整段重写"把模型锁死在探索脚本里：39 行打印脚本到 10 图完整实现本质是全文替换，Lark patch edit 对 deepseek-v4-flash-0731 过难（23 次 edit 中 path_invalid ×6——编辑后源码引用未签发路径、not_found ×3、invalid ×2、not_local ×2），预算耗尽时**最终脚本仍是纯探索脚本**（工作区现场实证，无一行绘图代码）；③ req47 边界 0ms `tool_error` **第二次复现**（本次为 read_script，同样无 code、未执行），升级为待办调查项。结论：candidate-2/3 同属一个失败族——首写失败或退化 → 探索/占位脚本 → declared_output_missing 软拒 + 禁止重写 + edit 契约过难 = 预算空转死局；candidate-1 唯一通过样本的差异恰在首写即真实实现。候选修复方向（协议行为变更，待拍板）：a) `declared_output_missing` 回执放开 write_script 重写闸门（如当前源码与签发产物差距达全文替换级、或连续 N 次 edit 被拒后允许重写）；b) diagnostics 白名单补 `unsignedPaths`/`forbiddenPathOperations`（本轮 path_invalid ×6 的具体被拒路径因此缺失，无法进一步归因）；c) req47 边界 tool_error 正式调查；d) 反占位指令对"被拒后退化探索"行为约束不足，需评估指令强化或结构预检层快速拒绝零写出脚本。

**2026-09-24 候选方向 a/b/c 已实施（工作树未提交），定向测试 91 passed、ruff 通过；尚未跑 candidate-4 真实回放验证（n=0，不宣称收益）：**

- **a) 门控重写闸门**：`toolkit.py` 新增 `REWRITE_GATE_EDIT_FAILURES = 3` 与 `_edit_failures_since_progress` 计数（edit 失败 +1；**仅成功 run 或成功 write 清零，成功 edit 不清零**——candidate-3 实证 edit 成败交替会让"纯连续失败"计数永远重置）。闸门开启后 `delivery.py` 的 `declared_output_missing` 回执放行 `write_script`（nextTools=["write_script","read_script","edit_script","run_script"]，闸门关闭时文案逐字不变），`protocol.py` 的 write_script 剔除逻辑在 `rewriteAllowed is True` 时跳过；payload 新增 `rewriteAllowed` 字段。
- **b) diagnostics 白名单补字段**：`metrics.py` `bounded_failure_diagnostics()` 白名单透传 path/errorType（≤256 字符）、errorLine/exitCode/used/limit（整数）、missingPaths/presentPaths/unsignedPaths/forbiddenPathOperations（各≤20 项）、stdoutTail/stderrTail（尾部 1000 字符）；归一化层有界透传，firstToolFailure 现携带诊断，path-rejection 类失败可直接归因被拒路径。
- **c) 工具限额编码回执**：`protocol.py` `_ordered_code_calls` 在 `stopped` 检查后新增限额拦截分支——`current_count >= function_call_limit` 时回编码回执 `report_code_tool_call_limit`（details 含 used/limit）并写 firstToolFailure，替代 Agno 对超限调用的裸 tool_error（req47 边界 0ms 无码 tool_error 的根因，Agno 3.0.9 `base.py` 行为）。请求上限口径：max(4, tool_limit+1)=47，工具上限 29+17=46；viz reserve 3+17=20 因修复态 read/edit/run 全在 `_DELIVERY_TOOL_CANDIDATES` 而从不触发，硬限额兜底。
- **受控放行 `os.path.join`**：`toolkit.py` `_reject_unauthorized_paths` 新增 `_safe_join_call` 分支，当 `os.path.join` 的所有参数都能静态解析为字面字符串、且计算结果命中 `authorized_paths` 时不加入 forbidden；动态参数或结果未授权仍拒绝。`os.path.abspath`/`dirname`/`getcwd` 等目录推导操作仍禁止。这样可在不放宽授权边界的前提下，减少 candidate-4/5 中因首写使用 `os.path.join` 导致的 `report_python_source_path_invalid` 失败。
- 回放脚本 cell timeout 由 120s 对齐到 `DEFAULT_TERMINAL_TIMEOUT`（900s），修复 candidate-2 的 120s 假超时。
- 定向验证：`test_reporting_code_agent_metrics.py` + `test_reporting_code_delivery.py` 合计 **91 passed**（新增 5 用例：归一化边界、declared_output_missing 轨迹 diagnostics 全等、tool_call_limit 编码、闸门开/关声明剔除与恢复）。continuation 测试 4 failed 经干净 HEAD worktree 双侧比对确认为**先存失败**（失败清单逐一致：`test_seed_runs_before_provider_without_fabricated_tool_messages[success/failure/cancelled]`、`test_seed_execution_counts_toward_exhausted_task_budget`），非本次改动引入，另列待办。

**2026-09-24 candidate-4 真实回放（a/b/c 修复后首个完整样本）`status=passed`：**

- 总 wall-time `907.77s`；Coding 24 请求、34 次工具调用、754312ms，input 926894 / output 37534 / reasoning 19084 / cache 680960 tokens。
- toolCounts：write_script=2、run_script=5、edit_script=7、read_script=5、view_image=14、submit_script=1；最终 budget used=34/limit=46，未触发硬限额，req47 `tool_error` 未复现。
- 关键轨迹：req1 首写同样被 `report_python_source_path_invalid`（forbiddenPathOperation=`os.path.join`）拒绝，diagnostics 已完整记录；req2 直接写出真实实现脚本（非占位/探索脚本），req3 run 失败（脚本数据去重断言）；req4-22 通过 read/edit/run/view 迭代修复，最终 req24 `submit_script` 成功提交 attempt-3，17 个产物（10 PNG + 7 plotly.json）全部生成，reviews 10 项均通过。
- 与 candidate-3 死局的核心差异：**req2 即真实实现 + 后续 edit 有进展**，模型没有退化为占位脚本，因此闸门未开启（edit 失败从未连续 ≥3 且无成功 run/write 清零）。这说明 candidate-3 的失败并非"任何首写失败必然死局"，而是"首写失败后模型选择退化探索"这一特定行为与禁止重写叠加的结果；a/b/c 提供的 healthier diagnostics/限额兜底/重写逃生虽未在 candidate-4 触发，但消除了 candidate-3 的硬边界风险。
- 样本量 n=1，仅证明修复后存在成功路径，不构成推广结论；候选方向 d（反占位指令/零产物脚本快速拒绝）仍为后续优化项。

**2026-09-24 candidate-5 真实回放（第二个验证样本）`status=passed`：**

- 总 wall-time `980.511s`；Coding 21 请求、37 次工具调用、655455ms，input 577146 / output 21735 / reasoning 7884 / cache 388096 tokens。
- toolCounts：write_script=2、run_script=5、edit_script=4、read_script=3、view_image=22、submit_script=1；最终 budget used=37/limit=46，未触发硬限额，req47 `tool_error` 未复现。
- 关键轨迹：req1 首写同样被 `report_python_source_path_invalid`（forbiddenPathOperation=`os.path.join`）拒绝；req2 写出真实实现脚本后 **req3 首次 run 即成功**（firstRunSuccess=true），后续 4 次 run 均为迭代/视觉 review 驱动（含一次 Plotly `standoff` 属性误用导致 ValueError），最终 req21 `submit_script` 成功提交，17 个产物全部生成，reviews 10 项均通过。
- 与 candidate-4 的共性：修复后连续两个样本在首写被拒后均未退化为占位脚本，均通过正常 edit/run/view 迭代到达 submit；闸门仍未触发，说明 a/b/c 中的“兜底逃生”尚未被调用，但消除了 candidate-3 的硬性死局边界。
- 当前真实回放证据：candidate-4/5 连续 2/2 passed，candidate-3 为 failed。样本仍不足以给出推广结论，但已支持“首写 path_invalid 不再必然导致预算空转死局”的定性判断。

**2026-09-24 candidate-6 真实回放（加入受控 `os.path.join` + 占位脚本快速检测后）`status=failed`：**

- 总 wall-time `1273.612s`；Coding 47 请求、46 次工具调用、input 2.88M / output 64095 / reasoning 45453 / cache ~93184 tokens；`failureCode=report_code_model_request_limit`（请求耗尽）。
- toolCounts：write_script=2、run_script=9、edit_script=14、read_script=7、view_image=14、submit_script=0。
- 关键轨迹：req1 首写仍被 `report_python_source_path_invalid`（os.path.join）拒绝；req2 写出真实实现，但 req3 首次 run 即 `ValueError`（line 70）；后续进入长 edit/run/view 迭代，产物反复生成但 visual review 未全过，req40 触发硬限额 `report_code_tool_call_limit`（used=46/limit=46），证实 fix c 的编码回执已生效；req41-47 模型连续调用 `read_script`，均被限额回执拒绝，直至 47/47 请求耗尽失败。
- **占位检测未触发**：该脚本并非纯占位/探索脚本（含真实绘图/写出调用），因此 `_is_placeholder_script` 未将其标记为 placeholder，闸门保持关闭。失败根因是“真实实现有 bug + 视觉 review 迭代消耗预算”，不是 candidate-3 式死局。
- 样本结论：candidate-4/5/6 共 3 个修复后样本，2 passed / 1 failed；`os.path.join` 放行和占位检测没有引入回归，但单次失败说明预算/迭代效率仍是瓶颈。下一步可选：a) 降低闸门阈值或在部分成功 run 后仍允许更快进入重写；b) 减少视觉 review 轮次；c) 再跑 1–2 个样本确认失败率。

**2026-09-24 同步实施 a/b/c 后续优化（用户拍板“123 同时进行”）：**

- **a) 降低重写闸门阈值**：`toolkit.py` `REWRITE_GATE_EDIT_FAILURES` 由 `3` 降至 `2`；`delivery.py` 的 `declared_output_missing` 回执和 `protocol.py` 的 write_script 声明剔除同步按新阈值生效。相关测试 `test_rewrite_gate_opens_after_repeated_edit_failures_and_closes_on_rewrite`、`test_declared_output_missing_advises_rewrite_after_gate_opens` 的循环次数由 3 次改为 2 次，定向回归 118 passed + ruff 通过。
- **b) 合并视觉 review 调用**：`toolkit.py` 的 `view_image` 工具参数新增 `paths` 数组（同时兼容单 `path`），单次调用最多 5 张图；底层通过 `asyncio.gather` 并发调用 `ReportVisionReviewer.review`，结果按原顺序返回 `receipts` 数组；单图调用仍返回 `receipt` 字段保持兼容。`protocol.py` 的冗余审查检测 `_is_redundant_visual_review` 同步支持 `paths` 批量；`_update_tool_result` 对 `view_image` 的 `first_repair_success` 跟踪兼容 `receipt`/`receipts` 两种形状。新增 `test_view_image_reviews_multiple_paths_in_one_call` 验证批量审查、并发调用计数和 `has_current_visual_review` 缓存更新，定向回归 118 passed + ruff 通过。
- **c) 候选样本继续采集**：candidate-7/8 在阈值与 review 改动后串行执行，结果见下两条。

**2026-09-24 candidate-7 真实回放（阈值 2 + view_image 批量后首个样本）`status=passed`：**

- 总 wall-time `781.961s`；planner 1 请求 `107.1s / 7,571 reasoning`；Coding 22 请求、22 次工具调用、`674.7s`，input `807,335` / output `35,059` / reasoning `22,986` / cache read `573,440`。
- toolCounts：`write_script=1`、`run_script=4`、`edit_script=5`、`read_script=4`、`view_image=7`、`submit_script=1`；最终 budget used=22/limit=46，未触发硬限额。
- 关键轨迹：req1 首写成功（`192.996s / 7,541 reasoning`），`firstScriptSuccess=true`；req2 首次 `run_script` 失败（`report_code_mode_execution_failed`，ValueError “2025 与 2024 期间无共同月份”）；req3-9 进入 read/edit/run 修复循环（含一次 `edit_script` `report_code_script_edit_not_found`）；req10-15 为视觉审查阶段，其中 req10/12/13/14/15 五次因模型一次传入超过 5 张图被宿主 `report_code_visual_paths_too_many` 拒绝，req11 成功审查 1 张图、req15 成功审查 5 张图，其余拆分后重试；req16-20 继续修复；req21 再次 `view_image`；req22 `submit_script` 成功提交 10 张 PNG + 7 个 plotly.json，17 个产物齐全。
- `rawProtocolCorrect=true`，`envelopeNormalizedInputs=4`（四层为 data 信封兼容解封），`criticalVisualDefect=false`；`firstRunSuccess=false`、`firstPatchApplied=true`、`firstRepairSuccess=false`（修复轮最终成功提交，但首次修复未闭环）。
- **批量 review 效果**：模型并未自动把 10 张图合并为 2 次 ≤5 张的调用，而是多次尝试一次性传入超过 5 张图并被拒绝，最终仍消耗 7 次 `view_image`。说明仅开放 `paths` 数组不足以保证模型利用批量能力；后续可考虑在指令或交付状态中明确提示“每次最多 5 张图，建议一次性传入”或把 `maxItems` 放宽到 10（v3 bundle 共 10 张 PNG），但当前按“限制/合并”目标保留 `maxItems=5`。
- 样本结论：阈值降至 2 与批量 review 接口在本样本未触发负面效应，passed；但 visual review 阶段的 model 方差仍是主要耗时来源之一（req16 `read_script` 64.1s/4,578 reasoning、req18 `edit_script` 31.1s/1,900 reasoning）。n=1，不宣称稳定改善。

**2026-09-24 candidate-8 真实回放（阈值 2 + view_image 批量后第二个样本）`status=passed`：**

- 总 wall-time `849.784s`；planner 2 请求 `205.953s / 13,416 reasoning`（第 2 次 planner 调用为补充/修正，属本样本特有）；Coding 27 请求、28 次工具调用、`643.7s`，input `1,144,169` / output `43,329` / reasoning `27,054` / cache read `859,136`，`visualReviewDurationMs=56,351`。
- toolCounts：`write_script=2`、`run_script=8`、`edit_script=7`、`read_script=4`、`view_image=6`、`submit_script=1`；最终 budget used=28/limit=46，未触发硬限额。
- 关键轨迹：req1 首写被 `report_python_source_path_invalid` 拒绝（`unsignedPaths` 含父目录，diagnostics 已完整记录）；req2 第二次 `write_script` 成功；req3 首次 `run_script` 即 `report_code_declared_output_missing`（脚本 exit 0 但零产物，stdoutTail 显示大量 facts/supplement 结构打印，与 candidate-3 占位脚本形态一致，但本次后续成功 escape）；req4-20 进入 read/edit/run 修复循环；req21 provider 在一次响应中返回 2 个 `view_image` 调用（`toolCallCount=2`），均成功执行，体现 `parallel_tool_calls=True` 与批量 review 接口同时生效；req22-26 继续修复/审查；req27 `submit_script` 成功提交 10 PNG + 7 plotly.json。
- `rawProtocolCorrect=true`，`envelopeNormalizedInputs=7`，`criticalVisualDefect=false`；`firstScriptSuccess=false`、`firstScriptFailureCode=report_python_source_path_invalid`；`firstRunSuccess=false`、`firstRunFailureCode=report_code_declared_output_missing`；`firstPatchApplied=true`、`firstRepairSuccess=false`。
- **批量 review 与多调用批次**：req21 把视觉审查拆成同批 2 个 `view_image` 调用（而非 1 个 `paths` 数组），说明模型尚未稳定使用 `paths` 数组做 5 图合并，但已能利用 provider 多调用返回减少往返；req16/17 仍出现 `report_code_visual_paths_too_many`（单调用超 5 张）。视觉 review 总调用 6 次，较 candidate-7 的 7 次略少，但样本差异不能视为批量接口的确定性收益。
- 与 candidate-7 对比：candidate-7 首写成功但首次运行失败，candidate-8 首写失败后二次写入成功、首次运行缺失产物；两次均最终 passed，但轨迹形态不同，说明当前改动未消除首写/首跑方差。合并 candidate-7/8：2/2 passed，累计 planner+Coding reasoning 分别为 30,557 与 40,470，方差大，n=2 仍不足给出 P95 结论。

**2026-09-24 同步实施 a/b/c 后续优化之 1/2 落地（用户“1 和 2”）：**

- **1) 让模型真正用上 `view_image` 的 `paths` 批量审查**：`toolkit.py` 的 `view_image` 工具描述改为明确鼓励把待审图片放入 `paths` 数组一次性调用（最多 5 张），只有单张图时才使用 `path`；`agent.py` 的 `_VISUALIZATION_CODE_COMMON_INSTRUCTIONS` 同步追加批量审查提示，说明“建议把当前待审图片一次性批量传入 view_image 的 `paths` 数组（最多 5 张），避免逐张单拆调用”。相关测试 `test_visual_tool_description_targets_current_output`、`test_code_agent_factory_creates_fresh_agent_with_custom_input_instructions` 和 `test_task_specific_code_instructions_delegate_wire_protocol_and_fit_budget` 已同步断言新文案与预算（可视化公共指令预算从 1,460 tokens 上调至 1,500 tokens，bytes 4,800 已够）。
- **2) 根治首跑零产物 / `declared_output_missing` 空转**：`toolkit.py` 的 `_declared_output_identities()` 在全部声明产物缺失时，直接把 `_edit_failures_since_progress` 设为 `REWRITE_GATE_EDIT_FAILURES`，立即打开重写闸门；缺失产物诊断 details 增加 `allDeclaredOutputsMissing: True`，回执文案仍保留“声明产物不存在，不代表脚本不存在”，但在闸门开启时允许调用 `write_script` 整段重写一次。`metrics.py` 的 `bounded_failure_diagnostics()` 白名单补透 `allDeclaredOutputsMissing` 与 `isPlaceholderScript` 两个 bool 字段，使 `firstToolFailure.diagnostics` 能直接归因零产物/占位脚本。
- **测试与回归**：新增/更新 `test_declared_outputs_partial_missing_keeps_rewrite_gate_closed`（部分缺失闸门保持关闭）、`test_declared_output_missing_advises_rewrite_after_gate_opens`（全缺失闸门开启）、`test_declared_output_missing_records_bounded_diagnostics`（零产物 metrics diagnostics 包含 `allDeclaredOutputsMissing`，且 runner 只需 2 个 model request 即可成功提交）、`test_missing_declared_output_includes_matching_source_context`、`test_run_script_does_not_flag_real_script_as_placeholder`。`ruff check` 与 `git diff --check` 通过；定向组合（interactive budget + code_delivery + code_diagnostics）68 passed；更广回归 `test_reporting_code_agent_metrics.py` + `test_replay_visualization_task.py` + `test_reporting_benchmark_variants.py` + `test_reporting_code_reasoning_replay.py` + `test_reporting_visual_repair_diagnostic.py` + `test_reporting_interactive_code_agent.py` 共 **304 passed，1 failed**（唯一失败为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`，本次改动前已失败，非新引入）。candidate-7/8 为真实回放且已 `status=passed`，无需因本改动重跑。
- **下一步可选动作**：继续采集 candidate-9/10 真实回放，验证“批量提示 + 零产物快速重写”在更多样本上是否降低 `declared_output_missing` 长循环频率；若模型仍不稳定使用 `paths` 数组，再评估把 `maxItems` 放宽到 10 或在交付状态中显式拆分审查批次。

**2026-09-24 candidate-9 / candidate-10 已同时启动：** 为加速样本采集，两个 frozen-visual-v3 candidate 全链回放使用同一 bundle、模型配置（Coding low / planner high）和 `--wall-timeout-seconds 1800`，分别以 `--output .local/reporting-validation/frozen-visual-v3/full-chain-candidate-9.json` 与 `full-chain-candidate-10.json` 在后台并行执行。因共享同一 provider 配额，并行执行存在网关排队/速率风险；本次按用户“1 和 2 子任务 同时进行”要求启动，结果落盘后按非删失样本纳入统计。

**2026-09-24 candidate-9 真实回放（并行采集第 1 个样本）`status=passed`：**

- 总 wall-time `1017.701s`；planner 2 请求 `127.459s / 6,091 reasoning`（第 2 次 planner 调用为补充/修正，属本样本特有）；Coding 19 请求、19 次工具调用、`890.103s`，input `501,243` / output `22,339` / reasoning `6,861` / cache read `336,896`，`visualReviewDurationMs=38,672`。
- toolCounts：`write_script=2`、`run_script=4`、`edit_script=5`、`read_script=3`、`view_image=4`、`submit_script=1`；未触发硬限额。
- 关键轨迹：req1 `run_script` 因 `report_code_source_missing` 失败（首跑源码缺失）；req2 `write_script` 被 `report_python_source_path_invalid` 拒绝（`forbiddenPathOperations=['os.path.join']`）；req3 二次写入成功；req5 `view_image` 因一次性传入超过 5 张图被 `report_code_visual_paths_too_many` 拒绝；req6 起拆分审查成功；req8 一次 `edit_script` `report_code_script_edit_invalid`；req19 `submit_script` 成功提交 10 PNG + 7 plotly.json，17 个产物齐全，reviews 10 项均通过。
- `rawProtocolCorrect=true`，`envelopeNormalizedInputs=4`，`criticalVisualDefect=false`；`firstScriptSuccess=false`、`firstScriptFailureCode=report_python_source_path_invalid`；`firstRunSuccess=false`、`firstRunFailureCode=report_code_source_missing`；`firstPatchApplied=false`、`firstRepairSuccess=false`。累计 planner+Coding reasoning `12,952`，低于 candidate-7/8，但样本形态不同（首写先被拒 + 首跑源码缺失），n=1 不宣称稳定改善。
- `declared_output_missing` 长循环未出现；`allDeclaredOutputsMissing` 零产物快速重写闸门在本样本未触发。

**2026-09-24 candidate-10 真实回放（并行采集第 2 个样本）`status=passed`：**

- 总 wall-time `1766.939s`（接近 1800s 上限但仍为非删失 passed）；planner 1 请求 `64.703s / 4,693 reasoning`；Coding 38 请求、38 次工具调用、`1702.135s`，input `2,194,983` / output `65,538` / reasoning `51,196` / cache read `1,752,064`，`visualReviewDurationMs=101,133`。
- toolCounts：`write_script=7`、`run_script=12`、`edit_script=6`、`read_script=4`、`view_image=8`、`submit_script=1`；未触发硬限额。
- 关键轨迹：req1 首写成功；req2/4/6/8/10/12 连续 6 次 `run_script` 均 `report_code_declared_output_missing`（17 项产物全缺，`allDeclaredOutputsMissing=true`，stdoutTail 显示大量 facts/supplement 结构打印，属占位/探索形态），每次失败后模型在下一轮调用 `write_script` 整段重写（闸门按设计放行）；req14/16 转为真实执行错误（TypeError/ValueError）后进入 edit/run 修复；req19/20 两次 `view_image` 因超 5 张被拒；req38 `submit_script` 成功提交 10 PNG + 7 plotly.json，17 个产物齐全，reviews 10 项均通过。
- `rawProtocolCorrect=true`，`envelopeNormalizedInputs=11`，`criticalVisualDefect=false`；`firstScriptSuccess=true`；`firstRunSuccess=false`、`firstRunFailureCode=report_code_declared_output_missing`；`firstPatchApplied=true`、`firstRepairSuccess=false`。累计 planner+Coding reasoning `55,889`，为 candidate-7/8/9/10 中最高；n=1 不宣称稳定改善。
- **零产物闸门观察**：`allDeclaredOutputsMissing` 诊断与重写闸门均按预期工作，但模型在 candidate-10 中仍经历 6 轮“写脚本→零产物→重写”循环，说明提示层修复能降低死局概率、不能把占位/探索脚本行为完全消除；后续可考虑结构预检层对“exit 0 但零写出”脚本更强约束，或继续观察更多样本。
- 并行执行结论：candidate-9/10 同时运行均成功落盘且均 `passed`，未观察到因并行导致的协议失败或网关拒绝；但 candidate-10 总耗时接近上限，样本方差仍大。

**2026-09-24 零产物结构预检 + view_image 自动分批已实施（candidate-10 空转族针对性修复）：**

- **view_image 自动分批**：`toolkit.py` 的 `view_image` 不再对超过 5 张的 `paths` 返回 `report_code_visual_paths_too_many`，改为按 5 张一组顺序分批、批内并发调用 `ReportVisionReviewer.review`，结果按原顺序合并返回 `receipts`（单图仍返回 `receipt`）。工具描述与可视化公共指令同步改为“把全部待审图片一次性传入 `paths`，超过 5 张宿主自动分批，无需自行拆分”。新增 `test_view_image_auto_chunks_more_than_five_paths`（6 张图一次调用，reviewer 按序调用 6 次）；`report_code_visual_paths_too_many` 不再作为模型可见错误路径。
- **零写出结构预检（仅可视化任务）**：`toolkit.py` 新增 `_resolved_path_literal` / `_all_referenced_literal_paths` / `_declared_output_literals` / `_declared_output_write_paths` 与 `_reject_output_write_contract`：可视化 `write_script`/`edit_script` 在既有 AST 校验链中检查脚本是否引用任何声明产物路径；完全不引用（纯打印 facts 的占位/探索脚本）直接失败 `report_code_script_no_output_write`（details 有界：`declaredOutputCount`、`detectedOutputWrites`），在 `run_script` 之前拦下 candidate-10 式空转。引用了声明路径但宿主无法静态确认写出调用时，`write_script` 回执追加软告警 `report_code_script_output_write_unverified`（不阻断，防 helper 间接写出的误伤）。分析任务不启用硬预检，保留 `run_script` 阶段 `_is_placeholder_script` 检测路径（`test_run_script_detects_placeholder_and_opens_rewrite_gate` 迁移到分析 binding 覆盖该路径）。
- **指标白名单**：`metrics.py` `bounded_failure_diagnostics()` 与 toolkit `_safe_diagnostic_details` 同步透传 `declaredOutputCount`（int）与 `detectedOutputWrites`（list ≤20）；`test_coding_metric_sample_keeps_bounded_first_tool_failure_diagnostics` 已补断言。
- **测试与回归**：新增/更新 6 个用例（自动分批、占位拒绝、间接写出软告警、真实写出无告警、edit 移除全部产物引用拒绝、metrics 白名单）；定向组合（delivery + diagnostics + metrics + interactive + replay）**277 passed，1 failed**（唯一失败为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`）；更广六文件回归 **304 passed，1 failed**（同一既有失败）。`ruff check` 与 `git diff --check` 通过。可视化公共指令预算微调至 4_800 bytes / 1_520 tokens。
- **下一步**：按同一 bundle 并行跑 candidate-11/12 验证 `report_code_visual_paths_too_many` 归零、零产物循环在 write 阶段被拦、通过率与 `rawProtocolCorrect` 不劣化；若回放出现合法脚本被 `no_output_write` 误伤，按预案降级为软告警 + delivery-state 提示。

**2026-09-24 candidate-11 / candidate-12 已同时启动（结构预检 + 自动分批后首轮验证）：** 同 v3 bundle、candidate variant、`--wall-timeout-seconds 1800`，输出 `.local/reporting-validation/frozen-visual-v3/full-chain-candidate-11.json` 与 `full-chain-candidate-12.json`，后台并行执行。验收点：`report_code_visual_paths_too_many` 是否归零、`report_code_script_no_output_write` 是否在 write 阶段拦下零产物循环、有无误伤合法脚本、通过率与 `rawProtocolCorrect` 是否不劣化。

**2026-09-24 candidate-11/12 均在 planner 门禁失败，Coding 阶段未启动：** 两个回放都在 `requiredCharts` 身份校验处失败，`report_phase_contract_invalid`，`pathMismatches=["chart_002"]`，分别耗 137.3s / 149.0s，未进入 Coding（`modelMetrics=[]`、`codingMetrics=[]`）。为判别是否系统性漂移，单独跑一次 planner 探针（`probe_planner_identity.py`，仅 planner、不进入 Coding）：同一 bundle 下 10 个 chartId 集合一致，`chart_002` 的 sourcePath/interactivePath 逐字一致，`mismatches=[]`。结论：本次失败是 planner provider 采样方差（并行两次同错可能由共享输入/缓存相关采样诱发），不是新改动影响 planner；Coding 改动的真实验收仍缺样本。随后串行启动 candidate-13 全链回放（非并行重试，输出 `full-chain-candidate-13.json`）。

**2026-09-24 candidate-13 真实回放（串行验证，结构预检 + 自动分批后首个 passed 样本）：** `status=passed`，总 `639.941s`；planner 1 请求 `135.715s / 11,876 reasoning`；Coding 11 请求、11 次工具调用、`504.104s`，input `360,497` / output `27,789` / reasoning `15,265` / cache read `188,416`，`visualReviewDurationMs=46,796`。toolCounts：`write=2、run=2、edit=1、read=2、view=3、submit=1`。关键验证点全部命中：① req1 首写即被 `report_code_script_no_output_write` 拦下（`declaredOutputCount=17`、`detectedOutputWrites=[]`），没有进入 run_script 零产物循环；② req2 二次写入成功，req3 首次 run 即成功；③ 全程 `report_code_visual_paths_too_many` 归零；④ `rawProtocolCorrect=true`、`criticalVisualDefect=false`、`firstRunSuccess=true`、`firstPatchApplied=true`、`firstRepairSuccess=true`；⑤ 17 个产物齐全、10 项 reviews 全部通过。这是本轮改动后首个同时满足“零产物在 write 阶段被拦 + view_image 不再因超 5 张被拒 + 质量指标全过”的非删失真实样本。n=1，不据此宣称稳定收益，但已证明改动方向有效。

**2026-09-24 candidate-14 真实回放（串行验证，预检后第二个 passed 样本）`status=passed`：** 总 `1188.55s`；planner 1 请求 `117.3s / 7,562 reasoning`；Coding 15 请求、15 次工具调用、`1071.2s`，input `544,781` / output `42,706` / reasoning `18,216` / cache read `329,728`，`visualReviewDurationMs=59,496`。toolCounts：`write=3、run=2、edit=2、read=4、view=3、submit=1`。关键轨迹：req1 首写被 `report_code_script_no_output_write` 拦下（`declaredOutputCount=17`、`detectedOutputWrites=[]`，占位形态）；req2 二次写入被 `report_python_source_path_invalid` 拒绝（`forbiddenPathOperations=['os.path.dirname']`）；req3 第三次写入成功；req4 首次 run 即成功（`firstRunSuccess=true`）；req7 一次 edit 被拒后经 4 次 read + edit 成功、run、view×3、req15 submit，17 个产物齐全、10 项 reviews 全部通过。`rawProtocolCorrect=true`、`envelopeNormalizedInputs=3`、`criticalVisualDefect=false`、`firstRepairSuccess=true`。与 candidate-13 合并：预检后连续 2 个 passed 样本呈现“占位在 write 阶段被拦 → 二次写入真实实现 → 首跑成功”的理想轨迹；但首写连续两次被拒（占位 + 路径规则）说明首写质量方差仍大，靠预检/路径回执兜底走到 passed。n=2，不宣称稳定收益。

**2026-09-24 candidate-15 真实回放（预检后第三个样本，非删失失败，新失败族根因已闭合）：** `status=failed`、总 `446.977s`、失败码 `report_code_script_edit_invalid`（7 请求 447s 内错误终止，未撞预算上限，模型在两次 edit 失败后停止调用、未提交）。planner 1 请求 `97.5s / 5,946 reasoning`；Coding 7 请求、7 次工具调用、`349.4s`，input `160,924` / reasoning `7,384` / cache read `91,136`。toolCounts：`write=3、run=1、edit=2、read=1`，未到达 view/submit（`criticalVisualDefect=false`、reviews=0、工作区零 PNG）。关键轨迹与根因（证据：firstRunFailure 边车源码 SHA 与终态脚本逐字节一致 + 冻结 facts 形状核对）：① req1 首写 `report_python_source_path_invalid` → req2 二次写入又被 `report_code_script_no_output_write` 拦（占位形态）→ req3 第三次写入成功；② req4 首跑 `TypeError: list indices must be integers or slices, not str`（脚本第 73 行）：模型把 facts 中 `metrics[0].periodValues`（**行对象数组** `[{period, value}]`，descriptor 声明 fields=[period, value]）误当作 supplement findings 的**表格对象** `{columns, rows}` 形状去解码，`target["columns"]` 对 list 取字符串下标直接抛错——两种受信数据形状混用是模型侧契约误解，非宿主缺陷；③ req5/req7 两次 `edit_script` 补丁格式无效（该失败码当前 **diagnostics=null，观测缺口**），终态脚本 SHA 与首跑失败快照完全一致（两次 edit 均未应用）。暴露两个待办：a) `edit_script` invalid 失败需补诊断白名单（对齐 run_script 已有待遇）；b) facts 行数组与 supplement 表格的形状差异需在投影/指令层澄清（涉及指令改动，按单变量原则单独拍板）。n=1，不据此宣称退化或改善；与 c2/c3/c6 失败族不同类，属新失败族。

**2026-09-24 candidate-16 真实回放（三项集成修复后首个验证样本）`status=failed`：** `failureCode=report_code_model_request_limit`（47/47 请求耗尽），总 `1197.389s`；Coding 47 请求、46 次工具调用、`1137.448s`，input `3,213,541` / output `80,291` / reasoning `63,000` / cache read `2,924,544`。toolCounts：`write=4、run=16、edit=18、read=8`，未到达 `view_image/submit`（`reviews=0`、`images=0`）。关键轨迹：req1 首写被 `report_python_source_path_invalid` 拒绝（`forbiddenPathOperations=['os.getcwd','os.path.join','os.path.relpath']`）；req2/req3 连续两次 `report_code_script_no_output_write`（占位形态，预检按预期拦下）；随后进入 16 次 `run_script` 失败与 18 次 `edit_script` 的长修复循环，最终 47/47 请求耗尽。与 candidate-15 的“7 请求内 repeated_identical_patch 快速终止”相比，本次失败族变为“长修复循环耗尽预算”，说明新 edit 上下文未在该样本中把修复收敛到预算内；但模型确实继续尝试了更多局部编辑而非立即重复同一补丁。三项集成修复中，Plotly 检查与图表锚点重排未在本样本被触发（未生成图片/PDF），不能据此评价；`no_output_write` 预检继续稳定拦下占位首写（2 次）。

**2026-09-24 candidate-17 真实回放（补跑样本，仍未提交）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `1575.842s`；planner 1 请求 `135.0s / 9,643 reasoning`；Coding 47 请求、`1441.0s / 65,333 reasoning`，toolCounts：`write=1、run=16、edit=19、read=7、view=3`，`submit=0`。与 candidate-16 的差异是**到达 `view_image` 3 次**（req35/36/44），第 4 次（req47）被 `report_code_tool_call_limit` 拒绝；`report_code_visual_paths_too_many=0`。全程 `no_output_write=0`、`declared_output_missing=0`。该样本验证了两点：① `view_image` 自动分批在真实链路可用；② 仍存在模型侧 Plotly 契约错误（`layout_plotly() got an unexpected keyword argument 'xaxis_title'`，charts.py:431），但这是模型脚本错误，不是 `inspect_plotly_file` 宿主缺口。图表锚点重排未被本样本验证（未到提交/PDF）。
**2026-09-24 candidate-18 真实回放（数据形状契约指令后首个样本）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `1328.225s`；Coding 47 请求、46 次工具调用、`1273.810s`，reasoning `50,468`，toolCounts：`write=3、run=16、edit=17、read=7、view=3`，`submit=0`。与 candidate-17 相比，reasoning 从 `65,333` 降至 `50,468`，edit 从 19 降至 17，仍到达 `view_image` 3 次，且 `visualReviewDurationMs=54,670`；但依旧 47/47 请求耗尽，未到 submit。轨迹显示：req1 首写被路径规则拒绝，req2 被 `no_output_write` 拦下；后续失败集中在 `resolve()` 的 `KeyError`（多个 dataPath 解析失败）与 `to_float()` 的 `ValueError`，说明新指令降低了推理量，但尚未完全消除数据形状误解。`sourceExcerpt/allowedEditRegion` 已在回放中持久化，证明 metrics 白名单修复生效。

**2026-09-24 三项集成修复已落地（Plotly 检查缺口 / edit 失败上下文 / 图表锚点重排）：**

- **Plotly 检查缺口（candidate-15 暴露的宿主缺陷已闭环）**：`ReportingWorkspaceAdapter` 补齐 `inspect_plotly_file`，并新增结构化失败码 `report_workspace_capability_missing`（fatal-fast）；`analysis.py` 的可视化 fresh-attempt 循环遇到该错误码记账后立即上抛，不再触发 4 次整段重跑。新增 8 个用例，受影响组合 50/47/29/110/83/146 passed，`ruff` 与 `git diff --check` 通过。
- **edit_script 失败最小片段回执**：`toolkit.py` 新增 `_bounded_edit_context` 与 `_search_anchor_line`，`not_found/ambiguous/overlap` 失败回执现在附 `sourceExcerpt/sourceStartLine/sourceEndLine/errorLine/allowedEditRegion/forbiddenEditRegions/sourceSha256`，SHA conflict 回执补全 `readRange.endLine`；`delivery.py` 抽出共享 `SOURCE_EXCERPT_MAX_BYTES=1800` 与 `bounded_edit_region()`；`code_generation.py` 的 `_short_diagnostic` 白名单放行 excerpt/行号/readRange/allowedEditRegion。新增 11 个定向用例，端到端覆盖“凭失败回执直接重试成功，无需中间 read_script”；8 个受影响测试文件 284 passed（1 个预存 flaky 已修复为不校验并发执行顺序）。
- **图表 citation 锚点重排**：`draft_v1.py` 的 `assemble_report_markdown()` 预计算每张图在同章节内第一个 citation 交集非空的 block 作为锚点，图片改为插在锚点 block 正文之后；原引用位置只保留 citation，不重复插图；锚点≠引用位置时记录 auto-fix `chart_reference_moved_to_anchor`，无锚点时保持原位并记 soft warning。新增 5 个用例，`test_reporting_heading_numbers.py` 31 passed；真实 `ReportRuntime.render_markdown()` 复现“1.2 引用、1.1 citation 匹配”场景，渲染结果图表紧跟 1.1 结论、先于 1.2 标题，PDF/DOCX 下游契约校验通过。
- **合并回归**：三个子修复合并后，13 个受影响测试文件（heading_numbers、code_edit、repair_feedback、code_delivery、stability、workspace_port、tool_contracts、failure_policy、metrics、diagnostics、interactive、replay、benchmark_variants）共 **591 passed，1 failed**；唯一失败为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`（改动前已存在）。`ruff check` 与 `git diff --check` 通过。
- **metrics 诊断白名单补齐**：`bounded_failure_diagnostics()` 现在持久化 `sourceExcerpt`（≤1800B、尾部裁剪）与 `readRange/allowedEditRegion`（只保留 path/startLine/endLine），`sourceStartLine/forbiddenEditRegions` 等仍不放行。新增 6 个定向用例并更新 1 个既有断言；`test_reporting_code_agent_metrics.py` 77 passed，相关套件通过。这补上了 candidate-16 的观测缺口，后续回放可直接从 `firstToolFailure.diagnostics` 看到锚点上下文。
- **facts/supplement 数据形状契约指令已补充**：candidate-16/17 复盘显示 11/16 的 `run_script` 失败来自同一数据形状误解（facts 中没有 `findings`，模型却反复在 facts 里找 `findings[2].rows`，而正确数据在 supplement 的 `columns+rows` 表格里）。`bootstrap.py` 的可视化公共指令新增明确契约：`metrics/derivedMetrics/comparisons` 的 `periodValues/topGroups/bottomGroups` 是行对象数组；`supplementalEvidenceSources[].findings[]` 是 `columns+rows` 表格对象；两类形状不得混用，必须按 `binding.dataPath` 与 `dataDescriptors.fields` 解码。candidate-18 后又追加“禁止编写通用 resolve()/动态路径解析器”，要求逐字使用 `binding.dataPath`，不要用正则或字符串拼接自行推导路径。预算测试同步上调至 5,300 bytes / 1,650 tokens，并新增断言锁定两条契约。
- **待验证**：candidate-16/17/18 均为 `report_code_model_request_limit` 失败样本。candidate-18 相比 17 将 reasoning 从 65,333 降到 50,468、edit 从 19 降到 17，但仍 47/47 请求耗尽；candidate-19 已启动，用于验证“禁止通用 resolve()”是否能进一步压低修复循环。

**2026-09-24 candidate-19 真实回放（禁止通用 resolve() 指令后首个样本）`status=failed`：** `failureCode=report_code_script_edit_invalid`，总 `425.229s`，Coding 仅 6 请求、6 次工具调用、`349.4s`，reasoning `16,747`，toolCounts：`write=2、run=2、edit=1、read=1、view=2、submit=1`。与 candidate-16/17/18 的长循环耗尽预算不同，本次在 6 请求内就因 edit invalid 而终止（模型未继续重试）。关键轨迹：req1 首写被 `report_code_script_no_output_write` 拦下（占位脚本，预检生效）；req2 二次写入成功；req3 首跑 `KeyError: 'findings'`（脚本在 facts 文件上访问 `findings[0].rows`，而该 facts 实际为 `metrics/derivedMetrics/comparisons` 结构，无 `findings`）；req4 view_image 成功、req5 再次 view_image、req6 submit_script 被调用，但随后 req6 中的 `edit_script` 返回 `report_code_script_edit_invalid`（诊断 null，因 metrics 白名单尚未补齐 edit invalid 归因），模型停止调用，任务失败。根因：尽管指令已禁止通用 `resolve()`，模型仍编写了 `navigate()` + `read_rows()` 两个辅助函数，通过 `path.split(".")` + `re.fullmatch` 动态解析路径，在 facts 上访问 `findings[0].rows` 导致 KeyError。这说明纯文本禁令不足以阻止模型构造语义等价的动态路径解析器；需要在 write/edit 阶段引入 AST 结构预检，把“参数名为 path/data_path + 点分路径解析 + 解析结果驱动下标访问”的函数直接拒绝。

**2026-09-24 动态路径解析器 AST 预检已实施：** `toolkit.py` 在 `write_script` 与 `edit_script` 的 AST 校验链中接入 `_reject_dynamic_path_parser(tree)`。判定为三信号合取：① 函数参数名为 `path` 或 `data_path`；② 函数体内出现针对该参数的 `.split(".")` / `.rsplit(".")` 或 `re.fullmatch/match/search` 调用；③ 解析结果被用于驱动下标访问 `X[key]`。满足时拒绝码 `report_code_dynamic_path_parser`，details 含 `functionName/parameterName/line`，并在失败文案中重申“逐字使用 binding.dataPath，不要写通用路径解析器”。误伤控制：参数名不为 `path/data_path`、`split("/")` 文件路径、常量 key 下标、`to_float`/列表推导等形态均放行；定向冒烟 13 个形态 + 新增 5 个单元测试全部通过。`ruff check` 通过，33 个 diagnostics 测试通过。candidate-20 已启动串行全链回放，用于验证该预检是否能阻止 candidate-19 的失败族。

**2026-09-24 candidate-20 真实回放（AST 预检后首个样本）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `1156.260s`；Coding 47 请求、46 次工具调用、`1048.628s`，input `2,472,764` / output `66,685` / reasoning `24,597` / cache read `2,063,360`，`visualReviewDurationMs=84,581`。toolCounts：`write=4、run=8、edit=16、read=12、view=6`。关键轨迹与根因：① req1 首写被 `report_python_source_path_invalid` 拒绝（`forbiddenPathOperations=['os.path.join']`）；req2 被 `report_code_script_no_output_write` 拦下（占位脚本，预检继续生效）；req3 第三次写入成功；② req4 首跑 `TypeError`（line 170，`build_chart_002` 中 `to_pe...` 截断/调用错误），该错误与 candidate-19 的 `KeyError` 不同族，AST 预检未触发（脚本中的 `read_table(supp_obj, finding_index)` 参数名为 `supp_obj`，不是 `path/data_path`，且按整数下标读取 supplement findings，属于合法辅助函数）；③ req12/14/17/20/37/38/39/40 等多次 `edit_script` 失败（ambiguous/not_found/invalid），`sourceExcerpt/allowedEditRegion` 已正常透传，证明 edit 失败上下文修复生效；④ req21 后脚本已能跑出全部 17 个产物，但 view_image 触发 `criticalVisualDefect=true`，后续进入视觉修复长循环；⑤ req47 最后一次 run_script 被 `report_code_tool_call_limit` 拒绝，预算耗尽。结论：AST 预检按设计生效，但 candidate-20 未落入该预检的拦截范围（参数名不是 `path/data_path`），失败族已从“动态路径解析导致 KeyError”切换为“首跑 typo/局部编辑失败/视觉缺陷修复循环耗尽预算”。`rawProtocolCorrect=false`、`envelopeNormalizedInputs=15` 偏高，与多次 edit invalid 导致信封被归一化有关。

**2026-09-24 candidate-21 真实回放（串行补样）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `1351.474s`；Coding 47 请求、46 次工具调用、`1217.542s`，input `3,624,569` / output `90,122` / reasoning `64,943` / cache read `3,183,616`，`visualReviewDurationMs=76,045`。toolCounts：`write=2、run=14、edit=15、read=11、view=4`。关键轨迹：① req1 首写 `report_python_source_path_invalid`（`os.path.join`）→ req2 二次写入成功（**未触发 `no_output_write`**，首写即真实实现）；② req3 首跑 `KeyError: 'findings'`（`table_rows(data, idx)` 被用于 facts 文件，该文件无 `findings`）；③ req4–24 围绕 `table_rows` 反复局部编辑/诊断，逐步加入 `fileRoot` 解包、根键探测、facts 结构打印；④ req25 `run_script` 首次成功，产出全部 17 个文件；⑤ req26/36/39/43 四次 `view_image` 批量审查均成功；⑥ req47 最后一次 `view_image` 撞 `report_code_tool_call_limit`，未到达 `submit_script`。`criticalVisualDefect=false`、`rawProtocolCorrect=true`、`envelopeNormalizedInputs=14`。这是迄今最接近 passed 的样本：运行已通、产物已全、视觉审查已启动，仅因工具调用预算耗尽而无法提交。

**2026-09-24 当前失败族收敛判断：**
- candidate-13/14 已证明“占位脚本在 write 阶段被拦 + 二次写入真实实现 + 首跑成功”的理想轨迹存在；
- candidate-16/17/18 属于“长修复循环耗尽预算”旧族；
- candidate-19 属于“动态路径解析器导致 KeyError”新族，已被 AST 预检针对性覆盖（但 n=0 真实验证，candidate-20/21 未复现该形态）；
- candidate-20 属于“首跑 typo + 视觉缺陷反复修复耗尽预算”族；
- candidate-21 属于“数据形状 helper 修正成功后，视觉审查循环耗尽预算”族，距 passed 仅差一次 submit。

**2026-09-24 candidate-22 真实回放（串行补样）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `1575.401s`；Coding 47 请求、46 次工具调用、`1479.307s`，input `3,172,543` / output `144,399` / **reasoning `108,401`** / cache read `2,419,712`，`visualReviewDurationMs=21,765`。toolCounts：`write=4、run=12、edit=17、read=12、view=1`。关键轨迹：① req1 首写被 `report_code_script_no_output_write` 拦下（占位脚本）；req2 二次写入成功；② req3 首跑 `KeyError: 'findings'`（line 119，`chart_002(data1)` 中 `data1` 实为 facts 文件 `analysis_001.json`，无 `findings`）；③ 脚本使用 **f-string 构造子路径**：`A1 = f"{FACTS}/analysis_001.json"`，这是 candidate-19/20/21 未出现的新动态路径形态，当前 AST 预检只拦截 `.split(".")`/regex，不拦截 f-string 路径拼接；④ req4–40 围绕数据形状反复局部编辑/诊断，stdout 打印显示模型能正确识别 facts 顶层键（`metrics/derivedMetrics/comparisons`），但仍反复尝试在 facts 上找 `findings`；⑤ req41 `write_script` 整段重写被 `report_code_script_no_output_write` 按设计拦下（证明重写闸门持续生效）；req42 再次写入成功；req43 run 成功；req44 view_image 成功；req47 撞 `report_code_tool_call_limit`。本样本 reasoning 高达 10.8 万，为 candidate-13/14 理想轨迹的 7 倍以上，显示数据形状误解仍是主要成本。

**2026-09-24 当前失败族收敛判断（candidate-20/21/22 三连样本后）：**
- candidate-13/14 已证明“占位脚本在 write 阶段被拦 + 二次写入真实实现 + 首跑成功”的理想轨迹存在（n=2）；
- candidate-16/17/18 属于“长修复循环耗尽预算”旧族；
- candidate-19 属于“动态路径解析器导致 KeyError”新族，已被 AST 预检覆盖（n=0 真实拦截）；
- candidate-20 属于“首跑 typo + 视觉缺陷反复修复耗尽预算”族；
- candidate-21 属于“数据形状 helper 修正成功后，视觉审查循环耗尽预算”族，距 passed 仅差一次 submit；
- candidate-22 属于“f-string 构造路径 + facts/supplement 形状混淆导致长诊断循环”族，reasoning 成本最高。

**2026-09-24 已实施第一项（指令层收紧）**：`smart_reporting/reporting/bootstrap.py` 的可视化公共指令追加：
- 禁止 `table_rows()` / `read_table()` 等通用数据读取 helper；
- 禁止用 `+`、f-string、`os.path.join` 构造或推导输入文件路径；
- 输入路径必须使用 `task.authorized_read_paths` / `binding.factFile.path` 的逐字字符串；
- 不得把 facts 文件（如 `analysis_*.json`）当作 supplement 来访问 `findings`。
- 预算测试通过：`bytes=4239 / 5300`、`cl100k_tokens=1300 / 1650`，`test_code_agent_factory_projects_only_task_specific_common_instructions` 1 passed，`ruff check` 通过。

**2026-09-24 candidate-23 真实回放（指令收紧后首个样本）`status=passed`：** 总 `775.569s`；Coding 17 请求、17 次工具调用、`652.073s`，input `638,336` / output `46,685` / reasoning `20,472` / cache read `385,024`，`visualReviewDurationMs=58,517`。toolCounts：`write=4、run=4、edit=3、read=1、view=4、submit=1`。关键轨迹：① req1 `report_python_source_path_invalid`（`os.path.dirname`）；req2 `report_python_source_path_invalid`（unsigned 目录路径）；req3 `report_code_script_no_output_write`（占位脚本被拦）；req4 第四次写入成功；② **req5 首次 run 即成功**（`firstRunSuccess=true`）；③ req6/9/13/16 四次 `view_image` 批量审查，req7/11/14 三次 `edit_script` 小修，req8/12/15 三次 `run_script` 重跑；④ req17 `submit_script` 成功。`rawProtocolCorrect=true`、`criticalVisualDefect=false`、`envelopeNormalizedInputs=5`、10 项 reviews 全部通过、17 个产物齐全。**这是指令收紧后首个 passed 样本，也是自 candidate-14 以来第二个 passed；与 candidate-22 相比，reasoning 从 108,401 骤降至 20,472（约 81% 下降），请求数从 47 降至 17。**

**2026-09-24 candidate-24 真实回放（稳定性检查）`status=failed`：** `failureCode=report_code_model_request_limit`，总 `991.611s`；Coding 47 请求、46 次工具调用、`928.048s`，input `2,715,132` / output `81,443` / reasoning `57,289` / cache read `2,284,544`，`visualReviewDurationMs=34,122`。toolCounts：`write=7、run=14、edit=15、read=8、view=2`。关键轨迹：① req1–req4 经历 `path_invalid`（`os.path.relpath`、`os.path.join`）、`no_output_write` 占位拦截，req5 写入成功；② req6 首跑 `FileNotFoundError`（脚本定义 `def load(p): ...` 通用文件读取 helper，但传入路径错误）；③ req7 `edit_script` 因脚本含 `os.path.join`/`pathlib.Path.cwd` 被 `path_invalid` 拒；④ req10–req20 继续因 `load()`/`rows_of(src, idx)`（`src["findings"][idx]["rows"]`）在 facts 上抛 `KeyError`；⑤ req22–req33 进入“脚本 exit 0 但零产物”循环（模型删除/注释掉绘图代码，只打印诊断）；⑥ req34 `edit_script` `marker_in_block` invalid；req36 `write_script` 因 unsigned 路径被拒；req37 再次写入成功；req38 `TypeError`；req41 终于 run 成功；req42/43 `view_image` 成功；req47 撞 `report_code_tool_call_limit`。**结论**：指令收紧后 candidate-23 通过，但 candidate-24 仍写出 `load(p)` / `rows_of(src, idx)` 等通用 helper，说明纯文本禁令不足以稳定阻止；需要 AST 硬拦截这类“参数化文件加载器 / 参数化 findings 解码器”。

**2026-09-24 AST 硬拦截通用数据读取 helper 已实施：** `toolkit.py` 新增 `_reject_generic_data_helpers(tree)`，在 `write_script` / `edit_script` 校验链中紧接 `_reject_dynamic_path_parser` 调用。两规则：
- **generic_loader**：函数参数被当作 `open(...)` / `json.load(...)` / `json.loads(...)` / `pathlib.Path(...).read_text()` 的文件路径，且函数返回加载后的数据；
- **generic_findings_decoder**：函数返回 `param["findings"][...][...]`，其中 `param` 是函数自身参数。

报错 `report_code_generic_data_helper`，details 含 `functionName` / `parameterName` / `line` / `reason`。误伤控制：模块级字面加载不受影响；chart 构建函数使用 `data["findings"][0]["rows"]` 但不返回该数据时放行。新增 6 个定向测试，39 passed；ruff 与预算指令测试均通过。

**2026-09-24 candidate-25 真实回放（AST helper 硬拦截 + 指令收紧后）`status=passed`：** 总 `1155.308s`；Coding 46 请求、46 次工具调用、`1096.069s`，input `2,835,418` / output `76,162` / reasoning `54,689` / cache read `2,356,224`，`visualReviewDurationMs=83,254`。toolCounts：`write=6、run=10、edit=11、read=9、view=9、submit=1`。关键轨迹：① req1 `path_invalid`（`os.getcwd`）→ req2 `no_output_write` 占位拦截 → req3 写入成功；② req4 首跑 `declared_output_missing`（只产出 chart_003，其余 16 个缺失）；③ req5/7 `edit_script` invalid（`no_valid_blocks`）→ req8/9 连续两次 `write_script` 被 `no_output_write` 拦下（模型想重写）→ req10 再次写入成功；④ req11 run 成功；⑤ req12/16/21/27/32/35/38/42/45 九次 `view_image` 批量审查 + 多轮 edit/run，req46 `submit_script` 成功。`rawProtocolCorrect=true`、`criticalVisualDefect=false`、10 项 reviews 全过、17 个产物齐全。**这是 AST helper 硬拦截后的首个 passed 样本，也是 candidate-20 以来第三个 passed；candidate-23/25 连续两次通过，证明当前组合拳（指令收紧 + 动态路径 AST + helper AST）有效。**

**当前样本统计（candidate-20 起，同一 v3 bundle）：**
| 样本 | 状态 | 关键特征 |
| --- | --- | --- |
| 20 | failed | 首跑 typo + 视觉缺陷循环 |
| 21 | failed | 一步之遥（差 submit） |
| 22 | failed | f-string 路径 + 形状混淆 |
| 23 | **passed** | 指令收紧后首过（17 请求 / 20k reasoning） |
| 24 | failed | 通用 helper 长循环（AST helper 尚未生效） |
| 25 | **passed** | AST helper 硬拦截后首过（46 请求 / 54k reasoning） |

**2026-09-24 candidate-26 真实回放（AST helper 硬拦截后第二个样本）`status=passed`：** 总 `1295.314s`；Coding 35 请求、35 次工具调用、`1216.393s`，input `2,666,213` / output `95,148` / reasoning `59,425` / cache read `2,095,104`，`visualReviewDurationMs=95,726`。toolCounts：`write=4、run=6、edit=10、read=7、view=7、submit=1`。关键轨迹：① **req1 首写即被 AST helper 预检拦截**：`report_code_generic_data_helper`，`reason=generic_loader`（模型仍尝试写 `load(p)` helper）；req2 二次写入成功；② **req3 首次 run 即成功**（`firstRunSuccess=true`）；③ req4/7/16/22/23/27/34 七次 `view_image` 批量审查 + edit/run 小修；④ req35 `submit_script` 成功。`criticalVisualDefect=false`、10 项 reviews 全过、17 个产物齐全。`rawProtocolCorrect=false` 仅因 `envelopeNormalizedInputs=9`（初始 helper 被拒 + 后续几次 edit invalid 导致信封归一化），不影响通过。**candidate-23/25/26 三连通过（candidate-24 因 AST helper 尚未生效而失败），当前组合拳验证通过率达到 3/4。**

**2026-09-24 合并回归结果：** 13 个受影响测试文件组合（heading_numbers、code_edit、repair_feedback、code_delivery、stability、host_workspace、tool_contracts、failure_policy、metrics、diagnostics、interactive、replay、benchmark_variants）共 **611 passed，1 failed**；唯一失败为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`（本次改动前已存在，与本轮改动无关）。`ruff check` 通过。预算测试因新增指令从 5_300/1_650 上调至 5_600/1_750，已同步更新断言与注释。

**当前改动清单**
- `smart_reporting/reporting/bootstrap.py`：可视化公共指令收紧（禁止 f-string/+ / os.path.join 构造路径、禁止通用 helper、禁止 facts 访问 findings）；
- `smart_reporting/reporting/code_agent/toolkit.py`：动态路径解析器 AST 预检 + 通用数据读取 helper AST 硬拦截；
- `smart_reporting/reporting/tests/test_reporting_code_diagnostics.py`：新增 11 个 AST 预检/ helper 拦截测试；
- `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`：可视化指令预算上调至 5_600/1_750；
- `docs/superpowers/plans/2026-09-20-reporting-coding-performance-optimization.md`：完整 candidate-20 至 26 复盘与决策记录。

**下一步候选方向**
1. **视觉审查/提交预算闸门（optional）**：candidate-25 用 46/46 请求，candidate-26 用 35/46，说明仍有撞预算风险，可作为下一波优化；
2. **是否继续补样本 candidate-27**：candidate-23/25/26 三连通过已提供较强信号，但 n=3 仍偏少，可再补一个样本后再做推广判断；
3. **合并提交**：当前改动已通过回归测试，可考虑阶段性 commit/merge。

**2026-09-24 candidate-27 真实回放（AST helper 硬拦截后第三个样本）`status=failed`：** `failureCode=report_code_script_edit_invalid`，总 `207.0s`，仅 6 请求（早停，未耗尽预算）。关键轨迹：req1 首写被 AST helper 闸门拦截（`report_code_generic_data_helper / generic_loader`，**第二次真实触发**）；req2 二次写入成功；req3–req6 三次 `edit_script` `no_valid_blocks`，重复失败检测触发后模型停止。与 candidate-19 同属"编辑失败早停"族，不是预算耗尽族。AST helper 硬拦截在真实链路稳定生效（candidate-26/27 两连触发）。

**2026-09-24 视觉审查收敛闸门已实施（对齐 codex 三层收敛，用户拍板对齐 3 次）：**

- **调研结论**（`/home/junge/pros/codex` 源码）：codex 的收敛靠 ① 模型自审图片（`view_image` 只内联返回，无外部审查循环）；② guardian 审查一次性决策 + `MAX_REVIEW_ATTEMPTS=3` + `REVIEW_TIMEOUT=90s` + 指数退避（`ext/guardian-reviewer/src/retry.rs`）；③ 熔断器：同 turn 连续拒绝 3 次即 `InterruptTurn`（`circuit_breaker.rs`，非累计而是**连续**语义）；④ 压缩时图片按 token 预算原子裁剪（`compact_remote_v2_images.rs`）。
- **实现（两层收敛 + 已有预算尾部安全网）**：
  - `toolkit.py`：新增 `VISUALIZATION_CRITICAL_REVIEW_ROUNDS_LIMIT = 3` 与连续计数 `self._consecutive_critical_review_rounds`（`_update_tool_result` 中：带 `freshReviewCount>0` 的 view_image 轮次，任何回执 `requiresRevision` → +1，全新干净轮 → 清零；**缓存重看不计数也不清零**，view_image 回执新增 `freshReviewCount` 字段，`_review_one_image` 缓存命中带 `cached` 标记）；`has_current_visual_review` 在闸门触发后接受 `requires_revision` 的当前图片；`submit_script` 在闸门触发时跳过 `report_code_visual_revision_required` 拒绝，改为在成功回执附 `warnings: [{code: report_code_visual_review_rounds_exhausted, details: {criticalRounds, flaggedCharts}}]` 软告警并打 loguru warning。
  - `delivery.py`：`build_delivery_state` 新增 `visualReviewGate: {tripped, criticalRounds}`，触发且 nextTools=submit 时 `requiredAction` 明示"剩余 critical 已降级为软告警，直接提交"；闸门触发后 `visualFailures` 自动清空（has_current_visual_review 放行）。
  - `protocol.py`：`get_request_params` 检测 `visualReviewGate.tripped` 时向当前 request metrics 追加 warning 事件并打 `report_code_visual_review_rounds_exhausted` 日志；预算尾部安全网（`_visual_budget_gate_triggered`，agent-17 早期已实现）保持不变。
  - `metrics.py`：`build_coding_metric_sample` 新增请求级 `warnings` 有界投影（≤8 条，code ≤128 字符，details 只保留标量，str ≤128）。
- **语义对齐说明**：采用 codex "连续拒绝"而非"累计"语义——持续收敛的修复循环（每轮问题变少最终干净）不会误触发；原地打转（连续 3 轮仍要求修订）才熔断降级。第 2 层"同图停滞检测"已被连续语义覆盖（停滞图每轮都贡献计数），未单独实现。
- **验收**：新增 6 个用例（熔断触发→submit 软告警、连续计数清零、缓存重看不清零、freshReviewCount 真实回执、协议 warning 事件、metrics 有界投影）；既有 2 个 view_image 精确断言补 `freshReviewCount` 字段。13 文件合并回归 **622 passed，1 failed**（唯一失败仍为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`）。`ruff check` 全绿。
- **风险登记**：limit=3 比历史通过样本的实际修订轮数激进（candidate-25 有多轮修订后最终干净通过）；连续语义使持续收敛样本不受影响，但"修 3 轮仍有 critical"的样本会提前带软告警提交，最终交付图片可能残留 critical 缺陷（软告警口径，符合 AGENTS.md"语义业务校验只需要软告警"）。真实影响由 candidate-28 回放验证。

**2026-09-24 candidate-28 真实回放（收敛闸门后首个样本）`status=failed`：** `failureCode=report_code_script_edit_invalid`，总 `441.7s`，仅 6 请求（早停，未耗尽预算）。关键轨迹：req1 首写被 AST helper 闸门拦截（`generic_loader`，**第三次真实触发**）；req2 占位脚本被 `no_output_write` 拦下；req3 写入成功；req4 首跑 `ValueError`（`month_of` 用 `re.search` 解析月份失败，非路径解析器故未被 AST 拦截）；req5/req6 两次 `edit_script` `no_valid_blocks`，模型停止调用。与 candidate-19/27 同属"编辑补丁格式无效后早停"族。**收敛闸门未被触发**（样本未到达 view_image 阶段）。当前失败族分布：编辑早停族（19/27/28）已成为 AST helper 拦截后的主要失败族，根因是模型连续产出信封格式无效的补丁（`no_valid_blocks`）后放弃，而宿主的 repairHint/最小片段回执未能挽回。

**2026-09-24 candidate-29 真实回放（收敛闸门后第二个样本）`status=passed`：** 总 `919.071s`；Coding 33 请求、33 次工具调用、`807.710s`，input `1,584,493` / output `58,719` / reasoning `31,914`，toolCounts：`write=4、run=4、edit=6、read=12、view=5、submit=2`。关键轨迹：req1 首写被 AST helper 闸门拦截（`generic_loader`，**第四次真实触发**）；req2 路径规则拒绝（`os.path.join`）；req3 占位被 `no_output_write` 拦下；req4 写入成功；**req5 首跑成功**；req6/7/24/26/32 五轮 view_image 审查；req25 一次 submit 被 `report_code_visual_review_required` 拒绝（尚有图片未审查，非修订问题）；req33 最终提交成功。**收敛闸门未触发（无误伤）**：请求级 warnings 为空，说明连续修订计数从未达到 3——样本的审查轮在持续收敛，验证了"连续语义不误伤收敛型样本"的设计目标。`criticalVisualDefect=false`、`rawProtocolCorrect=true`、10 项 reviews 全过、17 产物齐全。

**闸门后样本统计（全部改动到位后）**：candidate-26/29 passed（其中 26 未触发任何 helper 拦截、29 触发 4 次）；candidate-27/28 failed（编辑补丁 `no_valid_blocks` 早停族）。通过样本 4 个（23/25/26/29），失败 6 个（20/21/22/24/27/28）。收敛闸门真实"触发降级"路径仍无正样本（需出现连续 3 轮修订未收敛的运行），但"不误伤"已由 candidate-29 真实验证 + 6 个单测覆盖。

**2026-09-24 编辑早停族修复（candidate-19/27/28 对策第 1 项已实施）：** 根因分析：candidate-27/28 的 `no_valid_blocks` 表示外层信封（`*** Begin Edit / *** SHA256`）正确，但正文没有合法 `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` 块——模型大概率发出了 codex 风格 apply-patch 差异（`*** Update File` + `-/+` 行），且两次原样重复后触发 `repeated_identical_patch` 终止。原先的 repairHint 只在第二次失败后出现且只讲"更小补丁"，不教格式。修复：`edit_patch.py` 的 `report_code_script_edit_invalid` 消息追加**可逐行复制的信封模板**（`*** Begin Edit\n*** SHA256: <read_script 回执的 64 位十六进制>\n<<<<<<< SEARCH\n...\n=======\n...\n>>>>>>> REPLACE\n*** End Edit`），首次失败即达模型；消息同时显式排除 apply-patch 差异格式。消息共 294 字符，低于 512 截断。新增 1 个用例锁定模板标记（含 apply-patch 差异输入形态）；`test_reporting_code_edit.py` 55 passed，相邻组合 237 passed，ruff 通过。

**2026-09-24 candidate-30 真实回放（补丁模板后首个样本）`status=passed`：** 总 `574.543s`——**全程最快通过样本**；Coding 19 请求、19 次工具调用、`512.371s`，reasoning **18,671**（当时历史最低），toolCounts：`write=2、run=5、edit=4、read=4、view=3、submit=1`。关键轨迹：req1 首写被 AST helper 闸门拦截（`generic_loader`，**第五次真实触发**）；req2 二次写入成功（无占位、无路径违规）；req3 首跑 `TypeError`、req5 二跑 `IndexError`，经 read+局部编辑后 req8 第三跑成功；三轮 view_image 审查全部收敛（闸门未触发、无 warnings）；req19 提交成功。**编辑补丁 4/4 全部成功，零 `no_valid_blocks`**——补丁模板落地后编辑早停族在本样本未再现。`criticalVisualDefect=false`、`rawProtocolCorrect=true`、10 项 reviews 全过、17 产物齐全。

**2026-09-24 candidate-31 真实回放 `status=passed`：** 总 `544.634s`，10 请求 / 10 次工具调用 / reasoning `10,444`——全程最快、reasoning 最低。轨迹：req1 helper 闸门拦截（第 6 次触发）→ req2 写入成功 → req5 首跑成功 → 3 轮视觉审查收敛 → 提交。全程零路径违规、零占位、零编辑失败。

**2026-09-24 candidate-32 真实回放 `status=failed`（provider wire 方差）：** 总 `110.3s`，仅 3 请求，`failureCode=report_code_custom_tool_protocol_error`——req3 provider 返回未声明或类型不匹配的工具调用，宿主按 `failure_policy.py` 的 FATAL 登记 fail-closed（不降级、不耗预算）。req1 helper 拦截正常、req2 写入成功，失败纯属 grammar 约束退化的 provider 采样方差，与本轮改动无关。

**2026-09-24 candidate-33 真实回放 `status=passed`（收敛闸门首次真实触发降级，关键验证）：** 总 `680.417s`，21 请求 / reasoning `15,918`。关键轨迹：req1 helper 拦截（第 7 次触发）→ req2 写入 → 两轮跑失败修复循环 → 视觉审查多轮修订连续 3 轮未收敛 → **req21 提交成功，回执附 warning `report_code_visual_review_rounds_exhausted / criticalRounds=3`**，最终指标 `criticalVisualDefect=true`（残余 critical 缺陷按软告警口径记账，供事后审计）。**闸门"连续 3 轮修订未收敛 → 降级软告警 → 强制收敛提交"的完整降级路径在真实链路首次端到端验证通过**；同形态的 candidate-20/21/22 均因 47/47 耗尽预算判 failed，candidate-33 以 21 请求完成。

**累计样本统计（candidate-20 至 33，同一 frozen-visual-v3 bundle）**：passed 7（23/25/26/29/30/31/33），failed 7（20/21/22/24/27/28/32）。全部改动落地后（收敛闸门 + 补丁模板）：29/30/31/33 连续 4 个非方差 passed；失败 1 个为 provider wire 方差（32，fatal by design）。AST helper 闸门累计 7 次真实触发（26/27/28/29/30/31/33 的 req1），每次触发后均在第二次写入内恢复。收敛闸门累计 1 次真实触发降级（33）。编辑早停族在补丁模板落地后（30/31/33）零再现。

**2026-09-24 R1（wire 形态混淆恢复）已实施，目标：工作流级成功率：** candidate-32 的失败归因是 provider grammar 退化下任务集内 FREEFORM 工具以 `kind=function` 返回（`write_script` 的 `{"source": ...}` JSON 参数完好），宿主按声明不匹配 fail-closed。R1 改为**有界恢复**：`protocol.py::_recover_wire_shaped_freedom_call` 在参数 JSON 可解且工具名在任务集内时，把 function 形态还原为 custom 形态，交给既有链路——stage 内正常执行、stage 外走既有软拒绝回执（stage 白名单语义不变）；恢复计数 `budget.wire_shape_recoveries` 上限 3 次/运行，超限仍 fail-closed。名称不在任务集（如历史测试中的 "outside"）或参数不可解时保持 FATAL。metrics 新增 `wireShapeRecoveries` 字段（budget → protocol 访问器 → `build_coding_metric_sample` → code_generation 接线）。顺带修复两个早于 R1 的既有失败用例：`test_batch_preserves_order_stopping_and_total_budget[limit-*]`（早前 WIP 把限额边界回执改为编码 rejected，测试断言未同步）与 `test_rejected_provider_call_keeps_usage_and_safe_identity`（按新语义拆分：任务集内 recover / 任务集外仍 FATAL 且 usage 保留、私密输入不进指标）。新增 3 个用例（恢复执行、stage 外软拒绝、超限 fatal）；14 文件回归 **647 passed，1 failed**（唯一仍为既有 `test_interactive_v1_end_to_end_responses_loop[asyncio-True]`）。ruff 全绿。

**2026-09-24 防御纵深核实（步骤 2 结论，无需新改动）：** 生产可视化章节已有四层兜底——① 协议层 R1 就地恢复（本轮新增）；② `visualization_section_workflow.py` 单 Task 内：retry 类 3 次 fresh attempt（带修复诊断）、retry_then_degrade 类 3 次后走 `degrade` 通道（**零图提交 + `report_visualization_degraded` 软告警，报告仍成稿**）；③ `analysis.py:854-1298` 报告级 fresh attempt 循环：任何 section 失败（含 FATAL）都换新 Task 重跑整章，completion conditions 由上轮错误推导，上限 `MAX_REPORT_SECTION_PHASE_ATTEMPTS × (MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION + 1)`；仅 `_VISUALIZATION_FATAL_ERROR_CODES = {"report_workspace_capability_missing"}`（确定性宿主缺陷，重跑不可修复）短路循环。④ 最坏现实 outcome = 降级成稿（零图 + 软告警），不是用户可见失败。回放 CLI 是**单次尝试**，其 pass/fail 系统性低估生产成功率；工作流级口径应以"自动兜底后是否成稿"衡量。

**2026-09-24 candidate-34..37 真实回放（R1 后验证批次，串行 4 个）：** 35/36/37 **passed**，34 failed——3/4 通过，且收敛闸门在 36/37 连续第二次、第三次真实触发降级（均 `criticalRounds=3` 软告警后提交成功，36 仅 15 请求 / 12.1k reasoning）。candidate-35 呈现"闸门韧性"形态：开头连续 7 次占位脚本被 `no_output_write` 拦下（预检持续生效、零预算失控），中段 8 次 `declared_output_missing` 探索循环（exit 0 零产物的老族仍在但可自愈），req37 最终提交成功（43 请求）。**candidate-34 暴露新失败族**：req18 `view_image` 时 vision reviewer 内部 `WorkspaceError(cause=ValidationError)` → `report_code_visual_review_unavailable` → terminal_failure，18/46 请求处死亡（余 28 预算）。根因：`vision.py::review` 在供应商结构化输出转换偶发失败后（日志 `Failed to convert response to output_schema`），Agno 把 `response.content` 退化为原始 JSON 字符串，`ReportVisionAssessment.model_validate(str)` 必然 ValidationError，被一律包装为"审查不可用"终局。修复：content 为 str 时改走 `model_validate_json` 按原文解析（真实坏响应仍抛 WorkspaceError 保持门禁语义）；新增 1 个用例锁定；15 文件回归 **655 passed，1 failed**（唯一仍为既有 `test_interactive_v1_end_to_end_responses_loop`）。candidate-38 已启动验证修复。

**累计样本统计（candidate-20 至 37）**：passed 10（23/25/26/29/30/31/33/35/36/37），failed 8（20/21/22/24/27/28/32/34）。全部当前改动到位后：29/30/31/33/35/36/37 七个样本中 6 过 1 新族（34，已修复待验证）；收敛闸门累计 3 次真实触发降级（33/36/37）；AST helper 闸门累计 8 次真实触发；wire 恢复计数 4 个样本均为 0（32 型方差未再现）。

**2026-09-24 candidate-38 真实回放（vision 修复后验证）`status=failed`，R1 暴露第二层退化形态：** 8 请求处死于 `report_code_custom_tool_protocol_error`。日志：req8 声明表只有 `submit_script/view_image`（交付已就绪），provider 返回 `read_script`（软拒绝回执，正常）+ `edit_script kind=function`；R1 恢复尝试失败——模型的 function 参数**不是 JSON 对象而是补丁原文本身**（`arguments` 直接是 `*** Begin Edit...` 文本），`json.loads` 失败 → FATAL。修复：`_recover_wire_shaped_freedom_call` 增加第二机会——参数以该 FREEFORM 工具的输入前缀开头（`*** Begin Edit` / `# Python` / `%%bash`）时直接按原文接收。新增 1 个用例（裸文本参数恢复）；15 文件回归 **656 passed，1 failed**（唯一仍为既有失败）。vision 修复本身未被本样本触发（未出现 review schema 转换失败），仍待样本验证。candidate-39 已启动。

**2026-09-24 candidate-39 真实回放（裸文本恢复后验证）`status=passed`：** **全程最快最省样本**——8 请求 / 9 工具调用 / 421.4s / reasoning **6,206** / 零编辑。轨迹：req1 先 run 被拒（脚本不存在）→ req2 helper 闸门拦截 → req3 路径规则 → req4 占位拦截 → req5 写入成功 → req6 首跑成功 → req7 审查 → req8 提交。所有预检按设计工作且零浪费。`rawProtocolCorrect=true`、`criticalVisualDefect=false`。

**2026-09-25 真实 CLI 端到端验证（cli-report-e556f25b，PTY 驱动，40 分钟被驱动超时截断，前半链完整）：** 上游全链（查询→数据集→分析计划→大纲）完成；analysis_item Coding ×2 提交；可视化 attempt-1 提交、attempt-2 因 provider 协议长尾失败（req14 输入膨胀至 172K、158s、0 工具调用）**生产 fresh attempt 循环现场自动换新**（四层兜底实录）；attempt-3 **收敛闸门生产首触**（criticalRounds=3）软告警提交成功；占位闸门连续 3 次拦截；信封归一化持续吸收 wire 退化。产出三项优化：

**2026-09-25 三项生产实证优化已实施（800 passed / 1 既有失败）：**
- **① planner binding 结构校验**（生产实证：planner 把 supplement 形状 dataPath `findings[1].rows` 签到 facts 文件上，模型照计划执行必然 KeyError）：`_validate_visualization_plan_bindings` 从软告警升级——绑定字段集合在该 analysisId 的签发描述中**唯一精确匹配**时自动改指 factPath/dataPath（loguru 告警 + 返回修正后的 plan，StrictModel 用 model_copy 重建）；无法唯一修正时抛 `report_visualization_binding_invalid`（details 含 availableDescriptors），由报告级 fresh attempt 携错误上下文重签（该码默认 retry 策略，未登记 FATAL）。
- **② 占位回执附最小骨架**（candidate-35 七连占位 + 生产任务 #4 三连占位实证）：`report_code_script_no_output_write` 消息追加可逐行复制的最小脚本骨架（含首个签发产物路径字面值），镜像已验证有效的补丁模板手法；消息 387 字符 < 512 截断。
- **③ provider 实测输入回压**（生产实证：本地投影 ~36K 时 provider 实测 172K，本地门禁失明）：`project_with_metrics` 新增 `provider_input_hint`（protocol 在每次请求结算后记录 provider 实测 input_tokens），达到 `CODING_COMPACTION_PROVIDER_INPUT_GATE=100K` 时强制触发确定性压缩并强制走窗口重建路径，同时打 `report_code_input_inflation` 警告；压缩完成后清除提示避免持续强压。metrics 新增 `input_inflation_detected`。
- 测试：①拆分旧软告警用例为"可改指→自动修正"与"不可改指→终止"两组（fixed_phase_workflows + benchmark_variants），②骨架断言，③无提示基线不压缩 / 有提示强制压缩。17 文件回归 **800 passed，1 failed**（唯一仍为既有 `test_interactive_v1_end_to_end_responses_loop`）。ruff 全绿。

**2026-09-25 CLI 复跑（bash-q3mmq6zj）失败并归因——收敛闸门与 section 回执校验冲突（本轮引入的回归，已修复）：** 运行 50 分钟 / 8 个 Coding 任务后死于 `report_coding_workflow_output_invalid`。根因链：收敛闸门降级提交（回执 `requires_revision=true`）→ `_validated_visual_receipts` 把 `requires_revision` 与结构校验一起硬拒（`report_phase_artifact_changed`）→ 报告级 fresh attempt 重跑整章 → 再次降级提交 → 再次被拒 → **attempt-1..6 死循环**（这也解释了多次 section 重签）→ 重试耗尽 → 工作流输出无效 → CLI 终止。关键事实：未降级路径的 `requires_revision` 已被 `submit_script` 拦截，到达 section 边界的必然是降级回执——这道检查实际只挡降级路径，与闸门设计冲突。修复：`_validated_visual_receipts` 中 `requires_revision` 从硬拒改为软告警（`report_visualization_revision_soft_warning`）继续；sha/reviewed/passed 等结构身份校验保持硬性（对齐 AGENTS.md"语义业务校验只需要软告警"）。新增用例锁定：降级回执接受 + 未审查/sha 不匹配仍硬拒。该次 CLI 期间三项优化生产验证：binding 自动改指 4 次、收敛闸门 10 次触发、输入回压 0 次、占位骨架后无连拒。

**2026-09-25 CLI 第三跑（bash-4pyc0qxz）再次失败并归因——优化① 的硬拒过激（设计二次修正）：** 4 个 Coding 任务后同死于外层 `report_coding_workflow_output_invalid`；内部根因是**优化①新增的 `report_visualization_binding_invalid` 硬拒**：planner 产出无法按字段唯一改指的错配 → 硬拒 → agno step 层 attempt-1 重试再遇同形态错配 → 步骤失败 → 工作流输出无效。教训与修正：不可唯一修正的 planner 语义错配**必须回到软告警继续**（AGENTS.md 与 2026-09-23 拍板原则；执行层 AST/指令/修复回执已可兜底）——唯一字段匹配的**自动改指保留**（纯收益，两次生产触发均有效）。`_validate_visualization_plan_bindings` 最终形态：精确匹配放行 → 唯一字段匹配自动改指（告警）→ 其余软告警继续（details 含 availableDescriptors 供诊断）。测试同步改回"不可修正→软告警继续"。17 文件回归 **801 passed，1 failed**（唯一仍为既有失败）。

**2026-09-25 合并 origin/code（远端 Coding 收敛迭代 V1-V5/A1-A3 + chartInputs 预解析机制，+2967 行）与语义冲突修复：** 自动合并无文本冲突，但静默丢失/错位三处，逐一修复：① toolkit 的 `_reject_generic_data_helpers`（远端把 helper 硬拦降为软告警，按 8 次真实触发实证恢复硬拦，同时接入远端 `_collect_preflight` 多违规聚合与草稿隔离改进）；② bootstrap 指令索引拼接错位（远端 `[16:]` 按旧列表长度书写，跳过本方数据形状契约/禁 helper/路径逐字三条，补回 `[13:16]`，5567/5600 bytes）；③ 测试对齐远端改进（violations 逐项诊断、收敛计数 run_id 去重——同一 execution 多次 view_image 只算一轮，语义更精确）。合并后 17 文件 **809 passed，2 failed**（interactive_v1_end_to_end 为本方既有；visual_review_state[restart] 经 worktree 验证在纯 origin/code 同样失败，属远端既有）。commit：80af04c（merge）+ 848ef8e（语义修复）。

**2026-09-25 CLI 第五跑（bash-b4hysl4r，合并后验证，用户要求中途停止）—— 待修复问题清单：**

运行约 55 分钟后停止，上游链 + 多轮 section 签发完成，chartInputs/收敛闸门/helper 硬拦/降级通道均验证生效（submit 20+ 次、chart_input 8 次、收敛闸门 3 次、一次 section 走 degrade 零图兜底后继续、下一任务干净通过）。**卡住任务 `4196694c` 归因（24 请求，`report_code_no_progress` 终止）**：

- `declared_output_missing` ×6（零产物探索循环，candidate-22/35 老族在合并后代码仍偶发）；
- `edit_invalid` ×3（trailing_text ×2 / marker_in_block ×1，补丁模板存在但草稿机制下仍失败）+ `edit_not_found` ×1；
- `source_invalid` ×1（语法错误的草稿漏到 run 阶段才发现）。

**待修复问题（按优先级，未实施）：**

1. **`declared_output_missing` 回执缺“写出示例”**：回执只说缺哪些文件，不给怎么写对——修法与补丁模板同构：附单张图完整写出链示例（`fig.savefig(签发路径)` + Plotly `write_image/write_json`），低风险、针对主因。
2. **补丁连续失败与逃生口脱节**：草稿机制下连续 4 次 `edit_invalid` 后 rewrite gate 未接住（13 次 edit 仅 1 次 write）——需复查草稿状态下 write_script 的可用性语义与 `_edit_failures_since_progress` 计数是否覆盖草稿编辑路径。
3. **语法错误草稿漏到 run**：`write_script` 有 compile 预检，`edit_script` 应用草稿时缺——补丁落盘前加 compile 检查，把 `report_code_source_invalid` 前移到 edit 阶段。

正面确认：降级通道正确兜底（no_progress → degrade → 零图继续成稿）；占位骨架本跑 0 触发（模型首写质量提升）；chartInputs 数据未核对按软告警继续交付。

**专项收口结论（工作流级成功率）：** 至此每个**已被观察到的失败族**都有结构性修复并在真实回放中验证过至少一次（触发型）或单测覆盖（保险型）：

| 失败族 | 修复 | 验证 |
| --- | --- | --- |
| 占位/零产物 write | write 阶段闸门 | 真实触发 10+ 次 |
| f-string / helper / 路径 | 指令 + AST 预检 | 真实触发 8 次 |
| 编辑补丁格式 | 失败消息附模板 | 30/31/33/39 零再现 |
| 视觉审查循环耗尽 | 连续 3 轮收敛闸门（软告警降级） | 真实触发 3 次（33/36/37） |
| wire 混淆（JSON 参数，32 型） | R1 还原为 custom | 单测 3 用例，真实触发待样本 |
| wire 混淆（裸文本参数，38 型） | R1 第二机会（前缀匹配） | 单测 1 用例 |
| vision schema 转换退化（34 型） | `model_validate_json` 原文回退 | 单测 1 用例 |

生产四层兜底（协议 R1 / Task 内 retry×3+degrade / 报告级 fresh attempt / 降级成稿）保证最坏 outcome 是降级成稿而非用户可见失败；残余 provider 方差的单次失败成本已从 47 请求 / 1100s 降至 3-8 请求 / 110-420s。样本总账（20 至 39 共 20 个）：passed 11 / failed 9；当前全部改动后 9 个样本 7 过 2 败（败因均已修复）。

**2026-09-24 candidate-15 待办 a 已实施（edit_script invalid 诊断白名单，先写失败用例再实现）：** 与上条"edit_script 失败最小片段回执"互补、不重叠——上条作用于 `not_found/ambiguous/overlap` 的**源码片段回执**（修 model 上下文），本条作用于 `report_code_script_edit_invalid` 的 **metrics 观测归因**（修 firstToolFailure.diagnostics=null 缺口）。① `edit_patch.py::parse_edit_patch` 失败 details 新增分支化 `reason`：`oversized_patch`（附 `actualBytes/limitBytes`）、`trailing_text`、`missing_envelope`（含 bad_sha/wrapped，正则层不可区分）、`no_valid_blocks`、`marker_in_block`（附 `blockIndex`）；patch 原文与源码不进入 details（测试锁定不变量）。② `metrics.py::bounded_failure_diagnostics` 白名单透传 `reason`（≤256 字符）与 `blockIndex/actualBytes/limitBytes`（int）。验收：新增 6 用例（parse 分支 5 + metrics 透传 1）先失败后通过；`test_reporting_code_edit.py + test_reporting_code_agent_metrics.py` 107 passed；相邻 delivery/diagnostics/tool_contracts 102 passed；ruff 与 `git diff --check` 通过。下一轮回放的 edit invalid 样本可直接从 `firstToolFailure.diagnostics.reason` 归因，无需工作区反推。待办 b（facts 行数组与 supplement 表格形状差异澄清）未实施，按单变量原则单独拍板。

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
- [ ] 可视化真实 provider A/B 已尝试但未进入 Coding；新冻结输入见 2026-09-22 报告，路径漂移的具体原因仍待有差集的失败样本确认。单独 legacy planner 后续通过不代表两阶段收益验收。2026-09-23 只读诊断（子 agent）补充 candidate 修复轮非法 `edit_script` 的根因假设：按时序重建，"仅声明 `run_script`"的轮次要求编辑后的脚本已成功运行且预检未出结论（第 3 次响应应为 `edit_script + run_script` 多调用批次，可离线状态机模拟验证）；模型在该轮仍判断需要修改脚本，而当轮 `edit_script` 不在声明表内、没有 Lark grammar 约束输出形态，provider 退化为通用 `function_call` 类型返回，宿主 fail-closed 拒绝正确。现有证据无法区分模型/网关责任，也不能归因于 candidate 投影（后续同路径续修未复现）；revision-3 的 candidate-result.json 与 revision-2 失败差集随 /tmp bundle 清理无法恢复。2026-09-23 **H1 时序重建已离线确认**（真实 toolkit/delivery/protocol 代码 + 脚本化工具结果的状态机探针，新增 `test_reporting_delivery_state_machine_probe.py` 3 passed）："仅 `run_script`"状态在 4 请求预算内只有"第 3 次响应为 `edit_script + run_script` 同批多调用"一条可达路径；到达该状态后工具声明恰只含 function 型 `run_script`，provider 此时返回 function 型 `edit_script` 必然越界被拒。非法调用剩余问题收敛为可采样统计的拒绝率（无 grammar 约束时 provider 退化形态），不再是未解时序。另查明：旧 bundle 不可恢复（分析缺两份授权 CSV 物理字节，全盘/DB/git 无副本，SHA 已留档，恢复需从 StarRocks 按 facts provenance 重新物化；可视化 trace 提取因旧 planner 缺 `dataDescriptors` 按设计拒绝，prepare.py 路线三项输入全丢，详见 `/tmp/reporting-bundle-params/NOTES.md`）；新持久可视化冻结输入已重建于 `.local/reporting-validation/frozen-visual-v2/`。**2026-09-23 分析 bundle 已恢复：** 两份 CSV 按 facts provenance 从 StarRocks 重新物化（无 ORDER BY 导致 12 个连续块随机排列，用 trace 中三个分析会话的探索输出锁定遭遇序 + sha256 全排列命中逐字节验证，证据链见 `/tmp/reporting-bundle-params/RECOVERY-EVIDENCE.md`），bundle 重建于 `/tmp/reporting-r7-analysis-v2`（及 low 变体）并 validate-only 通过。（**2026-09-24：** 可视化侧由 frozen-visual-v3 首个非删失 passed 样本推进，详见上方两段 2026-09-24 记录；"可视化真实 provider A/B 未完成"状态不变，本行分析侧恢复记录保持不变。）

**2026-09-23 分析 low 档 requirements 配对（R7.1/R7.3 首个 low 档配对证据）：** 同一 bundle、`deepseek-v4-flash-0731`、Coding low / planner high、summary=auto、enable_thinking=true、parallel_tool_calls=true，legacy/candidate 交替串行各 3 组，6/6 全部交付、零删失（产物 `.local/reporting-validation/requirements-ab-20260923/`）。描述性结果（n=3）：Coding reasoning legacy P50 8,198 vs candidate P50 1,157；planner reasoning legacy 317–379 vs candidate 3,400–5,412（签发 requirements 的约 10 倍拆解开销）；**主指标 planner+coding legacy P50 8,545 vs candidate P50 4,557（约 53%）**，但 candidate-1 长尾 10,448 超过全部 legacy 样本，candidate 方差远大于 legacy；**首次运行率 candidate 3/3 vs legacy 0/3——与 high 档历史形态（candidate 首跑率下降）相反**，low 档下 candidate 在推理和首跑率两面均占优；candidate planner 签发数量 3/2/10 波动大，决策稳定性边界与历史记录一致；rawProtocolCorrect 新口径 6/6=true（信封 legacy×1、candidate×0，不再记违规）。边界：n=3 仅描述性，candidate-1 仅 2 项对账覆盖面偏薄未定性，未做独立数值复算；探针 replay grammar 保真 2/2 未过（provider replay 轮约束退化信号，本次 6 组未产生协议违规）。是否推广 candidate 仍需更多配对样本与独立数值验收。

**2026-09-23 晚 扩样 8 对 + 独立数值复算 + planner-low 配对（R7.1/R7.3 收尾证据）：**

- **8 对扩样（同 bundle、同 low 档配置，交替串行，产物同目录）**：legacy 8 组 7 交付（legacy-7 planner 判无需 Coding 被 benchmark 门禁拒绝，为 legacy 侧 planner gate 样本级失败，不计主指标）；candidate 8/8 交付。主指标 planner+coding reasoning：**legacy P50 9,773（8,465–12,862）vs candidate P50 6,965（3,050–12,400，约 71%）**；**首跑率 candidate 7/8 vs legacy 0/7**；candidate 两次长尾（10,448/12,400）高于 legacy P50，方差仍大。较 n=3 快照（4,557 vs 8,545）差距收窄但方向不变：low 档下 candidate 主指标与首跑率仍双优。
- **独立数值复算（`verify_numbers.py`，标准库 csv+Decimal 从两份源 CSV 直接聚合，不调用生成侧任何函数）**：15 个交付样本共 **6,096 个数值单元格全部通过独立复算，零数值错误**；67 项对账 consistency-ok、1 项 unverifiable（样本无可定位总体行）、20 项 unclassified。残余差异全部为**维度覆盖缺口**（软告警口径）：candidate-1 确证覆盖面窄（indicator 缺 5、area 缺 2、科室缺 46 标签），但 legacy-4 同样缺 56 个科室标签，其余 candidate 仅缺 财务处/日间治疗中心/脑病中心 等 1–2 个长尾标签——覆盖缺口两侧都有，candidate-1 是离群而非系统性退化。复算脚本自身校准出 6 类口径误判并已修正（2024 占比被"占比"关键词错归 2025、0-1 小数量纲、"1月"/纯数字月份格式、月份标签年份按列改写、表级年份语境误伤对比表、"总部院区"误命中总体行），修正记录全部留在脚本注释与 `recompute-report.txt`，不用舍入掩盖差异。
- **planner-low 单变量配对（candidate variant 固定，只改 plannerReasoningEffort high→low，各 3 组，6/6 交付零删失，产物 `.local/reporting-validation/planner-low-ab-20260923/`）**：planner reasoning low 档 1,648/1,649/3,272 vs high 档 2,590/2,789/3,597（2/3 样本省约 1–2k）；但**累计 reasoning low 档 2,083/5,411/8,423 vs high 档 3,105/3,559/3,816**——planner 省下的 reasoning 在 Coding 侧加倍回流（low-2 Coding 3,762/12 请求/首跑失败，low-3 Coding 5,151），首跑率 low 2/3 vs high 3/3。结论：**planner 保持 high，不推广 planner-low**；弱 planner 把成本下游化并伤及首跑率。
- 综合 R7.1 推广判断：low 档 8 对证据 + 独立数值复算零错误 + 首跑率 7/8 vs 0/7，支持维持现行生产默认（candidate，即动态 codingRequirements，`eea91c3` 起）；残余风险为 candidate 方差与 planner 签发数量波动（2–10 条），以 soft 告警持续观测，不阻塞。bundle 与参数已持久化到 `.local/reporting-validation/bundle-persist/`（/tmp 清理风险对冲）。

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
- [x] 冻结回放等待期间每 15 秒记录当前 phase、elapsed、remaining、最新 provider request index/status；`--output` 模式不再因 stdout 静默而无法区分长请求与进程异常。心跳只读请求指标，不改变请求参数、重试或 wall timeout。
- [x] 2026-09-23 使用冻结 visualization payload 做 60 秒观测探针：15/30/45 秒心跳均正常，最终在 61.285 秒写入 `status=timed_out`、`censored=true`，请求快照确认 `reasoningEffort=low`、`reasoningSummary=auto`、`enableThinking=true`、`parallelToolCalls=true`，phase 为 coding；该删失样本只验证配置与监控链路，不计入性能或成功率。
- [x] 首轮保留 reasoning，比较 `high`、`medium` 和 provider 明确支持的低档配置；不直接把 `off` 设为默认。
- [ ] 每种配置记录首次脚本通过率、首次 patch 应用率、首次运行成功率、critical 视觉缺陷率、总耗时、P50/P95 reasoning token、成本。
- [ ] 至少覆盖空值同比、格式化后源码、复杂局部 patch、视觉文字遮挡和工具失败恢复。
- [x] 已根据 provider usage 比较不同 `reasoning.effort` 的真实推理 token 和耗时：包含分析 high A/B、planner-medium 单变量诊断及可视化 low/medium/high 历史样本。历史证据不足以单独决定默认档位；2026-09-22 用户随后明确选择 Coding 默认 low、planner 保持 high。Responses API 的配置和验收均不再使用 `thinking_budget`。

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

### Codex 对齐的同一 `arun` 历史投影（已实现，待真实回放）

- [x] `TaskExecutionContextProjector` 在不修改 canonical Agno history 的前提下，识别已完成的 CodeMode `write_script`、`edit_script`、`run` custom 调用。
- [x] 识别已完成的旧 custom 调用并触发同一投影层的历史重建候选；保留 provider free-form raw input 原文，避免把 JSON 摘要伪装成 `write/run/edit` wire 输入。
- [x] 双重匹配 custom call 的 `call_id` 与 item `id`，确保 provider 用任一身份回填 tool result 时状态一致；assistant 正文伪工具调用仍不解析。
- [x] 投影 metrics 记录 `compaction_triggered`、候选调用数和原始字节量；canonical messages 不变。窄测试及 custom replay 手工验证通过。
- [x] 2026-09-23 补充：`project_with_metrics` 增加 `protected_call_ids` 参数，上下文压缩时保护指定 call_id 所在的 complete round 不被删除；incomplete batch（有调用但未全部返回结果）天然受保护，不依赖额外参数。用于确保当前部分完成的工具调用批次在压缩时不丢失，维护 Responses 调用链完整性。定向测试 `2 passed`，全文件 `57 passed`。
- [x] 2026-09-23 生产接线：`toolkit` 在 `last_failure` 记录 `callId`（不进入重复检测签名，相同失败更换 call id 仍计数）；delivery 状态 `lastFailure` 投影 `callId`；`protocol._project` 从未解决失败提取 `protected_call_ids` 传入投影层，保护仍代表当前源码 SHA 的 `read_script` 轮次，并整轮丢弃结果 SHA 已过时的单调用 read（无完整结果的批次仍交给 incomplete batch 保护）。此前失败的 3 个定向用例（失败身份 1 个、rebase 保留 2 个）全部转绿；reasoning replay、delivery、context、stability 受影响文件定向回归通过。
- [x] 2026-09-23 子 agent 修复 base 既有 6 个失败测试（均为测试替身/断言过时，无生产 bug）：stability 2 个改用含匹配事实描述的 `_visualization_payload()` 满足 R7.2 绑定交叉校验；trajectories outputContract 冒烟预算随 R2.1 schema 内联放宽到 1200 字节；evidence feedback 3 个替身改为文字结束 + 原生补交付延续（白名单未签发 submit_script 时的设计行为）。目标文件 67 passed、helper 相关 30 passed。另查明 `test_delivery_feedback_tracks_visual_receipts_and_changed_output` 的"flaky"是共享工作树并行编辑造成的混合状态假象，非测试或生产竞态；`test_reporting_code_continuation.py` 4 个与 `test_interactive_v1_end_to_end_responses_loop` 2 个在干净 HEAD（e82a80f）worktree 上同样失败，属在途工作的既有失败，未由本轮修改引入，留归其所有者处理。
- [ ] 真实 provider 回放确认输入 token、reasoning token、首次 patch/运行成功率和视觉质量不下降；未完成前不宣称已降低总耗时。2026-09-23 已取得首个完整非删失样本（健康探针先行、单次、未重试）：冻结 `.local/reporting-validation/frozen-visual/payload.json`、Coding low，`/tmp/reporting-projection-low-20260923.json` 为 `passed`，538.9 秒、25 次请求、累计 reasoning 31,293、cacheRead 217,088，`criticalVisualDefect=false`（首轮 X 轴标签裁剪 critical 经修复后六图全过）；但 `firstRunSuccess=false`、`firstPatchApplied=false`、`firstRepairSuccess=false`（9 次 edit 5 次被拒）、`rawProtocolCorrect=false`（provider 5 次 data 信封，宿主兼容解封）。输入 token 在 req18→20 从 30,640 回落到 16,395，与陈旧 read 丢弃设计一致；多次未解决失败后调用链未断裂，与 `protected_call_ids` 一致，但回放路径不持久化 `projectionMetrics`，压缩未触发也无直测，均为间接证据。单样本无配对基线，reasoning 仍高于 20,000 目标，不能宣称性能改善。

该实现只压缩已完成的旧 custom 调用，不限制当前 patch，也不改变 `parallel_tool_calls=True` 或宿主的顺序执行；若历史中没有可安全完成的旧调用，则保持原始 wire 内容。

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
