# Word 表格设计 ▸ 表格样式与表格样式选项验收

2026-11-14。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，基线 `origin/code` `0ce3aa10`。本次只验收“表格设计”上下文的两组命令：

- 表格样式：无样式、5 个内置样式、其他表格样式（文档表格样式库）。
- 表格样式选项：首行、末行、镶边行、首列、末列、镶边列。

不代表 Word 功能区已全部对齐。

## 固定源行为

- `components/Ribbon.tsx` 表格设计选项卡：
  - “无样式”把 `tblStyleId` 置空。
  - `TABLE_PRESETS` 有 5 个预设（网格、蓝色标题、蓝色带状、灰色带状、绿色标题），经 `applyTablePreset` 写入逐格直接格式：首行 `headerFill`，其余行 `rowIndex % 2 === 0` 取 `band2Fill`，否则取 `band1Fill`；四边单线 4/8 pt，颜色取 `borderColor`；同时删除 `tblStyleId`。
  - 文档中 `type="table"` 且不是 `TableNormal` 的样式列为可选样式，选中后写入 `tblStyleId`。
  - 六个样式选项经 `setTableLookOption` 改写 `tblLook`。未写 `tblLook` 时默认：首行、首列、镶边行开，其余关。
- 引擎 `docx-engine`：
  - `generate.ts` 的 `tableLookXml` 同时写十六进制 `w:val` 和显式属性 `firstRow/lastRow/firstColumn/lastColumn/noHBand/noVBand`。
  - `parse.ts` 的 `tblLookFlags` 读取优先级：显式属性 > `w:val` 位 > 默认值。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 共享规格 | `bridge/docx-table-style-spec.ts`：<br>- 预设数值与固定源一致。<br>- 行取色规则。<br>- `look` 的 6 个布尔键。<br>- 请求校验：`styleId` 与 `preset` 互斥；`styleId` 必须是 styles.xml 中已有的表格样式。<br>桥接和前端共用，不依赖 Node 或 XML 库。 |
| 操作 | 新增整表操作 `setTableStyle {blockId, expectedObjectSha256, styleId? \| preset?, look?}`。<br>Python `docx_native._OPERATION_KINDS` 已登记。<br>inspect 返回：<br>- 顶层 `tableStyles`（表格类型样式，排除 `TableNormal`）。<br>- 各表 `tableStyleEditable / tableStyleReadOnlyReason / tableStyleState {styleId, look, presetEditable}`。 |
| 桥接 | `bridge/docx-table-style.ts`。只改直属 `w:tblPr` 的 `w:tblStyle` 和 `w:tblLook`：<br>- 子元素顺序与引擎 `TBL_PR_ORDER` 一致。<br>- `w:tblLook` 写法与 `tableLookXml` 相同。<br>其余字节保持原样。<br>预设复用既有逐格写回：`patchDocxCellShading` 和 `patchDocxTableCellBorders`（`all` 模式，单线、4/8 pt），再删除 `tblStyle`。 |
| 拒绝条件 | 以下情况整批先验，不产生输出文件：<br>- 来源身份哈希不符。<br>- 文档受保护。<br>- 含修订或属性变更（`tblPrChange` 等）。<br>- `tblStyle` / `tblLook` 含未知属性。<br>- 模型与 XML 的样式引用不一致。<br>- 超过 100 行。<br>- 同批中同表还有其他操作（`table_style_batch_conflict`）。<br>预设另需全部单元格可逐格写底纹和边框；含合并单元格等情况时 `presetEditable=false`，只禁用预设，样式和样式选项仍可用。 |
| 写后回读 | 重新解析输出：表格 XML 与写入值逐字节一致，`styleId` 和 `look` 按请求生效；否则 `table_style_write_not_applied`。<br>只保存表格样式时保留原 `docProps/core.xml`。 |
| 前端 | `frontend/src/docx-table-style.ts`：<br>- 意图记在 `docTable.nativeTableStyle`。<br>- 预览改 `tblStyleId`、`tblLook`；预设时逐格改 `fill` 与四边 `borders`，只用 `setNodeMarkup`，不替换节点，保留光标。<br>- 连续命令合并为一次整表请求；与来源相同的字段会剔除，全部相同时清空意图。<br>- 保存前，整表必须与“来源 + 意图投影”完全一致，才映射为一条 `setTableStyle`；否则提示“表格样式修改不能与同表文字、格式或其他结构修改混用，请先保存”。<br>- 草稿恢复时按来源身份重放，并拒绝与同表其他操作混合的伪造草稿。 |
| 功能区 | `docx-ribbon.ts`：表格设计的 13 个按钮由 `createDocxTableCommands` 统一给出可用性、禁用原因与 `aria-pressed` 状态；“其他表格样式”打开样式库对话框（`select[aria-label="文档表格样式"]`）。<br>同表已有表格样式意图时，同表的单元格底纹、边框、结构、属性等命令禁用并说明原因。 |
| 文档样式库来源 | `docx-main.tsx` 核对 inspect 返回的 `tableStyles` 与本地解析的 styles.xml：每个 id 必须存在且类型为 `table`，否则加载失败。核对通过后挂到各来源表格身份上。 |

## 证据

- **桥接测试** `reporting/doc_engine/bridge/tests/docx-table-style.test.ts`，经真实 CLI 走 inspect → patch → 回读，结果 `# pass 5` / `# fail 0`：
  - inspect 返回样式库与当前状态。
  - 文档样式加样式选项写入；`tblGrid` 之后的字节与来源完全一致。
  - 选“无样式”删除 `tblStyle`，`tblLook` 不动。
  - 蓝色带状：底纹为 BDD7EE / DDEBF7 / FFFFFF，24 条单线 9DC3E6 边框，删除 `tblStyle`。
  - 网格预设加样式选项。
  - 8 类非法请求，以及与 `setTableAlignment` 同批，均被拒绝且无输出。
  - 合并单元格表格：样式选项可写，预设可用性随单元格底纹能力而定。
- **Python 测试** `reporting/tests/test_docx_native_table_style.py`，结果 `9 passed`。用 python-docx 生成来源，经隔离的固定引擎写回：
  - lxml 回读 `tblStyle`、`tblLook` 六个属性；python-docx 回读 `style_id` 与单元格文字。
  - 变化部件 ⊆ {word/document.xml, docProps/core.xml}；inspect 再读状态一致；清除样式后无 `tblStyle`。
  - 预设逐格填色与四边单线 9DC3E6。
  - 7 类参数化拒绝。
- **前端测试** `frontend/src/docx-table-style.test.ts`，结果 `Tests 7 passed (7)`：
  - 样式库校验。
  - 样式选项切换、预览与保存；切回原值后意图清空。
  - 无样式与样式库合并 `look`，草稿重放结果与预览一致。
  - 预设填色与边框；草稿往返一致；先选预设再选文档样式时，预设格式整体撤回。
  - 以下情况被拒绝：同表打字混用、不支持预设、只读、4 类伪造草稿。
  - 合并规则。
  - 功能区按钮可用并呈按下状态。
- **类型检查**：`tsc --noEmit` exit 0（`NODE_OPTIONS=--max-old-space-size=8192`）。
- **浏览器冒烟** `frontend/smoke/docx-table-style-gui-smoke.mjs`，exit 0：
  - 运行环境：Chromium 153，开发服务器，`REPORT_EDITOR_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`；预览用真实 `inspect_docx`，保存用真实 `patch_docx`，授权与修订路由为 fixture。
  - 修订 1：
    1. 在单元格内定位，进入表格设计；“首行”“首列”呈按下状态。
    2. 从样式库选 `LightGrid-Accent1`，关“镶边行”、开“末行”；表格出现 `data-tbl-style="LightGrid-Accent1"` 与 `data-tbl-nohband`。
    3. 刷新后草稿恢复。
    4. 保存为修订 2，载荷只有 1 条 `setTableStyle`。
  - 独立回读修订 2：
    - 变化部件只有 `word/document.xml`。
    - `tblStyle=LightGrid-Accent1`，`tblLook` 为 `firstRow=1 lastRow=1 firstColumn=1 lastColumn=0 noHBand=1 noVBand=1`。
    - python-docx `style_id=LightGrid-Accent1`，文字不变。
  - 修订 2：
    1. 重开后应用“蓝色带状”，预览首行为 rgb(189,215,238)，第 2 行为 rgb(221,235,247)。
    2. 保存为修订 3，载荷只有 `{preset:'blueBanded'}`。
  - 独立回读修订 3：底纹逐行为 BDD7EE / DDEBF7 / FFFFFF / DDEBF7，边框色只有 9DC3E6，`tblStyle` 已删除，文字不变。
  - 重开修订 3，颜色与预览一致；页面错误 0。
- **渲染**：LibreOffice 把修订 2、修订 3 转成 PDF 后目视：
  - 修订 2：浅色网格样式，首行和末行加粗，蓝色边框，无镶边。
  - 修订 3：蓝色表头、带状行，蓝色细边框。
  - 与编辑器重开截图一致。
- **上游失败基线**（临时工作树检出 `origin/code` 0ce3aa10 后对比，未使用 stash）：`test_docx_native_page_borders.py::test_whole_document_and_section_borders_roundtrip` 在基线同样失败（`docx_section_layout_invalid`），与本次改动无关。
  - 桥接表格/单元格测试 71 项中 2 个文件失败（`docx-table-cell-alignment`、`docx-table-cell-margins`：`Cannot find package '@genoffice/docx-engine'`），基线完全相同。
  - 前端全量 `vitest run` 一次：`Test Files 80 failed | 687 passed | 1 skipped (768)`，`Tests 554 failed | 6281 passed | 46 skipped (6881)`。
    - Word 相关失败 7 个文件、13 项：`docx-body-decorations` 1、`docx-operations` 1、`docx-table-alignment-ui` 1、`docx-table-alt-text-ui` 1、`docx-table-cell-margin-overrides-ui` 7、`docx-table-cell-wrap-ui` 1、`docx-table-row-breaks-ui` 1。在基线工作树中逐文件复跑，结果相同（同为 13 项失败，失败位置一致）。
    - `design-integration`、`native-office-assistant-entry`、`office-ui-inventory` 在基线中同样失败。
    - 其余失败位于 PDF、Slides、Workbook、Management，均不引用本次改动的模块。

## 差异与限制

- 在编辑器中切换为另一个**文档**样式时：
  - 新样式的填色、首行字形会立即预览（来自固定源 `doc-style-css` 的 `data-tbl-style` 规则）。
  - 打开文档时已解析进单元格显示的旧样式边框，要保存并重开后才按新样式重新解析。
  - 保存后的文件与 LibreOffice 渲染不受影响。
- 预设与固定源相同，写的是逐格直接格式，不是 styles.xml 样式。含合并单元格的表格暂不支持预设，按钮会禁用并给出原因。
- 未实现：新建或修改表格样式定义（固定源也没有），以及样式库缩略图预览。样式库以名称列表呈现。
