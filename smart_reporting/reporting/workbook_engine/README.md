# 工作簿引擎

这里保存 `sheets-web` 的固定源码快照及薄桥接。`SOURCE.md`、`SOURCE-SHA256.json` 与 `UPSTREAM.md` 记录版本和来源；运行不依赖相邻源码目录。

安装：`npm ci --ignore-scripts`。保留运行时需要的 `tsx` 依赖。

更新锁文件时使用与 Dockerfile 一致的 Node 22/npm 工具链，并在无 `node_modules` 的目录验证 `npm ci`，避免本机安装残留污染平台可选依赖。

Python 使用 `smart_reporting.reporting.delivery.xlsx`：

- `build_workbook(output_path, title, period, sheets, source_mapping, images=())`：按结构化冻结输入创建 XLSX。每个工作表提供 `name` 和 `rows`；单元格是 JSON 标量，或 `{value, formula?, style?}`。`headerRow` 是从零开始的表头行。公式缓存只写入调用方明确提供的冻结结果，不从展示文本推导。
- `inspect_workbook(content)`：返回原引擎的 `WorkbookModel`，并附加 `sourceMapping` 与 `images`。
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


静态图片仅在服务端桥接中读取本地文件：`build_workbook(..., images=(image, ...))` 或 `patch_workbook(content, [{"kind": "applyStaticImages", "images": [image]}])`。每项要求 `imageId/path/size/sha256/sheetName/range/chartId/snapshotId/chartRevision/sourceRanges`；`snapshotId/chartRevision` 为非空字符串，`range` 为包含末端单元格的 A1 范围，`sourceRanges` 为 `{sheetName, range}` 列表。可选 `sourceFiles` 用 `{path,size,sha256}` 复核来源。Python 解码 PNG/JPEG，Node 紧邻嵌入再次读取并核对实际字节身份。

同 `imageId` 的补丁更新原位置图片；改变位置会拒用并记录告警。可传 `sourceMapping` 更新共同快照信息；它与已有来源字段及 `chartRevisions` 合并，未提供的单元格来源保持不变。图片与来源中的 `snapshotId/chartRevisions` 不符时拒用该图片。坏图保留既有图片和值/公式；创建结果通过 `issues` 返回原因，图片补丁通过 `inspect_workbook(...)["sourceMapping"]["imageIssues"]` 读取原因。图片映射位于包内 `smart-reporting/source-mapping.json` 的 `images`，包含原始身份、范围、快照、图修订及 `mediaPart`。`applyStaticImages` 是服务端操作，不进入浏览器共享 operations；不新增宏、原生 Office chart 或 Plotly。
