# Word 表格 AutoFit 三入口调查

2026-11-10。初始只读调查完成后，经root确认新增独立core/bridge与定向测试；没有生产构建或完整测试。下文调查阶段现状保留为来源事实，当前实现证据见末节。均分行高的UI/built/下载验收是上一项独立工作，本调查不代表其验收完成；其core/bridge已冻结的状态与未验收入口范围见 `NATIVE_WORD_DISTRIBUTE_ROW_HEIGHT_DESIGN.md` 及root最终集成结果。

## 当前结论

本地有“根据内容自动调整 / 根据窗口自动调整 / 固定列宽”三个 Ribbon 控件，但没有可保存的命令链路。显示、解析和生成器底层已有 AutoFit 能力；不能据此标记入口已实现。固定源命令可直接抽取复用，但固定源整表 SavePlan 会重建段落并丢失源XML属性，不能作为本地原文件无损保存方案。

三个入口应作为一个完整工作包：同一个有序模式协议、源命令PM投影、可信节宽、网格与物理单元格宽度的手术式补丁、草稿/undo/redo/保存重开，覆盖 fixed/auto/pct 既有表，而不是只让固定表进入 AutoFit 后无法再切回。

## 本地与固定源定位

固定源仓库 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 层次 | 当前本地 | 固定源与可复用内容 |
|---|---|---|
| Ribbon | `frontend/src/docx-ribbon.ts:105` 三action已列出 | `components/Ribbon.tsx:3298` 三选项，调用 `setTableAutoFit(mode, sectionContentWidthPx)` |
| 宿主命令 | `docx-tables.ts:137` 只有行列增删的TABLE_ACTIONS；AutoFit无特判，reason返回“此表格命令尚未接入” | `editor/table-properties.ts:65` 纯PM Command；当前vendor没有此文件，可精确迁入所需闭包 |
| PM解析/显示 | vendor convert/extensions已有 `tblAutoFit`、`tblAutoFitEdited`、widthPx/widthPct/colWidthsPct、cell.colwidth 和 AutoFit CSS | 保留现有渲染器，不新造DOM测宽算法 |
| 保存协议 | `docx_native.py` allowlist与 `docx-operations.ts` 无AutoFit操作；直接改tblAutoFit不能成为合法保存意图 | source SavePlan整表XML生成有AutoFit，但非本地无损合同 |
| 已有列宽编辑 | `docx-table-column-width*` bridge要求明确fixed+dxa且tblW/grid/tcW一致 | 可以借用XML定位/span验证思路，不能原封复用来源门禁，否则auto/pct与缺tcW来源永远不可编辑 |
| 新表 | `docx-new-table.ts` 已生成window AutoFit新表 | 新表尚未保存时只能编辑允许的纯文字，不能误开AutoFit并破坏新表投影边界 |

来源身份：`table-properties.ts` SHA256 `bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f`；`packages/docx-engine/src/generate.ts` SHA256 `a339c97330a1551f3ca657f96b5abfd6d41473f9bdabddade3d62208be74e624`。重复标题行现已记录前者来源，但未整体迁入该文件；新闭包仍须登记 SOURCE-SHA256 / LOCAL-SHA256 与 SOURCE.md。

## 三种模式的真实语义

`setTableAutoFit` 先定位所在 `docTable`（选择任意单元格仍改整表）。Ribbon先 `enterSelectedTable` 支持表节点选择。没有DOM布局等待、字体等待或缩放读取；“固定”并不测浏览器当前实际列宽。

- **contents**：设置 `tblAutoFit='contents'` 与 Edited；清除 table.widthPx、widthPct、colWidthsPct，并把所有后代docTableCell/docTableHeader的colwidth清为null。
- **window**：设置mode/Edited、widthPx=null、widthPct=100；不主动清除colWidthsPct和cell.colwidth。因此从fixed直接window与先contents再window的内部状态/保存网格并不相同。
- **fixed**：`fixedGridWidths` 优先拼接首行cell.colwidth，数量等于逻辑列数且全>0就采用；否则按table.colWidthsPct及contentWidthPx生成 `max(24, round(pct/total*contentWidthPx))`；再否则等分 `max(24,floor(contentWidthPx/columnCount))`。设widthPx=sum、widthPct=null、colWidthsPct=比例，并按TableMap范围写cell.colwidth。source对无法定位的后代单元格catch后继续，宿主应先验证合法网格，不能把异常静默当完整成功。

窗口模式CSS以当前节**文本栏**为100%，不是浏览器窗口宽度。源Ribbon给fixed fallback的参数却是 `(pageWidth-marginLeft-marginRight)/15`（无section为624px）；现有来源代码未在此处扣多栏栏间距。若本地只支持可信单栏预算，应明确多栏只读原因；不能用 `clientWidth` 或显示zoom代替节宽，也不能宣称已复刻多栏全部语义。

生成器 `generateTableModelXml`：contents写 `tblW=0/auto` + `tblLayout=autofit`；window写 `5000/pct` + autofit；fixed写网格总宽/dxa + fixed。网格优先model.colWidthsTwips，否则按model.colWidthsPct（缺失则等分）分配到默认9360twip；所有物理tcW按对应网格和写成dxa。

## 已执行真实源码探针

`/tmp/word-autofit-investigation/probe.ts`：真实 `buildDocx → parseDocx → tableModelToPmNode → PM EditorState/TextSelection → setTableAutoFit → pmDocToSavePlan → saveDocx → parseDocx`；使用固定源真实函数，不仿写命令。最小schema按解析JSON采集attrs/marks，并明确添加 `tblAutoFitEdited`。这是无浏览器的真实DOCX/源算法/保存探针，不是built GUI验收。

```sh
node /tmp/word-autofit-investigation/build.mjs
node /tmp/word-autofit-investigation/probe.mjs > /tmp/word-autofit-investigation/results.jsonl
AUTOFIT_SOURCE=window node /tmp/word-autofit-investigation/probe.mjs > /tmp/word-autofit-investigation/window-source-results.jsonl
AUTOFIT_SOURCE=contents node /tmp/word-autofit-investigation/probe.mjs > /tmp/word-autofit-investigation/contents-source-results.jsonl
```

三种原始来源（fixed dxa4000、100%pct autofit、auto0 autofit），每种执行独立三模式及连续 contents→window→fixed，共18向量。回读断言保存mode与PM mode一致；断言源段落rsidR消失，从而暴露非无损路径。fixture两个逻辑列 `[2000,2000]`，均有tcW、带bold/color/keepNext/hideMark和精确行高300；source转换器将2000twip取整为133px。

| 操作 | PM cell.colwidth | 保存后grid twip | tblW / layout |
|---|---|---|---|
| 直接contents | 全null | `[4680,4680]` | 0 auto / autofit |
| 直接window | 保留 `[133]` | `[1995,1995]` | 5000 pct / autofit |
| 直接fixed | `[133]` | `[1995,1995]` | 3990 dxa / fixed |
| contents→window | 仍null | `[4680,4680]` | 5000 pct / autofit |
| contents→window→fixed，contentWidth=600px | `[300]` | `[4500,4500]` | 9000 dxa / fixed |

三种来源得到上述相同行为。每次SavePlan均为`xml`整表生成；段落 `w:rsidR="00ABCDEF"` 丢失，精确行高仍存在。这证明不能把“模式写对”当作无损保存通过，也不能只补两个表属性就声称复刻source的完整宽度语义。源生成器等分到9360并不表示“按真实内容测得9360”；实际内容自适应由布局引擎/Word执行。

探针未覆盖缺tcW、缺grid、非100%pct、merge/continue、嵌套/浮动/修订、RTL、多栏、非正常字体或真实Word排版；这些必须保持待验证标记。此次不会运行完整source测试补足。

## 最小完整实现建议

### 一条可回放协议与共享源命令

新增独立操作（不混进仅fixed来源的resizeTableColumns）：

```ts
{ kind: 'setTableAutoFit', blockId, expectedObjectSha256,
  steps: [{ mode: 'contents' | 'window' | 'fixed' }, ...] }
```

每step严格1键、1–50步；不接受client widthPx、任意XML、最终网格、节宽或AutoFitEdited。表级 `nativeTableAutoFit:{steps}` 只记录意图。服务端从原文件表与节推导输入和预算。前后端复用精确迁入的 `selectedTable/fixedGridWidths/setTableAutoFit` 最小闭包，加薄的PM state选择适配；共享投影只改变源命令触及的attrs，不重建内容和marks。

按完整序列回放，不折叠成最后mode：前面的contents清除colwidth会影响后面的window/fixed。必须保存draft、恢复、undo/redo、重复点击、保存再开并能继续三模式转换。与同表行高、结构、合并拆分、列宽、文字/格式的并发意图若暂不支持，沿用现有“先保存”清晰边界，不能把它们吞进整表重建。

### 双层宽度：显示PM与写入OOXML

保存网格必须有明确共享投影，不能只靠本地浏览器最后attrs或让client提交可信网格。可从source `pmTableToModel` 的首行宽度/比例回退闭包和generateTableModelXml的网格算法精确摘录所需纯函数，按原source默认9360与真实有序mode状态生成输出，bridge只消费这一可信输出。

有一个实施前需明确的精度选择：固定source转换已把2000变成1995；本地既有列宽链路以可信整数twip归一化保持未编辑列精度。建议延续本地整数精度约定，使不要求改变网格的window/direct fixed不无谓损失5twip，并在共享core、调查与测试明确这一局部适配；不能同时声称逐字复刻source的像素取整输出。contents清空网格意图后的9360默认回退及后续fixed节宽回退仍须按source完整回放。若选择绝对source输出，则应明确测试1995而非偷偷保留2000。此选择不能在UI与bridge各自决定。

### 无损 bridge 与可编辑范围

独立AutoFit来源检查至少能接受完整合法网格的fixed/dxa、auto、pct表及缺tcW；否则用户切出fixed保存后就无法切回。检查重复/嵌套几何标签、未知几何attrs、修订、歧义grid/span、预算限制和表/节身份。已有列宽桥接的固定dxa一致性限制不能直接作为AutoFit availability。

目标补丁仅作用于**目标表直属**：tblPr/tblW、tblPr/tblLayout、tblGrid/gridCol及各物理tc/tcPr/tcW。必要时插入缺失容器/标签，遵循OOXML顺序。保存仍按源生成器写dxa tcW；横合并宽度为网格范围和，纵合并continue的隐藏内容与独立tcPr原样保留，不把PM省略的continue单元格删掉。段落、run、绘图、嵌套表、表格样式、边框/间距/底色、行属性及zip非document.xml部分逐字保留；嵌套表的同名width标签不可被正则扫到。复杂内容可opaque保留，不应因文本有marks就拒绝。

缺grid需要推导可验证逻辑列，本次探针尚未覆盖；可以第一批明确只读，不可宣称全量来源支持。缺tcW只影响补丁插入并可从可信grid推导，不宜永久只读。float/bidi/多栏/位置/修订若尚未有可信几何边界，明确只读而非悄悄使用单栏总宽；这些均需单列能力范围，不冒称完整Word覆盖。

回读验证实际文件表mode、grid、每个物理tcW、逻辑cell范围与预期一致，同时对非目标XML/zip部件做精确保留断言；不能只读parse后的autoFit值通过。

## 实施后必须补的定向验收（未执行）

1. RED/GREEN：三入口从真实表格光标/CellSelection/表节点选择启用；无表/只读/新表待保存禁用；同表冲突明确。三个来源模式互相转换和多步回放，不只最后mode。
2. core/bridge：不等列/奇数twip、缺tcW、auto/0/pct与非100%pct、无tblLayout、合法横纵合并及复杂continue；unknown字段/伪XML/错hash/非法span/节宽冲突拒绝。缺grid、float/bidi、多栏等按最终范围逐项声明。
3. 原XML与zip保留、段落rsid/marks/多段/图片/嵌套内容不变；避免探针已暴露的整表重生成损失。
4. 实际built HTTP保存下载：UI mode和真实CSS变化、草稿刷新、undo/redo、连续切换、保存下载回读、重开再次切换；不同zoom不影响模式/可信几何。无需新增DOM测量与fonts/images等待。
5. 页面设置先改后AutoFit及逆序的确定规则；节预算变化不让前后端投影漂移。仅执行定向合约/必要built smoke，不重复完整测试。

当前只完成调查与18个固定源码探针，不包含AutoFit实现或均分行高验收结论。

## 独立 core/bridge 当前实现（2026-11-10）

新增 `frontend/src/docx-table-autofit-core.ts`、`slides_engine/bridge/docx-table-autofit.ts` 及各自定向测试；未修改edit-docx、UI、operations、Python。外层集成与built/HTTP下载不属于此子任务完成声明，仍由root验收。均分行高不因本项完成而视为已验收。

API:

```ts
applyTableAutoFitSteps(table, widthsTwips, contentWidthTwips, steps)
// => {table, mode, widthsTwips}
tableAutoFitAvailability(block, contentWidthTwips)
// => autoFitEditable, autoFitReadOnlyReason, autoFitMode,
//    autoFitWidthType, autoFitWidthValue, autoFitWidthsTwips,
//    autoFitContentWidthTwips, autoFitCells
editTableAutoFit(block, contentWidthTwips, steps)
// => {xml, mode, widthsTwips, cells, contentWidthTwips}
verifyTableAutoFitResult(block, result)
```

steps严格 `{mode:'contents'|'window'|'fixed'}`、1–50步。cells沿用logical rectangle + physicalRow/physicalColumn。source raw tblW/layout独立计算effective mode并要求与解析模型一致，auto/pct仅是原XML宽类型，不冒充mode。可信正文宽由集成人员从表所属单栏节签发；桥接不提供客户端覆写方式。

来源归属：core中 `fixedGridWidths` 是固定源table-properties.ts完整同名闭包逐字摘录（原文件SHA在上文和代码注释）。其余代码是源 `setTableAutoFit` 三分支的宿主纯投影与源 `pmTableToModel/generateTableModelXml` 保存宽度回退的等效实现，**不声称整个source command原样迁入**。明确局部适配为初始合法grid→cell.colwidth=/15，保整数2000/2001；source会取整为1995等。之后contents清空状态、window保留状态、fixed优先已有显式宽/缺失时source节宽fallback，按完整顺序执行；内容/marks与其他attrs保留。非法网格不使用source的catch跳过单格，而整体拒绝。

独立来源能力覆盖已有正整数grid、fixed/dxa、auto、pct（含非100%）、省略tblW/layout、缺tcPr/tcW、横纵合并与复杂continue；嵌套表内容opaque保留。没有grid、浮动、bidi、网格占位、修订、歧义/重复/未知几何属性、超100行/30列/1000槽或31680twip模型预算只读；多栏由上层可信节适用性拒绝。宽度只接受当前模型支持的数字值（不含字面“50%”）。此能力独立于columnWidthEditable。

补丁保留已有width标签引号/空白，只改w:w/w:type值；缺失标签/容器按顺序插入。只触目标表直属tblW、layout、gridCol和每个物理tcW，包含vMerge continue；嵌套表width不变。回读检查完整actual originalXml、effective mode、真实tblW/type/layout、grid、物理tcW及logical cells，不能以parse mode单点冒充。

验证证据：`/tmp/autofit-core-red.log` 先因缺模块失败，`/tmp/autofit-core-green.log` 3例通过；`/tmp/autofit-bridge-red.log` 先因缺模块失败，`/tmp/autofit-bridge-green.log` 4个真实DOCX用例通过。额外发现同位置缺tblW/layout插入顺序倒置，新增测试 `/tmp/autofit-insert-red.log` 失败后修复，`/tmp/autofit-insert-green.log` 通过；effective mode独立校验 `/tmp/autofit-mode-green.log` 通过。最后回读校验增强后的受影响3例 `/tmp/autofit-final-verification-green.log` 通过；限定TypeScript检查 `/tmp/autofit-types.log` 零错误。没有重复完整套件或生产构建。真实保存覆盖三模式/有序链、2000/2001精度、缺宽度、缺容器、复杂合并continue、嵌套表、段落rsid/富文本与zip非document.xml部件保留，以及不合法来源/step/结果拒绝。

raw mode边界额外与固定源parse真实回读核对：`tblW nil/0`、`pct/0`、`pct/7500`（150%）且无fixed layout都被source解析为fixed，因为有效widthPct仅接受(0,100]%，且nil不属于source autoWidth；`dxa/0`且无fixed layout为contents。bridge逐字遵循这套判定，不把所有pct都当window/contents。定向证据 `/tmp/autofit-raw-width-green.log`；scope tsc仍零错误。字面百分比值（如`50%`）source另有支持，但本地独立桥接当前数字宽度模型未覆盖，显式只读。
