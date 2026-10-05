# Report Editor 数据追溯 B8 进度记录

日期：2026-09-30。状态：第一增量（citation 编号/共用附录/显示开关/在线链接）与第二增量（claim/表格/静态图统一编号、状态投影、双格式联合验收）已落地；跨页表格视觉、人工视觉复核、浏览器交互与授权过期体验仍未覆盖，B8 未完成。

## 已完成

- 渲染器按 Markdown citation 首次出现顺序签发 `[来源 NNN]`，同一 citation 复用同一编号；未登记 citation 继续失败关闭。
- PDF 和 Word 从同一份服务端 presentation 生成“实际引用附录”，展示业务名称、状态、范围、期间、方法、快照摘要和在线定位。
- Word 附录使用专用非目录样式并强制新页，不污染正文标题编号或目录字段。
- 在线链接从冻结 trace index 的 subject→fact→dataset 精确关系生成，只包含 report/revision/subject，不携带 grant/session token；无法精确解析时不猜测。
- 导出设置增加“来源编号与附录”开关。关闭时只隐藏展示，citation 身份仍参与渲染与 manifest 验收。
- 无 citation 的旧报告继续按原路径导出。

## 验证证据

- 后端渲染/引用/发布定向回归：18 passed；另有在线 subject 链接专项回归覆盖凭据不外泄。
- 前端导出设置：4 passed；TypeScript 与 Vite 生产构建通过。
- 真实 WeasyPrint PDF 与 DOCX 渲染样本均为 2 页；逐页 PNG 检查无裁切、重叠、破损表格或标题污染。DOCX 使用动态 `SECTIONPAGES` 字段并标记打开时更新；LibreOffice 无头预览不会刷新其缓存值，Microsoft Word 打开后会按既有契约更新。

## G8 剩余

1. ~~按当前草稿校验结果把 `stale` / `unbound` / 缺文件状态精确投影到对应附录条目~~：第二增量已实现（claim 状态来自草稿校验，表格按单元格计数聚合，附录显式标注待复核/未绑定）。
2. ~~Editor 页面读取 `?subject=` 并自动打开对应来源对象；无 cookie/授权时保持现有 404/410 边界~~：已实现。页面载入后读取 `?subject=`（`linked-subject.ts`，128 字符契约上限，空值/超限不猜测）并调用 `tracePanel.openSubject`——sources 载入后按 subject 精确定位：chart 主体开图表来源、factRef 开事实明细、computationId 开计算记录，均不在冻结索引时不猜测并明确提示。无会话时页面加载即 404/410（现有授权边界，未改动）；会话中途过期的 410 在面板内给出“从报告列表重新打开”文案且不提供无意义重试。测试：`linked-subject.test.ts` 3 passed、`trace-panel.test.ts` 17 passed（含新增 410 无重试用例）；tsc 与 Vite 生产构建通过。浏览器内人工核对编号与在线对象对应仍属剩余项 2 的视觉验收范围。
3. ~~表格单元格和图表 subject 纳入同一附录矩阵，并覆盖多 CSV、多次引用和长中文名~~：第二增量已实现（表格经单元格 factRefs 解析数据集、图表按登记 imagePath 与正文图片绑定）；跨页表格场景仍未覆盖。
4. 用真实新报告和历史 revision 分别核对 Markdown、trace index、PDF、Word 版本一致性。

## 第二增量（2026-09-30）：数据来源附录（claim / 表格 / 静态图）

1. **统一编号**：`_pdf_markdown` 新增 `_traceSourcePresentations` 载荷，`[[claim:id]]`、表格块与静态图共用 `[数据来源 NNN]` 序列，按 Markdown 首次出现顺序分配；同一事实多次引用复用编号（claim 按首个 factRef 身份聚合）；正文未出现的登记项（标记被删的 unbound claim）排锚点后仍进附录；未登记标记不显示编号，模型无法伪造脚注。claim 编号内联替换标记，表格在块尾追加编号行，静态图把编号写进 `*图表：…*` 图注（无图注只进附录）。citation `[来源 NNN]` 与 `[数据来源 NNN]` 分序列，脚注不冲突。
2. **同一附录**：`markdown.py` 新增 `数据来源附录` 模板：事实值（整数化浮点）、期间（claim 用事实 periodValues，表格/图表用数据集 periodRoles）、范围（事实 scope / businessLabel）、方法（formula / computation / 图表转换说明）、源文件业务名称；不嵌入明细。
3. **失效状态**：附录以 `状态：待复核/未绑定/来源缺失` 显式标注；无追溯索引旧报告不生成附录、导出不受影响。
4. **在线定位**：指向 `/reports/v1/editor/{reportId}/{N+1}?subject={subjectId}`，无 token；PDF 链接注解、Word 外部超链接关系。渲染器沿用 `_valid_source_url`（仅 subject 查询、禁 userinfo/fragment）。
5. **导出装配**：`service._build_export_trace_sources` 从冻结索引 + 草稿校验装配，与引用展示同一快照联合渲染；表格数据集从单元格 factRefs 经同一事实解析并集补齐；载荷 >16 KiB 显式失败（job 48 KiB 硬上限），不静默截断。`validate` subjects 补充 `unit/periods/formula/scope/datasetIds`（冻结事实登记，不从草稿反推）。
6. **渲染验收**：`validate_pdf` 新增可见性门禁——来源开启时每个编号与附录标题必须在 PDF 文本且登记标志为真，关闭时三者缺失，协议标记任何设置不泄露。Word 外链门禁从“拒绝一切外部关系”收紧为“仅无凭据 http(s) 超链接并计数”——原门禁使带在线定位的 citation 附录在 Word 必败（既有潜伏缺陷），宏/OLE/ActiveX 拒绝保留。

### 第二增量验证

- 真实渲染：`test_report_runtime_full_render.py` 5 passed——双格式样本覆盖 claim 两次复用、图注/表格编号、多 CSV、长中文名、待复核/未绑定、未提供在线定位；PDF 文本 + 链接注解 URI、Word 段落 + rels 外链、`externalRelationshipCount` 三路核对；关闭来源双格式无编号无附录；样本过真实 `validate_pdf`（pdftoppm + Word 结构/渲染校验）ok=True。
- 渲染器单测 9 passed（顺序/复用/关闭保留登记/载荷严格校验/附录模板/可见性门禁正反例）；服务集成 `test_report_editor_lineage_export.py` 6 passed（渲染 job 携带完整载荷、3800 改值 → stale、URL 指向 N+1、图表状态投影）；`test_trace_subject_validate.py` + `test_report_editor_trace.py` 合跑 57 passed（含图表状态重判测试）。
- 既有回归：111 + 15 + 71 + 10 passed；修复一处与本增量无关的既有夹具漂移（`test_http_sources_preview_and_download` 夹具未登记 subject 绑定）。Ruff F821/F823/F401 与 `git diff --check` 通过。未重复完整测试。

### 第二增量剩余

1. 跨页表格编号行与附录的视觉核对；人工/截图级视觉验收（栅格化门禁 ≠ 人工视觉复核）。
2. 浏览器内导出后人工核对编号与在线对象对应；授权过期打开体验的自动化用例已覆盖（410 面板文案），真实浏览器体验未人工验证。
3. ~~图表状态恒为登记完整（valid）：草稿删图无 per-chart stale 判定~~：已实现。`validate` 返回新增 `charts` 载荷——按草稿 Markdown 中 `](image)` 出现次数重判：恰 1 次（登记时唯一绑定）为 valid，删图或重复引用为 unbound；`_build_export_trace_sources` 将其投影为附录图表状态。测试 `test_validate_marks_deleted_chart_unbound_and_keeps_present_chart` 覆盖删图与在文两种情况。
4. 摘要显示截断：源文件 10 项、方法 5 项、claim 主体 10 个；载荷 16 KiB 上限在超大报告显式拒绝导出；多期间事实附录同样显示全部登记期间（B6 已知限制）。

## 完成审计修复增量

按 B6/B7/B8 原始门禁复核发现并修复三类实际缺口：

- 多个不同 claim 引用同一冻结事实时，装配器原先只保留首个 claimId，后续正文标记没有编号。现在合并条目保留全部 claimIds，渲染器将这些标记映射到同一个条目，按任一标记首次出现分配编号，附录仅出现一次。新回归故意将第二个 claim 放在正文前面，核对两次编号复用、一条附录及两条定位链接。
- 仅被表格引用的事实没有正文 claim 缓存时，原先漏掉 CSV 与计算方法。validate 现从已经过文件身份校验的同一 fact cache 为每张表提供 datasetIds/methods，导出取其摘要；不依赖正文引用存在。
- 单位/期间软告警、新插行和复制候选原先可能仍导出“有效”。现在数据来源附录与 citation 附录统一投影为“待复核”；validate 的 valid 与 warnings 仍独立返回，保存不受阻断。

验证：装配/渲染器/subject/N+1 定向 45 passed；插行与表格摘要增量定向 7 passed、23 deselected；citation 软告警增量 1 passed、4 deselected。修改 service、trace_sources 与新增附录测试 Ruff F/I 通过，git diff --check 通过。pdf.py 既有 F841（citation normalization 的未使用 aliases）仍存在，未做无关清理。未重复完整测试。本轮尚未补齐跨页视觉、来源保留清理及浏览器在线对象联合验收，B8/G8 不整体标记完成。

真实 PDF/Word 来源附录定向用例另行 1 passed、4 deselected（20.24s），通过同一 ReportRuntime 渲染、文本/外链核对与 validate_pdf 联合门禁；本次未查看逐页 PNG，不把该结果记作新增视觉验收。

## 联合导出全页复核与真实浏览器增量

实际 Editor 保存改值/改图注后导出第 2 版、恢复第 1 版后导出第 3 版的联合用例已通过。样本包括封面、目录、48 行跨页表格、静态图及来源附录；两版 Markdown、manifest、index、PDF/Word 登记与持久化原字节匹配，链接指向各自 revision，claim/chart 状态从 stale 恢复 valid。

全页审查发现并修复以下实际缺陷：

- citation presentation 没有 subject links 时未反映 stale。现在使用权威 manifest 的 citation→dataset 映射，聚合当前 claim/table/chart 的最差状态；不同数据集不受影响，仍为软告警。新增三种对象类型参数化回归，真实双格式用例明确断言第 2 版“实际引用附录”不再显示有效，第 3 版重新有效。
- Word 的 SECTIONPAGES 缓存始终为 1。改用分节末尾书签的 PAGEREF 动态字段；目录与正文各自从 1 起，保留编辑后重新排版的更新能力。LibreOffice 真实渲染两版各 6 页，目录 `i / 1`，正文逐页 `1 / 4` 至 `4 / 4`，不是借用 PDF 的页数。
- PDF 同行 citation 阻止 figure 包装/图注编号的问题见 B6 增量。Word 还被 pandoc 将 figure 转成窄布局表，图片右侧被裁切；现在仅 Word HTML 使用 div 和图注段落，沿用图片页宽等比缩放，PDF figure 分页不变。最终 Word 只含一张 49 行业务表，不再含 figure 布局表。

已实际打开两版 PDF 各 7 页与修复后 Word 各 6 页，共 26 张完整页图：封面/目录清晰；3600 图中数值完整；跨页表头重复、记录 01～48 可读；表尾数据来源 003、图注数据来源 002 与附录一致；第 2 版引用/正文事实/图表待复核、表格有效，第 3 版全部有效；页眉页脚无重叠。最终 PDF 页图与上一批已逐页打开的 PNG 通过 diff -qr 完全一致，Word 使用最后一次布局修复后的新页图，不采用有截断的旧页图。证据在 `gui-test-screenshots/b6-b8-reviewed-2026-09-30/revision-{2,3}/{pdf-final,word-paragraph}/`。

新增真实 Chromium 用例核对同一 report/revision/subject 链接进入冻结事实明细（3600 万元、sum(revenue)）；匿名访问返回 404；真实会话过期后来源面板显示“从报告列表重新打开”，无重试按钮。两张截图均实际查看，保存在上述证据目录 `browser/`。浏览器使用真实 Editor API/Host workspace，授权仓库为内存测试替身；不宣称真实生产登录系统已验收。

验证：附录装配定向 8 passed；浏览器定向 1 passed、7 deselected；联合导出最终 1 passed（71.34s），版式修复前另通过一次（71.71s），不重复计覆盖；heading/figure 定向回归通过。Ruff F/I 与 diff 检查通过，未重复完整测试。按 Python 测试、PDF、文档技能进行定向回归及渲染复核；环境仍缺 bundled dependency loader，使用项目现有依赖及系统 LibreOffice，不宣称完成 bundled-runtime 验证或 Microsoft Word GUI 验证。

G8 尚不整体完成：附录源文件/方法/转换说明/在线主体的摘要截断仍需显式说明或改为完整展示并处理预算，不能把已有切片当作全部来源。G6 共享来源保留/删除接入仍未完成；B7 已有真实业务源与算法验收证据在本轮未重复运行。

## 2026-10-01 摘要省略契约与真实输出增量

此前静默截断缺口已修复：Editor 先收集完整数据，再应用源文件 10、方法 5、转换说明 10、subject/link 各 10 的摘要上限，将超出项数量写入可选 `omittedCounts`。共享事实保留全部 claimIds，不能因链接摘要上限改变正文编号；权威索引和在线来源登记不裁剪。完整载荷超过既有 16 KiB 总预算仍显式报错，不悄悄丢弃字段。

渲染器严格校验省略字段及正整数数量（拒绝 bool、负数、未知字段、超大数量和非对象），共享 HTML 模板明确显示源文件/方法/转换说明/在线定位各自省略数量，并提示完整登记见在线数据来源。表格/图表/claim 均覆盖，subject 与链接同源计数，不单独重复显示相同的主体省略数。

前序定向证据：装配及 citation 契约 26 passed；追加 claim/chart 共享编号用例 1 passed、9 deselected；总预算仍显式拒绝用例 1 passed、10 deselected。此处补记已执行证据，不重复整个套件。

本轮新增 `test_render_summary_omission_counts_are_visible_in_pdf_and_word`：真实 ReportRuntime/WeasyPrint/pandoc 生成 PDF 和 DOCX，两个格式文本均包含源文件、方法、转换说明、在线定位省略数量、完整登记提示、稳定编号及 stale/unbound 状态；原始载荷不变。定向 1 passed、5 deselected。使用 PDF 技能的标记与逐页 PNG 检查；新 PDF 共 3 页均实际打开，摘要行可读、状态/编号不冲突、无裁切或重叠，页图保存在 `gui-test-screenshots/b8-summary-omissions-2026-10-01/pdf/`。固定样本中的 4x4 红色图片仅用于定位编号，本样本不是富图表可读性证据。

边界：当前环境未提供文档技能要求的 bundled workspace dependency loader，也未发现 bundled LibreOffice。因此本轮采用项目自身的既有运行时执行代码回归，**没有**使用用户桌面 LibreOffice 替代文档技能完成新 DOCX 全页视觉验收；DOCX 文本/结构通过不能替代新摘要布局的 Word 视觉门禁。旧双格式完整页图证据仍有效，但不覆盖这次新增长摘要。G8 仍不整体完成。

## 2026-10-01 G8 完成审计

补齐上一节唯一未完成门禁：重新运行 `test_render_summary_omission_counts_are_visible_in_pdf_and_word`，真实 ReportRuntime/WeasyPrint/pandoc 生成 PDF 与 DOCX，**1 passed**。随后用 Poppler 渲染 PDF、用文档技能 `render_docx.py` 和 LibreOffice 渲染 DOCX；两个格式各 3 页，共 6 页均逐页实际查看。省略数量、完整登记提示、长中文名、稳定编号、待复核/未绑定状态和在线定位均可读，未发现裁切、重叠、缺字、表格破损或页眉页脚冲突；DOCX 的结构化表格来源条目在第 2～3 页自然续排。

按 B8 原始门禁复核：首次出现顺序与同源复用、正文/表格/图表统一附录、失效状态、无凭据在线定位、B6 同快照联合渲染、来源关闭配置和无来源旧报告均已有直接测试；真实新/历史 revision 的 Markdown、trace index、PDF、Word 一致性由联合导出样本证明。前端来源校验、面板与在线定位定向 **28 passed**，相关 Python 文件 Ruff 与 `git diff --check` 通过。没有重复完整测试。

G8 结论：实施 1～5、双格式文本/结构/链接门禁和实际分页视觉验收均完成，B8 完成。当前会话仍没有 bundled workspace dependency loader，因此 DOCX 使用项目 `.venv` 与系统 LibreOffice 渲染；这项环境差异已披露，不等同于 Microsoft Word GUI 认证，也不构成本计划功能门禁缺口。
