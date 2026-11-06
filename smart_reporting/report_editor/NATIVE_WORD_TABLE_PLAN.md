# Native Word Table：结构操作复用调查与实施前置条件

调查日期：2026-11-06。基线：仓库固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文保留最初源码调查与后续验收方案；后续已执行保真探针并接入受限后端增删行列，当前状态见 `NATIVE_WORD_TABLE_ACCEPTANCE.md`。前端结构命令与最终验收尚未完成。

## 结论

值得先做**受限结构操作的协议和保真探针**，已有 serializer 足以避免另造 OOXML 表格生成器；尚不能直接开放 Ribbon 增删行列。阻挡点不是“引擎没有生成表格”，而是 native 写回协议目前只有原文件坐标锚定的单元格文本，缺少结构变化后的身份映射、列宽契约和明确的可再生成子集。

首批建议：仅顶层、非合并、矩形、固定正列宽、无复杂内容的简单表格；四种操作 `insertTableRow` / `deleteTableRow` / `insertTableColumn` / `deleteTableColumn`。不包含新建/删除整表、合并拆分、表格样式或任意客户端 TableModel 提交。先证明保真与身份契约，再接 UI。已有 `replaceCellText` 是文本能力，不能计入结构能力交付。

## 原始依据与可复用路径

路径均相对于仓库根目录；行号用于定位本次源码，后续变动以函数名为准。

| 原始源码 | 实际行为与边界 |
| --- | --- |
| `smart_reporting/reporting/slides_engine/packages/docx-engine/src/parse.ts:955,1002` | `parseDocx` 的块携带 `docxIndex`、`originalXml`；顶层 `w:tbl` 经 `extractTable` 得到 TableModel。原始 OOXML 和包成员是保真证据，编辑器预览不是。 |
| 同目录 `types.ts:1464–1646` | TableCell 有 `paras` / `richParas`、`rawTcPr`；TableModel 有 rows、列宽及大量与 rows 同步的行属性数组。模型不是只有二维字符串。 |
| 同目录 `generate.ts:750` | `patchTableCellTexts` 只遍历**已有** `w:tr` / `w:tc` 并替换内容；不会增删行列，部分不支持的 cell patch 可返回 null 而被跳过。 |
| 同目录 `generate.ts:2452,2612` | `tableCellXml` 复用 rawTcPr 并更新建模属性；`generateTableModelXml(model, originalTableXml?)` 重建 grid、行与单元格，复用原 tblPr、rawTrPr、rawTblPrEx。它是结构修改的现成序列化入口，但不承诺整个表格原 XML 无损。 |
| 同目录 `generate.ts:2612–2640` | 列数取 rows span 与 `colWidthsPct.length` 的最大值。列宽数组长度不匹配会采用均分或总宽 9360 twips 的回退。删列若留下旧 pct 数组，甚至会留下旧列数。必须显式同步两种列宽数组，禁止依赖默认回退。 |
| 同目录 `patch.ts:369,746` | `SaveBlock` 支持 `{kind:'xml', xml, docxIndex}`；`saveDocx(parsed, finalBlocks, options)` 在原包上保存。未改块可用 `kind:'original'`。新路径应保留源 docxIndex，不应把整文档从编辑器 JSON 重建。 |
| 同目录 `index.ts:84,120,135` | parse/save、generateTableModelXml、patchTableCellTexts 都已有导出；无需新增 XML 生成依赖。 |
| `smart_reporting/report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions.ts:3009,3281,3340,3550` | docTable/docTableRow/docTableCell 与 NativeTableSupport 的 tableRole 已接入 ProseMirror 表格机制。Tab 到末格实际调用 `@tiptap/pm/tables` 的 addRowAfter（3569）。这证明编辑模型能产生结构事务，不证明 native API 能保存该事务。 |
| 同目录 `convert.ts:1489,1602,2589–2633` | tableStructureSignature 区分结构；pmTableToModel 从节点还原模型；结构/样式不变走文本 patch/原块，变化走 `generateTableModelXml(model, original.originalXml)`。这是可复用的上游完整编辑器路径，不应把客户端生成的 XML 直接送给 native bridge。 |
| 同目录 `convert.ts:1652–1677,1942` | 行高、header、cantSplit、rawTrPr 等从各行节点重组；前端结构事务与后端模型变换必须产生一致的行属性归属。 |

复用边界：前端复用 `@tiptap/pm/tables` 的 addRowBefore/addRowAfter/deleteRow/addColumnBefore/addColumnAfter/deleteColumn 命令及已有 tableRole，不手写节点移动算法；这些命令并非当前 native Ribbon 已接通的命令。后端重新解析可信源 DOCX，在服务端 TableModel 上做限定的数组增删，调用现成 generator/save。前端 convert 的逻辑用于对照和测一致性，不能作为信任边界外的任意 TableModel 输入。

特别核对了插行后的索引问题：generator 的 originalTableXml 参数只用于获取原 tblPr（2754），**不会**按原行号重新提取原行/格属性。格属性跟随 cell 对象；行属性取 nextModel 的并行数组。因此同步所有行数组后没有“originalXml 又把旧第 N 行属性套给新第 N 行”的二次错配；但只 splice rows 而未 splice rawTrPrs 等数组会直接错配。另一处更实质的保真边界在 `tableCellXml:2510–2527`：每个格段落都会重建 `<w:p>`，`mergePPrFormat` 从新建的 pPr 开始，TableParagraph 不携带原始 rawPPr。即使原表没有合并、richParas 保留了建模格式，原段落标签属性及未建模 pPr 也不保证保留。故“simple nonmerged”条件本身不足以直接启用单行增删。

## 当前已有 gate 不是结构 gate

- `bridge/edit-docx.ts:121–133` 的 editableTable 排除合并、修订、内容控件等；editableCell 进一步排除嵌套表、超链接、复杂段落，目的是保证文本 patch。该检查仍可容纳未建模的表格/行/段落属性，不足以证明重新生成整表安全。
- `bridge/edit-docx.ts:203–216`：blockId 与 cellId 绑定 sourceSha256、docxIndex 和原 row/column；expectedObjectSha256 分别核对原表/原单元格 XML。整个请求先基于同一源快照校验，再按请求顺序应用（231）。
- `bridge/edit-docx.ts:253–263,357–362,434`：replaceCellText 验证 cell anchor，patch 原 XML，保存后重开验证指定文本。当前没有增删行列 operation；现有回读检查也没有验证结构/宽度/行属性。
- `reporting/delivery/docx_native.py:14–16,61–66` 有 operation allowlist；任何新操作必须显式经过 Python 和 bridge 两层验证。
- `frontend/src/docx-operations.ts:166–180` 拒绝表格布局、行/格数、单元格结构或样式变化；现有 `docx-operations.test.ts:34–57` 证明的是文本白名单和结构拒绝。
- `reporting/tests/test_docx_engine_bridge.py:74,625,668` 已有文本写回保真、复杂格拒绝和内容控件拒绝回归；没有增删行列验收。

## 最小协议与身份设计（实现前先定契约）

建议请求继续携带现有 revision/source 身份，单个操作字段为：

```ts
type TableStructureOperation = {
  kind: 'insertTableRow' | 'deleteTableRow' | 'insertTableColumn' | 'deleteTableColumn'
  blockId: string
  expectedObjectSha256: string // 整个原表，不复用 cell XML hash
  index: number              // 源坐标；insert 是 [0,n] 的间隙，delete 是 [0,n)
}
```

初版每表每批只允许一个结构操作；拒绝与同表 replaceCellText 混用或第二个结构操作，避免把源 row/column 身份误读为当前坐标。不同表仍可独立编辑。成功保存并创建新 revision 后重新 inspect，重新签发所有表/格锚点；旧 cellId 不得迁移到移位后的另一格。前端连续操作须等待刷新锚点，或积累到下一阶段再设计显式源到结果映射。不能把数组下标相同视为身份相同。

inspect 应新增专用 `structureEditable` / `structureReadOnlyReason` / 行列数与明确宽度策略，不复用段落 editable 或 cell editable。拒绝条件至少包括：非顶层矩形、空行/零列、任何 span/merge/gridGap/gridBefore/gridAfter、嵌套表/图片/域/链接/书签/评论/修订/内容控件、浮动/RTL 表、无法正整数建模的列宽、未知的单元格/段落内容。首批还应对 raw 表/行/格属性使用**结构再生成专用**允许列表或经过探针证明的子集；仅复用当前负向正则会扩大保真承诺。

源模型只从 parseDocx 获得；客户端不得提交 XML、rawTcPr/rawTrPr 或完整 TableModel。index 必须是有限整数、边界检查；删除最后一行/列拒绝；设定单表尺寸/文件大小预算。失败不得写入新文件或伪报成功。

模型变换规则需要同时落地：

- 插入行：新格为空段落；明确采用相邻行的允许样式属性或固定默认值，不能不加选择复制 richParas、修订、header 标志。rawTrPrs、rawTblPrExs、rowHeightsTwips、rowHeightRules、repeatHeaderRows、rowCantSplit、rowRevisions、rowPrChanges、rowTblPrExChanges 与 rows 同步插入/删除；幸存行保留其属性。
- 插入/删除列：每一行同步变更；保留幸存格 richParas/rawTcPr，不以 paras 覆盖 richParas（richParas 是 serializer 的格式来源）。禁止直接复制新格的原正文。
- 列宽：首批只支持确定的固定列宽，约定总宽不变。可采用插列分割相邻列宽、删列把宽度归还相邻列；最小宽度不能满足则拒绝。更新 colWidthsTwips 与 colWidthsPct 并保证长度等于结果列数，测试每格 tcW、tblGrid 和 tblW 一致。策略是待实现契约，不是上游自动提供的行为。
- 保存：`generateTableModelXml(nextModel, originalXml)` → `{kind:'xml',docxIndex,xml}`；其他块 original；`saveDocx` 后 parseDocx 回读结果矩阵、宽度、属性。未证明可保持的 XML 不可用静默重建兜底。

## 可复现调查与探针

先用下面限定搜索核对现成路径；不运行全仓测试：

```sh
rg -n 'generateTableModelXml|patchTableCellTexts|export type SaveBlock' smart_reporting/reporting/slides_engine/packages/docx-engine/src/{generate,patch,index}.ts
rg -n 'tableStructureSignature|pmTableToModel|generateTableModelXml' smart_reporting/report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/convert.ts
rg -n 'NativeTableSupport|tableRole|addRowAfter' smart_reporting/report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions.ts
```

下一步创建临时 fixture/probe（本调查未执行，因此以下不是通过声明）：

1. 从测试 `test_docx_engine_bridge.py` 的 Document fixture 思路生成 3×3 唯一文本矩形；另制作带不同列宽、header/cantSplit/行高、格边框/底色/富文本的原始 DOCX。保留 ZIP 原成员哈希及完整原 XML。
2. 在 `smart_reporting/reporting/slides_engine` 目录用现有 `node_modules/.bin/tsx` 运行临时脚本：导入 `@genoffice/docx-engine`，readFile → parseDocx → 复制目标 table 模型 → 单独一次增删 → generateTableModelXml → saveDocx → writeFile；SaveBlock 按 parsed.blocks 中非 hidden 顺序生成，目标含 docxIndex，其他用 original。避免编辑源码或调用任意客户端 XML。
3. 逐个复现四类操作的首/中/末位置，重新 parse 检查预期矩阵、行属性归属与列宽；解压比较未改 body 块和 ZIP 成员（不要比较整个 ZIP 字节：保存时间/封装可能变化）。记录允许发生变化的成员及关系差异。
4. 对同一 fixture 运行 ProseMirror 命令 → pmTableToModel，比较与服务端限定模型变换的结果；关注新行 header/cantSplit 默认属性、rawTrPr 的继承和最后格 Tab 自动增行。未接通前保留 native 层结构拒绝。
5. 实现时只运行相关 bridge 测试、新增 table 结构测试、docx-operations 定向 Vitest 与构建检查；不因本调查运行全仓。当前文档只做 diff 格式检查。

## 独立正确性证据与验收矩阵

同一 engine 的 parse/save 回环只能发现内部不一致，不能独自证明 OOXML 或 Word 保真。除作者判断外，应保留可重放操作 JSON、源/产物 SHA-256、ZIP/XML 对比、独立读取器结果及桌面截图/重新保存证据。

| 场景 | 必需证据 | 通过条件 |
| --- | --- | --- |
| 4 操作 × 首中末，1/多行列边界 | engine 回读 + 独立 python-docx/lxml 检查 | 矩阵/行列数准确，保留格内容和富文本不丢；零行零列拒绝 |
| 非等宽固定表 | tblGrid/tcW/tblW 数值检查 | 宽度契约一致，无 9360/均分回退，无残留旧列 |
| header/cantSplit/行高/边框/底色 | 原始 XML 属性对照 + 重开 | 属性随原行/原格移动；新增属性符合明确策略 |
| 跨表/同表混合批次、撤销重做、末格 Tab | 前后端定向测试和请求记录 | 未支持组合明确拒绝；撤销后无需结构提交；刷新后锚点匹配 |
| 旧源/旧表 hash、越界、伪造 cellId | API 负例 | 拒绝且无新 revision；源下载字节不变 |
| 合并/嵌套/修订/域/链接/未知内容 | 原始 fixture + 负例 | 结构只读，原对象与未改 ZIP 部件保持；不能展平后宣称成功 |
| 旁邻正文、图片、页眉页脚、关系 | ZIP 成员/原块对照 | 除声明的目标表/保存元数据外，无意外内容变化 |
| Microsoft Word 桌面 | 实际应用打开、截图、另存后独立重读 | 无修复提示；行列/宽度/分页及 header 符合期望。未实测时 desktopVerified 必须保持 false |
| LibreOffice（若可用） | 打开/渲染、PDF 对照 | 作为第二消费者补充证据，不能替代 Word 桌面验收 |

调查时状态（已由后续阶段更新）：**当时仅确认源码路径、协议风险和验收方案。** 后续优先提交可重放 fixture 与限定 serializer probe；只有保真子集和锚点规则都通过，才进入四种命令的产品实现。保持已有导出 revision、Markdown 权威和下载非阻断契约，不将本阶段表格限制变为已生成文件的下载阻断条件。

## 已执行 serializer 保真探针（2026-11-06）

前述“未执行”的调查状态现由本节更新；产品结构操作仍未开放。
新增可重放入口：

```sh
.venv/bin/python scripts/probe_native_docx_tables.py /tmp/native-word-table-new-run
```

输出目录必须不存在。Python 生成真实固定非等宽 3×3 DOCX，Node/tsx
调用仓库固定 `parseDocx` / `generateTableModelXml` / `saveDocx`，再由
**python-docx 和 lxml** 独立读取每个文件，而非只相信 engine 回读。
探针 TS 位于 `reporting/slides_engine/probes/docx-table-structure.ts`。
它不是 native API，也不接受任何客户端 TableModel/XML。

实际结果：**14 个场景的已建模检查通过，13 个场景存在段落属性丢失**。
原文件 SHA-256：
`a354800f004bc8c4681baa67554e2b8a23a2a1818ff9cb4d814e5cc17e51d303`。

| 场景 | 文件数 | 独立检查 | 保真结果 |
| --- | ---: | --- | --- |
| 全部 original 块保存 | 1 | 完整文件字节、所有 ZIP 成员 | 与源文件逐字节相同 |
| 不改模型但再生成整表 | 1 | 矩阵、宽度、行/格属性、粗体/颜色、非目标部件 | 9 格的 `w:mirrorIndents` 和 `w:rsidR` 均丢失，共 18 个差异 |
| 插行/插列：首、中、末 | 6 | 3→4 行/列，新格为空，幸存内容/属性随源对象移动，列宽总和 9000 twips | 每文件 18 个相同属性差异 |
| 删行/删列：首、中、末 | 6 | 3→2 行/列，正确删除内容，余格宽度及属性准确 | 每文件 12 个相同属性差异 |

所有场景均检查 engine 与独立读取器矩阵一致、tblGrid 与每格 tcW
一致、总宽保持 9000、行高/header/cantSplit 随原行移动、幸存格底色和
粗体/颜色保留。未修改正文块完整 canonical XML 相同，页眉/页脚、关系
及其他非目标 ZIP 文件字节相同。仅整表再生成场景修改 document.xml 和
core.xml；core 仅允许 revision 1→2 与 modified 时间改变，并独立比对其余
元数据。ZIP 目录条目不作为文件内容差异。

首轮探针因未将 engine 的 revision/modified 元数据更新及 ZIP 目录条目
区分出来而失败；收紧为上述精确元数据契约后，最终探针完成。未改动产品
或 vendor serializer 来迎合验证，也未放宽任何正文/关系部件保真检查。

输出包含原 DOCX、14 个 DOCX、engine 矩阵、独立矩阵、每文件 SHA、
改变的成员及逐格丢失属性的 `evidence.json`。`structureReady:false` 和
`desktopVerified:false` 明确保留；14 个已建模检查通过不等于结构验收通过。
实际证据目录 `/tmp/pr190-word-table-probe-final`。Ruff 和 diff 检查通过。

下一步应先为幸存单元格保留原段落 XML，或实现并证明严格的结构专用
保真子集；不能仅因本矩阵内容/样式通过就开放结构命令。当前探针尚未
覆盖嵌套/合并/修订负例、旧锚点失效、前端结构事务或 Office 桌面验收。


## 当前后端保真阶段

已增加源 XML 保留适配，独立 13 场景零属性丢失；后端四种受限操作、
单表单操作批次限制、新修订锚点、固定列宽和连续表头规则已实现，44 项
新增后端检查通过，另有受影响回归、ASGI 和 Node22 断网运行包验收。
原生 UI 结构事务/草稿/Undo 和桌面验收仍未完成。准确协议、证据边界及
下一步见 `NATIVE_WORD_TABLE_ACCEPTANCE.md`，不能再把旧的 serializer
丢失风险描述为本适配仍未解决，也不能将后端可用等同于 Ribbon 已开放。
