# Report Editor 数据追溯 B9 验收、灰度与回滚记录

日期：2026-10-01

状态：宿主范围验收通过；本轮不纳入 Daytona/sandbox。真实生产部署滚动恢复和独立审核员签字仍属于发布现场记录，不影响宿主代码门禁结论。

## 1. 发布候选范围

本候选覆盖 F01～F12 的代码路径，包括 CSV 快照、facts、正文/表格/图表/复杂分析绑定、编辑生命周期、下钻、双格式来源附录、授权与保留，以及 B9 独立灰度开关。

灰度开关均默认开启，以保持升级兼容：

| 能力 | 环境变量 | 关闭后的行为 |
| --- | --- | --- |
| 新来源登记 | `AGENT_REPORT_LINEAGE_REGISTRATION_ENABLED` | 新报告不生成 trace index；报告与权威 manifest 仍正常发布 |
| Editor 来源面板 | `AGENT_REPORT_LINEAGE_PANEL_ENABLED` | 隐藏来源入口并停止草稿来源校验；历史证据文件不删除 |
| 原始/派生下载 | `AGENT_REPORT_LINEAGE_DOWNLOAD_ENABLED` | 拒绝新下载和派生导出；预览与面板可独立保留 |
| 单维度下钻 | `AGENT_REPORT_LINEAGE_DRILLDOWN_ENABLED` | 来源概览声明下钻不可用，直接调用返回稳定业务错误 |
| PDF/Word 来源展示 | `AGENT_REPORT_LINEAGE_EXPORT_SOURCES_ENABLED` | 服务端强制 `sources=false`，前端隐藏选项；冻结证据仍保留 |

开关由实例启动配置读取。若需按人群灰度，应使用独立部署实例或流量组，不在应用内临时引入用户分桶。

## 2. F01～F12 验收矩阵

| 功能 | 当前证据 | 状态 |
| --- | --- | --- |
| F01 CSV 文件级追溯 | revision index、manifest 身份互验、缺失/篡改测试 | 自动化通过 |
| F02 CSV 预览与下载 | 分页、列权限、游标签名、原始字节、派生任务和下载能力测试 | 自动化通过 |
| F03 基础/比较/派生/对账 facts | 确定性 bundle、FactRef 和一层展开测试 | 自动化通过 |
| F04 多步及补充分析 facts | computation record、依赖展开、循环拒绝和脚本证据测试 | 自动化通过；真实复杂报告待审核 |
| F05 正文与结论绑定 | claim subject、valid/stale/unbound、浏览器入口测试 | 自动化通过 |
| F06 结构化表格追溯 | table/cell identity、排序保持、改值/插入失效测试 | 自动化通过 |
| F07 静态图表追溯 | 图片、plot data、系列/转换及 CSV 关联测试 | 自动化通过；真实多系列图待审核 |
| F08 编辑状态与版本一致性 | 草稿、并发 CAS、历史恢复、N+1、重新分析和 lineage 继承测试 | 自动化通过 |
| F09 快照内单维度下钻 | sum/count/distinct/average/ratio/semi-additive、范围和对账测试 | 自动化通过 |
| F10 PDF/Word 来源展示 | 真实 WeasyPrint/python-docx 双格式渲染与 revision 一致性测试 | 自动化通过 |
| F11 授权、保留和恢复 | scope/capability、重启重新注册、共享引用、过期、失败清理测试 | 自动化通过；部署恢复待现场验证 |
| F12 上线与运维 | 五个独立开关、本文运行手册与回滚方案 | 宿主灰度证据已完成；业务审核签字待现场完成 |

“自动化通过”不替代 G9 的真实报告和审核员验收。F04、F07、F11、F12 的现场项完成前不得将本表解释为正式发布批准。

## 3. 2026-10-01 验证记录

### 3.1 灰度与相关回归

执行：

```text
uv run pytest -q smart_reporting/tests/test_settings.py \
  smart_reporting/reporting/tests/test_report_editor_trace.py \
  smart_reporting/reporting/tests/test_http_publication_lineage.py \
  smart_reporting/reporting/tests/test_report_editor_lineage_export.py
```

结果：137 passed，1 个第三方 `imghdr` 弃用告警。

另执行全部 lineage fixtures 与未重复的 `test_trace_*.py` 契约/算法矩阵：157 passed，覆盖独立答案、索引、预览、facts、claims、表格、图表、复杂计算、下钻、权限和错误预算。

前端执行三个受影响测试文件和生产构建：28 passed；TypeScript 检查及 Vite build 通过。构建仍报告既有 Plotly/Milkdown 大 chunk 告警，不是本批新增阻断。

真实 Chromium 灰度用例确认：关闭面板和导出来源展示后，来源按钮、来源校验状态和导出来源选项不可见，保存及普通 PDF 入口仍可用。首轮用例发现工具栏 CSS 覆盖 `hidden` 的缺陷，修复后复测 1 passed；正常来源面板及 CSV 预览浏览器用例同轮通过。

### 3.2 恢复、保留与兼容

执行 retention、history restore、revision inheritance 与 real export 测试文件：31 passed，1 deselected。被默认 `not integration` 选择器排除的真实双格式用例随后用 `-m integration` 单独执行：1 passed。

覆盖：

- 进程对象重建后通过持久 scope 重新注册 workspace；
- 历史正文与对应来源 revision 一起恢复；
- 共享 CSV 仍被其他 revision 引用时不删除；
- 来源过期、缺失、hash 不一致显示明确状态或拒绝证据读取；
- 渲染/提交前失败清理未发布 revision；提交后授权失败保留完整 revision；
- 无 trace index 的旧报告仍可编辑和导出；
- PDF 与 Word 使用同一冻结快照及来源状态。

### 3.3 B0 性能预算复测

本机合成 200 MiB CSV（209,715,164 bytes，5,825,420 行），每项 20 次：

| 项目 | B0 门槛 | 本次 p95 | 结果 |
| --- | ---: | ---: | --- |
| 预览首页 50 行 | ≤1,000 ms | 3.34 ms | 通过 |
| 单维度 sum 下钻 | ≤3,000 ms | 249.35 ms | 通过 |
| 2,000 文件索引解析（50 次） | ≤200 ms | 29.56 ms | 通过 |
| 500 条 fact 一层展开（50 次） | ≤300 ms | 1.39 ms | 通过 |

隔离进程单次测量（包含 Python/依赖导入基线）：预览峰值 RSS 约 355 MiB，下钻约 809 MiB。B0 未冻结内存失败阈值，故不据此判失败；下钻峰值必须作为灰度监控项，实例内大型下钻已有单并发限制，扩大流量前应在目标容器限额下复测 OOM 余量。

### 3.4 真实依赖探针

调用应用内建只读诊断（StarRocks 仅执行 `SELECT 1`）：StarRocks `rj` 通过（438 ms），metadata 通过（412 ms）。Daytona/sandbox 不属于本轮宿主范围，不作为宿主门禁条件。

### 3.5 宿主范围复测（2026-10-01）

在宿主机环境运行，绕过受限沙箱的 AnyIO worker 回调限制：

```text
176 passed：设置开关、来源 API、恢复、保留、历史恢复、来源附录与导出
85 passed，3 deselected：宿主工作区重启、渲染和兼容路径
1 passed，6 deselected：真实 PDF/Word 双格式导出集成
前端 262 passed；生产构建、构建预算检查通过
```

宿主最小工作区写入、进程重建和真实双格式导出均通过。受限沙箱中 `anyio.to_thread.run_sync` 的事件循环回调挂起不代表宿主运行结果。

### 3.6 宿主灰度阶段记录（2026-10-01）

按开关逐级扩大能力，使用可废弃宿主测试报告和合成来源索引：

| 阶段 | 开关配置 | 验证证据 | 结果 |
| --- | --- | --- | --- |
| 内部登记 | 仅开启 `REGISTRATION`，面板/下载/下钻/导出来源关闭 | 开关单测、索引保留断言 | 通过；报告主发布路径不依赖来源面板 |
| 内部审核 | 开启面板，下载/下钻/导出来源关闭 | 来源面板、主体定位、CSV 预览浏览器用例 | 通过；来源读取失败不阻断正文编辑 |
| 受控下载 | 开启下载，分享能力保持受限 | 原始/派生下载权限和跨报告隔离测试 | 通过；无越权读取 |
| 小流量下钻 | 开启下钻 | 下钻语义、资源上限、不可用维度和对账测试 | 通过；超限返回稳定错误 |
| 小流量导出 | 开启来源展示 | `test_report_editor_browser.py -m integration -k 'lineage_display or loads_table_and_trace or online_subject or repeated_export or history_restore'`：6 passed | 通过；来源按钮、在线主体、历史恢复和连续导出行为符合开关配置 |

本记录覆盖宿主代码和合成报告验收；真实流量比例、容器 RSS 和业务审核结论仍由部署现场填写。

### 3.7 独立审核矩阵（待业务审核员签字）

工程侧先提供固定样本、独立答案和操作路径，审核员只需按任务核对结果并填写结论：

| 审核任务 | 独立证据 | 工程复核 | 审核员结论 | 签字/日期 |
| --- | --- | --- | --- | --- |
| 事实核对 | R1/R2/R3 答案、正文 claim、fact detail、输入 CSV 预览 | 通过：fact/claim/preview 定向测试 | 待填写 | 待填写 |
| 图表核对 | 多系列作图数据、排序/单位转换、图表来源和输入 CSV | 通过：chart trace/plot data 定向测试 | 待填写 | 待填写 |
| 复杂分析核对 | computation record、输入 facts、中间结果、限制说明 | 通过：computation chain/contract 定向测试 | 待填写 | 待填写 |
| CSV 核对 | 原始快照、派生下载、列权限、来源身份和完整性状态 | 通过：preview/download/integrity 定向测试 | 待填写 | 待填写 |

审核通过条件：四类任务均能从正文或图表入口回到正确 revision 的证据，独立答案一致；发现 stale、missing 或权限拒绝时，审核员能解释其状态而不把告警当作数值通过。

工程独立复核（2026-10-01）执行：

```text
.venv/bin/pytest -q \
  smart_reporting/reporting/tests/test_trace_fact_service.py \
  smart_reporting/reporting/tests/test_trace_chart_subjects.py \
  smart_reporting/reporting/tests/test_trace_chart_transform.py \
  smart_reporting/reporting/tests/test_trace_computation_service.py \
  smart_reporting/reporting/tests/test_trace_dataset_service.py \
  smart_reporting/reporting/tests/test_lineage_fixtures.py
```

结果：`61 passed`。这些用例使用 B0 固定样本和独立标准答案，未通过当前报告生成器反向产生预期值；工程复核结论为四类任务通过。业务审核员仍需在上表填写实际使用结论和签字。

## 4. 灰度顺序与成功条件

1. 内部流量组：开启登记，关闭面板、下载、下钻和导出展示。确认报告生成成功、manifest 可读、trace index 数量与报告 revision 对应。
2. 内部审核员：开启面板，保持下载/下钻关闭。完成正文、表格、图表和复杂分析来源核对；观察 `snapshot_integrity_failed`、`source_missing` 和错误有效绑定。
3. 受控数据人员：开启下载；核对分享会话无越权、原始与派生文件身份/名称明确。
4. 小流量：开启下钻；监控 p95、RSS、超时、capacity limiter 等待与对账失败。
5. 小流量导出：开启来源展示；抽检 PDF/Word 编号、附录、在线对象与 revision 一致。
6. 全量：至少一个完整保留周期内无阻断缺陷，再扩大到全部流量。

每阶段成功条件：主报告生成/保存/导出错误率无显著回归；无越权和跨 revision 错配；完整性错误均能定位到 reportId/revision/requestId；内存不触发容器 OOM；审核任务结论与独立答案一致。

## 5. 运行与诊断手册

### 5.1 先确认对象边界

按用户反馈取得 reportId、revision、requestId 和发生操作，不收集编辑会话 token、下载 grant 或 CSV 原始行。确认问题是主报告不可用，还是仅来源证据不可用；后者不得通过重新查询源库伪造历史证据。

### 5.2 稳定错误码

| 错误码 | 检查方向 | 处理 |
| --- | --- | --- |
| `source_missing` | 旧报告无索引、对象不在当前 revision、功能关闭 | 验证 manifest；旧报告按已知限制处理 |
| `snapshot_expired` | revision/共享来源已过保留期 | 保留元数据与不可用原因，不实时补查 |
| `snapshot_integrity_failed` | 文件缺失、size/hash 或登记关系不一致 | 停止证据读取，保留编辑功能，检查持久卷/恢复流程 |
| `dataset_access_denied` | 分享会话或能力不足 | 核对 capability，不提升分享链接权限 |
| `cursor_invalid` | 游标过期、跨报告/revision/列集重放 | 客户端从第一页重取 |
| `drilldown_unavailable` | 功能关闭、维度未登记或输入粒度不足 | 显示能力限制，不接受任意字段替代 |
| `resource_limit_exceeded` | 页、列、响应或依赖展开超过预算 | 缩小合法请求；不得静默截断并声称完整 |

应用日志使用 loguru。诊断时按 requestId/reportId/revision 查询开始、成功、失败及 elapsed_ms；日志不得输出 token、完整 SQL 或 CSV 原始行。

### 5.3 恢复检查

- 确认持久工作区根目录仍存在；重新注册必须使用 context 中冻结 scope，不能按当前用户输入拼接路径。
- 校验权威 manifest 自身 size/hash，再校验 trace index 与其中被请求文件的身份。
- 导出失败先判断提交点：提交前可清理本次暂存目录；context 已提交后不得删除新 revision，应重试授权/持久化尾部步骤。
- 清理 revision 前扫描其他有效 manifest 引用；共享文件仍被引用时保留。

## 6. 回滚方案

按影响从小到大操作：

1. 关闭 `AGENT_REPORT_LINEAGE_EXPORT_SOURCES_ENABLED`，停止新导出展示来源；不删除历史附件。
2. 关闭 `AGENT_REPORT_LINEAGE_DRILLDOWN_ENABLED` 和 `AGENT_REPORT_LINEAGE_DOWNLOAD_ENABLED`，保留只读面板。
3. 关闭 `AGENT_REPORT_LINEAGE_PANEL_ENABLED`，隐藏全部 Editor 来源交互并停止草稿校验；主编辑、保存与普通导出继续工作。
4. 仅当 trace 生成本身影响主发布时，关闭 `AGENT_REPORT_LINEAGE_REGISTRATION_ENABLED`。新报告不登记来源，既有 report/revision/manifest 与证据文件保持不变。
5. 若需回退应用版本，先保留持久工作区和数据库状态。旧版本应忽略 manifest 的可选 traceIndex 字段；不得用清理脚本删除新版本已登记文件。

回滚后验证：打开一个旧报告、一个已有 trace 的报告和一个新生成无 trace 的报告；分别执行读取、保存和不含来源的 PDF/Word 导出。确认历史报告不被错误套用最新来源。

## 7. 已知限制与 G9 未完成项

- 旧报告没有可信 trace index 时只显示“无可用来源”，不反推 facts、行映射或公式。
- CSV 是生成时登记快照，可能已聚合，不承诺业务库逐笔明细。
- 下钻只接受索引登记的指标和维度，不开放任意 SQL。
- 当前 200 MiB 下钻隔离进程峰值 RSS 约 809 MiB，目标部署必须按容器限额复测。
- 尚缺：独立审核员完成事实/图表/复杂分析/CSV 四类任务的签字。生产部署重启、目标环境性能和真实流量比例按本轮约定不作为当前宿主判定条件。

以上未完成项全部关闭前，B9 与 G9 保持未通过。
