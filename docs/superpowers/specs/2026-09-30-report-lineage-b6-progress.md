# Report Editor 数据追溯 B6 进度记录（第一增量）

日期：2026-09-30。状态：B6 草稿来源校验、权威 manifest 传递、HTTP 初始发布、N+1 索引继承、历史来源摘要、面板竞态修复与真实渲染冒烟已实现；完整渲染视觉验收、浏览器集成和表格编辑重判仍待验收。

上游：计划 B6、b1~b5 进度记录。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| `[[claim:id]]` 协议标记 | 装配器注入（`_marker_lines` 第三参数，与 citation/analysis 同模式：服务端生成、模型提交被 `_RESERVED_BODY_MARKERS` 继续拒绝）；PDF/Word 渲染剥离（pdf.py 两处 strip 链）；前端 protocol.ts marker kind 扩展 `claim`（编辑器内只读保护、保存前还原转义全部沿用） | 渲染回归（test_report_runtime 等）+ 前端 237 全过 |
| SubjectBindingV1 生成 | `trace/subject_builder.py`：finalize 从 SectionArtifact.claims 构造（subjectId=内容寻址、locator=section、subjectSha256=生成时 claim 值指纹、factRefs 由 factId→(analysisId, 指针) 目录解析）；factId 目录由 `_build_server_tables` 读 bundle 时一并产出（不重复读文件）；未知 factId 的 claim 软跳过不伪造绑定 | `test_trace_subject_validate.py` 4 例（映射、未知跳过） |
| validate API | `POST /api/sources/validate`（写操作：Origin+CSRF）：输入 {markdown(≤10MiB), draftSha256}；服务端复核草稿 SHA-256、索引报告/revision/工作流/正文资源身份及事实文件 size/sha256 后，对 subjectBindings 按 `[[claim:id]]` 附近 ±200 字符的事实值文本判定 **valid / stale / unbound**；事实文件身份失败返回 `snapshot_integrity_failed`，不产生有效结论 | `test_trace_subject_validate.py` 6 例（含草稿摘要、事实文件篡改及索引身份）与 `test_report_editor_trace.py` 21 例通过 |
| 草稿联动 | 初次载入及 Markdown 更新时防抖校验，编辑后立即显示“来源校验中”；请求可取消，响应必须与当前草稿文本及 SHA-256 同时匹配，待复核/未知/有效状态在编辑器元信息栏提示 | `source-validation.test.ts` 3 例（真实 SHA-256、乱序响应、取消/摘要不符），`trace-panel.test.ts` 9 例；前端构建通过 |

语义边界（按 AGENTS.md 与计划 6.1）：stale 是**软语义**——提示"当前内容待复核"，不拒绝保存；标记被删 → unbound（正文不再受证据约束）；比对是宽松文本匹配（展示值四舍五入/千分位均命中）。

本增量验证（2026-09-30）：后端定向 `test_trace_subject_validate.py` 6 passed、`test_report_editor_trace.py` 与前者合并运行共 25 passed（新增用例后分别运行）；前端 `source-validation.test.ts` 3 passed、`trace-panel.test.ts` 9 passed；`npm run build` 通过。此前 415/237 的运行不覆盖本增量，未重跑全量测试。

## 权威继承增量验证

后端四个定向文件合并运行：67 passed（editor 38、sources/subject 27、revision inheritance 2）；新增继承用例验证目标 revision 与 fact resource 重绑定、subject 原指纹保持、改值后仍 stale、旧版来源隔离、同内容 sidecar 重放、索引篡改和未登记 sidecar 降级。Ruff F821/F823/F401 与 git diff --check 通过。未执行真实 PDF/Word 发布或浏览器集成，不将这些门禁记为完成。

## 服务集成验收增量

恢复暂停任务后，`test_http_publication_lineage.py` 7 项通过：真实 Host workspace、ASGI HTTP 路由、授权兑换、CSV 预览/原字节下载、产物持久化、修订号偏移、发布重放；六类已登记哈希但归属错误的 index 在复制前拒绝。`test_report_editor_lineage_export.py` 5 项通过：真实 workspace 与 durable reducer，覆盖带静态图/作图数据的 N+1 重绑定、fact/CSV 访问、改值 stale、历史来源、提交前回滚和提交后 grant 失败保留文件。测试发现并修复 `_copy_revision_assets` 未返回 path map 的真实缺陷。

claim 校验收紧为唯一标记所在段落的有界数字匹配，拒绝重复标记、数字子串、相反符号、相邻其他段落与协议 ID 里的数字误命中；仍是软语义提示，单位/期间校验未完成。manifest/index 互验正文 size/sha256，新增负向回归。

本轮合并定向后端 81 passed；发布持久化与导出另行定向 29 passed、3 deselected（不代表被排除场景通过）；前端 12 passed，生产构建通过，存在既有大 chunk 警告。HTTP 发布测试 PDF/Word 使用固定测试字节，N+1 renderer 使用替身，不能记为真实 PDF/Word 渲染或视觉验收。未重跑完整套件。

## 前端竞态、安全渲染与真实渲染冒烟增量

来源面板修复了一类真实缺陷：关闭回调此前是空操作，按钮/遮罩/Esc 均无法关闭面板。现在统一 `closePanel`（作废在途请求、清空内容、隐藏弹窗），所有列表/详情/预览/下载请求按"捕获 signal → 成功与失败双路守卫 `isCurrentRequest`"执行，忽略 AbortSignal 的自定义 fetcher 迟到成功/错误不再覆盖当前页签或已关闭面板，也不会触发下载跳转。图表转换说明与计算记录字段（method/executionId/环境/限制）改为 textContent DOM 构建，不再 innerHTML 插值服务端可控文本。面板测试 12 项（含关闭丢弃、Escape 关闭、恶意标记不执行）。

草稿来源校验失败路径同样绑定当前正文：错误响应在正文已变且未再次调度时不写入"暂无法校验"；source-validation 5 项通过。

新增 [test_report_runtime_full_render.py](../../../../../smart_reporting/reporting/tests/test_report_runtime_full_render.py)：无 mock 的真实渲染冒烟（WeasyPrint 69 + pypdf + pandoc，LibreOffice 兜底可用），合成 CSV+规范章节锚点、关闭封面/目录，断言 rendered、页数、PDF/DOCX 磁盘字节与返回身份哈希独立复算一致、临时目录清理；缺 pandoc/soffice/WeasyPrint 时 skipif。本机运行 1 passed（14.64s），PATH 剥离下验证 skip 生效。该测试不含图表/封面/目录场景，未执行视觉验收，不替代完整渲染门禁。

前端定向 17 passed，`npm run build` 通过（既有大 chunk 警告）。

## 表格身份重判与完整渲染场景增量

**表格重判（计划 6.1 表格规则，服务端）**：`sources/validate` 现同时评估 `index.tables`——行标签→rowKey 映射取自当前 revision 已提交正文的表格块（与 TableTraceV1 同源生成），列按草稿表头文本 == columnKey 定位，单元格文本用与 claim 相同的带边界数值匹配（新增共用 `value_matches`）。判定：行排序 → 绑定保持 valid；改值 → 该格 stale；插入/改名行 → insertedRows 计数且原格不受影响；删行/删表块/表头被改 → 对应格 unbound 或 stale。响应新增 `tables`（逐表 cells 计数）与 `tableSummary`；仍为软语义，不阻断保存。事实值查找重构为共用 `_fact_value_of`（身份校验语义不变）。测试：`test_trace_subject_validate.py` 新增 4 例（排序保持、改值、插/改名/删行/删块、表头改判 stale），与继承/来源回归合并 35 passed。

**完整渲染场景**：`test_report_runtime_full_render.py` 新增第二例（2 例共 28.96s 通过）：真实 4x4 PNG 经 render manifest 图片绑定（相对路径解析失败时按 manifest 定位）、封面+目录启用、`[[claim:]]`/`[[section:]]` 从真实 PDF 提取文本中断言剥离、DOCX `embeddedImageCount == 1`、产物哈希独立复算一致、临时目录清理。仍无人工视觉审查，不记为视觉验收。

**前端状态接入**：`TraceValidation` 类型与元信息栏标签纳入表格汇总——待复核计数 = claim stale/unbound + 表格 stale/unbound/新插行；仅有表格绑定时不再误显示"无精确来源绑定"。前端定向 17 passed，构建通过。

## Claim 单位与期间软告警增量

`subject_builder.claim_status` 在事实数值命中后返回 `warnings`：匹配数值后紧邻的单位与事实登记 `unit` 不一致，或同句中出现不在事实登记 `periodValues` 集合内的绝对期间，给出软告警。`元/万元/亿元` 精确区分；`2025-09`、`2025/09`、`2025年9月` 规范化比较；其他指标数值后的单位与其他句子的日期不参与本 claim 核对。缺少生成时信息、正文未重述单位/期间、仅写“本月/环比”时不推断。数值绑定状态保持 `valid`，软告警单独返回，不阻断保存；前端把带告警的 valid claim 按一处计入“来源待复核”。

能力边界：期望信息来自被冻结事实记录，不从草稿反推。事实跨多个期间时仅验证是否属于该集合，不能替代原 claim 唯一期间、业务范围或单位换算的完整验证。本实现仍是语义提示，不是数值核对证明。

定向验证：subject/继承/N+1 导出 33 passed（含同句正确日期不掩盖错误日期、紧邻其他指标单位、格式化数值单位）；前端 source-validation 6 passed，生产构建通过（既有大 chunk 警告）；Ruff F821/F823/F401 与 git diff --check 通过。未重复完整测试。

## 历史恢复的持久化来源增量

新增同源/CSRF 保护的 `POST /api/history/{historyRevision}/restore`，提交当前 `expectedSha256`。服务端仅从同报告/工作流/作用域的已登记历史 context 定位冻结正文（不读历史草稿），先复核 manifest/index，再保存恢复正文与 hash-bound draft origin sidecar；GET/PUT document 返回 `sourceRevision`。来源列表/事实/图表/计算/校验、资产与后续保存读取选中的来源 context。恢复后导出仍按当前编辑器版号生成 N+1，继承选中历史 manifest/index/资源而不套用当前事实。

前端已发布历史恢复改用异步服务端接口：先完成当前保存，恢复成功后重置正文/CAS 基线、关闭旧来源面板并重校验；失败保留历史面板显示错误，禁用重复恢复。会话文本快照仍是本地正文恢复，不猜测其历史来源。

恢复与 editor/trace/export 合并定向 68 passed，新增“当前 2 版恢复 1 版证据后导出 3 版”1 passed；前端 history/api 40 passed（异步等待/失败/选中 revision/当前 CSRF+CAS 契约），此前 history/api/source-validation 45 passed 与构建通过。Ruff F821/F823/F401 与 git diff --check 通过。

限制：当前 provenance 锁进程内有效；多进程 sidecar 竞态可能完整性拒绝，不是分布式原子事务。相同 Markdown 但来源不同的恢复返回 409，避免仅正文哈希 CAS 无法辨别来源提交的恢复歧义。未验证真实浏览器、多进程及带历史图片的可视交互，不据此宣称全部 B6 完成。

## 浏览器黑盒验收与保存响应修复

本轮使用仅监听 `127.0.0.1:8767` 的临时 FastAPI 服务、真实编辑器路由/授权/workspace，以及两版合成来源；临时密钥随机生成，不连接业务数据库。准备阶段通过接口验证了历史恢复，并将当前草稿恢复为 current 内容，因此本轮不把准备阶段操作计作 GUI 恢复成功。正式测试仅使用可见按钮、DOM 快照和实际查看的截图，未调用页面 fetch 或注入状态。测试视口为 1280x720。

- 来源面板打开、CSV 预览和关闭通过：DOM 与截图共同确认 `period=2025-09`、`revenue=3600`，关闭后弹窗消失且焦点回到来源按钮。
- 页面加载后未手动编辑即出现“操作失败”，并显示“来源待复核 3 处”；表格结束标记被渲染成表格行。该表格显示问题尚未修复，也未证明来源计数符合预期。
- 历史列表及版本差异显示通过；点击“恢复为当前草稿”后未获得正文切换或反馈。代码存在 `window.confirm` 前置确认，本机运行时后续查询未返回确认框，因此历史恢复 GUI 路径记为未完成，不据此判定恢复后端失败。
- 浏览器运行时未提供 console 日志接口，本轮只记录页面表现；正式测试结束后读服务日志定位保存失败：FastAPI `ResponseValidationError` 指向整数 `sourceRevision=2` 与 `dict[str, str]` 返回注解不符，保存已写入却返回 500。

已修复 PUT document 返回注解为 `dict[str, object]`，并扩展历史恢复 HTTP 契约测试：恢复后保存返回 200、保留整数 sourceRevision、正文与 SHA-256 回读一致。仅运行该定向用例，1 passed。此修复尚未重新进行浏览器验收；原服务仍运行修复前代码，不将其视为修复后环境。B6 仍未完成。

已查看并保留的截图：

![加载后保存失败与表格标记异常](../../../gui-test-screenshots/b6-2026-09-30/call_BtDplYcXo775k6FRK4UxuLqe-tool-result-e10139ed-98f8-4c31-b5ce-7c03a009958f.png)

![冻结 CSV 预览](../../../gui-test-screenshots/b6-2026-09-30/call_vNhxPbmunWZ2tffxvwoVYmyW-tool-result-9d0878e7-16eb-4247-b538-be54d5f5344e.png)

![来源面板关闭](../../../gui-test-screenshots/b6-2026-09-30/call_tPdRbZaiXBhigLEFLf14sEpn-tool-result-3c4a4187-e273-4f44-bcb3-4411295adca8.png)

![历史恢复点击后未完成](../../../gui-test-screenshots/b6-2026-09-30/call_atZXwb90V7UUDf6U805PpNEW-tool-result-f67c1e6a-e41a-45ed-974e-cbab13752c23.png)

未覆盖：移动端、AI、历史图片/交互图、真实导出视觉验收、双窗口/多进程 CAS、重复导出及故障恢复。未重复完整测试。

## 表格协议块编辑器渲染修复增量

浏览器黑盒验收发现 `[[table:...]]`/`[[/table:...]]` 结束标记被 Milkdown 表格解析器渲染为表格最后一行，同时 claim 与 table 标记均未在编辑器中隐藏。

修复：
- 后端 `render_table_markdown` 在结束标记前插入空行，使 Milkdown 正确结束表格；`_TABLE_BLOCK` 正则可同时识别新旧格式，保证旧报告与已生成产物向后兼容。
- 前端 `protocol.ts` 新增 `table`/`table_close` marker kind，并复用已有只读保护与保存前还原机制；`style.css` 隐藏 table/claim 标记及其独占段落，避免结束标记残留为表格行。

验证：后端 table/validate 38 项通过，前端 protocol 4 项通过，定向 editor/export/publication/full-render 76 项通过，trace 全量 361 项通过（5 skipped），生产构建通过；Ruff F821/F823/F401 与 git diff --check 通过。未重跑完整套件。

## 后端并发、重复导出与故障注入验证增量

针对计划 B6 验证清单补充了可脱离浏览器运行的后端契约用例：

- **双窗口 CAS**：`test_report_editor.py` 新增 `test_concurrent_save_draft_serializes_and_reports_conflict`，两个任务基于同一 `expected_sha256` 并发保存，验证串行化后恰好一个成功、一个返回 `report_editor_conflict`，且草稿目录只保留一份最终内容。
- **重复导出**：`test_report_editor.py` 新增 `test_repeated_export_creates_sequential_revisions`，从 revision 1 导出到 2、再从 2 导出到 3，验证每个版本独立、旧版 Markdown 不变、渲染每版只触发一次。
- **故障注入**：`test_report_editor_lineage_export.py` 新增 `test_export_revision_fails_cleanly_when_lineage_source_file_missing`，导出前删除来源 CSV，验证导出失败（`report_editor_job_invalid`）且不留下 `reports/revision-2` 半成品，原草稿保留。

验证：report_editor 40 项、lineage_export/history_restore 11 项合并 51 项通过；trace 全量 142 项通过；前端 251 项通过；Ruff F821/F823/F401 与 git diff --check 通过。未重跑完整套件。

## Playwright 浏览器复测增量

此前环境缺少浏览器自动化 harness；本增量将 `pytest-playwright` 加入 `dependency-groups.dev`，复用系统 Chromium（避免在测试运行中下载浏览器二进制），新增 `test_report_editor_browser.py`。

浏览器测试覆盖：
- 编辑器加载后 table 协议块（`[[table:...]]`/`[[/table:...]]`）不可见，表格正常渲染；
- 点击“来源”打开数据追溯面板，异步加载后能看到数据集条目；
- 点击“预览”展开 CSV 表格，包含 `2025-09`/`3600`；
- 关闭面板后弹窗隐藏。

验证：`-m integration` 下浏览器用例 1 passed；此前后端 table/validate 38 项、前端 251 项、trace 全量 142 项均通过；生产构建通过。未重跑完整套件。

## 历史恢复 GUI 浏览器用例增量

在已有 Playwright harness 上补充历史恢复端到端用例：

- 构造 revision 1（旧正文，含 table/claim 与 trace-index）与 revision 2（新正文）两个已发布 context；
- 浏览器打开 revision 2，验证初始正文为当前版本；
- 点击“历史”打开版本列表面板，选择 revision 1，点击“恢复为当前草稿”，自动处理 `window.confirm`；
- 验证状态栏出现“已恢复第 1 版及来源”，正文回退到 revision 1（编辑器区域出现“报告”与表格数据，不再包含“Current report”）；
- 重新打开“来源”面板，验证数据集“收入明细.csv”出现在 revision 1 的来源列表中。

修复发现的前端缺陷：`protocolMarkerPlugin.filterTransaction` 会拦截任何改变协议标记的 ProseMirror transaction。当恢复的历史版本包含当前正文没有的 `[[table:...]]`/`[[claim:...]]` 时，普通 `replaceAll` 的替换 transaction 被过滤，导致编辑器内容不更新。历史恢复改用 `replaceAll(restored.markdown, true)`（flush 模式重建 EditorState），绕过该拦截。

验证：`-m integration` 下浏览器用例 2 passed（含此前 table/来源用例），后端 editor/history_restore/lineage_export 51 项通过，trace 全量 142 项通过，前端 251 项通过，生产构建通过；Ruff F821/F823/F401 与 `git diff --check` 通过。未重跑完整套件。

## 程序化文档替换防拦截修复增量

历史恢复用例暴露的 `protocolMarkerPlugin.filterTransaction` 问题同样影响其他程序化整文替换场景：冲突恢复、合并重试、本地草稿恢复、会话快照恢复都可能引入当前正文没有的协议标记（例如远端版本带 table/claim，或本地崩溃前草稿含标记），导致 `replaceAll` 被静默拦截、编辑器内容不更新。

修复：上述场景统一改用 `replaceAll(markdown, true)`（flush 模式重建 EditorState），避免被 filterTransaction 拦截。搜索替换保持原行为（其 `replaceAll` 为搜索控制器的整文替换入口，通常不引入新协议标记；若后续出现可再处理）。

涉及位置：`main.ts` 中 conflict 的 `mergeAndRetry`/`recoverFromConflict`、本地草稿恢复回调、历史控制器的会话快照恢复分支。

验证：前端 251 项通过，`-m integration` 浏览器用例 2 passed，后端 editor/history_restore/lineage_export 51 项通过，trace 全量 142 项通过，生产构建通过；Ruff F821/F823/F401 与 `git diff --check` 通过。未重跑完整套件。

## 双窗口 CAS 浏览器体验验证增量

新增 Playwright 用例模拟两个独立浏览器 context 同时编辑同一报告 revision：

- 窗口 A 与窗口 B 使用同一会话 cookie 分别加载编辑器；
- 窗口 A 在正文末尾追加 " edited by window A" 并点击保存，等待状态栏显示“已保存”；
- 窗口 B 在正文末尾追加 " edited by window B" 并点击保存；
- 验证窗口 B 状态栏出现“保存冲突”，因为 B 保存时携带的 `expectedSha256` 已被 A 的保存更新。

该用例不调用页面 fetch 或注入状态，完全通过可见按钮、键盘输入与状态栏文本断言验证真实 CAS 冲突提示。

验证：`-m integration` 下浏览器用例 3 passed（含 table/来源/历史恢复），后端 editor/history_restore/lineage_export 51 项通过，trace 全量 142 项通过，前端 251 项通过，生产构建通过；Ruff F821/F823/F401 与 `git diff --check` 通过。未重跑完整套件。

## 重复导出浏览器体验验证增量

新增 Playwright 用例 `test_editor_repeated_export_creates_sequential_revisions`，在浏览器中连续点击“导出 PDF”按钮：

- 构造 revision 1 的已发布 context、draft Markdown 与 mock render/pdf/word 产物；
- 为 editor 提供带 `apply` 方法的内存 durable state repository，使 `export_revision` 能按版本号递增提交新 context；
- 浏览器加载编辑器后连续两次点击导出按钮，等待导出浮层出现，断言浮层内 `.export-revision` 文本依次为“版本 2 已生成”“版本 3 已生成”。

该用例覆盖浏览器端导出按钮、浮层关闭与顺序 revision 生成，不依赖真实 PDF/Word 渲染，亦不做视觉验收。

验证：`-m integration` 下浏览器用例 4 passed（含 table/来源/历史恢复/双窗口 CAS），后端 editor/history_restore/lineage_export 51 项通过，前端 253 项通过，生产构建通过；Ruff F821/F823/F401 与 `git diff --check` 通过。未重跑完整套件。

## 故障恢复浏览器体验验证增量

新增 Playwright 用例 `test_editor_export_failure_shows_error_and_recoverable`，验证导出失败后前端能显示错误并恢复：

- 复用重复导出的测试构造，但让 mock `_render_report_pair` 第一次调用抛出 `ReportingError("report_editor_export_failed", "渲染失败")`；
- 浏览器点击“导出 PDF”，等待状态栏进入 `data-state="error"` 并显示“导出失败”，同时导出浮层与阻塞遮罩均隐藏；
- 点击状态栏旁的“重试”按钮，第二次渲染成功，导出浮层显示“版本 2 已生成”；
- 关闭浮层后在编辑器追加文字并保存，验证状态栏显示“已保存”，编辑器在导出失败后仍可正常编辑。

该用例覆盖后台导出任务失败、前端轮询到失败状态、错误提示、重试恢复与编辑器可用性，不依赖真实 PDF/Word 渲染。

验证：`-m integration` 下浏览器用例 5 passed（含 table/来源/历史恢复/双窗口 CAS/重复导出/故障恢复），后端 editor/history_restore/lineage_export 51 项通过，前端 253 项通过，生产构建通过；Ruff F821/F823/F401 与 `git diff --check` 通过。未重跑完整套件。

## B6 剩余（下一增量）

1. ~~浏览器黑盒复测与 N+1 视觉验收~~：已实现 Playwright 浏览器复测核心路径（含 table 隐藏、来源面板、历史恢复、双窗口 CAS、重复导出、故障恢复）；仍待带图表/封面/目录的真实渲染视觉人工审查。
2. ~~历史恢复 GUI 路径~~：已实现真实浏览器用例（见上节）；历史静态图片恢复及刷新已验证（见下节）。既有交互图恢复体验尚未验证，且不属于本计划新增追溯能力。
3. **前端集成验证及定位收紧**：控制器已接线，AI/历史修改复用 Markdown 更新事件；table 协议块渲染与隐藏已修复，claim 标记已纳入隐藏；程序化整文替换防拦截已修复。仍受多期间事实和相对期间无法唯一定位的限制（见上节）。
4. ~~表格重判的复制单元格细分~~：已实现——重复标签行（复制行）不再静默覆盖首行映射，与未知标签行一起进入复制候选；新格文本与冻结单元格事实值一致时返回逐格候选绑定提示（`tables[].copiedCells`：行标签/列/文本 + 候选 rowKey/columnKey/factKey，截取前 5 条），`tableSummary.copiedCells` 计数并计入前端待复核；复制后改值不给提示、原映射行不受影响。新增 1 例覆盖三种复制场景，36 项合并回归通过。
5. ~~双窗口 CAS / 重复导出 / 故障注入~~：已实现核心后端契约用例、双窗口浏览器体验验证、重复导出浏览器体验验证与故障恢复浏览器体验验证。

## 历史静态图片恢复与 AI 来源保护增量

本轮修正已有、尚未通过的历史图片浏览器用例：图片改用真实 workspace API 写入，修改历史正文时同步更新权威 manifest 与 trace-index 的正文身份和登记哈希，不再通过猜测本地目录或不一致的冻结身份构造测试。修正前用例无法加载历史详情，恢复按钮一直隐藏；修正后验证 revision 2 恢复 revision 1、图片实际加载为 80×40，以及刷新后仍可读取历史图片。这里只验证静态图片，不涉及 Plotly。

AI 后端协议选区保护此前漏掉新增的 claim/table/结束 table 标记，现与前端约束对齐，原生及 Markdown 转义标记均在调用模型前拒绝。新增生命周期用例使用确定性 agent 替身，经过真实 AI service、来源校验和草稿保存：改写 3600 为 3800 后绑定 stale、冻结 factValue 仍为 3600；保存成功；撤销恢复原文并保存后绑定重新 valid。该用例不代表真实模型或 AI 浏览器交互验收。

验证：

- Chromium 集成定向 `test_editor_history_restore_recovers_image_asset`：1 passed、5 deselected（真实 HTTP、授权、workspace、历史恢复与刷新）。
- AI 文件首次运行：14 passed，新增生命周期用例因测试断言误用 `value` 而失败；修正为接口的 `factValue` 后仅重跑该例：1 passed、14 deselected。
- B7 builder/service 定向回归：15 passed；本轮没有重跑源库探针或大快照基准。
- 修改 Python 文件 Ruff F/I 与 `git diff --check` 通过。未重复完整测试。

B6 仍不标记 G6 全部通过：带图表/封面/目录的真实导出视觉审查、AI 浏览器应用/撤销及多进程提交竞态仍未在本轮验收。多期间/相对期间的语义提示边界保持原记录，不通过扩大猜测匹配消除限制。

## AI 接受拒绝撤销浏览器验收与格式误判修复

新增 `test_editor_ai_accept_and_undo_revalidate_claim`，使用真实 Chromium、同源授权、AI HTTP 流接口、Milkdown 选区工具栏、diff 操作、草稿保存与来源校验。模型使用确定性 agent 替身，不连接外部模型。

浏览器验证：初始正文与表格有效；AI “全部拒绝”后原正文及有效状态保持；再次改写并“全部接受”后 3600 改为 3800，来源待复核 1 处，保存成功且 claim 标记保留；Control+Z 后恢复 3600，来源重新对应当前内容，再次保存成功。两次模型请求均不含 claim 身份。截图已实际查看，正文、表格和来源状态可见；证据位于本机 `/tmp/pytest-of-junge/pytest-174/test_editor_ai_accept_and_undo0/ai-accepted-stale.png` 和 `ai-undone-valid.png`（临时测试目录，可能被后续 pytest 清理）。

用例在初始有效状态发现并修复两个格式变化误判：

- 前端 `restoreProtocolMarkers` 未还原 Milkdown 转义的 `/table:` 结束标记；补齐规则及真实序列化回归，同时保留非法 `/claim:` 的原始转义形式。
- Milkdown 将列名 `income_total` 序列化为 `income\\_total`，服务端按原始 Markdown 比较而误判两个单元格 stale。表格重判现复用现有 MarkdownIt 解析器提取行列标签及单元格文本，转义/强调不改变绑定；实际改值与改名仍由原用例检查。

定向验证：前端 protocol/source-validation/ai 共 18 passed；后端表格重判 6 passed、20 deselected；AI 浏览器增强用例 1 passed、6 deselected。生产构建通过（既有大 chunk 警告）。修改服务与浏览器文件 Ruff F/I、subject 测试 Ruff F、`git diff --check` 通过；subject 文件已有额外空行触发 I001，未做无关格式整理。未重复完整测试。

AI 浏览器接受/拒绝/撤销门禁已补齐；B6 不标记整体完成。真实导出图表/封面/目录视觉审查、多进程提交和共享源文件保留清理联合验收仍待推进。

## 同机多进程草稿与来源事务串行化增量

此前 `_draft_lock` 仅是进程内 asyncio.Lock，无法覆盖多个服务进程的正文 CAS 与 provenance sidecar 联合写入。现保留进程内锁，并在已恢复、可信 ReportingWorkspaceIdentity.root 下使用标准 POSIX `flock`：锁键按报告 Markdown 路径哈希生成，文件以 O_NOFOLLOW 打开并检查普通文件身份，非阻塞获取并异步等待，取消或退出均关闭 descriptor。锁文件不删除，避免不同 worker 锁住不同 inode；读草稿、读取活动来源、保存、历史恢复及导出快照读取复用同一锁。

新增真实 multiprocessing spawn 用例：父进程持锁时，两个独立 worker 发起对同一已恢复历史来源的草稿保存，两者都不能提前完成；父进程释放后恰好一个成功、另一个返回 `report_editor_conflict`。回读最终 SHA-256 与成功者一致，sourceRevision 仍为历史 1 版，没有来源 sidecar 错配。另一个用例验证独立 service 等锁时取消，随后保存可完成，未遗留阻塞锁。

验证：多进程定向 1 passed；editor/history_restore/lineage_export 受影响定向回归（排除已单独执行的多进程用例）52 passed、1 deselected。覆盖既有 N+1 成功、渲染/提交失败回滚、提交后授权失败保留、历史恢复与再导出、共享原 CSV/事实字节不被失败清理删除。修改文件 Ruff F/I 与 `git diff --check` 通过，未重复完整测试。

边界：这是同机共享宿主文件系统的 POSIX 锁，不宣称跨主机/对象存储的分布式事务，也不等于对所有平台的支持。未新增定期删除来源快照的任务；当前下载授权过期回收只覆盖持久化 PDF/Word，与 Editor workspace 的 CSV/facts 生命周期不是同一个清理机制。共享来源的定期保留/删除策略及真实导出视觉审查仍待验收，因此 B6/G6 仍不整体勾选完成。

## 富文档逐页视觉验收与图表状态显示增量

真实渲染样本不再使用 4×4 红色占位图：现为 960×400 的营业收入/经营现金流对比图，数值分别为 128.50/32.10 亿元，与样本 CSV 和正文一致。Word 增加内嵌图片宽高比断言，避免嵌入成功但图形被拉伸。图题修正为“核心指标对比”，不将横向指标对比误称为时间趋势。

使用真实 ReportRuntime、WeasyPrint、pandoc 生成 PDF/Word；PDF 经 pdftoppm 转为页图，Word 经文档技能提供的 `render_docx.py` 和 LibreOffice 转为页图。最终两个格式各 3 页，已逐页实际打开全部 6 张 PNG：封面中文完整，目录条目/页码可读，正文图表数值与单位清晰，图题/表格/页眉页脚无重叠或截断，claim/section 协议标记不泄露。PDF 与 Word 保留各自既有样式，不要求两者像素级相同。证据保存在 `gui-test-screenshots/b6-rich-render-2026-09-30/{pdf,word}/page-*.png`。

环境边界：本会话未提供文档技能要求的 workspace dependency loader，因此使用项目现有 Python/LibreOffice，缺少的 `pdf2image==1.17.0` 仅安装到本地 `.venv`，未改依赖清单。不宣称通过了技能规定的 bundled-runtime 环境验证。

另修复前端图表状态遗漏：`TraceValidation` 纳入服务端已有的 `charts` 字段，删除/失效图表计入来源待复核，有效图表也纳入“有精确来源绑定”的判断；旧接口缺少 charts 时保持兼容，仍为软告警，不阻断保存。

定向验证：富文档用例最终 1 passed、4 deselected；图题修正前该例另运行一次通过，属于视觉迭代，不计为两项覆盖。前端 source-validation 7 passed；生产构建通过（既有大 chunk 警告）；Python 文件 Ruff F/I 与 `git diff --check` 通过。未重复完整测试。

B6/G6 仍未整体完成：共享 CSV/facts/作图数据的保留及删除尚未接入；现有图表重判仅检查图片定位，图注变化尚未检测；本次视觉验收是渲染层固定快照样本，并不替代真实 Editor 历史恢复/N+1 提交与双格式渲染的联合验收。不得依据此样本勾选整个生命周期门禁。

## 图题与图注生成时指纹及 N+1 继承增量

新增 `ChartTraceV1.presentationSha256` 可选字段，记录生成时图片 alt、title 与紧邻“图表：/图注：”段落的规范化内容指纹。发布侧使用已验收且哈希匹配的同一份 Markdown 固化指纹。采用既有 MarkdownIt 结构化解析，强调/转义等格式不改变文本身份；无关段落不影响绑定；改图题、改/删图注或图片 title → stale；删图、重复图片、代码围栏里的伪图片、其他目录同名图片 → unbound。旧记录无该字段时，从已登记正文经 size/sha256 校验后补齐，不从当前草稿反推。

N+1 继承保留该生成时指纹；旧记录迁移读取原 index 登记正文，不能读取编辑器已重建 manifest 的新正文来重设基线。冻结正文没有唯一图表定位时记录不可匹配基线，不凭后续新增图片创建有效来源。同名图片登记存在歧义时，裸文件名不能同时绑定两张图。全部内容变化仍是软告警，不阻断保存。服务端已有图表状态进入前端待复核计数及 PDF/Word 来源附录状态，沿用上一增量的接线。

新增测试最初 12 项因直接调用来源服务而漏做 Host workspace 恢复失败；补齐真实编辑器 read_document 入口后 12 passed。随后新增初次发布/同名歧义 2 passed；初次发布用例继续补充正文哈希不符的拒绝断言并单独重跑通过。新增覆盖合计 14 项（重复执行不重复计数），包含连续两个编辑 revision 保持 stale、恢复生成时图注重新 valid，以及真实索引 writer 写入指纹。受影响契约/历史继承/N+1 导出/附录/HTTP 发布定向 53 passed；既有图表删除校验 1 passed；来源未知图表/HTTP 路由另 2 passed。未重复完整套件。

图表列表/预览与既有删除校验在同名歧义规则收紧后定向 2 passed（删除校验重复执行，不重复计覆盖数）。修改模块 Ruff F/I 与 diff 检查通过；`trace_revisions.py` 仅检查 F 通过，该文件既有 import 排序 I001 未做无关调整。此处不把 Python 初次发布 writer 的测试替代外部业务源探针，也不把索引继承替代富文档 N+1 服务联合渲染。

剩余 B6 门禁：共享来源保留/删除接入，真实 Editor 历史恢复与 N+1 双格式联合渲染。现有相对期间和多期间事实定位仍保持已有软语义边界，未增加猜测规则。G6 尚未整体勾选。

## 真实 Editor 双格式联合导出与同行引用图片修复

新增 `test_report_editor_real_export.py`，使用真实 Host workspace、durable reducer、WorkspaceReportService 子进程渲染、ReportArtifactPersistenceService 和授权服务；仅持久化仓库使用内存测试替身。样本含封面、目录、900×260 图表及 48 行跨页业务表格。经实际 save_draft 导出第 2 版，再经 restore_history 恢复第 1 版并导出第 3 版，核验正文/manifest/index 版本与哈希、claim/chart 的 stale→valid、48 个有效表格单元格、双格式持久化原字节、在线 subject 链接的版本号及临时资源清理。原历史正文与来源保持不变。

真实页图检查发现图片同行包含 citation 时未匹配 figure 布局，导致 PDF 图片溢出、数值截断；图注编号匹配也遗漏同行 citation。现扩展既有规则，仅允许服务端生成的来源编号作为图片同行尾部，保留引用文字并给正文图片增加限宽兜底。关闭来源展示仍正常包装 figure，普通正文解释不被误收为图注。移除测试误加的 HTML anchor，标题锚继续由可信 heading contract 绑定，不增加用户 HTML 清理规则。Word figure 被 pandoc 转为布局表，联合测试改为按业务表头识别数据表，不再假设第一张表就是业务表。

定向验证：受影响 citation/heading 用例中既有 53 项及新负向 1 项通过；新参数化用例初次因测试载荷缺少必需字段失败，补齐后 2 项通过（新增共 3 项）。真实联合用例最终 1 passed、71.43 秒；前次运行因上述表格顺序假设失败，修正后仅重跑该用例。未重复完整套件。修改文件 Ruff F/I 通过；pdf.py 排除既有 F841 后通过，该无关未使用变量保持原状；git diff --check 通过。

按 PDF 技能使用现有系统 Poppler，将修复后第 2 版 PDF 第 3 页转为 PNG 并实际查看：图表完整、3600 数值不截断、引用和图注来源编号清晰，无 HTML anchor 泄露。证据：`gui-test-screenshots/b6-inline-citation-2026-09-30/edited-3.png`。此次仅检查受影响页面，不宣称两版本双格式全部页面通过。此前完整页图检查还发现无 subject links 的 citation 附录可能错误显示“有效”，以及 Word 多页正文总页数字段显示 1；这两个缺陷未在本增量修复。

G6 仍不整体勾选：共享 CSV/facts/作图数据保留与删除尚未接入，联合渲染视觉验收仍需修复上述缺陷并完成全页检查。报告 revision 当前没有独立保留期与到期记录；不能把下载授权 TTL 或派生导出 24h 保留期当成来源删除条件。

## 联合渲染视觉门禁补齐增量

继续修复了联合导出实际发现的 citation 状态遗漏、Word 分节总页数缓存及 figure 布局表裁切。最终真实 Editor 联合用例 1 passed（71.34s），第 2 版改值/改图注为 stale、第 3 版恢复原历史证据为 valid；两版 PDF 各 7 页、最终 Word 各 6 页全部实际检查，正文/图表数值、跨页表格、编号/附录状态、目录与页码一致。详细实现、页图证据与环境边界见同日 B8 记录“联合导出全页复核与真实浏览器增量”。

本样本的历史恢复/N+1 双格式联合渲染门禁已有语义与全页视觉证据；不得据此推断所有生产数据样本或 Microsoft Word GUI 均通过。G6 仍缺共享 CSV/facts/作图数据保留及删除接入，不整体勾选。报告版本未登记到期信息时继续保留，不能采用派生下载保留期删除历史证据。

## 设计决定（如实记录）

- claim 标记由服务端装配注入而非模型书写：与 citation 同治理边界（协议标记不可伪造）；编辑器侧由既有 marker 只读保护覆盖（前端 protocol kind 扩展即生效，无需新插件）。
- subject 定位锚用协议标记而非字符偏移：符合"不依赖易变字符偏移"（计划 3.2）；标记删除 = unbound 是显式状态而非定位失败。
- validate 的数值比对宽松（多形态文本命中）：这是软语义校验；严格数值核对是发布门禁（B2 的硬核对）职责，两者不混。
- factId 目录复用表格构建的 bundle 读取：一次 IO 服务表格与 subject 绑定两个消费者。

## 2026-10-01 保留策略与共享来源清理预检

已增加服务端维护入口 `set_revision_retention` 和耐久 reducer 命令 `set_report_editor_retention`：截止时间必须带时区，绑定已登记 context 的 digest，独立存入 `reportEditorRetention`，不修改 context 身份或现有授权。缺省策略及显式 `expiresAt: null` 均永久保留；下载授权 TTL、派生导出保留时间不参与判断。策略支持截止时间调整及恢复永久保留，重启后仍可读。

本次推进增加 `preview_revision_source_cleanup(expected, now=...)`，仅供服务端维护，只读预检，不新增 HTTP 清理路由，也不删除文件：

- 严格读取当前 workflow 中全部版本登记，不沿用历史列表跳过损坏项的行为；作用域、版本键、保留策略 digest 必须一致。
- 以权威 manifest/index 扫描共享来源引用，未到期或未登记期限的版本保护其来源；所有草稿 sidecar 的 active/pending 来源也保护，宁可多保留，不冒险删除恢复中的历史证据。
- 固定顺序获取既有 POSIX 草稿锁；缺索引、损坏 provenance、同一路径的文件身份冲突时停止预检；扫描后复核耐久状态版本，变化则拒绝返回候选。
- 返回到期/受保护版本、受保护路径及候选文件登记身份，显式 `dryRun: true`。候选只表示当前登记中没有受保护版本引用，**不表示文件实际字节、归属、其他工作流中间状态或删除执行条件已验证**，不可将清单直接交给通用删除工具。

验证使用 `python-testing-patterns` 技能组织真实 Host workspace 与真实耐久 reducer 定向测试。`test_report_editor_retention.py` 8 passed；扩充共享引用边界及新增状态变化用例后，仅执行这两个受影响用例，2 passed、7 deselected，去重覆盖共 9 项。涵盖默认保留、可逆策略、重启、身份/时区拒绝、共享 CSV/facts 保护、最后登记引用到期、独有中间结果候选、真实历史恢复的 active/pending 保护，以及六类权威登记损坏停止预检。预检不改变耐久状态、不删除来源文件。修改模块 Ruff F/I 与 `git diff --check` 通过，未重复完整测试。

**B6/G6 仍未完成**：尚未接入实际来源回收、耐久回收记录及失败恢复；执行删除前仍需覆盖来源读取/完整导出周期与清理的锁协调，核对生成中 workflow 的引用及文件所有权，并验证回收后 metadata 可读、详情明确不可用、不重新查询真实数据源。此次预检不能替代上述联合门禁。

## 2026-10-01 实际来源回收与耐久重试增量

本轮在上述预检基础上接入服务端维护入口 `cleanup_revision_sources`，不新增公开删除 API、不自动选取报告或期限。仅允许 phase=completed 的工作流回收来源，避免与生成中 workflow 的来源引用竞争。workspace key 包含 run 身份，扫描同一耐久 run 的全部已登记版本；不跨工作区猜测文件归属。

生命周期使用工作区根目录固定 inode 的 POSIX shared/exclusive flock：来源读取、草稿保存/恢复、完整 N+1 导出、后台派生快照生成和 CSV 响应发送持有共享锁，策略修改和实际回收持有独占锁。锁文件不删除；支持同机多个 worker，不宣称跨主机或对象存储锁。下载发送前再次校验来源，并禁用 ASGI 延后按路径发送扩展，防止响应返回路径后释放锁、服务器稍后才打开文件。

回收先从权威登记重新预检，并校验全部候选的大小/哈希，再以耐久 reducer 登记 pending 回收意图与版本来源 retired 身份。实际删除只处理意图里的精确普通文件，逐级 O_NOFOLLOW 打开目录和文件、核对大小/哈希/inode，再 unlink；不递归删除目录，不删除 Markdown、manifest、追溯索引。途中失败保留 pending；重启重试重新核对引用和身份，已删文件视为幂等完成。finish 命令持久化已回收文件登记；finish 提交失败也可重试。retired 版本不能通过修改期限重新变为有效来源。

过期版本正文与历史列表仍可读，来源概览保留数据集业务名、行数和登记身份，返回 `available=false/reason=snapshot_expired`；明细拒绝为 410，不调用实时数据源。前端显示保留期结束提示、仍展示数据集登记信息，禁用预览/原始下载。历史恢复和含来源的再导出不会伪造已回收证据。

新增回收定向验证去重共 8 项：最后共享引用到期才删除 CSV/facts、独有中间结果回收、元数据/正文/历史可读、未完成工作流禁止清理、读取期间等待、删除中途失败重启重试、finish 提交失败重试、哈希替换/符号链接拒绝，以及真实 ASGI 文件响应锁覆盖和过期前置重判（参数化项计入去重数）。这组不是对全部生命周期的整体完成声明。HTTP 原始下载/后台脱敏回归另 2 passed；N+1/历史恢复及预检状态变化受影响回归 13 passed、13 deselected。前端 trace-panel 18 passed；TypeScript/Vite build 成功，既有 chunk 大小警告保留。修改模块 Ruff F/I、diff 检查通过，没有重复完整套件。

仍不勾选 G6：新清理分支尚需真实浏览器过期状态与富图表/作图数据共同回收验收、同机多进程生命周期锁联合测试，以及逐项复核总计划 B6 验证表。当前到期版本允许读/编辑正文，但不允许凭已回收来源重新恢复或带来源导出；不能把此明确拒绝称作“所有旧报告导出场景已验收”。B8 显式省略摘要的真实双格式渲染增量也仍待完成。

生命周期锁接线后的 B7 Editor 下钻能力/对账与重新分析新旧快照隔离定向 2 passed、30 deselected；未重复真实源库探针或大快照基准。B7 既有完成证据保留，不据这两个用例扩大结论。

## 2026-10-01 独立进程与真实浏览器回收验收

新增 `test_cleanup_waits_for_reader_in_independent_process` 使用 spawn 独立进程持有真实工作区生命周期共享锁：主进程实际回收等待期间，耐久状态尚未退休来源、候选文件仍存在；子进程释放后，回收完成并精确删除独有文件。1 passed。子进程验证锁原语，主进程执行真实回收与 reducer；不把此用例称为两个独立数据库 worker 的完整分布式事务验收。

新增 Chromium 用例 `test_retired_sources_keep_browser_metadata_and_live_revision_preview`，通过真实 Host workspace、耐久 reducer、维护回收、HTTP 会话和静态前端打开两版报告。到期版本来源面板仍显示收入明细业务名和行数，明确“明细不可用”，预览/原始下载按钮禁用；直接请求下载返回 410/snapshot_expired。有效版本仍从原共享 CSV 预览 3600。显式 `-m integration` 定向 1 passed、8 deselected；首次合并命令被默认 `not integration` 排除，不能将排除视作浏览器通过。两张截图已实际打开检查，保存在 `gui-test-screenshots/b6-retention-2026-10-01/`。

新增共享静态图与 chart-input JSON 联合用例：真实 PNG、结构化作图输入及 ChartTraceV1 登记由两个 revision 共用。第一版到期只删独有中间结果，第二版仍可读图像哈希及作图表；第二版也到期才删除两项并拒绝图表明细。第一次运行发现测试错误使用不存在的 `charts` 模型字段，改为严格 model_validate 的 `chart_traces` 后，定向 1 passed、18 deselected。不凭这个资源身份样本宣称整套富图表视觉验收。

新下载响应的发送前重验错误映射已沿用 `TRACE_ERROR_HTTP_STATUS`，避免原本的 409 完整性错误/403 权限错误被误降为 404。定向 2 passed、19 deselected，过期仍为 410。B6 总门禁尚未最终勾选，下一步应完成按总计划逐项的最终审计；不能只按本轮新增测试覆盖重新定义完成范围。

## 2026-10-01 G6 完成审计

按总计划 B6 原始范围逐项复核，不以本轮回收测试代替此前生命周期证据：

1. 正文 claim、结构化表格和静态图题/图注均已固定生成时身份及规范化规则；数值、单位、期间、标签、排序、插行、复制、删图、重复图和纯格式变化分别有软语义重判证据。
2. 本地编辑即时进入待复核，服务端响应绑定草稿 SHA-256；自动保存、CAS、双窗口冲突及 AI 全部接受、全部拒绝、撤销后重新校验均已通过浏览器或服务契约。
3. 历史读取/恢复绑定各自冻结索引和资源；静态图片恢复、刷新、恢复后 N+1 及重新分析新旧快照隔离均有独立用例，旧 revision 不被覆盖。
4. N+1 正文、manifest、trace index、PDF 和 Word 从同一快照联合提交；改值/改图注后的 stale 与恢复后的 valid 已由真实 Editor 双格式联合导出及全页检查证明。
5. 顺序重复导出、旧版重定基、并发读取、渲染/提交失败清理、提交后授权失败保留、后台失败重试和同机多进程正文/来源事务均有故障注入证据。
6. CSV、facts、静态图、chart-input 和中间结果按最后受保护 revision 回收；保留策略、共享引用、读取/删除锁、耐久 pending/finish 重试、文件身份重验及回收后 metadata/410/浏览器状态均已覆盖。无到期登记时永久保留，下载授权 TTL 不参与来源删除。

最终定向复核：沙箱内 AnyIO worker 不能调度，最小 `anyio.to_thread.run_sync` 同样挂起；移到沙箱外后，B6 保留/回收、图题指纹和重新分析隔离合并 **36 passed**，真实 Chromium 过期来源体验 **1 passed**。前端来源校验、面板与在线定位 **28 passed**；相关 Python 文件 Ruff 与 `git diff --check` 通过。没有重复完整测试。

G6 结论：原始实施 1～6、验证清单和门禁均已有直接证据，B6 完成。边界仍如实保留：生命周期锁是同机 POSIX 文件锁，不宣称跨主机/对象存储分布式事务；相对期间和多期间事实继续作为软语义提示，不增加猜测匹配；这些不改变计划冻结的交付范围。
