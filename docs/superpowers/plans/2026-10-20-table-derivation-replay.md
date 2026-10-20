# 2026-10-20 真实附件 table 派生正文引用回放（脱敏聚合）

本报告只含聚合计数、原因分布、复现命令与产物路径；不含附件正文、数值原文、token、resourceId 或归档成员路径。含正文/身份的全量结果保留在本地 `/tmp`，不入库。

## 1. 输入与不变量

- 输入附件：`/home/junge/下载/report-revision-2-artifacts.zip`；解 extract 目录 `/tmp/replay-77`。
- ZIP 内 175 个文件成员与解压文件逐字节核验一致；回放结束后再次核验全部未改动。
- 实际来源清单：12 个事实文件、18 个图表输入文件、11 个补充证据文件。任务口径中的 17 个图表输入与真实归档不符（chart-013 有 4 次尝试共 6 个输入属于 section_005），不删减凑数。
- 旧 trace-index 中 18 个图表输入的登记路径在解压目录中不以原路径存在，但其字节（size+SHA-256）均能在归档其他成员中找到并核验；本回放按字节身份重新登记，不伪造旧路径存在。
- 原始 Markdown 64,407 字节、597 行、108 个历史 claim 标记；revision-2 归档副本与 revision-1 逐字节一致。
- 5 个 CSV 数据集保留原 datasetId、行数、SQL hash、period roles、query window 等原始 lineage 字段；`sourceId` 使用回放本地路由值（旧索引无 sourceId 字段）。
- 事实授权零伪造：补充证据文件从不进入 factFiles；无结构化 claim 注入。

## 2. 首次全链路回放（render → subject → index → editor validate/restore）

| 步骤 | 结果 |
| --- | --- |
| 参与渲染的正文段落 | 104（排除：仅协议段 28、图片段 15、图表题注 15） |
| 清除历史锚点后新签正文数值引用 | 3（全部 tableDerived；此为全部重签数，非相对增量，增量见第 3 节） |
| 构建的 number subject | 3；登记进 trace index 的 numberReference subject 3 |
| 从登记原始字节重算 tableDerived 值 | 3/3 成功 |
| 编辑器基线校验 | valid 3 / stale 0 / unbound 0 |
| 篡改显示值后校验 | 3/3 转 stale |
| restoreText 可用 | 3/3 |
| 按 restoreText 恢复后校验 | 3/3 转 valid，且 3/3 恢复后全文与回放基线逐字节一致 |
| 复核告警 | 46（全部 source_review） |
| catalog/check 事件冒充正文引用 | 0（表格单元格 subject 与正文引用分开统计，未计入） |

## 3. renderer 反事实对照（table_sources=None，只读模式）

同一 104 个原始段落文本、同一核验过的来源 contents（顺序与字节对首次结果复验一致），仅 `table_sources` 取 `None` 与取已核验映射各跑一次 renderer；不重复 subject/index/editor 链路。对齐键为 `(section, 原始段落行号, 段内数字出现序号, 显示文本)`；claimId 在两次独立渲染间不可比，不用于对齐。

| 计数 | 值 |
| --- | --- |
| baselineReferences（无表来源） | 0 |
| finalReferences（已核验表来源） | 3 |
| newlyEnabledTableDerived（真正新增） | 3 |
| factPairReissued | 0 |
| factReferenceReissued | 0 |
| retained（两运行均签发） | 0 |
| lost（仅 baseline 有、新版丢失） | 0 |
| 新增引用分布 | section_001 ×2（1 个百分比、1 个元金额），section_004 ×1（亿元金额） |
| 新版与首次全链路签发一致性 | 逐字段复现（claimId/token/displayText/offset 完全一致） |

两轮运行的核验结论完全相同：`registered:direct` 389、`registered:decline` 8、`registered:derived` 9、`registered:profile_rate` 7（合计 413 个带单位数字出现核验通过）；`missing`、`corrected`、`percent_point` 均为 0；`numeric_unverified` 告警两轮均为 0，`source_review` 两轮均为 46。即表来源映射的引入只新增锚点签发，不改变任何核验结论或正文替换行为。

## 4. 剩余无引用数值的原因分布

1. **source_review 46 处**：原始正文在归档前已将数值替换为“待核实”，原始显示无法从该文本恢复。回放保持复核告警，不借无关事实恢复数值。
2. **核验通过但未补签锚点 413 处**（direct 389 / decline 8 / derived 9 / profile_rate 7）：数值可由冻结事实或派生目录核验，但已发布正文是纯文本、没有 `{{value:…}}` 协议占位。普通事实引用只能在草稿生成期由占位符签发，不能对纯文本追溯补签；渲染器仅为“唯一可铸 token 的派生值”补发锚点，当前仅 tableDerived 满足该条件（3 处）。
3. **fact-pair 派生 0 处**：9 处 derived 支持的核验中没有一处具备可铸 `{{derived:…}}` token 的唯一双事实身份，故 factPairReissued=0。
4. **锚点裁决追踪（补充诊断）**：对全部出现派生候选的数字做 match 层追踪——22 处有候选，3 处候选唯一并锚定，其余 19 处均为多候选歧义（每处 2–12 个候选，各自产生互不相同的有效 token；典型是补证表与图表输入表对同一数值各能推出一遍）。零处属于来源未授权、共享校验拒绝或无身份候选。本 PR 随后实现了内容寻址的投影折叠：图表输入自带的 `source.sha256` 经字节核验指向某个补证、且该补证也在候选集中时，折叠投影视图、保留声明的原始来源（声明不可核验或原始来源不在候选集时不折叠）。折叠后新增锚点前还有一道与发布显示规则同口径（含方向词）的门禁：重算值核不上正文显示就不签锚点、数值照常保留，守住"语义支持保留数值"的边界——该门禁同时修复了折叠初版会把已注册数值事后降级为"待核实"的回归。最终态：**净新增 tableDerived 11 条**（对照基线 0，section_001/section_004 集中），11/11 全链路闭环且逐字节还原；两轮通知（46/46）与核验结论（direct 389 / decline 8 / derived 9 / profile_rate 7，missing 0）逐项相同，折叠只新增锚点、不改变核验与替换行为。剩余未折叠的歧义需更进一步的来源角色策略（信任策略决策，另行立项）。
5. **无隐性丢失**：`missing`/`numeric_unverified` 为 0，两轮对照无任何数值因缺少表来源被降级为待核实。

## 5. 方法学与可信性检查

- baseline 只读模式复用首次 results.json 的段落清单，并按首次清单的 size/SHA-256 逐项复验归档字节后才重建 contents。
- 当前代码重跑结果与首次全链路签发的引用逐字段一致，证明对照与首次运行同构。
- 核验结论观测使用 `replace_unregistered_numbers` 既有 `on_verdict` 观测钩子（契约保证只统计、不改变替换行为）；不改任何应用源码。

## 6. 复现命令

```bash
# 首次全链路（render → subject → index → manifest → editor validate/篡改/恢复）
/home/junge/pros/smart_reporting/.venv/bin/python \
  /home/junge/pros/smart_reporting/scripts/replay_table_derivation_references.py \
  --output /tmp/table-derivation-replay-A

# 只读 renderer 反事实对照（不重复编辑器链路）
/home/junge/pros/smart_reporting/.venv/bin/python \
  /home/junge/pros/smart_reporting/scripts/replay_table_derivation_references.py \
  --baseline-from /tmp/table-derivation-replay-A/results.json \
  --output /tmp/table-derivation-replay-B
```

## 7. 产物路径

- 脚本：`/home/junge/pros/smart_reporting/scripts/replay_table_derivation_references.py`（本回放新增的唯一项目脚本；`ruff check` 通过）。
- 本地全量结果（含附件派生正文与来源身份，仅本地）：`/tmp/table-derivation-replay-20261020-a/results.json`（全链路）与 `/tmp/table-derivation-replay-20261020-baseline/results.json`（对照）。
- 本报告：脱敏聚合，可入库。

## 8. 限制

- 归档实际为 18 个图表输入（15 个图表，chart-013 含 4 次尝试），与任务口径 17 不符，如实按 18 处理。
- 纯文本回放结构性无法补签普通事实引用（见第 4 节第 2 条），该限制来自协议设计，非本次缺陷。
- “待核实”处的原始数值不可恢复，保持复核告警。
- 章节适配器承载真实渲染 block，不含完整 LLM 工作流与 PDF/Word 发布链路；编辑器恢复经验证/restoreText 与内存内显示替换完成，未走浏览器 UI 或 HTTP 导出。
- 未修改任何应用源码；未运行完整测试；未 commit/push。

## 9. 第二份真实附件（另一 report-run，revision-2 集中布局）

回放脚本已泛化支持第二种归档布局（全部修订产物位于 `revision-2/` 下、数据集在 `revision-2/trace-resources/`、无根 manifest/索引）；facts 优先取 manifest 同层目录，图表输入按 `.chart-input.json` 识别，supplement 允许为 0。对第一份归档的发现计数回归校验不变（12/11/18）。

脱敏聚合结果：

| 项 | 值 |
| --- | --- |
| 归档成员 / 事实 / 图表输入 / 补证 | 71 / 15 / 20（17 图，3 图各 2 次尝试）/ 0 |
| 图表输入 source 可核验 | 0/20（`evidence/` 树未随归档携带，如实记录为不可核验，不伪造） |
| 参与渲染正文段落 | 129（排除：协议段 31、图片段 17、图表题注 17） |
| 核验结论 | registered 336（direct 323 / decline 5 / profile_rate 6 / derived 2）；missing 67 |
| 反事实对照 | baseline 0 → final 1，净新增 tableDerived 1；retained/lost/重签均为 0；与首次全链路逐字段复现。投影折叠在该附件不生效：无补证文件可作折叠目标（source 声明 0/20 可核验），此前 2 条中的 1 条本就依赖不可核验声明，最终态如实降为 1 条唯一派生 |
| 编辑器闭环 | 重算 1/1、基线 valid 1、篡改 stale 1、restoreText 1、恢复 valid 1、逐字节还原 1 |
| 锚点裁决追踪 | 仅 2 处出现派生候选且全部唯一锚定，无歧义、无未授权来源 |
| 复核告警 | source_review 40 + numeric_unverified 67（两轮一致） |

第二份附件剩余缺口的主因与第一份不同：**归档未携带 evidence/supplement 树**，67 处带单位数值在 facts+图表输入目录下无法核验（第一份归档携带 11 个补证文件时 missing 为 0）。根因已在现行代码中定位并随本 PR 修复：`workflow/runtime/sections.py` 原先只在 evidence 项携带有效 computation_record 时才把 `evidence_files` 登记进 trace index（真实运行 computations=0，补证全部被跳过），修订产物包只收 manifest/index/job 登记过的身份，编辑器导出的修订因此整棵丢失 evidence 树。修复后补证文件身份无条件登记进索引（计算记录无效或循环时只丢弃计算层、保留补证身份；不伪造计算记录），后续修订包将携带补证，编辑器与离线回放即可核验这些数值。两轮对照核验结论逐项相同，表来源只新增锚点、不改变核验与替换行为。

复现命令（第二种布局需显式传 `--archive` 与 `--extracted`）：

```bash
/home/junge/pros/smart_reporting/.venv/bin/python \
  /home/junge/pros/smart_reporting/scripts/replay_table_derivation_references.py \
  --archive '/path/to/report-revision-2-artifacts-2.zip' --extracted /tmp/replay-78 \
  --output /tmp/table-derivation-replay2-A
/home/junge/pros/smart_reporting/.venv/bin/python \
  /home/junge/pros/smart_reporting/scripts/replay_table_derivation_references.py \
  --archive '/path/to/report-revision-2-artifacts-2.zip' --extracted /tmp/replay-78 \
  --baseline-from /tmp/table-derivation-replay2-A/results.json \
  --output /tmp/table-derivation-replay2-B
```

本地全量结果：`/tmp/table-derivation-replay2-20261020-a`（全链路）、`/tmp/table-derivation-replay2-20261020-baseline`（对照）；均不入库。
