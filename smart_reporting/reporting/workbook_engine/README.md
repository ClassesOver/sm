# 工作簿引擎

这里保存 `sheets-web` 的固定源码快照及薄桥接。`SOURCE.md`、`SOURCE-SHA256.json` 与 `UPSTREAM.md` 记录版本和来源；运行不依赖相邻源码目录。

安装：`npm ci --ignore-scripts`。保留运行时需要的 `tsx` 依赖。

更新锁文件时使用与 Dockerfile 一致的 Node 22/npm 工具链，并在无 `node_modules` 的目录验证 `npm ci`，避免本机安装残留污染平台可选依赖。

Python 使用 `smart_reporting.reporting.delivery.xlsx`：

- `build_workbook(output_path, title, period, sheets, source_mapping)`：按结构化冻结输入创建 XLSX。每个工作表提供 `name` 和 `rows`；单元格是 JSON 标量，或 `{value, formula?, style?}`。`headerRow` 是从零开始的表头行。公式缓存只写入调用方明确提供的冻结结果，不从展示文本推导。
- `inspect_workbook(content)`：返回原引擎的 `WorkbookModel`。
- `patch_workbook(content, operations)`：顺序应用操作并返回新文件，原文件字节不变。操作失败时不写出部分完成的文件。

成稿默认冻结表头，并采用横向 A4、按一页宽度打印、纵向自然分页及重复表头，避免将同表的列拆到不同打印页。

Node 使用 `npm run --silent workbook -- request.json`。请求类型为 `create`（`output` 与上述创建数据）、`inspect`（`input`），或 `patch`（`input`、`output`、`operations`）。路径来自当前报告服务授权的本地临时文件。

浏览器直接导入 `@sheets-web/xlsx-engine`，以及 `bridge/operations.ts` 的 `applyWorkbookOperations`。原有引擎导出保留不变。桥接操作使用原生结构：

| kind | 参数 |
|---|---|
| `applyCellEdits` | `edits`（原生 CellEdit，行列从零开始） |
| `applySheetEdits` | `plan` |
| `applyRowColumnOps` | `sheetName`, `ops` |
| `applySheetMerges` | `sheetName`, `ranges`（完整 A1 合并区域列表；空列表取消全部合并；拒绝重叠区域及与表格、透视表输出冲突的区域） |
| `sortRange` | `sheetName`, `spec`（原生 SortSpec；含公式的排序区域会被拒绝） |
| `applyDvRules` / `applyCfRules` | `rules` |
| `applySheetNotes` | `sheetName`, `notes` |
| `applyColumnWidths` / `applyRowHeights` | `sheetName`, `entries` |
| `applyTableAdditions` | `additions`（包括原生自动筛选） |
| `applyPageSetups` | `setups` |
| `addPivot` | `addition`（包含维度、分组、筛选和聚合定义） |
| `refreshPivotCaches` | 无 |
| `applyPivotLayoutExpansions` / `expandPivotOutputs` | `updates` / `expansions` |
| `applyDefinedNames` | `plan` |
| `protectSheet` / `protectWorkbookStructure` | `sheetName`, `protect` / `lockStructure` |
| `setThemePart` | `themePath`, `state` |

公式编辑复用原引擎的 `fullCalcOnLoad` 机制。该引擎不提供通用公式求值器；写入公式不代表已验证 Excel 的重算结果。创建时可提供确定性冻结结果缓存；编辑后由原生 Excel 或浏览器公式引擎重新计算。
