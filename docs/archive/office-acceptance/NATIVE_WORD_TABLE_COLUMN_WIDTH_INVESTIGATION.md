# Word 来源表格列宽与均分列调查

2026-11-10 只读调查。固定来源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮仅新增此文档并在 `/tmp` 执行真实固定源 helper 探针；没有修改生产代码、测试、运行完整测试或生产 build。本调查提出下一批实现方案，不代表列宽入口或全部表格能力已对齐。

## 下一项完整交付范围

建议只交付来源固定表的 **指定选中逻辑列宽 + 平均分布各列**：包括合法横向/纵向合并来源、多次调整、Undo/Redo、草稿刷新、保存及重开，且非目标 XML 原样保留。行高/均分行、AutoFit 模式切换、拖边界、嵌套表与自由表格属性不混入此项。

固定源有可复用的列宽命令，但不能直接采用它的全表 SavePlan 重建作为无损保存方案。真实探针确认：原始 2401 twip 经 PM 初始投影后成为 160px，写回仅 2400 twip；修改列宽后 `tblGrid/tcW` 已改变，而 `tblW` 仍是旧总宽；重建丢失原段落 `w:rsidR`。这些是已观察到的源行为，不应被包装成本地已支持或正确行为。

## 固定源语义与入口

所有路径相对固定源，源码永久根 https://github.com/ahaodev/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c 。

| 位置 | 事实 |
| --- | --- |
| `apps/docs/src/renderer/editor/table-sizing.ts:1` | 独立纯 PM 命令模块，仅依赖 PM；SHA256 `1fa1efaa9277264ba62a52733c68d2cbf5895da349a67367e0710391ee8f68e4`。最小列宽常量 40px。 |
| 同文件 `fitColumnWidths:16` | 先把请求/现有宽度提升到 floor；floor 是 `min(max(1,minimum),limit/列数)`。总宽超过节内容宽时先按未选列的可缩空间比例缩，仍不够才缩选中列；结果保留 0.01px，并消除超宽浮点漂移。未超宽时允许总表宽变大/变小，不强制维持原总宽。 |
| `targetFromSelection:76`、`tableGridWidths:102` | 使用 `selectedRect` 的逻辑 `[left,right)`；每个逻辑列从 TableMap 顶行覆盖格的对应 colwidth slot 取宽，缺失则由表百分比乘节内容宽、最后均分回退。rowspan/colspan 不按物理 cell 下标处理。 |
| `writeGridWidths:125` | 遍历全表逻辑槽、同 cell 去重，所有可见格写入对应 colwidth slice；表写 widthPx=总宽、widthPct=null、colWidthsPct；非 fixed 时切换 fixed 并标记 tblAutoFitEdited。内容/rowspan/colspan 不改。 |
| `setSelectedColumnWidth:187` | 选择覆盖到的每一逻辑列都设置同一个 desiredPx。一个横跨两列的合并格 caret 会把**两列各自**设为请求宽度，不把请求当成合并格总宽。输入无有效 target 返回 false；宽度差≤0.01px 时可能不派发 transaction。 |
| `distributeSelectedColumns:204` | 多逻辑列选择时只均分所选列的当前总宽；仅覆盖一个逻辑列时均分全表。caret 在 colspan>1 格上等价于多列选择，均分其跨度，并非必定整表。均分后仍调用相同 fit 约束。 |
| `components/Ribbon.tsx:1477–1543,3285,3346` | 节内容宽为 `(pageWidth-marginLeft-marginRight)/15`（缺节回退624px）；列宽输入 twip，先 `max(1,round(twips/15))` 再调用命令。全表 NodeSelection 先经 `enterSelectedTable` 转成 CellSelection。 |
| `editor/table-ops.ts:440` | 均分行是 DOM 测量操作：选多行则只选中行，否则全表；按实际 row DOM 高度平均，除 zoom 转为像素，再乘15取整为 twip。它不是列宽 helper，也不能用于无 DOM bridge。 |
| `Ribbon.tsx:1517` | 指定行高选中行写 heightTwips，null=auto，按节可用高度上限截断；本轮不实现。 |
| `editor/convert.ts:1241,1880` | 初次 grid twip→PM colwidth 使用 round(width/15)，回写取首行所有 cell colwidth slots，再逐列 round(px*15)。因此非15倍数宽度在来回转换中会漂移。 |
| `convert.ts:2589` 的保存计划与 engine `generate.ts:2452` | 表格式/结构变化产生整表 XML SaveBlock；tcPr 的 modeled shd/borders 等和段落被重新生成，不能据 attrs/marks 仍在推断原 XML 无损。 |

固定源已有相关测试 `apps/docs/tests/native-table.test.ts:179` 的 `[200,200,200] + col0=500,max600 → [500,50,50]`，及 `table-ops-wave.test.ts:589` 的均分命令。本轮仅阅读，没有重新运行它们。

## 真实来源 helper → 实际 DOCX 探针

目录 `/tmp/word-column-width-investigation/` 包含 `probe.ts`、`build.mjs`、`probe.mjs`、`source.docx`、六份输出 DOCX 和 `results.jsonl`。探针直接 bundle 固定源 `table-sizing.ts`、`convert.ts`、源 docx-engine parse/save 与 buildDocx helper；PM 依赖使用本地安装版本，最小无 DOM schema 自动声明实际来源 JSON attrs/marks。仅对 `/tmp` 探针 bundle，不是生产构建或浏览器验收。固定源无已安装 node_modules，本轮不声称覆盖其锁文件所有依赖组合。

源文档 2×2，grid `[2401,2401]`，固定 `tblW=4802`；每段含 `w:rsidR="00ABCDEF"`、keepNext、bold、红色，tcPr 含 hideMark。命令 maxWidth=500px=7500twip。运行 `node .../build.mjs` 和 `node .../probe.mjs` 均退出0，每例产物重新 parseDocx。

| 探针 | 实际回读 grid twip | 其他观察 |
| --- | --- | --- |
| 第一列设200px | `[3000,2400]`，总5400 | 未选中第二列原2401变2400；tblW仍4802。 |
| 第一列设450px | `[6750,750]`，总7500 | 未选列先让出空间，选列请求保留；tblW仍4802。 |
| 先设第一列200，再单列caret均分 | `[2700,2700]` | 单列选择均分全表，保持命令前总宽5400。 |
| 首行横向合并后caret设200px | `[3000,3000]` | 合并首格 tcW=6000；次行各3000，跨度保持。 |
| 初始奇数twip表直接均分 | `[2400,2400]` | 命令前 PM 已丢每列1twip，原总4802变4800。 |
| 实际保存合并格DOCX→重开→caret设210px | `[3150,3150]` | 合并来源重开后可调整，首行 span2、次行各span1及段落顺序保留；tblW仍4802。 |

每例 SaveBlock.kind=xml；bold、颜色、hideMark、keepNext保留，rsidR均丢失。没有用“能打开”替代宽度或 XML 保留断言。探针只验证合并列来源；纵向 continue 的宽度补写须由下述向量补齐。

## 本地实际缺口与可复用部分

1. `frontend/src/docx-ribbon.ts` 已列出 `table-column-width`、`table-distribute-columns`、行高/均分行等来源 action，但365行实际可用判断只认可行列增删、重复标题、合并拆分；列宽两项仍 disabled，并非已有可用输入。
2. `docx-tables.ts` 的 TABLE_ACTIONS 仅行列插删；新增 shapeTarget 仅服务合并拆分。没有列宽命令、列宽输入或独立宽度意图；不应把列宽塞成现有 TableStep index 操作。
3. `docx-operations.ts` collector 对非意图表 attrs 变化报“暂不支持修改表格布局”，对 colwidth cell attrs 变化报“暂不支持修改单元格结构或样式”；replay 无列宽操作。直接派发源 PM 命令会被 guard 拒绝，或留下不可保存变化，必须贯通 collector/replay。
4. `docx-table-cell-shape-core.ts` 已有可信整数 widthsTwips→PM fractional colwidth `/15` 和 colWidthsPct 投影，及严格 grid/预算检查；shape steps只包括merge/split，不能冒用为宽度意图。可抽取其纯宽度投影小函数供新的 sizing core 共用，但无需为本轮改造 shape 协议。
5. `slides_engine/bridge/docx-table-cell-shape.ts` 当前已核验固定dxa网格及合法vMerge，并具备原 tcPr/段落 XML保留的结构补丁。它用于结构变化，准入对复杂 continuation/content 相当保守；列宽只需更新宽度，不移动段落，不应复制它的完整重建路径或为列宽无条件丢 continuation 自身属性。
6. `bridge/edit-docx.ts` 无受控列宽 branch/inspect能力，现有 shape 分支保护文档和同表混用拒绝可作为协议范式。列宽必须核对原 table hash、所属节内容宽及来源 logical grid，服务端不信任前端 widths/XML/maxWidth。

## 建议最小实现协议及顺序

新增独立来源表格 sizing 意图，示例只是下一批建议，字段名须实现前统一：

```json
{
  "kind": "resizeTableColumns",
  "blockId": "来源表身份",
  "expectedObjectSha256": "原table XML SHA256",
  "steps": [
    {"kind":"setTableColumnWidth","left":0,"right":1,"widthTwips":3000},
    {"kind":"distributeTableColumns","left":0,"right":1}
  ]
}
```

- `[left,right)` 描述源命令选择覆盖的逻辑列；列宽应用对整个表相应列生效，纵向选区无需写入协议。先禁止跨表/嵌套输入岛，NodeSelection可沿源入口变全表。合并格caret产生完整span范围；UI选择范围服务端仍仅当作受控列带请求，不接受 PM/XML 或任意cell IDs替代原来源身份。
- inspect签发独立 columnWidthEditable/reason、可信 grid widthsTwips、表所在节有效内容宽及逻辑格映射。初版只支持可信固定dxa表，30列/100行/1000槽，拒绝gridBefore/After、浮动/RTL等未验证几何；普通gridSpan和合法restart/continue须支持。保护文档拒绝。含复杂内容的格若只改tcW可原样保留，是否扩大准入应单独证明，不能套用shape规则后宣称全部合并格支持。
- 迁入固定源纯 `table-sizing.ts`（依赖闭包仅PM），前后端共享其 fit/选择/整表投影语义；宿主从可信**整数原twip网格**按 `/15` 投影，避免源convert初始round带来的未选列漂移。列宽输入保持来源UI twip→整px取整语义；若产品决定改成精确twip须明确记录为本地扩展，不静默混淆。
- bridge从原节推导maxWidthTwips，不能接受客户端扩大页面上限。请求步数≤50，严格 own keys、安全整数/正宽、有效列带，每步验证结果。pure planner按来源 fit 计算结果，再以确定性总宽量化分配到整数twip（例如最大余数、同余前列优先），投影PM colwidth与百分比，前后端严格相同。应保证未受fit影响的原列twip不变；均分奇数总宽余数前列分配，保持总宽。此量化是为DOCX整数存储所需的明确本地适配。
- XML写回只外科更新三处：每个tblGrid/gridCol@w:w、tblPr/tblW@w:w（保持dxa，与新总宽一致）、所有物理tc/tcPr/tcW@w:w（取该格逻辑span新宽之和，包括每个continue）。保留gridSpan/vMerge、原表/行/格属性、段落、书签/批注引用及其他parts的原字节。既有生成器可用于结构校验对照，不能把整表重建视为列宽保存必需步骤。
- collector对baseline重放width步骤，只允许生成的width相关attrs和native意图差异；段落/marks、跨度、row attrs必须完全相等。replay用同一pure core，恢复意图；draft刷新后保存须等价。初版同表与文字、样式、合并拆分、行列增删、标题行等混用报“请先保存”，不同表可按既有批次hash核验组合。保存后重新inspect，再可编辑合并来源或继续调宽。
- 不新增任意XML/完整TableModel客户端入口，不把列宽写回失败变成成功。报告产物的非阻断验收/下载契约继续适用；编辑结构来源校验与发布门禁是不同层级。

## 下一批定向验证向量

- 普通单列、多列、整表；caret单列的均分全表与caret colspan>1的仅均分span；NodeSelection整表；跨表拒绝、嵌套输入岛拒绝。
- 横span、纵span、横纵混合、首行物理格少于列数、全宽vMerge导致PM空行；逐格tcW等于各逻辑列之和，continue自身tcPr/空段完整保留。
- 源fit标准 `[200,200,200]→[500,50,50] max600`，最小40px与列数过多时floor降级、超宽时先缩未选再缩选中、未溢出允许表总宽变化；达到节边界仍不溢出。
- 原2401/3000等奇数宽度未选列不漂移；均分奇数总宽余数策略；多步set/distribute→Undo/Redo→draft刷新→保存重开多轮总宽稳定。原grid、tblW、tcW三者一致。
- 原段落rsid/paraId、pPr/rPr、run marks、字段/书签等复杂对象的允许保留或明确只读边界；底纹主题、边框主题、间距、raw tcPr/trPr不变；非目标DOCX parts逐项hash不变。
- 伪造block/hash、step/未知key/__proto__、零/负/NaN/非安全整数、越界列带/50步、客户端伪造节宽、保护文档、同表混用/不同表组合；失败不改变PM/ZIP。
- 真实来源Ribbon列宽输入与均分按钮、单格/多格/合并格选区、保存重开实际DOCX解包验证；确认输入聚焦不丢目标选择。源helper探针不能替代这些UI验收。

## 后续独立core/bridge实现记录（UI集成未验收）

本调查之后按授权新增 `frontend/src/docx-table-column-width-core.ts`、固定源pure fit闭包及 `slides_engine/bridge/docx-table-column-width.ts`；未修改操作入口/collector/UI。共享API与协议为 `applyTableColumnWidthSteps(table,widthsTwips,maxWidthTwips,steps)`，step采用上文set/distribute union。bridge提供availability/edit/verify三函数，真实固定dxa网格支持横纵合并及complex continuation，保留嵌套表为opaque XML，只外科修改三类宽值；不接受client max。来源namespace局部重绑定、布局修订、gridBefore/After、hMerge/浮动/RTL和不清晰格网明确readonly；完整XML先校验，原始属性引号/空白保留。

专属core首次RED为缺模块 `/tmp/column-width-core-red.log`；5个初始向量GREEN后，root复核补15/30列均分总宽用例发现来源两位像素取整会累计丢1twip，先RED `/tmp/column-width-many-columns-red.log` 再修复：未触floor/fit时从原整数总宽做均分，避免舍入漂移；需约束时仍复用源fit。最终core 7/7 `/tmp/column-width-core-final-green.log`，bridge真实DOCX 5/5 `/tmp/column-width-bridge-final-green.log`（XML脱敏宽值后逐字相等、ZIP非document parts不变、complex continuation隐藏字/主题属性保留、实际保存重开再编辑、opaque nested表不变及损坏/重复attr/非法布局拒绝）。独立限定tsconfig检查core/bridge及两份tests通过 `/tmp/column-width-isolated-types.log`。尚需root完成原节maxWidth签发、保护文档、入口身份/批次混用、collector/replay、UI及Python/浏览器集成，不能以此记录宣称整个功能完成。
