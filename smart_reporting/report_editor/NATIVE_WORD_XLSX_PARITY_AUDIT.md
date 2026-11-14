# Word / XLSX 固定 GenOffice 功能对齐审计

> 2026-11-13 状态更正：本文原审计及按日期增补为历史记录，不能直接作为当前全缺清单。Word 普通／多级列表库及设置编号值、XLSX 推荐图表／多图选择／限定拖动缩放已在专项范围交付；PDF 书签／Bates／四项属性与 PPTX 四种视图／拼写翻译预设亦不再列为全缺。当前范围限制和专项证据见[四格式已交付子能力与剩余边界](NATIVE_GENOFFICE_FOUR_FORMAT_SCOPE.md#已交付子能力与剩余边界2026-11-13-更正)，剩余 Word／XLSX 功能见[当前缺口索引](NATIVE_WORD_XLSX_CURRENT_GAPS.md)。保留原始失败与验收边界，不将历史结论改称本次整包通过。

## 2026-11-11 最新 AI 优先项补记

后续增量已接入 Word 显式审阅目标的 AI 回复、线程状态与简单修订决策，复用真实预览/采纳、SSE 中文进度和带图标中文入口。真实 provider 经输出合同修复后三项候选及实际 ZIP 核验通过，首轮失败保留；仍存在重复工具提案被拒的效率问题。完整前端 types 与 XLSX 体积预算当前失败，不冒称全构建通过。详见 [审阅写操作验收](NATIVE_WORD_AI_REVIEW_WRITE_ACCEPTANCE.md)。

Word 新增 Agno `read_comments` / `read_revisions`，分别核验正文、批注、修订覆盖与真实引用，沿用 SSE 中文进度。选区不读取未锚定全文批注，单格不扩张至块级修订，复杂修订明确限制。核查并修复既有 Word 编辑 toolkit 未接生产工厂的问题，开放能力进入真实预览/显式采纳链，保留 PDF 旧路径；已有选表结构草稿先保存重开。

实际 DOCX/Agno/任务服务及前端定向测试通过。真实 provider 两问内容、作者、审阅身份与各自2/2覆盖正确，但首轮严格结果仍 false：无正文证据的误告警随后修复；模型额外提供未读正文引用仍被服务端丢弃并告警。未重跑或改写真实探针，不标完整provider通过。完整 AI 审阅写工具、多步复杂操作和本轮生产浏览器验收仍开放。详见 [专项验收](NATIVE_WORD_AI_REVIEW_ACCEPTANCE.md)。

审计日期：2026-11-06。审计工作区：`/home/junge/pros/smart_reporting`，分支 `feat/native-word-excel-followup`。本文件是只读代码审计产物，不是执行验收通过记录。

**结论：完整功能对齐尚未达成。disabled、显式 unavailable、tab/按钮存在、manifest 哈希通过都不构成功能完成。未核验的命令和宿主差异不可计完成；不同 host 中不适用的功能必须经用户明确确认才能从目标排除。不得据当前信息给完成百分比。**

## 1. 固定来源与证据边界

- 固定完整源根（下文 `U`）：`/home/junge/pros/genoffice-source-full`。本次读取 `git rev-parse HEAD` 精确得到 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`git status --short` 无输出。完整固定源确实可读，无需远程替代或猜测。
- 当前前端根（下文 `F`）：`/home/junge/pros/smart_reporting/smart_reporting/report_editor/frontend/src`。
- 当前 DOCX engine 根（下文 `D`）：`/home/junge/pros/smart_reporting/smart_reporting/reporting/slides_engine`。
- 当前 workbook engine 根（下文 `X`）：`/home/junge/pros/smart_reporting/smart_reporting/reporting/workbook_engine`。
- `F/vendor/genoffice-docs/SOURCE.md:3` 固定 ref，`:4` 指向完整本地源码；`:8-16` 明确桌面启动、IPC、上游 AI、系统字体扫描不在依赖闭包；`:19-27` 明确 Home/Insert 是裁剪适配。实际 vendor 的 `apps/docs/src/renderer/components/` 仅见 `HeaderFooterArea.tsx`、`PaginationPreview.tsx`、`icons.tsx`，**未含原 Ribbon.tsx、ribbon-tabs.tsx 或各 ribbon-*-tab.tsx**。因此不能声称本地 vendor 已包含完整 Word Ribbon。原文件在 U 中可读，以下 inventory 基于 U，非历史审计文件。
- `F/workbook-vendor/SOURCE.md:6-10` 明确未集成桌面 external-link、formula-settle export、printing，排除 `ExcelShell.tsx`、dispatcher 和桌面 App。`:17-24` 给出 rotation 原生 callback 契约，`:26-37` 描述 Find/Replace 和 custom number-format 适配。`X/SOURCE.md:2-12` 明确现有引擎是 sheets-web 子集及三项 backport，不是完整最新 xlsx-gateway。
- 当前工作区已有未提交实现。本次以当前可读代码为准；未运行测试和 GUI，不把测试文件存在当成本轮执行通过。`NATIVE_RIBBON_COMMAND_AUDIT.md` 未作为当前真相来源。
- 行号是本次快照定位，后续并行修改可能移动；callback 名称作为稳定补充定位。本文 `U/F/D/X` 均严格指上述绝对路径，不是另一份检出。

## 2. 完整成功标准（root 追踪任务必须采用）

每个固定源 tab/group/命令、gallery 选项、对话框选项、上下文命令必须有一条追踪项，并满足：

1. **来源核验**：固定 ref 文件及 callback 可定位；UI 中动态 gallery、contextual tab、selection state、keyboard/context-menu 入口也有对应。不能仅复制最上层标签。
2. **用户可执行**：在正确选区/对象/权限下可完成实际动作；无权限/无选区时正确禁用是边界行为，不能用永久禁用交付该功能。
3. **语义和状态一致**：当前值、继承值、混合状态、选区变化、焦点移动和只读/保存中状态准确；undo/redo 能恢复文档及命令状态。
4. **持久化命令完整闭环**：UI → 授权且含身份校验的操作 → 草稿恢复 → 服务端写回 → 新修订下载 → 独立文件读取 → 重开渲染，均保持目标语义；非目标 parts/关系/资源保留，旧修订字节不变。视图/导航类命令则验实际 UI 状态和适当的恢复边界，不人为写入文档内容。
5. **失败与恢复真实**：stale source/object/section/sheet identity、网络中断、重试幂等、保存响应丢失、恢复后再次保存均不丢草稿、不越权、不重复生成修订。
6. **发布非阻断**：遵守 `/home/junge/pros/smart_reporting/AGENTS.md`。验收失败不得冒称通过；已生成且身份可读取的 PDF/Word 要保留并签发链接，同时给具体问题。新增签发链故障点登记相应非阻断故障注入契约。
7. **host 等效或用户批准排除**：桌面文件/打印/剪贴板/窗口/系统字体/插件能力以真实 web 等效交付并验收；若无法等效，仍为缺口，只有用户确认才能缩减目标。

状态词：**已有代码闭环** = 本轮静态取证见 UI/操作/持久化链，不代表本轮独立验收通过；**局部** = 仅受限对象/选项或缺恢复/回读/UI；**未实现** = 当前适配未见可执行闭环；**来源未核验** = 尚未展开对应外部宿主/菜单实现，不能认为不存在；**进行中** = 明确其他 agent/root 正负责，不能预记完成。

阶段建议：P0 来源/状态/持久化边界和现有功能验收；P1 高频编辑、文件剪贴板、格式和视图；P2 结构/审阅/数据处理；P3 插件、复杂对象、邮件合并和外部集成。优先级只影响顺序，不削减完整目标。

## 3. Word 逐 tab 权威命令族 inventory

固定 tab 定义：`U/apps/docs/src/renderer/components/Ribbon.tsx:548`（Mac 文件动作在 native menu，其他 host 含 File）、`:564` 表格、`:622` 图片、`:623` 形状、`:673` 页眉页脚；当前 tab：`F/docx-ribbon.ts:16-39`。

| Tab / group | 固定源命令、galleries/options/context（来源） | 当前事实与缺口 | 可复用 / 需补读写 | 阶段 |
|---|---|---|---|---|
| File / 标题栏 / 转换 | File tab 依 host；原 Ribbon `onSave/onSaveAs/onOpen` 等宿主 props、转换 PDF/HTML/Markdown/images；Home Convert `Ribbon.tsx:3583`，`ConvertFormat` 定义 `:5`。文件原生菜单、打印、系统对话框需继续追 App/menu callback。 | File 在 `F/docx-ribbon.ts:27` 为待迁移按钮；报告 shell 有保存/导出但尚不能认定与所有源文件命令等效。**局部；菜单/Print 完整选项来源未核验**。 | 复用 native API/修订下载；补打开/另存为/重命名/转换对应语义与打印入口、范围、分页验证。不能将浏览器下载直接等同全部 Save As/Print。 | P0/P1 |
| Home / AI 与转换 | AI 入口、总结、润色（全篇/选区）、排版整理、思维导图，`Ribbon.tsx:3442-3578`，callbacks `onToggleAi/onAiPreset`；Convert 见上一项。 | 当前 `DocxHomeSource` 不是完整此 group；**未见源 AI presets 闭环**。需当前报告模型授权接 Agno，不能引入上游桌面 provider 配置或擅自改模型。 | 复用报告 native AI proposal/accept/reject 和身份协议；生成候选后显式采纳、可撤销、权限/选区绑定。思维导图/图输出守 Matplotlib 静态图要求。 | P1/P2 |
| Home / Clipboard | Paste split + paste modes、Cut、Copy、Format Painter（含格式捕获/应用）；`Ribbon.tsx:3611`，`applyPainterFormat:496`，painter marks/paragraph attrs `:451-478`。 | **已闭环**（clipboard 线）：paste 分体（source/merge/text，富文本拒绝并说明、纯文本协议校验）、cut/copy（execCommand）、格式刷（单击/双击锁定/Esc/¶ 标记规则/协议内属性白名单）；23+18 测试与 6 文件 124 项回归。**图片粘贴已闭环**（`insertParagraphImage`：png/jpeg 魔数/8MB/尺寸校验、media part+关系+drawing inline 经既有 `embedImageMedia`、12 pytest lxml 独立回读 media 字节一致；表格内/浮动/裁剪/替换诚实拒绝）。**未达**：选择性粘贴对话框、默认粘贴设置、词粒度刷、⇧⌘C/V、HTML 精确映射（协议只支持整段统一格式）。 | 复用 ProseMirror clipboard/transaction；剩余项需协议扩展（局部样式/图片资源）或对话框实现。 | P1（主链已完成） |
| Home / Font | 系统/文档字体、字号及增减、B/I/U/strike、下划线选项、上下标、字体颜色 palette、highlight named colors/no-color、大小写/CJK 半全角、清格式、字体更多选项；`Ribbon.tsx:3714-4110`，highlights `:773`。 | `F/docx-home-source.tsx:77-95` 基础控件；`F/docx-operations.ts:118-137,271-281` 仅整段一致 run 格式及上下标，局部同段混合样式拒绝；字体/字号/颜色清除的历史限制已由下述2026-11-09前置协议更新覆盖。**局部**。**段落整体高亮已闭环**（`docx-highlight.ts` 源15色+none，formatParagraph 协议；浏览器黄→保存→下载→python-docx 回读→重开画布黄色、调色板直点与撤销验证，见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md 2026-11-06 第二批）；**局部字符格式已闭环（2026-11-09）**：开始页加粗/倾斜/下划线/删除线/字体/字号/颜色在有选区时只作用于选中文字（光标折叠仍整段），文字不变的段落按 UTF-16 区间差分为最小变化的新协议 `formatRange`（每段变化键与新值相同；整段单一区间仍为 formatParagraph），桥接按区间拆分 run 并合并格式、区间外 run 原样保留，草稿回放一致；含已有局部格式的段落亦可局部加/去粗体等。真实浏览器验收（`DOCX_INSERT_CASE=format`：选中两字加粗 + 另一段整段倾斜，python-docx 回读 run 切分）通过。**大小写与半／全角已接通（2026-11-09）**：原样复用固定源 case-transform 七种转换，限定同一来源正文段落内的选中文字、整段格式统一且无链接／内联对象；变长转换、撤销重做、草稿恢复、下载 python-docx 回读和修订2重开通过，见 NATIVE_WORD_XLSX_CASE_SPLIT_ACCEPTANCE.md。**清除格式前置协议已补齐（2026-11-09）**：formatRange/formatParagraph 的 fontFamily/fontSize/color 支持 null，表示移除直接属性并恢复继承；草稿回放移除空样式标记，桥接同步清除 rawRPr 字体/主题字体、颜色/主题颜色、字号及复杂文字字号，区间外属性保留；80前端和9桥接定向测试通过。完整清除格式按钮仍未接通，需继续覆盖段落样式与直接段落属性。局部高亮（含none）及上下标（含baseline）已在2026-11-10完成单段UTF-16区间、撤销/草稿和真实DOCX保存重开验证（见末尾本批证据）。仍拒：同段同时修改文字与局部格式（请先保存）、表格单元格内格式。 | 复用 marks/extensions、DOCX engine run 生成/patch；需局部 run anchor/offset、保持已有 rPr/links、完整 palettes和清除语义。系统字体见跨格式要求。 | P0/P1 |
| Home / Paragraph | bullets/numbering/multilevel galleries、级别、起始编号/继续/重启，indent、alignment/RTL、line-spacing 1/1.15/1.5/2/2.5/3、段前后、更多行距、底纹/边框/显示格式等固定原 group；`Ribbon.tsx:4111-4455`，`ribbon-tabs.tsx:setParaAttrs/toggleParaSpace`。 | `F/docx-home-source.tsx:97-122` 有基本列表、可用原编号级别、0.5英寸左缩进、对齐、倍数行距和段前后；`F/docx-operations.ts:202-250` 有操作；**精确段前后 0–720pt/0.05pt 已闭环**（docx-spacing）；**段落底纹已闭环**（`docx-shading.ts` 源 20 色板+无颜色，`setParagraphShading` 最小 pPr 补丁，4+3 测试与浏览器保存/回读/重开实证，见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md）。**段落边框已闭环**（`docx-borders.ts` 源 Home 六位置 b/t/l/r/tblr/无框线、单实线 0.5–3pt+20 色板+自动颜色，`setParagraphBorders` 同段独占批次，桥按 PPR_CHILD_ORDER 有序补丁；源含 between/bar/nil/double/themeColor pBdr 整体拒绝 fail-closed；between 抑制为源显示层装饰由既有 vendor 层承担，写路径不产生 between；6+6 测试与浏览器保存/回读/重开实证）。自定义编号、完整 multilevel、精确/至少行距、自动间距、完整段落 dialog 仍缺。 | 原 definitions/numbering/list-presets 和 engine pPr 可复用；需复杂 numPr/override/起始值、任意负/正左缩进、首行/悬挂、bidi 协议。 | P0/P1/P2 |
| Home / Styles | 固定 gallery、来源 paragraph styles、应用样式时直接格式处理、normal/headings 等；`Ribbon.tsx:4456-4507`，`ribbon-tabs.tsx:184,256,305`。 | `F/docx-styles.ts:8-28,47-108` source paragraph style select；拒绝含编号/heading/复杂显示属性/不完整继承；同段样式与文字/格式不能混存。**局部，普通来源样式有代码闭环**；不是完整 gallery 和 heading 对齐。 | 复用 parsed.styles/docStyleCss；需 heading/list/复杂 display 状态刷新、源 gallery 直接格式处理语义、样式管理（以源实际入口为准）。 | P0/P1 |
| Home / Editing | Find/Replace/Select；`Ribbon.tsx:4508-4544`。 | **Find/Replace 已闭环**（`docx-find-replace.ts` 复用 pinned find.ts 匹配/通配符/正则/展开+search 插件；82 项定向回归；浏览器 Ctrl+F 查 3 处、全部替换仅目标段变化、Ctrl+Z 还原）。Go To 独立导航与 Select 仍缺；protected/页眉页脚不搜索；段落拆分/链接正文/混合 run 单元格替换明确拒绝并给原因。 | 复用 Tiptap/PM 搜索和 selection，不解析 assistant 正文为执行；替换已沿用严格 operation/replay 一致性；Go To/Select 需补独立导航协议。 | P1 |
| Insert / Pages & Tables | Cover gallery/移除、Blank Page、Page Break；table grid/自定义行列 modal；`U/.../ribbon-insert-tab.tsx:678-837`，`ribbon-tabs.tsx:353-397,693-748`。 | **Page Break 已接通代码链（2026-11-08）**：按固定源 `editor/page-break.ts` 语义（段首标记当前段 / 段中拆段后半段承载 `pageBreakBefore`，单次撤销），`F/docx-insert-source.tsx` `insertDocxPageBreak` 拆段时清空后半段 `docxIndex`（固定源 splitBlock 会复制锚点）；新操作 `setParagraphPageBreakBefore`（原 XML 最小补丁，CT_PPr 顺序，非 on/off 源标记拒绝，同段只允许单一分页操作）与 `insertParagraph.pageBreakBefore`，含草稿 replay 校验；python-docx `page_break_before` 独立回读与非目标部件字节保留通过。**局部**：文档开头（固定源写 hardBreak）、表格/嵌套内、带样式/格式的拆分后半段如实拒绝；未做真实 GUI 验收。**Blank Page 已接通代码链（2026-11-08）**：按固定源 `ribbon-tabs.tsx:703 insertBlankPageAt`（一个自成一页的空段落，仅当后面有内容时给后续块加分页，后续块不能承载分页时补分页空段，光标落在空白页），段首/段尾/段中/文档开头均一次事务；桥接允许锚定插入与该段分页补丁同批共存；python-docx 回读通过。**表格插入已接通代码链（2026-11-08）**：按固定源 `ribbon-tabs.tsx:357 insertTableAt` 与原样引入的 `editor/new-table.ts`（整宽 autofit、等分列、单线 0.5pt 边框、单元格垂直居中、单倍行距无段后）；8×10 悬停网格 + “插入表格…”行列表单（原生约束校验）；空段保留在表下、段中拆段、段首前插/段尾后插，表格前后保证段落；编辑器节点携带 `nativeTableInsert` 行列意图并须等于确定性投影，差分为 `insertTable`，桥接以引擎 `generateTableModelXml` 写出；预算与既有表格结构一致（≤100 行、≤30 列、≤1000 格，严于固定源 200×63）。真实 vendored 扩展上验证投影稳定、单次撤销、草稿 replay；python-docx 独立回读表格尺寸/边框/vAlign/段落间距及 styles.xml 字节不变。保存前在新表格内输入的纯文字（多段以换行分隔）随 `insertTable.cells` 写回，按行列+文字重算投影比对（仅忽略投影派生的 `originalFormatting` 快照），python-docx 回读单元格段落/文字/转义通过。**局部**：保存前不能对新表格加格式或改布局（保存后作为来源表格走既有链），表格/嵌套内插入（固定源为嵌套子表）、粘贴表格如实拒绝；未做真实 GUI 验收。**Cover Page 已接通代码链（2026-11-08）**：原样引入固定源 `editor/cover-pages.ts`（预设画廊仅用段落/文字基本格式、文档开头插入并以分页段结束、`_GenOfficeCoverPage` 隐藏书签、插入替换旧封面、删除当前封面）；首段携带预设段落规格意图，保存前可改占位文字（按规格+当前文字重算投影比对），其余格式/结构修改须先保存；`insertCoverPage` 桥接按同一受限规格 schema 校验并生成段落，强制位于文档开头且每批至多一个。真实 vendored 扩展上验证插入/改字/替换/删除/拒绝/replay 与画廊；python-docx 回读对齐/粗体/字号/颜色/上边框/底纹/分页与书签。Word 渲染懒加载块预算 700→710 KiB（画廊进入同步保存守卫）。**真实浏览器验收（2026-11-09，`smoke/docx-insert-gui-smoke.mjs`，Chromium 153 + vite + 真实 Python patch_docx + python-docx/XML 回读，连续两次通过）**：经典封面（含首尾隐藏书签与分页结束段）、段中分页符、文档末尾空白页、在空白页空段插入 2×3 表格并于首格输入，均按序落盘；保存操作为 insertCoverPage/insertParagraph/insertTable/insertParagraph/replaceParagraph。**续验收（`DOCX_INSERT_CASE=followup`，多修订往返）**：修订 2 先插经典封面再替换为色带封面并改标题占位为“年度经营报告”，同批插入 1×2 表格，回读只剩一个封面书签对且无旧封面文字；重开修订 2 后在保存表格空首格输入并删除封面，修订 3 回读为正文 + `后填` 单元格、无封面书签。此轮验收发现并修复两处产品缺陷：①已保存封面的书签段因隐藏书签被判只读，无法删除/替换——桥接新增 `deletable`（仅含 `_GenOfficeCoverPage(End)` 书签的简单段可整段 `deleteParagraph`，仍不可改写），前端删除判定读 `deletable`；②保存表格的空单元格（无 text 子节点）输入被守卫以“暂不支持修改单元格结构或样式”回滚——单元格差分改为段落结构/属性不变时，有文字段保持 run 格式、空段只允许新增普通文字（无格式或全空 textStyle）。 | 复用 insertBlankPageAt/insertPageBreakAt/insertTableAt 和 generated blocks；需服务端新结构/分页/封面协议、selection anchor、草稿 replay。 | P1/P2 |
| Insert / Illustrations & Text | 图片、chart modal（series/category/type）、shape gallery（含 lines）、text-box presets/绘制、WordArt gallery、drop cap、field gallery；`ribbon-insert-tab.tsx:290-429,838-1088`，`ribbon-tabs.tsx:399,473,543,648`。 | **本地图片插入已接通（2026-11-09）**：浏览器文件选择器、PNG/JPEG ≤8MB、620px 等比缩放，复用图片粘贴的 insertParagraphImage；冻结异步插入目标、保存锁/销毁检查、单次撤销、草稿刷新恢复、真实 patch_docx 下载及 python-docx 回读和重开均通过，见 `NATIVE_WORD_XLSX_PICTURE_FLASH_ACCEPTANCE.md`。**局部**：GIF、浮动/裁剪/替换以及 chart/shape/text-box/WordArt/drop cap/field 仍未完成。 | 已有 docProtected/textbox/image/shape extensions + docx-engine；需图片资源关系/geometry、chart 静态图资源写回、drawing/textbox/field 安全生成与读回，禁止新 Plotly。 | P2/P3 |
| Insert / Links | Insert/edit/remove hyperlink、bookmark 新增/删除/跳转、cross-reference；`ribbon-insert-tab.tsx:144,248,496,1089-1123`。 | `F/docx-insert-source.tsx:196-213` 超链接有回调；`F/docx-operations.ts:64-116,253-269,325` 安全 URL + UTF-16 boundary +简单段内 link patch/replay。tooltip/plain/复杂内联、已有链接段落文字改动受限；bookmark/cross-ref disabled。**超链接局部，其余未实现**。 | 复用 safeDocxLink/原关系 metadata；补书签/ref字段、局部编辑保持关系、导航与外链安全。不能放宽为任意 scheme。 | P0/P1/P2 |
| Insert / Comments / HF / Symbols | 新批注；header/footer galleries及编辑/移除、页码位置/格式/移除；50 symbols、equation gallery；`ribbon-insert-tab.tsx:1125-1339`。 | `F/docx-insert-source.tsx:222-285` 仅 symbol 插入有可执行文字操作；comments/HF/equation disabled。**Symbols 有代码闭环，其余未实现**。 | 字符复用现有文字操作；comments/notes/HF/equation需专用 read/write/replay，不能当正文字符串。 | P1/P2 |
| Draw | select/pen/highlighter/eraser、笔预设选择/宽度/颜色/透明度/删除/新增、clear all；`ribbon-tabs.tsx:1701-1947`，callbacks `onTool/onPresets/onActivate/onClearAll`。 | `F/docx-ribbon.ts:28` 占位，未见 ink annotation 写回。**未实现**。 | 源 ink model/renderer 可考察复用；需 annotation coordinate/page anchoring、持久化、undo、擦除/清空与预设状态；文字 highlight 不等于 Draw highlighter。 | P3 |
| Design | Theme presets、font/color theme galleries、page color/no-color、水印预设/自定义/移除、page-border gallery/none；`ribbon-design-tab.tsx:29,92,110,197,222-508`，`onThemeFonts/onThemeColors/onPageColor/onWatermark/onPageBorderAll`。 | 2026-11-12：页面颜色已接通（`NATIVE_WORD_PAGE_COLOR_ACCEPTANCE.md`）；水印预设 / 自定义文字水印 / 删除水印已接通（`NATIVE_WORD_WATERMARK_ACCEPTANCE.md`）。2026-11-13：页面边框（方框/无/对话框，整篇文档或本节）已接通（`NATIVE_WORD_PAGE_BORDERS_ACCEPTANCE.md`）。主题、主题字体与颜色、图片水印仍**未实现**。 | 复用 engine theme/section/page metadata，需写回对应 parts、所有节应用范围、继承/颜色 palette 与草稿恢复。 | P2 |
| Layout / Page setup | margins gallery/custom/mirrored、portrait/landscape、paper sizes/custom/全部节、columns、breaks next/continuous/even/odd、active section；`ribbon-layout-tab.tsx:139-152,338-570`。 | `F/docx-layout-source.tsx:29-52` 有三种统一页边距、四边值、纸张/自定义、方向、1-3栏；`F/docx-main.tsx:47-54,146-157` 仅尾节 anchor；`F/docx-operations.ts:10-33` strict section patch。**多节页面设置与分节符已闭环（2026-11-09）**：桥接返回全部节（身份、设置、块范围、起始方式），编辑器按光标所在顶层块定位当前节（布局页显示“第 n 节，共 m 节”），页面设置作用于当前节——尾节沿用 saveDocx section，非尾节以引擎 `applySectionSettings` 改写其分节段 sectPr；按固定源 `App.tsx insertSectionBreak` 新增 `insertSectionBreak`（下一页/连续/偶数页/奇数页）：锚块后插入携带该节 sectPr 副本的分节段，原终止 sectPr 写入所选起始方式（尾节经 sectionStartType），编辑器以只读 docProtected 呈现并可撤销/草稿回放；每节每批至多一个分节符，分节与该节页面设置须分批保存（副本取原 sectPr），保存后回读节数核验。真实浏览器验收（`DOCX_INSERT_CASE=sections`：插入连续分节符→重开两节→第 1 节窄边距、第 2 节横向，python-docx 回读）通过。**局部**：镜像边距、纸型全集、“应用于：整篇/插入点之后”、删除分节符仍缺。 | 复用 readSections/readSectionSettings/saveDocx；补 section insert/delete/active selection、mirrorMargins、custom gallery 等。当前 preview `colFlow=null,colMode=none`（docx-main:121），分栏显示也须独立验。 | P0/P1/P2 |
| Layout / Paragraph & Arrange | left/right indent、段前后数值、position 3×3/inline、wrap options；`ribbon-layout-tab.tsx:200-235,255-335,571-731`。 | `F/docx-ribbon.ts:153-281` 右缩进及段前后 twip输入有 capture/stale guard；左缩进仍受720 twip倍数限制；arrange 占位。**局部**。 | 复用段落 operations；任意左缩进、首行/悬挂、对象定位/环绕需新协议。 | P0/P1/P2 |
| References | Zotero add/edit citation/bibliography/refresh/preferences/remove codes；TOC insert/update（真实页码）、footnote/endnote、source类型/元数据/add citation/bibliography、caption Figure/Table/Equation +编号、index insert/mark；`ribbon-references-tab.tsx:244,351-360,510-719`。 | **脚注/尾注基础增删改已接通并验收（2026-11-10）**：来源entry/ref哈希、服务端id、原生undo、草稿恢复及四修订真实DOCX保存重开；复杂note文本只读，安全删除独立判断。未建模正文引用/非标准notes关系仍限制；同段正文与insert/deleteNote混改正在下一批实现。TOC/citation/bibliography/caption/index等其余功能仍未实现。 | engine已有 generateTocFieldXml/generateCaptionXml/generateIndexFieldXml/citationText/bibliographyLine；需严格字段/notes/source metadata读写与独立页码验收；Zotero IPC须web授权等效或用户批准排除。 | P2/P3 |
| Mailings | **固定实际源不是当前占位的整套 Office 邮件菜单**：Mail merge panel、选择数据源、插入 merge field、记录前后预览、合并；`ribbon-mailings-tab.tsx:20-35,66-136`，callbacks `onPickSource/onInsertField/onMerge`。 | `F/docx-ribbon.ts:32` 大量占位标签比源不同，不能当权威 inventory。**未实现**。 | 复用源 mail-merge model/生成机制需进一步追；补数据源授权/字段映射/预览、合并产物修订与下载。envelope/labels 是否源其他入口须核验，不能擅自添加为已核验范围。 | P3 |
| Review | proofing/editor/spellcheck、translation langs/AI、new/delete current/all/resolved comments、previous/next/show/comments AI；track changes、display modes、insert/delete/format/author filters、balloons/options、accept/reject next/all/shown/selection/author、prev/next/review-pane、AI revisions、compare/protect；`ribbon-tabs.tsx:774-821,875-1353`。 | `F/docx-ribbon.ts:33` 占位；既有 protected/revision 渲染不等于可审阅。**未实现**。 | 复用 parsed comments/revisions/protection 和 engine APIs；需 author/ids/timestamps/relationships、修订接受拒绝与保留、compare结果、保护状态/密码合法操作、AI候选授权。 | P2/P3 |
| View | print/web/outline、read mode、zoom/fit/page width/full page、appearance AI/dark、ruler/grid/nav、new tab/split/switch等；`ribbon-tabs.tsx:1362-1694`。 | 已有分页预览 `F/docx-main.tsx:117-128`；**缩放已闭环**（`docx-view.ts` 10–500%、±10、100%、页宽/整页、手动对话框；浏览器 110%/142%/125% 三方式验证不产生草稿修改；缩放不持久化为已登记缺口）。web/outline/read/grid/dark/nav/ruler/window 仍 pending 禁用并给原因。 | 复用 doc-zoom/editor-scroll/PaginationPreview；视图类验实际尺寸/viewport/selection/resize，不必制造正文写回。原native window/tab以web等效或用户确认排除。 | P1 |
| Table Design context | no style +5 presets +来源表格样式、first/last row/column +banding six toggles、shading palette/no-color、last border +12 border modes、8 styles、width4/8/12/18/24、color；`Ribbon.tsx:567-621,681-717,2891-3103`。 | `F/docx-ribbon.ts:44-67` 标签覆盖较多但无真实格式写回；`docx-operations.ts:177-187` 既有表格仅文字改动，拒绝属性/样式变化。**未实现**。 | 复用上游 table commands/engine cell/table properties；补 source style tblLook继承和per-edge border/cell shading patch，不用整个表重建丢失复杂结构。 | P2 |
| Table Layout context | select cell/col/row/table、gridlines/properties；delete table/cell/row/col +shift dialogs；insert rows/cols/cells；merge/split cells/table；row height/col width/autofit contents/window/fixed/distribute；9 align/directions/margins；repeat headers；`Ribbon.tsx:3106-3437`。 | `F/docx-ribbon.ts:68-105` 只是全清单；仅连接 `docx-tables`允许的简单表增删行列和删除表等窄命令（须以 TABLE_ACTIONS/allowed 实际映射逐项验），**同表多步结构修改已闭环（2026-11-09）**：新协议 `restructureTable`（`steps` 有序行列增删，每步坐标基于上一步结果，≤50 步；`texts` 按最终坐标的纯文字修改），编辑器意图 `nativeTableStructure: {steps}` 按步确定性投影，结构前后的单元格文字修改随单元格迁移；同表格式/段落结构修改仍拒绝。桥接 `editTableStructureSteps` 一次组合生成，幸存源单元格保持原 XML，文字经与 replaceCellText 相同的补丁写入并回读核验；旧单步草稿仍可回放。**真实浏览器验收（`smoke/docx-table-smoke.mjs`）**：表 0 插入行→刷新恢复草稿→右侧插入列并在新单元格输入，其余三表单步，保存经真实 patch_docx，python-docx 回读矩阵/列宽/源段落 c14n 与非目标部件字节一致。**局部**：合并/拆分单元格、表格属性与单元格格式仍未接入。 | 已有 strict table anchor/projectDocxTable/bridge patch；补合并/嵌套/网格跨度、cell styles、属性尺寸、复杂表增删与replay。UI selection纯命令可先复用。 | P0/P2 |
| Picture Format context | adjust replace/background/color/transparency、位置/环绕/前后层/rotate/crop、height/width/aspect/reset；图片框选与普通图片路径不同；`Ribbon.tsx:2687-2888`。 | `F/docx-ribbon.ts:37` pending。**未实现**；source完整具体菜单某些 options需再细化callback，不能计不存在。 | 上游 imagePatch/embedded resources/尺寸可复用；需受信上传、media关系、同一对象锚点、裁剪/透明度/去背景真实服务与无关资源保留。 | P2/P3 |
| Shape Format context | shape presets/fill/outline颜色/粗细/effects、edit text、arrange front/forward/backward/back、position/wrap/rotate、size；`Ribbon.tsx:625-648,2537-2686`。 | `F/docx-ribbon.ts:38` pending。**未实现**。 | 复用 protected/textbox shape model，补geometry/style/文字的严格patch及上下文选择。 | P2/P3 |
| Header/Footer context | edit/remove header/footer、page-number位置/here/NUMPAGES/format/remove、DATE/TIME/picture、goto other/link previous、first/even-odd、header/footer distance、close；`ribbon-hf-tab.tsx:32-48,85-289`。 | **页眉/页脚编辑已接线并有桥回归**：`docx-hf-source.tsx` 进入嵌套 hf-editor、header/footer + default/first/even 变体、首页不同/奇偶页不同、PAGE/NUMPAGES/SECTIONPAGES 插入、位置与删除页码；`docx-hf.ts` 严格 setHeaderFooter diff/replay；`docx-main.tsx` 接 controller，bridge `edit-docx.ts` 已写回部件/字段并保留非目标部件。pytest header/footer 7 项通过、`docx-hf.test.ts` 覆盖操作/replay。保存前未失焦内容 flush、保存锁/失败解锁、部件状态投影和布局/HF 组合恢复已有定向回归（面板 9、恢复 17、会话 8 项）；面板测试使用 mock vendor handle，真实浏览器保存/回读/重开仍待验收。**未达**：日期/时间/图片字段、link-to-previous/goto other、完整 header/footer gallery/距离交互与真实分页视觉仍未全验。 | 复用 parsed.hfParts/readSections/header-footer engine；补每节/first/even/previous links 与 field关系写回/恢复、实际分页回读。 | P2 |

## 4. XLSX 逐 tab 权威命令族 inventory

固定源 `U/apps/sheets/src/renderer/ExcelShell.tsx:133-148` 有7常规 tab及 **Chart Design、Table Design、Shape Format、Picture Format 四个 contextual tab**。当前 `F/workbook-ribbon.ts:8-16,111` 只包含7常规+类型中的Chart Design；不能将缺失的另外三个 contextual tab遗忘。

| Tab / group | 固定源命令、galleries/options/context（来源） | 当前事实与缺口 | 可复用 / 需补读写 | 阶段 |
|---|---|---|---|---|
| File / Title / Print / status | 标题保存、AI命名、undo/redo、native file菜单/打印、normal/page-break preview、zoom slider；`ExcelShell.tsx:906-953,1110-1176`。原 File不在7 tab中，必须追 App/menu不能误认为无文件功能。 | 当前报告 shell保存/新修订下载有链（workbook-main:354-387）；缺完整文件/打印等效；**局部，native菜单/打印完整选项来源未核验**。 | native API和下载复用；formula-settle export/打印被SOURCE明确排除，补真实web打印/PDF/范围布局与缓存一致性；undo需见后节。 | P0/P1 |
| Home / AI | assistant entry及AI动作；`ExcelShell.tsx:3535` 的 `onAiRun` callbacks。 | `F/workbook-main.ts:50,61,295-352` 旧工作簿AI proposal/accept/reject/undo存在，但 native 模式form隐藏且inert；不能称native AI对齐。**局部/Native缺失**。 | 复用当前报告模型Agno与 native scoped proposal，无新provider；补源preset语义及选区上下文、审阅采纳撤销。 | P1/P2 |
| Home / Clipboard | paste +value/formula/format/col-width/besides-border、cut/copy、painter once/locked；`ExcelShell.tsx:3606-3653`，`ribbon-actions.ts:422-475`。 | **剪切/复制/粘贴及 5 种选择性粘贴已接通代码链（2026-11-08）**：`F/workbook-clipboard.ts` 按固定源 `ribbon-actions.ts:422-445` 映射到 `univer.command.copy/cut/paste` 与 `sheet.command.paste-value/formula/format/col-width/besides-border`（8 个 id 已在 pinned 0.25.1 包中核验存在）；复制为只读安全命令，剪切/粘贴需可编辑态；写入走 `sheet.mutation.*` 并由既有值/样式/合并/列宽差分写回。**局部**：仅有功能区状态/分发单测，**未做真实浏览器剪贴板 GUI 验收**（系统剪贴板权限、跨 sheet、外部来源粘贴、富文本/图片），**格式刷已接通代码链（2026-11-08）**：`F/workbook-format-painter.ts` 移植固定源 `format-painter.ts`（单击刷一次、双击锁定、再次单击或 Esc 取消，状态镜像为 aria-pressed），服务经 pinned preset 转出导入；保存开始时解除格式刷；刷出的样式经 set-range-values 由既有样式差分写回。转换表、真实 Univer 命令服务分发/Esc 快捷键注册、单/双击区分有测试；painter 服务本身（sheets-ui 渲染层）未在测试中实例化。 **真实浏览器验收（2026-11-09，`smoke/workbook-ribbon-gui-smoke.mjs`，Chromium 153 + vite + 真实 Python patch_office 保存 + openpyxl 回读）**：缩进、格式刷（单次）、行高/列宽对话框、自动调整行高、复制→粘贴均落盘正确。该验收发现并修复三处单测未覆盖的缺陷：①普通粘贴不带参数时 Univer 0.25.1 粘贴权限检查读取 `params.value` 抛错，现传 `{}`；②格式刷默认钩子在 Univer Steady 阶段（首次渲染后 3 秒）才安装，此前武装会“看似激活却刷不出格式”，现未就绪时禁用并提示；③`installFormatPainter` 在挂载时 painter 服务尚未注册而静默失败（Esc 取消与状态镜像从未安装），现等 Steady 后安装。列宽按网格整像素取整（12.5→12.57 字符）。补充验收（同日）：锁定格式刷（双击）连续应用到 A3/B3 并以 Esc 取消、外部 HTML 富文本粘贴（粗体与数值）、新增工作表后跨表粘贴均落盘正确；跨表场景另发现并修复引擎缺陷：openpyxl 产出的工作簿把 `xmlns:r` 声明在各 `<sheet>` 上，引擎新增 `<sheet>` 未自带声明导致整本工作簿无法读取，现新增元素自带声明（Python 回归在旧代码上失败）。仍未覆盖：图片粘贴。 | P1 |
| Home / Font | editable字体menu、字号/steps、B/I/U/double/strike/sup/sub、font auto/color、fill none/color、完整边框gallery和线色；`ExcelShell.tsx:3655-3822`，`ribbon-actions.ts:1541-1638,1794-1868,2239`。 | 基础B/I/U、字体/字号/颜色、all borders、**双下划线与删除线已闭环**（`workbook-font.ts` 官方 setValue 样式 patch，clear underline 不误清 strike；浏览器应用→保存→openpyxl 回读 strike/double、无边框伪差异）；格式状态 mixed/unavailable 投影已实现（`workbook-format.ts`）。上下标已闭环（2026-11-11，引擎 `vertAlign` 已在 schema 中，功能区接通，见 NATIVE_XLSX_SYMBOL_VERTALIGN_ACCEPTANCE.md）；auto色/完整边框gallery/theme gallery仍缺。**局部**。 | 复用 Univer style API +style-map +applyCellEdits；补 auto/no-fill/全边框模式、字体动态来源、引擎 vertAlign 字段（需授权引擎改动）。 | P0/P1 |
| Home / Alignment | top/mid/bottom、wrap、6 rotations、align、±indent、merge center/cells/across/unmerge；`ExcelShell.tsx:3823-3928`，`ribbon-actions.ts:1639-1790,2074`。 | `F/workbook-ribbon.ts` 有对齐/合并/wrap/rotation代码；inherit rotation不完整源sheet只读。**±缩进已闭环（2026-11-08）**：按固定源 `selection-format.ts` 一级=8px `pd.l`、`ribbon-actions.ts:1672` 逐格相对 ±1（0–250、≤10000 格），`style-map.ts` 读写 `alignment@indent`（清零写默认 2px 以区分显式清除与未触碰），引擎 `indentReadOnlyReason` 对行/列/默认/父样式/禁用对齐继承禁用；真实 Univer 加载→命令→回读差分→引擎写回→openpyxl `alignment.indent` 独立回读用例通过。仍**局部**：缩进按钮无 0/250 边界禁用态，未做真实 GUI 验收。 | 复用 Univer signed tr（degree/`v`）与merge ops；补row/column/default/named-XF继承、multi-range selectedstate与undo。 | P0/P1 |
| Home / Number | NumberFormatSelect分类/预览/完整dialog、accounting currency、percent/comma、decimal±；`ExcelShell.tsx:3929-3969,4548`。 | 当前0.00/percent/comma、decimal、custom parser/dialog +mixed/inherited/explicit target已实现代码链（workbook-ribbon:238-242，workbook-main:113-123,137-140）；**设置单元格格式▸数字已闭环（2026-11-09）**：原样移植固定源 `numfmt-dialog.ts`（常规/数值/货币/会计专用/日期/时间/百分比/分数/科学记数/文本/自定义，小数位、千位分隔、负数四式、货币符号、日期/时间/分数类型，格式代码⇄选项往返识别，实时示例）与 `FormatCellsDialog.tsx` 数字页，打开时冻结选区，生成的格式代码经与自定义数字格式相同的校验、预算与写入链（只改显示格式，值与公式不变）。真实浏览器验收（`WORKBOOK_RIBBON_CASE=numfmt`：C3 货币 ¥、负数括号，openpyxl 回读 number_format 与原值）通过。设置单元格格式的对齐/字体/边框/填充/保护页仍未接入。formula派生n隔离在main:170-202。**局部**。 | 复用numfmt、source theme、style-map/strict edits；独立验日期/货币/会计/自定义/General清除及公式不变，缓存n不得成为用户改格式。 | P0/P1 |
| Home / Styles | CF/rules dialog、format-as-table完整gallery、cell-style gallery；`ExcelShell.tsx:3971-4026`；table palette helper `:1651-1715`。 | `F/workbook-ribbon.ts:243,375-377` disabled。官方Table preset安装不等于XLSX表写回。**未实现**。 | 现有engine有相应模块可复用（需细分公共API vs内部）；补完整read model→projection→diff→operation→readback。 | P2 |
| Home / Cells | full format cells、row/col insert/delete、insert/delete cells shifts、row height/width/autofit/hide/unhide等format dropdown；`ExcelShell.tsx:4028-4104`。 | 窄行列增删可走structuralMutation +applyRowColumnOps。**行高/列宽对话框已闭环（2026-11-08）**：按固定源 `AxisSizeDialog` 与 `ribbon-actions.ts:1400-1423`（文件单位：行=磅、列=字符，支持小数逗号；冻结选区后经 setRowHeightsForced/setColumnWidths 写入网格）；行 1–409 磅（引擎上限，固定源 409.5）、列 1–255 字符（保存差分下限 1 字符），0（隐藏）留给隐藏命令。**同时修复既有缺陷**：从 sheets-web 迁移的加载/回读使用 `width/height/hidden`，Univer 0.25.1 实际键为 `w/h/hd`——此前文件列宽/行高/隐藏行列不显示，网格尺寸/隐藏修改也回读不到；现与固定源 univer-sync.ts 一致，筛选可见性与打印同步改用 `hd`。真实 Univer 加载→设置→回读差分→引擎写回→openpyxl 行高/列宽回读，及文件几何加载/未修改零差分有用例。**自动调整行高/列宽已接通（2026-11-09）**：按固定源 `ribbon-actions.ts:695-712` 与 `autofit-selection.ts`（选区触及的整行/整列）调用官方 `set-row-is-auto-height` / `set-col-auto-width`；行自动高度（ia=1）对文件已设行高的行保存为行高重置（引擎 `applyRowHeights` 新增 `heightPoints: null` 去除 ht/customHeight），列自动宽度写入测得宽度由几何差分保存。行自动调整经真实 Univer→差分→引擎→openpyxl（height None、customHeight False）验证；列自动宽度依赖渲染层测量，仅验证分发与范围。**插入/删除单元格已闭环（2026-11-09）**：按固定源 `insert-delete-cells.ts`/`InsertDeleteCellsDialog.tsx`（整行/整列选区直接执行，其余弹出右移/下移/整行/整列四选一，默认下移），网格执行官方 `sheet.command.insert-range-move-*`/`delete-range-move-*`；Univer 无对应 mutation，故按命令 + 撤销元素记入结构日志（真实 Undo/Redo 认领/恢复，移位期间附带的扩列 mutation 不进行列日志），保存为新引擎操作 `applyCellShift`（本地新增 `cell-shift.ts`，`ShiftSpec.band` 限定移位带：带内单元格记录移动、行元素不动；同表公式、他表限定引用、定义名称、图表系列、批注随带移动；交叉轴范围不完全在带内的引用与整行/列引用保持原样；带内合并单元格平移）。表格、筛选、数据验证、条件格式、超链接、图形/OLE/控件锚点、共享/数组公式组触及移位区域，合并单元格跨带或被删除拆分，非空值被推出边界时引擎拒绝；前端在命令后用同一引擎预演，拒绝即撤销并显示原因。**真实浏览器验收（`WORKBOOK_RIBBON_CASE=cells smoke/workbook-ribbon-gui-smoke.mjs`）**：A1 插入下移、B1 删除左移，经真实 Python patch_office + openpyxl 回读值、粗体、公式 `=A2→=A3` 正确；验收发现并修复既有缺陷：Univer 移动单元格后 `s` 为内联样式对象，`grid/sync.ts` 只按样式 id 解析导致移动后格式被保存为重置。**局部**：带外受影响的范围特性未做逐格重写（按 Excel 多数情形拒绝）。 | 复用 currentOperations:219-248 和geometry helpers；补选区大小/边界/隐藏状态、shift修复formula/range/table/validation等引用。 | P0/P1/P2 |
| Home / Editing | auto fn5、fill上下左右、series/日期或复制当前值选项（dropdown实际选项须逐条接）、sort/filter menus、clear all/formats/contents/comments/hyperlinks、find/replace/goto；`ExcelShell.tsx:4105-4195`；`ribbon-actions.ts:561-676`。 | autofn5、clear-content、简单sort、**Find/Replace 已浏览器验收**（官方 preset 对话框、多表预检、替换后保存回读/Undo/恢复回归通过；见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md）。**填充与定位已闭环（2026-11-09）**：按固定源 `ribbon-actions.ts:561-596`，填充菜单向下/向右走官方 copy-down/copy-right、向上/向左以末行/末列为源走 auto-fill COPY；“序列…”原样移植 `fill-series.ts`（等差/等比/日期/自动填充、预测趋势、步长/终止值，单格+终止值开放延伸）与 `fill-series-apply.ts`/对话框（方向随选区形状，日期格式默认日期序列，1904 日期系统按 1900 处理），写入为普通 set-values；定位原样移植 `goto.ts`（单元格/区域/整行列/跨表/已定义名称，越界拒绝）与对话框，仅移动选区，只读/受保护亦可用。真实 Univer 序列与定位回归、真实浏览器验收（`WORKBOOK_RIBBON_CASE=fill`：向下、向左、定位，openpyxl 回读）通过。自定义排序见数据组。其余“清除”（批注/超链接）、定位条件未实现。**局部**。 | pinned Univer search算法复用，replacement预算及锁见workbook-main；保留notes/公式/非目标parts，补完整fill/clear协议。 | P0/P1/P2 |
| Insert / Tables | Pivot create/edit、table create；`ExcelShell.tsx:2464-2486`。 | `workbook-ribbon.ts:264` placeholder。**未实现**。 | engine pivot/table API和official table preset可复用；需数据范围、字段布局/聚合/刷新、真实OOXML parts/cache/关系，不只是网格渲染。 | P2 |
| Insert / Illustrations & Checkbox | picture、shape gallery、icons、screenshot、checkbox；`ExcelShell.tsx:2487-2531`。 | `workbook-ribbon.ts:265-266,389`未接持久化；drawing preset安装但currentOperations无drawing diff。**未实现**。 | 复用pinned drawing及engine image/shape；补资源+anchor/尺寸/替代文本/对象id/checkbox读写。 | P2/P3 |
| Insert / Charts / Sparklines | recommended、column/bar/line/area/pie/scatter/radar/doughnut/combo；sparkline line/column/stacked；`ExcelShell.tsx:2532-2625`。 | `workbook-ribbon.ts:267-268,390-402` disabled。**未实现**。 | 原engine图表/迷你图能力可评估，报告新图遵守Matplotlib PNG/JPEG，不扩Plotly；若源要求可编辑chart和series，静态图单独不能宣告完全等效，需明确chart语义/用户确认。 | P2/P3 |
| Insert / Filters / Links / Notes / Text / Symbols | slicer/timeline、hyperlink、note、text-box、HF、equation/symbol；`ExcelShell.tsx:2626-2696`。 | **单元格超链接已闭环（2026-11-13）**：插入 ▸ 链接按固定源 `ExcelShell.tsx` LinkDialog 与 `univer-sync.ts` normalizeLinkTarget，写入移植固定源 `xlsx-gateway/xlsx-hyperlinks.ts`（`applySheetHyperlinks`，按单元格当前链接绑定来源、http/https/mailto 与存在的工作表单元格、写后回读），链接与蓝色下划线样式同一历史步骤；区域链接只读，见 NATIVE_XLSX_HYPERLINK_ACCEPTANCE.md。**legacy notes 已闭环**（读注释/VML 严格身份、SHEET_NOTE_PLUGIN 投影、patchSheetNotes 精确补丁保作者、行列插删随迁含 VML/Anchor/清理、弹窗/位置视图语义按源收紧；main 级真实命令历史组合回归 31 项+浏览器多作者闭环验收；见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md）。threaded comments、slicer/timeline、hyperlink、text-box、HF 仍缺。**插入符号已闭环（2026-11-11，固定源 SymbolDialog，公式/富文本单元格拒绝追加，见 NATIVE_XLSX_SYMBOL_VERTALIGN_ACCEPTANCE.md）**；公式编辑器仍缺。 | engine相应API+source models；threaded person/comment parts 须单独模型与读写授权。 | P1（notes 已完成）/P2/P3 |
| Page Layout | theme/colors/fonts/effects；margins/orientation/paper/print-area/page-breaks/background/print-titles；fit-width/height/scale；view/print gridlines/headings；`ExcelShell.tsx:2704-2894`，`page-layout:fit-${axis}:${value}`等callbacks。 | `workbook-ribbon.ts:275-280`**页面设置族已闭环**（page-layout 线）：margins/orientation/paper-size/print-area/print-titles/page-breaks/fit-width/fit-height/print-gridlines/print-headings 读模型+差分收集+applyPageSetups 落盘+openpyxl 独立回读（引擎 13/13、桥 7 passed）；scale 固定源仅打印对话框诚实禁用。theme/colors/fonts 已闭环（2026-11-12，固定源 themes.ts 8 套配色/6 套字体/8 个预设，引擎 setThemePart 改写 theme1.xml，浏览器内真实重放预览，见 NATIVE_XLSX_THEME_ACCEPTANCE.md）；effects 固定源无写入保持禁用；background 未实现；行列增删不重映射已写分页符（声明）。 | 复用engine page/print/theme接口；需sheet/workbook-level metadata model/diff/replay，打印范围/标题/缩放真实分页。 | P0/P1/P2 |
| Formulas / Library | insert-function dialog、recent/financial/logical/text/date-time/lookup/math/more、autofn5；`ExcelShell.tsx:2900-2949`。 | autofn5可用，完整函数目录disabled（workbook-ribbon:424-431）。**局部**。 | 复用Univer formula/函数目录和source metadata；函数参数dialog/区域引用/locale及正确写回。 | P1 |
| Formulas / Names / Audit / Calculate | names manager/define/use/create-from-selection；trace precedents/dependents/arrows、show formulas、error checking/watch/external links；calculate-now/sheet/mode；`ExcelShell.tsx:2950-3082`，`ribbon-actions.ts:719,1067,1095,1170`。 | 名称管理器/定义名称/用于公式已接通（见 defined-names 线）。**显示公式与计算组已闭环（2026-11-09）**：按固定源 `formula-view.ts`、`calc-options.ts`、`ribbon-actions.ts:1067-1084`、`App.tsx:4758-4774`——显示公式为按工作表视图状态（CELL_CONTENT 拦截器换出公式文本并翻转 RENDER_RAW_FORMULA 刷新骨架），引擎新增 `SheetModel.showFormulas` 回读，保存差分经 `applyPageSetups` 写 sheetView/@showFormulas；开始计算（强制整簿）/计算工作表（整表脏区）/计算选项自动·手动（手动为否决计算启动 mutation 的编辑器状态，与固定源一致不写文件，切回自动即重算），计算结果不作为修改保存；只读、受保护工作表亦可用。真实 Univer 公式栈回归：手动模式改 A1 后 B1 保持旧值，开始计算后更新，保存仅含 A1 与视图。**真实浏览器验收（`WORKBOOK_RIBBON_CASE=formulas`）**：画布 D5 显示 `=A2`，保存操作仅 applyPageSetups showFormulas，openpyxl `sheet_view.showFormulas` 为真。**未实现**：追踪引用/从属、错误检查、监视窗口、外部链接（需审核覆盖层与外链宿主能力）。 | existing formula engine +named range/external links APIs；补calc mode/cache/settle export、host安全外链break/retarget和audit overlay状态。 | P0/P2 |
| Data / Pivot & Get Data | pivot/refresh、CSV import/merge-workbooks/refresh-all/query refresh/query pane；`ExcelShell.tsx:3084-3157`。 | `workbook-ribbon.ts:298-299`无可执行映射。**未实现**。 | engine imports/pivots/query metadata；授权文件上传/CSV映射/外部网络连接/credentials和刷新策略，保护非目标part。 | P2/P3 |
| Data / Sort & Filter | asc/desc/custom multi-level/header、toggle/clear/reapply/advanced filters；`ExcelShell.tsx:3158-3197`，`ribbon-actions.ts:677,777,1869,1978`。 | **升/降序已切换官方 `sheet.command.sort-range` 并浏览器闭环（含批注）**：值/样式随迁、范围外公式重算、批注经 move payload 迁移且作者保留（`patchSheetNotes` move 语义，环形置换按文本配对）。**筛选已接入引擎读写与前端闭环**：读模型（values/blank+customs 多列）+ `applySheetFilter` 声明式写回/清除 + 前端 smart-toggle/clear/reapply 官方命令与声明式差分收集（浏览器闭环 ref+条件落盘、批注保留；行可见性 v1 不写文件已声明）。附带修复：①生产未注册 sort preset；②`univer-data.ts` 投影缺 `t` 类型标记；③`update-note-position` 事件守卫恒取消；④FFilter 方法名误用（getCriteria→getColumnFilterCriteria）由浏览器实测抓出。**dateGroupItem 已闭环**（pinned 源无此代码——语义取自 OOXML 规范；读写+粒度链校验+非法组合拒绝；前端 pinned Univer 无字段故仅 server 路径可写，前端差分拒绝不静默丢弃）。**仍拒**：color/icon/top10/dynamic（读写两端）、表格内筛选路由、advanced 筛选对话框。**自定义排序已闭环（2026-11-09）**：按固定源 `ExcelShell.tsx` SortDialog（三级关键字，“然后依据”可为无；升/降序；“数据包含标题”默认勾选；列选项上限 26）与 `ribbon-actions.ts` sort-custom，打开时冻结选区，经官方 `sheet.command.sort-range` 多条 orderRules + hasTitle 执行，批注受同一结构守卫；真实 Univer 两级排序回归与真实浏览器验收（`WORKBOOK_RIBBON_CASE=sort`：降序、无标题，粗体随值迁移，openpyxl 回读）通过。行可见性 v2 已完成。 | hiddenRows/visibilityRange 经 structural/diff 生成（v2）；表格内筛选路由需先清除表格筛选；advanced 需对话框。 | P0/P2 |
| Data / Tools / Forecast / Outline | text-to-columns delimiters、flash-fill、dedupe、DV、consolidate；forecast/what-if；group rows/cols/auto、ungroup、hide/show details、clear outline、summary below/right、subtotal；`ExcelShell.tsx:3198-3272`，`ribbon-actions.ts:529-560,2006,2082,2219`。 | **快速填充已接通（2026-11-09）**：复用固定源字段拼接推断，左侧六列、单格向下最多1000行，只填空白目标，既有公式/格式/批注保留；一次官方稀疏写值命令、保护/预算预检、撤销/重做、草稿恢复、真实 patch_office 下载和 openpyxl 回读均通过，见 `NATIVE_WORD_XLSX_PICTURE_FLASH_ACCEPTANCE.md`。**文本分列已接通（2026-11-09）**：逗号／分号／空格／制表符字面分隔，复用现有 textToColumnChanges；单列、来源和输出各最多2000单元格，展开前预算预检，右侧已有值／公式／富文本、合并区域与受保护工作表拒绝；单次撤销、草稿、下载 openpyxl 回读通过，前导零／Boolean／公式形态文本／样式／批注保留，见 NATIVE_WORD_XLSX_CASE_SPLIT_ACCEPTANCE.md。**删除重复值已接通（2026-11-09）**：原样复用固定源 dedupeRows，选区所有列整行比较、文本不区分大小写、默认保留标题；冻结原选区，单次官方命令压缩值并清尾，保留目标位置格式/批注；保护/合并/2000单元格/草稿预算预检，无计算结果的公式拒绝并提示重算；撤销重做、草稿重开、真实 Chromium + Python patch_office 下载 + openpyxl 回读通过，见 NATIVE_XLSX_DEDUPE_ACCEPTANCE.md。**局部**：CSV引号限定／自定义分隔符向导、快速填充截取/大小写推断、数据验证及其余数据工具、forecast/what-if 和完整 outline 仍未完成。 | 已有engine纯compute helpers优先复用；需所有选项真实授权operation、引用修复、公式与分组状态、结果预览和撤销。 | P2/P3 |
| Review / Proofing & Language | spell-check、stats、spellcheck-toggle、translation languages经onAiRun；`ExcelShell.tsx:3380-3429`。 | 当前只有stats/translate占位，缺spellcheck入口；**未实现**。 | 复用当前模型Agno授权translation；统计只读可先做，spellcheck使用现有host/web服务并保留用户选择。 | P1/P2 |
| Review / Comments vs Notes | threaded `comment-new/delete/prev/next/comments-pane-toggle` 与 Notes menu 独立；Notes含open/delete/prev/next/show/show-all/pictures/conversion等dispatcher；`ExcelShell.tsx:3430-3480`，`ribbon-actions.ts:824-906`。 | **legacy notes open/delete/prev/next/show-toggle 已闭环**（只读导航可用、写入受限锁与预算；位置迁移仅随结构修改）；show-all/pictures/conversion 与 threaded comments 仍缺，`workbook-ribbon.ts` 批注/注释两组仍共用 note-open，不等于完整源 Notes menu。 | engine legacy notes可复用；threaded person/comment parts及conversion损失规则须单独模型与读写/授权。 | P1（notes 已完成）/P2 |
| Review / Protection | protect/unprotect sheet、workbook、change-password、allow-edit-ranges；`ExcelShell.tsx:3482-3511`，`ribbon-actions.ts:488-528,1697`。 | **保护工作表/保护工作簿已闭环（2026-11-09，无密码子集）**：引擎新增保护状态回读（`protection-read.ts`：`SheetModel.protection`、`WorkbookModel.workbookProtection`，含是否带密码/哈希）；按固定源 `ribbon-actions.ts:488-528` 与 `ExcelShell.tsx:3482-3511`，按钮标签/按下态随当前工作表与工作簿结构切换（保护↔撤销），保存为既有 `protectSheet`/`protectWorkbookStructure`（无密码、Excel 默认权限）；撤销保护排在本次编辑之前（原表名），新增保护排在之后（最终表名）。受保护工作表在网格内只读（Excel 默认全部单元格锁定；未解锁单元格编辑需 xf protection 投影，未做），工作簿结构锁阻止增删/重命名/移动/隐藏/标签色；Univer 网格自带的区域/工作表权限命令一律拒绝（不写回文件）。保存端同规则校验：本次前后均受保护的工作表、结构锁定的工作簿不得被本次修改触及（草稿重放亦然）。密码保护的工作表/工作簿只读并说明原因。**真实浏览器验收（`WORKBOOK_RIBBON_CASE=protect`）**：先改 A2，再保护工作表与工作簿，A1 键入被拒并提示，开始页编辑按钮禁用；保存操作序为 applyCellEdits/protectSheet/protectWorkbookStructure，openpyxl 回读 `protection.sheet`、`security.lockStructure` 为真且 A1 未变。**局部**：保护对话框的密码、权限勾选、更改密码与允许编辑区域未实现（引擎无密码哈希与权限写入）。 | 复用engine protection APIs，先投影源protected状态/允许操作，再做合法密码/区域变更，禁止只在UI挡而写回能绕过。 | P0/P2 |
| View | normal/page-break、grid/formula-bar/headings/RTL/cross-highlight、zoom/select/100%、window/freeze menus；`ExcelShell.tsx:3275-3377`，`ribbon-actions.ts:907-1041,1051,1085,1213`。 | 当前仅gridlines直接动作且缺收集持久化，其余disabled（workbook-ribbon:432-448）。**局部/未实现**。冻结窗格引擎全链已存在（读取 `workbook-read:206-215` pane 解析进 `SheetModel.freeze`、写回 `page-setup` pane 替换、前端投影 `univer-data` freeze），**冻结/网格线/缩放均已闭环**（均经官方命令+applyPageSetups 落盘+浏览器 openpyxl 实证，见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md）。formula-bar/headings 无独立 Univer 运行时命令（固定源为本地状态切换）仍缺。 | 复用Univer公开viewport/zoom/freeze/selection APIs及engine metadata；web窗口等效需用户确认，不能自动排除。 | P1/P2 |
| Chart Design context | chart-element/layout/color menus、chart type、select-data/switch-row-col/format pane/delete；`ExcelShell.tsx:2064-2280`。 | 当前 `workbook-ribbon.ts:346-350`只有部分标签，不含完整layout/colors；暂无selectedChart/context可执行链。**未实现**。 | engine chart parts/series更新、source chart state，可用静态renderer但需与完整可编辑图表目标区分并用户确认。 | P2/P3 |
| Table Design context | name/resize、dedupe/convert-range、table options、Light/Medium/Dark style gallery；`ExcelShell.tsx:2386-2455,1651-1715`，`table-rename/table-resize-open/table-option/table-style`。 | 已接上下文表格设计：名称/范围、汇总行、60种内置样式及无样式，并完成撤销/草稿/真实文件保存验收。首列/末列/行条纹/列条纹本批已接通并完成GUI回读，最终构建待记；创建/转换为区域/标题行及筛选按钮已分别闭环（见2026-11-10批次）；已有自定义DXF配色/固定源边框读取显示与原styles保留已验证。完整视觉组合及其余源功能仍需逐项验收。**局部**。 | 复用engine table及Univer table，需listobject id/name/range/style/options/autofilter/totals完整映射。 | P2 |
| Shape Format context | fill/outline palette、delete、arrange/order、visual:size/alt-text；`ExcelShell.tsx:2287-2383`。 | 当前tab缺失，drawing保存未收集。**未实现**。 | engine shape anchors/style与pinned drawing，补资源/geometry/selectedVisual和replay。 | P2/P3 |
| Picture Format context | 与visual分支共享arrange/size/alt-text，图片分支的adjust菜单需继续细化；`ExcelShell.tsx:2287-2383`。 | 当前tab缺失。**未实现**；不能声称只有shape菜单就是图片全部。 | engine images/media +pinned drawing；资源身份/替换/裁剪等按固定源真实callback补齐。 | P2/P3 |

## 5. 当前严格保存链的真实边界

### Word

- `F/docx-main.tsx:33-51` 校验源SHA、block原XML hash、blockId及尾节identity；`:63-69` filterTransaction以 `docxOperations` 拒绝无法映射的事务。
- `F/docx-operations.ts:140-286` 允许段落文字、普通段落插删、整段基础格式/上下标、基础列表/级别、对齐/有限缩进/间距、简单link、受限表格操作和section layout；`:290-414` replay。
- `F/docx-operations.ts:146` 不允许原对象重排；`:151-154` 新段落先保存再改结构/样式；`:174` 表格一次结构改动必须先保存；`:197` 同段style切换不能和其他改动同存。这些是当前兼容性边界，不是完整源支持范围。
- `D/bridge/edit-docx.ts:8-9` 已导入真实parse/save/patch/pPr helpers；`:289` model仍标`desktopVerified:false`；`:420` spacing协议只有spaceBefore/spaceAfter/lineSpacing；`:555`最终saveDocx和`:582`输出identity receipt。不能因底层engine更丰富，就认定Web adapter已经暴露全部功能。

### XLSX

- `F/workbook-main.ts:79-85` 实际注册core/find/drawing/table presets；`:125-166` native Ribbon只把已知窄命令交applyWorkbookRibbonCommand。
- `F/workbook-main.ts` **currentOperations 现收集** staged、sheet edits、row/column ops、cell edits、merges、column widths、row heights、**patchSheetNotes**（legacy notes 已含投影/diff/恢复/行列迁移）。新增 protection/filter/theme/page-layout/drawing/chart/table 等特性仍必须同时补投影、diff/op 和恢复；单调用Univer command不保证写回。
- `F/workbook-main.ts:170-202` 派生number-format/cache result隔离及replace预算，`:203-215` undo时按实际trigger撤回对应结构journal；`:250-260` 从original+operations重建；`:354-387` save/new revision/download行为。
- `F/workbook-ribbon.ts:366-454` 是当前显式disabled reasons；它是缺口证据，不是功能对齐成果。对于仅`commandLabels`或`groups`有id而无`RibbonCommand`/apply映射的入口也不能算实现。

## 6. 跨格式必须独立追踪的命令与边界

### Clipboard / File / Print 的 desktop → web 等效

- Clipboard：真实用户触发下读取/写入、HTML/plain/images、多种Paste Special、跨文档/跨sheet、剪切不是只复制、painter一次/锁定；权限拒绝/浏览器不支持要有可执行替代路径并保留草稿。fallback提示本身不算等效完成。
- File：报告修订保存可复用，但需区分打开本地文件/报告已有文件、保存/另存为新修订、下载/转换/重命名/恢复、源身份和scope。Mac没有File tab不能据此排除native menu功能。
- Print：跟进固定App/menu真正callback和print settings；验证当前未保存内容是否包含、页码/页眉页脚/页边距/横纵向/选区/分页/缩放。`window.print()`入口不自动等效源打印全功能，现有PDF下载不自动等效打印设置。

### AI integration / fonts / links

- AI应使用**当前报告已授权模型和Agno执行链**，复用native report AI proposals与采纳、拒绝、撤销、锁定、stale snapshot校验；不得移植桌面provider密钥/设置或自行切模型。源AI总结/润色/翻译/排版/命名等各项应有可执行映射。必要时先读相关Agno skill再实施，本审计未实施AI。
- 系统fonts：Word SOURCE明确没有系统IPC scanner，当前只嵌入/静态fallback；XLSX字体菜单是小集合。字体名可输入并不代表字体可用/渲染匹配。需文档字体、web可用字体或用户授权本地字体access、无授权fallback、保存字体名和独立渲染证据；不自动声称桌面系统fonts不适用。
- Links：Word现有safeDocxLink限制http/https/mailto、credentials/control chars/UTF-16 boundary；XLSX hyperlink和external-workbook link是不同功能。对javascript/file/data等不得直接开放；拒绝不可信数据不应阻断已核验产物下载。外部链接break/retarget、network refresh需scope/identity与网络边界。

### Undo / redo / selected state

- Word：Tiptap history可复用，但section draft更新不是自动等于同一history；表格project操作、styles、focus捕获、保存/恢复后的history定义需明确；按当前group按钮值不代表mixed selection真实状态。
- XLSX：Univer有undo/redo与结构journal反向处理，但loadOperations重建实例内容、staged ops和AI undo是不同history。需实测连续编辑→undo→redo→保存→独立回读，新增sheet/rename/reorder/delete及多次row/col操作不能只验单步。
- 每类state验：collapsed/range/multi-block/multi-cell/multi-range；explicit/inherited/mixed/unavailable；切sheet/对象移除/context tab消失；dialog打开后改选区、source换身份、保存中、read-only、saved/closed均不误操作旧目标。

## 7. 独立验收矩阵与证据要求

本轮未运行测试。后续只运行变更必要的聚焦测试，不重复完整测试。每个tracked任务至少记录以下证据路径/结果，不能只记“green”。

| 类别 | 必须验收的实际结果 |
|---|---|
| DOCX 独立回读 | 下载实际DOCX，用与前端projection独立的python-docx +ZIP/XML/relationships检查目标w:pPr/rPr/numPr/tblPr/tcPr/sectPr/fields/notes/media等；复杂结构独立XML检查不能仅python-docx文本；旧修订SHA不变、非目标part/关系/媒体字节或语义保留。 |
| XLSX 独立回读 | 下载实际XLSX，用openpyxl与ZIP/XML独立检查values/formulas/styles/numberFormat/rotation/merged ranges/sheet topology/geometry/notes/protection/filter/chart/table/drawings/print metadata；data_only与formula模式区分cache；公式派生n不新增错误style edits；源未支持结构需保留。 |
| 真GUI | 真页面实际点击tab/menu/gallery/dialog，验证键盘/焦点/selection capture/Escape/outside click/resize/context切换；检查画布、数值和pressed/mixed状态；保存→下载→打开新修订重演。mock smoke只证明该mock链，不能当真实HTTP授权和修订登记通过。 |
| Identity与恢复 | source SHA替换、block/cell/section/sheet identity伪造/变化、错误scope拒绝使用；草稿保留；刷新/关闭重开恢复同operations；保存响应丢失后同身份重试不重复新修订；载入旧草稿和stale anchor不能误写。 |
| Undo与只读 | edit→undo→redo→save读回；multi-step和structure+format组合；保存中/成功后/无权限/关闭后禁止新mutation；navigation和search可按源语义保留；不可将permanent disabled当成功。 |
| 非阻断发布 | 依AGENTS精确故障注入回归：验收失败返回具体issues且不标通过，已生成且身份可读取的PDF/Word下载链接仍签发；新增签发函数/失败步骤登记静态守卫和lineage故障注入。 |

## 8. root 可直接拆入 tracked 清单的阶段建议

1. **P0：锁定inventory/证据与已有闭环**：将本表每个group拆任务；先验未提交Word段前后精度/普通来源styles、XLSX find/customformat/theme读取/派生n隔离；核清gridlines等仅canvas状态未收集事项；保留来源未核验菜单任务，不算完成。
2. **P1：可见高频命令实际可用**：已完成——Word 精确段前后、来源段落样式、段落高亮、视图缩放、查找替换；XLSX 格式状态/自定义数字格式、查找替换、双下划线/删除线、legacy notes（含行列迁移与位置语义收紧）。全部有定向测试+浏览器闭环证据（见 NATIVE_RIBBON_STYLE_ACCEPTANCE.md）。**进行中**：Excel 官方排序+批注随迁、筛选引擎持久化、Word 段边框/底纹。随后排：Clipboard、剩余字体/颜色/清除语义、XLSX View/geometry、File/Print web等效、原生AI入口授权。
3. **P2：先打通共同读写模型再接UI**：Word复杂段落/section/tables/HF/review；XLSX filters/protection/tables/CF/DV/names/print metadata/计算导出；每族先补完整model→diff/op→replay再迁移gallery与dialogs。
4. **P3：复杂对象/集成**：Word Draw/picture/shape/references/Zotero/mail merge；XLSX图表/绘图/迷你图/切片器/外链/queries/forecast及threaded comments，保留固定源真实语义，host不适用请求用户决定。
5. 最终完成条件：全部源命令族及展开选项有“通过独立验收”的证据或用户明确批准排除；来源未核验、仅disabled、进行中、仅engine支持、仅mock测试均不得关闭完整对齐目标。

## 9. 本轮尚待细化的源分支（明确保留，不推断完成）

- Word/Excel native App/menu/file/print完整options与实际callback；当前已定位Ribbon/ExcelShell入口，后续从具体宿主callback单点追，不重扫全树。
- Word Picture Format的pictureBox与普通image差异、具体adjust/rotate/crop菜单展开项；Home字体/段落全gallery、styles直接格式舍弃语义须逐选项任务。
- Excel chart-layout/colors、shape/picture arrangement菜单、what-if/forecast、outline、Notes menu与threaded comments，需将现有group级inventory展开成选项级验收项；本表给出的fixed callbacks是权威入口，未逐项展开部分不算来源已完全核验。
- 当前engine完整API可复用范围需按目标family核定；不得因包名含chart/filter/protection便声称adapter支持。下阶段应精准读取对应export与bridge whitelist。

## 2026-11-09 清除所有格式续批更新（覆盖上文按钮未接通的历史状态）

开始页清除所有格式已接通原子 clearParagraphFormatting。选择字符去 marks、折叠光标整段清字符格式，段落回默认样式并清直接属性；标题转普通段，列表保留编号。源多数覆盖规则、草稿投影、UTF-16边界、撤销重做已有定向测试；真实Chromium下载/回读/重开验证折叠光标场景通过。表格、子编辑器、内联对象、未保存新增段及同段混合修改仍缺。验收细节见 [NATIVE_WORD_CLEAR_FORMATTING_ACCEPTANCE.md](NATIVE_WORD_CLEAR_FORMATTING_ACCEPTANCE.md)，不关闭全量目标。

## 2026-11-09 XLSX 数据验证续批更新

官方数据验证面板、legacy/x14规则读写、草稿与保存快照、行列及跨表引用迁移已接通；
定向测试、真实浏览器整数规则编辑→刷新→Python保存→openpyxl回读通过。
多选列表、部分容器元数据、定义名称/结构化列表上下文和完整选项GUI验收仍有缺口。
详见 [NATIVE_XLSX_DATA_VALIDATION_ACCEPTANCE.md](NATIVE_XLSX_DATA_VALIDATION_ACCEPTANCE.md)，
本条覆盖上文数据验证整项未实现的历史状态，不关闭全量目标。

### 数据验证审查修复与重开续验收

受保护目标表引用迁移和预算异常导致结构编辑半执行的问题已补回归并修复；
公式字符串中类似本工作簿限定符的文字保持原样，撤销保留原公式。
Chromium 保存后实际打开修订2，官方面板显示已保存规则；详见数据验证验收记录。
这仅更新数据验证本批事实，不关闭其余选项或Word/XLSX完整对齐目标。

### 全局定义名称列表续批

裸全局名称及别名链列表已接入官方面板校验和实时计算；名称换绑、来源值变更、
插行/重命名及撤销重做、草稿和保存保持名称身份已有真实Univer回归。
Chromium名称管理器修改Alias→面板beta→修改规则→刷新草稿→真实Python保存
→openpyxl回读→修订2实际重开通过，pageErrors=[]（HTTP测试替身）。
修复间接名称词法缓存、结构迁移误写展开公式和单格引用误判三处问题，28项定向测试通过。
工作表局部名称、表格结构化来源及其余数据验证边界仍未关闭。详见数据验证验收记录。

### 2026-11-09 XLSX 表格读取前置能力

工作簿模型现按真实 tableParts/内部关系读取表格身份、范围、列、表头与汇总行、
样式选项；结构插行插列后的范围与新增列可回读。缺省 name、显式 Internal、
前缀及绝对路径、XML/XLSX列名转义有覆盖；损坏容器/关系/命名空间返回
空上下文与原因，不阻断整簿读取。22项读取测试通过；此前表格创建/结构
18项回归通过，现有前端数据验证/主保存链26项通过；openpyxl独立生成
的含汇总行、含引号表名文件经实际CLI inspect回读通过。引擎typecheck、
前端build通过；workbook-engine最终418.9KiB，预算416→419KiB，其余预算
不变，预算和预算契约检查通过。只读复审未发现新阻断项。

本条只证明表格元数据读取，不代表Table Design、官方表格资源或结构化
数据验证来源已交付；这些仍需UI、结构/撤销、草稿、保存与重开验收。

### XLSX 官方表格资源与简单结构化数据验证来源续批

表格资源及简单单列结构化验证来源已接入，原始规则身份保留；真实Univer覆盖
无表头/汇总行、来源更新、行结构、撤销、草稿与保存。审查发现的删除半执行、
插列列名分歧、删列撤销丢汇总元数据已补回归并修复。36项定向测试及前端
类型/build/预算检查通过。Chromium157 dv-tables经实际Python保存、openpyxl
回读和修订2重开通过，HTTP仍为测试替身。详细边界见数据验证验收记录。

本条覆盖“表格结构化来源尚未接入”的旧状态，仅关闭简单单列来源本批验收；
Table Design、表头更名同步、原生表格样式渲染、完整结构化语法仍有缺口。

### 2026-11-10 XLSX 表头同步与表格元数据写入续批

表头更名同步已接入：单元格、官方表列与公式 SuperTable 注册同次更新，
空白补默认列名、大小写无关重复追加序号、名称限制255字符；对应单元格
公式、数据验证及全局定义名称中的显式表列引用随动迁移，字符串原文、
换行、其他表引用和 #Data 限定符保持不变，支持 @Name 当前行简写。
撤销/重做、同批表头和公式修改、草稿恢复及真实引擎保存已有回归。
受保护工作表存在消费者时，在基础写入前拒绝并指出目标表；单元格、
表格模型及历史保持原样，不能视为保护消费者自动迁移已实现。

新增 applyTableEdits 底层支持既有表的元数据编辑与转换区域，复用固定源
table-edit 及本地 ZIP overlay，严格检查工作表所有权、共享部件与关系别名；
低层接口不自动改表头单元格及引用，由编辑器协调同批操作。

验收：前端4文件52项通过；引擎/桥接表格读取与编辑46项、既有表格结构与
样式18项通过；桥接重建后 Python 实际 patch_office/openpyxl 独立回读5项通过。
引擎 typecheck、前端最终 build 通过；引擎包427.3 KiB，预算419→428 KiB。
来源三份哈希合并覆盖98个包文件（不含 node_modules 缓存），逐文件核验无差异。
真实 Chromium140 table-headers：键入→撤销/重做→刷新草稿→实际Python保存
→openpyxl独立检查表头/列名/名称/验证/公式→修订2重开通过，pageErrors=[]；
HTTP仍为测试替身。复审发现的字符串换行损坏、批量编辑撤销、保护消费者、
当前行简写四项均有局部复核确认修复。

续补：官方 clear-selection-content/all 已并入同一表头规范化与引用迁移历史，
清空表头补 ColumnN，清空区域内被删除的公式不会被引用迁移重新写回。
清空→撤销、组合编辑及既有52项定向回归和最终构建通过。其他剪贴板
专用 hook 路径仍需独立接入和验收，不能以批量 setValues 测试代替真实粘贴。

本条覆盖旧记录中“表头更名同步未接入”的状态。完整 Table Design UI、
原生样式渲染、隐式表内引用及图表/条件格式等其他消费者迁移、全部结构化
语法、跨保护表自动迁移和真实HTTP链路仍不算完成；全量目标继续保留。

### 2026-11-10 XLSX 真实表头粘贴同步续批

表头同步现接入官方 ISheetClipboardService 的实际计划：所有参与的单元格
hook 先生成变更，最后的从属 hook 使用官方 mergeSetRangeValues 合并最终
写入，再统一规划表列、显式单元格公式、数据验证和全局名称迁移。
保留官方解析与选择性粘贴语义，不把真实粘贴替换为 setValues。
安装时立即接入已注册服务，并在 Rendered 补装；每次粘贴收集晚注册 hook，
销毁时恢复原回调并移除从属 hook。

真实验收先复现普通粘贴不生成表格差分；HTML 续验收又发现清空/写值/样式
分步计划造成中间列名 Column1，已通过最终计划聚合修复。独立审查发现
跨 hook 列快照覆盖、纯格式规范化原有空格列名、纯格式对保护消费者误拦截，
均已补修复及真实 Univer 局部复核。实际更名影响受保护消费者时，在所有
基础变更执行前拒绝并保留原单元格、表列和公式；纯格式不改值与列名。

验证：三个定向文件共36项通过（main-fill-goto 31、table-paste 2、
table-headers 3）。新增真实 Univer 回归覆盖多 hook 清空/写值/样式聚合、
粘贴公式投影、同次 undo/redo、格式保留及保护拒绝；clipboard 为服务壳，
表格/公式/命令/undo 与 merge 使用官方实现。前端 build（含 tsc）、预算与
预算契约通过；未修改引擎，包仍427.3 KiB，未提高预算。

Chromium140 真实系统剪贴板验收：plain、HTML两格、仅值、仅格式四种路径
经过撤销/重做、刷新草稿、实际Python patch_office、openpyxl独立回读和
修订2重开通过，pageErrors=[]。仅格式先断言没有表格差分，再普通粘贴改名；
仅公式外部无公式文本也先断言不产生表格差分，再普通粘贴，最终闭环通过，
不据此声称真实公式来源的全部选择性粘贴已验收。真实公式消费者迁移由上述
Univer 回归覆盖。构建与多个开发服务器并行时曾出现 Vite Outdated Optimize
Dep 504，单服务重验 plain 后通过；该失败未当成产品验收通过。

本条只关闭上述表头粘贴子集。跨表剪切/粘贴的完整表头语义、合并/富文本
复杂来源、全部选择性粘贴、图片粘贴仍需独立验收；完整 Table Design UI、
原生表格样式渲染、隐式表内引用和图表/条件格式消费者仍缺。HTTP授权、
修订登记及下载路由仍为测试替身，不能视为生产HTTP链路已通过。全量目标保留。

#### 表头组合粘贴消费者续修复

后续组合回归发现：表头更名同批对既有公式消费者仅贴样式时，预规划按
“目标格出现于粘贴集合”一律跳过，遗漏该消费者的引用迁移。现按实际
f/v/p写入区分值变更和纯格式，纯格式目标继续参与公式迁移；新增组合断言
在修复前失败、修复后3项表头回归通过（含多hook、撤销/重做和保护边界）。
续验：最终前端 build（含 tsc）通过，Vite 构建38.32秒；预算及预算契约通过，
引擎包仍427.3 KiB，未提高预算。最终代码的 Chromium140 HTML表头粘贴
闭环通过（撤销/重做、草稿恢复、Python patch_office、openpyxl回读、修订2
重开），pageErrors=[]，D5引用正确迁移为 Staff[Employee]。同一消费者仅贴
样式与表头更名组合仍由真实Univer集成回归覆盖，尚无该组合的独立GUI场景；
本条不扩大前述验收范围。


### 2026-11-10 并行续批：Word纸型/宽边距与XLSX表设计更名

按“一缺口一子agent”分别实施与验收，root负责集成。

Word布局纸型画廊按固定源补齐13种预设，含横向换算、±2 twip回显和当前节
切换；既有自定义纸型允许直接编辑。布局及分节定向回归通过。Chromium140
两节A5纵向/A3横向经草稿恢复、实际patch_docx、python-docx独立回读和修订3
重开通过，pageErrors=[]。GUI后自定义输入启用判断经对应回归验证，未重复GUI。
“宽”页边距从四边2160修正为上下1440、左右2880 twip；按实际四边回显，
旧四边2160显示自定义。最终布局6项通过；独立margins-wide浏览器场景回读
首节[1440,2880,1440,2880]、相邻节原样[1440,1800,1440,1800]，修订3
重开正确，pageErrors=[]。不扩大全部纸型打印、“应用到整篇”和镜像边距验收。

XLSX新增上下文“表格设计”的名称与范围回显，名称输入捕获表格身份并保留
编辑中的输入。名称事务使用官方mutation及同一撤销历史，写前校验命名规则、
工作簿表名/定义名称冲突和来源/消费者保护；同步显式单元格公式、DV和定义名称。
后续mutation拒绝时回滚已执行步骤。复用官方词法器迁移表名，保留字符串、
普通名称、其他表和外部工作簿引用，覆盖Unicode/反斜杠/CRLF；解析20项、
真实Univer事务16项通过，含SuperTable注册、连续更名、撤销重做和故障回滚。
保存差分补齐来源身份下的表名、范围、列数变更及可写存续工作表的表格删除；
不将未支持或已移除工作表误判成表格删除。差分12项通过，含真实引擎回写重读。
名称范围差分是底层能力，不能据此宣称resize/convert的完整UI与语义已完成。
root集成的main/ribbon/tables三个定向文件65项通过。

Chromium140实际“Staff→People”经界面编辑、撤销重做、草稿恢复、Python
patch_office、openpyxl独立回读和修订2重开通过，pageErrors=[]；表格名称、
D5=COUNTA(People[Name])、DV=People[Name]和全局Employees=People[[Name]]
一致。HTTP context/file/登记/下载为替身，不能当成生产HTTP授权/溯源通过。
统一构建、样式模块集成与审查仍在进行；全量Word/XLSX目标继续保留。


#### 本批样式集成及审查续验

新增原生表格样式渲染模块，适配固定源60种内置Light/Medium/Dark调色规则，
使用工作簿主题色、表头/数据/汇总行、行列条纹与首末列强调。官方资源恢复时
TableManager未传递styleId会重置绑定，现按来源meta在载入完成后重新关联每表
主题；两张不同主题表及销毁重建由真实官方插件测试覆盖。默认空主题保留给
无样式或未知自定义样式，未推测自定义DXF。实色单元格格式优先、自动黑/空填充
渲染让位，原始matrix不改；所有60种只有生成覆盖，实际组合渲染示例不能代替
全部样式视觉验收。审查补齐无表头Light首行顶边框，先红后绿。

集成首次回归70绿1红，唯一失败为旧测试断言空主题，已改为来源Medium2真实
表头/条纹断言并定向重验通过，草稿仍为空。新增backslash合法表名的DV展开
回归先红后绿，tables最终15项通过。旧截图脚本坐标选到了官方表名横条而非
A1，移动到区外后不能回到表上下文；改为实际单元格坐标后GUI通过，此脚本
失败不记为产品验收通过。

带原生Medium4样式的Chromium140更名闭环再次通过，额外断言保存operations
没有主题渲染诱发的cell style编辑；网格截图人工查看表头与行条纹正确。
官方表格菜单中文locale已合并。公式视图样式链短路和表头显式bl=0的优先级
仍在补组合回归，最终构建须在两项修复稳定后续验。


#### 样式组合收尾与code同步

审查后的两项显示差异已修复：无显式填充表头强制加粗，实色填充/非默认文字
保留固定源优先级；6项样式定向回归通过，raw matrix不变。公式视图不再
短路后续CELL_CONTENT样式链，新真实Univer组合回归通过，含NUMFMT、显式
实色、切换恢复、raw公式及snapshot.styles不变。原main-calculation测试补齐
官方DV/Table插件依赖后，在首次切换前的公式缓存初始化仍为null而非6；该项
尚未通过，不能将本批说成全部计算回归已通过。后续需独立处理该初始化问题。
反斜杠表名\People的Chromium140真实更名闭环通过，DV列表、公式、全局名称、
撤销重做、草稿恢复、实际文件回读及修订重开保持一致，pageErrors=[]。

按用户要求拉取code：GitHub直接TLS失败后通过临时代理抓取，同步本地code到
7defea08（较原HEAD快进59提交），未改变origin URL。本地改动先备份至
/tmp/smart-reporting-code-update-20261110-013940，并保留命名stash；恢复时
唯一冲突为delivery/xlsx.py操作白名单，合并保留applyStaticImages和本地
replaceSheetDataValidations/applyTableEdits。184个原文件无缺失，只有6个上游
重叠文件内容变化，其余hash保持一致。前端tsc+Vite build通过（38.68秒），
预算及预算契约通过，未提高预算。发现本地Node dist仍为旧代码后，已重建
workbook/slides/pdf三个服务端桥接；最新静态图片替换回归通过。


### 2026-11-10 下一并行批次：计算fixture、表范围与首页不同

公式缓存初始化根因现已查证并关闭：真实引擎发出B1=6结果，但测试将table
preset替换为空时漏掉官方table facade导入，tableHeaderProtectionReason缺少
getTableList接口而打断回填。补齐真实DV/Table插件与facade后，原有全部断言
通过（初始6、公式视图、manual保持6、CalculateNow为15、实际XLSX保存回读）；
不放宽数值、不删除断言、不改生产逻辑。该证据覆盖前条“初始化待修”状态，
不扩大到所有公式兼容性。日志/tmp/table-calculation-init-green.log。

本批其余两项为完整表范围调整事务与Word当前节首页不同，仍在实现中。


#### 表格范围、隐式引用与首页不同：本批实现与定向验收

XLSX表格设计新增调整范围按钮和捕获tableId的对话框，提交时重验可编辑态，
失败保留输入与具体原因。事务整体预检A1范围/1000列/表头行/交叠/最少数据行/
保护/合并冲突，按实际表头规范列名，保留绝对列身份；按固定源移动汇总行，
清理旧内容与粗体，刷新SUBTOTAL数据范围。显式消费者及有坐标所属表的隐式
消费者同步，列名互换只迁移一次；同次undo/redo，嵌套注册失败也回滚当前步骤。
真实Univer最终22项通过，tsc通过。对话框/功能区/公式注册共24项定向通过。

新增公式注册适配：完整表范围保留汇总行，SuperTable数据范围排除来源totals，
按真实表范围计算以避免重复扣行，覆盖加载、重建、更名和范围/列名变更。
独立只读probe确认连续注册幂等、titleMap保留、销毁恢复。组合回归发现官方
临时表可能没有meta，补来源判定后“精确排除header/totals”3项通过且无未处理
异常；此前32项断言虽通过但出现3个未处理错误，不算成功验收。

Chromium140普通表A1:A3→A1:B5、汇总表A1:A4→A1:B7分别经过对话框、撤销重做、
刷新草稿、真实Python patch_office、openpyxl独立回读和修订2重开通过，
pageErrors=[]。汇总场景A4清空且去粗体，A7=SUBTOTAL(103,A2:A6)且粗体，
totalsRowCount=1、原生Medium4及列名保留。GUI后新增仅隐式引用迁移与无meta
注册适配，由定向回归验证；未重复两种GUI。HTTP与登记/下载仍为测试替身。

表头隐式列引用按公式真实worksheet+table范围迁移[@Qty]/SUM([Qty])/#Data，
不误改同名异表、表外、另一sheet或外部引用；支持粘贴投影/纯样式/清空不复活/
保护预检和undo/redo。references28项、headers8项通过；DV、全局名称、图表等
无唯一公式坐标的隐式作用域没有猜测扩大。

Word当前节“首页不同”复用setSectionLayout.values.titlePg与节身份，非尾节
最小修改sectPr，尾节复用saveDocx flag；按当前节回显、草稿恢复、与尾节HF
两入口同步且单次撤销，未知/重复标记显示不可判定并禁用。布局/分节/恢复30项、
后续原子撤销对应1项、HF组件10项/协议7项通过，文件新增3项通过（旧分节8项
此前通过）。仅titlePg补丁除document.xml外所有实际ZIP部件字节保留，正文
去除titlePg后完全一致。Chromium140首节开启→草稿恢复→修订2→重开关闭→
修订3通过，最终[false,true]，8个HF parts及document.xml.rels SHA保留，
pageErrors=[]。GUI后unknown/事务/core.xml保留经独立定向回归；非尾节HF内容
编辑、真实HTTP与全部Word布局功能不算完成。统一最终构建和审查仍在进行。


#### 本批最终审查补验

只读审查发现同一尾节Layout与HF的titlePg相反时，恢复阶段先前接受而保存端
才拒绝。现恢复协议在挂载前明确拒绝并保留草稿，未静默选择某一值；该回归
先红后绿，冲突拒绝与正常双入口原子恢复两项通过。之前统一构建通过（39.65秒），
预算及预算契约通过，引擎427.3 KiB、workbook-main247.3 KiB，未提高预算；
此恢复补丁之后正在重建最后产物。公式注册/公式视图两个定向集成通过。
全量目标仍未完成，表设计创建/选项/转换、完整表格样式视觉组合、Word其他
页眉页脚/域/修订与复杂对象等均需继续独立验收。

最终恢复冲突补丁之后tsc+Vite build通过（39.17秒），预算及预算契约再次通过；
无新增预算额度。所有本批代码仍为未提交工作区改动，未推送或部署。

### 2026-11-10：整篇奇偶页页眉页脚与表格汇总行、内置样式

固定 GenOffice 来源仍为 f8c17004fb730df11f0f743164ffd8b4281bb38c；本批一个缺口一个子 agent，root 负责界面集成、保存差分和统一构建。远端 code 已 fetch 核对，HEAD/origin/code 均为 7defea08，未覆盖未提交修改。

- Word：固定源 evenAndOddHeaders 是 settings.xml 整篇设置。Layout/HF 两入口共享状态和原子历史，使用尾节身份的 setSectionLayout 信封，恢复阶段拒绝矛盾草稿。无法解释、重复或替代前缀标记保守只读。真实文件测试覆盖开启/关闭与未知标记，浏览器覆盖首节开启、尾节同步、草稿刷新、修订2保存、关闭并修订3重开；12个HF部件及document关系哈希保持，页面参数/titlePg保持，pageErrors=[]。证据 /tmp/word-evenodd-smoke.log、/tmp/word-evenodd-source-green.log；布局/sections13项，恢复/HF33项通过。复杂HF版式并未因此宣称全量通过。
- XLSX 汇总行：在现有表模型上原子变更范围、footer、单元格和公式注册，开启先检查保护/占用/合并/其他表，数字109、其他103，撤销恢复主题和元数据，嵌套失败回滚。13项真实Univer及引擎往返测试通过，包含Dark/None兼容，证据 /tmp/table-totals-final-compat.log。
- XLSX 样式：60种内置样式及显式无样式，通过官方范围主题显示，不逐格写主题格式；独立历史和回滚、保护检查，保存保留其他flag。基础11项通过，新增Dark3/None两项实际保存回读通过，ZIP除table部件外逐项不变，cells不变；证据 /tmp/table-style-edit-final.log、/tmp/table-style-real-roundtrip.log。
- root：表格设计接入汇总行checkbox与样式select，回显当前表、保护状态；保存diff明确输出totalsRow/style（空串不丢）。ribbon与tables39项通过，计算集成1项及保护2项通过。保护测试补齐官方DV/Table插件，未以生产容错掩盖测试环境缺失。只读交叉审查未发现新增阻塞问题；公式注册统一从完整表范围排除汇总行，覆盖后续表头改名。

本批首次tsc+Vite构建通过，但workbook-main255.5KiB超过现有250KiB预算，尚不能称最终门禁通过；已将新totals/style模块拆为独立workbook-table-design包，等待最终构建预算结果。全量对齐仍未完成：表创建/转换、其余表选项与样式视觉组合、Word复杂页眉页脚/域/修订/复杂对象等仍需推进。GUI HTTP端点仍为mock，文件保存由真实Python patch/openpyxl等独立读取验证，未声称生产HTTP验收。

拆包后最终构建通过（39.03秒），预算与预算契约通过：workbook-main242.6KiB、table-design6.1KiB，未提高预算。GUI复验发现实际新缺口：从修订2重新加载后关闭汇总行，内容清空但A4来源粗体仍保留；不放宽验收断言，已交原汇总行agent修复并补来源格式回归。该项解决前不宣称本批GUI全通过。

本批最终补验：关闭汇总行使用bl:0明确取消来源粗体（原bl:null只删除覆盖，保存无法表达bold:false），未改公共readback继承语义。13项定向回归通过，包含真实文件开启保存与关闭回读粗体；浏览器table-options最终通过，顺序完成totals+Dark3、两次undo/redo、草稿reload、修订2保存、重开关闭totals+None、reload、修订3保存，A4=[null,false]、表范围A1:A3、样式空串，pageErrors=[]。证据/tmp/table-totals-unbold-green.log与/tmp/table-options-gui-final.log。修复后tsc+Vite最终构建通过（39.71秒），未提高预算；最终预算结果另记。全部仍未提交、未推送、未部署。

最终粗体修复后预算检查和预算契约均exit0（/tmp/office-table-options-bold-final-budget.log），本批验收完成。下一独立缺口已核对为Table Design首列/末列/行条纹/列条纹四个flag的界面与保存差分；现有底层读写和主题支持不等于这些入口已对齐。

### 2026-11-10：表格首末列与行列条纹四选项

- 复用现有样式owned mutation实现setOption：首列、末列、行条纹、列条纹只更新目标表的meta与官方范围主题，保留样式名/其他flag/汇总状态。None保持无样式但保存flag；无变化不新增历史；主题登记前/后失败均恢复，不写单元格主题格式。
- root Table Design四checkbox准确回显来源值，按当前表身份分派，保护/只读时禁用；保存diff只输出发生变化的firstColumn/lastColumn/bandedRows/bandedColumns，回到来源值不产生diff。
- RED/GREEN：root界面/保存差分原先2项失败，补实现后41项通过（/tmp/table-style-flags-root-red.log、/tmp/table-style-flags-root-green.log）；style-edit25项通过（/tmp/table-options-final.log），含四flag实际引擎保存回读、None来源、单表隔离、显式非粗体优先、无变化/保护/失效身份/故障回滚，非table ZIP部件完全不变。
- Chromium140实际GUI通过（/tmp/table-style-options-gui.log）：两列源四flag true/false准确回显，逐项反转、4次撤销/重做、草稿刷新、真实Python/openpyxl保存及修订2重开；最终false/true/false/true，源单元格XML逐格原样，无applyCellEdits，pageErrors=[]。HTTP仍mock，未声称生产HTTP验收。

本批Word当前节页码格式/起始仍在实现；统一构建预算待该项稳定后执行。完整样式视觉组合、表创建/转区域和Word其他功能仍未完成，不据此标记全量对齐完成。

四flag独立复核未发现保存/撤销/None语义阻塞。GUI并不含像素验收；后续探针确认一处实际显示缺口：Medium23行列条纹同时启用时A3应为列条纹#B4C7E7，实际被whole fill #DAE3F3覆盖，原因是缺省第二行条纹错误填入整表底色（临时探针/tmp/review-table-stripe-priority.cjs）。已交原主题agent做真实Univer RED/GREEN最小修复。仍未验收单列首末列同时强调、隐藏/筛选行条纹节奏、无表头/汇总行与全部选项组合、60套样式逐套视觉/边框精确度；未知自定义DXF属于实际实现缺口。

条纹显示补验完成：仅去掉缺省secondRowStripeFill→wholeTableFill这一错误回退；wholeStyle继续负责整表底色。Medium23与Dark2真实Univer先红后绿，Light2/Medium23/Dark2/双色Medium9同时条纹、只行、只列逐格回归共该文件10项通过，matrix原样。证据/tmp/table-stripe-priority-red.log、/tmp/table-stripe-priority-green.log。此对齐依据为固定源导入文件renderer applyTableBanding的优先级，源session helper本身也存在同fallback，未混称上游两路径一致。

下批转区域调查新增独立官方行为probe（workbook-table-convert-probe.test.ts），2项通过，不代表产品契约：同大小写显式表引用变#REF!，大小写变体/隐式/DV/names原文保留；删除移除主题；官方undo丢meta/列身份/筛选，导致总计范围与DV计算副本包含汇总行。未直接开放转换按钮以声称完整源对齐；后续需复用官方消费者变更同时补完整原子恢复。

### 2026-11-10：Word当前节页码格式与起始

固定源App.tsx openPgNumModal/applyPgNumFormat逐节语义：七种格式，decimal与空起始移除直接设置（续前节），0保留。新增逐节inspect字段与只读原因，setSectionLayout.values.pageNumberFmt/pageNumberStart按sectionId/sha最小修改目标pgNumType；尾节复用saveDocx、非尾节官方applyPageNumType。未知格式/重复tag或属性/额外属性/不可解释起始拒绝修改且保留原标记。null移除、undefined不修改；旧HF入口999999限制已取消，与源及逐节入口统一为非负安全整数，包含4294967295回归。

Layout当前节页码格式对话框、尾节HF附带参数同步、原子撤销恢复，矛盾草稿挂载前拒绝且保留。修复弹窗autoFocus造成的React/PM生命周期flushSync警告与按钮失焦点击丢失，保留真实点击和pageErrors=[]要求。前端4文件51项通过（/tmp/word-pgnum-ui-final.log），后端6项通过（/tmp/word-pgnum-backend-final.log），包括仅目标sectPr变化、其他实际ZIP部件逐字节不变和未知标记只读。协议独立只读复核无新增阻塞。

Chromium140真实GUI通过（/tmp/word-pgnum-smoke-final.log）：两节分别upperRoman/start0、lowerLetter/start5，草稿刷新、实际修订2保存，再首节decimal/空起始保存修订3并重开，尾节保持；12个HF部件+document关系哈希保持、pageErrors=[]。不据此声称所有PAGE域渲染/多节HF归属已完成；链接到前一节仍缺完整ownership协议。GUI HTTP为mock，文件patch与python-docx/ZIP读取真实。统一build与预算正在执行，结果另记。

本批最终验收：聚焦/按钮最终补丁后Word四文件51项再次通过（/tmp/word-pgnum-ui-final2.log），新增输入guard后layout单文件10项通过（/tmp/word-pgnum-input-guard.log；合计当前52项，未重复完整测试）。统一tsc+Vite构建exit0，38.72秒（/tmp/office-style-flags-pgnum-build.log），体积预算与预算契约均exit0（/tmp/office-style-flags-pgnum-budget.log），未提高预算。git diff --check无错误。代码仍未提交/推送/部署。全量目标保持未完成，下一批转区域完整恢复与Word多节HF ownership等仍需实现和验证。

### 2026-11-10：XLSX转换为区域

固定源table-design-actions.ts convert-range删除表及banding/filter，不承诺主题烘焙或引用改A1。复用官方SheetInterceptorService删除消费者变更以及Add/DeleteSheetTableMutation，以受信owned transaction补齐完整table.toJSON/theme/filter/columns/meta/汇总引用注册undo；所有相关表页保护在写前核对，失败逆向恢复，不另推残缺官方history。删除前通过官方TableManager清除该表filters，修复删除后隐藏行缓存残留；撤销恢复filter及真实隐藏行。

root Table Design按钮带confirm明确移除表格/条纹/筛选、保留显式格式内容、结构化引用可能失效；对应guard/保存diff沿现有实际回读。ribbon先RED后GREEN25项（/tmp/table-convert-ui-green.log），main计算/保护3项通过（/tmp/table-convert-main-regression.log）。模块11项通过（/tmp/table-convert-final.log），含完整undo/redo、保护/过期/伪造参数、删除与消费者写前/写后故障回滚、nested owned守卫、实际引擎保存。保留固定官方事实：同case显式变#REF，异case/隐式/DV/names原文保留；删除列表计算副本=#NAME，undo恢复排除totals的正确来源范围。

Chromium140 GUI通过（/tmp/table-convert-gui.log）：双表fixture转换、undo/redo、草稿恢复、真实patch_office/openpyxl保存，只目标Staff删除、Other整份table XML不变、目标8格源XML/显式格式/值不变，DV/names原文保持、pageErrors=[]。HTTP仍mock，未声称生产HTTP测试。Word多节HF链接正在开发，统一构建预算待稳定后执行。

转换独立只读review无新增阻塞：早期故障也恢复完整snapshot，滤镜缓存/主题/汇总引用注册一并恢复，相关消费者保护在写前核对；不重复测试。新增convert代码进入原workbook-table-design独立chunk，未提高预算，最终构建待Word稳定。

Word多节HF开发中交叉审查新增两个真实问题，尚不算完成：insertSectionBreak与链接同批导致输出节序号和来源模型错位；另三节同批前节开启继承、后节解除继承会使动态owner变为复杂带关系部件，若只按原始owner检查会复制XML却丢.rels。均已交Word agent补来源映射/明确先保存约束及动态复制来源完整性检查，禁止将损坏文件记作通过。多节相同sectPr首匹配误改节已用按文档顺序定位修复并有真实文件回归。

Word链接GUI已有真实五修订闭环通过（/tmp/word-hflink-smoke.log）：第2节开启继承→保存2、解除继承原XML克隆→保存3、编辑新own→保存4、重新开启→保存5并重开；正文及其余原HF保持、pageErrors=[]。此GUI之后尚在补动态复杂关系/分节组合边界与迟到commit身份守卫；故最终状态待其定向回归和统一build。已有临时限制：链接未保存前同slot内容需先保存后编辑；复杂内部图片/超链接关系复制尚未完成迁移，明确只读保留，不能据此声称完整HF对齐。

### 2026-11-10：Word多节页眉页脚继承基础链

inspect新增每节六slot的own/effective owner、rId/path/hash/linked；新setHeaderFooterLink整体核对来源节和own/effective身份。开启继承仅移除本节引用，保留孤立源部件；解除继承复制当前有效原XML为独立part/关系/contentType。前端跟随当前节、首节禁用，继承编辑提交到effective owner，独立新own保存后可实际编辑，单history/草稿身份恢复。

已修相同sectPr首匹配误改节、分节+link同批索引错位（明确先保存）、动态继承owner复制复杂关系丢.rels（复制前动态copyable检查拒绝，保留原文件）。复杂独立图片/超链接关系的完整克隆仍未实现，来源只读原因明确；链接尚未保存的同slot需先保存再改内容是临时限制，不算完整源HF对齐。

文件sections26项通过（/tmp/word-hflink-backend-final.log），包含目标节改写/原part保留、原XML克隆、独立编辑、首节/伪造身份拒绝、相同节XML、动态复杂关系和分节组合。主视图新增单次undo/redo owner/content同步、合法草稿恢复和伪造owner挂载前拒绝且草稿保留；组件新增迟到commit节身份守卫。固定源开启继承需确认：补confirm取消保留编辑内容/确认discard，解除继承携pending文本写owner再克隆，避免静默丢字。确认补丁后3文件41项通过（/tmp/word-hflink-confirm-history.log），最终追加main/文件针对性用例仍在取结果。

此前五修订GUI通过日志仍有效，但它早于confirm及最终边界guard补丁；不将它描述为这些后补分支的GUI证据。这些分支由精确组件/main/真实文件回归验证。最终统一构建已启动，预算与结果待记。未提交、推送或部署。

最后针对性结果：confirm与pending继承文字同history后3文件42项通过（/tmp/word-hflink-confirm-history-final.log），新增真实原owner写入再clone1项通过（/tmp/word-hflink-pending-backend.log；与原26项合计sections当前27项，未重复整文件），既有HF桥接8项通过（/tmp/word-hflink-existing-backend.log）。最终只读审查未再改生产。实际限制仍包括复杂独立关系复制未支持及链接未保存前内容编辑约束，不缩小全量目标。

本批最终构建与预算：tsc+Vite exit0，38.76秒（/tmp/office-convert-hflink-final-build.log）；预算及预算契约均exit0（/tmp/office-convert-hflink-final-budget.log），workbook-main244.9KiB、docx-main195.7KiB、table-design9.2KiB，未提高预算。最终动态复杂继承草稿拒绝补验使hf-sections测试文件2项通过（/tmp/word-hflink-dynamic-recovery.log）。git diff --check通过；全部未提交、未推送、未部署。全量对齐未完成；下一XLSX独立缺口已核对为原生创建表事务/表头选择/新增表保存差分，Word以上限制仍需解除。

### 2026-11-10：XLSX原生创建表（含有/无表头）

复用官方Add/Delete mutation、undo factory和范围主题，实现owned创建事务：有表头trim/255/空ColumnN/大小写去重，无表头优先上方空行、否则下方有空位时移动原始数据一行（公式搬移明确拒绝）；预检保护、合并、现有表/自动筛选、范围和1000列边界，名称TableN避全部表及定义名称。默认Medium2/行条纹，完整meta/主题/公式注册，失败恢复与单history。单格范围按固定源连续区域扩展，空/单行不可推断则保留原选区由对话框调整。

root Home/Insert“套用表格格式”创建入口接captured sheetId范围对话框，创建后激活Table Design。保存从live nativeCreatedTable最终状态生成addition，样式选项/汇总行后置补齐；既有表删除/更名/范围更新先执行，避免转换后复用名称/区域冲突；既有source删除再排在其他source编辑之前（真实失败先RED后GREEN）。新表转换/撤销后不残留addition。来源只读检查改用稳定sheet身份，修复改名后绕过限制、保存时丢新增表的问题，真实主视图先RED后GREEN。

创建API23项通过（/tmp/table-create-final.log），真实engine保存覆盖创建后resize/style/options/totals/convert组合、原格式/值保持与撤销diff空。ribbon+tables44项通过（/tmp/table-create-root-green.log），追加顺序回归后tables20项通过（/tmp/table-create-save-final.log）；main保护/改名来源只读3项通过（/tmp/table-create-readonly-rename-green.log），计算/保护3项先前通过。创建对话框2项通过（/tmp/table-create-dialog-green.log）。新表组合还发现转换undo把空filter数组改成长空数组，已保持实际原长度，convert12项通过（/tmp/table-create-convert-empty-green.log）。

Chromium140实际GUI通过（/tmp/table-create-gui.log）：Table1有表头→Dark3/首列/列条纹/totals A1:B4，Table2无表头借空行A6:B8/Column1+2，undo/redo、草稿刷新、真实patch_office/openpyxl回读；原Staff F1:G3整table XML及10个来源cell XML/显式格式和值不变，pageErrors=[]。HTTP仍mock。统一构建预算进行中，不据此声称其余插入/表筛选选项全量完成。

### 2026-11-10：Word带媒体/链接页眉页脚继承解除

新关系图检查复用官方parseRels/相对路径解析，原HF与新HF同目录，新own复制原XML和companion rels原字节，依赖保持共享原位置/字节身份；External/TargetMode/rId保持，不重编码或改写共享媒体。inspect与link草稿带own/effective依赖图SHA（关系、内容类型及可达目标），动态继承来源也重新核验；缺失/重复/未知类型/循环/悬空引用只读说明。支持图片、external hyperlink及chart→嵌套package等已验证图。

实际编辑测试发现生成器丢wp等root命名空间，现保留原HF全部声明及mc:Ignorable并合并新增声明，严格XML解析和实际PNG读取验证。媒体/关系等定向15例中14先通过，1个fixture重复mc:Ignorable导致无效XML，修正fixture后该例单独通过（/tmp/word-hfmedia-final-backend.log、/tmp/word-hfmedia-namespace-final.log）；既有HF8例通过，前端29项通过。媒体GUI通过（/tmp/word-hfmedia-smoke.log）：PNG+external hyperlink继承解除→保存新own→重开改文字→保存重开，图片/链接各1，原HF哈希及媒体SHA保持、pageErrors=[]。GUI后仅补空根/>保护并由实际文件回归通过，不混称该分支GUI已验。

仍未完整对齐：未知关系类别、循环/无法核验依赖保守只读；链接修改后同slot内容需先保存、新分节与链接需分次保存等先前限制仍在。代码未提交/推送/部署，完整目标保持未完成。

媒体最终交叉审查新增真实路径假设缺口：合法HF位于word/headers/header1.xml时，其../media/image1.png相对目标依赖原目录；固定复制到word/headerN.xml会断链。已交owner补非默认目录真实RED/GREEN、在有效来源同目录分配新part/正确document关系及输出图回验。修复取证前本批媒体复制不标最终完成。创建来源只读回归与保存删除顺序已修复通过；首次统一构建仅因新test可选view类型报错，最小修正测试后前端构建正在运行。

上批最终补验：创建/媒体前端统一tsc+Vite构建exit0、39.14秒（/tmp/office-table-create-hfmedia-build.log），预算及预算契约exit0（/tmp/office-table-create-hfmedia-budget.log）；未提高预算。该构建早于下面创建下移格式及标题行新补丁，新补丁需后续统一构建。

Word非默认目录断链已真实RED/GREEN修复：新own分配在动态effective来源的实际目录，document关系及contentType正确URI编码；输出前全新inspector重新核验每个新part完整图。word/headers、other/headers、含空格嵌套目录3例原先失败（/tmp/word-hfmedia-directory-red.log），修复后含既有媒体/动态owner/nested chart→package共6例通过（/tmp/word-hfmedia-directory-green.log）；三种目录解除保存后再次实际编辑新own，严格XML解析、drawing/hyperlink各1、原部件和媒体SHA保持，3例通过（/tmp/word-hfmedia-directory-edit-green.log）。仅bridge与测试变化；不混称前端构建覆盖bridge。

创建下移新增真实格式缺口已修复：普通增量diff将缺失样式视为继承，导致移动来源普通格式后保留目标粗体/填充/数字格式。仅创建下移格随官方custom携nativeTableCreateStyleReset，保存用同一snapshot按实时完整基础格式输出styleReset；公共diff继承语义保持，已有custom保留，后续格式修改不被旧缓存覆盖，撤销无差异。先真实RED（/tmp/table-create-shift-style-red.log），定向10项通过（/tmp/table-create-shift-style-green2.log），覆盖无样式/Calibri普通/绿色斜体蓝边来源、格式后改及回滚。root保存入口已接helper；真实主视图创建对话框→保存→引擎回读1项通过（/tmp/table-create-main-shift-green.log）。首次入口测试仅缺测试宿主官方filter插件，补齐宿主后通过。全量对齐目标仍未完成。

### 2026-11-10：XLSX标题行开关（当前批验证中）

固定源toggleHeaderRow的实际范围语义已接入：关闭清原header内容/startRow+1，开启需上方空行并按XML列名写回/startRow-1，data及totals end保持。owned transaction保存完整columns/meta/theme/filter，过滤条件与engine headerRow保持清空，undo恢复全量来源。新增Table Design“标题行”checkbox与保护状态、主视图回显/guard/保存diff；来源与新表按最终真实range持久化headerRow。TableAddition新增可选顶层headerRow:false，直接支持单data行且不生成autoFilter，不借虚构header范围保存。

root界面/保存先RED（/tmp/table-header-row-ui-red.log、/tmp/table-header-row-save-red.log），补实现后ribbon+tables49项通过（/tmp/table-header-row-root-green.log）；真实主视图标题切换/undo/redo/保存及创建下移最新helper共2项通过（/tmp/table-header-row-main-final.log）。新headerless单行实际Python patch/openpyxl/原cell XML回读1项通过（/tmp/table-header-row-python-green.log）。既有engine创建8项中7先绿、1仅旧错误文案契约失败，保留原有表头错误文案后该项单独通过（/tmp/table-header-row-existing-additions.log、/tmp/table-header-row-existing-additions-recheck.log）。

模块最终16项通过（/tmp/table-header-row-final.log），含原/无header来源、总计、真实engine回读、完整undo、保护/占位/merge/交叠、写前后故障和真实BeforeCommand表头消费者保护：undo已调整先模型再cells，避免撤销新增header被误识别为清列名。GUI首次关闭确实成功但选中原header移到表外，context tab卸载令Playwright uncheck追旧控件超时；正按实际点击→保存状态→重选data格补GUI，不把该失败当通过。

官方formula registry无header/totals参数，ReferenceNodeFactory兼容适配复用官方解析/引用对象，保持真实表range：无header #Data含首行、#All含总计，缺失#Headers/#Totals为#REF!；#This Row按官方当前行执行。真实headerless XLSX生成/回读、节点展开10/20/30与首中末当前行通过（/tmp/table-formula-header-real.log）。依赖固定Univer0.25.1私有对象，dispose恢复factory；大小写不敏感表名、多段union及@简写仍属未修官方限制，不据此声称完整结构化公式对齐。

创建下移完整格式补验：helper现通过现有styleDelta映射逻辑字段到engine字段，并局部规范middle→center；否则hAlign/vAlign/wrap直接保存会错误。新增右对齐/垂直居中/换行真实文件来源，第4来源用例连同原3例通过（/tmp/table-create-shift-alignment-green.log）。上述新增生产仍待统一前端构建/预算；Word同槽链接+内容保存仍在修复多级组合与GUI，不标批次完成。

### 2026-11-10：Word链接与同槽内容同次保存

解除前节继承后可立即编辑新own；开启继承后可编辑计划中的有效owner。新增严格afterLink:true内容协议，必须匹配该节同slot解除操作，来源sha仍按原inspect及全批链接计划核验，不接受客户端部件路径/XML。原owner内容先原生保存、复制有效XML/rels后再原生保存新own；原namespace及输出图重新核验，未变化固化内容跳过重写以保原XML。每次解除把当时显示内容固化为afterLink，修复三级继承在后续解除时跳回旧内容；onLink pending同样采用planned来源身份。修复离开HF页签时未flush丢文字及二次save包含hidden辅助block导致重复节。

前端3文件49项通过（/tmp/word-hfsame-save-cascade-final.log；较早ui-final/cascade-ui为定位失败日志，不作为通过证据），tab退出flush新增定向1例通过（/tmp/word-hfsame-save-tab-flush.log）。真实文件两/三级继承、媒体、非法/未匹配afterLink、最终ZIP/节数定向5例通过（/tmp/word-hfsame-save-cascade-fixed.log），此前ZIP4例通过（/tmp/word-hfsame-save-zip-final.log）。独立review发现的pending身份/下游复制旧文本两问题均已补回归修复。

Chromium140实际GUI通过（/tmp/word-hfsame-save-smoke-green.log）：PNG+hyperlink来源解除→同次改字→退出页签flush→草稿reload→单次保存修订2；重开开启链接→同次改有效共享owner→单次保存修订3。原owner/弃用own按意图保持、正文/图片/超链接/媒体SHA核验，pageErrors=[]。HTTP仍为mock，patch_docx及ZIP/媒体读取真实。前面“链接改变后同槽须分次保存”的限制已由该闭环解除；新增分节符与链接仍需分次保存，未知关系类别/循环依赖等只读边界仍在。

统一构建：最终tsc+Vite exit0、39.02秒（/tmp/office-header-row-hfsame-build.log）；check:budget与test:budget均exit0，预算契约日志/tmp/office-header-row-hfsame-budget-contract.log。实测workbook-main245.4KiB、docx-main197.3KiB、workbook-engine427.5KiB，未提高预算。本次构建覆盖最终创建helper映射/标题行/formula及Word同槽保存生产代码；后续若仅调整smoke就绪判据不需重复构建。

标题行最终GUI通过（/tmp/table-header-row-gui.log，Chromium140）：source双表+totals，关闭→undo/redo→草稿reload→实际保存修订2并重开→上方空行恢复标题保存修订3。headerless range A2:B4/headerRowCount0、XML列名、源data/totals及Other整table XML保持，pageErrors=[]。恢复后activeRange停A1的原因经临时只读facade/hit-test probe确认为render-canvas尚不可点击，点击命中了初始化容器；最终等待真实canvas hit-test后同坐标实际点击通过，移除probe，未修改生产来迁就测试。git diff --check通过，代码未提交/推送/部署。

下批独立只读核对的真实缺口（非完整清单）：P1 Word选区高亮/上下标（固定源Ribbon selection.setMark，本地仍整段且formatRange拒highlight）；P1 XLSX工作表scope定义名称（源NameManager可选sheet，本地只读全局、reader跳过localSheetId）；P2 Word脚注/尾注增删改（源references/review-actions具入口，本地按钮待迁移，底层patch已有notes部件能力）。应分别实施区间run保留/UTF-16边界、scope稳定身份及局部优先级、hash锚定notes引用与separator保留，不将纯文本支持混称复杂note全量完成。以上均尚未实现，完整xlsx/word对齐目标保持未完成。

### 2026-11-10：Word选区高亮及上下标；局部名称与注释集成中

Word formatRange增加highlight（含none）和vertAlign（baseline/superscript/subscript），沿用UTF-16边界及run拆分，只修改目标字符属性，保留区间外rawRPr。主视图非空单段、可锚定简单选区使用区间协议；折叠光标保持原有段落入口，复杂内联/跨段仍有限制。后端15项通过（/tmp/word-selection-backend-green.log），前端相关5文件57项通过（/tmp/word-selection-related.log），新增helpers45项通过（/tmp/word-selection-final-helpers.log）。Chromium140实际GUI完成4个修订，覆盖😀B高亮/上标、undo/redo、草稿恢复、清除none/baseline及下标，区间外run保持，pageErrors=[]（/tmp/word-selection-gui2.log）。HTTP仍mock，DOCX patch与ZIP回读真实；本批统一构建尚待其他生产模块稳定。

XLSX局部名称已接名称管理器scope、稳定sheetId、scope差分与保存时localSheetId定位。主视图7项通过（/tmp/name-scope-main-second.log）；Chromium140 GUI通过（/tmp/name-scope-gui.log），覆盖全局及两工作表同名Rate、新建/编辑、undo/redo、草稿刷新、真实openpyxl保存重开及print area保持，pageErrors=[]。随后独立review发现AI accept/undo重建workbook后installer仍绑定旧core，正在修复；上述GUI不覆盖该重建路径，不能据此标记局部名称最终验收。

脚注/尾注独立核心19项及真实ZIP后端10项通过（/tmp/docx-notes-final-green.log、/tmp/word-notes-backend2.log），共享编辑器/历史/草稿/GUI仍在验收。额外正在核对未建模正文（如表格内）引用是否被完整纳入删除身份校验；未核实前不宣称所有引用安全删除。复杂note文本编辑、同来源段正文与note混改等边界仍需继续对齐。此处为阶段证据，完整目标未完成。

本批补验：局部名称installer改为实时Workbook匹配，重建core后CRUD及undo/redo通过（/tmp/scope-name-core-recreated.log）。独立review发现的所属表未限定引用不迁移和opaque localSheetId重排丢失均已修复；同时修复官方Univer对其他工作表局部引用错误迁移，以官方SheetInterceptorService在同次历史中补正。前端9项通过（/tmp/scope-cross-final.log），真实openpyxl实体表名插行1项通过（/tmp/scope-structural-openpyxl.log）。root主视图新增行+列插入→undo/redo→草稿重开→真实engine保存回读通过（/tmp/name-scope-main-structure-final.log）：Sheet1 Local由$A$1至$B$2，Other同名Local仍$A$1，保存没有多余名称diff覆盖结构迁移。engine CLI已重新bundle，来源说明与hash已刷新。

Word注释主视图35项通过（/tmp/word-notes-main-final.log），独立module20项通过（/tmp/docx-notes-merge-green.log）：包含PM自动合并相邻text后的删除比较。真实ZIP15项通过（/tmp/word-notes-backend4.log），覆盖所有document.xml引用与建模引用(kind/id/count)核对，表格/隐藏/未建模引用使notes能力关闭但普通正文仍可编辑；未修改复杂entry与separator保留。复杂文本编辑仍只读，删除改按全部来源引用是否可编辑独立判定，已有真实ZIP单例通过（/tmp/word-notes-complex-delete.log）。

Chromium140注释GUI通过（/tmp/word-notes-gui6.log）：脚注/尾注新增、pending文字修改、CtrlZ/Y、草稿刷新、修订2保存；重开更新脚注并删尾注保存修订3；重开删脚注保存修订4，正文恢复、pageErrors=[]。插入id由服务端分配，已有entry/ref均hash锚定；修复模态关闭后rAF迟到focus覆盖下一次真实点击光标的问题，最终GUI明确等待PM选区更新。HTTP仍mock，DOCX patch、文件下载回读和ZIP检查真实。同来源段正文+insert/deleteNote混改仍有限制；updateNote不改marker，已允许与正文同批。自定义表样式DXF读取显示的新独立缺口已实际RED确认，尚未实现。统一构建与预算结果待另记。

本批最终补验：删除行列时官方interceptor仅传range，现从原始by-range命令按range身份恢复真实unit/subUnit；所有global/local registry entries按实际目标表计算期望迁移，用同次官方历史覆盖错误结果。root插入/删除行列两项主视图通过（/tmp/name-scope-main-structure-delete.log）；非当前表删除另抓到global qualified引用被错误迁移，修复后root强化实际下载文件globals回读通过（/tmp/name-scope-main-inactive-saved-globals.log），独立与main原反例两项通过（/tmp/scope-inactive-all-registry.log）。

最终tsc+Vite构建exit0、39.41秒（/tmp/office-scoped-names-word-notes-final-green-build.log），预算和预算契约均exit0（/tmp/office-scoped-names-word-notes-final-budget.log、/tmp/office-scoped-names-word-notes-final-budget-contract.log）。名称管理沿自然功能边界拆chunk，main240.0KiB、engine424.9KiB、names14.8KiB、docx-main211.2KiB，未提高预算。构建产物Vite preview的名称GUI闭环已验证（/tmp/name-scope-production-chunks-gui.log），早于最后inactive globals补丁；该补丁由实际主视图/下载回读证明，不混称为生产HTTP验收。新批Word混编与XLSX DXF/filterButton已有独立预期RED测试，未计入本批通过，完整suite没有重复执行。git diff --check通过；代码仍未提交/推送/部署。全量对齐仍未完成。

### 2026-11-10：XLSX已有自定义样式、筛选按钮与Word同段混编（本批进行中）

筛选按钮按固定源TableEdit.filterButton：reader读取autoFilter存在态并以nativeFilterButton元数据进入实时模型；新独立owned mutation使用官方TableManager清除/恢复条件并触发过滤行重算，不改手动隐藏行、表范围、单元格或其他表。root接Table Design checkbox、保护/标题状态、主视图installer/guard/dispose及保存差分；标题隐藏/恢复同步filter元数据，省略与engine默认相同的冗余filter字段。ribbon先RED后GREEN（/tmp/table-filter-button-ribbon-red.log、/tmp/table-filter-button-ribbon-green.log），root界面+主视图34项通过（/tmp/table-filter-button-root-related.log），含保存真实文件/undo/草稿重开。独立module5项通过（/tmp/table-filter-button-header.log），engine1项通过（/tmp/table-filter-button-engine.log），覆盖关闭清criteria、开启ref排除totals、无header=false、原false来源、core重建、保护/伪造mutation拒绝。

Chromium140筛选GUI初步通过（/tmp/table-filter-button-gui-final.log）：关闭→undo/redo→草稿reload→真实保存修订2、重开开启→保存修订3，源cell XML保持，pageErrors=[]。首次保存等待失败在重建CLI后解除；第二次等待失败是smoke save response缺editor.openUrl，产品按契约正确展示锁定说明，补齐mock后通过，不为此修改生产。额外正补最后修订界面重开、其他表XML及filter ref/criteria独立核验。HTTP仍mock，不宣称生产HTTP验收。

已有自定义tableStyle读取/显示已独立实现并初验：读取DXF palette，复用现有颜色解析与官方RangeThemeStyle/renderer副本；原styles/cells不写回。reader/renderer真实ZIP+Univer回归在推进，交叉review已发现并修正渐变通道平均应向下取整、none/无style边框不作为有效outline fallback。复杂格式未超固定源reader字段扩展；不加入自定义样式authoring。Word同段混编新final-run计划首批前后端RED已转绿，异常引用/软换行/主视图与GUI仍待；不据首批核心通过宣称完整闭环。本批尚待统一构建/预算与最终证据补记。

筛选按钮最终GUI强化通过（/tmp/table-filter-button-gui-final-reopen.log，Chromium140）：修订3界面重开再次回显开启；Staff autoFilter ref=A1:B3排除totals、旧filterColumn不复活，Other整table XML原样，所有source cell XML保持，pageErrors=[]。自定义样式GUI像素反例仍待修：模型关行条纹但截图stripe计数7923保持（/tmp/table-custom-dxf-gui.log），定位为直接主题API未触发官方value/range change使Canvas cache不刷新；不可用getCellStyle绿色代替实际显示。正在复用官方theme mutation补标准重绘信号，并核对header/totals重建路径。

Word混编首轮扩展：前端core10+主视图37项通过（/tmp/word-notes-inline-main2.log），后端20项通过（/tmp/word-notes-inline-back-expanded.log），软换行来源保留另1项通过（/tmp/word-notes-inline-break.log）；跨段引用删除及伪造/重复source片段独立5项已持久化repo回归（test_docx_notes_inline_identity_review.py；/tmp/word-mixed-repo-identity-review.log）。本批浏览器及最终统一构建仍待，不标最终完成。

DXF最终浏览器补验通过（/tmp/table-custom-dxf-gui-final.log、/tmp/table-custom-dxf-gui-full.log）：header关后像素0/undo恢复6005；totals开启黄色3854/undo为0；stripe关闭7923→0，undo/redo、草稿刷新、修订2保存重开保持，styles.xml及sheet XML字节一致，pageErrors=[]。styleEdit使用官方SetWorksheetRangeThemeStyleMutation在既有owned transaction内发送标准刷新信号，不新增独立history或写cell；header/totals已有range事件实测能重绘，无额外无证据修改。root独立查看initial/stripe-off截图确认蓝色表头红字保持、条纹按操作消失（/tmp/custom-dxf-initial.png、/tmp/custom-dxf-stripe-off.png）。reader及独立review6项通过（/tmp/table-custom-reader-final.log），刷新相关29项通过（/tmp/table-style-repaint-green.log）。尚待统一构建预算。

Word同段混编最终GUI通过（/tmp/word-notes-inline-gui3.log，Chromium140，四修订，pageErrors=[]）：先打字再在当前UTF16位置插注、继续改字与选区高亮/上标、undo/redo、草稿恢复后续写、真实保存重开；再同段删除脚注/改字/新增尾注并保存；最后保留尾注继续改字保存。来源A😀/原italic尾段保留，当前offset5没有误切来源offset5。新增patchParagraphRuns只发单调来源UTF16片段、继承文字、既有引用身份、新note operationIndex；服务端保留原rawRPr/链接元数据并分配新id，整批校验后一次写正文及notes。普通anchor editable未放宽；note-safe专用格式anchors允许marker旁选中文字格式，marker本身不加mark。相关helper56项通过（/tmp/word-notes-inline-helper-green.log），跨段独立身份5项已持久化repo；新core孤立UTF16代理项真实RED→GREEN并确认不产出文件（/tmp/word-notes-inline-malformed-red.log、/tmp/word-notes-inline-malformed-green.log），前端负例1项通过（/tmp/word-notes-inline-front-unicode-green.log）。已有notes text insert/update原链路已拒绝相同非法Unicode，2项通过（/tmp/word-notes-inline-note-unicode-red2.log，虽名red实为通过，未为此改notes validText）。

仍有明确边界：空来源段落先输入文字后混编缺少可继承run，下一批继续补齐；复杂inline/不透明属性不支持的变更、段落layout与混编同批仍限制。新协议不能复制/移动/漏删marker、伪造来源/新note id；source切片不可重叠或切开代理项。未将本批简单notes-safe段落闭环等同全部Word功能对齐。

最终统一tsc+Vite构建exit0、39.01秒（/tmp/office-dxf-filter-word-inline-build.log）；预算与预算契约均exit0（/tmp/office-dxf-filter-word-inline-budget.log、/tmp/office-dxf-filter-word-inline-budget-contract.log），main241.2KiB、engine426.5KiB、docx-main219.4KiB、table-design21.7KiB、新独立table-style-read4.0KiB，未提高预算。源hash和说明已更新；git diff --check通过。构建产物custom GUI补验进行中。代码仍未提交/推送/部署，完整目标未完成。

构建产物custom DXF补验已通过（/tmp/table-custom-dxf-preview-gui.log）：lazy-workbook-table-style-read-Cf5YkAxY.js三次响应200，header6005、stripe7923→0且重开保持0，totals3854；undo/redo、draft恢复、revision2保存重开、styles.xml及sheet XML字节保留、pageErrors=[]。新增smoke最初chunk URL断言未匹配lazy前缀，修正测试匹配后通过；无生产代码变动。仍为mock HTTP + 真实patch/ZIP/browser验收。

### 2026-11-10：XLSX模拟运算表与Word单元格底纹、空段注释

XLSX Data Table按固定源三字段/三布局运行原生Univer公式服务，不创建TABLE公式，不引入外部provider。manual模式强制计算，2秒无事件fallback保持源等值输入行为；输入原值恢复、结果缓冲后一次静态写入。官方batch对多次输入写入正序追加undo，现仅在本batch内按命令组逆序重排undo，真实一次undo/redo证明输入和结果均恢复。模块11项通过（/tmp/data-table-module-final.log），另公式输出以=开头字符串与#DIV/0!静态文本的实际XLSX回读2项通过（/tmp/data-table-static-text-output.log）。保护/重入/失败progress/取消/同id核心重建/写命令拒绝均有实证。

root接Data入口、异步dialog、grid/ribbon/AI运行锁、保存锁及中间草稿隔离，等待既有persistence后再代入。dialog1项通过（/tmp/data-table-dialog-green.log），ribbon/main相关31项通过（/tmp/data-table-root-related.log）。额外等待期间换表真实RED→GREEN（/tmp/data-table-target-wait-red.log、/tmp/data-table-target-wait-green.log）；再补直接命令服务undo可绕过inert反例，命令服务拦截后窄GREEN（/tmp/data-table-busy-undo-green.log）。undo拒绝复用CustomCommandExecutionError并清理该命令栈项，批次内部rollback仍可恢复。

Chromium140 GUI通过（/tmp/data-table-gui2.log）：manual、一次undo/redo、draft刷新、真实patch保存、openpyxl下载回读、revision2页面重开，输入D1=10与原B1公式=D1*2保持，只有B2=6/B3=10两项静态结果diff，pageErrors=[]。首次smoke在Home页找undo导致失败，修正为源File页后通过，无为此修改产品。

Word单元格底纹使用独立shadingEditable，不借正文editable错误限制rich runs。caret、CellSelection、整表NodeSelection沿用固定源selectionCell已有目标色则整次no-op语义；前后端重放/身份验证只接受fill的HEX或null，改直接tcPr/shd，无色删除直接shd让tblStyle继承。复杂merged/nested/revision表仍明确只读，同cell正文/结构与底纹同批仍限制，不能称全部表格格式已对齐。

独立helper20项通过；真实ZIP13项完成（首轮11项通过，2项暴露core.xml修改后，修复并只重跑2项通过：/tmp/docx-cell-shading-zip-two-final.log）。shading-only保存进入既有不触碰core metadata策略。ZIP文件part集合及所有非document部件字节相同，document仅目标shd变化；目录entry顺序属于打包差异，不作为内容契约。Chromium140 GUI通过（/tmp/docx-cell-shading-gui-final.log）：caret绿、整表紫、undo/redo、无色继承浅蓝、draft、真实patch保存重开，rich runs及styles/rels/core/header保持，pageErrors=[]。root独立查看green/reopened截图确认颜色/超链接/粗体保留。

以上GUI HTTP路由用mock，inspect/patch/ZIP/openpyxl/浏览器操作真实，不宣称生产HTTP验收。Word空段注释和统一构建证据待后续补记。全量对齐仍未完成，下一批Goal Seek及Word cell borders只读/RED核对中。

Word空来源段混编已补齐：Block.emptyRun仅在原runs为空时提供，经正常buildRun/runResolveOf解码来源属性。多空run按属性取末次显式值，pPr/rPr优先覆盖；opaque如noProof保留，pStyle有效格式只用于显示，不物化为新直接字体/字号。前端空段继承3项通过（/tmp/word-empty-notes-front-green2.log），相关notes/inline/recovery69项通过（/tmp/word-empty-notes-related.log）；后端空段5+既有引用身份5共10项通过（/tmp/word-empty-notes-back-final.log）。

Chromium140空段GUI最终通过（/tmp/word-empty-notes-gui-final.log）：Arial22斜体空run先输入新增😀后插脚注、undo/redo、draft刷新、实际保存下载重开；随后pStyle段输入Latin并插尾注再次保存重开，computedStyle为Cambria/21.3333px/italic/600，原pStyle样式与无direct override的ZIP断言通过，pageErrors=[]。首次对中文字强求仅ascii/hAnsi字体Cambria的断言错误，实际东亚主题字体符合源；改Latin验证对应字符集后通过，无为此修改产品字体选择。

本批最终统一tsc+Vite构建exit0，Vite40.51秒（/tmp/office-data-table-empty-shading-build.log），check:budget及test:budget均exit0（/tmp/office-data-table-empty-shading-budget.log、/tmp/office-data-table-empty-shading-budget-contract.log）。workbook-main249.7KiB/250、engine426.5KiB/428、docx-main225.4KiB/250，未提高预算。本批没有调整chunk映射；GUI使用dev实际模块，未将它宣称为新构建产物GUI验收。source说明及parse/types SHA已更新，git diff --check通过；未提交、推送或部署。新Goal Seek与cell borders仅只读/RED，完整对齐仍未完成。

### 2026-11-10：Goal Seek、合并计算与Word边框/notes布局

Goal Seek按固定源割线法（100次、绝对误差0.001）调用原生Univer计算，自动/手动、初值已达目标、非线性、公式错误/无解恢复、空输入、保护/非法值/重入、dispose与同id新core保护已由12项定向测试证明（/tmp/goal-seek-module-final.log）。源逐guess journal历史保留，没有虚称单次undo。root复用模拟运算表的计算锁，运行中屏蔽中间草稿及保存，等待既有persistence后复核core/工作表身份。三字段dialog1项通过（/tmp/goal-seek-dialog-green.log）；main成功真实保存回读通过，失败回归最终1项通过（/tmp/goal-seek-main-failure-green.log）。最初失败断言匹配了对话框静态说明“未找到解”，在实际运行未结束时抢读save disabled；改为role=status后通过，无产品改动。

GoalSeek Chromium140 dev GUI通过（/tmp/goal-seek-gui.log）：manual求解10→15、逐guess undo→11/redo→15、常数公式无解恢复15、draft刷新、真实patch保存及openpyxl回读、revision2页面重开。最终只一项D1输入diff，原B1/F1公式保持，pageErrors=[]。

合并计算按固定源按位置五函数SUM/COUNTA/AVERAGE/MAX/MIN、按左列标签三函数SUMIF/COUNTIF/平均；源标签SUMIF的=及*条件语义保持，不为迁就用例自行转义。跨表空格/单引号引用、大小写匹配、不同尺寸、首次标签顺序、源重叠拒绝、公式替换、标签=前缀静态文本、保护和写前拒绝均有真实Univer证据。模块最终16项通过（/tmp/consolidate-module-final.log）。复用现有1m cell edit预算，在矩阵分配前检查；其常量提取到轻量workbook-edit-budget，未提高预算。标签扫描逐行原生core.getCell().v与官方getValues同语义，避免巨量空二维数组；root beforeWrite投影v/f调用既有10MiB/操作预算，异常发生在唯一原生命令之前。

合并计算dialog1项通过（/tmp/consolidate-dialog-green.log），主视图目标切换拒绝、公式计算、单次undo/redo、draft及实际保存回读通过（/tmp/consolidate-main-budget-green.log）。旧预算相关2例通过（/tmp/consolidate-shared-budget-final.log）；初次指定不存在workbook-find-replace.test.ts无测试执行，随后定位真实native-recovery用例，不将无测试结果当通过。Chromium140 dev GUI通过（/tmp/consolidate-gui.log）：West Side/O'Brien标签来源、未添加输入计入、undo/redo、draft、真实patch保存回读与revision2重开，来源sheet2/3 XML逐字节保持，只有结果标签/公式diff，pageErrors=[]。

Word单元格边框完整源菜单12模式、8线型、5粗细、颜色及默认pen已接真实ribbon；caret作用整表、CellSelection矩形、NodeSelection全cells；none明确六边none并清全表insideH/V，保留其他cell未命中边。表hidden有序steps协议从可信table hash/cellIds重放，不从最终PM猜模式。独立helper24项分批通过，正式ZIP14项（初始2与新增12）通过（/tmp/docx-cell-borders-zip-green.log、/tmp/docx-cell-borders-zip-guards.log）。源没有50步限制，review发现照搬结构限额后已移除，并以51steps回归证明。额外发现backend capability无源依据10000cells限制，正以独立RED补修，不先宣称全部最终验收。

Word边框dev GUI通过（/tmp/docx-cell-borders-gui-final.log）：caret/整表红2px、首行选择绿dashed3px、undo/redo、首行none/全表inside清除、draft、真实patch/rev2重开，所有非document部件包括core/styles/rels/header保持，rich runs/底纹/未命中theme斜线保持，pageErrors=[]。首轮smoke只枚举docTableCell漏Header而选中第二行，实际产品按选择正确画线，修smoke后通过。root独立查看pen/reopened截图确认边框、底纹与原斜线保留。controls仅独立宽度换行改动，待built preview补验。

Word正文/notes+段落layout：保留普通editable，用paragraphLayoutEditable专用能力只开放既有对齐/左右缩进/间距4kind，服务端同一原pPr和run合成；草稿回放补exact hash、字段白名单、capability校验，不接受客户端XML或泛放只读。新增前端31、相关171（首169+修旧fixture后窄2）、后端新增11+既有39共50通过，见NATIVE_WORD_NOTES_LAYOUT_ACCEPTANCE.md及其实际日志。真实Chromium140两次patch保存下载重开通过（/tmp/word-notes-layout-gui-green1.log），既有footnote正文改字+新endnote+布局，后续仅layout+updateNote无多余runplan，pPr.keepNext/run.noProof保持，pageErrors=[]。段落样式/列表/边框底纹与notes混编、同表边框+底纹等仍有明确后续缺口，未据本批闭环宣称完整Word对齐。

边框backend无依据10000cells限额已移除，独立10100cells反例RED→GREEN（/tmp/docx-cell-borders-source-size-red.log、/tmp/docx-cell-borders-source-size-green.log）。该helper为backend-only，frontend只导纯spec，故仅重打edit-docx bundle（/tmp/docx-cell-borders-size-bridge-bundle.log）并窄测，不重复前端构建。built preview边框GUI通过（/tmp/docx-cell-borders-preview-gui-final.log），controls换行完整可见、边框/none/undo/draft/真实保存重开及ZIP保留均通过，pageErrors=[]。

陈旧审计修正：普通干净来源段落同次改字+局部格式、无note，实际已被main notes normalizer fallback的通用final-run链支持。真实PM输入新增并仅选新增bold、唯一patchParagraphRuns、严格草稿replay相等（/tmp/word-plain-format-pm-final.log）；真实DOCX patch+python-docx/ZIP回读保持pPr.keepNext/run.noProof及第二段、未创建notes parts（/tmp/word-plain-format-docx.log）。这不意味着所有来源已支持：整份文档notesAvailable=false时普通混编仍被全局notes能力耦合限制，属于下一独立缺口。此轮核查未改生产代码，不重复造相同功能。

本批统一tsc+Vite构建exit0，Vite39.86秒（/tmp/office-goal-consolidate-borders-layout-build.log）；预算及预算契约exit0（/tmp/office-goal-consolidate-borders-layout-budget.log及-budget-contract.log），main245.0KiB/250、engine426.5KiB/428、docx-main236.2KiB/250，未提高上限。按自然功能边界拆workbook-what-if12.1KiB与workbook-consolidate6.6KiB；built XLSX GUI新chunk实际加载/保存补验待最终结果。root相关35项首轮34通过，1旧ribbon仍断言consolidate禁用，更新为已启用后只重跑该项通过（/tmp/office-goal-consolidate-root-related.log、/tmp/office-goal-consolidate-ribbon-one-green.log）。

built XLSX GUI首轮reload后仅等ribbon与旧localStorage满足即点击save，未等loadOperations完成、监听器注册，导致没有save请求/状态仍“已恢复本地草稿”；诊断/tmp/goal-seek-preview-gui-diagnostic.log。测试已加入界面save-state aria-busy=false就绪判据，未为此改产品，定向复验中。不同于已通过的dev GUI，不把首轮preview超时称通过。

新构建产物最终GoalSeek与合并计算preview均exit0（/tmp/goal-seek-preview-gui-final.log、/tmp/consolidate-preview-gui-final.log）：workbook-what-if-xS2FwEgB与workbook-consolidate-MBXjkZTG均3次实际加载200，manual/undo/redo/失败恢复/draft/真实patch保存及revision2重开通过，pageErrors=[]。合并计算来源sheet XML保持、GoalSeek只有最终输入diff；首轮测试载入竞态已由真实就绪判据解除。仍为mock HTTP授权/修订路由与真实文件/浏览器验收，不宣称生产HTTP或桌面Office验收。

DataTable新what-if chunk构建产物回归exit0（/tmp/data-table-what-if-chunk-preview.log）：实际chunk3次加载200，manual、undo/redo、draft、真实保存重开、输入/公式保持及静态结果6/10通过，pageErrors=[]。本批补验全部闭环，完整对齐仍未完成。


### 2026-11-10：同表边框/底纹组合与普通正文独立混编（本批进行中）

同表边框与底纹已允许组合：从原表身份投影有序边框意图，为shading提供可信baseline，再完整核验边框终态；草稿规范输出border→shading。后端先对原始hash/能力整批校验，再逐条修改当前state.saved.xml的tcBorders/shd，避免后操作覆盖前补丁。前端11项通过（/tmp/docx-cell-format-combination-guard-green.log）；真实ZIP14项分批通过（原4、守卫9、交换顺序1：/tmp/docx-cell-format-combination-zip-green.log、-zip-guards.log、-order-identity.log），none→null与null→none所有part字节相同，未选中theme diagonal保持。两方向Chromium GUI保存重开通过（/tmp/docx-cell-format-combination-gui.log、/tmp/docx-cell-format-combination-shade-first-gui.log），undo/redo/draft及rich runs/其他ZIP保持，pageErrors=[]。结构、正文及伪造属性混合仍拒绝；未将此描述为所有表格组合修改已支持。

普通段落final-run混编已与全局notes能力解耦：duplicate-note或dangling-reference导致notes model不可用时，仅原editable普通paragraph可使用既有run编译链，保护/未知inline/外来hash/伪造reference仍拒绝；note操作仍要求原notesPlanner。前端ordinary先行，fallback失败抛回原错误保留其他布局/节诊断；纯正文草稿不重编号未知注释。后端9项（/tmp/word-plain-without-notes-back-green.log）、helper+main recovery38项（/tmp/word-plain-without-notes-front-green.log）及未知note编号/未知inline定向1项（/tmp/word-plain-without-notes-opaque-front-final.log）通过。Chromium真实保存下载重开通过（/tmp/word-plain-without-notes-gui-green.log），复杂notes部件/关系/Content_Types SHA保持，pageErrors=[]。详见NATIVE_WORD_PLAIN_RUNS_WITHOUT_NOTES_ACCEPTANCE.md。

以上浏览器HTTP授权/修订路由仍mock，inspect/patch/文件回读真实；统一tsc/Vite/预算与构建产物补验尚待XLSX分组读写链稳定，不先宣称本批最终验收。XLSX outline已查固定源handleOutline真实实现，本地缺reader/writer/model/operation和ribbon联动，正在单独补齐。完整对齐目标仍未完成。


Word本批交叉只读review补证：A组合新增多cell底纹穿插边框与纯反顺序所有ZIP part字节同值、错误hash/正文碰撞拒绝（/tmp/word-cell-combination-review-final.log），前端5边界及真intent-only伪造拒绝（/tmp/word-cell-review-forged-intent-final.log），未发现问题。B另12项独立探针通过，覆盖enforced保护、修订/域/绘图/pPrChange、重复plan/rawRPr注入和前端readonly提升尝试（/tmp/review-plain-fallback-boundaries.log、/tmp/review-plain-fallback-frontend.log）；不把临时探针称正式新增suite。

XLSX分组6个Data入口已启用；level/collapsed采用官方轴custom随结构移动，新增applySheetOutline严格协议仅补目标属性，保留原尺寸/样式/cells/其他部件，行writer改Map单遍避免逐项重扫。root主视图3项通过（/tmp/outline-main-three-final.log）：draft恢复/真实保存、组内插行继承、无autoFilter折叠行保存；ribbon定向1项通过（/tmp/outline-ribbon-green.log）。初轮GUI定位真正漏写：filters模块仅在autoFilter存在时写范围内hidden，不能接管所有原生隐藏行；新增真实RED后outline planner同时负责raw行列hidden差分，filter操作后置，仅对其range以raw+filter缓存合并覆盖。真实RED→GREEN日志/tmp/outline-row-hidden-red.log与-green.log；root新hidden测试启动时补丁已落地，/tmp/outline-main-hidden-red.log实际为GREEN，不能冒称独立RED。

Chromium140分组dev GUI最终通过（/tmp/outline-gui-final.log）：行分组/折叠、原生hidden undo/redo、列分组/折叠、draft刷新、真实Python native patch保存与revision2重开，行2/3 hidden及行4collapsed，列C/D hidden及Ecollapsed，原cell XML/行高40/列B宽30保持，pageErrors=[]。最初列选C1:D2用auto hide按源选择rows，且reload只等旧op存在；改为整列C:D并等待具体hidden/collapsed草稿状态后复验，不为此改变源auto轴语义。

额外真实撤销边界已修：undo delete时native insert mutation含trigger，不能按邻接填充恢复的原无custom/level0 gap（/tmp/outline-gaps-and-structure-final.log三窄例通过）；显式闭合sheetFormatPr先前造成重复节点，真实RED后修正保留原attrs且仅一个节点（/tmp/outline-formatpr-green.log）。初轮统一build exit0但engine430.1KiB超过428；已按自然outline模块拆chunk等待最终build预算，不提高预算。

范围仍有明确缺口：固定源outline-gutter.ts与App.tsx安装的边栏层级/加减控件、showOutlineLevel、Shift+Alt左右分组快捷键、显式行列hide/show、summaryBelow/Right切换及clear UI均尚未对齐。本批只交付现有6个Ribbon入口及原生保存基础链，不称完整outline交付，更不称完整xlsx/word对齐。


本批最终统一tsc+Vite构建exit0，Vite39.64秒（/tmp/office-outline-combination-plain-build-final.log）；预算与预算契约均exit0（/tmp/office-outline-combination-plain-budget-final.log、/tmp/office-outline-combination-plain-budget-contract-final.log）。outline前端/engine沿自然边界独立7.2KiB，workbook-main245.9/250KiB、engine427.4/428KiB、docx-main237.2/250KiB，无提高预算。原生分组module9项、engine4项、Python真实入口4项及最终bundle回读1项通过（/tmp/outline-module-final-9.log、/tmp/outline-engine-final-4.log、/tmp/outline-python-final.log、/tmp/outline-python-bundle-final.log）。engine与workbook-vendor按来源覆盖顺序合并manifest后逐文件SHA均匹配，git diff --check通过。

新built XLSX preview完整闭环exit0（/tmp/outline-built-preview.log）：lazy-workbook-outline-DzJ2zvAM.js三次实际加载200，hidden undo/redo/draft/真实native保存/revision2重开及row/col层级/折叠/原cells尺寸保持，pageErrors=[]。B新built Word preview完整闭环exit0（/tmp/word-plain-without-notes-built-preview.log），实际docx-main-CetCLxMW与native-docx-engine-DsROsJBD及全部已加载JS逐项SHA等于当前static；普通混编/草稿/history/真实保存重开及未知notes部件保持通过，pageErrors=[]。A新built组合业务完整走完，新增加载断言误漏lazy前缀导致最终断言失败，脚本匹配修正后定向复验中；不为此改产品，不把失败称验收成功。


A新built组合preview最终exit0（/tmp/docx-cell-format-combination-built-preview.log）：preview=true，docx-main-CetCLxMW、native-docx-engine-DsROsJBD、parse-worker-Dh5VkJt三轮加载200，336条JS响应全200；边框→none→绿色底纹、undo/redo/draft/真实patch保存/revision2重开通过，其他ZIP/rich runs/未触及theme斜线保持，pageErrors=[]。首轮仅独立smoke加载名称断言修正，无生产改动。本批三个构建产物GUI均已闭环；未提交、推送、部署或运行重复完整suite。全部目标仍保持未完成，剩余源功能按独立缺口继续推进。


### 2026-11-10：分组边栏/剩余菜单与Word段落边框底纹组合（本批验收中）

XLSX固定源outline-gutter.ts的绘制、列头扩展、geometry/viewport及睡眠paintLoop已迁移至独立workbook-outline-gutter.ts/-model.ts/.css，改用本地官方轴custom，host仅包grid；精确group与level callback重用同一核心，不修改选区猜目标。点击先比对真实workbook/sheet core，dispose释放事件/观察器/RAF并只还原同core原标题高度。headless无render直接返回空handle。6项生命周期用例均有有效GREEN；初次合跑遇环境暂停约70分钟动态import timeout，其他5通过，首项窄重验通过（/tmp/outline-gutter-loop-final-retry.log），不把超时日志称绿色。

核心新增read/groups/exact-toggle/showLevel/summary setters；summaryBelow/Right通过严格applySheetOutline可选字段保存，Python仅该op白名单接受可选字段，旧请求兼容。Univer11项（/tmp/outline-core-final.log），shared/boundary与null-selection clear各1项（/tmp/outline-summary-guards-final.log、/tmp/outline-clear-null-final.log），engine summary ZIP2项（/tmp/outline-engine-summary-green.log），Python旧4与重bundle后summary1项（/tmp/outline-python-summary-bundled-final.log）通过。原source summary切换不迁移已有collapsed flag语义保留。

root菜单增加显式行列hide/show、summary切换/aria-pressed及clear；Alt+Shift左右仅在非输入/非modal/非cellEditing、可编辑状态派发auto轴。新快捷键3项、ribbon新例1项、主视图summary+keyboard草稿保存1项先RED后GREEN。首次shortcut GUI对ribbon tab发ArrowRight被既有nav消费，改聚焦grid host（保留选区）后通过，无产品修改。完整actions dev GUI通过（/tmp/outline-actions-gui-final.log），明确轴/keyboard/clear/false汇总方向、draft/真实native patch保存/revision2重开，cells XML/原几何保持，pageErrors=[]。root相关41项串行复验通过（/tmp/outline-actions-root-retry.log）；此前并行运行遇同环境长暂停，34例中33绿、1超时及main import超时，保留原日志不计通过，不改超时上限。

边栏dev真实GUI完整通过（/tmp/outline-gutter-gui-final.log）：实际canvas inner/outer exact hit与rows/cols level1/2/3，nested保留，freezeB3/zoom110%/wheel滚动后远组点击，draft刷新/native保存/新修订重开，切Plain→新分组出现→clear消失→切回Outline重现，openpyxl核对远端rows20–22隐藏、原层级/summary及freeze/zoom，pageErrors=[]。万行性能样本仍在只读归因：jsdom真实metadata8次refresh双帧27.2–48.5ms且RAF稳定归零；真实浏览器10次滚动存在60–100ms LongTask，不能据此声称性能通过，正比较无边栏控制样本，未加缓存或人为改阈值。

Word同段setParagraphBorders+setParagraphShading组合已保留原hash/字段白名单并基于当前XML合成，只有这两属性可共存；其他正文/样式/分页/布局/notes仍拒绝。前端相关32、ZIP新增9+既有9、保护1通过；三修订dev GUI两顺序及同时清除/undo/draft/真实patch下载重开通过（/tmp/word-paragraph-combo-gui3.log），正文rPr/keepNext/其他ZIP SHA保持，pageErrors=[]。发现既有两op缺documentProtection守卫后以RED补齐，新增专门capability只影响两项，保护GUI四按钮disabled通过。能力复用现有纯字符串writer探测复杂源可写性，pattern/double源分别关闭对应flag；实际inspect源bytes/mtime/inode保持且不创建output。独立review验证中间hash/跨段伪造拒绝、多段交错合成、未知attrs/readonly仍拒绝（/tmp/review-word-paragraph-combination.log、/tmp/review-paragraph-combination-front.log）。详见NATIVE_WORD_PARAGRAPH_FORMAT_COMBINATION_ACCEPTANCE.md。

初轮统一build exit0但环境暂停使Vite70m32s，不作正常耗时估计；预算engine428.2超过428KiB。已将新增outline reader机械提取为独立outline-read.ts并随outline chunk，真实ZIP提取前后6/6通过，来源SHA更新。最终build/预算/构建产物preview待实际结果；不提高预算、不先声称本批最终通过。完整xlsx/word仍未对齐，目标保持未完成。


首轮拆outline-read后的统一tsc+Vite已exit0，37.49秒，预算与预算契约均exit0（/tmp/office-gutter-summary-paragraph-build-final.log、-budget-final.log、-budget-contract-final.log）。engine427.9/428KiB、main247.7/250KiB、docx-main237.6/250KiB，未提高预算。actions新构建preview通过（/tmp/outline-actions-built-preview.log），keyboard/clear/explicit axes/summary、draft/真实保存/rev2重开、pageErrors=[]。

但万行性能controlled对比证明边栏有真实开销，不能在此结束验收：同一source/viewport/10次wheel，启用边栏RAF max38.2ms/mean1.737ms、LongTasks10个60–100ms，dispose后max0.3ms/mean0.040ms、LongTasks0（/tmp/outline-gutter-controlled-perf.log）。已授权gutter实例级数据缓存，仅command/explicitrefresh/core或sheet切换失效、Scroll/Resize/theme只绘geometry；先RED再修，尚未验证完成。后续该唯一生产修复需要最终重build及built gutter验收，不将上述构建称最终交付。


边栏性能后续取证纠正：早期controlled样本含fillText glyph hook，hook每次读DOM几何，不能将其全部开销归因产品。关闭hook、等待启动稳定后仍确认scroll触发sheet.operation.set-scroll与sheet.command.set-scroll-relative使缓存失效。最小修复为gutter实例缓存、仅这两个纯滚动命令不失效；其他command/explicit refresh/core或sheet替换保持失效。新增readWorkbookOutlineSummary仅读sheet custom metadata，main summary状态不再扫描行列。两条RED及focused GREEN见/tmp/outline-gutter-scroll-command-red.log、/tmp/outline-summary-red.log、/tmp/outline-cache-summary-green.log；失效/newcore两项GREEN见/tmp/outline-cache-invalidation-green.log。

无glyph hook最终万行10次wheel样本/tmp/outline-gutter-controlled-perf-final.log：metadataReads=0，meanRAF1.40ms/max40.4ms，仍10个67–99ms LongTask；dispose mean0.036ms/无LongTask。分段paint各段通常小于2ms，仅首次lazy skeleton尺寸更新重建1次groups；剩余全页LongTask未完成CPU归因，不称性能完全对齐，不追加猜测cache。

最终缓存修复统一tsc+Vite exit0，Vite37.24秒（/tmp/office-outline-perf-final-build.log）；预算及预算契约均exit0（/tmp/office-outline-perf-final-budget.log、/tmp/office-outline-perf-final-budget-contract.log），engine427.9/428KiB、main247.7/250KiB，未提高上限。built gutter GUI待实际结果。

Word段落组合最终built preview与保护preview均通过（/tmp/word-paragraph-combo-built-preview-final.log、/tmp/word-paragraph-combo-protected-built-preview-final.log）。本次XLSX-only重build后Word产物SHA未变：lazy-docx-main-umqu0fnf.js为33820de1724f4d79f1e3af4eaa34ee8470961dc72c3cd768dc209d9dfa6caa48，lazy-native-docx-engine-DsROsJBD.js为29e787ebfd5fe24856ad8b1d9a5eadc96cbb2ca04e8b2f9d7711f39c42af35a6；不重复相同Word GUI。


最终built gutter GUI仅执行一次且exit0（/tmp/outline-gutter-gui-built-final.log）：Chromium140、267个实际JS响应全HTTP200，关键响应SHA与static一致；exact inner/outer/nested、行列level、freezeB3/zoom110%/wheel后远组点击、draft刷新/真实Python patch保存/openpyxl校验/revision2新core、Plain新组出现/clear消失/切表恢复均通过，pageErrors=[]。上述GUI授权/修订HTTP为mock，Python补丁及ZIP文件/浏览器真实；保留剩余全页滚动LongTask限制，不宣称全量功能或性能完成。

### 2026-11-10：选区缩放、工作簿统计与普通正文段落格式合成（进行中）
固定源重新只读取证：ribbon-actions.ts:919–960按真实skeleton累计尺寸与viewport实现zoom-to-selection，本地按钮仍disabled，已有zoomScale写回可复用；源:1183 workbook-statistics实际只反馈snapshot全表统计，不存在对话框，本地仍disabled。分别交独立agent实现，root负责main/ribbon集成，统计不得标记草稿。Word已用真实DOCX探针确认普通正文/局部格式与段落边框底纹同批被前后端拒绝，源setNodeMarkup保留正文；独立agent实施最终run与两属性合成，保留原hash/capabilities/文档保护。上述新任务尚未验收，不计完成。

工作簿统计独立3项GREEN（/tmp/workbook-statistics-green.log）按完整snapshot统计隐藏表、0/false/空格、稀疏数据和公式独立计数，读取不改模型；当前本地确为完整readWorkbook并逐cell投影，无lazy选项猜测。dev GUI /tmp/workbook-statistics-gui.log通过真实editable+protected与test-only editable=false状态的同一按钮/handler，2表5值1公式、重复点击draft不变/save请求0/pageErrors=[]。editingEnabled=false实际隐藏整个编辑入口，不能称该入口已提供只读ribbon。root View/readonly-protected相关2项与Review相关3项GREEN（/tmp/workbook-view-stats-ribbon-green.log、/tmp/workbook-stats-review-green.log），解除新两命令禁用并保留统计纯读。
选区缩放真实GUI定位新适配问题：Univer scroll-to-cell在已在视口内时也return false，且forceTop/Left检查在其后；zoom为operation不会被主视图mutation监听自动标dirty，不能用scroll false抹去已实际应用的zoom。正按源无害no-op语义修正，并核对异步回执前后真实core身份；修复与GUI待实际结果，暂不计交付。


选区缩放生产修复已冻结：实际getZoom确认缩放，scroll false按固定源合法no-op保留修改；scroll throw与同core换sheet返回具体诊断且仍保存原sheet缩放，新workbook/dispose在zoom与scroll两个await后均复核core避免误记草稿。11项针对性验证有效GREEN（首9见/tmp/workbook-zoom-selection-observed-green.log，末2见/tmp/workbook-zoom-selection-final-core-guard.log）。独立review确认source geometry/readonly/core边界；root修正只读反馈只去掉未保存后缀，保留异常和切表原因，并用独立view-ready getter在加载/保存时禁用选区缩放按钮（/tmp/workbook-zoom-ready-ribbon-green.log 1项通过）。dev GUI最终/tmp/workbook-zoom-selection-gui-final.log exit0：132%、draft恢复/唯一applyPageSetups真实保存/revision2 footer132%，freeze C3、row2=40/colB=30、原cells及其他ZIP part字节保持，pageErrors=[]。早期失败与定位日志保留，不计GREEN。

Word普通body/局部格式+边框底纹完整组合已freeze，仅扩展属性提取与后端generated当前rawPPr，不增加协议、不得用原XML覆盖最终runs。24前端、21新增ZIP通过；既有31后端初30绿1红准确发现原source普通但本批insertNote越界，一行增加最终runs无noteRef检查后该项与4关联负向窄测GREEN。两种dev来源（notes可用/真实损坏notes全局不可用）各3次保存下载、draft/undo/clear/rev4重开/非document ZIP SHA保留均通过。独立只读review核对hash/capability/保护/重复/新旧noteRef/rawPPr透传，无新增阻断发现。详见NATIVE_WORD_BODY_DECORATIONS_ACCEPTANCE.md。notes引用段落与其他style/pageBreak/layout组合仍是独立未完成范围。

本批统一tsc+Vite exit0，37.76秒（/tmp/office-zoom-stats-body-decorations-build.log），预算及预算契约exit0（/tmp/office-zoom-stats-body-decorations-budget.log、-budget-contract.log）：main248.9/250KiB、engine427.9/428KiB、docx-main237.8/250KiB，新zoom模块独立2.3KiB，未提高上限。按SOURCE→LOCAL-ADAPTATIONS→UPSTREAM-PATCHES覆盖顺序核对engine105文件SHA全部一致；vendor按SOURCE→LOCAL-ADAPTATIONS核对11文件全部一致。首次验证脚本遗漏LOCAL清单产生差异，补齐既有文档规定的覆盖顺序后通过，无修改源manifest。三个agent分别做本次最终构建产物GUI，结果待实证，不预记通过。


本批最终三个构建产物闭环全部通过：statistics /tmp/workbook-statistics-built-final.log仅一次preview、真实保护表2表5值1公式、重复点击草稿不变/save0/pageErrors=[]；90个JS响应全200，main DRxdOZRZ响应SHA等于static。zoom /tmp/workbook-zoom-selection-built-final.log仅一次preview，132%→draft刷新→真实Python保存→revision2 footer132%，freeze C3/原尺寸/cells/其他ZIP entry字节保持，main与zoom CZrec1pd三次实际加载全200且SHA等于static，pageErrors=[]。

Word普通来源/tmp/word-body-decorations-built-preview-final.log与notes不可用来源/tmp/word-body-decorations-no-notes-built-preview-final.log各一次最终preview，均三次真实保存下载、草稿/history/同时清除/最终重开通过；原noProof/keepNext/未改段落和所有非document ZIP身份保留，pageErrors=[]；全部实际JS200且SHA等于static。docx-main uUigo26P SHA b9e0352cb4eee6618106fdd9abe370456bd451759b80c82e38e856f4aaf31227；native-docx-engine DsROsJBD SHA29e787ebfd5fe24856ad8b1d9a5eadc96cbb2ca04e8b2f9d7711f39c42af35a6。HTTP授权/修订路由仍mock，不称生产HTTP或桌面Office验收。未提交/推送/部署，未重复完整测试。

全量xlsx/word对齐仍未完成。本轮关闭选区缩放、工作簿统计、普通body+段落边框底纹三项明确功能缺口；含notes段落的装饰混编、其他段落属性组合、XLSX其余disabled源功能以及既存宿主差异仍需继续逐项核查实现。outline全页滚动LongTask仍有未归因限制，不能因功能GUI通过宣称性能完整对齐。目标保持active。


### 2026-11-10：notes段落装饰混编、完整缩放选择与插入函数（进行中）
上一轮已产出代码、测试与最终浏览器证据，归类为实际进展。本轮继续固定GenOffice f8c17004逐项取证，不调整完整目标。三个同模型agent分别负责：含notes段落正文/局部格式+边框底纹；源ZoomDialog及View六快选；源两阶段InsertFunction目录→参数/preview/range-pick→captured cell写入。root独占main/ribbon/vite集成与最终构建。
源ExcelShell:3345 View六快选50/75/100/125/150/200，footer打开完整ZoomDialog（五radio预设、fit、自定义整数10–400与取消）。root已接View原六值菜单及完整dialog入口，callback捕获并复核真实workbook/sheet core；新单测先RED后GREEN（/tmp/workbook-zoom-dialog-ribbon-red.log、/tmp/workbook-zoom-dialog-ribbon-green.log），验证保护/只读视图门禁、六值与busy禁用。尚待真实GUI/保存重开，不计交付。
插入函数源实际含完整运行时目录/15分类与Recent/All/search/syntax、动态参数/重复参数/嵌套call、引擎预览和范围选择；将优先复用源与Univer，不造简版计算器。当前本地无desktop linked-workbook宿主，外部picker保持独立未完成缺口，不静默空列表宣称全量支持。notes装饰通过notesPlanner与可信reference block单独能力开放，仍保留全局editable=false与字段白名单、保护、来源身份，未预记通过。


本轮root已接入函数host完整open/category/onWrite/dispose，单独函数chunk；原source分类按钮先RED后GREEN（/tmp/workbook-functions-ribbon-red.log、/tmp/workbook-functions-ribbon-green.log）。新增组件初始化兼容无injector/无menu/description的headless宿主；旧outline真实主视图恢复+保存窄测通过（/tmp/workbook-dialogs-main-startup.log）。随后官方footer接入与preset配置改变后，仅按新增变更复验该启动/保存路径，通过/tmp/workbook-zoom-footer-main-startup.log；功能区相关单文件33项通过/tmp/workbook-functions-zoom-ribbon-final.log，并非重复项目完整suite。

完整缩放View已接六快选与源完整dialog，root将旧+/-/reset重复同步逻辑统一复用actual-zoom/core校验helper。footer百分比原来为Univer内部useState快菜单，无官方open command；源App:2226本就关闭native zoomSlider。本地依同样preset zoomSlider:false，通过官方IMenuManagerService/ComponentManager在既有footer中渲染源等效−/range/+/%四控件，无native DOM替换。真实mount发现外层menu会把button冒泡当未注册command，独立no-op operation与label阻止冒泡后已修。/tmp/workbook-zoom-dialog-official-footer-final.log exit0：唯一四控件、百分比完整dialog、step100→110→100、range101实际草稿、Other75↔Summary100同步、六快选/fit132/custom137 Enter/cancelclean/draft/真实保存/rev2重开、保护表及freeze/geometry/其他ZIP保全，pageErrors=[]。本批最终build待Word与函数新guard收尾。

插入函数完整dev GUI /tmp/function-dialog-gui-fourth.log通过Financial/search SUM/引擎preview5/真实grid pointer range pick/写captured C3/draft reload/Python patch/openpyxl/rev2现有SUM直接参数编辑，pageErrors=[]；61个source fallback名称live hasExecutor全部true。源RATE等额外numerical修复仍待独立核对，不把registry presence称完整计算对齐。最初range拾取脚本误选屏外测量canvas，导航日志未见额外reload；改用可见大canvas后通过，未为此改产品。独立review发现setValue同步事件可能换同id新core后仍onWrite，临时RED /tmp/review-function-host-write-core.log，已交owner加写后/通知前身份复核，未预记最终验收。外部workbook picker仍为显式未实现宿主缺口。


本轮Word notes装饰与标记后输入生产已freeze：前端相关25及既有notes/plain六文件68共93项GREEN，backend notes/装饰/新继承共44项GREEN（/tmp/word-note-reference-input-zip-regression.log）；两个notes装饰dev样本与独立标记输入dev（/tmp/word-note-reference-input-gui-final.log）均通过真实保存/草稿/history/删除引用保留文字，未先验当最终built验收。
notes装饰cap仅notesPlanner可信建模+editableNoteReferenceBlock+既有writer来源探测，原global editable仍false；frontend逐source marker核note entry.references的block/hash/kind/id/共用referenceIndex，后端独立验证原块/notes身份，再合成当前generated rawPPr。独立review未见新来源反例。review曾静态推断layout+decor会产无效草稿，真实Editor临时probe证实normalize的属性投影已先明确拒绝，未产operations或进入replay（/tmp/review-notes-layout-decor.probe.log）；属于既有未实现组合，不登记为新增BUG。
独立marker输入BUG以源PM继承真实marker opaque marks为依据：沿用同hash source inheritFrom，只复制可信Run格式并去掉noteRef生成普通文字；不要求源marker最终仍保留/邻接，因为既有普通text继承允许来源run被删除/位移。marker引用本身仍须保留或有合法deleteNote，字段白名单/UTF16边界/foreign hash守卫保持。第一版保真测试发现source marker parser仅rawRPr没有managed模型值，生成普通文字会丢superscript；最终改parse.ts noteRef分支复用已有buildRun(...keepEmpty=true)，保留原rawRPr与引用身份，不再复制ZIP/二次parse或手写属性解析。SOURCE与UPGRADE已登记，当前parse.ts SHA89859d2c2d535c3e528c1da1fe1b87cfda7bc6d2a9caa65a2581da75ca13fe11实文件匹配。

函数物理fx进一步实证：本地原preset header:false/toolbar:true不挂载formula bar，已按固定源App:2213改为header:true/toolbar:false（只显示namebox/formula，避免重复native toolbar）。其后物理bar/fx均1个，但host构造fxHas=false导致永未订阅；新refresh once binder在loadOperations结束调用，late provider RED→GREEN，重复refresh不重复订阅、dispose后不重绑。write-core同步监听反例新增3项窄GREEN，写后及通知前重新核core。最终fx/保护/只读分支又捕获原生pageerror，尚待stack定位，不称最终通过或开始覆盖static。


本批最终统一构建与浏览器证据已核对：tsc+Vite exit0、40.09秒（/tmp/office-functions-zoom-notes-build.log），预算与契约均exit0（/tmp/office-functions-zoom-notes-budget.log、/tmp/office-functions-zoom-notes-budget-contract.log）。main249.8/250KiB、engine428.0/428KiB、docx-main238.7/250KiB；独立function27.9KiB、zoom-dialog5KiB，未提高预算。

源App:2213的header:true/toolbar:false/formulaBar:true已接入。物理fx冲突定位为原生FormulaEditorController同时启动隐式DOCS编辑；采用仅formula-bar fx捕获路由到本地源dialog并阻止原生重复click，不泛截工具栏。service订阅保留，但不宣称非DOM直接调用该service无冲突。Shift+F3按固定源global-shortcuts.ts:87接同一dialog，复用抽取的workbook-shortcut-target门禁；新2项与原outline3项GREEN（/tmp/workbook-function-shortcuts-green.log），不引入额外cellEditing门禁。新增shortcut文件由root适配，不冒充18文件迁移清单中的原文件。

函数最终built一次exit0（/tmp/function-dialog-gui-built-final.log）：分类/搜索、SUM参数与真实engine预览5、captured C3写入、draft刷新、真实Python patch/openpyxl保存、修订2既有调用参数重开；物理fx取消/Escape及真实grid Shift+F3单dialog均通过，pageErrors=[]。282次JS响应全200且SHA匹配static，18文件LOCAL清单无差异。真实pointer范围选择另由/tmp/function-dialog-gui-final-source.log证明，built日志明确rangePickAndCapturedCell=false，不能把dev证据当built范围拾取通过。

完整zoom/footer最终built一次exit0（/tmp/workbook-zoom-dialog-built-final.log）：唯一官方四控件、六快选、fit126%与反馈/footer/draft/dialog一致、137%草稿恢复/真实保存/revision2重开、保护及freeze C3/原行列几何/cells/其他ZIP保持，pageErrors=[]。header新增后fit相对旧132%变化由实际viewport决定。namebox与formula bar真实可见；截图未等待grid首帧，仅证明header/footer，不作为表格内容绘制完成证据。main bpD2Uonf及zoom-selection CbnQzhBW实际响应SHA一致；zoom-dialog DhSMfWQu独立HTTP200与static SHA相同（/tmp/workbook-zoom-dialog-built-asset-sha.log），未重复完整GUI。

Word三个最终built分别一次exit0：/tmp/word-notes-decorations-built-final.log、/tmp/word-notes-decorations-fresh-built-final.log、/tmp/word-note-reference-input-built-final.log。共8份真实patch保存/下载/ZIP回读与最终修订重开，pageErrors=[]；实际size/SHA及document.xml身份见/tmp/word-final-built-identities.json。实际docx-main BhWm8x5A SHA ad79e0ef59b854dc475643b0e808cd74f876bc8633a040974e2bae806b7213c4、engine Ct5Ep5gD SHA312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c，全部JS200/响应SHA匹配static。未重复93前端/44后端整批测试。

上述HTTP授权/修订路由仍mock，真实浏览器、Python patch、ZIP/openpyxl与下载文件身份有效；不称生产HTTP或桌面Office验收。代码未提交/推送/部署。全量目标仍active：外部工作簿宿主/拾取、RATE与CELL及MINIFS/MAXIFS数值覆盖、其他Word段落属性组合、其余disabled源功能及outline剩余LongTask归因仍需逐项推进。

### 2026-11-10：函数数值覆盖与Word布局装饰组合（进行中）
上一轮实际完成最终built验收且本轮已同步origin/code（HEAD7defea08、ahead/behind均0，保留全部dirty），属于实际进展。下一批三个同模型agent分别承担RATE深负根fallback、MINIFS/MAXIFS空匹配归零、Word正文/notes+段落布局+边框底纹组合。root核查CELL文件名宿主与集成。每项先实际反例RED再最小源复用修复，不将注册存在当数值对齐；当前未计新项完成。


本批数值反例已由真实Univer确认：MINIFS/MAXIFS空匹配返回空字符串（/tmp/workbook-function-ifs-real-red.log），RATE(5,-100,100,10)默认guess返回#NUM（/tmp/function-rate-engine-real-red.log），CELL无reference文件名返回#N/A（/tmp/workbook-function-cell-red.log）。分别复用固定源wrapper/fallback/delegate后定向转绿；RATE已有深负默认样例当前原生已能解，未当RED。源算法扫描/多根/切根等边界保留独立验收记录，不声称任意数值算法完备。

root首轮主视图真实用例抓到启动覆盖：仅createUniver后注册+0ms重绑不足以保证readWorkbook异步期间native初始化后的首次计算。最终改首个loadWorkbookData后安装三覆盖、loading期间calculateNow，原生计算结果明确排除dirty；同runtime换core保持安装。CELL路径由native已鉴权context或报告file响应X-Workbook-Path一次百分号解码进入provider，不从URL猜文件名。真实ASGI先缺header RED后GREEN，/tmp/workbook-cell-path-api-green.log。独立reload probe当前path/sheet刷新与三executor保持通过，/tmp/review-function-overrides-reload.probe.log。

该主视图反例进一步定位reader未剥_xlfn导致本引擎自己保存的MINIFS/MAXIFS重开#NAME。作为独立无sidecar适配增加调用token scanner：固定源gateway TS reader同样直接读（依赖sidecar），不虚称原reader已有剥离。真实ZIP初9项RED→GREEN，扩至16项，包括二次保存防双marker、_xlws、大小写/空白、引号/命名范围/结构化引用负例；CSV相关9通过。独立review抓到structured reference的apostrophe转义闭括号提前结束，真实RED后最小skip规则修复，最终/tmp/xlsx-future-marker-escaped-bracket-green.log与engine tsc通过，writer未改。CLI最终bundle /tmp/workbook-function-markers-bridge-final.log exit0。

root主视图初载所有4函数结果正确且draft.operations=[]/save0，/tmp/workbook-functions-main-final-green.log；安装包装沿功能边界提取后仅窄复验该受影响1例GREEN，/tmp/workbook-functions-main-extracted-green.log。旧headless native保存例首失败准确定位测试替身缺既有outline的sheet.getSheet接口，补齐实际shape（空row/column/custom metadata）后窄GREEN，/tmp/workbook-function-overrides-headless-green.log；无为此改生产outline或放宽身份。

数值dev浏览器一次exit0（/tmp/function-values-gui-first.log）：CELL中文/%路径、RATE正根、显式_xlfn.MINIFS/MAXIFS空集0、SUM原公式；真实canvas键盘A1 5→10后RATE0.962325503943→0.998920069612与SUM8→13，draft刷新、真实Python patch/openpyxl下载校验、修订2重开正确，只有A1一项cellEdit，全部公式/marker/B2文本保留，pageErrors=[]。dev wrapper仅暴露真实runtime做观测，不算built或生产HTTP证据。

Word本批布局装饰组合：source runSetParagraphAttrs仅合并attrs，本地前后端原互斥导致真实Editor16项与ZIP16项RED。仅额外允许既有alignment/左右缩进/spacing四kind与border/shading/final-runs合成，保留hash/capability/保护/未知字段，未新造协议。新增/受影响前端42、ZIP24、tsc通过；两种notes dev各三次真实patch下载/ZIP及最终重开通过，/tmp/word-layout-decorations-gui2.log、/tmp/word-layout-decorations-fresh-gui.log。layout真实save按源更新core modified/revision，旧全core字节断言失效，已明确校验只此两字段合法变化及revision+1，其他字段保持。独立真实Editor交错pPr顺序/unknown attrs/readonly1例通过，/tmp/review-docx-layout-decor-orders.probe.log。

初次本批tsc+Vite构建exit0、39.49秒（/tmp/office-function-values-layout-build.log），但预算engine428.7>428KiB、main略>250KiB，不能算最终验收。root沿自然边界将future-functions映射独立chunk、将三个源适配器安装包装到workbook-function-overrides，仅上述主视图受影响路径窄复验已GREEN；未提高上限。最终构建与built GUI待实证。全量目标仍active。


本批预算后续：自然拆future-functions后engine425.6KiB，但main实际256044字节，仍比250KiB多44字节（/tmp/office-function-values-layout-budget-final.log）。root发现既有editable与zoomAvailable条件逐项完全相同，机械复用同一predicate，无放宽门禁。最终tsc+Vite exit0、40.26秒（/tmp/office-function-values-layout-build-budget-fixed.log），预算与契约exit0（/tmp/office-function-values-layout-budget-fixed.log、/tmp/office-function-values-layout-budget-contract-fixed.log）。main C145fz5H约250.0/250KiB（真实字节低于上限，显示四舍五入），engine BNCXgAHt425.6/428KiB、docx-main BqX_pacj238.7/250KiB，future-functions hD9e7sTM3.2KiB。未提高上限；此后生产/static冻结，两个agent分别最终Word双样本与XLSX数值clipboard闭环进行中，尚不预记通过。


Word布局装饰最终built双样本已实际通过（各一次，未重复42/24）：/tmp/word-layout-decorations-built-final.log、/tmp/word-layout-decorations-fresh-built-final.log，各三次真实Python patch/下载ZIP与修订4重开，pageErrors=[]。112类实际JS响应均200/SHA匹配static；docx-main BqX_pacj SHA03f304873bc085bf71c9a0ef152742489bb83d08f43febe322f4248d9b3a152b，engine Ct5Ep5gD SHA312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c。六份新修订实际path/size/SHA/document.xml SHA与独立ZipFile.testzip见/tmp/word-layout-decorations-built-identities.json。HTTP仍mock，不称生产发布验收。

数值built首轮仅在clipboard读数阶段空串失败（/tmp/function-values-gui-built-first.log），未到修改/保存，不据此判断数值错误。测试采用自定义ribbon goto后未建立native FOCUSING_SHEET，当前改用官方namebox Enter聚焦路径继续验证；保持生产/static冻结，不用dev globals冒充built值证据。若独立源调查确认自定义goto连续键盘缺失，将作为新缺口保留，不因测试换路径而丢弃。


数值built第二轮保留失败实证：/tmp/function-values-gui-built-native-namebox.log已完成真实TSV初载四值、改输入重算/draft/真实patch-openpyxl/revision2重开，285JS响应200/SHA匹配，但3次namebox触发[redi]缺si，整体不计GREEN。si准确对应SheetsScrollRenderController；UniverSheetsUIPlugin.onRendered才registerRenderModules，本地却在stage1 Ready时公布aria-busy=false（真实/tmp/workbook-ready-lifecycle-probe.log），Rendered为2。不能通过smoke sleep或重试掩盖真实用户竞态。root新workbook-render-ready按官方LifecycleService.onStage(Rendered)等待、await后复核core/disposed，加载期间grid inert保留旧值；无render服务headless跳过。helper2项RED→GREEN（/tmp/workbook-render-ready-green.log），真实主视图函数初载受影响1例GREEN（/tmp/workbook-functions-render-ready-main-green.log）。

另确认独立GoTo源行为缺口：固定源data-tools-actions goToReference选区后ILayoutService.focus，本地dialog关闭恢复ribbon opener导致CtrlC/typing无grid焦点。新增focusWorkbookGrid使用官方layout服务，dialog成功先close再onNavigated，取消/失败保留既有策略；root接第三callback，不用延迟focus。该项属于真实源入口连续键盘行为补齐，非仅测试换选择器。新navigation功能chunk承载goto/render-ready，当前新build正在验证；此前Word构建产物SHA若未变，不重复两完整GUI。


Rendered等待与GoTo焦点修复后的最终tsc+Vite exit0、39.72秒（/tmp/office-functions-render-ready-build.log），预算与契约exit0（/tmp/office-functions-render-ready-budget.log、/tmp/office-functions-render-ready-budget-contract.log）。main CBZ8XXAO247.3KiB、engine ALYWZ5G-425.6KiB、navigation CHVb8VB73.5KiB，预算未调整。Word docx-main BqX_pacj与native engine Ct5Ep5gD实际SHA仍分别03f304873bc085bf71c9a0ef152742489bb83d08f43febe322f4248d9b3a152b、312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c，故不重跑相同双Word完整GUI。GoTo4项/strict窄tsc证据见/tmp/workbook-goto-focus-{green,boundaries,tsc}.log，未将官方layout测试宿主等同Chromium实交互；受影响XLSX built重新验收中。

新增局部显式缺口调查 docs/parity/2026-11-10-explicit-ribbon-gaps-inventory.md：区分源已确认行为缺口、源入口缺口、动态禁用、本地placeholder但本次源证据不足。该清单不是全量分母，不能据其算百分比；此前口头例举background/translate/split-window等在源未定位，本次没有计入已确认源行为缺失。全量目标不缩水，继续核对等价行为。


Rendered gating built后续仍有输入失败，保留/tmp/function-values-gui-built-render-ready.log：first namebox不再报si、goto CtrlC有正确TSV，但typing后A1仍5，整体失败。窄context probe（/tmp/workbook-goto-typing-context-probe.log）确认goto/namebox/canvas均EDITOR_ACTIVATED=false、无文字命令、Enter仅移动，不是异步提交断言太早。唯一变量dev route移除grid.inert=true、保留Rendered与其他源码后输入激活/insert-text与A1=10恢复（/tmp/workbook-goto-no-inert-probe.log），证明inert造成原生hidden editor初始化回归。root移除inert，改installWorkbookLoadingLock捕获用户pointer/click/keydown/beforeinput/paste，保留focus给原生初始化；loading终止后不拦输入。新反例先RED，lifecycle/core与event lock3项GREEN（/tmp/workbook-render-ready-lock-green.log）。当前修复待真实dev窄probe与新built，不能把此前无si当完整通过。GoTo旧cell正在编辑时需endEditingAsync是另一个源行为边界，本轮没有混改或声称覆盖。


新event-lock源码真实dev窄probe已通过（/tmp/workbook-goto-event-lock-direct-probe.log）：无任何main源码替换，ribbon goto A1→type10实际EDITOR_ACTIVATED=true、出现set-cell-edit-visible/doc.insert-text；Enter后直接读A1=10，无页面错误栈。未重复数值完整smoke；新最终构建进行中。

下一Word具名调查 NATIVE_WORD_STYLE_COMPOSITION_INVESTIGATION.md 已证实：固定源Ribbon applyParagraphStyleId会shedMajorityDirectFormatting，而源AI style操作仅改attrs；本地Ribbon保留全段direct bold，与源不同，不能把现有语义直接放宽组合后称对齐。临时真实Editor源规则比较RED（/tmp/word-style-majority-red.log），真实DOCX style-only普通段可用，但style+finalruns/replace与notes style被独立拒绝（/tmp/word-style-composition-docx-probe-full.log）。后续先处理Ribbon多数格式规则，再实现最终runs+pStyle/body/notes组合，不一次泛放layout/decor/pageBreak。当前只是明确下一缺口，未实现未计完成。


事件loading-lock最终统一tsc+Vite exit0、39.70秒（/tmp/office-functions-event-lock-build.log），预算与契约均exit0（/tmp/office-functions-event-lock-budget.log、/tmp/office-functions-event-lock-budget-contract.log）。main TIDMCHtw247.3KiB、navigation DXYENm6r3.8KiB，Word两chunk SHA再次核对未变，不重复相同Word双完整GUI；engine来源覆盖顺序核106文件SHA全部匹配。当前最终XLSX built完整重验使用每次唯一clipboard sentinel→CtrlC→等待本次实际写入，避免旧TSV使假通过。结果待实证，生产/static冻结。


本批XLSX最终built完整验收实际exit0（/tmp/function-values-gui-built-event-lock-final.log）：首次native namebox无si异常；后续全部ribbon goto→真实键盘输入/原生CtrlC，初值5/中文%文件名/RATE0.962325503943/IFS0/0/SUM8，输入10后RATE0.998920069612/SUM13。draft reload/真实Python patch/openpyxl/修订2重开均通过，仅A1一项cellEdit，原全部公式包括_xlfn.MINIFS/MAXIFS及B2文本保持，pageErrors=[]。288JS实际响应200且逐一SHA=static，覆盖main TIDMCHtw、engine ALYWZ5G-、future-functions hD9e7sTM、insert-function FBE3MIvK/Dhsfi0gc。clipboard导出RATE为12位小数，金融残差按1e-5验收，不宣称底层IEEE全部精度。中途draft重开clipboard一度仍读sentinel，数值断言未放行；最终新的正确TSV与文件回读才通过。smoke随后改为原子返回匹配6列的clipboard handle，避免二次读竞态；不为测试工具变化重复完整GUI。

所有本批最终构建/预算与受影响built验收已通过，未提交/推送/部署；完整xlsx/word目标仍active，不能据此称全量完成。未把mock授权/修订HTTP当生产HTTP、未称桌面Office兼容完成。明确继续源外链宿主、剩余功能/入口、Word样式语义组合及outline全页LongTask等独立缺口。


### 2026-11-10：Ribbon段落样式多数格式规则、checkbox与criteria缓存（进行中）
上一轮实际完成数值与Word最终built、修复原生Rendered竞态和inert输入回归，属于实际进展；本轮继续完整目标不缩范围。三个同模型agent各一缺口：源Ribbon样式majority shedding（AI不shedding）、Univer checkbox DV完整保存/自身重开、重复criteria compare缓存。root独占XLSX main/ribbon/vite及集成。

样式调查确认现有fontFamily:null会过度清fontCs/eastAsia/themes，不能用它冒充源独立font/fontAscii规则。选最小受限setParagraphStyle ribbon:true（缺省旧/AI不shed，false拒绝），服务端只用可信source计算八项多数属性，再对source XML定点去除并合成pStyle，不收客户端raw或任意格式值；normalizer完整projection核验。此A仅普通safe style，notes/body组合B仍另项。当前生产/测试进行中，未计完成。

checkbox源为requireCheckbox数字1/0或自定义checked/unchecked，源gateway同样fallback为list，与新版Excel boolean cell controls非同一语义。按源原值和官方UI实现，额外明确本地worksheet extension记录checkbox类型；fallback DV和完整ranges/options规范身份一致才恢复，普通1,0列表不启发式转换。Excel本体可点的现代checkbox没有冒称完成。真实engine roundtrip当前checkbox变list RED见/tmp/workbook-checkbox-roundtrip-red.log；root源Insert入口先RED→GREEN1项（/tmp/workbook-checkbox-ribbon-red.log、/tmp/workbook-checkbox-ribbon-green.log），保护/readonly动态禁用保持。尚未接完整主视图保存，不能计交付。

criteria缓存真实低层repeat compare已RED；最初裸setValues把月份字符串转serial导致完整工作簿[80,80,80]，不当缺失实证。显式STRING模拟真实导入同pass三公式后[80,0,0]（/tmp/criteria-cache-text-column-probe.log），缓存string keys但criteria数值46174，源适配目标现已由实际用户公式路径证实。拟最小源dense compare修复+多runtime共享prototype ownership/refcount，尚未预记实现。

本批root集成新增真实main定向RED→GREEN：criteria初载[80,0,0]现[80,80,80]且draft=[]/save0；checkbox走Ribbon创建、undo/redo、draft重开、applyOperations保存再readWorkbook保留checkbox（2项，/tmp/workbook-checkbox-criteria-main-green.log）。criteria独立dev GUI实际文本导入→键盘金额→draft→Python/openpyxl→rev2重开已通过（/tmp/function-criteria-gui-first.log）；HTTP身份/修订为mock。统一构建预检42.80秒exit0，预算预检通过main248.0KiB、engine427.8KiB；因后续Word显式off保留和checkbox旧metadata洗白负例需修，不把该预检称最终产物验收。8项独立接续队列已保存docs/parity/2026-11-10-parallel-gap-queue.md，环境root+3并发硬限已告知用户，不冒称8并发。

### 2026-11-10：本批最终静态验收与下一批
环境恢复后原/tmp日志及agent进程消失，已核磁盘生产改动保留，重新建立3个同模型子agent并最终构建取证。最终build /tmp/office-checkbox-criteria-style-build-restored.log exit0（39.49s）；预算/预算契约 /tmp/office-restored-budget.log、/tmp/office-restored-budget-contract.log exit0。此前428.1KiB超预算已通过checkbox-validation独立模块拆chunk解决，未提高预算。

当前三项最终built均通过：Word /tmp/word-style-majority-built-restored.log（112 JS200/SHA，pageErrors=[]，两次真实Python写回/下载及rev2/rev3重开、同style重复应用）；checkbox /tmp/workbook-checkbox-built-restored.log（204JS响应200/SHA，真实Ribbon、canvas、undo/redo、draft、Python/ZIP保存、新修订链接及rev2交互，errors=[]）；criteria /tmp/function-criteria-gui-built-restored.log（291JS200/SHA，无dev注入，真实clipboard80→85、draft/Python保存/rev2，pageErrors=[]）。各独立验收文档保存边界，不把mock身份/修订HTTP当生产HTTP，不声称桌面Office完整兼容。新源复选框是数字/自定义DV，本地extension自身重开，不是Excel新式boolean cell control。

下一批已启动：Word源全选入口2RED→GREEN与editable/readonly dev GUI（待新构建）；XLSX编辑栏会话开关主入口集成；XLSX行列标题reader真实ZIP1RED→GREEN（/tmp/workbook-headings-reader-{red,green}.log），withWorkbookView初载2RED→GREEN（/tmp/workbook-headings-view-{red,green}.log），独立标题模块异步切sheet风险已修。该下一批仍未整链验收，不能把上一批静态通过扩展为当前新源码全部完成。全量目标继续active。

标题读取后补真实无渲染替身的Univer hydration定向1GREEN（/tmp/workbook-headings-hydration-green.log），文件隐藏状态与无关单元格编辑互不覆盖。Python真实bridge/openpyxl/ZIP定向1GREEN（/tmp/workbook-headings-python-green.log）：隐藏及恢复、原值/保护sheet保留、ZIP仅目标sheet1.xml变化；首次probe误把inspect返回当model包装，已按真实CLI结构修正测试。withWorkbookView测试改用真实readWorkbook模型而非不完整断言，2GREEN（/tmp/workbook-headings-view-real-model-green.log）；showHeadings字段可省略兼容旧构造模型，reader仍总返回明确布尔。以上不替代尚未集成的主入口/草稿验证。

标题视图保护契约已定向RED→GREEN（/tmp/workbook-headings-protection-green.log，1项）：仅允许原生header尺寸视图命令，不放开单元格行高/列宽。Word HF调查确认源三入口有完整dropdown/目标语义；已有setHeaderFooter空值能保留关系并清空，不新增删除关系协议。准确末页变体依赖真实pageInfo，正在从既有Preview机械抽取共享分页快照，禁止猜末节default即计对齐。样式预设14项独立helper已有实链验证，入口未接。编辑栏CSS隐藏后真实键盘编辑触发原生docs排版stack overflow，子agent正在隔离根因；未掩盖错误或计GUI通过。

三个子agent于当前轮同时遭provider HTTP403 insufficient balance停止，root确认终态后接手，没有重复假称仍并行。root接通14预设菜单与主入口（源helper复用），入口定向1RED→GREEN /tmp/workbook-cell-style-menu-{red,green}.log；真实dev GUI /tmp/workbook-cell-style-menu-gui.log exit0，Input/Heading1/Total/Good、源分步undo、draft/Python/openpyxl/新修订重开通过，pageErrors=[]，尚待新构建。标题功能区1RED→GREEN /tmp/workbook-headings-ribbon-{red,green}.log，主入口/实时header差分已接；真实main imported hidden→edit→draft→save保留标题状态1GREEN（/tmp/workbook-headings-main-preservation.log）。标题实际浏览器切换/草稿重开仍未验收。

Word子agent终止前磁盘证据：共享pagination-snapshot机械抽取已有3定向GREEN（/tmp/word-pagination-snapshot-green.log）及Preview dev真实cut后对比（/tmp/word-pagination-after-dev.log），Word全选源码已接但新built未验；HF source edgeTarget及三dropdown尚未完成。编辑栏隐藏不编辑隔离errors=[]（/tmp/formula-bar-hide-only.log）；显示栏baseline键盘编辑也曾触发docs stack overflow（/tmp/formula-bar-baseline.log），不把原因归给隐藏，仍待进一步定位。

root进一步定位输入回归：withWorkbookView新增rowHeader/columnHeader对象仅含hidden，使Univer浅覆盖默认width46/height20，真实Worksheet字段变undefined；独立native尺寸负例RED（/tmp/workbook-headings-native-dimensions-red.log）后补默认并保留来源自定义，GREEN（/tmp/workbook-headings-native-dimensions-green.log）。修复后编辑栏dev完整链exit0（/tmp/workbook-formula-bar-fixed-dev-root2.log）：隐藏键盘金额15/公式85，真实reflow、draft、Python保存、rev2重开，pageErrors=[]。显示后geometry精确等于编辑前的probe断言不合理（反馈内容变化改变父布局），改同tab同当前反馈下隐藏/显示相反reflow验证，无产品迎合。首次新build预算main253.1→独立模块拆包250.1仍超250，继续自然protection模块边界拆分，未升budget。Word全选新built已通过（/tmp/word-select-all-built-root.log），但当前最终全批构建仍待预算确认。标题browser隐藏键盘probe仍在定位，不计完成。

root接手最终构建 /tmp/office-view-controls-budget-final-build.log exit0（38.78s）；预算/契约 /tmp/office-view-controls-budget-final.log、/tmp/office-view-controls-budget-final-contract.log exit0，main247.7KiB、engine425.9KiB。自然module边界view-controls/cell-style-presets/checkbox-control/protection，不升cap。编辑栏最终built /tmp/workbook-formula-bar-budget-final-built.log exit0：303JS200/staticSHA，真实clipboard80→85，隐藏输入、双向reflow、draft/Python/openpyxl/save/rev2，pageErrors=[]；标题dev /tmp/workbook-headings-gui-final.log exit0，三次真实toggle、hidden键盘、draft/Python保存/rev2重开/恢复显示，pageErrors=[]。标题首次probe把官方格式化getValue '77.00'误断言number77，记录诊断证实无error，改按数字等值校验，未改产品迎合。标题尚未无注入built图形验收；样式预设最终built文件验证正在跑，不能提前计。

本批最终补证：样式菜单built /tmp/workbook-cell-style-built-final.log exit0（303JS200/SHA，无runtime注入，代表4组合/undo redo执行/draft/Python文件/重开）；标题built /tmp/workbook-headings-final-built.log exit0（303JS200/SHA，无runtime注入，toggle/hidden键盘/native clipboard/draft/Python保存/rev2及恢复显示）；readonly Word全选built /tmp/word-select-all-readonly-final-built.log exit0。均pageErrors=[]。独立验收文档已更新，8任务队列更新状态；第5HF完整源入口仍未完成，其他全量缺口仍存在。没有commit/push/deploy、没有完整suite重复、没有标全量目标完成。子agent余额403为外部并行执行阻碍，root本轮仍取得实质进展，未将目标blocked或complete。

### 2026-11-10：Insert HF、RTL、条件格式快照并行推进（尚未整批验收）
同模型三个子agent分别负责Word HF、XLSX RTL、CF底层；root接main/ribbon/保护与真实保存链。不重复完整suite，不提交推送部署。

Word Insert六位置/删除/移除/异步过期/readonly十二项定向通过（/tmp/word-insert-hf-menu-green.log）。真实开发态普通、titlePg、两物理页even、首末节独立HF与末节逻辑页码restart12，以及删除均完成Python保存回读；ZIP字段独立验证移除PAGE保留NUMPAGES、w:jc和非目标HF部件SHA不变（/tmp/word-insert-hf-fields-zip-gui.log、/tmp/word-insert-hf-multi-zip-gui.log）。新发现离开Insert精确HF目标后手动HF页签仍沿旧target，已有真实main回归RED，正在修复。当前分页测量共享Preview算法，但大脚注/尾注/复杂多栏collector尚未全量对齐，不能推广普通末页奇偶结果。

RTL固定源镜像原字节vendoring与正式命令已接；ribbon入口、保护表仅视图命令允许且cell仍阻止，定向GREEN。真实main toggle→undo→redo→draft恢复→bridge保存→reader方向/原公式GREEN（/tmp/workbook-rtl-main-first.log）；重建dist后真实Python/openpyxl定向1PASS（/tmp/workbook-rtl-python-dist-green.log），root tsc exit0（/tmp/office-hf-rtl-root-types.log）。实际浏览器视觉翻转与undo/redo通过，但真实mouse目标偏列，经定位官方reCalculate不触发currentSkeleton$导致冻结viewport未重建；agent正以实际GUI失败为RED修复本地适配，未改源vendor，未宣称RTL验收完成。

CF full snapshot底层linked-x14/缺styles阶段46项定向GREEN、engine tsc exit0（/tmp/cf-snapshot-linked-final-targeted.log、/tmp/cf-linked-types-final.log）。linked匹配身份规则与sheet ext逐字保留，拒用伪造/删除/改变扩展；无styles纯bar不增加styles，highlight按需新增dxf/CT/rel。正式index/schema/bridge/reader集成开始，完整UI尚未接，主题dxf/外部等价读取仍有缺口。

本批进一步验证：Word显式HF目标离开页签后先flush再清target，真实main RED→GREEN与多节GUI均通过（/tmp/word-hf-target-lifecycle-green.log、/tmp/word-insert-hf-target-lifecycle-gui.log）。RTL本地adapter用官方setCurrent激活操作触发冻结viewport重建，真实失败mouse路径修复后全链GREEN（/tmp/workbook-rtl-view-gui5.log），无runtime纯fill像素定位mouse版本dev亦GREEN（/tmp/workbook-rtl-view-gui-pixels2.log）。源mirror原字节未变。

CF正式reader/index/schema/bridge、Python白名单已接；native真实openpyxl测试先拒协议RED，接入后仍RED（/tmp/workbook-cf-native-green-first.log）：openpyxl六位RGB会写00RRGGBB，新reader仅接受FF前缀误拒。固定源Rust/TS及旧local均会去任意8位alpha，已确认是本地过严限制，尚未修复，保留原fixture不绕过。另外readWorkbook仍强读styles部件，无styles合法bar入口仍待补。

统一build /tmp/office-hf-rtl-cf-build.log exit0（39.13s），预算/契约 /tmp/office-hf-rtl-cf-budget.log、/tmp/office-hf-rtl-cf-budget-contract.log exit0，未升cap，按RTL和CF自然模块拆包。最终built HF/RTL开始验证，全生产/static暂冻结避免取证竞态。docs LOCAL 233项逐项SHA无不匹配。此处仍非整批验收通过，CF native红例明确保留。

HF最终built ordinary/multi实际日志均ok:true、pageErrors=[]（/tmp/word-insert-hf-final-built-ordinary.log、/tmp/word-insert-hf-final-built-multi.log），各112JS响应200/磁盘SHA一致，含target生命周期与非目标ZIP SHA。身份 /tmp/word-insert-hf-final-built-identities.json；Word下一缺口为 NATIVE_WORD_PAGINATION_COLLECTOR_PLAN.md，脚注/尾注/多栏探针规格已写但尚未执行。RTL最终built初载Home未出现超时，正在诊断初始化，未作为通过记录；不重复其已过dev全链。

RTL built初始化失败最终实证为CF分块TDZ：/tmp/workbook-rtl-view-gui-built3.log外层status Cannot access 'Da' before initialization；动态import stack engine:58:22636(ne/ZodNumber) ← CF chunk:2:21818，非RTL坐标问题。root先前把CF schema/read/snapshot全部手工同块，导致engine↔CF初始化循环。调整自然边界为无依赖fixed source serializer单独CF、zod单独叶子schema块，其余read/snapshot留engine；/tmp/office-hf-rtl-cf-cyclefix-build.log重新构建中。不修改预算，不把catch后无pageError误当成功。

cyclefix最终构建 /tmp/office-hf-rtl-cf-cyclefix-build.log exit0（39.10s）；budget/contract同前缀日志exit0。新CF↔engine循环告警消失，既有其他循环未扩展处理；Zod叶子schema185.26kB、engine356.71kB、main254.81kB（Vite十进制kB，预算按KiB）。未升cap，静态继续freeze等待RTL失败链和Word新产物启动窄probe。真实CF ARGB失败仍未修。

上一goal轮为实际进展：源入口/保护/保存定向、分块TDZ定位修复、统一构建预算以及HF最终built已改变权威状态。本轮收证RTL cyclefix最终built /tmp/workbook-rtl-view-gui-built-cyclefix.log exit0：312JS200/SHA，fill像素镜像→真实mouse B1→金额15与SUMIFS85×3、freeze B2、undo/redo、draft、Python/openpyxl、rev2均通过，pageErrors=[]。Word cyclefix后仅初始化+HF菜单窄probe通过（/tmp/word-hf-cyclefix-init-built.log，112JS200/SHA），未重复未变双保存链。

下一三独立任务已授权：CF合法ARGB/无styles reader修复（已有RED）；CF frontend完整官方模型适配（主入口root集成）；Word当前脚注collector（真实RED /tmp/word-footnote-pagination-probe-red.log：实际Preview1页，源实测脚注200.546875px占位后2页）。大脚注已由推测变为实际失败，尾注/多栏仍不计完成。静态验收结束后开放新生产窗口，目标仍全量xlsx/word，不commit/push/deploy。

CF ARGB及无styles完整入口已修并重建dist：原Python/openpyxl六位构造fixture不改，替换→检查无重复/保公式→inspect→清空GREEN（/tmp/workbook-cf-native-argb-green.log）；新增native无styles真实ZIP→inspect→清空→ZIP仍无styles GREEN（/tmp/workbook-cf-native-no-styles.log）。agent颜色受影响33项定向及新增ARGB/noStyles/未知属性边界通过，两层tsc通过，未重复完整suite。

root下一CF UI入口真实主链RED（/tmp/workbook-cf-main-red.log）：已注册官方model但未resource导入时highlight规则0。Ribbon cf-open先RED后GREEN（/tmp/workbook-cf-ribbon-{red,green}.log），主入口新增official preset/zh/css，Rendered后执行source管理面板value2。正式adapter三API已由独立agent建立，root开始接resource/full diff/mutation dirty/命令guard；停用本入口旧窄cfRules投影避免双加载。新增真实main测试覆盖import→set→undo/redo→draft→保存回读，结果尚待，未宣称完整条件格式UI验收。

本轮root真实main CF定向已GREEN（/tmp/workbook-cf-main-green-first.log）：完整highlight资源导入1条且draft空，官方set到9→undo回原无操作→redo→draft恢复→bridge保存→reader9，原公式不变。adapter后续补native公式'=' hydration/文件去'='，结构迁移与实际管理器GUI仍在agent验证，尚未作UI完成宣称。

Word脚注实时修改/删除和prepareEdges实证 /tmp/word-footnote-pagination-live-gui.log exit0：长脚注两页/default footer，改短一页显示新文本，删除后无脚注且first footer；Python实际保存ZIP notes=[]，pageErrors=[]。collector4项、main边缘4项与fonts等待失效1项GREEN。尚未统一最终build，不推断尾注/多栏已完成。最新并行tsc曾两处CF中间态报错，已送各owner纠正，以最终输出为准。

root新增未知CF不阻断普通编辑定向GREEN（/tmp/workbook-cf-main-unknown-green.log）：unknown CF不被误投影为空可编辑集，普通cell7保存仍保留原unknown CF XML。adapter独立继续验证离屏规则结构迁移和scalar数字规则标准化；不因普通主链绿色宣称全格式可用。Word collector无编号默认的边界已提出review，等待owner确认；当前最新tsc曾CF read closure narrowing错误，owner已最小修为捕获前布尔值，需终态日志确认。

CF官方管理器真实dev GUI /tmp/workbook-cf-manager-dev4.log已ok:true/pageErrors=[]：原生dblclick数字规则10→20、删除、File undo/redo/undo、草稿重载、真实Python patch_office/openpyxl两规则20与离屏formula及原A1/F1保留。普通及离屏D5001:D5100行插删迁移经full preset实测通过；本地hydration扩充完整CF范围网格尺寸，数字native scalar/文件array及公式native'= '/文件裸式转换已定向验证。root main相应scalar真实调用/恢复定向GREEN（/tmp/workbook-cf-main-native-scalar-green.log）。

linked x14结构迁移仍有独立实际缺口：既有engine只移base sqref而不移配对xm:sqref。frontend现有官方RefRange可信followers WeakSet扩CF，root仅对该真实params身份从属mutation不拿初始linked范围判断，最终snapshot仍按结构回放baseline完整校验；未以命令source字符串/泛关闭保护绕过。engine owner暂停cellIs阶段，优先补linked双范围同步。尚未统一新build。

linked结构同步本地安全修复（固定源自身只移动base，未冒称源已支持）新增10项GREEN、原有DV/baseCF受影响3项GREEN（/tmp/cf-linked-structure-first-green.log、/tmp/cf-linked-structure-extra.log、/tmp/cf-linked-structure-regression.log）：base/twin同步、整删无悬挂/空extLst、scope/namespace/重复身份拒绝、混合普通规则保留、实际ZIP与异表字节保持。engine/bridge tsc过，Word readonly测试构造最小修后前端最终tsc exit0（/tmp/word-footnote-final-typecheck.log）。

CF整列D1:D1048576真实GUI导入与管理器完整范围通过（/tmp/workbook-cf-full-column-dev.log），strict schema后扩网格尺寸，无剪裁冒充；最终built manager无runtime probe准备完成。全部生产freeze后root已bundle engine dist（/tmp/office-cf-structure-engine-bundle.log）并启动 /tmp/office-footnote-cf-build.log，尚未验收本次最终产物。

统一首构建39.29s exit0，但预算失败（/tmp/office-footnote-cf-budget.log）：native-docx-render712.1KiB>710、workbook-main250.2KiB>250。root未升cap，按自然边界分note-dom与workbook-data-validation控制模块，/tmp/office-footnote-cf-budgetfix-build.log重新构建中。CF linked真实官方行0边界另发现：B1:B3插行0官方扩为B1:B4，而engine移到B2:B4，不能放宽immutable冒充等价；agent继续只读定位与保存失败取证，生产/static仍冻结。

budgetfix2最终build /tmp/office-footnote-cf-budgetfix2-build.log exit0（39.59s），budget/contract exit0，不升cap；note-dom+note-format自然同块、DV controls独立。main253.98kB/render726.03kB为Vite十进制，均在KiB门限内。engine叠加来源114项仅RTL page-setup旧hash不符，核对本轮RTL实际字段后刷新该UPSTREAM项；无代码回退。最终built脚注与CF纯UI已通知执行，静态继续freeze。

linked官方边界差异已由实际保存失败证实（/tmp/workbook-cf-linked-structure-dev2.log：保存失败/linked身份），且row0/row4/col0/col4四定向RED（/tmp/workbook-cf-boundary-follower-red.log）。源文件引擎>=边界平移，官方UP common在相等时扩范围；下一修复使用已有engine范围函数规范可信follower redo并保undo原身份，不放宽linked身份。待built验收后实施。

最终built脚注 /tmp/word-footnote-final-built-live.log exit0：长2页→短/删1页、footer default→first、Python保存/ZIP notes=[]，115JS200/SHA、pageErrors=[]；身份 /tmp/word-footnote-final-built-identities.json。CF最终纯UI built /tmp/workbook-cf-manager-built-final.log exit0：无runtime注入/读取，管理器10→20、删、undo/redo、draft、Python/openpyxl保存、rev2重开20/离屏范围，327JS200/SHA、pageErrors=[]。构建/预算同budgetfix2最终通过，未重复旧HF双链。

这证明本批普通CF管理闭环与脚注，不证明linked边界/复杂split已完成。linked精确边界RED进入下阶段trusted follower修复窗口；split源规则priority槽位/stopIfTrue和x14派生身份仍明确全量缺口。Word下一独立任务为尾注真实分页RED与方案，生产窗口开放后各agent按独占文件继续。

本轮root新增CF可信来源缓存：结构变更后普通规则编辑此前仍用初始linked范围误拒，真实RED /tmp/workbook-cf-linked-ordinary-after-structure-red.log。currentOperations结构回放baseline按来源model引用+sheet plan+不含undo对象的结构日志签名缓存，guard仅取匹配签名来源，不把当前CF当可信来源；未同步时明确重试。真实dev终态 /tmp/workbook-cf-linked-ordinary-after-structure-green2.log exit0：普通20、undo/redo、实际localStorage草稿完成后reload、Python保存cellIs20、base/x14 B2:B4、A2/F2/离屏公式均通过。首“green”命名日志实际失败仅reload未等待本次draft，已明确保留而未计通过。

collector整批预检在改任何payload前校验scope/旧cfId唯一性，split/重复Set/foreign不登记豁免，5新定向通过（/tmp/workbook-cf-batch-preflight-green.log）。cellIs正式阶段112定向及最终保真3项通过；固定源六函数VM oracle636组合匹配，serializer字节不变，两层tsc及前端tsc过。root主链受影响定向 /tmp/workbook-cf-cellis-main-regression.log GREEN。

尾注两真实RED均GREEN（/tmp/word-endnote-pagination-probe-green.log、/tmp/word-endnote-edge-probe-green.log）：长尾注2页、改短/删除1页，footer default→first与实际Python ZIP endnotes=[]，9共享回归及最终tsc通过。全部freeze后已bundle并启动 /tmp/office-endnote-cf-cellis-build.log；仍待本轮最终built验收。

cellIs root真实native Python /tmp/workbook-cellis-native-python.log1PASS：openpyxl cellIs(B1)→inspect公式投影→加bar仍cellIs(B1)/stop→真改A1>10写expression且B1不变。engine叠加114项与docs LOCAL233项SHA逐项全匹配。

本轮首build40.01s exit0但main250.6KiB超cap，未升cap；自然structure-followers控制模块拆包后最终 /tmp/office-endnote-cf-cellis-budgetfix-build.log exit0（39.71s），预算/契约同prefix exit0。CF linked/尾注最终built已授权执行，仅跑本轮受影响路径，不重复旧普通管理器/脚注完整链。生产/static继续freeze。

本批最终built全部收证：linked CF /tmp/workbook-cf-linked-manager-built-final.log exit0，无runtime注入，333JS200/SHA，插行→普通10/20→delete/undo/redo→实际localStorage20持久化→draft→Python/openpyxl/ZIP base+x14 B2:B4→rev2重开，A2/F2/离屏公式保真，pageErrors=[]。尾注 /tmp/word-endnote-final-built-live.log exit0，115JS200/SHA，长2页/改短删1页、footer default/first及Python ZIP endnotes=[]，pageErrors=[]。对应统一构建/预算budgetfix均通过。未提交推送部署，完整goal保持active。

下一独立缺口已有真实浏览器RED /tmp/cf-complex-split-probe-red.log：Other B1:B4条件Source!A1>0，Source插第2行后只有一组未更新依赖，Other B2可能指向新Source A2。先核固定源/官方loader对跨表公式需workbookId前缀的引用注册协议，避免把缺少hydration转换误认算法缺失。两个CF agent分前端/engine共同定位；Word agent进入uniform/mixed多栏真实RED调查，不只改none props。

complex split后续根因已排除loader前缀：固定源toCfFormula仅加=，官方依赖服务能解析裸Source!A1。只读替换collector捕获官方result实际出现Set旧id(B2:B5,Source!A3)与Add新id(B1,Source!A1)，前者错误移动未受结构影响Other范围，Add会unshift破坏原priority槽位。本地预检拒绝该split但可能base结构已执行，需下一阶段共享planner/事务预检，不能冒称支持。engine公式迁移regex亦需CF依赖独立RED核验，不可只修UI保存错配。

Word uniform双栏新真实RED /tmp/word-uniform-columns-red.log：当前Preview2页，同DOM按源uniform276px宽度与同分页器得到1页/2column regions，pageErrors=[]。仅probe新增未改生产。已授权首节canvas事实+uniform完整CSS测量通道，保持光标当前节编辑身份；mixed另继续，不以改props当全量完成。

上一goal轮具实际进展（最终333/115JS验收与新split/uniform RED），本轮继续未重开旧suite。root新增native Python实际跨表结构RED /tmp/workbook-cf-crosssheet-native-red.log：Source index1插行后，Other B1:B4应保TRUE stop优先1，依赖条件分B1/SourceA1与B2:B4/SourceA3优先2/3，当前未实现。新增测试 test_workbook_conditional_formatting_structure.py保留权威端到端契约。

两个CF agent最终共享API约定 planConditionalFormattingStructure(rules,hostSheetName,editedSheetName,spec)→按原sourceRuleIndex有序groups，engine结构保存与frontend官方mutation计划复用；关联raw dxf/twin由server原XML派生，不加client可信mapping。前端保原parent priority槽并在基础mutation前整批预检，不以拒split算完成。Word uniform真实RED现dev GREEN、首末节光标改变canvas宽度RED亦已修，尚待目标保存及最终构建，mixed仍独立缺口。

Word uniform阶段dev实际正文收证完成，未计最终built或mixed完成：/tmp/word-uniform-columns-edge-save-green.log exit0，实际canvas cols2/width480、首末正文横坐标600.5→804.5，neutral=false；Preview与固定源uniform均1页/2column regions；prepareEdges first footer、Python保存ZIP columns仍2且正文未改，恢复单栏cols auto/class false/page-gap0，pageErrors=[]。定向5项通过 /tmp/word-uniform-columns-directed.log。最终tsc /tmp/word-uniform-columns-final-typecheck.log exit2仅并行CF readonly，Word无错，仍待统一构建。mixed/continuous/nextColumn进入下一独立RED调查，不以none降级算对齐。

CF shared planner前端跨表复杂split实际dev从RED转GREEN /tmp/workbook-cf-complex-split-dev-green1.log exit0：原TRUE stopTrue仍首位且Other B1:B4不移动；Source!A1分Other B1、Source!A3分Other B2:B4，无多余B5，pageErrors=[]。此证据只覆盖实时范围与优先级，undo/redo、draft、实际保存和最终built尚在进行。

CF共享split正式引擎freeze：/tmp/cf-split-final-green.log 22项通过（split12+linked10），/tmp/cf-split-final-types.log engine/bridge及 /tmp/cf-split-final-frontend-types.log frontend类型检查通过。新增owner审查修复包括own-sheet全列顶/中插越界、lowercase依赖、带外host逆映射，XML最终精确回读语义对齐planner。UPSTREAM-PATCHES62项及CF local4项逐项SHA无不匹配。applyCellShift相交CF仍是独立缺口，后续只读源调查中。

root重新bundle实际bridge /tmp/office-cf-split-engine-bundle.log exit0后，新增native Python插行与删行两项均GREEN /tmp/workbook-cf-crosssheet-native-green.log（2passed），host单元格不动、依赖分区/优先级以及Source!#REF!保留。前端原保存旧dist失败 /tmp/workbook-cf-complex-split-dev-save1.log 在更新dist后 /tmp/workbook-cf-complex-split-dev-save2.log exit0，真实payload只有Source applyRowColumnOps、无client provenance；undo/redo/draft→Python/Openpyxl三组及stopTrue有序正确，pageErrors=[]。最终built纯UI仍待统一构建，不以dev代替built。

Word mixed主路径dev已实现并收证：continuous单转双24段1页、nextColumn2页、continuous64段3页，实际body宽384→180、左右栏600.5/804.5，3页2gap/height1496、nextColumn1gap/height988，保存startType/columns/body保持；/tmp/word-mixed-continuous-layout-green.log、/tmp/word-mixed-multipage-final-green.log、/tmp/word-mixed-nextcolumn-final-green.log，pageErrors=[]。源码桥复用columnLayoutSpecs/sectionWidthSpecs/widthPassGate与setColumnLayout/LayoutBatch，pagePaperEdges/gapLedger和HF effective margins用于真实canvas；8pass不收敛明确软警告。曾漏gapLedgerOf第二参数导致probe超时，已修并在最终日志重验，不计中间日志为通过。类型检查 /tmp/word-mixed-columns-final-typecheck.log exit0，仍待built；复杂表格/HF注释gap/RTL不等宽组合保留缺口。

统一首build /tmp/office-mixed-columns-cf-split-build.log exit0（39.59s），预算失败native-docx-render723.7KiB>710，budget-contract通过；未升cap，按自然pagination-sections.ts分成native-docx-section-layout，budgetfix重新构建中。CF下一cell-shift调查已得到5engine和1browser真实RED，详见NATIVE_XLSX_CONDITIONAL_FORMATTING_CELL_SHIFT_INVESTIGATION.md；仅调查/tests/smoke无生产改动，不能将整行split支持推断成局部插删单元格支持。

预算拆包继续记录：budgetfix1 build39.28s exit0但render715KiB>710；budgetfix2 build39.23s exit0但render710.1KiB>710。未改cap，root按源分节geometry与editor column-layout/recovery自然模块边界拆包，最终再把section直接依赖page-margins归同chunk；budgetfix3在跑。各budget-contract均通过，前两版未作最终built验收，避免以新代码配旧static。

最终统一budgetfix4构建 /tmp/office-mixed-columns-cf-split-budgetfix4-build.log exit0（40.04s），budget/contract同prefix均exit0，未升cap。fixed源模块只调整Vite自然归属：pagination-sections/page-margins同section-layout、column-layout/recovery/top-level-pos同column-layout，docs源字节不变。最终render726.44kB（十进制）、main Word155.97kB、XLSX245.79kB；仍有render↔layout静态循环告警，实际built初始化必须验证，不能以编译通过替代。生产/static继续freeze，两个agent分别运行本轮CF pureUI与Word uniform/mixed三新链。

Word最终built三新链全部收证：/tmp/word-columns-final-built-{uniform,continuous,nextcolumn}.log均exit0；uniform1页真实双栏/恢复单栏/ZIP columns保持，continuous3页2gap/height1496，nextColumn2页1gap/height988，body/startType/columns与footer目标保存正确，pageErrors=[]。每条117实际JS200/磁盘SHA匹配；/tmp/word-columns-final-built-identities.json的main/section-layout/column-layout已由root再次与磁盘逐项核验无不符，新分块真实初始化通过。复杂row/cell/重复表头gap、注释/HF gap组合、差纸张居中/mirror、RTL不等宽及长段跨栏仍未覆盖，未宣称完整Word分页完成。CF built首次在undo切回Source后probe没切Other而超时，生产无改，仅修脚本真实goto再验，保留该失败证据。

本轮CF最终pureUI built /tmp/workbook-cf-complex-split-built-final.log exit0：333JS200/磁盘SHA，native manager跨表插行三组、undo/redo、草稿恢复、实际Python/openpyxl、rev2重开均通过；payload仅Source applyRowColumnOps insert index1。输出有序TRUE stopTrue B1:B4→Source!A1 B1→Source!A3 B2:B4，pageErrors=[]，无runtime注入。首undo页签probe错误归档 /tmp/workbook-cf-complex-split-built-undo-sheet-red.log，修脚本定位后通过，未修改生产规避。统一最终build/预算同budgetfix4通过，Word三链117JS也通过。本轮验收完整收证后开放下一生产窗口：cell-shift geometry/可信XML与frontend四命令原子collector两agent推进；Word单栏跨节差宽/mirror先独立真实RED。全量目标未完成，不commit/push/deploy。

cell-shift阶段root新增原生Python真实回归两项（down/up），同时校验Source自己CF插入空白/删范围、Other跨表依赖三组与原stopTrue优先、band外单元格和host正文保留；旧dist实际RED /tmp/workbook-cf-cell-shift-native-red.log 两项native拒绝，保留后待新bridge验证。frontend wrapper/collector15定向已GREEN /tmp/workbook-cf-cell-shift-frontend-green1.log，engine12契约+既有受影响7项共19GREEN /tmp/cf-cell-shift-engine-green.log；root复核指出incomplete source不得range-only冒支持，owner已cell geometry严格拒绝并新增unknown/DV保护，x14DV补验中，尚未统一bundle/build。

Word单栏跨节差纸宽真实RED /tmp/word-single-column-section-width-red.log已变GREEN /tmp/word-single-column-width-body-save-green.log：最大canvas672，首节384宽/pageDx96/实际纸上144，末节528宽/pageDx0/纸上96，source sectionWidthSpecs一致；光标末节footer目标仅1HF操作，Python保存body/sections保持，pageErrors=[]。8项定向 /tmp/word-single-column-width-directed.log与最终tsc通过，生产freeze待build。mirror独立RED /tmp/word-mirror-margins-red.log：页号重启12/13但两页正文x均96，源12偶数应48，后续单独merge source mirrorMarginSpecs/pageMargins，不在本阶段冒计完成。

cell-shift engine已freeze后root bundle /tmp/office-cf-cell-shift-engine-bundle.log exit0，真实Python两个新增down/up回归 /tmp/workbook-cf-cell-shift-native-green.log 2passed。engine20项终态 /tmp/cf-cell-shift-final-green.log及两层types通过，63项UPSTREAM/4项CF LOCAL/233项docs LOCAL逐项SHA无不符。frontend真实dev暴露两个额外缺口而未冒验收：官方四cells命令反转整个undo列表，导致整表CF恢复后又删除，原empty RED /tmp/workbook-cf-cell-shift-dev-undo-order-red.log；仅反转CF undos抵消后15项GREEN /tmp/workbook-cf-cell-shift-undo-order-green.log。其后实际保存到rev2但payload出现Source A2黄色fill永久化，真实getCellRaw无s/getCell有CF黄色，官方命令getInsertRangeMutations把投影s作为自动插空样式写回，证据 /tmp/workbook-cf-cell-shift-style-diagnostic.log。正以外层准确生命周期修nested style-only payload来源为raw，不在保存diff抹真实fill；普通手动样式必须保留。官方扩容显式rowheight单独核验中，不能泛忽略geometry。

Word uniform/mixed→none→原模式两窄恢复探针通过，旧height/deco/gap清理恢复正确，生产freeze待统一build。下个独立rename/reorder缺口已有新engine与browser RED，仍只读调查，不扩大本批生产范围。

cell-shift投影样式源修复已dev终态GREEN /tmp/workbook-cf-cell-shift-dev-stylefix-final.log：before raw无s/显示getCell黄色，helper仅在outer insert命令同步构造的nested style-only set-range-values批取raw.s，普通手工样式不改，支持无params selection入口、microtask失效/消费一次/销毁释放。官方构造nested调用是直接interceptor而非command execution，不触发before清scope；因此真实时序normalize先于任何base mutation，避免仅单测假通过。undo/redo原CF ID/body、draft、Python实际保存、新修订均通过，A2 directFill=null，Source A1 A3:A5，Other有序三组，pageErrors=[]。额外行高严格核为官方扩容anchor/default24px→新rowData24px→18pt，保留唯一对应applyRowHeights；无CF snapshot/污染fill，仅两个worksheet XML变化。helper/collector定向与最终tsc通过，已freeze；统一build /tmp/office-cells-cf-word-width-build.log运行中。

本轮统一build /tmp/office-cells-cf-word-width-build.log exit0（39.81s），budget/contract同prefix exit0，未升cap，无需再次拆包。main XLSX242.51kB、Word156.18kB、render726.55kB（Vite十进制），engine和docs来源清单仍无不匹配。4220 cells pureUI与4196 Word差宽built两独立新链已通知运行，生产/static保持freeze，直到完成真实JS身份与保存检查。

本轮最终built全部收证：4220 /tmp/workbook-cf-cell-shift-built-final.log session42946 exit0，无runtime注入，333JS200/SHA，Source A1 A3:A5/A2 directFill=null、Other三组priority1/2/3、undo/redo原identity、draft恢复、实际Python/openpyxl及rev2通过，payload仅applyCellShift+真实扩容18pt行高，仅两个worksheet XML变化，pageErrors=[]。Word /tmp/word-single-column-width-final-built.log session85318 exit0：3页真实canvas672、首节384/x+144及末节528/x+96，末节footer可信目标实际保存、body/sections保持，117JS200/SHA，root逐项重核磁盘无不符。身份 /tmp/word-single-column-width-final-built-identities.json，mainBn6cIeWi。统一build/budget同office-cells-cf-word-width全部通过。本轮静态身份验收结束，完整goal仍active；后续仍有CF rename/linked双侧公式一致性、Word mirror逻辑页号边距等真实RED，未将本批子目标替代全量目标。

rename引擎freeze：/tmp/cf-sheet-edits-final-green.log 135项通过，最后cfvo属性匹配收紧后15项再绿 /tmp/cf-sheet-edits-final-attribute-green.log，两层types通过。共享rename大小写/合法引号/外部簿保护和cfvo@val/xm:f一致更新，linked读取新增独立threshold数量/类型/数值/公式身份检查，不再仅投影base。root已核64UPSTREAM/4CF LOCAL/233docs LOCAL逐项SHA一致。frontend19项与tsc通过，bundle /tmp/office-cf-rename-engine-bundle.log exit0后真实dev /tmp/workbook-cf-sheet-rename-dev-final.log exit0：4规则/linked视觉ID/原顺序/undo/draft/Python/rev2，仅applySheetEdits，Source XML/styles不变，仅workbook.xml及Other XML变化。root新增native回归首次因插入测试位置带入旧删除断言失败，已移回原test；/tmp/workbook-cf-rename-native-fixed.log1passed，真实公式和阈值大小写改名/字符串保留正确。统一build /tmp/office-cf-rename-word-mirror-build.log运行，仍待built。

Word mirror开发两逻辑页号窗口12/13及13/14，实际正文48/96与96/48、gap边距、prepareEdges default/even、仅一HF可信操作、body/sections/settings SHA保持均GREEN，5定向及最终tsc通过，生产freeze待相同统一build。

本轮build /tmp/office-cf-rename-word-mirror-build.log40.37s exit0，budget/contract同prefix均exit0，未升cap。Word镜像最终built两窗口 /tmp/word-mirror-final-built12.log、built13.log进程98271/53820均exit0，逻辑12/13正文48/96、gap96/48与default保存；13/14正文96/48、gap48/96与even保存。仅可信HF操作、正文/分节/settings.xml SHA保持，pageErrors=[]。每组117JS200/SHA，root逐项与磁盘核验无不符。CF pureUI built初始manager公式文字locator超时 /tmp/workbook-cf-sheet-rename-built-final.log，尚未计最终通过，正只修probe诊断实际UI。下个sheet删除调查发现fixed gateway对被引用sheet本就拒绝，后续以该源契约核cfvo是否漏拒绝，不自造#REF目标。

CF rename最终pureUI built /tmp/workbook-cf-sheet-rename-built-final3.log session19118 exit0：真实tab双击改名、undo/redo、draft、Python/openpyxl、rev2全部通过，333JS200/SHA，mainNRM-WSGM/engineBMpvh_QZ/structureByVcUCp-，pageErrors=[]。四规则priority1-4，普通/linked阈值两侧一致，linked原ID/gradient/negative色保持，仅workbook.xml/Other sheet2.xml变化，Source/styles原字节，payload仅applySheetEdits。前两probe失败分别manager不展示公式全文及填名后旧名locator失效，日志保留，未修改生产规避。与Word mirror两117JS窗口及统一40.37s build/预算共同完成本批静态验收。下一生产窗口为referenced removal：源拒绝语义保持，engine补cfvo依赖漏检，frontend补真正原子前置拒绝；Word不等宽仅只读稳定性调查，旧参考改DOM导致伪RED未计。全量目标仍active，不commit/push/deploy。

本轮referenced removal原生Python新增21项已有GREEN证据：9项三类cfvo公式本地依赖拒绝、12项literal/external/Other允许删除，保留sheet/styles字节与内容。root主入口新增incomplete真实源RED（删除错误true）后采用真实ZIP→局部WeakMap按model身份保存raw，仅issues非空读取，匹配cfBaseline签名；最终 /tmp/workbook-cf-removal-main-green3.log通过。另新增live清除引用后删除真实保存RED，修为prefix sheet plan/structural→存续CF replace→removal，/tmp/workbook-cf-removal-live-save-main-green2.log通过。增强测试时root误将下载callback补入旧GoalSeek test，已还原并移入新test，失败日志保留不计通过。rename组合新增已绿，insert-row组合仍有原子拒绝待诊断，未推断复杂组合完成。

统一 /tmp/office-removal-word-stability-build.log exit0（40.45s），budget与budget-contract同prefix均exit0，未升cap。Word重复入口不再重排漂移的dev与定向通过，但8轮split未收敛软告警仍存在，不等宽最终视觉固定点未完成。静态freeze后本轮两agent进入最终built：CF先拒绝→manager清除→删除保存；Word重复Preview/编辑/HF保存，尚未以dev代替built验收。

Word本轮最终built /tmp/word-unequal-final-built-stability.log进程51590 exit0：未编辑与真实编辑后各重复Preview cuts稳定，实际Python可信HF1op、body/sections保持，pageErrors=[]。117实际JS200/SHA，root用 /tmp/word-unequal-final-built-identities.json逐项重核静态磁盘117无不匹配。main wUtPVnqd；8次未收敛告警仍保留，sourceCompared=false，未宣称源最终不等宽shape完成。root新增rename→clear→delete保存组合绿；insert-row首轮只清首个split分区，剩余规则仍真引用导致正确拒绝，修测试清除所有分区后 /tmp/workbook-cf-removal-combined-structural-green.log1passed，生产未改。CF built首次等待不存在的“确认”按钮超时，agent正只读诊断实际菜单弹窗，尚未计本批CF built完成。

本批CF最终pureUI built /tmp/workbook-cf-sheet-removal-built-clear-source-final3.log进程72038 exit0：先真实tab删除原子拒绝，undo/redo点击后sheet/rules/draft/saveLabel原状；真实manager清除依赖→删除/undo/redo/draft→Python/openpyxl→rev2重开通过。payload严格先replaceSheetConditionalFormats Other的TRUE/stopTrue，再applySheetEdits remove Source，styles字节与数据保持，333JS200/SHA、pageErrors=[]，mainC0LkXP2Y/engineDHUBPuWA/structureDAPCydf4。前两probe失败为“确认/确定”按钮文案及误设空栈ribbon disabled契约，均仅修probe；dev exact undo/redo返回false证据独立保留。与Word117JS及统一build/budget共同收证，不外推全量完成。

下一独立真实缺口DV referenced removal已由agent只读取证：engine四项同源拒绝/安全literal-external允许GREEN，GUI仍先删Source再草稿失败，详见NATIVE_XLSX_DATA_VALIDATION_SHEET_REMOVAL_INVESTIGATION.md。后续需前置live formula1/2和incomplete真实raw检查，并在解除依赖后删除前持久化DV，不能仅补预检。Word最终源App同fixture shape尚未跑到，长段不等宽8次未收敛保留。完整goal active，不commit/push/deploy。

DV删除正式窗口：root真实main两个RED /tmp/workbook-dv-removal-main-red.log分别证incomplete raw先删成功、clear后删除草稿仍被旧源引用拒绝。扩可信raw缓存为structureSourceXml/readModelWithStructureSource，仅CF issues或DV readOnlyReason时取实际ZIP；model引用与结构签名保护保留。删除前在已有两阶段计划中追加DV当前规则回写，三plain/rename/insert-row保存定向 /tmp/workbook-dv-removal-main-save-green.log3passed；主入口接新helper可信source后incomplete /tmp/workbook-dv-removal-main-source-green.log1passed。新增CF+DV同时解除依赖 /tmp/workbook-dv-cf-removal-main-combined.log1passed，均实际保存回读。native独立文件18passed /tmp/dv-sheet-removal-native-python.log，未修改engine。最终frontend browser/build尚待，不外推完成。

DV helper终态15GREEN /tmp/workbook-dv-sheet-removal-helper-final-green.log及collector原子预检定向GREEN；unknown namespace不能完整核对时在修改前明确拒绝，不从空live误推无依赖。root全前端types /tmp/office-dv-removal-types.log exit0，CF受影响两窄回归 /tmp/workbook-dv-removal-cf-affected-regression.log2passed。真实dev拒绝 /tmp/workbook-dv-sheet-removal-dev-refusal.log及clear-source /tmp/workbook-dv-sheet-removal-dev-clear-source.log全部终态GREEN：准确formula1/uid/range/名字/history/draft保留；清除后payload仅replaceSheetDataValidations Other[]→applySheetEdits remove Source，Python/rev2/styles/data保持、pageErrors=[]。全部生产freeze后统一 /tmp/office-dv-removal-build.log启动，最终pureUI待验。

下一普通cell公式引用删除真实RED /tmp/formula-sheet-removal-browser-investigation.log：没有CF/DV，remove返回false却已删Source、Other C1变=#REF!、undo/redo均false，无原子回滚；只读探针已保留，尚未修复。不能以DV通过覆盖普通公式；Word源App临时运行仍未取得终态debug事实。

DV统一build /tmp/office-dv-removal-build.log exit0（41.92s），budget与budget-contract同prefix均exit0，未升cap（main238.4KiB/render709.6KiB）；类型检查包含在build通过。Word本轮无生产改动，不重复其上一批完整链。static继续freeze，4227最终DV纯UI进程13580 /tmp/workbook-dv-sheet-removal-built-final.log在跑。

本批DV最终纯UI /tmp/workbook-dv-sheet-removal-built-final.log进程13580 exit0：先引用拒绝、真实undo/redo点击后名字/规则/草稿/saveLabel原状；真实Data→DV面板删除规则，再tab删除→undo/redo→draft恢复→Python/openpyxl保存→rev2重开全部通过。payload精确replaceSheetDataValidations Other[]→applySheetEdits remove Source，原values和styles字节保持，pageErrors=[]。333实际JS响应200/磁盘SHA校验；mainE1BmN5bO SHA b25c34c69f9388384e7993dfb9fbf6db6e7a28dc223a7dbd2b36552fe5cecb7e，structureDBJhCmtV SHA a82f2803bb2e4a245e984d88f1efb352e721c6f48a37d131b2acf9dba63426e2，root已复核文件与探针实际响应比较逻辑。统一build/预算41.92s通过，未提交推送部署。下一普通cell公式原子性RED仍未修；Word源App临时boot仍受CJS/ESM互操作影响，未取得源最终shape，不记完成。全量目标继续active。

普通cell删除正式窗口：root main新RED /tmp/workbook-cell-removal-main-red.log三失败确证bare删失败但snapshot破坏、实际unitId qualified漏拒绝、clear后删除旧源保存阻断。新增删除前formulaEdits仅持久化存续表原有formula已改变的cell，继续已有prefix rename/structural→CF/DV/formula edits→remove计划；plain/rename/insert-row三真实保存 /tmp/workbook-cell-removal-main-save-green.log3passed。collector默认live+main可信来源接helper后live bare/internal两项 /tmp/workbook-cell-removal-main-live-green.log2passed；shared anchor已改但未投影follower原源仍拒绝 /tmp/workbook-cell-removal-main-shared-source.log1passed。raw以actual ZIP和model+structure signature缓存，使用helper筛未投影nodes，不能把shared解除计完成。native新独立11passed /tmp/formula-sheet-removal-native-python.log，未改engine。最终dev/built仍待。

Word源App同fixture原文件已运行成功：/tmp/word-unequal-source-app-attempt10.log exit0，三稳定采样源2页、followUps1/loopStops0，源/宿主同SHA9bc28e294c02b1eb9767ad5ddc171c1a1788617a25e9e470693ba7c634b0901b及viewport1600x1000但host3页。agent定位动态docStyleCss未加.docx-native scope导致文档Normal10pt间距被静态8pt覆盖（实测13.3333vs10.6667px），已授权最小scope修复与computed geometry验证，不固化页数/改源算法。

普通cell helper当前全表稀疏读取官方FormulaDataModel facade、确切runtime unitId归一及特殊来源过滤已收定向证据；review指出原raw扫描所有sheetData会误拒已清普通公式，已改仅特殊/自闭节点。另unknown namespace先前扫全XML误收CF/DV xm:f，专项RED→GREEN已改f只查sheetData。root受影响来源组合 /tmp/workbook-cell-removal-source-affected.log3passed（CF incomplete/DV incomplete/shared anchor清除）；types /tmp/office-cell-removal-types.log exit0。真实dev /tmp/workbook-cell-formula-removal-dev-refusal.log整snapshot相等、history/draft/saveLabel原状，clear-source对应日志15244 exit0，strict applyCellEdits C1=1→applySheetEdits remove Source，Python/rev2/styles/data保持。owned生产freeze，未重复完整套件。

Word scoped dynamic doc CSS最小修复已使same-SHA fixture computed margin13.3333px、宿主2页且8轮警告消失；source端终flow1350.961075 vs host1391.304825仍未同，不能以页数相同冒计不等宽最终shape完成。CSSOM scope仅处理CSSStyleRule并递归group，font-face保持，定向 /tmp/word-doc-style-scope-final-directed.log通过，未动vendor。统一 /tmp/office-cell-removal-word-style-build.log已启动，最终built双路径待验。

本批统一 /tmp/office-cell-removal-word-style-build.log exit0（39.11s），预算及契约同prefix均exit0，未升cap。两个owner已收到READY，cell最终pureUI4229进程98758 /tmp/workbook-cell-formula-removal-built-final.log运行；Word同时验证CSS最终静态。静态及生产继续freeze。Word剩余只读线索为源App在4383测量阶段用measuring-natural隐藏旧gaps、5391写回前移除，宿主snapshot目前未复用该测量环境；尚未独立RED，不先宣称根因或擅自本窗口加改。

本批最终built双链收证：cell /tmp/workbook-cell-formula-removal-built-final.log进程98758 exit0，真实tab引用拒绝→File undo/redo不变→goto C1键入1/Enter→删除/history/draft/Python/rev2全部通过；严格applyCellEdits Other C1=1→applySheetEdits remove Source，data/styles保持，333JS200/SHA、pageErrors=[]，mainB6Kmq1fR/engineBuxs6LHL/structureBYTmT2Sq。Word CSS /tmp/word-doc-style-scope-final-built.log进程28331 exit0：sameSHA三段margin13.3333、2页重复cuts稳定、无8轮告警、真实编辑后稳定、可信HF1op保存body/sections保持；117JS200/SHA，root逐项重核磁盘无不符，mainNn3ro9Eb SHA94453e94eb4b18c7647c538cccbd34b4ad81b6f88a041bd34ca371b7658e189a。构建/预算同office-cell-removal-word-style通过，未提交推送部署。Word源终cuts差异未消除，shared解除仍为未投影保守边界，不能外推全部完成。

下一定义名称引用删除已只读取证RED：global及Other local引用Source时先删且名称变#REF，undo完整snapshot不能恢复，草稿后端拒绝；/tmp/defined-name-sheet-removal-browser-{global,local}.log。下一生产窗口需前置作用域检查及当前names解除依赖先持久化，Source自有local应随表删除。Word下一自然测量gaps独立调查继续。全量goal保持active。

定义名称正式窗口：root新main RED /tmp/workbook-name-removal-main-red.log3失败证global/local删除非原子及修改后旧源阻断。新增可信workbookSourceXml按实际ZIP/model身份缓存，初始load按名称+稳定scopeSheetId+ref记录未投影失败名，匹配cfBaseline/signature后调用完整names helper。global/local前置 /tmp/workbook-name-removal-main-live-green.log2passed；pre-removal applyDefinedNames后remove顺序使plain/rename/local真实保存 /tmp/workbook-name-removal-main-save-green.log3passed。actual builtin与初始导入故障注入 /tmp/workbook-name-removal-main-source-green.log2passed；进一步failed import普通cell保存仍保原names /tmp/workbook-name-removal-import-preserved.log1passed。新增本表local随表丢弃控制 /tmp/workbook-name-removal-main-own-control.log1passed。19项native /tmp/defined-name-sheet-removal-native-python.log通过，未改engine。review指出failed local表已删时scope不能降为global，root已明确missing local不匹配global，新增同名global/local实保存回归中。

criteria实际3-sheet RED证首删ownlocal facade残留失效scope阻碍第二删；授权在既有scope collector原子并入owned name remove/undo完整元数据，不忽略未知scope。官方事务定向 /tmp/workbook-defined-name-owned-history-green.log已GREEN，真实3sheet browser待终态。Word源natural测量与Preview原生layout协议已接（未改vendor），独立旧gap污染RED→GREEN、prepareEdges复用committed cuts及正文关闭恢复已定向通过；source最终cuts仍差，当前未计完全对齐。统一build待owned scope最终freeze。

本轮review发现的失败导入local scope退化global已修为missing局部scope明确不匹配global；新增故障注入同名global/local、用户删除global再删除local所属表实际保存 /tmp/workbook-name-removal-main-failed-scope.log1passed。scope事务定向及真实三表 /tmp/workbook-defined-name-removal-owned-second-green.log进程30822 exit0：owned local首删清掉、undo完整元数据/作用域/引用恢复、redo再次清掉、第二删Other成功，pageErrors=[]。类型检查只scope新测试Nullable报错已送owner修，未改生产绕过。Word自然测量及原Preview layout协议终态dev/正文恢复已绿，仍不宣称source cuts已一致。

定义名称/自然测量统一build /tmp/office-name-removal-word-natural-build.log exit0（40.09s），budget/contract同prefix均exit0，未升cap；最终global/local/owned三UI窄链与Word同fixture自然测量协议链已发READY，生产/static freeze。root scope风险修复后的同名global/local保存回归已通过；受影响CF/DV/cell保存四定向 /tmp/workbook-name-removal-affected-save.log4passed，未重复完整测试。

下一chart删表独立调查已出现真实engine RED：默认chart namespace的<f>漏检，仅c:f对照拒绝；固定源chartReferencesSheet也仅c:f，不能冒称来源已支持。browser没有CF/DV/cell/names时delete true并保悬空chart ref，/tmp/chart-sheet-removal-{engine,browser}-investigation.log；当前未修改生产。另source已支持owned drawing级联，而本地trimmed拒绝charts/images，须作为额外源差异处理，不能固化本地拒绝冒来源契约。Word剩余source/host实际块行数26/21/20 vs25/18/21（lineheight相同），差异已定位到换行/split形状，未记完全对齐。

最终built本轮已部分收证：名称global /tmp/workbook-defined-name-removal-built-global-final.log进程99429 exit0、local对应log也终态ok，真实Name Manager改引用→删除/undo/redo/draft/Python/rev2，全scope正确，存续sheet/styles字节保持，333JS200/SHA、pageErrors=[]，mainCJ_l72AD/engineBAKi6X21/collectorBbV_9C8c。owned local连续删表纯UI还待独立终态，不把global通过外推。

Word natural /tmp/word-natural-final-built.log进程34152 exit0：sameSHA重复cuts743.7814/1291.6642及真实编辑后稳定、关闭Preview natural=false/1gap/height988，可信HF1op实际保存body/sections保持，无收敛告警、pageErrors=[]。117JS200/SHA，root逐项重核 /tmp/word-natural-final-built-identities.json与磁盘117无不符；mainBhHCTG4W SHA67d530721bdde72ec2fe003f72c5545b86752ada24fc7e0043ecdd313dacd946。source换行/最终cuts仍未对齐，独立下一阶段保留。

owned连续删除最终纯UI /tmp/workbook-defined-name-removal-built-owned-final.log进程24749 exit0：三表Source自有local名称真UI删Source→同步后真UI删Other，最终仅Third且名称管理器无残留；111实际JS200/SHA（单次加载，不与双修订333数量混淆），同mainCJ_l72AD/engineBAKi6X21/collectorBbV_9C8c，pageErrors=[]。至此本批名称global/local/owned与Word natural最终静态均收证，统一build40.09s/预算通过，未提交推送部署。完整goal继续active；下一图表namespace引用/owned drawing级联、Word源实际换行split等缺口仍在，未以本批替代全量目标。

chart引用正式窗口engine采用显式saxes6 runtime namespace parser，导出readChartFormulas；合法default/alias/scoped rebind与CDATA/text按chart URI识别，foreign c:f不误判、malformed明确抛错。32 targeted PASS/1 owned cascade独立TODO，types+单次bundle及新增native9GREEN，未扩chart-read投影。root新actual OPC来源reader workbook-chart-source.ts绑定sheet→drawing→chart并校验关系URI/安全路径，所有未归属numeric chart仍追加存续扫描以匹配engine全包检查；missing/malformed/external源错误仅缓存到model并删除时拒绝，不阻断普通load。graph3项RED→GREEN /tmp/workbook-chart-source-{red,green}.log；main实际未投影chart Source拒绝/Other保存 /tmp/workbook-chart-removal-main-green.log2passed。每model graph绑定actual bytes，并沿cfBaseline identity/signature取结构回放来源。

frontend chart helper9+collector可信callback前置1项GREEN；真实dev /tmp/workbook-chart-sheet-removal-dev-refusal-green.log整snapshot原状/history/draft不变，Other安全对照 /tmp/workbook-chart-sheet-removal-dev-safe-save-green.log删除/undo/redo/draft/Python/rev2、chart/survivor/styles原字节、pageErrors=[]。允许undo snapshot既有差异未定位，未称完全恢复。owned drawing cascade仍未完成，不能以helper跳target视为已对齐。

Word同SHA新字体证据：原App有loaded Caladea、同句measureText273px，宿主无faces fallback251.525px；probe窄栏36vs30行。已授权迁入固定源Caladea四原字体+原@font-face/license/provenance宿主assets，不动vendor分页算法。初接入cuts744.2813875/1350.961075与source同，浮点1e-13差已作为probe数值精度问题处理，最终字形/shape与built尚待收证。

用户追加“多支持中文字体”：复用固定源Noto Sans/Serif CJK SC两原woff2、四条SC/GO原@font-face及SIL OFL1.1；4,912,432bytes，provenance四项root独立SHA核对一致。Word/XLSX共享assets/docx-cjk，XLSX在createUniver前显式load两SC字体防首次canvas字宽缓存。两端菜单新增思源宋/黑及宋体、黑体、微软雅黑、楷体、仿宋五系统选择，label区分内置/系统；不分发专有字体、不承诺生僻字全覆盖或桌面Office/PDF等价。XLSX真实Univer菜单7family→保存重读字体定向1GREEN，菜单2GREEN；Word真实dev四font-face loaded、中文4页重复Preview稳定、局部思源黑保存eastAsia且Latin保留，/tmp/word-cjk-final-dev.log exit0。中西字体槽冲突修复及统一built验收仍进行，不先称完成。

中文字体脚本槽修复：共享固定source字体名predicate语义到bridge/docx-font-slots.ts；live Ribbon、draft replay与native bridge同源映射CJK→font/eastAsiaFont、Latin→fontAscii，保另一script槽，null仍清全部direct font槽。collector识别slot变化映射既有fontFamily协议；同时改中西槽或正文变化后slot变化明确提示分别保存，fontCs/theme独立编辑继续拒绝。修复空默认mark归一以免纯文字误拒。source TS真实native非null组合6passed(/tmp/docx-font-slots-native-source.log，其同批null用例自身访问空rPr错误)，修正测试后null2passed(/tmp/docx-font-slots-native-null-green.log)；frontend最终slot9passed(/tmp/docx-font-slots-defaultguard-green.log)，Home等18及范围原5已受影响验证；最终types exit0。详见NATIVE_WORD_FONT_SCRIPT_SLOTS.md。统一built进行中。

图表/Caladea/中文统一构建：首build通过但main269.8KiB>250预算，未升cap；自然分离saxes/xmlchars解析库workbook-xml-parser与图表来源/预检workbook-chart-references后，最终 /tmp/office-chart-cjk-caladea-final-build.log exit0(40.68s)，同prefix final-budget与final-budget-contract均exit0，main240.9KiB/XML53.6KiB/graph1.9KiB。最终static浏览器验收已下发，须以这些产物的实际初始化/JS和字体200+SHA为准。

最终static首轮：chart拒绝114JS与Other保存342JS均200/SHA且pageErrors=[]；/tmp/workbook-chart-sheet-removal-built-{refusal,safe-save}-final.log均exit0，后者Python/rev2+part原字节。XLSX中文 /tmp/workbook-cjk-font-built-final.log exit0，两SC真实woff2 200/SHA、7菜单family实际保存重开全过、228JS200/SHA；root已目视/tmp/workbook-cjk-font-built.png正常。Word Caladea /tmp/word-caladea-final-built.log exit0，同fixture117JS+4Caladea字体200/SHA、重复/编辑/HF保存过；中文 /tmp/word-cjk-final-built.log exit1，新actual selected-chain断言明确发现marks与保存已Sans但CSS仍Serif。诊断为源font resolver将Noto映射Word SimSun替代，不记Word中文完全通过；继续修复已内置family可用性注册，未放宽断言。

Word中文built RED根因已独立确认：源resolveFace没有宿主实际内置字体指标，Noto SC落入Word SimSun替代。新增host loadDocxBundledFonts，真实load成功后把两原woff2 FontTools head/hhea/OS2指标登记最小vendor setBrowserFontMetrics seam（只browser map优先，其他installed IPC/snapshot规则原样；避免provider返回null屏蔽snapshot），docx-main在adoptEmbeddedFonts后await登记。原文档嵌入字体优先保留；失败load清旧登记。真实runFaceDecls RED→GREEN+snapshot/embedding/loadfailure4项与script9项共13passed，root独立核验原二进制metrics及vendor SOURCE/LOCAL SHA。新统一 /tmp/office-cjk-browser-font-final-build.log进行，最终浏览器等待。

中文字体最终收证：/tmp/office-cjk-browser-font-final-build.log exit0(40.40s)，同prefix budget+contract exit0；render709.7KiB未升cap，XLSX main仍BnjejPFA240.9KiB/其他已验图表字体chunk未变不重复完整验收。Word最严选中inner text node /tmp/word-cjk-registered-inner-textnode-built.log exit0：中文字体4字实际computed首family=Noto Sans CJK SC，EA变量同，Latin Serif保留，保存重开通过，2原woff2 HTTP200/SHA，117JS身份核对通过，pageErrors=[]。正确metrics使中文fixture6页（原替代font4页），重复稳定而非固定页数。Caladea /tmp/word-caladea-registered-built.log exit0及/tmp/word-caladea-registered-source-comparison.json：同SHA fixture cuts744.2813875/1350.961075与固定源误差<1e-6，字宽273、split373.78/415.08/156.36+inset218.42，真实编辑/重复Preview/HF保存通过，117JS+实际6字体200/SHA。本批中文支持完成浏览器与OOXML保存验收；生僻字/完整粗斜字体/系统专有字体和后端PDF字体嵌入、桌面Office等价未纳入，整个Word/XLSX全量对齐仍未完成。

下一轮全量对齐：chart rename默认/别名/CDATA等namespace兼容修复engine10GREEN+native5GREEN；固定源仍c:f regex故明确本地修复。root另复现同一chart双sheet rename后前一改名被覆盖，sheet-ops改取replaced累计后 /tmp/chart-multi-rename-{red,green}.log 1RED→GREEN；actual frontend rename→save→删除新名原子拒绝 /tmp/workbook-chart-rename-main-first.log1GREEN。owned drawing/image delete按固定源owned闭包、存续incoming共享拉回及子树保留；helper13+safe7GREEN；root sheet-ops接入skip dying chart引用/rename、删除satellite及rels、清Override保Default，4实际ZIP /tmp/owned-drawing-delete-integrated-green.log GREEN；rename+delete窄组合 /tmp/owned-drawing-delete-rename-combination.log1GREEN。root frontend exclusive允许保存parts删除/Other+styles保、shared chart引用Source原子拒绝 /tmp/workbook-owned-chart-main-green.log2GREEN。最终bundle/static GUI尚待，owned旧TODO已转真实可执行契约。Word重复标题行源语义与协议实现31窄测GREEN，active/merged补验进行，尚待bridge bundle与真实Python/UI保存重开。

owned cascade review补齐：移除blanket后可能放开table，已按固定源新增assertRemovedTableDependencies，实际SalesData结构化跨表ref/存续names/removed local例7GREEN及真实applySheetEdits集成1GREEN；前端table引用删表原子预检仍明确独立缺口（未以engine守卫冒计）。原owned TODO单测转可执行后1GREEN /tmp/chart-owned-cascade-former-todo-green.log。引擎typecheck /tmp/chart-rename-owned-engine-types.log exit0、bundle /tmp/chart-rename-owned-bridge-bundle.log exit0。Word重复标题行最终PM/helper32GREEN，合并DOCX Python6GREEN（首测试zip目录/顺序假设错误已修为真实文件集合+byte一致）；统一Word bridge仅bundle一次exit0。frontend首build因新merged测试JSON类型未收窄失败，改为实际PM Node读取后第二最终build进行；无生产绕过/无预算放宽。

### 2026-11-10 Word Table Layout：重复标题行独立增量

`table-repeat-header-rows` 已由清单项接入固定源首行连续前缀toggle/active语义，支持普通和合并来源表，不借用结构编辑或固定宽度门槛。严格新操作 `setTableRepeatHeaders` 以可信table hash/expectedRowCount/prefixRowCount及headers终态写回，只改直接trPr/tblHeader；PM Undo/Redo、草稿精确回放、ARIA active、嵌套XML保留32项窄测通过，真实Python合并DOCX保存/关闭恢复全部文件部件原字节与5项拒绝共6项通过。详细范围、源文件SHA及RED/GREEN见 `NATIVE_WORD_TABLE_HEADERS_PLAN.md`；最终frontend静态GUI仍等root统一build，不将实现通过记作静态验收完成。独立嵌套表anchor、合并/拆分单元格命令、复杂表结构增删与行列属性仍各自保留缺口。

本轮最终统一构建 /tmp/office-chart-owned-word-headers-final-build.log exit0(40.83s)，对应budget/contract exit0，未升cap；engineB1-xJNXH372.2KiB/mainMtsn8kgY240.9KiB/docx-main7KG1kDmH155.5KiB，renderBSfJ0zJF709.7KiB未变。最终chart rename default与alias /tmp/chart-sheet-rename-built-{default,alias}-final.log均业务与身份GREEN：UI undo/redo、draft reload、Python仅chart+workbook改变、显式rev2重开、图表引用删新名原子拒绝、342JS200/SHA/pageErrors=[]。owned exclusive/shared-image两链 /tmp/workbook-owned-drawing-{exclusive,shared-image}-built-final.log均GREEN342JS200/SHA：删除/history/draft/Python/rev2、无悬挂内部关系/Override、Other/styles及共享media/drawing/foreign部件字节保。shared-drawing agent因模型403 insufficient balance中止后root接管跑 /tmp/workbook-owned-drawing-shared-drawing-built-final.log，业务与114JS身份GREEN、引用删除原子拒绝、pageErrors=[]；root目视exclusive截图正常。Word /tmp/word-repeat-header-final-built-identity.log：enabled/active/undo/redo/draft/rev2开/关闭rev3开与实际Python flags通过，117JS200/SHA。三个子agent后续均因上游模型余额不足403结束，root检查无在途smoke进程后接管缺项，未重复已绿完整测试。全量目标保持active，表格结构化引用live原子预检、pivot来源删除、复杂表组合/嵌套与其他源功能仍未完。


### 2026-11-10 中文字体扩展：五款内置字体（本地功能，固定源外扩展）

- 新增霞鹜文楷 / LXGW WenKai、马善政毛笔楷书 / Ma Shan Zheng、站酷小薇 / ZCOOL XiaoWei。固定提交下载、原始 SHA、WOFF2 子集 SHA、逐项 OFL 授权均登记于 frontend/src/assets/docx-cjk/provenance.json。新增资产分别 1,598,776 / 3,234,020 / 2,617,472 字节，cmap 分别 7619 / 6995 / 6995 字符；GB2312 与 U+0020–00FF 子集，不宣称全汉字覆盖。原有两款思源资产未改。
- Word 菜单与 XLSX 菜单均提供实际 family 名；Word 实时选择 / 草稿回放 / Python OOXML 桥接统一判定东亚字体，只修改 eastAsia 并保留 Latin。XLSX 在 Canvas 引擎初始化前加载五款字体。Word 实际加载成功后登记真实 FontTools 表指标；站酷小薇原始代码页标记缺少中文位，因此仅对已核验内置 CJK 资产显式登记 eastAsian=true，原始指标与其他字体来源规则保持原值。
- 定向 RED：/tmp/cjk-expanded-fonts-red.log（缺菜单、Ma/ZCOOL 被错误写入 Latin）；/tmp/cjk-expanded-resolver-final.log（ZCOOL 被错误归为西文行高）。GREEN：/tmp/cjk-expanded-fonts-green.log 5项、/tmp/cjk-expanded-resolver-green.log 7项、同批 font-slots 12项通过；/tmp/cjk-expanded-fonts-python.log 14项 Python 直接桥接通过。未运行完整测试套件。
- 生产构建 /tmp/office-cjk-expanded-build.log exit0；budget 与 budget-contract 同前缀日志 exit0。workbook-main DNXdHCvd 244.4 KiB；docx-main B-VMnren 156.8 KiB。未提高预算。
- 真实 Chromium 生产资源：/tmp/cjk-expanded-xlsx-browser.log exit0，五字体真实加载、十个菜单字体逐项选择、Python patch/ZIP/openpyxl 回读、明确打开 revision2 后逐项一致，228 次 JS 200及SHA、五个字体200及SHA，无页面错误。截图 /tmp/workbook-cjk-font-built.png 已人工查看。
- Word 三份日志 /tmp/cjk-expanded-word-{wenkai,mashan,zcool}-browser.log 均 exit0；选中实际中文内层节点 computed font、DOCX eastAsia 写入、原 Latin 槽保留、明确 revision2 重开字体保持，五个字体真实加载且身份匹配，分页六页重复稳定、无页面错误。HTTP context/revision/save 为替身路由，Python patch 与浏览器真实执行；不等同生产 HTTP 全链路验收。
- 剩余：系统字体安装不可保证；生僻字仍后备；粗体/斜体为浏览器合成；DOCX 不嵌入这批字体，桌面 Office 需安装；服务端 PDF 字体嵌入/渲染没有在本轮实施或验收。全量对齐目标继续开放，不据此计算总体百分比。


### 2026-11-10 表格所属工作表删除原子性收尾

前端稀疏结构化引用、实时CF/DV及名称依赖预检完成，拒绝时不改快照/草稿；清引用后原生删除及完整表格元数据 undo/redo 正常。定向8GREEN及最终生产浏览器拒绝/放行两模式均exit0，日志 /tmp/workbook-table-removal-built-{refusal,clear}-final.log。放行模式 Python ZIP 回读和明确revision2重开正常，342次JS200及SHA；拒绝模式114次，均无页面错误。最终统一构建及预算 /tmp/office-cjk-expanded-* exit0。详情及未投影表格/透视缓存边界见 NATIVE_XLSX_TABLE_SHEET_REMOVAL_INVESTIGATION.md。本条替代“前端结构化引用删除尚未原子化”的旧状态，不代表全量对齐完成。


### 2026-11-10 透视缓存来源删除与只读表格身份闭环

本轮恢复后检查无残留测试/build/smoke进程，按实际代码接续子agent产物。透视文件引擎3真实RED→新13用例及既有19用例通过，纯helper拆分后13和tsc通过，详见 workbook_engine/PIVOT_SOURCE_SHEET_REMOVAL.md。root前端真实ZIP RED /tmp/pivot-removal-main-red-real.log（删除Source错误返回true）→GREEN：实际包缓存XML与模型身份绑定，完整解析后在原生删除mutation前拒绝；缓存读取失败只影响相关删除，不阻断文件打开。无关删除仍允许。

只读表格engine将独立tableSources与编辑tables分开，完整空列表/未核对身份区分，projection失败仍保留全部根身份；保存端同一根解析保护双别名和真实关系定位的非标准part，共享incoming由既有planner保留。定向61项及engine tsc通过，详见 workbook_engine/READONLY_TABLE_SOURCE.md。root将各含表页最终removedParts按可信模型缓存，使用所有incoming关系的实际删除计划排除保留表；不再依据编辑投影失败一律拒绝。真实main RED /tmp/readonly-table-main-red.log → 六项受影响GREEN /tmp/pivot-readonly-main-green.log（含既有结构化引用、clear→delete、pivot拒绝/放行、readonly拒绝/放行）。不重复完整套件。

统一构建 /tmp/office-pivot-readonly-build.log exit0 (44.72s)，预算和contract同前缀exit0，bridge /tmp/office-pivot-readonly-bridge.log exit0；main0vGsEY2k245.4KiB、engineB9pC2Rr5374.8KiB，无提高预算。root核验本批7个生产引擎文件SHA与登记一致。

最终production Chromium四链均exit0：
- /tmp/workbook-pivot-removal-refuse-browser.log：Source被Pivot缓存引用，删除拒绝，history/draft/save状态保持，114次JS200/SHA。
- /tmp/workbook-pivot-removal-allow-browser.log：删Unused→undo/redo→草稿刷新→真实Python保存→明确revision2重开；pivot/cache/关系part集合及原字节、Pivot sheet/styles不变，342次JS200/SHA。
- /tmp/readonly-table-browser-refusal.log：tableColumns计数故障注入导致编辑只读，存续SalesData引用仍在时删除原子拒绝，114次JS200/SHA。
- /tmp/readonly-table-browser-clear.log：同只读表先通过界面清除Other!C1引用，再删除Source→undo/redo→草稿恢复→真实Python保存→revision2重开；仅Other，表part删除，B1:B5与styles不变，342次JS200/SHA。
全部pageErrors为空；HTTP context/revision/save为替身路由，浏览器与Python/ZIP真实执行，不据此声称生产HTTP或桌面Office验收。子agent浏览器无残留进程，root两个smoke session均exit0。

Word嵌套表调查完成真实双同胞DOCX探针：两个相同内层表阅读anchor均1，只有外层来源签发；源底层补丁可精确改第二张并保留其余XML。详见 NATIVE_WORD_NESTED_TABLE_ANCHOR_INVESTIGATION.md；尚未实现独立嵌套协议/输入岛flush/选择和保存闭环，仍为下一批缺口。透视改名/结构移位/命名范围源及透视编辑也未被本批补齐，全量目标保持active。


### 2026-11-10 第一层嵌套表文字编辑闭环

独立内层table/cell来源身份、严格replaceNestedCellText、真实XML局部补丁与DOCX回读、前端diff/replay及输入岛能力/保存flush完成。两张相同表可精确改第二张；只读/保存锁/外层命令误操作保护、内层Ctrl+A及提交拒绝反馈完成。原空正文fontSlots回归定向修复。详见 NATIVE_WORD_NESTED_TABLE_ACCEPTANCE.md（范围/限制/逐层证据）。

最终 /tmp/office-word-nested-budget-fixed-build.log 与budget/contract exit0，无提高预算；render3Z3gu3C-709.9KiB/mainCTiRKV1E158.3KiB/table-inputJY6Wgg3M1.0KiB。真实GUI /tmp/word-nested-built-smoke-final.log exit0：118JS200/SHA、Ctrl+A限定格、草稿刷新、保持岛内焦点保存、Python真实patch、下载与明确rev2重开、第一张/外部XML/OPC部件不变、中文emoji多段尾空段保持，errors=[]，无残留进程。root目视重开截图正常。HTTP为替身路由，不宣称生产HTTP/桌面Word/PDF。内层合并/结构/重复表头、更深嵌套、复杂来源及tab/br投影仍是独立缺口，全量目标未完成。


### 2026-11-10 透视缓存来源工作表改名闭环

namespace-aware renameSheetInPivotCacheSource接入实际sheet-ops，连续改名读取已替换版本避免覆盖。纯helper先验证完整XML再精确改属性，支持default/alias/strict与实体编码，DOCTYPE/损坏拒绝。真实ZIP定向10GREEN、既有相关32GREEN，引擎types零错误，详见 workbook_engine/PIVOT_SOURCE_SHEET_RENAME.md。root实际main来源改名保存后再删新名 RED→GREEN 1项（/tmp/pivot-rename-main-{red,green}.log）。

统一build /tmp/office-pivot-rename-build.log exit0(40.67s)、budget与budget-contract同前缀exit0；workbook bridge /tmp/office-pivot-rename-bridge.log exit0，未升cap。最终production Chromium default/alias /tmp/pivot-rename-browser-{default,alias}.log均exit0：纯UI改名→undo/redo→草稿刷新→Python真实patch→ZIP/openpyxl回读→明确revision2重开→新名来源删除原子拒绝；各342次JS200且SHA匹配，pageErrors=[]。仅workbook/cacheDefinition变化，其余部件集合及字节保留。alias缓存还经过既有zip.ts readText→xml.ts normalizeOoxmlPartPrefix（去q前缀并default/r声明），probe严格比较该已知规范化与唯一来源属性变化，未声称alias原缓存字节只改sheet属性。HTTP context/revision/save为替身路由，非生产HTTP或桌面Office全链路。

Word合并/拆分下一批独立协议与逻辑网格实现进行中，NATIVE_WORD_MERGE_SPLIT_INVESTIGATION.md的四真实源探针已确认原始XML丢失风险；未将调查或未最终验收代码计为完成。全量Word/XLSX目标保持开放。


### 2026-11-10 Word 来源表格合并与拆分闭环

独立reshapeTableCells协议、服务端逻辑矩形能力、共享PM/source split语义、整数twip、原段落XML token、collector/replay/undoRedo及Ribbon拆分对话框完成，合法已有span来源保存后继续编辑通过。全文宽rowspan覆盖行的宿主PM schema从+扩为*，避免自动产生幽灵格；旧物理cell身份在结构修改后不再上报。独立复核发现生成器改写非目标tcPr主题属性及空白排版字节，均先RED后修复为只补宽/span字段、保留原cell/trPr及paragraph片段。详细证据与剩余边界见NATIVE_WORD_CELL_SHAPE_ACCEPTANCE.md。

core9、collector2、UI9、原行列兼容31、bridge最后7及Python首6+追加5定向通过；未重复全量套件。旧Ribbon字体名单漏三款已实现字体，仅修该预期后原失败项通过。最终frontend /tmp/office-word-cell-shape-final-build.log exit0(40.56s)、budget/contract exit0，未升cap；首build在UI提交前报union.extend类型错误，显式DocTableRow.extend修正后最终build通过，不隐藏失败。最终bridge /tmp/word-cell-shape-bridge-final-bundle.log exit0。

最终production Chromium /tmp/word-cell-shape-built-smoke.log exit0：鼠标完整2x2选格→merge→undoRedo→默认split两个rowspan2→撤销→显式2x2→草稿刷新→公开保存/真实Python/真实下载/ZIP→明确rev2重开；独立实际merged来源rev10拆存→rev11重开通过。119个不同JS200且SHA核对，无页面错误。12原段落XML逐字及阅读顺序、所有其他OPC部件和表外XML身份不变。root目视/tmp/docx-cell-shape-built-nEvW2o/revision-11-reopened.png。HTTP仍为替身context/revision/save，非生产HTTP/桌面Word/PDF等价证据。

复杂continuation/嵌套/修订等来源、同表与其他编辑混合、自动宽度与复杂网格仍未完成。XLSX下一批已实际复现透视来源行列变更不安全：本地会移格但cache ref不变，固定源拒绝此编辑；正补engine与frontend同源原子保护，不将尚未实现的ref同步算为完成。全量目标仍开放。


### 2026-11-10 XLSX 透视来源行列编辑原子保护

固定源明确拒绝透视来源页行列移位；本地原先移动数据却留cache旧ref，已在引擎applyRowColumnOps实际ZIP缓存预检补齐。新12真实ZIP GREEN及types通过，详见NATIVE_XLSX_PIVOT_SOURCE_SHIFT_INVESTIGATION.md，不冒计为新增ref同步支持。frontend同源guard覆盖命令服务before、结构拦截器及直接mutation；工作表名称身份和行列几何分离避免无关页Undo误拒。main4GREEN覆盖原名/改名来源各12命令及raw mutation拒绝的完整snapshot/history/draft/save不变，无关页普通/改名组合插行列、UndoRedo和真实保存；结构兼容16GREEN。

首built暴露facade吞底层false而Ribbon无条件markDirty/覆盖错误原因，新增真实helper+main callback RED→GREEN1项，提取同源函数在facade前检查。最后/tmp/office-pivot-source-structure-ribbon-build.log exit0(40.24s)，budget/contract exit0，workbook bridge /tmp/pivot-source-row-column-bridge.log exit0，未升cap。

最终/tmp/pivot-source-structure-built-smoke-http.log exit0：Source四enabled Home按钮真实尝试插/删行列原子拒绝，原生复制矩阵、完整localStorage、保存label和history状态保持；Unused插行UndoRedo/插列、草稿刷新、Python真实patch、浏览器实际下载、明确rev2重开均通过。仅sheet3.xml变化，Source/Pivot/styles及全部其他ZIP部件原字节保留，342JS200及SHA匹配，errors=[]。原route拦截下载在独立标准a-download最小探针也canceled，最终改随机127.0.0.1真实临时HTTP endpoint，不放宽下载/path/SHA断言。root目视/tmp/pivot-source-structure-built-zViXQb/revision-2-reopened.png。公开UI外证与main内部完整snapshot断言分层，HTTP授权/修订仍为替身，不宣称生产HTTP或桌面Excel等价。

下一Word指定列宽/均分列实现进行中，尚未完成最后built验收。全量对齐目标继续开放。

### 2026-11-10 Word 指定列宽与均分列闭环

独立 resizeTableColumns 协议、签发逻辑网格与实际来源节宽、共享来源 fit、整数 twip 余数分配、只改三类原始宽属性值的 bridge、collector/replay/Ribbon/UndoRedo 完成。加载转换器的整数像素取整会丢奇数 twip，新增真实宿主来源归一化 RED→GREEN，baseline 前恢复精确宽度且不生成意图、更新事件或历史；刷新草稿不覆盖已编辑宽度。多栏/未知几何及同表混编、同节页面布局变更保持明确边界，不把整页宽冒作实际栏宽。详见 NATIVE_WORD_TABLE_COLUMN_WIDTH_ACCEPTANCE.md。

最终 frontend /tmp/office-word-column-width-final-build.log exit0（39.85s），budget/contract exit0 未升cap，bridge /tmp/word-column-width-final-bridge.log exit0。core7、bridge初5+几何2、UI初6+宿主2+归一化1及兼容40等针对性证据见专项文档，未重复完整测试。

最终 /tmp/word-column-width-built-smoke-rerun.log exit0、ok=true/errors=[]：单列指定→UndoRedo→单列均分全表→两列局部均分→草稿刷新→Python真实patch→实际HTTP下载→明确rev2重开；独立复杂横纵合并与隐藏continuation来源保存→rev11重开通过；DOM*15与奇数源grid精确一致，页面9000上限及多栏只读通过。原document.xml仅三类宽属性值变化，其他XML/OPC部件字节不变，JS200核对本地SHA。首轮probe在Undo/Redo间点击Ribbon夺焦失败，修正操作顺序并增加Undo精确断言后必要重跑，不隐藏失败或放宽断言。实际产物 /tmp/docx-column-width-built-tanTUM。授权/修订路由为替身，非生产HTTP/桌面Word/PDF等价。

新调查确认行高/均分行高入口仍禁用且无保存协议，固定来源均分依赖DOM实际高度/zoom，不能用原声明高度均分冒充；NATIVE_WORD_TABLE_ROW_HEIGHT_INVESTIGATION.md含真实源DOCX探针。下一批独立指定/清除行高core与bridge已启动，均分行仍待独立DOM协议。全量Word/XLSX目标保持开放。

### 2026-11-10 Word 指定与清除行高闭环

setTableRowHeights 严格逻辑行带协议、实际所属节正文高度、共享投影、collector/replay与Ribbon完成；输入0或空恢复自动，原exact/atLeast保留，合法auto/零声明可编辑。窄复核发现显式空hRule放行问题及合法auto来源误拒，均新增RED→GREEN修复。只改直属trHeight，格网/段落/复杂continuation及非目标部件原样保留，实际保存回读验证；保护/hash/同表混编及同节页面设置依赖具备针对性证据。详见 NATIVE_WORD_TABLE_ROW_HEIGHT_ACCEPTANCE.md。

首统一build通过但XLSX main超250KiB预算0.4KiB，只拆独立高亮模块，最终 /tmp/office-row-height-cross-highlight-final-build.log exit0（40.51s），budget/contract exit0未抬cap，main247.5KiB、高亮块3.1KiB、Word main159.0KiB；最终bridge /tmp/word-row-height-final-bridge.log exit0。core3、bridge初3/追加/auto2、UI7+选区1、列宽兼容9、Python协议/实际保存/节预算/保护及auto3、前端节契约1通过，未重复完整测试。

最终 /tmp/word-row-height-built-smoke.log 首轮exit0、ok=true/errors=[]、120JS200/SHA：指定600保exact→UndoRedo→输入0清除→草稿刷新→Python实际patch/真实HTTP下载→修订2；自动行750恢复atLeast→修订3；独立复杂rowspan覆盖两行900→修订11；30000请求截到原节14800→修订12。DOM属性严格比对，mask仅直属trHeight后完整XML及其他OPC文件字节相等。产物 /tmp/docx-row-height-built-hEuDYT，root目视revision-11-row-height-reopened.png及上限修订12，正常合并布局与高度呈现。授权/修订替身不冒称生产HTTP或桌面Word/PDF等价。

均分行高仍未完成。下一真实DOM调查已发现宿主zoom位于PM根而源helper读wrapper，直接搬用会在缩放时算错；正在设计按真实100%DOM测量再恢复显示，不用声明高度冒充。XLSX活动行列高亮已实现并在独立built像素验收中，未提前标为通过。全量目标保持开放。

### 2026-11-10 Word 平均分布各行闭环

共享行高协议增加严格distributeTableRows步骤，强制atLeast，旧set保持原规则；测量值不套用旧set的节高clamp，允许合法实测超页，当前模型上限31680。真实TR DOM临时100%测量后finally恢复原zoom/priority，所有行必须成功；准备具15秒期限与状态变化取消、事件/帧/计时器清理，允许宿主fallback字体的实际排版。独立review的pending图片及fonts.ready语义问题均已记录并处理。证据见 NATIVE_WORD_DISTRIBUTE_ROW_HEIGHT_ACCEPTANCE.md。

core5、新bridge2与legacy6、Python新协议6、UI/测量15及取消追加1、真实宿主测量13向量、types通过；未重复完整测试。最终bridge /tmp/word-row-distribute-bridge-build.log exit0，统一frontend /tmp/office-row-distribute-cross-highlight-build.log exit0（40.25s），budget/contract exit0未抬cap。

最终 /tmp/word-row-distribute-built-smoke.log 首轮exit0、ok=true/errors=[]：公开100/150/75%入口三档同源caret均分整表全部1312twip，UndoRedo/zoom恢复/draft/Python实际patch/HTTP真实下载/ZIP/新修订重开通过；鼠标局部两行927、第三行500不变。mask仅直属trHeight后全documentXML及其他OPC文件字节不变，JS200/SHA匹配。root目视 /tmp/docx-distribute-row-built-n70w1P/local-rows-reopened.png，未冒计生产HTTP/桌面Word/PDF等价。

XLSX高亮built发现RTL坐标倒序丢行带，窄RED/GREEN最小修复后真实RTL/普通/冻结/150%/主活动格反选像素均通过，远处空白导航仍在最终验收。AutoFit三个Word入口已确认未接通，NATIVE_WORD_TABLE_AUTOFIT_INVESTIGATION.md含18真实源DOCX探针，未把调查计为交付。全量目标继续开放。

### 2026-11-10 Word AutoFit 三模式闭环

严格setTableAutoFit有序mode步骤、独立fixed/contents/pct准入、baseline前整数twip归一化、共享投影及只补直属width/layout/grid/tcW的bridge完成。仅fixedGridWidths逐字摘录，其余等效投影；完整记录contents→window→fixed，避免折叠末mode改变网格。保护/hash/所属单栏节宽/同表与同节布局冲突具定向证据。review发现前端误拒异节分节批次，新增sourceSectionId后RED→GREEN，实际Python正反序均成功；另12个pct50/省略宽度序列及5个伪造几何/合法嵌套审查向量通过。详见 NATIVE_WORD_TABLE_AUTOFIT_ACCEPTANCE.md。

core3、bridge初4及插入顺序/源mode/回读追加、UI7与types、Python7+跨节1、前端节契约通过，未重复完整测试。最终bridge /tmp/word-autofit-section-bridge-build.log exit0；统一frontend /tmp/office-autofit-goto-build.log exit0（40.76s），budget/contract exit0未抬cap，XLSXmain249.0KiB/Wordmain159.4KiB。

最终 /tmp/word-autofit-built-smoke.log 首轮exit0、ok=true/errors=[]、120JS200/SHA：13次公开保存/真实Python/实际HTTP下载/ZIP/新修订重开，覆盖fixed、contents、70%pct缺tcW、复杂merge/hidden continuation、100%window。直接fixed保1801/2401/3001整数网格，完整模式序列及UndoRedo/draft后保存3000×3；另逐模式各最终修订回读通过。仅四类直属geometry标签变化，非目标XML/OPC与cell身份不变。root目视 /tmp/docx-autofit-built-Mw4BvQ/revision-32-autofit-reopened.png；授权/修订替身非生产HTTP/桌面Word/PDF等价。

XLSX goto远目标滚动也已通过五场严格built，专项由XLSX agent追加。下一Word文字方向三个入口未接通，NATIVE_WORD_TABLE_TEXT_DIRECTION_INVESTIGATION.md有10真实源方向向量；属性、插删格、边距/对齐等仍逐项待交付，不以本批表格能力代替全量目标。

### 2026-11-10 XLSX 活动行列突出显示闭环

固定 GenOffice canvas helper 迁入宿主独立模块，以真实 Worksheet WeakMap
隔离实例，官方 selection command 更新主活动格；View 阅读偏好支持只读、
刷新与主题/销毁生命周期，不写文件、样式、草稿或历史。built 实际像素发现
RTL 反向坐标丢行带，独立 RED→GREEN 最小修复端点 min/max；不是仅纯几何验收。
详见 NATIVE_XLSX_CROSS_HIGHLIGHT_ACCEPTANCE.md。

root 最终统一build /tmp/office-row-distribute-cross-highlight-build.log exit0
（40.25s，含tsc），budget/contract exit0未抬cap；初main超预算通过拆独立
高亮chunk解决。定向 helper/Ribbon/main/只读/存储/RTL/隐藏轴用例通过，未重复
完整测试。最终 /tmp/xlsx-cross-highlight-built-smoke.log session82482明确exit0、
ok=true：普通/冻结/150%/RTL/反向选区主cell的实际混色及恢复100%，远处空白
85182px、行1363/列664px带、恢复100%；原生剪贴板确认反选矩阵。230JS200/SHA，
偏好reload，完整draft/history/save态不变，save0、pageErrors[]。source与真实
下载before/after SHA均e665e4fae5b03534db912e65f188055a84553d1eb8aefe390144cc4397c11e2f。
root已目视 /tmp/cross-highlight-built-AAfR14/rtl-on.png，授权路由为本地夹具，
非生产HTTP/桌面Excel/浏览器打印等价。

goto远处只选不滚动是真实独立导航差异，已留失败证据并只读调查，未顺手改
生产；高亮通过原生方向键滚入后验收。不把此差异或后续Word AutoFit调查计为
已交付，完整Word/XLSX对齐目标继续开放。

### 2026-11-10 XLSX 定位远处目标滚动闭环

固定source revealCellBelowFreeze迁入宿主独立helper，保留原setActiveRange、
跨表与模态框关闭后的官方焦点语义；官方scrollToCell/getVisibleRange校正
冻结偏移，考虑RTL/全部冻结viewport，实例级取消新导航/替换/dispose。
实际可见才报告目标已显示，失败保留选区并给原因；旧失败不覆盖新导航。
不改已验收高亮或引入源lazy系统。详见 NATIVE_XLSX_GOTO_SCROLL_ACCEPTANCE.md。

helper7、main只读跨表/失败反馈3、迟到回调1、焦点兼容4 GREEN，main真实接线
先RED后GREEN，完整snapshot/draft/history/save态不变，tsc exit0。root统一
/tmp/office-autofit-goto-build.log exit0（40.76s），budget/contract exit0，未升cap。
最终 /tmp/xlsx-goto-scroll-built-smoke.log session66605明确exit0、ok=true：五场
真实sheetProtection来源Plain/自定义高宽Frozen/150%/RTL/Far直接Z25001，完全
无方向键补滚动，精确可见反馈+实际画布像素通过，关闭恢复100%；230JS200/SHA，
reload/state不变、save0、errors[]，真实下载before/after/source均
62309006fa04bad848c07b784987df0ff3564e90cbd488ce4fb0be0445418bbe。
产物 /tmp/goto-scroll-built-o6aIj7，目视推荐frozen-distant-on.png、rtl-distant-on.png。

顶层editingEnabled=false既有native-office-view全局门禁禁止挂载在线编辑器，
首probe因此无法出现Home；失败证据保留，最终built明确限真实受保护表阅读，
不冒称关闭功能时仍有UI导航；main层false另有集成证据。HTTP授权/修订为夹具，
非桌面Excel/打印等价。Word AutoFit与后续文字方向专项独立推进，完整目标开放。

### 2026-11-10 Word 表格文字方向三模式闭环

横排、90°与270°已接入来源绑定的严格步骤、UI/草稿、无损直属textDirection补丁与实际保存回读；合并owner与全部物理continuation同步，未选内容保留，独立页面设置可同批。详见 NATIVE_WORD_TABLE_TEXT_DIRECTION_ACCEPTANCE.md。

core3、bridge4+1、UI6、Python6及限定types通过；bridge build exit0，统一frontend /tmp/office-cell-text-direction-build.log exit0（41.41s），budget/contract exit0未升cap。未重复完整测试。

最终 /tmp/word-cell-direction-built-smoke.log 首轮exit0、ok=true/errors=[]：三来源乘三方向共9次真实Python保存、HTTP下载、ZIP与新修订重开；实际字符Range沿Y正/Y负/X正，UndoRedo/draft通过。mask仅直属textDirection后完整document.xml与其他OPC部件字节保持，120JS200/SHA。root及UI agent目视合并格旋转截图。产物 /tmp/docx-cell-direction-built-p1RPVx/；授权/修订路由为夹具，不代表生产HTTP、桌面Word/PDF等价。

下一Word九宫格对齐仅完成18个真实源组合调查，尚未交付；XLSX分页预览独立模块9项定向测试与types通过，尚未主界面接线/最终浏览器验收，结构编辑后的分页符坐标一致性需解决。完整目标继续开放。

### 2026-11-10 Word 九宫格对齐与 DOC engine 独立目录

九种垂直/水平组合以严格矩形steps接入前端、collector/draft与无损bridge；可信解析显式/推断/样式继承RTL，保留隐藏continue水平、nested/XML/geometry。独立review发现自闭合空段落插入错误，新增真实保存回读RED→GREEN修复；built发现RTL空align继承旧cell center，最小显示基线修复并新增5项render测试。详见 NATIVE_WORD_TABLE_CELL_ALIGNMENT_ACCEPTANCE.md。

最终 /tmp/word-cell-alignment-migrated-built-smoke.log exit0、ok=true/errors=[]，普通九组合+复杂合并三组合12次真实Python保存、HTTP下载/ZIP/新修订重开、UndoRedo/draft及真实top<center<bottom通过；mask仅jc/vAlign后整documentXML与其他parts身份保持。产物 /tmp/docx-cell-alignment-built-rHNpVF/，root目视修订33。授权/修订路由为夹具，非生产HTTP/桌面Word/PDF等价。

按用户要求新增reporting/doc_engine，同级归属packages/docx-engine、17个DOCX bridge、7个tests及probe；共享PPTX/agent/zip保sibling file依赖，PPTX公式和transition引用更新。Python doc运行目录/env、前端alias/chunk、Docker独立安装/打包/许可与剪裁已更新。doc及slides npm ci、独立bundle、目录/Docker6项、无源码node_modules的DOCX真实patch2项、PPTX/XLSX隔离桥接1项通过；跨目录依赖许可补收3项及实际裁剪包inspect通过。最终前端统一budget/分页预览built仍单独验收，不因此关闭全量目标。

迁移后最终统一frontend /tmp/office-doc-engine-page-break-build.log exit0（41.52s），budget及contract exit0；分页预览独立chunk后XLSXmain236.8KiB、Wordmain160.3KiB，未提高cap。DOC engine目录迁移与本轮Word九宫格专项已核验；XLSX分页预览真实浏览器和可编辑结构保存专项继续推进，尚不宣告全量完成。

### 2026-11-10 XLSX 分页预览专项浏览器闭环

预览与FilePrint共用实际保存操作重放后的页面设置和live geometry；共享结构引擎补手动break坐标，journal按字段capture支持跨epoch。主入口/Ribbon/controller/overlay及清理接线完成。最终统一build41.52s、budget/contract exit0，XLSXmain236.8KiB未抬cap。详见 NATIVE_XLSX_PAGE_BREAK_PREVIEW_ACCEPTANCE.md。

只读 /tmp/page-break-built-readonly3.log exit0：四真实保护表普通/冻结/150%/RTL，实际水印几何及normal清理/身份切换、draft/history/save/source/downloadSHA保持，save0。可编辑 /tmp/page-break-built-editable-final.log exit0：7阶段预览与实际printHTML页数4/4/9/9/9/9/6一致，跨epoch设置/插删/UndoRedo/尺寸/新隐藏轴/真实Python保存下载ZIP断言通过。各118资源HTTP200/SHA、pageErrors0；root目视 /tmp/page-break-editable-built-pox3x9/editable-final-preview.png。

原隐藏列随结构移动后在geometry宽度保存补丁丢hidden是真实独立缺口，已交子agent修复，未被本专项掩盖。顶层功能关闭门禁、生产HTTP/桌面Excel/打印机等价不在本证据范围，全量目标继续开放。

### 2026-11-10 Word 整表默认单元格边距闭环

Ribbon整表默认边距已接入来源绑定的严格setTableCellMargins、可信默认/覆盖/raw快照、collector/draft与无损直属tblCellMar补丁。UI以精确pt显示，单位输入复用来源长度解析，未改字段保持整数twip，无操作确认不派发事务；所有物理单格tcMar、样式/行例外及合并续格隐藏内容保留。详见 NATIVE_WORD_TABLE_CELL_MARGINS_ACCEPTANCE.md；Cell页单格覆盖/恢复继承仍为独立缺口，不计作本项交付。

core/project5、bridge6、UI5、Python6及限定types通过，未重复完整测试。最终bridge /tmp/word-cell-margins-final-bridge-build.log exit0；统一frontend /tmp/office-margins-hidden-final-build.log exit0（40.01s），budget/contract exit0。长度解析独立chunk后render709.9KiB、Wordmain160.5KiB，未提高cap。

最终 /tmp/word-cell-margins-built-smoke.log 首轮exit0、ok=true/errors=[]：普通/横纵合并/bidiVisual/竖排四来源保存为修订2/11/21/31，四次setTableCellMargins均为top0/right176/bottom96/left130。无操作确认、UndoRedo/draft、真实Python保存、HTTP下载SHA、ZIP及新修订重开通过；所有physical cell XML全文、仅mask直属tblCellMar后的documentXML与其他parts身份保持，121JS200/SHA。普通默认格padding L7.2→8.667px、R7.267→11.733px，显式owner left33保持2.2px；四来源重开geometry与修改后精确一致。

产物 /tmp/docx-cell-margins-built-jQTQuL/，UI agent已目视修订11/31截图。授权/修订路由为夹具，不代表生产HTTP、桌面Word/PDF等价；完整Word/XLSX对齐目标继续开放。

### 2026-11-10 XLSX 源隐藏列结构移动与列宽保存闭环

分页预览旧实测发现的源隐藏列丢失已独立修复：完整列操作迁移 col 定义范围，列宽 writer 保留 hidden/style/outline 等非尺寸属性；支持单双引号与等号空白，拒绝无效重叠范围。固定来源37向量、真实 ZIP/Univer9项、geometry7项、结构25项与属性引用专项4+7项已通过，来源清单同步。详见 NATIVE_XLSX_HIDDEN_COLUMN_PERSISTENCE_ACCEPTANCE.md，历史失败保留。

最终 workbook bridge /tmp/xlsx-hidden-quotes-bridge-build.log exit0；统一frontend /tmp/office-margins-hidden-final-build.log exit0，budget/contract通过未升cap。最新 /tmp/page-break-hidden-final-built.log exit0、ok=true：插列后的原隐藏D保存后仍隐藏，hiddenCols为D/F/G且请求没有index3伪列宽；7阶段预览/打印页数4/4/9/9/9/9/6一致，真实Python保存一次及HTTP下载SHA f31488ec18509726e18a48ac970f65ceee0fbe4cb8c01ab1ef77c1ec350a2c8f一致，ZIP area/titles/breaks/height42/width20/hiddenRows6,7通过。118资源HTTP200/SHA，pageErrors=[]；产物 /tmp/page-break-editable-built-YUH8oD。授权/修订路由为夹具，不代表生产HTTP或桌面Excel/打印机等价。

root另已目视 /tmp/docx-cell-margins-built-jQTQuL/revision-11-margins-reopened.png，补充前条Word默认边距视觉核对。下一Word单格边距覆盖/恢复继承和XLSX公式追踪尚在实施，全量目标继续开放。

### 2026-11-10 Word 单格边距覆盖／恢复继承闭环

独立 setTableCellMarginOverrides 严格矩形有序steps、来源hash、collector／草稿与Cell属性UI接通；服务端复用真实parser一次批量产生reset继承基线（按原包WeakMap缓存），只补全部目标physical tcMar，保留隐藏续格和其他内容。区分owner rawPresent、所有physical的hasPhysicalOverrides、raw/effective/resetEffective；review发现owner无覆盖但continue有覆盖会抑制reset，新增真实RED后修复。详见 NATIVE_WORD_CELL_MARGIN_OVERRIDES_ACCEPTANCE.md。

core/project4、bridge7、Python10、UI与旧投影互斥定向通过；限定和完整前端types通过。final doc bridge build exit0，统一frontend /tmp/office-overrides-trace-build.log exit0（Vite39.79s），budget/contract exit0未升cap。独立review真实“两表逆序修改＋其他段落插删”探针passed=true，证据 /tmp/cell-margin-overrides-integration-review/。

真实Chromium普通来源在 /tmp/docx-cell-margin-overrides-built-us3sxn 完成修订2保存/下载/ZIP/重开；其后样式夹具预检失败保留（非产品失败），按真实firstRow条件样式修正后仅续跑剩余三源。最终 /tmp/word-cell-margin-overrides-built-smoke.log exit0、ok=true/errors=[]：style/row继承、merged hidden-only、bidi/vertical分别4/5/4步保存修订11/21/31，mixed/no-op/UndoRedo/draft/实际Python/HTTP下载SHA/ZIP与重开通过，121JS200/SHA。reset继承padding左41/右151twip真实呈现，所有隐藏正文/非tcMar及其他parts保留。root目视修订11；产物 /tmp/docx-cell-margin-overrides-built-ZNUz4R。授权/修订为夹具，非生产HTTP/桌面Word/PDF等价。

XLSX公式追踪已接线并通过定向/构建，但built发现RTL浮层不可见，尚未专项闭环。Word Row允许跨页断行亦为下一独立缺口调查。全量Word/XLSX目标仍开放。

### 2026-11-10 Word 允许行内跨页闭环

新增严格setTableRowBreaks有序行带、属性独立入口、mixed/no-op、collector/draft和局部trPr/cantSplit补丁；复用真实selectedRect，不向其他列额外扩张。成对与自闭合目标均正确处理，保留height/header/全部physical正文与隐藏续格。固定source paired清除失败未复制为本地契约。详见 NATIVE_WORD_TABLE_ROW_BREAKS_ACCEPTANCE.md。

core/project4、bridge6、Python7、UI5与旧边距4定向通过，完整types和独立两表索引/整批原子probe通过；未重复完整测试。统一frontend /tmp/office-row-breaks-trace-pane-build.log exit0（40.55s），budget/contract exit0未升cap。四来源实际分页、UndoRedo/draft、Python保存/HTTP下载SHA/ZIP保真/修订重开全部通过；最终paired /tmp/word-row-breaks-built-smoke.log exit0、ok=true/errors=[]，121JS200/SHA。18条目标文字从全部第二页，切换为第一页00–11/第二页12–17；再次禁止恢复，保存重开与live一致。root目视merged两态截图。

总证据 /tmp/word-row-breaks-built-evidence.json；前两source逐行数组未单独持久化，只保留当时实际断言、HTML/ZIP与恢复结果，明确不伪造。RTL class顺序与paired mask探针失败均保留并仅从失败source续跑，产品未因此改动。授权/修订为夹具，非生产HTTP/桌面Word/PDF等价。整表对齐调查已完成但未实施，XLSX公式追踪最后复合验收收尾中，完整目标继续开放。

### 2026-11-10 XLSX 引用／从属追踪与移除箭头闭环

固定source collector迁入宿主，Ribbon与实际main只读入口接通；名称/结构化/动态引用明确不完整，跨表只计数，不把空解析当无依赖。官方RTL跨列float负宽与Frozen跨pane非仿射显示两次真实built失败均保留；最终每端点用官方单格float的当前可见裁剪矩形，host SVG只连线，高亮按freeze分段，offscreen明确提示/隐藏并在滚回后恢复。ref重绑与生命周期释放专项RED→GREEN，零面积/合并边界明确拒绘。详见 NATIVE_XLSX_FORMULA_TRACE_ACCEPTANCE.md。

源18向量、helper/controller/main/Ribbon定向及types通过；最终pane10项后新增ref1项窄回归通过。统一frontend /tmp/office-row-breaks-trace-pane-build.log exit0（Vite40.55s），budget/contract exit0，main248.9KiB未升cap。最终同dist分段七真实保护表Plain/Frozen/Zoom150/RTL/RTL150Frozen/RTLHiddenEnd/Hidden均通过前置2/从属1、清除及真实canvas选择像素对齐；Frozen/RTL150Frozen另验证实际滚动跟随。全部具体日志与截图在验收文档，不将tail cases=[]冒称单次跑过七表。

最终 /tmp/formula-trace-built-pane-tail.log exit0、ok=true：merge拒绘、跨表计数、复杂不画伪箭头、切表释放、可编辑真实插行后释放与Undo，118JS HTTP200/SHA、pageErrors=[]、save0。source和只读前后下载SHA均10cee14b9c17885fd18624f770a7893376d1018805a058ac9cb853894b48f08f。root目视 /tmp/formula-trace-built-D3X05o/RTL150Frozen-precedents.png，箭头对齐D6。七表旧DOM几何数值未单独持久化，仅保留截图与运行时断言，明确不补造；授权/修订为夹具，非生产HTTP/桌面Excel/完整计算依赖图等价。

整表对齐与左缩进调查已完成；固定source左缩进没有控件且generic PM修改不能保存，应独立列gap，不捆绑宣称支持。全量Word/XLSX对齐目标保持开放。

### 2026-11-10 整表对齐／监视窗口中间验收问题

本轮实际进展，不作专项完成声明。Word built 已通过4次保存；legacy14 的 left 从 live -7.296875 到明确重开 -9.5 暴露显示缩进投影遗漏。原始 tblInd 应保持，修复由真实导入器计算各对齐下显示 indentTwips；错误日志 `/tmp/word-table-alignment-built-legacy14-indent-failure.log` 保留，剩20次通过 resume 继续，已过保存不重复。详情见 NATIVE_WORD_TABLE_ALIGNMENT_ACCEPTANCE.md。

XLSX watch 独立 review 发现非 native 保存后 shell.editor.inert 锁住其监视窗口；已新增真实 main 保存路径定向回归，RED 在祖先 inert 断言失败，最小改为 editor 同级宿主后 GREEN，日志 `/tmp/watch-saved-host-red.log`、`/tmp/watch-saved-host-green.log`。验证增删关闭监视、保存内容与状态不变且仅一次保存请求；jsdom 不模拟 inert 真实点击屏蔽，故还需新 dist 的 Chromium 补验。此前 built 已过7个检查点；菜单探针失败不计产品通过，完整目标保持开放。

后续核对发现非native Ribbon同样被祖先inert锁住，关掉watch后真实UI无法重开。新增保存态导航契约RED→GREEN（`/tmp/watch-saved-grid-lock-red.log`、`/tmp/watch-saved-grid-lock-green.log`）：保存结束解除editor整体锁，锁网格与AI form，既有saved写命令门禁保留；最终新dist必须验证真实Ribbon重开。Word legacy修复6环境24回读已GREEN，完整types/构建首次成功后因上述新增生产变化重新统一构建，未重复完整测试。watch删表UI仍受官方离屏菜单阻挡，另以真实main公开FWorkbook.deleteSheet和Undo验证gone恢复通过 `/tmp/watch-window-facade-delete2.log`，明确不计菜单UI通过。

最终统一构建 `/tmp/office-alignment-watch-saved-navigation-build.log` exit0（完整tsc，Vite40.23s），同前缀budget和contract均exit0。新dist冻结后Word从既有4次通过结果续跑20次，XLSX仅补saved-host/真实Ribbon重开和reload/revision隔离；浏览器结果仍待验收。下个真实XLSX缺口Error Checking已有固定源可执行探针exit0与 NATIVE_XLSX_ERROR_CHECKING_INVESTIGATION.md，尚未实现，不混称本批完成。

### 2026-11-10 XLSX 监视窗口分段验收结果

固定源会话监视已接通：稳定sheetId+坐标、格式化值/公式、每次最多新增20新格、去重、关闭保留、替换清会话、仅开窗800ms刷新、按key保焦点、越界/删表gone。保护只读不改snapshot/draft/history/status；保存后网格与AI form锁定，监视及Ribbon重开可用。详见 NATIVE_XLSX_WATCH_WINDOW_ACCEPTANCE.md。

首七真实built检查点用旧冻结dist通过；本次保存态修复后新dist仅补saved及reload/revision尾项，未重复前七。saved `/tmp/watch-window-built-saved.log` exit0，114实际JS200/SHA、pageErrors=[]、一次save，真实面板增删关闭及Ribbon再开通过，root目视saved截图。tail `/tmp/watch-window-built-tail-final.log` exit0，357实际JS200/SHA、save0、pageErrors=[]，刷新/新修订监视清空通过。总manifest `/tmp/watch-window-acceptance-manifest.json`。删表浏览器菜单UI受官方离屏popup阻挡仍未通过，仅公开facade删表+Undo的main回归证明gone恢复；未将该限制省略或冒充UI通过。HTTP授权/修订为夹具，不等价于生产鉴权或桌面Excel。完整Word/XLSX目标仍开放。

### 2026-11-10 Word 整表对齐浏览器最终回读

从22次已过记录仅续最后2次，最终 `/tmp/word-table-alignment-built-smoke.log` ok=true、errors=[]，目录 `/tmp/docx-table-alignment-built-rdefw0` 的8份独立result.json各3保存，root实际解析核对累计24次。legacy14 left live/明确重开保持-9.5px，RTL legacy、pct、隐藏continuation、真实浮动和suppressed浮动均完成；原tblInd/布局/非目标XML与ZIP保真由每case严格断言覆盖。高表handle失败仅因hover表中心滚走首部，probe改滚动首段后正常公开handle点击，无force/PM注入/产品改动。root目视suppressed revision72与legacy revision12截图。旧4次/新18次/末2次分批复用，未称同一dist全24重跑；首旧dist与新版显示缩进修复边界在专项验收文档保留。

下一批仍未完成：Word noWrap独立core/bridge开发中；XLSX Error Checking独立controller6项RED→GREEN及含测试窄types已过（`/tmp/workbook-error-checking-final-green.log`、`/tmp/workbook-error-checking-types.log`），尚未接main/Ribbon/真实built，不能计UI交付。全量对齐目标保持开放。

### 2026-11-10 自动换行／错误检查集成冻结

Word setTableCellWrap已接严格collector/replay、cap/hash/保护/同表批次互斥、局部XML save/最终索引回读和core metadata保留。core3/bridge5、Python7+索引布局1、ops2、UI5及受影响旧投影14定向GREEN；独立真实review两merged逆序+段落插删保hidden/tcFitText/非目标ZIP，迟到无效step无输出。详情 NATIVE_WORD_CELL_WRAP_ACCEPTANCE.md。来源直属noWrap语义和固定/超宽仍可换行的限制明确，不扩tcFitText。

XLSX错误检查main/Ribbon已接：当前表稀疏已有结果精确分类、next/wrap、官方activate/reveal，readonly/protected/saved导航零草稿历史/保存；loading/saving/calculationBusy/disposed禁用。controller7、真实main2、保护1/Ribbon1与窄types分段通过；同表改选竞争先RED后GREEN，旧异步reveal不再抢滚动/反馈。详情 NATIVE_XLSX_ERROR_CHECKING_ACCEPTANCE.md。统一build首次仅新测试resetNoWrap字面量类型错误，补夹具类型后重新构建；浏览器尚未放行，不能计专项最终通过。全量目标开放。

最终统一 `/tmp/office-wrap-error-navigation-build.log` exit0（完整types/Vite40.28s）、同前缀budget/contract exit0：XLSXmain249.2KiB、error1.6、Wordmain161.3。两次预算失败251.6/250.2均保留，通过独立error chunk及既有navigation收goto-reveal解决，未升cap。XLSX真实built `/tmp/workbook-error-checking-built-smoke.log` exit0/ok=true，18 checkpoints、120实际JS200/SHA、save0、pageErrors=[]；保护表5错误B2→D4→F6→FIELD I9→Z220→回绕、当前表Clean无错、其它表范围、键盘修复后4错误/Undo恢复5错误均通过，检查前后snapshot/draft/history/status与源下载SHA保持。root目视Z220实际canvas蓝框/名称框/反馈一致。详情与manifest由专项文档登记，HTTP授权/修订仍为夹具，非完整Excel语义向导/生产鉴权验收。

### 2026-11-10 Word 自动换行最终浏览器结果

`/tmp/word-cell-wrap-built.log` session84144 exit0，四来源4/4、恰好四次保存且无重跑：auto-caret2、fixed-mixed-rect11、rtl-rect21、merged-lower31。每source真实noop/mixed、UndoRedo、草稿、Python patch/HTTP下载身份、ZIP只noWrap改变、live/draft/明确修订重开几何/CSS/正文一致。合并隐藏续格、tcFitText、未知节点及非目标ZIP保持；root目视auto及merged重开截图。merged下部真实caret只证明同owner，不虚称逻辑lower独立UI。121实际JS HTTP200/SHA、console/pageerror=[]；总manifest `/tmp/word-cell-wrap-built-manifest.json`，产物 `/tmp/docx-cell-wrap-built-X2U2pO`，详见 NATIVE_WORD_CELL_WRAP_ACCEPTANCE.md。HTTP授权/修订为夹具，不宣称生产鉴权或桌面Word/PDF等价。

下一实际缺口：Word表格标题/说明（Alt text）固定源24保存调查已完成，独立适配实现中；发现数值字符引用/LF解码与&amp;#10;一次语义边界，需局部parser复用raw实体解码修复，不引前端第二baseline。XLSX打印scale进入只读调查，尚未实现。全量Word/XLSX目标保持开放。

### 2026-11-10 表格标题／说明与打印比例增量

Word setTableAltText已接完整final pair、strict wire/hash/保护/同表互斥、PM专用intent/collector/replay、XML补两标签/实际输出索引回读/core metadata保留。core3/bridge+parser6、Python9、ops2、UI4及受影响旧投影13定向GREEN。局部parse.ts现成raw tblPr属性用既有decodeEntities一次语义，numeric LF/CR/TAB与literal &amp;#10;保持，engine/renderer PM/lxml真实回读一致。独立review两表逆序+missing tblPr/paired+段落插删/section通过；迟到无效超长title不产生输出。详情 NATIVE_WORD_TABLE_ALT_TEXT_ACCEPTANCE.md。textarea初始CRLF/CR未触碰也归一LF的问题新增有效RED，UI agent修复中，不预记最终完成。

打印scale源20向量与4真实XLSX writer回读调查已完成，NATIVE_XLSX_PRINT_SCALE_INVESTIGATION.md。源PrintDialog比例修改立即进入journal/保存，取消不撤销；本地已有scale读写/分页/fit，缺入口。独立打印比例子功能正在实现，复用现有pageSetupJournal并关闭fit，不另建writer；完整源PrintDialog仍为独立gap。源允许400%但print renderer最多200%的差异记录，不照抄为本地截断合法值。全量目标仍开放。

### 2026-11-10 多子 agent 分工与最终构建放行

本轮按用户授权分成三个独立任务：Word 表格标题/说明真实 built 验收、XLSX 打印比例真实 built 验收、XLSX 迷你图持久化调查及已复现 writer 缺陷。root 负责集成与预算。最终 `/tmp/office-alt-print-statistics-build.log` 完整 types/Vite40.58s exit0，配套 budget/contract 均 exit0；main249.7KiB、print-settings11.8KiB、view-controls2.6KiB，未提高250KiB上限。之前两次250.2KiB预算失败保留，仅拆分现有打印/统计模块，未改业务语义。此后冻结 dist 放行两个浏览器专项，不重复已通过全套测试。

Word首轮 `/tmp/word-table-alt-built-probe-red.log` 无保存即失败：探针点击既有禁用的table-select-all入口；改用已有真实表格手柄，保留NodeSelection及Alt禁用断言，未开放pending功能。最终专项仍在运行，不预记通过。迷你图已发现源存在真实x14写出与本地现成writer风险，专项调查/修复结果待独立证据，不能计完整迷你图UI交付。全量Word/XLSX目标保持开放。

### 2026-11-10 表格标题／说明真实浏览器收尾

最终冻结 dist 的 `/tmp/word-table-alt-built.log` exit0，4 来源4保存修订2/11/21/31，121实际JS HTTP200+SHA、errors=[]。全 final pair、特殊实体/LF/literal引用、仅标题、merged lower owner、RTL浮动CRLF noop和清空均通过UndoRedo/草稿/Python patch/真实下载SHA/ZIP只直属Alt标签改变/新修订回读及几何保持。root独立解析结果核对4保存并目视RTL浮动重开截图。manifest `/tmp/word-table-alt-built-manifest.json`，目录 `/tmp/docx-alt-text-built-VA6zov`，专项 NATIVE_WORD_TABLE_ALT_TEXT_ACCEPTANCE.md。前两轮均0保存：禁用入口改真实handle、dialog取消后键盘前真实点cell恢复焦点，仅修probe，不改产品；未重复成功保存。HTTP授权/修订仍为夹具，非桌面Word/生产鉴权/完整嵌套表属性等价。全量目标开放。

### 2026-11-10 打印比例验收及迷你图 writer 定向修复

XLSX `/tmp/workbook-print-scale-built.log` exit0：10/100/400三来源3保存、121实际JS HTTP200+SHA、errors=[]，操作只applyPageSetups的scale与fitToPage=false；真实Python patch、下载SHA、ZIP非目标保全、100默认属性省略、新修订重开及File Print HTML均通过。原30pt行3/30/120pt，页数1/1/8，未复制源renderer200%截断。root独立解析日志并目视400重开截图。目录 `/tmp/print-scale-built-5hZxNX`；专项 NATIVE_XLSX_PRINT_SCALE_ACCEPTANCE.md。首轮stale探针裸click未真正切表，改组件公开keydown Enter并等待aria-selected，保留原拒绝断言，无重复成功保存；该stale事件为DOM调度而非穿过modal真实鼠标操作。完整PrintDialog、实际打印机与生产鉴权仍未验收。

迷你图独立源writer探针确认三类真实写出；本地现成writer两处缺陷已定向修复：根extLst插入位置、同类型异色/markers/axis分组。原3+新4测试共7通过及engine tsc通过，root审diff和实际ZIP/XML回读结果，原始RED/GREEN工具输出的事后摘录有明确标识。证据 `/tmp/xlsx-sparkline-gap/fixed/`、NATIVE_XLSX_SPARKLINE_INVESTIGATION.md。此引擎修复发生在冻结dist之后，不冒称本轮浏览器覆盖，也未接迷你图新增bridge/Ribbon；下一步仍为追加协议与用户入口闭环。未重新跑完整测试。全量Word/XLSX对齐仍未完成。

### 2026-11-10 迷你图新增闭环集成与Word审阅调查

三子agent分别实做迷你图raw追加引擎、前端journal/官方UndoRedo、Word审阅源调查，root补main/Ribbon及Python双白名单并review集成。Word24实际源保存+ZIP/lxml证据见NATIVE_WORD_REVIEW_INVESTIGATION.md；新agent开始独立修订XML core，未预记UI交付。迷你图定向实现与证据见NATIVE_XLSX_SPARKLINE_ACCEPTANCE.md（仍进行中）。累计200宿主分批及特殊sheet qualifier、官方拒绝命令栈泄漏等review发现已修，跨表reader误指宿主页已补真实来源身份与绘制，统一构建和built验收尚在推进。全量目标开放。

迷你图统一 `/tmp/workbook-sparklines-data-split-build.log` exit0（完整types/Vite40.50s），budget/contract exit0，main235.3KiB/data-tools14.6KiB/sparklines5.0KiB，cap仍250KiB。完整types先发现resolver实Worksheet.getCell的void返回，main标准化后修；两次251.0预算失败保留，最终拆既有数据工具模块，未改业务或提高cap。来源结构实测canonical跨表单格/alias行列会错位，已加bridge全簿依赖检查和前端stable source身份guard，4桥新增与前端累计22项GREEN、独立真实ZIP矩阵通过。浏览器从冻结dist进入验收，尚未预记成功。Word raw修订core4项真实保存/独立lxml已通过，宿主/UI未接。

迷你图首次built `/tmp/workbook-sparklines-built.log` 虽exit0/3保存/124JS/errors=[]，smoke agent和root目视column/stacked截图发现真实柱条越宿主格，因此不计最终验收。保存产物 `/tmp/sparkline-built-AbVJe8` 三下载和raw/foreign/跨表G2绘制证据保留；renderer已修零基准/半高、零值/极小/密集边界，18新+3跨表定向通过。待新统一构建后只resume已有文件重开绘制，不重复成功保存。独立集成验证索引 NATIVE_XLSX_SPARKLINE_INTEGRATION_VERIFICATION.md 保留分层证据；实际built状态由ACCEPTANCE单独记录。Word core新增验收备忘 NATIVE_WORD_TEXT_REVISION_ACCEPTANCE.md 与4份留存DOCX/独立lxml，仍未接宿主/UI。

### 2026-11-10 迷你图绘制修复后最终分段验收

最终 `/tmp/workbook-sparklines-bars-build.log` 完整types/Vite40.21s、配套budget/contract均exit0，main235.6KiB，cap仍250KiB。`/tmp/workbook-sparklines-bars-built.log` exit0、ok=true、saveCount=0，3结果resumed=true，124实际JS200+SHA、errors=[]。仅重开首次已保存修订2/11/21，下载SHA原样，独立ZIP/lxml保全仍过；新增真实skeleton targetBounds与全部bar containment/盈亏正负半高断言通过。root独立解析最终机器结果，目视新column/stacked截图均在E4/E5格内。checkpoint `/tmp/sparkline-built-AbVJe8`，旧越格截图/结果与原3保存证据另由smoke agent留存并区分；未重做三保存，不冒称单dist执行全部。专项NATIVE_XLSX_SPARKLINE_ACCEPTANCE.md和集成验证文档登记精确范围：原生组编辑删除、跨表新增及完整结构同步仍未交付，HTTP授权/修订为夹具，非桌面Excel/生产鉴权验收。

Word下一步仍为简单修订授权宿主与UI映射：core4真实DOCX与独立lxml已完成，RevisionRange缺OOXML快照身份映射，必须处理相邻wrapper歧义、同段合批及与文字/格式操作互斥，不能直接开放按钮后套普通段落替换。完整全量目标仍开放。

证据留存更正：上一条“旧越格截图/结果另由smoke agent留存并区分”不准确。agent核实resume覆盖前未及时备份，现checkpoint内截图/result均为最终复验内容；没有旧截图另存。旧图曾由agent和root目视，当前只保留初次完整日志summary、当时工具读取的Canvas坐标及ACCEPTANCE缺陷调查记录。拷贝时已是最终内容的目录明确命名final-bars-evidence，未冒称初版。最终三份下载SHA及新实际bounds/截图证据完整，首次3保存与最终0保存的日志分别保留。


## 2026-11-10 简单正文修订宿主与界面闭环；分类汇总调查

- Word 顶层简单 ins/del 的逐目标定位、接受/拒绝已贯通原 XML 身份、宿主严格保存、前端投影、collector、草稿重放与 Undo/Redo。保留普通段落权限；同段其它写入与节操作混批拒绝，500 总数上限在所有 fallback 合并后核验。复杂/嵌套/move/属性修订、新建跟踪和接受全部未交付。
- 27 个宿主专项、9 个映射/控制器窄用例、2 个收集重放集成、4 个实际 main collector 用例与新增2项500/501边界已通过。受影响旧操作59项、恢复45项通过；未跑全测。恢复测试补过期mock后发现并修复多节初始化TDZ，ready前仅更新当前节，不访问未创建功能区。
- 真实 Chromium 140.0.7339.16 的5次保存/下载/新修订重开一次通过，四方向及同段4目标，重复w:id/相邻同mark/中文emoji，草稿刷新、真实UndoRedo和精确UTF16定位均通过。真实Python patch，独立ZIP/lxml核验只改所选wrapper，19个非目标ZIP部件字节一致；认证与revision路由由fixture提供，非生产认证/桌面Office等效验收。证据 `/tmp/docx-text-revisions-built-Hwbrm7/`，result.ok=true，errors=[]。root目视检查same-paragraph-four-draft.png及accept-insertion-reopened.png。
- 最终前端build、额外最终tsc、预算及预算契约通过，未扩大上限；bridge最终bundle通过。详见 NATIVE_WORD_TEXT_REVISION_INTEGRATION_VERIFICATION.md 与 NATIVE_WORD_TEXT_REVISION_BUILT_ACCEPTANCE.md。旧core阶段未接入记录仅代表历史。
- XLSX subtotal源真实保存与本地既有三个core组合验证完成，5份XLSX经ZIP/lxml/openpyxl回读；发现源非原子、命令拒绝忽略及15次Undo等边界。只调查，未交付subtotal UI；方案及证据见 NATIVE_XLSX_SUBTOTAL_INVESTIGATION.md。
- 无提交、推送、部署；未修改发布签发链。全量对齐仍未完成。


## 2026-11-11 分类汇总实现、真实浏览器发现与批注core

- 三子agent按独立缺口推进：XLSX分类汇总运行时、保存/浏览器验收、Word批注文字core；root完成main/Ribbon/对话框/保存预演集成。分类汇总支持相邻组sum/count/average、200组上限、原生命令一次UndoRedo、草稿与真实Python文件保存；复用既有cell edits/行插入/outline协议，不新造OOXML writer。
- 原子失败路径覆盖原生命令false/抛错、中途mutation已执行而history未登记、CF follower身份保全、metadata失败、官方history push前后抛错；保持当前unit的既有redo及元素身份。预演逐次插行计操作，与500项公开预算一致；保护、已有outline/SUBTOTAL/合并行、迷你图/透视依赖在首mutation前拒绝。runtime最终17向量分段验证，dialog4、preflight边界、main9项和持久化3项专项及6份实际XLSX独立ZIP/lxml/openpyxl证据均有记录，未重复全测。
- 首次浏览器三链虽有3保存，pageerror守卫捕获4条分类汇总期间工作簿变化，故不计通过。诊断stack指向docs-ui独立unit的history；修复为其它unit透传官方push且partial逆向捕获只针对目标unit。真实双unit先RED后GREEN，6项相关窄回归通过；旧失败日志/截图/文件保留，不静默过滤异常、不重复保存原修订1/10/20。
- foreign unit修复后完整build exit0（Vite40.89s），budget及contract exit0，main237.0KiB/subtotal11.4KiB，上限不变。日志 `/tmp/xlsx-subtotal-foreign-fix-{build,budget,budget-contract}.log`；新修订31/40/50使用独立built-final目录验收，最终结果另附。详见 NATIVE_XLSX_SUBTOTAL_INTEGRATION_VERIFICATION.md 与 NATIVE_XLSX_SUBTOTAL_ACCEPTANCE.md。
- Word批注已交付独立 `doc_engine/bridge/docx-comments.ts`：授权来源绑定、whole-part及object hash、严格整批校验、复用固定源patchParagraphTexts，仅替换安全目标文字，保留现代扩展parts。8组core专项通过，真实DOCX独立ZIP/lxml确认只改comments.xml；证据 `/tmp/word-comments-gap/`、NATIVE_WORD_COMMENT_TEXT_ACCEPTANCE.md。尚未接parse/edit宿主授权、HTTP白名单、frontend/collector/recovery，不能计批注产品闭环；新建/回复/删除/解决等仍缺。
- 未提交、推送、部署，未修改发布签发链。全量Word/XLSX对齐仍未完成。


分类汇总最终补记：修复后built-final smoke exit0，summary.ok=true、errors=[]，125实际加载JS全部200+SHA匹配；3来源31/40/50各仅保存一次至32/41/51，计算100/4/25，UndoRedo/草稿刷新/真实Python保存/HTTP下载/独立ZIP-lxml-openpyxl/新修订重开均通过。root独立解析summary、逐下载及全部加载资源SHA核对，并目视新sum重开截图。该明确范围闭环完成，完整数据功能族仍未完成。首次失败及旧保存保留；公式缓存null、fixture鉴权和非桌面Office边界见专项文档。

## 2026-11-11 XLSX Agno 公式依赖追踪增量

固定源 `apps/sheets/src/renderer/ai/tools.ts` 的 `tracePrecedents` / `traceDependents` 已在 `WorkbookAIToolkit` 注册为只读工具。实现绑定冻结工作簿与现有范围授权，支持有界本地/跨表 A1 单元格及矩形引用，返回公式、当前值、错误标志和 `truncated`；命名范围、结构化引用、外部链接、未知工作表、过大范围和无法确认的语法明确返回 unsupported，不猜测依赖链。候选写入与真实引擎预览/显式采纳流程未改变。

定向验证 `test_workbook_ai_tools.py` 5 项通过，其中新增普通公式、跨表公式、依赖反查及不支持语法用例；`ruff` 和 `git diff --check` 通过。尚未做浏览器或真实 provider 验收，完整 XLSX AI 工具面仍未完成。

### 公式追踪解析与覆盖修正

后续复核确认上述正则扫描版本不能证明一般公式正确：字符串地址可能误认引用，函数名含数字、绝对引用、转义表名处理不足；反向依赖遇不支持公式曾静默省略。现改用既有 openpyxl Tokenizer，只从 RANGE token 提取完整 A1 引用，支持 `$`、小写地址、转义引号表名，字符串内容不作为引用；范围总预算 200。命名范围、结构化/外部/三维引用、INDIRECT/OFFSET 及未闭合括号拒绝。它仍是直接静态引用分析，不是公式求值器或完整动态依赖图。

反向追踪新增 `scope`、`complete`、`unsupportedFormulaCount`，有不支持公式、结果截断或仅授权选区时不得声称全簿完整。范围模式沿用逐单元格读取授权，不泄露未授权单元格值。

定向证据：原工具回归与两项新复现共 7 项通过；后续 8 项边界与 1 项真实 Agno 工具循环分批通过（该循环使用 ScriptedModel、预览用 AsyncMock，不冒称真实 provider 或引擎验收）。生产/测试 ruff、git diff --check 通过。未重复全项目测试，无发布链变更；UI 与部署验收仍开放。

## 2026-11-11 四格式 AI 共性优先增量

原生 PPTX 已接入 Agno 的上下文读取、分页读页、候选提交工具循环，复用真实引擎预览和显式采纳；实际工具事件接入共享 SSE。四格式共用进度新增 23 个已注册工具的中文展示名。PPTX 定向后端分批共 37 项通过，共用进度及候选前端分批 44 项通过。31 页整稿预算不足经回归复现并修复，坏预览回执不得登记候选。完整固定源工具、复杂对象操作、纯阅读入口和真实 provider/浏览器验收继续开放。详见 `NATIVE_PPTX_AI_TEXT_STYLE_ACCEPTANCE.md`；不将本增量标为四格式完整对齐。

## 2026-11-11 Word 独立阅读与四格式 AI 剩余范围

Word 新增独立问答、正文/选区摘要与要点入口，使用真实 Agno 上下文/分页读取/搜索工具，SSE 中文进度、取消、来源/草稿身份和服务端覆盖/引用核验。读取真实 DOCX 或经引擎生成的未保存草稿，限定正文及表格文字；不生成编辑候选。独立阅读选区避免编辑回调整表回退；同步待完成编辑后再次核验，结构不明则拒绝选区，不回退全文。工具10、任务7、HTTP15及受影响PDF HTTP2分批通过；选区/面板/接线16、阅读API1和原main/API10分批通过。旧Word编辑工具另修尾页绕过完整阅读，4项定向通过。详见 NATIVE_WORD_AI_READ_ACCEPTANCE.md。

最终前端types/Vite43.87秒、budget及contract通过。首次built浏览器发现编辑关闭时画布初始化调用写预览门禁，使阅读入口也消失，故该轮不计通过，正在补独立只读模型接口。真实deepseek-v4.1-flash探针单格问答通过、未泄露相邻格；全文3/3已读及金额正确，但无效引用被丢弃并软告警，模型另有不准确范围表述，严格结果false，未记完整provider通过。

当前源码核对确认四格式均已有任务/SSE/取消；XLSX已注册11工具，PPTX已注册3工具，不再沿用“没有工具循环”的旧结论。下一优先缺口仍是：XLSX/PPTX独立纯阅读回答合同与入口；Word批注/修订/脚注AI工具；PPTX复杂原生操作候选；PDF页操作及表单AI工具；各新工具循环的真实模型与浏览器验证。人工编辑功能存在不代表AI工具已注册，ScriptedModel或旧构建证据不替代当前真实验证。全量四格式对齐保持开放。

Word阅读收尾：独立GET read-model已补，关闭编辑的只读画布不再依赖写预览；新增后端2/前端API2通过，原preview门禁仍拒绝。最终Vite44.98秒/budget通过；Chromium140真实built浏览器2链通过（整篇3/3、实际选区1/1），122实际JS HTTP200+SHA、manifest稳定、errors=[]，源与草稿不变、无preview/save/export POST。证据 /tmp/word-ai-read-20261111-final/summary.json，root独立解析并目视截图。模型为ScriptedModel经真实Agno，不能代替前述真实provider严格false结果。

构建期间共享工作区新增的放映mock及独立交叉引用类型问题以最小类型声明修复，对应5/4项窄测试通过；最终tsc仍遇workbook-ribbon的superscript/subscript与RibbonCommand不一致，未改该独立工作簿功能，不声称当前全前端类型检查通过。最终类型日志 /tmp/word-ai-read-model-final-types.log。未提交/推送/部署，完整四格式AI工具与复杂操作仍开放。

## 2026-11-11 XLSX/PPTX 独立 Agno 阅读

已新增两格式独立问答/总结/要点、中文SVG入口和SSE/取消，阅读不再强制产生非空编辑候选。NativeOfficeReadService复用既有任务生命周期，原件或真实patch/inspect草稿，选区冻结、分页覆盖、服务端引用重建及软告警。关闭编辑时独立原件阅读与下载，不伪造编辑画布；有草稿仍需编辑权限。XLSX7只读工具、PPTX上下文/读页工具均用当前reporting模型的原生Agno循环。PPTX仅实际text，备注/图片/无text对象不计已读，UI展示limitations。详见 NATIVE_OFFICE_AI_READ_ACCEPTANCE.md。

审查复现PPTX parse-time sp_* ID在重排后碰撞会读取邻对象，真实15文本框红绿回归后已改原文件与真实草稿拓扑核验、按页及对象序重绑；结构不明选区拒绝但整稿仍读取实际草稿。页脚删除再追加另有同名对象窄回归，已从保持拓扑白名单移除。

PPTX工具12、XLSX工具9+追加2、任务原8分批+重排1+页脚1+只读/来源变化2、HTTP6、旧WordHTTP1、前端18+边界1+动态采集6均为定向通过，未重复全测。真实deepseek-v4.1-flash两格式各选区问答/整篇摘要4链通过、issues=[]，收入42/成本17正确、秘密格/对象不在选区快照与引用、原件SHA不变，无写提案，证据 /tmp/office-ai-read-real-provider-20261111.json。

首次实际built浏览器2链通过，9实际JS SHA、中文工具进度、覆盖与边界、原件/草稿不变、无写POST，errors=[]，root独立解析并目视PPTX截图。首次budget253.0KiB略超253cap，拆出本轮采集模块后最终主包252.5KiB/新模块0.9KiB；Vite43.61秒与budget通过，未提高上限。最终入口chunk哈希变化，浏览器最终复验另记。完整types被共享工作区新交叉引用测试导入doc_engine bridge后的TS扩展/严格类型错误阻挡，不声明全前端types通过。无发布链变更/提交/推送/部署，完整四格式AI复杂工具与原功能区目标仍开放。

最终复验补记：/tmp/office-ai-read-20261111-final/summary.json ok=true，两格式原件阅读2链/9实际JS HTTP200+SHA全部通过，manifest d12da77b2e20337ba1a6a38da53ddf2e811f950b1d1fe61d1b63830353af188b与最终磁盘一致。root重新核验全部资产及manifest并目视最终XLSX截图；errors=[]、源/草稿不变、无preview/save/export POST。仅因拆包改变实际加载入口hash才复验这两窄链，未重复完整测试。编辑开启选区/未保存草稿的完整浏览器验收仍开放，不用后端真实文件及前端mock证据替代。

## 2026-11-11 PPTX AI 已有表格与安全图表增量

原生任务新增 `tableCells` 与 `chartEdits`，复用现有 Agno 上下文/读页/提案工具、真实引擎预览和显式采纳。模型读取实际授权表体与安全图表数据，中文候选展示格位及数据前后差异，工具事件走已有 SSE。严格核验真实对象、非空合并格、数字与维度，拒绝未授权或引擎标为不安全的图表。结构变更草稿须先保存；页面尺寸草稿另有防止二次缩放的定向回归。未扩张旧报告 SlidesAIProposal 合同。

真实 deepseek-v4.1-flash 两链首轮通过（17.08 秒），独立 PPTX 回读表格42→84、图表42→84且费用17与未选对象保留；原件SHA不变。最终冻结构建浏览器两链通过，采纳前草稿不变、采纳后真实PPTX正确，中文差异/进度可见，无保存或导出POST，JS/console/HTTP错误均为空。root独立复核113资源、来源和候选SHA；manifest为906221925dfc66230da119e975cf4b58d2f99c3d7ee4c4c32ed617b6709bcc90。证据 `/tmp/pptx-ai-objects-20261111-verified/summary.json`、`/tmp/pptx-ai-objects-real-provider-20261111.json`。首次浏览器因测试正则假定中文空格失败，修正测试匹配后复验，保留失败记录。

Vite构建成功；完整tsc仍在共享工作区的slides-clipboard-link-main测试及workbook-main报错。冻结构建budget未通过：docx-render764.8>710KiB、workbook-engine443.1>428KiB、workbook-main266.1>253KiB，未提高阈值。生产/新增测试/探针定向ruff、JS语法与相关已跟踪diff检查通过。详见 `NATIVE_PPTX_AI_TABLE_CHART_ACCEPTANCE.md`。固定源任意脚本、图片/母版/动画、表格结构、复杂组合任务与四格式全量AI工具仍开放，本增量不表示完整对齐。

## 2026-11-11 PDF 表单 Agno 与 AI 助手前端优先增量

新增可信 `list_form_fields` / `apply_ops`，明确fieldId选区的text/checkbox/radio/choice值候选，服务恢复原身份并二次校验、真实预览和显式采纳。独立于原位改字开关，保留人工草稿和未选字段。工具14+schema说明1、service/API9、前端初5+新增输入/dock4分批通过。首次真实provider参数说明不足导致两链失败，精确契约修正后两链通过13.12秒，独立文件回读和SHA验证，原件/未选秘密字段保留。

按用户最新要求把助手前端纳入对齐，PDF阅读/审阅/填表已接同一右dock、当前功能区入口和窄屏抽屉，Word/XLSX/PPTX侧栏仍开放。最终Vite44.70秒成功；built浏览器3链通过（填值/取消/侧栏切换及窄屏），33 JS SHA、manifest23832cb6163ab7d191f3b49e6126d13b5372588661dc5ce20131bd4412f40c98，实际PDF字段独立回读，错误[]。PDF main245.2KiB回到250cap内。全局types和4项其他包budget仍失败，未提高cap。详见 `NATIVE_PDF_AI_FORM_ACCEPTANCE.md`、`NATIVE_AI_ASSISTANT_FRONTEND_ALIGNMENT.md`；完整四格式目标保持开放。

## 2026-11-11 四格式侧栏、浮动与 PPTX AI 备注增量

四格式阅读/编辑助手已接右侧共用布局（PDF沿既有dock），标题/功能切换/滚动结果/底部输入区沿固定源结构，保留主题色。Word/XLSX/PPTX使用源宽度边界，功能区保持画布之外；浮动切换、标题栏拖动、键盘移动、窄屏约束不重建任务。旧“Word/XLSX/PPTX侧栏仍开放”是早期状态，不代表当前实现。共享外壳9项、types与隔离浏览器通过；实际PDF新build5场景、37JS SHA验证、真实Agno ScriptedModel填写链通过，详见NATIVE_AI_ASSISTANT_FRONTEND_ALIGNMENT.md。历史构建及类型/预算失败仍按各自快照保留。

PPTX AI 备注已追加显式页授权、读后提案、实际备注差异和采纳合并；新8项后端分批与旧工具/表图26项、API1、前端1项通过，真实PPTX引擎独立ZIP仅目标notesSlide1.xml变化，其余46部件一致。最终built浏览器及真实provider尚在验收，详见NATIVE_PPTX_AI_NOTES_ACCEPTANCE.md。不把人工备注能力当作AI闭环证据，也不将该增量视为完整四格式对齐。

备注增量最终补记：真实模型10.58秒15项检查全部通过、最终built浏览器117JS及实际PPTX回读通过；新透视分包同build143JS、实际创建/保存/下载回读通过，预算全部通过。详见NATIVE_PPTX_AI_NOTES_ACCEPTANCE.md的精确manifest与证据边界。截图发现PPTX输入框缩窄，已修共享align-items，原断言失败/当前CSS覆盖复验通过；含最后CSS的完整构建暂受另线程PDF缺失模块导入阻挡，不能声称最新工作区build/types全绿。下一明确工具缺口为Word脚注/尾注的read_notes/insert_footnote/insert_endnote/edit_note/delete_note Agno闭环，人工能力已存在但AI未接；完整全量目标继续开放。

## 2026-11-13 Word 设计 ▸ 页面边框

复用固定引擎 `applySectionSettings` 的逐节 `pgBorders`，经既有 `setSectionLayout` 写回。“方框/无”和对话框的“整篇文档”作用于全部节，也可只改本节。桥接整批先验，写后逐节回读。桥接3、Python5、前端5项通过，tsc exit0；浏览器冒烟 exit0，经保存、下载、ZIP回读、重开和LibreOffice渲染验证。Word前端6项失败与基线1e0b6e31完全相同。与分节/水印需分开保存；生产构建与Word打开未验收。详见 `NATIVE_WORD_PAGE_BORDERS_ACCEPTANCE.md`。完整全量目标继续开放。
