# XLSX 插入 ▸ 链接（单元格超链接）验收

2026-11-13。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收单元格超链接这一项，不代表 XLSX 插入选项卡已全部对齐。

## 固定源行为

- **对话框**（`apps/sheets/src/renderer/ExcelShell.tsx` `LinkDialog`）：
  - 只有一个地址输入框；没有链接的单元格显示“插入链接”，已有链接的显示“编辑链接”，并多出“删除链接”按钮。
  - 地址为空时“确定”不可用，按 Enter 提交。
- **地址规范化**（`univer-sync.ts` `normalizeLinkTarget`）：
  - `http(s)://`、`mailto:` 原样保留，`Sheet!A1` 形式写为 `#Sheet!A1`，裸域名补 `https://`。
  - 其他输入和超过 2083 字符的输入一律拒绝。
- **单元格样式**（`link-set` / `applyAiHyperlink`）：链接单元格设为蓝色 `#0563C1` 加下划线；删除链接时清除颜色与下划线（`cl`、`ul` 置空）。
- **写入**（`packages/xlsx-gateway/src/gateway/xlsx-hyperlinks.ts` `applyHyperlinkEdits`）：
  - 外部链接写为工作表关系里的 `TargetMode="External"` 关系，由 `r:id` 引用；文档内链接写为 `location` 属性。
  - 删除链接时回收不再使用的关系；`hyperlinks` 节空了就整个删除；新建的节按 schema 顺序插入。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 引擎移植 | `src/hyperlinks.ts` 移植固定源写入器，编辑逻辑不变，只把依赖改为本地 `xml.ts`；`nextFreeRelationshipId` 原样复制。固定源两份测试原样引入，只改了导入路径。 |
| 引擎适配 | `src/hyperlink-write.ts`。 |
| 读取 | 区域链接、同时带 `r:id` 和 `location` 的链接、无法核验的关系都视为只读，并给出原因。 |
| 来源身份 | 每项修改都带 `expectedTarget`（该单元格当前的链接）。与文件不符、目标未变化、单元格重复时，整批拒绝。 |
| 目标校验 | 只接受 http / https / mailto，或指向本工作簿中存在的工作表单元格（`#Sheet!A1`，工作表名带空格时加引号）。 |
| 写后回读 | 写完后回读全部链接：被改的单元格是新目标，其余链接不变。不一致时放弃本次修改。 |
| 桥接 / Python | 新操作 `applySheetHyperlinks {sheetName, edits}`，已加入 `native_office.py` 和 `delivery/xlsx.py` 两处白名单。 |
| 前端 | 插入 ▸ 链接按钮已接通。`workbook-link-dialog.ts` 照搬固定源的对话框结构、中文文案和 `normalizeLinkTarget`。 |
| 当前链接 | 读取“草稿重放后”的文件，所以未保存的行列插删、改名也会反映出来。 |
| 写入与撤销 | 链接操作和一个仅改样式的单元格编辑（蓝色下划线，或清除样式）作为同一步追加到草稿，再由浏览器内引擎重放。因此撤销、重做、刷新恢复时，两者总是一起进出。 |

## 证据

- **引擎测试**（`packages/xlsx-engine`）：
  - 固定源原有的 `tests/hyperlinks.test.ts` 和 `tests/hyperlink-reid-regex.test.ts`，以及适配层的 `tests/hyperlink-write.test.ts`：`Tests 15 passed (15)`。
  - 覆盖内容：添加、编辑、删除外部链接 / 文档内链接 / mailto；`&` 被转义；关系被回收；空节被删除；过期身份、目标未变化、不安全或悬空目标、重复单元格、空批次均被拒绝；区域链接和混合链接只读，它们覆盖的单元格拒绝编辑。
- **Python**（`reporting/tests/test_native_xlsx_hyperlinks.py`，经真实引擎用 openpyxl / ZIP 回读）：`8 passed`。
  - 三类链接的写入结果都正确，单元格值不变，另一张工作表不变，只改了工作表 XML 和它的关系部件。
  - 删除后 openpyxl 读到的链接为 `None`。
  - 非法目标、过期身份、目标未变化、小写引用、多余字段都被拒绝。
- **前端单元测试**（`src/workbook-link-dialog.test.ts` + `src/workbook-ribbon.test.ts`）：`Tests 55 passed (55)`。覆盖 `normalizeLinkTarget`、对话框的插入/编辑/删除/报错，以及功能区可用性门控。
- **类型检查**：只剩上游已有的 `pdf-form-canvas.test.ts` ×2、`slides-main.test.ts` ×1。
- **`src/workbook` 全量对比**：与基线 `1e0b6e31` 逐条比较失败用例名。基线 119 个失败，本分支 115 个，没有新增失败；失败的都是上游已有的 `__getInjector`。
- **浏览器冒烟** `smoke/workbook-link-gui-smoke.mjs`（Chromium，开发服务器，真实 Python 引擎；授权和修订路由用 fixture），退出码 0，`"ok":true`。步骤：
  1. A1：先输入 `javascript:` 地址，被拒绝；再输入 `example.com/report?a=1&b=2`，补成 https 后保存。
  2. B1：输入 `'汇总 表'!A1`。
  3. C1：已有链接显示“编辑链接”和来源地址，删除。
  4. 再打开 A1，显示重放后的链接。
  5. 撤销一步后，C1 的链接和样式一起撤回；重做恢复。
  6. 刷新后草稿恢复，保存为修订 2，下载字节与保存一致。
  7. openpyxl 回读：A1 是外部链接，B1 的 `location` 为 `'汇总 表'!A1`，C1 没有链接；A1 字体为 `FF0563C1` 加单下划线，C1 没有下划线；单元格值和另一张表不变。改动的部件只有 `sheet1.xml`、它的关系部件和 `styles.xml`。
  8. 重开修订 2，A1 的链接从文件读出；截图中 A1、B1 为蓝色下划线。

## 与固定源的差异 / 未完成

- **白名单更严**：固定源可以写任意规范化后的地址（如 `ftp://`）。这里只接受 http / https / mailto 和指向本工作簿存在工作表的单元格；悬空的工作表引用会被拒绝。
- **只读的链接**：区域链接（`ref="A1:B2"`）、同时带外部地址与位置的链接、无法核验关系的链接，都只读不改。
- **点击单元格不打开链接**：固定源提示“点击单元格即可打开”。这里没有接网格内跳转，只负责编辑和写回。
- **未验收**：生产构建、真实授权与发布链路；也没有用 Excel 人工打开核对。
