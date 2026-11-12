# XLSX 插入符号与上/下标验收

2026-11-11。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这两个命令的闭环，不代表 XLSX 功能区已全部对齐。

## 固定源行为

- **插入 ▸ 符号**：`apps/sheets/src/renderer/SymbolDialog.tsx` 提供五个分类的符号网格（货币/常用 20、数学 30、箭头 20、希腊字母 27、几何/其它 26）。点击一个符号即追加到活动单元格，对话框保持打开以便连续插入，“关闭”退出。
  - `data-tools-actions.ts` 的 `handleInsertSymbol` 取活动区域左上角单元格，用 `appendSymbol` 追加：空单元格直接写入符号；数字和布尔值先转成文本再追加。写入走 Univer `FRange.setValue`。
- **开始 ▸ 上标/下标**：固定源经 Univer 样式 `va`（3 = 上标，2 = 下标，1 = 基线）切换所选单元格的字体垂直对齐，保存为 OOXML `<font><vertAlign>`。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 功能区 | `workbook-ribbon.ts`：“上标”“下标”“符号”改为可执行命令。此前上标/下标处理函数已存在，只是功能区项没有绑定命令；审计文档中“引擎 schema 无字段”的原因已不成立（`edit-schemas.ts` 已有 `vertAlign`）。 |
| 符号对话框 | `workbook-symbol-dialog.ts`：符号表与 `appendSymbol` 逐项照搬固定源，分类名取固定源 `i18n/dialogs/zh.ts`。外壳使用统一的 `--office-*` token。 |
| 写入 | `workbook-main.ts`：取活动单元格，经官方 `FRange.setValue` 写入网格并标记修改。保存沿用既有网格差分 → `applyCellEdits`，没有新增写入器。 |
| 上/下标保存 | 既有 `style-map.ts` 已把 Univer `va` 与 `vertAlign` 双向映射，`styleDelta` 已包含该字段；引擎 `workbookStyleEditSchema` 接受 `baseline/subscript/superscript`，`baseline` 移除属性。 |
| 门禁 | 工作簿加载或保存中、未选单元格、工作表受保护时不打开对话框或拒绝插入，并给出原因；功能区沿用既有的可编辑与工作表保护门禁。 |

## 与固定源的差异

- **公式单元格**：固定源以计算结果覆盖公式再追加。这里拒绝并提示“活动单元格含公式”，不静默删除公式。
- **富文本单元格**：固定源以纯文本覆盖，会丢失分段格式。这里拒绝并提示。
- **长度上限**：追加后超过 Excel 单元格 32767 字符上限时拒绝。
- **其他**：与固定源相同，只作用于活动区域左上角单元格；上/下标按所选区域首个单元格的当前状态整体切换。

## 证据

- `frontend/src/workbook-symbol-dialog.test.ts`：分类与数量、`appendSymbol` 语义、公式/富文本/未知符号/超长拒绝、连续插入、出错时内联提示、切换分类、关闭与释放。
- `frontend/src/workbook-ribbon.test.ts`：上标、下标、符号不再标记为不可用，并派发各自命令；“公式”仍保留不可用原因。
- `reporting/tests/test_native_xlsx_symbol_vertalign.py`：经真实引擎写入后用 openpyxl 回读。
  - 文本与数字追加符号，数字转为文本。
  - `superscript`、`subscript` 写入 `styles.xml` 的 `<vertAlign>`，并保留粗体与字体。
  - `baseline` 清除该属性；非法值被拒绝。
- `frontend/smoke/workbook-symbol-vertalign-gui-smoke.mjs`：Chromium 开发服务器模式，真实 Python→XLSX 引擎链路，授权和修订路由用 fixture。步骤：
  1. 功能区“插入 ▸ 符号”在 A1 连续插入 € 与 →（中途切换分类），对话框保持打开。
  2. 在公式单元格 C1 插入被拒绝。
  3. B1 设为上标，A2 设为下标，撤销后重做。
  4. 刷新页面，草稿恢复后保存修订 2；下载字节与保存一致。
  5. openpyxl 回读：A1 = `价格€→`；B1 为上标，粗体与 Calibri 保留；A2 = 12.5，为下标；C1 公式不变；受保护工作表及其内容不变。只有 `xl/styles.xml` 与 `xl/worksheets/sheet1.xml` 改变。
  6. 重开修订 2 无页面错误。
- 网格截图显示 A1 文本与 B1/A2 的上/下标渲染。

生产构建、真实授权与发布链路未在此验收；未在 Excel 中人工打开核对显示效果。
