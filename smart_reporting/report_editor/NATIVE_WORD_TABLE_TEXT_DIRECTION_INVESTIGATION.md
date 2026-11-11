# Word 表格剩余入口盘点与文字方向完整缺口

2026-11-10。仅调查与 `/tmp` 独立探针，不改生产、不build、不跑完整测试。AutoFit属于已实现后待最终集成验收的独立项，本调查不重复计入，也不把当前有限表格能力视为全量目标完成。

## 盘点与本批选题

| 入口族 | 固定源事实 | 本地现状（调查时） |
|---|---|---|
| 插入单元格对话框 | `components/TableDialogs.tsx:123` above/below/left/right+count，调用 `insertRowsOrColumns`；实际是批量整行/整列插入，不能凭标签误认为局部右移/下移 | Ribbon有table-insert-cells，但命令未接通；已有单次整行列按钮不等于此对话框交付 |
| 删除单元格 | `editor/table-ops.ts:580` shiftLeft/shiftUp/row/column，plain-grid约束见canShiftCells | table-delete-cells未接通；已有删行列不覆盖移格内容语义 |
| 表格属性 | `components/TablePropertiesDialog.tsx` 包含表/行/列/单元格相关多项和导航 | table-properties未接通；AutoFit只覆盖其中独立模式，不等于属性窗口交付 |
| 单元格边距 | `TableDialogs.tsx:216` 实际是整表默认边距选项，applyTableValue touched margins写table.cellMar；不是选中cell.tcMar | table-cell-margins未接通；不能误做只改选中cell |
| 九宫格对齐 | `table-ops.ts:708` 同时改selected cell.vAlign和直属docParagraph/docListItem.align，包含bidi解释 | 9入口未接通；段落对齐已有能力不等于cell垂直对齐交付 |
| 文字方向三入口 | `table-ops.ts:729` lrTb/tbRl/btLr，明确选择范围与保存语义 | 三入口均未接通；本批选为可独立完整交付的下一项 |
| 已交付/集成中的表能力 | 合并拆分、行列结构、行高/均分、列宽/均分、标题行、AutoFit等各有独立边界 | 不混算到本调查完成度；各项最终built/下载结果以root报告为准 |

本地定位 `frontend/src/docx-ribbon.ts:114–116` 三action分别为 `table-text-direction-horizontal` / `table-text-direction-rotate-90` / `table-text-direction-rotate-270`。`docx-tables.ts` 未处理这些action，落入target后因TABLE_ACTIONS没有映射返回“此表格命令尚未接入”。协议与bridge也未提供可保存的单元格方向操作。vendor解析/渲染已经支持textDirection，只能证明显示能力，不能标记编辑链路完成。

## 固定源码身份与语义

仓库 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- `apps/docs/src/renderer/editor/table-ops.ts` SHA256 `d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd`。
- `components/TableDialogs.tsx` SHA256 `08ec3b80d2ea04314adcc0281e4c9dcdd7519bd344fcb61a7944a98f4a7b4791`。
- `components/Ribbon.tsx:3399` 调用 `runTableCommand(setCellTextDirection(dir))`，runTableCommand先focus并 `enterSelectedTable`，表节点选择转换为全表CellSelection。

`selectedCells`（约688行）遍历selectedRect逻辑网格，按cellPos去重，并跳过gridGap。普通光标只改变所在cell；CellSelection改变矩形内的每个唯一cell；合并单元格只在PM中更新owner一次。不是整行或整表默认扩展。

`setCellTextDirection(dir)` 复用 `setCellProps`：横排lrTb写 `textDirection:null`，另两种分别tbRl/btLr；同时 `tcPrEdited:true`，保留其余cell attrs/content/marks。`lrTb` 是清除显式属性，不是强行写 `<w:textDirection w:val="lrTb"/>`。

源engine parse把tbRlV归为tbRl、btLrV归为btLr（`parse.ts:6187`），这是有效模型归一而非原字节保真；未编辑来源必须保留原别名字节，明确编辑才改标准值。generate约2501行在tcPrEdited下替换/清除直属textDirection。纵向合并保存会把owner方向传播到物理continue，不能只patch PM里存在的restart。

## 可复现实证

`/tmp/word-table-direction-investigation/probe.ts` 直接调用本地 `createDocxTableCommands.reason`，八个入口代表（properties/insertCells/deleteCells/margins/align以及三方向）全部断言返回“此表格命令尚未接入”。这证明实际命令路由缺口，探针没有启动生产站点，不冒称GUI截图验收。

同一探针真实 `buildDocx → parseDocx → tableModelToPmNode → PM state/selection → 固定source setCellTextDirection → pmDocToSavePlan → saveDocx → parseDocx`。原fixture两行两列，源XML含2000twip网格、精确行高300、bold/color/hideMark/keepNext和段落rsidR。schema按来源JSON记录attrs/marks，并显式包含textDirection/tcPrEdited。

```sh
node /tmp/word-table-direction-investigation/build.mjs
node /tmp/word-table-direction-investigation/probe.mjs > /tmp/word-table-direction-investigation/results.jsonl
DIRECTION_SOURCE=merged node /tmp/word-table-direction-investigation/probe.mjs > /tmp/word-table-direction-investigation/merged-results.jsonl
```

普通表及首列纵合并表各执行三方向、首列两行选区、tbRl→lrTb清除，共10个source操作向量：

| 选择/命令 | source实际PM/保存结果 |
|---|---|
| 光标A1→lrTb | PM null；保存不含任何textDirection |
| 光标A1→tbRl | 普通表仅A1方向tbRl；合并表A1 restart及下一行continue均写tbRl |
| 光标A1→btLr | 普通表仅A1方向btLr；合并表restart+continue均写btLr |
| CellSelection首列两行→tbRl | 普通表两个cell变化，第二列不变；合并表唯一owner变化 |
| tbRl→lrTb | 最终删除方向元素，没有旧方向复活 |

三种保存模式均再次证明source整表SavePlan会丢段落rsidR（探针断言消失），因此后续不能直接接source整表生成当作原文件无损实现。

目前未探测横向跨列合并、复杂continue原内容、嵌套表独立选区、表节点选择、旋转后的真实浏览器排版及保存HTTP链路。必须保持为待验收范围，而不是用上述10向量代替全量表格能力。

## 最小完整实现建议

新增独立cell-direction共享core/bridge，不借AutoFit/列宽协议携带任意cell属性。推荐操作：

```ts
{ kind: 'setTableCellTextDirection', blockId, expectedObjectSha256,
  steps: [{ top, left, bottom, right, direction: 'lrTb'|'tbRl'|'btLr' }, ...] }
```

各step精确5键，矩形为逻辑半开范围，1–50步。core使用合法TableMap，按source selectedCells唯一owner范围语义应用并设tcPrEdited；不接收client cell XML、rawTcPr、任意方向字符串。前端命令、草稿登记/恢复、undo/redo和服务端都顺序回放，重复步骤与清除后设置必须一致。表节点选择与CellSelection沿用固定源，不只支持光标单格。

独立capability建议 `cellTextDirectionEditable/ReadOnlyReason/Cells`，logical rect+physical字段标识合并owner和continue；不依赖fixed-dxa、文字纯净或AutoFitEditable。方向是单元格属性，表auto/pct、正常nested内容opaque保留、单元格含富文本/图片不该默认只读。独立嵌套编辑器尚无可信block anchor时明确提示，避免误操作外表。

bridge从原XML和原模型核验table/cell身份、完整span/grid、方向标签单例与叶属性、修订/重复/伪造方向；只补每个目标owner覆盖的物理tcPr/textDirection，含同一合并范围所有continue。原有合法tbRlV/btLrV可按source有效归一解析，未选中保留字节；编辑的正向方向标准化为tbRl/btLr，横排删除标签。缺tcPr插入并保持OOXML顺序。不得重建table/tc/p/r，不得触paragraph textDirection或嵌套表的同名元素。

特别注意：tcPrEdited只是PM显式编辑标志，不授权服务器把tcPr全部重写；格边距/nowrap/边框/宽度/方向以外属性仍按原文件保留。合法纵合并continue可能含自己的方向、tcPr、隐藏段落/绘图，更新方向之外均保留。复杂源的独立可编辑性必须做真实fixtures验证，不凭现有有限fixed表能力冒称全支持。

同表其他编辑若本批未做可组合投影，清楚要求先保存；同节页面修改是否冲突应由实际方向依赖决定，它没有width/height预算，不应复制AutoFit的节宽门禁。文件保护、作用域/对象SHA边界继续生效。

## 实施后验收（未执行）

1. core/bridge RED/GREEN：三个方向与横排清除；光标/矩形/表节点选区；横纵合并owner去重、continue传播；多步方向覆盖、空/非法范围、额外字段/未知方向拒绝。
2. XML保留：原别名tbRlV/btLrV、缺tcPr、复杂continue、富文本多段/图片/嵌套表；只改目标直属方向，非目标段落rsid、marks、width/grid/rowheight、包内其他parts不变。故障回读不能只看PM标签。
3. built真实入口：三按钮启用、方向实际布局变化、选区不丢、undo/redo、草稿刷新、保存下载、回读XML、重开继续；图片和字体显示不因方向切换被丢弃。注意source btLr/tbRl渲染的真实浏览器方向差异，不能只检查字符串。
4. 文件保护/非法来源/跨scope/hash伪造拒绝。与其他同表步骤混合的明确支持/先保存边界；不扩大 unrelated工作范围。
5. 后续仍需独立覆盖插删格、属性、边距、九宫格对齐、拆表/选表等剩余能力；本项即使交付也不等于全量Word表格完成。

## 独立core/bridge实现证据（2026-11-10）

经root确认已新增 `docx-table-cell-text-direction-core.ts`、`bridge/docx-table-cell-text-direction.ts` 及各自测试；外层入口、operations、Python由其他集成任务负责，本子任务没有修改或构建。原调查时本地reason未接通的证据保留为历史时点，入口已开始接入后，旧混合探针不再可用作当前未交付断言。

API为 `applyTableCellTextDirectionSteps(table,steps) -> {table,directions}`；`tableCellTextDirectionAvailability(block)` 签发 `cellTextDirectionEditable/ReadOnlyReason/Cells` 和 `cellTextDirections`；`editTableCellTextDirection(block,steps) -> {xml,cells,directions,physicalDirections}`；`verifyTableCellTextDirectionResult(block,result)`。步骤精确5键、1–50，所有坐标逻辑网格slot→唯一owner，不用物理tc索引冒充选区。core为source selectedCells/setCellTextDirection/setCellProps等效纯投影，保留内容/marks/其他attrs，不声称原函数逐字迁入；来源SHA已写代码注释。

桥接独立于fixed-dxa宽度及节高预算，允许合法横纵合并、富文本、多段、嵌套表内容opaque、缺tcPr和常规auto/pct来源。已有正整数grid、≤100行/30列/1000槽为当前模型边界；缺grid、非法span、未知方向、重复/nested控制、修订等显式只读。方向别名有效归一，未编辑原值与属性引号空白保留；lrTb删除直属tag。目标合并owner的所有物理continue统一更新，未选owner即使continue原方向不一致也逐字保留。回读同时核验actual原XML、逻辑cells/directions和每个物理direction，不只看restart。

真实source补充：`/tmp/word-table-direction-investigation/alias-only-probe.ts` + `alias-only-build.mjs` + `alias-source-results.jsonl` 证明原tbRlV/btLrV在固定source parse与convert后均为tbRl/btLr，其余null。`span-probe.ts`/`span-results.jsonl` 验证跨水平合并选区由source selectedRect扩展到其owner覆盖范围，随后selectedCells按slot去重写每个owner。

RED/GREEN：`/tmp/cell-direction-core-red.log` 缺新模块失败后，core3例 `/tmp/cell-direction-core-green.log` 通过；bridge缺模块 `/tmp/cell-direction-bridge-red.log` 后，4个真实DOCX用例 `/tmp/cell-direction-bridge-green.log` 通过；额外未选合并owner/continue故意不一致保留用例 `/tmp/cell-direction-unselected-green.log` 通过；限定TypeScript `/tmp/cell-direction-types.log` 零错误。覆盖三方向、clear链、span owner/continue、未选别名原字节、missing tcPr、nested opaque、段落rsid/富文本、非document.xml包件、伪造模型/结果及未知/nested方向拒绝。没有完整套件重复或生产build。

当前仅此core/bridge子任务完成并冻结，真实GUI/HTTP下载/undo/redo/草稿验收由root单列；其余表格完整目标范围继续保留，不能据此标记全部完成。
