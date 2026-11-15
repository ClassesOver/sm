# XLSX 视图 ▸ 拆分窗口验收

2026-11-14，基于 `origin/code` `0ce3aa10`。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收“拆分窗口”这一项的读取修复与取消拆分写回，**没有**实现新建拆分窗格，也不代表“窗口”组其余按钮已对齐。

## 为什么不是“插入 ▸ 图片”

本轮首选的“插入 ▸ 图片”已在 `origin/code` 中由上游完成（`insertPicture` / `editPicture`、`packages/xlsx-engine/src/pictures.ts`、`bridge/pictures.test.ts`、`picture-edits.test.ts`，功能区“图片”已接通）。基于旧基线 `0b09fd79` 完成的同名实现与之重复，没有并入；该提交保留在本地分支 `worktree-agent-a6fb64f0ef0dc2a61-picture-superseded`（`b4486aed`），只作参考。因此按指令改做“视图 ▸ 拆分窗口”。

## 固定源与运行时事实

- 固定源 `apps/sheets/src/renderer/ExcelShell.tsx` 视图 ▸ 窗口组只有“冻结窗格”菜单（冻结至选区 / 首行 / 首列 / 取消冻结），**没有拆分窗口**，`ribbon-actions.ts` 也没有对应命令；`NATIVE_WORD_XLSX_PARITY_AUDIT.md` 此前也记为“源未定位”。
- Univer 0.25.1 没有拆分视口，只有冻结。新建拆分窗格既无源可移植，也无法在网格中预览，所以不做。
- ECMA-376 §18.3.1.66：`<pane>` 的 `state` 缺省为 `split`；拆分窗格的 `xSplit`/`ySplit` 单位是 1/20 磅（twips），只有 `frozen`/`frozenSplit` 时才是行列数。

## 发现并修复的缺陷

`packages/xlsx-engine/src/workbook-read.ts` 原先不看 `state`，把任何 `<pane>` 的 `xSplit`/`ySplit` 都当作冻结行列数。临时工作树基线（`0ce3aa10`）实测：`<pane xSplit="2400" ySplit="1200" topLeftCell="C5" activePane="bottomRight"/>` 被读成 `{frozenRows: 1200, frozenColumns: 2400}`，编辑器会把整张表冻结成 2400 列 × 1200 行。

修复后：只有 `frozen`/`frozenSplit` 产生 `freeze`；`split`（含缺省）产生新的只读字段 `splitPane: {xSplitTwips, ySplitTwips, topLeftCell?}`，`freeze` 为 `null`。冻结行列数改为只接受非负整数。修改文件已在 `UPSTREAM-PATCHES-SHA256.json` 中更新哈希（原登记值已与 `origin/code` 文件不一致，现与合并后文件一致）。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 写入 | `workbook_engine/bridge/split-pane.ts` `removeSheetSplitPane`：zod 严格校验 `{kind, sheetName, expected}`；工作表必须存在且当前读取到的 `splitPane` 与 `expected` 完全一致（来源身份），否则拒绝。只删除第一个 sheetView 中的 `<pane>` 及按窗格限定的 `<selection>`（与 `page-setup.ts` `setFrozenPane` 同一清理规则），其余属性和部件不变；写后回读确认既无拆分也无冻结。 |
| 操作 | `bridge/operations.ts` 新增 `removeSheetSplitPane`；Python 白名单 `native_office.py` 与 `delivery/xlsx.py` 已加入。 |
| 冻结 | 保持原行为：冻结写回（`applyPageSetups`）按 Excel 行为以冻结窗格替换拆分窗格；文件只有拆分窗格且用户未改冻结时，保存差分不写 pane，拆分窗格原样保留。 |
| 前端 | 功能区“拆分窗口”接通 `split-window`。仅当当前工作表（草稿重放后的模型）有拆分窗格、可编辑且未受保护时可用，`aria-pressed=true`，提示“取消文件中的拆分窗格”（对应 Excel 再次点击“拆分”取消拆分）；否则禁用并说明“固定源未提供拆分窗口，网格无拆分视口；当前工作表没有可取消的拆分窗格”。执行时在写锁内从当前重放字节重新读取 `splitPane` 作为 `expected`，按“链接”相同的整批重放进入草稿，可撤销/重做、刷新恢复。 |

## 证据

- `workbook_engine/bridge/split-pane.test.ts`（2 项通过）：缺省 state 与显式 `split`（含小数 twips）读为拆分、`freeze` 为 null；`frozen`、`frozenSplit` 仍读为行列数。取消拆分只改 sheet1.xml，`tabSelected`/`zoomScale` 保留，pane 与按窗格 selection 被删除，其他部件字节不变；身份不一致、已无拆分、工作表缺失、多余字段、非法 topLeftCell 均拒绝；冻结写回替换拆分窗格。
- 临时工作树基线对比：同一读取用例在 `0ce3aa10` 上得到 `frozenRows: 1200, frozenColumns: 2400`（失败），本分支通过。
- 引擎全量 `npx vitest run`（workbook_engine）：`7 failed | 1088 passed (1095)`；7 项失败（条件格式、图表轴标题、行插入、迷你图 ×3、表格读取）在 `0ce3aa10` 临时工作树上以相同 6 个文件、相同 7 项失败复现，与本次无关。
- `reporting/tests/test_native_xlsx_split_pane.py`（7 项通过）：openpyxl 生成的真实拆分窗格经 `inspect_office` 读为 `splitPane`、`freeze` 为 None；`patch_office` 取消后 openpyxl `sheet_view.pane` 为 None、`zoomScale` 保持 120，单元格与其他工作表不变，ZIP 只有 `xl/worksheets/sheet1.xml` 变化；真实冻结 `B3` 读为 2 行 1 列；4 种非法或过期操作、无拆分窗格时取消均被拒绝。
- `frontend/src/workbook-ribbon.test.ts`：新增“拆分窗口仅在有拆分窗格、可编辑、未受保护时可用并派发 `split-window`”用例；“窗口”组禁用原因用例去掉拆分窗口。合跑 `1 failed | 55 passed (56)`，唯一失败为既有“插入公式不可用原因”断言，在 `0ce3aa10` 临时工作树上同样失败（`1 failed | 54 passed (55)`）。
- 前端 `npx vitest run src/workbook`（一次）：`22 failed | 189 passed (211)` 文件，`247 failed | 1652 passed (1899)` 项。在 `0ce3aa10` 临时工作树（补装 doc/pdf/slides 引擎依赖后）对同 22 个文件复跑：`247 failed | 76 passed (323)`，失败用例名逐条比对完全相同（主要为上游 `installThreadedCommentAffordances` 的 `HoverManagerService` 未注册），与本次无关。
- Python 相关回归：`test_workbook_engine_bridge.py` / `test_office_format_preferences.py` 中冻结窗格回读用例 3 项通过（冻结 `A2` 不受读取修复影响）。
- `frontend/smoke/workbook-split-pane-gui-smoke.mjs`（Chromium + vite 开发服务器 + 真实 Python `patch_office`，授权与修订路由为 fixture），通过：
  - 打开含拆分窗格（Data）与真实冻结 B3（冻结）的工作簿：Univer `getFreeze()` 为 Data `[0,0]`、冻结 `[1,2]`。
  - “拆分窗口”可用且按下态；点击后草稿为 `removeSheetSplitPane {Data, expected:{2400,1200,C5}}`，按钮变为禁用并显示原因。
  - 文件 ▸ 撤销后草稿清空、按钮恢复可用；重做恢复；刷新后草稿恢复。
  - 保存载荷只有 `removeSheetSplitPane`；下载字节与保存一致；openpyxl/ZIP 回读：Data 无 pane、zoom 120、A1/B2 不变，“冻结”工作表仍为 `B3`，变化部件只有 `xl/worksheets/sheet1.xml`。
  - 修订 2 重开后 Data 无冻结，按钮禁用；页面无脚本错误。
- `npx tsc --noEmit`（`NODE_OPTIONS=--max-old-space-size=8192`）exit 0。

## 差异与未完成

- 未实现新建拆分窗格（固定源无此功能、Univer 无拆分视口）；“拆分窗口”只能取消文件中已有的拆分窗格。
- 文件中的拆分窗格在网格中不显示为拆分视图，只在功能区以按下态和提示说明。
- 只处理第一个 sheetView（与读取侧一致）；多 sheetView（多工作簿窗口）不改其余视图。
