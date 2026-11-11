# Word 来源表格合并 / 拆分的保存实现调查

调查日期：2026-11-10。固定源 `/home/junge/pros/genoffice-source-full`，实际 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。只读源码与 `/tmp` 真实 DOCX helper 探针；本次只新增本文，没有修改生产代码或测试、运行项目测试套件、启动服务、提交或派生 agent。本地为共享脏树，行号是调查时快照。

## 可实施结论

不能只将 Ribbon 两个按钮接到 PM：本地保存协议主动禁止合并格，且投影与来源映射假定每行物理 cell 数等于逻辑列数。下一步应增加**合并 / 拆分独立结构意图、逻辑网格来源映射、XML 段落保留与草稿回放**，作为同一次完整交付。继续使用来源 PM 命令决定编辑语义，bridge 校验受控意图后以源引擎生成结构壳，再放回原段落 XML；不要接受客户端 XML 或整个 TableModel。

建议初版允许：固定宽度规则表及合法 `gridSpan/vMerge` 表的合并 / 拆分、多步合并拆分后保存及刷新重开；在同次保存中暂不混用现有行列增删、表格格式、标题行或文字更改。原有字样、段落次序、run 格式、完整原段落 XML 必须保留。这个边界仍须支持从已有合并格拆分与保存后再次合并/拆分，否则不能称为完整功能。语义告警与产物下载继续遵守项目非阻断契约。

## 固定源实现路径与准确行为

以下路径均相对固定源，GitHub 不可变根为 https://github.com/ahaodev/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c 。

| 路径 / 行号 | 事实 |
| --- | --- |
| `apps/docs/src/renderer/App.tsx:751`、`components/Ribbon.tsx:3249`、`components/ContextMenu.tsx:553` | 合并直接执行 `@tiptap/pm/tables` 的 `mergeCells`，不是 `table-properties.ts` 中自写的函数。 |
| `components/TableDialogs.tsx:82–127` | 拆分默认 `rows=1, cols=2, mergeFirst=true`；输入范围 1..50，1×1 禁止确认。 |
| `editor/table-ops.ts:129–322` | `gridOf/buildTable/blankCellContent/splitGridCell` 是拆分核心，`partition` 将整数余数优先分给前面的块。 |
| `editor/table-ops.ts:324–373` | `splitCellsInto` 对真多格 CellSelection 按 mergeFirst 决定先合并；关掉时将所选独立 cell 去重后按从右下到左上逐个拆分。 |
| `editor/table-properties.ts:1–85` | 表属性、AutoFit 的 helper，不承载 merge/split 保存；不要把此文件当作完整结构支持入口。 |
| `editor/convert.ts:1098,1182,1213–1243,1339–1422` | 模型中横向 `colSpan` 直接转 PM colspan；纵向 restart 扫描后续相同列 continue 得 rowspan，continue 不创建普通 PM 格。原 continuation model 按行/逻辑列挂在 table attrs。 |
| `editor/convert.ts:1602–1877` | `pmTableToModel` 将 PM rowspan 展开成各行物理 `vMerge=restart/continue`，保留 richParas 与 rawTcPr；结构签名变化时清空按旧坐标存的 continuationCells。 |
| `editor/convert.ts:2589–2634` | `pmDocToSavePlan` 比较 originalStructure/originalFormatting。结构未动用 original/文字补丁；结构变动调用 `generateTableModelXml(model, original.originalXml)`，产生 XML SaveBlock。 |
| `renderer/file-actions.ts:839,907` | 采集 PM JSON 成保存计划，交给 `saveDocx(parsed, saveBlocks, options)`，随后写实际 DOCX。 |
| `packages/docx-engine/src/generate.ts:2452–2544,2612` | `tableCellXml` 按 rawTcPr 外科更新 tcW/gridSpan/vMerge；富段落/运行内容重新生成。`generateTableModelXml` 按所有物理格的 span 计算网格，写 tblGrid、tr、tc。 |
| `packages/docx-engine/src/patch.ts:746` | `saveDocx` 将 XML SaveBlock 写入 DOCX，沿用原包其余 parts；它不是前端 TableMap 的替代物。 |

### 合并的内容与边界

本地安装的 PM 实现可核对 `frontend/node_modules/prosemirror-tables/dist/index.js:1523–1603`；源应用引用相同公开命令，但固定源仓库没有 node_modules，本次 helper 探针使用本地安装依赖，未声称验证固定源锁文件的所有依赖组合。

- 要求 CellSelection，anchor/head 不同；必须是完整矩形，不能把某个现有 rowspan/colspan 截成一部分。跨表选区不能变成该表内矩形。
- 遍历顺序是逻辑行优先、列次之；同一 merged cell 在 TableMap 中出现多次时只处理一次。左上 cell 保留类型与 attrs（背景、rawTcPr 等），colspan/rowspan 更新到选区尺寸；其他 cell 的 cell 级格式不会组合进左上 cell。
- 非空 cell 的完整 PM block content 按顺序追加，保留 PM 所表示的各段落及 inline marks，不是把纯文字拼成一个段落。后续 cell 若只有一个空 textblock 会跳过；若左上也是这种空段，则被后续内容取代。即便空段带段落 attrs，这个空判定仍只看结构与 childCount，因此来源会丢掉被跳过空段的格式。
- 原段落 XML 不在 PM Fragment 中。源保存结构重建会重新生成所有单元格段落，不能据“PM marks 没丢”宣称原 XML 无损。实际探针中 `w:p/@w:rsidR` 丢失，`w:b`、颜色及建模 keepNext 保留，rawTcPr 的未知 `w:hideMark` 保留。
- 原 continuation 的隐藏文字和各自 tcPr 在结构签名变化后不再复用。对于含隐藏内容的 vMerge continue、修订 cellMerge 等对象，不应直接照搬源行为并承诺完整保留；初版必须拒绝该目标结构编辑并给具体原因。

### 拆分的行列、宽度与相邻格

- `splitGridCell` 接收任何覆盖目标逻辑坐标的 cell，拒绝 gridGap 与 1×1。R/C 经 floor 后限制 1..50（UI 使用 round）；受控协议应只接受整数，不隐式修正。
- 已有 cell 跨 cs 列、rs 行。若请求 C≤cs 或 R≤rs，不缩小全表网格；在已有跨度内分块，`partition(max(cs,C),C)` 与 `partition(max(rs,R),R)` 决定新格跨度。因此拆分结果可能仍有 rowspan/colspan。
- C>cs 时仅在该 cell 原有列跨度内扩展逻辑网格，将旧各列分成 k 个子列。其他行覆盖这些旧列的邻格 colspan 随之增长，视觉总宽不变；有效 colwidth 与 colWidthsPct 同比例分配。
- R>rs 时在目标原 bottom 后插入 R-rs 行；位于插入点后的 cell 下移，终点抵达或越过该边界的邻格 rowspan 增长，其他内容不移动到新空格。
- 左上新格保留目标全部 content；其余新格只有一个空 docParagraph，复制目标首段 attrs、清空 docxIndex；目标 cell attrs 复制到所有 pieces，再覆盖跨度/宽度。并不把旧的各段落或被合并前的文字重新分配回四角。
- 新行从目标底边原行复制 attrs，但清 height/rule、repeatHeader、rawTrPr、rowRevision，并使 cantSplitEdited=true，保证继承的 cantSplit 写入。
- 多选 mergeFirst=false：逐个源格拆分，右下先行以防新行列挪动尚未执行目标。mergeFirst=true：先合并，所有内容汇到左上，再拆；caret 位于已合并格不再次尝试 merge。
- 默认 1×2 对一个 2×2 合并格的结果是两个 rowspan=2 的格；恢复四格应明确选 2×2。无需把“默认拆分”做成 PM `splitCell` 的“全部解除合并”；后者不是来源对话框语义。
- 源算法按像素浮点拆 colwidth；写 DOCX 用正整数 twip，必须单独验证总宽与余数策略。建议 bridge 整数 partition，前端按 bridge 同一 twip 网格投影；不能各端独立 round 导致宽度漂移。

## 本地缺口与最小改动位置

1. `frontend/src/docx-tables.ts:9–14,35–105` 仅四个行列增删 kind；`Projection.origin` 是单源格二维矩阵，`projectSteps` 要求物理格数等于列数。`projectStep` 还会按 rowIds/colIds 重建每格，不能直接扩 union 后复用处理合并。
2. 同文件 `target:126–149` 要求单个 1×1 cell，与合并多格 CellSelection 冲突；nestedInputActive 守卫应继续保留。需 merge 专用完整矩形检查及 split 的 caret/CellSelection 目标。
3. `frontend/src/docx-operations.ts:449–474` collector 只识别现有 structure intent，其他布局变化直接拒绝；`675,745` replay 也仅认识四种 row/column 步骤。必须同时接通 collector/replay，不能仅本次保存能工作、刷新草稿失败。
4. `reporting/slides_engine/bridge/docx-table-structure.ts:41–97` 的 sourceOf 显式拒绝 vMerge/gridSpan、嵌套、修订等；并将每格 tcW 与单列宽比对。`editTableStructureSteps:118` 的 rowIds/columnIds 只能保留一个源 cell，无法表达多格合并后的段落串。
5. `bridge/edit-docx.ts:1012–1042` 的严格 keys/kind 校验、`restructureTable` 步骤解析与能力签发都要新增受控结构分支；不能让新字段悄悄绕过哈希/源身份检查。现有 cells 是物理行/cell 坐标；逻辑选区必须新增映射，不要修改 cellId 现有语义。
6. 本地源引擎已具备 span 写入；缺的是可验证编辑协议和原 XML 保留，不需要重新造 DOCX ZIP 或表格 XML 生成器。

## 建议协议与端到端实现顺序

这是建议设计，尚未实施；字段名可在实现时沿现有风格定稿。

```json
{
  "kind": "reshapeTableCells",
  "blockId": "来源表 blockId",
  "expectedObjectSha256": "完整源表 XML 的 SHA256",
  "steps": [
    {"kind":"mergeTableCells","rect":{"top":0,"left":0,"bottom":2,"right":2}},
    {"kind":"splitTableCells","rect":{"top":0,"left":0,"bottom":2,"right":2},"rows":2,"columns":2,"mergeFirst":true}
  ]
}
```

- rect 为零基逻辑网格、bottom/right 排他；每一步坐标基于前一步完成后的表。split 的 rect 描述源选择，单 caret 也传覆盖整个 cell 的 rect；服务端验证它确实等于目标 cell，不能借坐标切割部分 span。最多沿用 50 步，行≤100、逻辑列≤30、网格槽≤1000，各步扩展后都检查。拒绝未知 key、非安全整数、1×1 no-op split、重复伪坐标和超预算。
- inspect 新增独立 `cellShapeEditable/cellShapeReadOnlyReason` 与服务端核验的逻辑格清单 `{top,left,bottom,right,physicalRow,physicalColumn,cellId}`、正整数 widthsTwips；保留现有 structureEditable 及 cells 语义。简单固定表可兼容原能力；允许合法 span，必须证明每个槽唯一覆盖、continue 与 restart 同列同宽、无孤儿/交叉、无 gridBefore/After。初版可拒绝 hMerge 旧编码、非连续 header、修订/嵌套/字段/绘图/SDT/书签等原 sourceOf 其余复杂对象；需明确原因。
- **先写共享语义适配，再接 UI。** 前端复用 mergeCells 与固定源 splitCellsInto/splitGridCell，不重新设计选择或文字分配；适配层集中将逻辑 rect 建成 CellSelection，记录非渲染 intent，确定性投影。bridge 用同一算法和最小无 DOM PM schema执行 source TableModel→tableModelToPmNode→命令→pmTableToModel；只接受签发能力与哈希，绝不相信客户端提供的 PM/原 XML。源 helper 可 bundle，勿把整个 renderer/UI 包搬进 bridge。
- **段落 XML 来源映射须随结构步骤推进。** 每个 logical GridCell 附服务端原 `w:tc` 与有序直属段落片段列表（按 row/physicalColumn/paragraphOrdinal 定位，不能用文字搜索）。合并时沿 PM 行列扫描、去重、空判定，拼接其段落片段；采用左上 rawTcPr。拆分左上 piece 接收全部片段，其余 piece 按首段 pPr 模板生成空段，并清段落身份/书签类 ID。邻格只改跨度与宽度，原片段继续指向原 XML。可由稳定服务端 origin tokens 对照 PM 操作前后 content 完成，不把 tokens 写进 DOCX。
- **结构壳复用 generateTableModelXml，内容保留用直属 XML child。** 用结果 model 生成合法 tblGrid、trPr、tcPr 与 continue 格壳；然后对每个可见 restart/普通 cell 放回映射的完整原段落 XML，保持原 w:p attrs/pPr/rPr/空段。continue 只生成空段。未改动格保留完整 cell XML 并只外科更新 tcW/gridSpan/vMerge；变化格采用引擎生成 tcPr 加原段落列表。不要全文替换相同段落字符串。这个策略优于直接源 SavePlan 重建全部段落，也与现有 bridge 的原 XML 保留习惯一致。
- **既有 continue 边界。** 仅签发 continuation 无有效文字/对象/特殊属性的简单合并格；否则不支持本次结构编辑。不能把隐藏文字既追加到合并内容又留在 continue 导致重复，也不能清 continuationCells 后静默丢掉。后续若要覆盖复杂 continuation，需给每条 continuation 独立来源映射与迁移规则。
- **采集与回放必须严格等价。** collector 从 baseline 与 intent 重放投影，确认当前表除意图外与投影完全相等，再发一个 reshapeTableCells。replay 校验 blockId/hash/能力后使用同一 helper重建投影并恢复 intent。初版与同表文字/行列增删/格式/重复标题混用给明确“请先保存”原因；不同表操作可在现有整批原始来源校验后组合。保存成功重新 inspect、更新 baseline/anchors，下一轮即可编辑合并后的格。
- **两端回读。** bridge 生成后调用 parseDocx 回读，比较逻辑 span 矩形、总宽、各可见 cell 的段落顺序、非目标 XML 与原段落片段字节。输出失败时不能将无效编辑说成成功；若属于报告导出验收告警仍应遵守已有下载非阻断契约。编辑结构校验与报告发布门禁是不同层级。

这里独立 operation 比直接扩大现有 restructureTable 更小：现有矩形行列插删路径及旧草稿契约不需要重写。待合并/拆分闭环后，再以经过统一网格映射的结构 step union 支持与行列增删混用。

## 已执行的真实 DOCX 源 helper 探针

目录 `/tmp/word-merge-split-investigation/`：`probe.ts`、`build.mjs`、`ui.ts`（仅重导出固定源 WORDART helper，避免无关 UI 资产依赖）、`probe.mjs`、`source.docx`、四个输出 DOCX、`results.jsonl`。构建使用本地 esbuild/PM 依赖，直接 bundle 固定源 `table-ops.ts`、`convert.ts`、engine parse/save/generate 与原测试 buildDocx helper；最小无 DOM PM schema 自动声明来源 JSON 的 attrs/marks。它证明源 helper→XML SaveBlock→实际 ZIP→parseDocx 回读，不是 UI/浏览器或生产 bridge 验收。

最终命令 `node /tmp/word-merge-split-investigation/build.mjs`、`node /tmp/word-merge-split-investigation/probe.mjs` 均退出 0。四例全部 SaveBlock.kind=xml：

| 输出 | 回读关键结果 |
| --- | --- |
| `merge-2x2.docx` | 2×2 原表变为顶行一个 colSpan=2/vMerge=restart，次行同宽 continue；可见格 paras 为 `[A1,B1,A2,B2]`，四段顺序一致。 |
| `split-default.docx` | 从前例 caret 执行 splitCellsInto(1,2,true)；网格仍 2×2，顶行两个 rowspan=2 的格，全部四段仍在左上，右上空。 |
| `split-plain-3rows.docx` | 普通 A1 分为 3×1 后网格 2×4，B1 跨前三行；A2/B2 在第 4 行，A1 内容只在第一格。 |
| `split-each.docx` | 第一行选中 A1/B1，mergeFirst=false、1×2；网格 4×2，第一行 `[A1,空,B1,空]`，第二行 A2/B2 各 colSpan=2。 |

每例 `w:b`、颜色 FF0000、rawTcPr 未建模 hideMark、建模 keepNext 仍在；每例原段落 `rsidR=00ABCDEF` 均消失，证实源“保存成功”不等于所有原 XML 保留。

固定源已有相关用例 `apps/docs/tests/table-ops-wave.test.ts:137–234,322`，本次仅阅读没有执行；应复用其语义向量，而非宣称它们是本地 bridge 通过证据。

## 下一步定向验收

仅运行与改动相关测试，不全量重复测试。至少覆盖：横/纵/矩形合并；带不同 run 格式与完整 p attrs 的阅读顺序；格式化空段的来源空判定；跨已有 span 边界拒绝；默认 1×2 与显式 2×2；普通格扩行/扩列导致邻格 span 改变；多选不先合并的右下顺序；宽度奇数余数总和不漂移；已有合法 merge 来源重开可拆；复杂 continuation 明确只读；伪造 block/hash/rect/steps；草稿刷新恢复后保存；同表不允许的混用不丢原内容。真实浏览器验收须点击来源 Ribbon/对话框、选区、撤销/重做、保存/重新打开，对实际 DOCX 解包验证段落片段和 span；本调查没有替代这些验收。

## 实施补充：独立 bridge helper（2026-11-10）

已新增 `reporting/slides_engine/bridge/docx-table-cell-shape.ts`，由 root 另行接通 inspect/apply：

- `tableCellShapeAvailability(block)` 签发独立能力、整数 twip 网格与可见 cells 的逻辑 rect + 真实 XML physicalRow/physicalColumn。准入保留原固定表限制，仅增加合法 gridSpan/vMerge；continue 必须是无隐藏内容、无额外 tcPr 的纯延续格。
- `editTableCellShape(block, steps)` 调用共享 `frontend/src/docx-table-cell-shape-core.ts`。服务端最小 PM schema 用段落 docxIndex token 保留原片段身份；合并/拆分沿固定源语义推进 token。原段落逐字放回引擎生成的结构壳，新空段只继承首段 pPr，不复制来源段落身份。
- 返回 `{xml,widthsTwips,cells}`，cells 含实际逻辑 rect、物理坐标和完整 paras 数组。`verifyTableCellShapeResult(actualBlock, result)` 供 root 实际产物 ZIP 重新 parseDocx 后验证：整张原 XML 必须与生成值逐字相等，且逻辑网格、段落数组、网格宽度相等。helper 内部还会同步检查生成 XML/model 的准入与布局一致性。
- 专属 `bridge/tests/docx-table-cell-shape.test.ts` 先以未实现 stub 得到预期 RED，再实现 GREEN；新增字节篡改回归同样先 RED 再 GREEN。最终定向运行 5/5 通过，包含真实 buildDocx→parseDocx→编辑→saveDocx→JSZip 解包→parseDocx→再次拆分；额外覆盖扩行扩列、奇数 twip、复杂源、隐藏 continue、超步数、伪字段与原段落属性被篡改。

运行命令：`TSX_TSCONFIG_PATH=smart_reporting/report_editor/frontend/tsconfig.json smart_reporting/reporting/slides_engine/node_modules/.bin/tsx --test smart_reporting/reporting/slides_engine/bridge/tests/docx-table-cell-shape.test.ts`。未运行完整前端构建或全量测试。本补充仅描述独立 helper 验证，UI、协议入口及整批保存由 root 集成验收。

### 复核修复：完整属性及 pretty XML 字节保留

独立复核发现引擎 tableCellXml 会规范化主题 shd/borders（丢 themeFill/themeTint，border space 变0），因此 bridge 不再整体采用生成 tcPr：服务端 sourceCell.rawTcPr 仅更新生成壳 tcW/gridSpan/vMerge，其余属性全部保留；未变结构字段保留原拼写。原行 rawTrPr 逐字回填，新行才生成。另保留每个源格 sourceXml，若内容段落序列未变，直接对完整原 cell 外科替换 tcPr，保留 pretty XML 的 tcPr 间空白、tcPr 与段落及 cell 尾部空白。两个新增回归分别先 RED 再 GREEN，最终专属 7/7 通过。
