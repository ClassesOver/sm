# 标准算子三批修复验收记录

日期：2026-11-06。基线：4b543a5399d4de1ce786aa8203ad7d98ed6bd80d。
分支：audit/standard-supplemental-depth。
worktree：/home/junge/.codex/worktrees/b554/smart_reporting。
实施计划：[R01—R22](../plans/2026-11-06-standard-supplemental-repairs.md)。

## 当前结论

21项完成实现或核查；R19缺外部材料，用户明确答复“暂时没有”，保留未验收。七类算子仍为原七类，未扩展图表、工作流或依赖。原审查两个普通失败已转绿，保留原断言及原审查记录。

本次生产修复包括空白成员证明、原始行期间覆盖、旧证明消费边界、稳定失败诊断及两类数值溢出处理。业务语义问题只软告警；不改发布签发链路。完整总体证明支持输入身份和成员完整性，不代表所有派生值都能用有限浮点数表示，也不替代业务定义和取数验证。

## 完整逐项清单

“核查完成”表示所列契约已有独立样本和定向回归通过，未发现需要改动的生产缺陷；不是为完成清单而修改既有正确实现。

| 编号 | 状态 | 实际结果与证据 |
|---|---|---|
| R01 | 已修复 | `_read_rows` 对 null、空串、ASCII/Unicode空白发软告警；保留原标签、分组和金额，拒绝完整证明。`test_standard_population_proof.py`、独立F1回归。 |
| R02 | 已修复 | 服务端登记重查实际标签、成员清单/数量/哈希；语义目录撤回失格总体资格；持久化 TopN 解析拒绝空白标签。身份有效且重新登记的旧异常证明也被拒绝。`test_population_contexts.py`、`test_semantic_quantity.py`。 |
| R03 | 已核查 | 不自动 trim；`A`、` A `、字符串`0`保留为不同有效成员；无维度期间比较的内部空键不报错。 |
| R04 | 已修复 | proof 在scope过滤后检查实际有效行覆盖，不从父事实零推断有行。显式零月可签、其他scope的零月不可替代本scope覆盖。独立F2及`test_standard_population_diagnostics.py`。 |
| R05 | 已实现 | finding 的 `issues` 和 `populationVerification.issues` 保留 code/message/datasetId/outputName/periods；运行时补 tablePointer。代码包括 invalid_member、invalid_period、invalid_numeric、missing_period、identity_mismatch、reconciliation_failed、output_mismatch、parent_period_mismatch、missing_field、proof_error。不解析中文文案作分类。 |
| R06 | 已实现 | `populationVerification.status` 为 verified/unverified/not_applicable；不支持证明时不产生失败告警，支持但拒绝/异常有明确原因。旧dict/None API兼容，诊断为可选收集参数。 |
| R07 | 已实现 | 每表分别收集原因和指针；独立对照CSV的诊断绑定实际baselineDatasetId和对照窗口，无法解析的期间标注本次读取的请求窗口。一表证明异常后继续后表，另一表仍登记完整证明。runtime故障注入及3项对照定位反例回归。 |
| R08 | 已核查 | 不修改旧文件字节/哈希；下游只撤回证明资格，普通表仍可读。旧身份有效异常样本验证源bytes不变，未将其认定为文件损坏。 |
| R09 | 已核查 | 沿用BatchAnalysisInputCache，不新增文件读取或聚合扫描；额外覆盖来自已有rows集合。缓存回归覆盖单次解析、内容绑定、scope和授权独立。新增异常日志仅Loguru记录安全异常类型，不输出异常正文。 |
| R10 | 已核查 | summary/series/cross缺期缺组不补零；合法重复明细累加；边际合计不能再次跨行求总。独立表格、缺期和cross单元样本。 |
| R11 | 已核查 | 日历配对、signed/absolute、窗口贡献/排名、零基数/零变化均保留原契约。independent、generic、period_comparison及boundary回归。 |
| R12 | 已核查 | 操作数先聚合再相除，单位换算和有序父事实绑定；零分母保留操作数/差额，ratio空。period_ratio、zero_denominator、routing及独立1/1+9/99样本。 |
| R13 | 已明确口径 | 保留各自有效操作数独立汇总；finding标注`operandAggregation=independent_valid_sums`，无效输入有结构化原因。分子100/invalid与invalid/分母50仍为100/50并告警；未擅自改为同行删除。 |
| R14 | 已核查 | 各组和总体独立计算均值/中位数；中位数不可加时保留实际残差和空贡献，不配平。 |
| R15 | 已核查 | 完整尾部、跨期先合并、HHI不乘10000；负净组HHI空；有限CR5可超过1，不clamp。concentration及独立尾部样本。 |
| R16 | 已修复并核查 | 比率/差额溢出各自置空，保留其他有限操作数和派生值；summary/series/cross占比及CR5溢出置空并告警。14项极限样本覆盖大/小数、消减、微小分母、NaN/Inf、抵消后微小总体及严格JSON有限性。未改容差、未引入全面Decimal。 |
| R17 | 已核查 | 原36项独立验证全通过。csv/Decimal期望不调用生产聚合、期间、单位换算或对账helper；Hypothesis保持确定性设置。 |
| R18 | 已核查 | 同总额错误成员、期间、scope、hash拒绝证明；共同聚合依赖故障仍会使生产与proof一起错，独立Decimal基准能识别。保留此盲区演示，不新增第二套生产引擎。 |
| R19 | 未完成 | 用户暂无真实定义、grain/行键、SQL+参数+连接基数及冻结CSV。只读检索本机output发现历史探针/投影样本，未将其认定为这条完整业务证据；未读取生产库或提交新报告。待材料齐全后才能作真实业务验收。 |
| R20 | 已核查 | 正常冻结从实际CSV行形成periodValues；按原身份模型读回保持原期间；旧兼容reader保留原始document/raw，不补月份、不复用新语义。缺月与显式零月分别回归。F2仍定位为防御修复，未发现正常生产路径制造无行零月的证据。 |
| R21 | 已核查 | proof异常不阻断证据文件签名/后续表。项目规定的发布非阻断用例75项通过，含签发溯源故障和静态raise守卫。没有新增签发步骤/函数，无须扩展签发故障注入登记。 |
| R22 | 已交付 | 原审查记录、三批计划、本报告、源码与回归留在隔离worktree；R19单独未验收。初次交付未提交或推送；后续按用户要求准备PR，记录见下。 |

## 新发现的数值反例

1. 分子`1e308`、分母`1e-308`：原ratio溢出会连有限分母和有限差额一起清空。现在保留分母`1e-308`、差额`1e308`，仅ratio为空。分子`1e308`、分母`-1e308`时仅difference为空，ratio仍为-1。
2. 分组`1e308,-1e308,1e-308,0,0,0`，总体`1e-308`：原summary/series/cross的份额及CR5会出现Inf，严格JSON序列化失败。现在保留原金额，仅不可表示的占比为空且软告警。没有把这些值改成零、截为1或放宽对账。

这些是确定性人工极限样本，不声称真实业务出现过此量级。14项样本不能穷尽浮点数全部输入组合；本次没有改写原始聚合引擎。

## 测试证据

统一从worktree根目录使用`/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q`执行，仅定向回归，不运行全仓完整测试。以下为实际成功结果；出现新改动才重跑直接依赖。

| 批次 | 测试选择 | 实际结果 |
|---|---|---|
| 第一批首次绿 | independent、standard_population_proof、population_contexts、semantic_quantity | 116 passed / 10.77s |
| 第二批 | standard_population_diagnostics、standard_supplemental_artifact、standard_supplemental_input_cache | 55 passed / 9.01s |
| 第三批初次核查 | numeric_limits、parent_coverage，以及standard_supplemental、period_comparison、period_ratio、concentration、boundaries、generic、zero_denominator、routing、ruijin_six_domain_semantics | 264 passed / 14.28s |
| 登记加固后 | population_contexts、standard_population_diagnostics（含新增scope覆盖） | 22 passed / 8.23s |
| 最后数值修复后 | numeric_limits、independent、standard_population_proof、semantic_quantity、standard_supplemental、concentration、period_comparison、generic、standard_population_diagnostics | 230 passed / 11.57s |
| R07对照诊断定位补修后 | standard_population_diagnostics、independent、period_comparison、standard_supplemental_artifact、standard_supplemental_input_cache | 121 passed / 10.85s |
| 发布非阻断契约 | 见下列精确命令 | 75 passed / 2 deselected / 47.16s |

这些批次存在交集，不能直接相加当作不同用例总数。按上述全部文件/节点的并集另作收集校验：516/518 tests collected（2 deselected），退出0，12.24s；首轮516个选中用例均已在上述批次通过。随后R07新增3项对照定位回归，当前分批覆盖519个不同用例，未将收集视为执行。唯一警告为既有第三方visions的imghdr弃用。

最后230项命令：

```bash
/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q \
 smart_reporting/reporting/tests/test_standard_supplemental_numeric_limits.py \
 smart_reporting/reporting/tests/test_standard_supplemental_independent.py \
 smart_reporting/reporting/tests/test_standard_population_proof.py \
 smart_reporting/reporting/tests/test_semantic_quantity.py \
 smart_reporting/reporting/tests/test_standard_supplemental.py \
 smart_reporting/reporting/tests/test_standard_supplemental_concentration.py \
 smart_reporting/reporting/tests/test_standard_supplemental_period_comparison.py \
 smart_reporting/reporting/tests/test_standard_supplemental_generic.py \
 smart_reporting/reporting/tests/test_standard_population_diagnostics.py
```

非阻断契约命令：

```bash
/home/junge/pros/smart_reporting/.venv/bin/python -m pytest -q \
 smart_reporting/reporting/tests/test_publication_nonblocking.py \
 smart_reporting/reporting/tests/test_report_artifact_persistence.py::test_publication_gate_exception_preserves_download_input_and_failed_validation \
 smart_reporting/reporting/tests/test_http_publication_lineage.py::test_http_publication_never_blocks_links_on_lineage_faults \
 smart_reporting/reporting/tests/test_http_publication_lineage.py::test_http_publication_drops_hash_registered_foreign_index_but_still_issues_links \
 smart_reporting/reporting/tests/test_report_editor.py::test_editor_export_creates_new_revision_without_overwriting_published_markdown \
 smart_reporting/reporting/tests/test_report_editor_lineage_export.py::test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing \
 smart_reporting/reporting/tests/test_report_editor_lineage_export.py::test_export_revision_registers_ai_chart_edit_and_still_issues_links \
 smart_reporting/reporting/tests/test_report_editor_lineage_export.py::test_export_revision_registers_l2_chart_edit_plot_data \
 smart_reporting/reporting/tests/test_report_editor_lineage_export.py::test_export_revision_registers_table_edit_and_still_issues_links \
 smart_reporting/reporting/tests/test_reporting_completion_content.py::test_completed_report_content_states_the_specific_validation_reasons
```

先红后绿记录：原F1/F2两项失败；成员/消费端新增7项失败；诊断与runtime新增11项失败；原比率溢出2项失败；登记正文空白1项失败；占比溢出4项失败；对照数据集/期间定位3项失败。均在修复前观察到预期缺口，未使用skip/xfail或放宽期望。R20新核查直接通过，未为其编造生产修复。Ruff最终检查通过；没有安装/升级依赖。

## 第三方复核与证据边界

可按固定CSV字节、手写/Decimal期望、Hypothesis设置、签名身份故障注入及以上命令复核。哈希证明文件身份；总额闭合证明相应等式；既有proof复算和生产仍共用聚合器，不能取代独立基准。业务指标是否可加、SQL是否重复连接、真实明细是否完整，仍需R19材料及业务责任人确认。

没有新提交真实AgentOS报告，没有声称完成真实下载端到端实测；发布证据为项目既有非阻断契约的定向测试。旧的无行零月proof若没有原始CSV，消费者无法仅凭历史JSON追溯原始行覆盖；本次生成端已补覆盖核验，未伪造历史覆盖记录。

## 文件身份

以下为本次交付源码/测试的SHA256；初审报告中的旧hash仍作为历史记录保留。

| 文件 | SHA256 |
|---|---|
| smart_reporting/reporting/workflow/runtime/standard_supplemental.py | fee774ff257d595e8fe44373ac625a5e3078dd4d0240845f45eda65949f671ef |
| smart_reporting/reporting/workflow/runtime/analysis.py | 7e9e80669e4f44d632df0ea3ff234be48c2d28d2685449051be1ce8e80d131c5 |
| smart_reporting/reporting/workflow/runtime/sections.py | 224421c82ad0bee83c4a9ed14b59c8d9de31fdf390866948e4cdda0ed439f9f6 |
| smart_reporting/reporting/trace/table_sources.py | 487114ecbfa18cd1f56a41c05d1a5b7726b4298697bd9c411ec5b7534630c6a1 |
| smart_reporting/reporting/trace/semantic_quantity.py | c3382bd216e61b2e8c3363653d81ed6e37cac41d196730d31df172b92b314da2 |
| smart_reporting/reporting/tests/test_standard_supplemental_independent.py | 8289b32ecee12cc09f3e546d77c07f19965f04d298cc4dedfaad366778441d34 |
| smart_reporting/reporting/tests/test_standard_population_proof.py | 3827c013e98fa0af701f404bcd14b092fadd50f49770a8db213d34fe2e5b9911 |
| smart_reporting/reporting/tests/test_population_contexts.py | de38d062dd866866ced71182c298eb5c3a21dd21f4d3b33957d67d7dd323b7ee |
| smart_reporting/reporting/tests/test_semantic_quantity.py | 0caaf31dee56afd874b526e58b3dda8e58d373c87b6de3c9f9e884dc1469212d |
| smart_reporting/reporting/tests/test_standard_supplemental_artifact.py | c3f3abac32da33d4ae7e036dc2258fb9df811cbccd98f8c74b9ea15f58cee96e |
| smart_reporting/reporting/tests/test_standard_population_diagnostics.py | 8a68294939f8a47376f5c635b91df157153e9900a0eaf445002c386a5af9a38f |
| smart_reporting/reporting/tests/test_standard_population_parent_coverage.py | 1a19c050ed7f79b45f49e57617350d8a55c797b1742bce243b91c4723a4b6aea |
| smart_reporting/reporting/tests/test_standard_supplemental_numeric_limits.py | dbd3d3f38b95d0d2794c5aa293ae1f9ce748999775f20335523a014c2f94656a |

## PR 提交前复核

用户于同日要求创建 PR。修复提交已无冲突 rebase 到 `origin/code`：
`d0a683c11a9b4c068c8d91fcf385fd7f040c17b9`（PR #188）。
更新基线后，将前文所有定向测试文件与非阻断节点的并集实际执行一次：
**519 passed、2 deselected，56.78s，退出0**。本次因基线变化而重验直接相关回归，未运行全仓测试。
13个源码/测试文件的已登记SHA256仍一致，Ruff与git diff检查通过。
GitHub HTTPS git传输持续连接超时，拟通过GitHub Git Data API发布同一提交树并创建PR；
PR中的R19仍明确未完成，不将其记为业务验收通过。不自动合并。
