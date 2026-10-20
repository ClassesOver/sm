# 派生正文引用与表格来源重算契约

日期：2026-10-20。分支 `feat/derive-and-anchor`，交付至 PR #80。

## 数值支持与引用签发

数值有业务证据支持，可以留在正文；只有全部语义候选都指向同一个可信来源 token 时，才能新增精确引用。来源缺失、重复资源身份或多个候选产生歧义时，保留已支持的数值，但不签发唯一引用。已有受信引用不重复插入锚点。末位、符号和显示精度修正后，以最终正文重新冻结 statement fingerprint。

事实对使用 `{{derived:factA:factB:kind:digest:unit}}`，摘要保留操作数事实身份顺序，并兼容旧版排序 ID 的 token。普通 `{{value:}}` 解析不构建派生目录；新旧目录共享一次枚举，枚举失败丢弃部分结果并缓存空目录。同 token 的解析视图不同则拒绝解析。

## 表内派生的原始单元格身份

本阶段已实现表内派生协议，取代此前“仅放行、不签发”的边界。`TableOperandV1` 绑定：

- 已登记的 `fileResourceId`。
- 指向原始 JSON 表的 RFC6901 `tablePointer`。
- 原始 `rows` 与 `columns` 数组中的 `rowIndex`、`columnIndex`。
- 显式包含单位换算的十进制 `coefficient`。

`TableDerivationV1` 保存操作数与输出单位。`{{tableDerived:<SHA-256>}}` 摘要同时绑定规范化派生 metadata 和来源原始字节 SHA-256，不伪造 analysisId 或 factId。

`trace/table_sources.py` 是生成端和编辑器共同使用的验证、重算实现。只接受调用方已核验身份的原始 bytes；拒绝重复 JSON member、重复单元格、非法坐标、布尔/非有限数值、不完整表行、重复列名、非法单位及不符合换算比例的系数。单次派生限同一文件的同一张表，最多 100 个操作数。

支持形状：

1. 两行同列或同行两列差额。
2. 同列 TopN 合计；排除总计类行，排序后仍使用原始行坐标。
3. 两列所有行总额之差；正负两侧都必须覆盖原始表全部 rows。
4. 百分比差额输出“个百分点”，金额、人次、床日按受支持单位族换算。

periods、period roles 与 scope 仅来自核验过的来源表和文档；结构化期间优先，缺失或歧义期间保留空，不从正文推断年份。

## 生成、索引与编辑器闭环

生成端先验证未投影证据的冻结 path、size 与 SHA-256，再将可信来源传给数值渲染；finding 的投影内容不能替代原始字节或原始坐标。相同原始 bytes 对应多个资源身份时，不签发唯一表引用。

`numberReference → subject → index` 保留 `tableDerivation`。索引只从单独提供的 `table_source_files` 登记操作数实际使用的来源。普通 index files、plot-data 关联或宽泛 review evidence 不自动授权为表派生来源。来源登记失败只降级受影响绑定：无其他事实来源的 table-only subject 被移除，有合法 FactRef 的绑定清除不可用表派生。

编辑器按操作数明确指定的资源读取实际文件，核对 size 和 SHA-256，再用共享 resolver 定位原始单元格、验证 token 并重算。文件身份篡改仍报 `snapshot_integrity_failed`，不伪装成普通数值不匹配；无法解析的派生软降级为 unbound。有效引用提供 `restoreText`，修改正文后可恢复并重新验证。

导出调用方 `report_editor/service.py` 在上层捕获来源读取、validate 和追溯重建异常，记录具体 lineage issue、丢弃不可用追溯数据并继续渲染。报告验收或发布门禁失败不能阻断已生成且实际身份可读取的 PDF/Word 下载链接签发。

## 统计口径

`quality_scan.py` 明确区分数值放行、目录条目和实际正文引用：

- `derivedShare` 是派生放行占 registered 的比例，不代表无锚点比例。
- `missingDelta` 比较回放剩余缺失与归档告警，二者总体不同，不能解释为净修复数。
- form/scale mismatch 是启发式相似候选，不是已证实根因。
- 当前归档正文已被替换为“待核实”的原值无法从正文恢复，不能纳入实际新增引用数。

真实附件回放另行记录实际正文新增引用数、tableDerived 数、编辑器重算及 restore 成功数，不能用 catalog 大小或 checking event 代替。

## 真实附件回放结果（2026-10-20）

输入附件 175 个成员逐字节核验一致（12 事实文件、18 图表输入、11 补充证据；图表输入实际为 18 个而非 17 个，chart-013 含 4 次尝试，不删减凑数），104 个正文段落在隔离副本中重渲染。

全链路（render → subject → index → manifest → editor validate/篡改/恢复）：

- 清除历史锚点后新签正文引用 3 处，全部为 tableDerived；构建 number subject 3、登记进索引 3。
- 3/3 从登记原始字节重算成功；编辑器基线 valid 3；篡改显示值后 3/3 转 stale；restoreText 3/3 可用；按其恢复后 3/3 转 valid，且全文与回放基线逐字节一致。
- 全程未改动解压目录原始文件；补充证据从不进入 factFiles，无伪造 claim 或计算记录。

renderer 反事实对照（同 104 段、同核验 contents，仅 `table_sources=None`，只读模式）：

- baselineReferences 0 → finalReferences 3，真正新增 tableDerived 3（section_001 两条、section_004 一条）；factPair/普通事实重签、保留、丢失均为 0。
- 当前代码重跑与首次全链路签发逐字段复现（claimId/token/displayText/offset 一致）。
- 两轮核验结论完全相同（registered:direct 389、decline 8、derived 9、profile_rate 7；missing/corrected/percent_point 均为 0）：表来源映射只新增锚点签发，不改变核验与替换行为。

剩余无引用数值的具体原因：46 处 source_review 为归档前已替换“待核实”、原始显示不可恢复；413 处核验通过但已发布正文是纯文本、没有 `{{value:…}}` 占位，普通事实引用只能在草稿期签发、不能对纯文本追溯补签，当前仅唯一可铸 token 的 tableDerived 满足补锚条件；9 处 derived 支持的核验无一具备可铸 `{{derived:…}}` 的唯一双事实身份。无隐性丢失。补充锚点裁决追踪：22 处出现派生候选的数字中 3 处候选唯一并锚定，其余 19 处均为多候选歧义（每处 2–12 个候选、token 各不相同，典型为补证表与图表输入表同值各推一遍）。本 PR 随后实现内容寻址投影折叠与显示门禁，最终态第一份附件净新增 tableDerived 11 条（基线 0），两轮通知与核验结论逐项相同；残余歧义需来源角色策略，属信任策略决策，另行立项。

锚点签发的两道安全边界（折叠后新增）：其一，图表输入的 `source.sha256` 声明只有经内容寻址核验且声明目标在候选集中才折叠投影视图，声明不可核验不折叠；其二，锚点签发前用与 `bound_number_display` 同口径（含方向词）的显示规则门禁核对重算值，核不上不签锚点、数值照常保留——语义放行不等于可锚定。

回放脚本 `scripts/replay_table_derivation_references.py`（含 `--baseline-from` 只读对照模式）；脱敏聚合报告见 `docs/superpowers/plans/2026-10-20-table-derivation-replay.md`；含正文与身份的全量结果仅保留在本地 `/tmp`。

第二份真实附件（另一 report-run，全部产物位于 revision-2/ 下、无补证树）复验：129 段重渲染，净新增 tableDerived 2 条（唯一派生候选全部锚定、无歧义），编辑器重算/篡改/恢复 2/2 全通过且逐字节还原；registered 336、missing 67。missing 的根因已定位并修复：`sections.py` 只在 evidence 项有有效 computation_record 时才登记补证文件身份，真实运行 computations=0 导致补证全部不进索引，修订产物包（只收登记身份）随之整棵丢掉 evidence 树。现在补证文件身份无条件进索引，计算记录无效或循环时仅丢弃计算层；图表输入 source 0/20 可核验同样源于该缺口，如实记录。回放脚本已泛化支持两种归档布局，第一份归档的发现计数回归校验不变。

## 验证记录

已完成的定向验证（批次间可能重叠，不将批次数相加作为 unique 总数）：

- 共享表来源与新旧 resolver 缓存：36 passed。
- schema、index、editor 的表派生/表来源定向：39 passed，234 deselected。
- 表派生签发和 numeric 定向：28 passed，230 deselected。
- generation、index 与 HTTP publication lineage：32 passed。
- 其他发布非阻断契约：20 passed；与上一批共同覆盖 AGENTS.md 的八项契约。
- 前一阶段 numeric、quality scan、source validation 分别为 245、22、8 passed；后续仅做受影响定向检查，不重复完整套件。
- 本次改动 Python 文件 Ruff 与 `git diff --check` 通过。

两轮只读审查未发现已确认的具体缺陷；审查不替代测试或真实回放。
