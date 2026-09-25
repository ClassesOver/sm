# 可视化与补证 Coding 下一轮迭代优化方案（2026-09-25）

> **执行说明：** 本方案承接 `2026-09-20-reporting-coding-performance-optimization.md`（下称"主计划"）截至 `9b1e3ab` 的记录，不重复其中已完成的项。每个迭代只改变一个变量，沿用主计划的测量纪律：冻结输入、串行真实回放、删失样本不进分位数、缺失 usage 保持 `unknown`、业务语义只做软告警、不加盲目重试、不放宽 SHA/patch/路径硬校验。步骤用复选框跟踪，只按测试和真实回放证据勾选。

## 0. 结论

1. **可视化仍是主要矛盾。** frozen-visual-v3 的 37 个非规划门禁样本单次通过 20 个（54%）。全部修复落地后的 c29–c39 为 8/11（73%），但 95% Wilson 区间是 43%–90%，与 c20–c39 的 55%（34%–74%）在统计上还分不开。通过样本总耗时 P50 为 575–728 秒，Coding 请求 P50 为 19–20 次，仍是 B0 首阶段目标（≤300 秒、≤8 次请求）的 2–3 倍。
2. **失败很贵。** 17 个失败里 10 个是 `report_code_model_request_limit`（47/47 次请求耗尽），平均 1,254 秒、Coding reasoning 60,676。按 c20–c39 的单次通过率折算，**每交付一个章节的期望墙钟约 1,478 秒**（通过均值 796 秒 + 0.45/0.55 × 失败均值 833 秒）。
3. **目前的修复方式是逐个失败族打补丁，已经接近收益上限。** 可视化公共指令从 09-22 的 16 条/3,026 B 增至 19 条/3,945 B，其中 16 条含"禁止/不得/不要/必须"。`write_script` 前有 6 个依次执行的 AST 拒绝器，一次只报第一个违规。即便如此，c13–c39 中 **22/23 个样本首写整稿至少被拒 1 次，平均 1.96 次**。每次被拒，模型都要重新生成整个脚本。
4. **根因是 Coding 在自己导航原始事实 JSON。** 模型按 `dataPath` 字符串读取两种形状：facts 的行对象数组和 supplement 的 `columns+rows` 表格，还要自己拼路径。形状误解（`KeyError: 'findings'`、`list indices must be integers`）、路径推导（join/dirname/getcwd/f-string）、通用 helper，以及"打印 facts 结构"的探索/占位脚本，是同一件事的不同表现：**模型不确定数据长什么样，所以先去探索**。主计划中 c3/c8/c10/c21/c22 的 stdoutTail 都是结构打印。宿主已在 `_validate_visualization_plan_bindings` 确定性校验过这些绑定，完全可以替模型把数据解析好。
5. **有一块墙钟成本还没有被量化：Kaleido。** Kaleido 1.x 每次 `fig.write_image()` 都会启动并关闭一个新 Chrome，官方建议用 `kaleido.start_sync_server()` 复用同一个实例。主计划记录过一次完整 10 图渲染约 183 秒，而每个样本会执行 2–16 次 `run_script`。现有 `executionSpans.script` 已经在记录这部分耗时，但从未拿来做墙钟分解。
6. **补证（分析）Coding 已基本收敛，剩余问题在质量和 planner。** low 档 8 对扩样中，candidate 的 planner+Coding reasoning P50 为 6,965（legacy 9,773），首跑率 7/8，6,096 个数值单元格零错误。剩下三点：
   - reasoning 主要花在 planner 上：签发 requirements 需要 3,400–5,412，而 Coding P50 只有 1,157。
   - 签发条数在 2–10 之间波动。
   - **维度覆盖缺口（candidate-1 缺 46 个科室标签）生产侧检测不到**，只在离线独立复算中发现。对账 `passed` 是脚本自己算、自己填的。

## 1. 证据盘点

数据全部摘自主计划的逐样本登记，统计脚本见附录。c11/c12 是 planner 身份门禁失败，未进入 Coding，不计入。

### 1.1 可视化 frozen-visual-v3 样本总账

| 样本段 | n | 单次通过 | 95% 区间 | 通过样本总耗时 P50/P95 | Coding 请求 P50 | Coding reasoning P50/P95 |
| --- | ---: | ---: | --- | --- | ---: | --- |
| c1–c39 全部 | 37 | 20（54%） | 38%–69% | 850 / 1,390 s（n=17） | 21 | 18,444 / 55,399 |
| c20–c39 | 20 | 11（55%） | 34%–74% | 728 / 1,246 s（n=8） | 20 | 18,671 / 57,531 |
| c29–c39（收敛闸门+补丁模板之后） | 11 | 8（73%） | 43%–90% | 575 / 871 s（n=5） | 19 | 14,009 / 28,603 |

失败族（n=17）：`request_limit` 10、`script_edit_invalid` 早停 4、wire 协议 2、视觉审查不可用 1。后三类已分别有对策（补丁模板、R1 wire 恢复、`model_validate_json` 回退），各有 1–4 个样本验证。`request_limit` 仍是均值成本最高的一族。

视觉 planner 只有 1–2 次请求，却耗时 64–206 秒，占通过样本总墙钟的 P50 13.7%（n=7，3.7%–32.9%）。

### 1.2 首写整稿被拒轨迹（c13–c39，已知 23 个）

| 首个被接受 write 之前被拒次数 | 0 | 1 | 2 | 3 | 4 | 7 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 样本数 | 1 | 10 | 6 | 4 | 1 | 1 |

拒绝码集中在三类：`report_python_source_path_invalid`（join/dirname/getcwd/relpath/未签发目录）、`report_code_script_no_output_write`（占位/探索脚本）、`report_code_generic_data_helper`（`load(p)` 类 helper）。c29、c39 依次被"helper → 路径 → 占位"拒绝，c23 依次被"路径 → 路径 → 占位"拒绝；每次只暴露一个违规。

### 1.3 墙钟构成：已知与未知

- 已知：`visualReviewDurationMs` 为 21–101 秒；planner 占比如上；零产物 run 的 script span 约 3.9 秒；完整 10 图渲染约 183 秒（单次观察）。
- 未知：每个样本的 Σ Coding 模型耗时、Σ 正式脚本耗时，以及被拒整稿消耗的请求耗时。这些字段已经在回放 JSON 里（`requestMetrics[].durationMs`、`codingMetrics[].executionSpans.script`），只是没有汇总。**V0 先补上这张表，再定 V1/V2/V3 的先后。**

### 1.4 补证（分析）

| 对照 | 结果 |
| --- | --- |
| high，n=3 | 累计 reasoning P50：legacy 11,767 / candidate 10,010；总耗时 P50：167.5 / 145.2 s |
| low，8 对 | planner+Coding P50：legacy 9,773 / candidate 6,965（3,050–12,400）；首跑率：0/7 vs 7/8 |
| low，n=3 拆分 | planner：legacy 317–379 / candidate 3,400–5,412；Coding P50：8,198 / 1,157 |
| planner-low | 累计 low 2,083/5,411/8,423 vs high 3,105/3,559/3,816，首跑率 2/3 vs 3/3，已否决 |
| 独立复算 | 15 个样本 6,096 单元格零数值错误；覆盖缺口：candidate-1（指标 5、院区 2、科室 46）、legacy-4（科室 56），其余 1–2 个长尾标签 |

## 2. 迭代路线

| 顺序 | 迭代 | 改什么 | 是否调用 provider | 进入条件 |
| --- | --- | --- | --- | --- |
| 1 | V0 测量闭环 | 墙钟分解脚本；把可视化接入 Coding-only 冻结 | 否 | 无 |
| 2 | V1 Kaleido 常驻 Chrome | 正式脚本包装器 | 否（离线确定性对照） | V0 显示 scriptExec 占比显著 |
| 2' | A1 补证覆盖率软校验 | 分析验收 | 否（用已有 15 个样本离线验证） | 无，可与 V1 并行开发 |
| 3 | V2 受信绑定数据预物化 | 可视化 Coding 输入 | 是，A/B | V0 完成 |
| 4 | V4 无进展快停 + 规则瘦身 | 交付状态机、指令 | 是 | V2 通过门槛 |
| 5 | V3 预检一次性回执 + 被拒整稿转草稿 | `write_script` 预检 | 是 | V2 后残余被拒仍 ≥0.5 次/样本 |
| 6 | V5 视觉收敛的质量口径 | 统计与宿主排版默认值 | 否（离线复渲染 + 审查） | 闸门触发率 ≥20% |
| 7 | A2 / A3 | 补证输出契约、planner 实验 | A3 是 | A1 完成 |

真实回放必须串行。c11/c12 并行时同时在 `chart_002` 身份门禁失败，单次串行探针却正常，不排除共享输入或缓存造成的相关采样。

### V0：测量闭环（半天，无 provider 请求）

**目的：** 把"时间花在哪"从推测变成逐样本数据，决定 V1/V2/V3 的先后。

- [ ] 用附录的 `scripts/coding_wall_breakdown.py` 汇总 `.local/reporting-validation/frozen-visual-v3/full-chain-candidate-*.json`，逐样本输出以下字段：
  - `plannerModelS`、`codingModelS`、`scriptExecS`（含 `scriptRuns`）、`visionS`、`residualS`；
  - `rejectedWrites`、`rejectedWriteS`、`rejectCodes`；
  - `firstSuccessfulRunRequest`。
- [ ] 按以下规则决策：
  - 通过样本的 `scriptExecS / seconds` 中位数 ≥20% → V1 排在 V2 之前（成本最低，且不影响模型）；
  - `rejectedWriteS` 中位数 ≥15% → V3 可以提前与 V2 并行开发，但真实 A/B 仍须串行；
  - 从通过样本的 `firstSuccessfulRunRequest` 最大值标定 V4 的快停阈值。
- [x] 扩展 `scripts/replay_visualization_task.py` 的 `--freeze-coding` / `--coding-only-payload`。目前第 630 行只接受 analysis，需要支持 visualization。V2–V4 的变量都不在 planner，冻结一次 planner 输出之后只重放 Coding，每个样本可以省下约 14% 的墙钟，并消除 planner 方差和身份门禁失败。
  - 2026-09-25 已实现（离线单测，未做真实回放）：可视化仅支持 candidate，legacy 在 planner 请求前拒绝。link 时用冻结 payload 中的 `visualizationPlan` 重走 `prepare_benchmark_coding_payload` + `normalize_replay_payload`，逐字比对签名 payload；授权输入须是 v2 输入的同 SHA 子集（planner 绑定后只授权被引用的事实文件）。
- [x] 统一报告口径，增加三项：
  - `expectedSecondsPerDelivery = 通过均值 + (1−p)/p × 失败均值`；
  - 通过率的 Wilson 95% 区间；
  - `gateTrippedRate`：因收敛闸门降级提交的比例，单列，不并入"通过"。
  - 2026-09-25 已在 `coding_wall_breakdown.py` 汇总中实现：`timed_out` 删失样本不进通过率与期望成本；`gateTripped` 按"通过样本的最终视觉回执仍 `requiresRevision`"确定性推导（只有闸门降级才能在该状态下提交），同时输出残余 critical 的 `category` 分布；Coding-only 样本 `plannerModelS` 记 0。

**验收：** 能对每个样本回答"模型等待、脚本执行、视觉审查、被拒整稿各占多少"；不补造历史缺失字段。

### V1：Kaleido 常驻 Chrome（宿主侧，模型无感）

**假设：** 正式脚本每次 `write_image` 都冷启动 Chrome，`run_script` 的耗时中有很大一部分是可以去掉的固定开销。

- [ ] 在 `smart_reporting/sandbox/matplotlib_defaults.py::run_reporting_script` 中，于 `runpy.run_path` 之前尝试 `kaleido.start_sync_server()`，在 `finally` 中执行 `kaleido.stop_sync_server()`。导入或启动失败时静默退回逐次启动，不影响脚本语义。`_script_process_cell` 已经统一经过这个包装器，无需改动模型可见的内容。
- [ ] 做离线确定性对照，无 provider 请求：取 V0 中已通过样本的最终脚本和工作区，开关各重跑 3 次，比较 `script` span P50 和产物 PNG（同 SHA，或像素差低于阈值）。
- [ ] 补测试：脚本抛异常后没有残留 Chrome 进程；未安装 kaleido 时路径不变；`docker/sandbox-tools` 镜像不受影响（该镜像仍禁止 kaleido）。

**门槛：** 10 图脚本的 `script` span P50 下降 ≥50%，产物视觉等价。未达到则撤回，只保留测量结论。

### V2：受信绑定数据预物化（根因治理，核心迭代）

**假设：** 宿主按已校验的 `dataBindings` 把每张图需要的数据解析成统一的表格文件，模型就不再需要导航原始 JSON。这会同时消除形状误解、路径推导、通用 helper 和探索/占位这四个失败族，并减少首写 reasoning。R3 已有同类先例：分析侧投影紧凑 `existingFacts` 后，首写 reasoning 从 11,948 降到约 3,947。

**设计：**

- 新增纯函数模块 `smart_reporting/reporting/workflow/runtime/chart_inputs.py`，提供 `materialize_chart_inputs(plan, facts, read_identity_bytes)`。只处理通过 `_visualization_binding_catalog` 校验的绑定；不匹配的绑定照旧软告警，并对该图回退为现有的原始 facts 路径。
- 解析规则全部确定性执行，以 descriptor 声明的形状为准，不猜测：

  | 绑定的 dataPath | 转换方式 |
  | --- | --- |
  | `findings[i]` / `findings[i].rows`（`rowEncoding=columns_rows`） | 原样取 `columns + rows`，保留 null 和 `nullableFields` |
  | `metrics[i].periodValues` / `topGroups` / `bottomGroups` | 行对象数组 → `columns = binding.fields`，`rows = [[obj[f] for f in fields]]` |
  | `metrics[i]` / `derivedMetrics[i]` / `comparisons[i]` | 对象 → 单行表，只取 `binding.fields` 中的标量字段 |

- 输出文件 `chart-input/v1`：`{chartId, role, source:{analysisId, path, sha256, dataPath}, columns, rows, nullableColumns, rowCount}`。
  - 写到 `chartOutputRoot` 之外的只读兄弟目录，例如 `<attemptRoot>/chart-inputs/<chartId>--<k>.json`，避免混入声明产物集合或视觉审查队列。
  - 由宿主写入并计算哈希，加入 `authorized_read_paths`。
  - treatment 臂只授权 chart-inputs，加上回退图所需的原始 facts；执行层的 AST 字面路径白名单会阻止模型读取其他 facts。
- 模型可见 payload 在 `analysis.py` 的 Coding facts 组装处（`facts_payload`）增加 `chartInputs: [{chartId, role, path, columns, rowCount, nullableColumns, preview: 前 3 行}]`。treatment 臂不再向模型投影 `visualizationFacts` 的 descriptors、metrics 和 findings；宿主仍保留完整 facts 用于审计和 citation。
- 指令收敛：在 treatment 臂中，把 metricIndex/findingIndex、rowEncoding、跨指标分组复用、数据形状契约、禁止 resolve/helper、facts≠supplement 这 6–8 条规则，替换为两条："每张图只逐字读取 `chartInputs` 中本图的 path；按 `dict(zip(columns,row))` 解码，null 保留并标注"。其余规则（百分比单位、全零、禁止默认值掩盖失败、Plotly 双产物）保持不变。
- 可选确定性数据核对（软告警）：Plotly 图可以把 `.plotly.json` trace 中的数值数组与对应 chart-input 的数值列比对，允许舍入误差和 ×100 百分比换算。无一匹配时记 `report_visualization_chart_data_unverified`。这项放在 V2 通过之后单独上线，不与 V2 同时改变。

**对照：**

- 新增 benchmark-only 投影开关（例如 `BenchmarkProjection.materialize_chart_inputs`，CLI 参数 `--chart-inputs on|off`），不复用 legacy/candidate 名称。
- 两臂均为当前生产 candidate，同一个冻结 planner 输出（依赖 V0 的 Coding-only 扩展），交替串行，每臂 n≥10。

**门槛（全部满足才推广生产默认）：**

- 首写被拒次数：≤0.5 次/样本（基线 1.96）；
- 形状类运行错误（`KeyError`/`TypeError` 解码错误）清零；
- 首跑成功率 ≥60%；
- Coding 请求 P50 ≤15；Coding reasoning P50 下降 ≥30%；
- 单次通过率不低于基线，且 treatment 至少 8/10 通过；
- `criticalVisualDefect` 和 `gateTrippedRate` 不上升。

**测试：**

- 覆盖每种 descriptor 形状、null、行列不等长时拒绝；
- 绑定不匹配时该图回退、其余图照常物化；
- sha/来源身份写入 chart-input，treatment 臂的授权路径集合正确；
- 修复轮（`_repair_task_facts`）保留 `chartInputs`；
- legacy 回放路径不受影响。

**风险：**

- 物化器本身出错会生成错图。缓解手段是确定性单测，以及上面的 Plotly 数值核对。
- 部分图需要跨绑定联合计算（例如占比 = 分项 / 总量）。chart-input 只提供数据，计算仍由脚本完成；不在宿主侧预算任何业务指标，不构成 DSL。

### V4：无进展快停 + 规则瘦身（压低失败成本）

**假设：** 长循环失败大多在前 20 次请求内就已经看得出来。与其耗满 47 次请求，不如尽早交给生产的 fresh attempt，带着紧凑诊断重来。按单次通过率约 0.6 计，这样的期望成本更低。

- [ ] 在交付状态中增加无进展判定，二者命中其一即以 retry 类失败码 `report_code_no_progress` 终止：
  - 请求序号超过 R 仍没有一次成功的 `run_script`，R 由 V0 按"所有通过样本的首次成功运行序号最大值 + 余量"标定；
  - 连续 K 次 `run_script` 失败，且 `(errorType, 所属函数)` 相同。

  判定只用宿主已经持有的回执，不新增模型请求。生产侧由 `visualization_section_workflow` 现有的 fresh attempt 接手，复用 `_repair_diagnostic`。
- [ ] 规则瘦身：V2 推广后，逐条删除被 chart-inputs 取代的指令（每删一批做一次单变量回放）。评估把 `report_code_generic_data_helper` 从硬拒绝改为软告警：统一形状下 `load(p)` 本身无害，真正的风险路径已经由字面路径白名单兜底。
- [ ] 对照：固定 V2 生产配置，只切换快停开关，每臂 n≥10。

**门槛：** 失败样本平均墙钟从约 833 秒降到 ≤450 秒；在接续一次 fresh attempt 的模拟口径下，`expectedSecondsPerDelivery` 下降；已通过样本不被误杀，用 V0 的历史 `firstSuccessfulRunRequest` 回放判定验证。

### V3：预检一次性回执 + 被拒整稿转草稿（条件项）

**进入条件：** V2 推广后，首写被拒仍 ≥0.5 次/样本，或被拒整稿耗时占通过样本墙钟 ≥10%。

- [ ] `toolkit.py::write_script` 的 6 个 `_reject_*` 改为收集模式：一次返回全部违规（每项包含 code、行号、≤300 B 片段、修正提示，上限 8 项）。主失败码沿用第一个违规，保证 `firstToolFailure.code` 统计可比；完整列表放进 `details.violations`，并加入 `bounded_failure_diagnostics` 白名单。
- [ ] 被拒整稿不落盘，只在 binding 内保存为隔离草稿，并返回 `draftSha256`，允许 `edit_script` 以该 SHA 对草稿打补丁。补丁后重新执行全部预检，通过后才写入签发脚本。`run_script` 永远不执行草稿；闸门、SHA、唯一匹配语义不变。这样被拒后就不必重新生成约 11 KB 的整稿。

**门槛：** 首个被接受 write 之前的请求数下降；`rejectedWriteS` 下降 ≥50%；`rawProtocolCorrect` 与首跑率不劣化。

### V5：视觉收敛的质量口径

c33/c36/c37 都靠连续 3 轮闸门降级提交，`criticalVisualDefect=true`。按现在的口径它们算"通过"，但交付的图可能仍有 critical 问题。

- [ ] 把 `gateTrippedRate` 与降级时残余 critical 的 `category` 分布单独报告，数据来自 binding 中的完整 receipt。
- [ ] 如果主要是 `text_overlap` 或标签密度一类问题，先尝试宿主侧确定性排版默认值：matplotlibrc 加 `figure.constrained_layout.use: True`，包装器里为 Plotly 设置 automargin 模板。用最终脚本离线复渲染，再调用生产视觉审查（不开 thinking，成本低）做对照，不调用 Coding provider。

**门槛：** 闸门触发率与残余 critical 数下降，且没有新增 critical 类别。

### A1：补证覆盖率确定性软校验（质量，离线可验证）

**问题：** 生产侧只校验 evidence 的结构，reconciliation 的 `passed` 由脚本自报。candidate-1 缺 46 个科室标签，只有离线复算才发现。

- [ ] 在 `analysis_item_workflow.py::_validate_evidence` 结构校验通过后，增加宿主侧覆盖率检查，结果只做软告警：
  1. 对 `codingRequirements[].fields` 中在签发 CSV 里属于低基数字符串的列（例如 distinct ≤500），读取全集；
  2. 用值集合重合来定位 finding 中对应的维度列，不按列名匹配，因此与主题无关；
  3. 全集中缺失的值记为 `report_analysis_dimension_coverage_gap`，携带 `outputName`、`coverageRatio`、最多 20 个缺失样例；
  4. 同时检查两个方向的单侧缺失告警是否齐全（主计划 09-22 样本曾遗漏"仅上年存在"方向）。
- [ ] 先离线验证：在 `.local/reporting-validation/requirements-ab-20260923/` 的 15 个交付样本上运行，以 `recompute-report.txt` 为真值。只有当 candidate-1 与 legacy-4 被检出、其余样本的误报率可接受时才接线。
- [ ] 告警第一期只进审计日志和 metrics，不进入报告正文，也不驱动 Coding 修复（不增加重试）。

**门槛：** 对已知缺口召回 100%，对"有意 TopN 过滤"类需求的误报可通过 `calculation` 文本或输出行数识别并降级。

### A2：补证输出与下游可视化对齐（软契约）

- [ ] `outputContract.rules` 增加一条："每个 `codingRequirements[].outputName` 对应一个 `findings[].name`"。宿主做软检查，缺失时记 `report_analysis_requirement_unfulfilled`。
- [ ] finding 可选增加 `columnMeta`（单位、是否百分数、期间角色），供 V2 物化时透传到 chart-input。这直接回应可视化侧"百分数是否已 ×100"那条规则：宿主给出单位，比指令提醒更可靠。

### A3：补证 planner 成本与签发稳定性（可选实验）

- 事实：planner 现在占补证 reasoning 的大头，签发条数 2–10 波动，10 条的样本同时拉高了 Coding 成本。planner-low 已被否决，不再尝试降档。
- 候选单变量（每次只试一个）：
  1. 向 planner 投影确定性的数据集画像（列角色、基数、期间覆盖），减少字段选择推理；
  2. 签发粒度指引改为"同维度多指标合并为一个 outputName"。
- 在分析 v2 bundle 上串行 A/B，每臂 n≥5。

**门槛：** planner+Coding P50 下降 ≥20%，首跑率不劣化，A1 覆盖告警不增加。

## 3. 统一实验协议

- **变量：** 每次只改一个开关；两臂使用同一冻结输入（v3 manifest `4c27385a…`），V2–V4 使用 V0 冻结的同一份 planner 输出。
- **样本：** 通过率类结论每臂 n≥10，并报告 Wilson 区间；n=10 时区间半宽约 ±20–25 个百分点，因此门槛同时看被拒次数、请求数、reasoning、墙钟这类更灵敏的连续指标。删失样本单列。
- **口径：** 报告 P50/P95、`expectedSecondsPerDelivery`、`gateTrippedRate`、`criticalVisualDefect`。缺失 usage 为 `unknown`，不补 0；不以 n=1 宣称收益。
- **停止规则：** 任一臂首跑率或最终质量下降，立即停止推广，不叠加下一个变量继续比较。

## 4. 不建议做的事

- 为新的失败族继续追加指令或 AST 规则。V2 之后应该让规则变少，而不是更多。
- 提高 47 次请求 / 46 次工具的预算来"救"长循环。主计划和 Codex 对齐结论一致：预算扩大只会拉长尾部。
- 把上下文压缩当作性能手段（四组对照已否定）；补证 planner 降档（已否定）；并行跑共享 provider 的真实回放。
- 在宿主侧预算业务指标，或建设通用图表/分析 DSL。V2 只解析已签发的绑定，不做计算。

## 附录：墙钟分解脚本

`scripts/coding_wall_breakdown.py`（只读，不调用 provider）：

```bash
.venv/bin/python scripts/coding_wall_breakdown.py \
  .local/reporting-validation/frozen-visual-v3/full-chain-candidate-*.json --csv /tmp/v3-breakdown.csv
```

逐样本输出 planner/Coding 模型时间、正式脚本时间、视觉审查时间、残差、首写被拒次数与耗时、首次成功运行序号，并汇总通过样本的 P50/P95、`scriptExecShare` 与失败码分布。字段缺失保持 `unknown`。已用构造的通过/失败/损坏三类 fixture 验证，Ruff 通过。

参考：Kaleido 1.4.0 发布说明中关于 `start_sync_server()` / `stop_sync_server()` 复用单个 Chrome 的说明，见 <https://pypi.org/project/kaleido/1.4.0/>。
