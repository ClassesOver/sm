# Word 来源表格行高与均分行高调查

2026-11-10。固定源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只读代码、在 `/tmp` 运行来源 helper/真实 DOCX 探针并新增本文；未修改生产代码或测试，未运行完整测试或生产 build，不代表全部表格能力已对齐。

## 可实施的下一项缺口

本地“行高”和“平均分布各行”均尚未实现闭环。建议下一项只做**来源表格指定行高与清除行高（自动）**：普通及合法合并格来源、选中行带、多次设置、Undo/Redo、草稿刷新、保存重开、非目标 XML 保留。均分行高属于另一项，因为固定源计算依赖当前 DOM 实测，而非原 XML 的声明高度；不能拿声明行高平均冒充来源均分语义。

指定行高可使用纯 PM 投影和受控行带协议，服务端只修改对应 `trPr/trHeight`，不需要重建表格/段落或更改格网。固定源 UI 本体很短，可精确摘录到宿主纯适配；现有 source TableMap/selectedRect、Native 意图 collector/replay、hash 签发与 XML 直接子节点补丁均可复用。

## 固定源准确语义

路径相对固定源，永久根 https://github.com/ahaodev/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c 。

| 位置 | 行为 |
| --- | --- |
| `apps/docs/src/renderer/components/Ribbon.tsx:1483,1517–1534` | 最大行高为当前节 `pageHeight-marginTop-marginBottom`，无节回退13200twip。`applyRowHeight` 要求canEdit，focus，`enterSelectedTable`；输入正值截到上限，null/0/非正输入变null；只对 selectedRect 的 `[top,bottom)` 行写heightTwips，**不修改 heightRule**。 |
| 同文件 `3273–3281` | LengthInput值为当前行heightTwips，min0、max节上限、allowEmpty、placeholder自动；不是额外“固定值/最小值”下拉框。协议应明确接受正安全整数或null，不照搬JS隐式容错给非法client字段。 |
| 同文件 `3333–3338` | 均分入口先enterSelectedTable，再调用 `distributeRowsEvenly(editor.view)`。NodeSelection全表通过该 helper 变CellSelection；caret在跨多行合并格上，selectedRect包含该格完整rowspan。 |
| `editor/table-ops.ts:431–467` | `rowRange`：选区覆盖多逻辑行时用该行带；只覆盖一行时均分全表。遍历对应原生row DOM节点，`getBoundingClientRect().height / zoom`，对成功取得HTMLElement的行取平均；avg>0才派发。每个目标行heightTwips=`round(avgPx*15)`，**heightRule强制atLeast**。不存在“严格视觉等高”保证，内容更高时仍可撑大。 |
| 同文件 `zoomOf:435` | 从closest `.doc-zoom`的computed zoom读取，缺失/无效回退1。不是devicePixelRatio，也不能把页面CSS缩放重复除两次。 |
| `editor/extensions.ts:2667–2693,3281–3327` | row attrs已有heightTwips、heightRule、rawTrPr等。rowHeightCss对exact和atLeast/null使用不同边框/内边距高度计算；DOM高度不等于声明twip/15，受内容、边距、边框影响。因此不能从tblGrid或原trHeight推导来源均分测量。 |
| `editor/convert.ts:264–275,1346,1661` | source将原rowHeightsTwips/rowHeightRules投影为PM attrs并回写；节高度上限会用于来源布局显示。PM内容/其他行attrs由命令原样保留。 |
| `packages/docx-engine/src/parse.ts:5770–5773` | 有效trHeight读取为正height（最高31680）；hRule exact保留，其余归为atLeast；无height读为null。原hRule省略/auto/未知不能仅凭该规范化model声称原XML可完整解释。 |
| `packages/docx-engine/src/generate.ts:2740–2754` | 正高度写trHeight，hRule exact否则atLeast；height=null移除trHeight；空trPr可能移除。原source SavePlan整表XML重建不能保证非目标段落/属性原样。 |

固定源 `table-ops.ts` SHA256 `d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd`。均分完整闭包为rowRange/zoomOf/distributeRowsEvenly，依赖PM selectedRect/isInTable及EditorView/浏览器DOM，不必迁入整个UI/修订table-ops模块。已有 `apps/docs/tests/table-ops-wave.test.ts:573–603` 用模拟DOM20/40px验证均分450twip与atLeast；本轮仅阅读未运行。该测试不等于真实排版/浏览器验收。

## 真实来源 DOCX 探针

`/tmp/word-row-height-investigation/`：`probe.ts`、`build.mjs`、`probe.mjs`、`source.docx`、三份输出DOCX、`results.jsonl`。直接复用固定源convert、table-ops、engine parse/save和buildDocx，PM依赖使用本地安装版本，最小schema声明实际来源attrs/marks。build仅输出 `/tmp` probe，不是生产完整构建。

源2×2固定表，首行trHeight300/exact和cantSplit，第二行auto；原段含rsidR、keepNext、bold/红色，tcPr含hideMark。指定行高探针机械复现Ribbon只写heightTwips的代码；均分直接调用固定源helper，提供明确DOM测量替身40/80px与zoom2。后者证明算法，不声称真实浏览器测量值。三例均真实saveDocx后parseDocx回读：

| 操作 | 回读结果 |
| --- | --- |
| 首行指定600twip | heights `[600,null]`，rules `[exact,null]`，cantSplit保留。指定高度不会将exact改为atLeast。 |
| 首行清除heightTwips | 首行trHeight移除，trPr仅cantSplit；没有残留exact高度标记。 |
| 单行caret均分全表，测量40/80px、zoom2 | `(20+40)/2×15=450`；两行均450/atLeast；首行cantSplit保留。 |

每例SaveBlock.kind=xml；bold、颜色、hideMark、keepNext保留，**原rsidR丢失**。因此下一项应外科改行高，不以source整表重建作为无损保存方案。

## 当前本地链路核对

- `frontend/src/docx-ribbon.ts:104,106` 已列出 `table-row-height`、`table-distribute-rows`，但365/663行可用判断只包括行列增删、重复标题、合并拆分及列宽两项，行高两项仍禁用。
- `docx-tables.ts` 已接入shapeTarget、columnWidthTarget等独立能力，但没有行高target/run/dialog。`docx-table-column-width-ui.test.ts:139` 还明确断言这两个入口disabled；这是范围边界，不是已经完成的实现。
- `docx-operations.ts` 无行高意图：row attrs变化仍被“暂不支持修改表格布局”拒绝。collector、replay及NativeTableStructure attrs都需新增独立行高分支，不能只派发PM attrs。
- `slides_engine/bridge/edit-docx.ts` 无行高operation/inspect签发。原shape bridge会携带rowHeight但那是合并拆分语义，不可把它当作设置行高协议。
- 本地vendored DocTableRow已有来源高度显示及attrs，docx-engine已有parse/generate；这些只证明基础能力，不等于来源编辑/保存/草稿闭环。XML补丁可参考 `bridge/docx-table-headers.ts` 的直属行/属性补丁，但新增行高需严格解析源hRule与字段，而不是接受任意raw XML。

## 下一项建议协议、准入与保存

建议独立 `setTableRowHeights` 操作，示例：

```json
{
  "kind":"setTableRowHeights",
  "blockId":"来源table身份",
  "expectedObjectSha256":"原table XML SHA256",
  "steps":[
    {"top":0,"bottom":2,"heightTwips":600},
    {"top":1,"bottom":2,"heightTwips":null}
  ]
}
```

- top/bottom零基右排他物理行带，等于PM逻辑行数；纵向合并不会删除XML行。UI使用来源selectedRect，跨行合并caret覆盖完整span；NodeSelection沿源enterSelectedTable转整表。桥接不接受客户端heightRule、原XML、DOM或maxHeight。
- 1..50步、正安全整数或null，100行/30列/1000槽沿既有预算。正值上限由服务端从原所属节有效正文高度推导，前后端相同截断；不能接受客户端替换max，不能盲用尾节。gutterAtTop已有源section settings折入marginTop，勿重复扣减。与同节setSectionLayout同批暂拒绝或明确定义最终节预算。
- 初版独立rowHeightEditable/reason。普通及合法gridSpan/vMerge应支持；不移动内容时complex continuation可完整保留。来源table/row直属结构、trPr重复/属性、重复trHeight、height负/非法数、未知hRule、修订/布局例外无法完整解释时明确readonly。不要因为段落未知格式或对象就全表重建；原段落、未知非几何属性能证明安全则原样保留。
- 每步只变选中行heightTwips；正值保留原exact，否则写atLeast，按已确定来源UI语义处理省略hRule；null清trHeight及PM的有效heightRule。collector需注意源UI清高度仍残留PM旧heightRule，但保存后该rule无意义，应在共享投影中定义一致的持久化语义，不能把这点静默当作用户改了行规则。
- XML只替换/插入/删除直属trPr/trHeight；新增时按CT_TrPr顺序插入，保留trPr其他属性、空白、cantSplit、tblHeader、row revision边界及完整tc/paragraph XML。不整表重建、不丢空行/trPr身份，必要时保留原空trPr。输出再parseDocx核对高度、rule、非目标parts/paragraph字节及原格网。
- 非渲染意图记录完整steps；collector重放共享投影，除height相关attrs及意图外要求完全相等；replay同算法。初版同表文字、宽度、shape、行列增删、重复标题混用明确“请先保存”，不同表允许既有批次hash核验组合。保护文档始终拒绝。

## 均分行高的后续独立边界

均分不能简单交给bridge从原height平均：auto行、换行、字体、图片、padding、border和纵向合并均影响测量，且源helper故意使用实际DOM。可复用源DOM helper在前端产生受控目标高度，但服务器若只接受用户所选最终height，应明确该操作与普通手动行高同等权限、进行同样max/字段约束，不声称服务端独立验证了“测量真实”。若要求服务端验证均分来源，则需可信渲染测量/测量快照身份协议，不是本项可顺便增加的小功能。

浏览器采集需等待字体/图片稳定，固定当前文档/来源hash/选区/zoom，在异步等待后再验证身份；所有目标DOM行都应成功读取，不能沿源“缺一行只平均其余行但应用全部行”的不完整测量静默放行。均分强制atLeast且不承诺视觉严格相等，需产品文案说明。不要新增一套自制排版/测量引擎。

## 指定行高完整验收条件

1. 来源Ribbon正高度/自动空值，caret单行、多行CellSelection、整表NodeSelection、跨rowspan格、nested输入岛拒绝；定位/打开输入后源身份或选区改变时不得误写别行。
2. 原exact/atLeast/省略hRule/auto行的指定与清除；raw trPr有cantSplit/tblHeader/空白/属性，插入/移除顺序合法；重复/非法height与未知rule明确readonly，不规范化后误签发。
3. 来源首/中/尾节不同高度、gutterAtTop、保护文档；伪造block/hash/max、unknown keys/__proto__、零/负/小数/非安全整数/步数/行带、同表混用/不同表组合；失败无PM/ZIP部分修改。
4. 多步设置→Undo/Redo→draft刷新→保存重开再次设置；目标高度与规则准确，格网/列宽/span不变，非目标XML及DOCX parts字节保持。至少一个合法横纵合并来源和complex continuation隐藏内容不丢。
5. 真实浏览器点击来源Ribbon，实际DOCX解包与parseDocx双向回读；不能用PM unit/helper探针替代UI闭环，也不需要重复完整项目测试。行高保存验证不改变项目报告验收告警与产物下载非阻断契约。

## 后续指定/清除行高独立实现（入口集成待完成）

按后续授权新增 `frontend/src/docx-table-row-height-core.ts`：`TableRowHeightStep={top,bottom,heightTwips:number|null}`，`applyTableRowHeightSteps(table,maxHeightTwips,steps)` 返回 `{table,rowHeightsTwips,rowHeightRules}`。1..50步，100行/30列/1000槽，严格字段与行带，正安全整数或null；正值clamp可信max，保留当前exact/atLeast；clear将有效高度与rule置null，clear后再set为atLeast。保留所有cell/content/marks及非目标row attrs。不包含DOM均分。

新增 `slides_engine/bridge/docx-table-row-height.ts`：`tableRowHeightAvailability(block,max)` 签发 `rowHeightEditable/rowHeightReadOnlyReason/rowHeightMaxTwips/rowHeightsTwips/rowHeightRules/rowHeightCells`；`editTableRowHeights(block,max,steps)` 返回XML及高度/rule/格网预期；`verifyTableRowHeightResult(actualBlock,result)` 验证实际XML完整身份和回读语义。max仍由root从原所属节推导，不接受client max。

bridge独立验证来源XML完整性、直属行/grid及合法span链；未知/重复/嵌套trHeight属性/内容、未知hRule、非法高度、未知trPr几何/属性和布局修订明确readonly。复杂continue内容/段落未知格式保持opaque。set现有height仅替换val，省略hRule仍省略；缺失height按CT_TrPr相对cantSplit/tblHeader顺序新增atLeast。clear仅删除原直属trHeight，保留trPr空白、cantSplit、tblHeader及完整cell/paragraph XML。顺序逐步回放，避免原exact在clear后错误复活。

专属core先RED缺模块 `/tmp/row-height-core-red.log`，GREEN3/3 `/tmp/row-height-core-green.log`；bridge先RED缺模块 `/tmp/row-height-bridge-red.log`，首轮真实DOCX3/3 `/tmp/row-height-bridge-green.log`（实际save/parse、复杂横纵合并continuation、不改宽度/段落、ZIP非document parts字节对照、set/clear/无trPr/自闭trPr/省略rule、未知重复嵌套height）。追加trPr未知attrs/隐藏height/orphan拒绝与opaque段落控制通过 `/tmp/row-height-bridge-final-green.log`；限定core/bridge/tests类型检查零错误 `/tmp/row-height-types.log`。尚未以本模块证据宣布UI、collector/replay、服务端入口/保护/节预算或浏览器完成；root与host agent继续集成。本轮未改edit-docx/operations/UI/Python，未跑完整测试或生产build。

## root 入口集成进行中

`setTableRowHeights` 已接 Python whitelist、来源 inspect、hash/保护校验、所属节正文高度上限、同表/同节页面设置混批拒绝、原始 XML 保存及实际产物回读；metadata恢复包含此操作。前端 collector/replay 接受同一严格步骤及完整投影对照，按 rowHeightSectionId 拒绝依赖不确定的页面设置/分节草稿。

Python 定向先在缺 capability 处 RED `/tmp/word-row-height-python-red.log`；新增六项首跑五项通过，保存项仅 ZIP 目录 entry 的集合断言失败，过滤目录、保留所有实际部件严格字节对照后仅重跑该项通过 `/tmp/word-row-height-python-save-green.log`。已通过实际指定600保exact/新增atLeast/clear、原段落身份、非目标部件、非法字段/行带、实际第二节9000上限及伪造max/同节布局混编拒绝。额外保护/伪造hash一项通过 `/tmp/word-row-height-protection-green.log`；前端节依赖一项 `/tmp/word-row-height-section-contract.log` 通过。bridge `/tmp/word-row-height-bridge-build.log` exit0，是auto/零高度补充前版本；最终需重建并真实浏览器验收。

独立复核发现空hRule应拒绝，以及合法auto/零高度来源仍未覆盖，正在真实源探针与定向修复，不以只读边界代替最终支持。UI及built尚未验收，全量目标开放。

### 合法 auto/零高度来源补齐与空规则修复

后续窄复核发现 `declared &&` 将显式空 `w:hRule=""` 当省略放行，新增空规则向量先RED后改为“属性存在但非法即拒绝”。未知非空规则继续readonly。合法 `auto` 与零高度不再永久只读：`/tmp/row-height-auto-source-probe.ts` 直接固定源parse→PM→机械来源指定/clear→实际DOCX保存回读，证据 `/tmp/row-height-auto-source-results.jsonl`：auto300有效高度300/rule atLeast；auto0及省略rule0有效高度/rule均null；三者指定600后固定源实际写600/atLeast。正auto清除移除height；零高度clear因源PM前后相同而走original原XML保留，这是源无显式clear意图导致的no-op，并非零height不能安全删除。

本地bridge按明确受控clear协议删除直属height，保留其他XML；未选中行auto/0原字节不动。set已存在auto或零height时外科改val并将rule改/增为atLeast，保留其余属性引号/空白；正height既有exact/atLeast/省略rule仍沿前约定保留。core不变，baseline capability归一化与源parse一致，UI agent已同步。追加2专属向量先RED `/tmp/row-height-auto-red.log` 后GREEN `/tmp/row-height-auto-green.log`，涵盖empty rule拒绝、auto300/auto0/省略0的签发、set/clear、未选行raw保留及实际保存回读；限定类型检查 `/tmp/row-height-auto-types.log`。未重跑已有绿测试，入口统一重建由root执行。
