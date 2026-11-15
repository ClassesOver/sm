# Word 整表对齐与左缩进调查

2026-11-10。只新增本文及 `/tmp/word-table-alignment-investigation` 探针；不实现生产、不改AUDIT、不重建产品。固定来源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。这里的整表对齐与已交付的单元格九宫格/段落对齐不同。

## 结论及本地缺口

来源 TablePropertiesDialog Table页有 left/center/right 整表对齐，**没有左缩进输入控件**。`tableValueOf`仅读取tblAlign，`applyTableValue(... touched align)`仅调用真实updateSelectedTableAttrs写tblAlign。不能把读取/渲染tblInd的能力当作来源已闭环的左缩进编辑：本轮真实调用通用命令写indentTwips=901，PM发生变化，但保存重开仍是原333/-109或null；converter既未将indent写入保存model，其structure signature也不包含indentTwips。

本地 `docx-tables.ts` 的table-properties当前只打开已交付单元格边距覆盖框；没有整表alignment/indent专用cap、project或操作。将本轮真实来源PM改动交给当前真实`docxOperations`，有数值变化的tblAlign和indent均报“暂不支持修改表格布局”。“accepted”仅出现与原tblAlign完全相同的no-op，得到空操作，不证明已支持保存。后续优先交付来源确有闭环的**整表对齐**；indent需作为明确新增的本地扩展单独获准，不能伪称复刻来源UI。

## 来源路径与语义

- `components/TablePropertiesDialog.tsx:58` tableValueOf将center/right映射同名，其余/null回退left；`:86` applyTableValue align组写`patch.tblAlign=value.align`。
- `editor/table-properties.ts:25` updateSelectedTableAttrs定位selectedRect所属整表并合并attrs，caret/矩形均只是定位同一表；bare NodeSelection拒绝，enterSelectedTable后可改整表。
- `editor/convert.ts:1306/1326` 输出tblAlign=model.align??null，浮动表通常将indentTwips置null，inline保留model indent；`:1499` signature含tblAlign但不含indent；`:1960` 保存align有值时显式传递，null保留raw jc，left表示删除jc。保存model没有从现有PM读取indentTwips的赋值。
- `packages/docx-engine/src/parse.ts:5535` tblInd仅无type/dxa按Number读取，非零有限值保留（允许负值）；pct/auto等不产生effective indent。`:5631` raw jc center→center，right或end→right，其余包括left/start→undefined；没有按bidiVisual交换start/end。
- `generate.ts:2841` align显式left移除jc，center/right写规范selfclosing jc；paired jc可正确被setTblPrChild替换/移除。`:2755`新生成表支持model.indentTwips，不能替代现有PM保存链缺失。

固定来源hash沿前两个调查：TablePropertiesDialog `45eaefe31e49748964b959957fa8550e402326b86c056266b4ea4737f52d2036`，table-properties `bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f`，convert `7b05f77cd9d6a4859ad51993170d22252f9798c0dc62dddb726b6b99be8781fa`，generate `a339c97330a1551f3ca657f96b5abfd6d41473f9bdabddade3d62208be74e624`。

## 真实来源命令与保存

实际链路：buildDocx→parseDocx→真实tableModelToPmNode→PM选择→真实tableValueOf/applyTableValue或updateSelectedTableAttrs→pmDocToSavePlan→saveDocx→parseDocx/converter。独立/tmp probe bundle不是产品构建。最小schema保留converter输出attrs/marks，不证明实际浏览器布局。

```sh
node /tmp/word-table-alignment-investigation/build.mjs
# 每mode执行left/center/right、indent-direct、bare-node、entered-node
for mode in inline rtl-start rtl-end floating paired pct-ind negative pct-width style; do
  ALIGN_MODE="$mode" node /tmp/word-table-alignment-investigation/probe.mjs > "/tmp/word-table-alignment-investigation/$mode.jsonl"
done
```

共9模式×6尝试=54次，其中bare-node9次拒绝；45次accepted并保存。indent-direct9次只是调用真实通用属性命令，明确不属于不存在的缩进UI。全部source/输出DOCX保留。Python ZipFile/ElementTree独立核对word/document.xml的jc/tblInd/tblW/grid，结果`zip-xml-verification.json`。只统计上述九个具名JSONL，不把同目录其他旧调查文件计入本轮。

| 原始向量 | parse/PM | 真实align保存重开 |
|---|---|---|
| inline jc=center，tblInd333/dxa，tblW4000/dxa | center、333 | left删jc后PM=null；center/right写规范jc；tblInd333与tblW4000原样保留 |
| bidiVisual+jc=start | align=null、indent333；dialog显示left | left删start，重开null；right写right；不改bidiVisual，不交换字段 |
| bidiVisual+jc=end | align=right、indent333 | left删end；center/right规范化值；raw end与effective right需分开 |
| floating tblpPr X777/Y111+center+indent333 | model indent333，PM indent=null；float left | 改jc成功但tblpPr保持、PM indent仍null；不能据此声称视觉位置改变 |
| paired jc=end与paired tblInd333 | right/333 | paired jc被正确删除/替换；paired tblInd原样保留 |
| tblInd1250/pct | indent=null | 改对齐保留raw pct标签，不能把null当无raw或零 |
| tblInd-109，无type | indent=-109 | 改对齐保留符号与缺type原写法 |
| tblW2500/pct | widthPct50，widthPx=null | 改对齐不改tblW/百分比；indent333保留 |
| raw无jc，table style jc=right/indent71 | PM align=null，direct indent333 | 当前parser不合入该style jc；left删jc后仍null，不能声称Word所有style继承一致 |

source左对齐命令的PM临时值left，重开值null，前端确定性投影需按重开语义/专用intent区分。零tblInd在parser中折叠为缺省，raw空缺、raw0、非dxa导致effective null不是同一来源状态。

**缩进direct向量**：9模式均命令PM indent901，但保存重开仍原值。尤其inline raw333仍333且rsid保留，证明并非保存后被Word另算，而是该属性变化未进入save plan。不能先只加一个输入框再认为闭环完成。

source整体serializer改align时仍出现原段落rsid丢失、grid2001/1999→1995/1995、插入tblLook等副作用；它们不属于对齐意图，应采用局部jc补丁保真。no-op center可能仍dispatch但save plan保原表，和真实值变化要分别报告。

另3个明确标为**parser-reference-only**实验只替换原XML直属tblInd为901/dxa，调用真实xml模式saveDocx+reparse（paired、pct-width、floating）：paired和pct-width的model/PM读到901，raw jc别名、tblW/百分比、rsid原样保留；floating model901但PM仍null。文件`parser-reference-{mode}-indent.docx`。这证明局部XML缩进写入可被parser读取，不等于来源编辑控件/保存功能已存在。

## raw、effective 与 RTL

信任快照至少分开 raw直属jc标签及val、raw直属tblInd及unit/数值、parser align/indent、PM attrs、bidiVisual、float原始/抑制状态、raw tblW/实际grid。不能从PM null反推删除某层，也不能把别名end等同原文right而无操作就重写。

`editor/table-geometry.ts:127` rtlStartAligned只在body、bidiVisual、非浮动且align不是center/right时为true；`:227` tablePositionCss在该状态使用rtlStartMarginCss，从**右边**量indent。正333从右内缩，负109向右外悬；普通LTR left/null则margin-left。center/right不应用普通indent位置，但raw tblInd继续保留，切回start后会重新生效。因此来源UI名为left的动作在bidiVisual表格中实为清除jc后“起始侧”，不能以“物理左对齐”误导用户。

raw start→null/默认起始与raw end→right是当前reader映射；不能套用段落effectiveBidi/alignAttrFor，它们属于段落，不是整表。若产品要物理左/右或完整logical start/end，应作为不同设计调查真实Word并调整模型；本轮不默认改vendor映射。对齐首版可明确用“起始侧/居中/右对齐”或提示RTL来源语义，不能暗自交换raw jc。

## inline / floating 与宽度、缩进互作

`editor/extensions.ts:3162`明确tblpPr优先于jc/tblInd：真实浮动走tableFloatCss，抑制float又可能走suppressedFloatX分支；不能仅因PM tblFloat=null判断inline，还要查看tblFloatSource、tblFloatSuppressed及raw tblpPr。首版建议对raw浮动/抑制定位来源关闭“改变整表位置”能力并说明原因，保留原定位，而不是改jc后声称已移动；浮动的jc原数据可保真但应属独立操作范围。

`parse.ts:5488` usableTableWidths在pct/布局识别中考虑tblInd和legacy margin hang；`convert.ts:791`宽度适配区分leftAligned、signed indent、legacy compatibility14/15。改indent可能改变百分比/溢出布局识别和可用宽度；改align也可能显露/隐藏既有indent。不得顺手重算tblW/grid/tcW或调用AutoFit来“修复”位置。本轮4000dxa与50%两类source验证了保存raw宽度不变，但未覆盖所有sections/columns、legacy模式、负缩进与过宽百分比组合的真实DOM。应把这些列入布局验收，而非盲目绑定fixed-layout门禁。

## 严格协议与最小交付建议

建议先交付单一来源已闭环的对齐操作，不把左缩进捆入：

```json
{"kind":"setTableAlignment","blockId":"已签发表ID","expectedObjectSha256":"原表身份","alignment":"left"}
```

严格四字段、alignment仅left/center/right；作用整张表，caret/矩形定位同一表，NodeSelection显式全表包装。left沿来源删除直属jc（不是写left/start），保存重开PM=null；center/right写对应值。专用`nativeTableAlignment:{alignment}`；重复修改可只保最终值，不需要人为引入steps。其他同表意图首版互斥，collector核对完整确定性投影，草稿replay核对hash/strict keys。cap可用`tableAlignmentEditable/ReadOnlyReason/Source`，必须签发raw/effective jc、indent、width/float/RTL与几何，服务端从原包核验，不接受客户端XML或bidi声明。

左缩进若下一阶段单独获准，建议独立`setTableIndent`，`indentTwips`为有界带符号整数，明确0移除直属tblInd、非零写dxa；范围需按产品需求和Word探针确定，不能借用margin非负0..28350。对center/right可只保存潜在indent或要求先选start，需明确文案；不允许输入却看似无效果。该协议是本地新增扩展，不是source Table页现有控件。

局部bridge只补直属tblPr/jc（后续indent只补tblPr/tblInd），支持缺容器、自闭合和空成对元素，按照schema顺序jc在tblW后、tblCellSpacing/tblInd前；保留tblInd、tblW/grid/tcW、浮动定位、样式/行例外、未知sibling、hidden continuation与段落/ZIP原字节。目标重复/未知属性或内容、非法单位/无效整数、namespace歧义/修订、目标非同一直属容器应明确拒绝；非目标opaque原样保存，不能全表重建。start/end可读取并签发raw，不在no-op中规范化；首版无法证明RTL语义的来源应返回具体只读原因或明确语义提示。

验收需源向量对应的真实DOCX保存重开、局部XML与非目标parts保真、保护/hash/strict键/同表冲突、NodeSelection/merged定位、undo/redo/草稿、HTTP下载及真实浏览器box位置。布局需LTR/RTL、legacy14/15、正负indent、dxa/pct、窄栏/过宽表、真实/抑制floating及切回start；浮动关闭能力原因应可见。当前只完成源码/真实保存调查，不证明浏览器、下载或桌面Word一致性；不改报告发布非阻断契约。

## 随后授权的独立整表对齐实现（2026-11-10）

主任务随后明确授权整表对齐独立core/project/bridge及窄测试；左缩进仍不在本项实现。新增 `frontend/src/docx-table-alignment-core.ts`、`docx-table-alignment.ts`，导出 `TableAlignment`、`TableAlignmentSource`、`DocxTableAlignmentAnchor`、`projectDocxTableAlignment(source,anchor,alignment,schema)`。Source实际为 `{alignment:'center'|'right'|null,raw,rawIndent,rawWidth,bidiVisual,positioning:'inline'|'floating',cells:[{top,left,bottom,right}]}`。cap为 `tableAlignmentEditable/ReadOnlyReason/Source`，意图 `nativeTableAlignment:{alignment}`只保最终值，支持反复切换。left确定性投影null；其他attrs与全部content保持不变。collector/旧意图互斥和入口由root处理。

新增bridge同步接口 `tableAlignmentAvailability(block)`、`editTableAlignment(block,alignment)`、`verifyTableAlignmentResult(reopenedBlock,result)`；只定位/补删直属jc，实际XML与模型align、geometry、raw indent/width及RTL/positioning回读核对。missing/selfclosing tblPr能创建合法jc位置，paired jc整体处理；新jc在tblStyle/tblOverlap/bidiVisual/banding/tblW之后、tblCellSpacing/tblInd/borders等之前。其他来源XML和包部件保持原字节。

按本轮明确授权，floating来源不再采用上文调查阶段“首版关闭能力”的建议：cap仍editable=true、Source.positioning='floating'（raw tblpPr存在即视为定位来源，覆盖显示抑制场景），供UI提示浮动位置优先且本次未移动位置；jc依照真实source照常编辑，不修改tblpPr或清除浮动。raw start/end与effective值相同的no-op由UI保留原文，不因打开对话框而规范化；实际选择不同对齐后按来源规范值保存。style/RTL解释仍复用当前parser/renderer，不宣称桌面Word全部继承一致。

测试先有有效RED：前端3个行为失败、bridge3个行为失败（`/tmp/table-alignment-red.log`、`/tmp/table-alignment-bridge-red.log`）。随后前端3项通过（`/tmp/table-alignment-green.log`）；bridge定向测试覆盖paired/end、RTL、percent width、negative/zero/paired/opaque-unit indent、missing/selfclosing tblPr、schema前后继、style解析边界、hidden正文/非目标ZIP保真、floating可编辑且位置不变、空val/重复属性/未知jc/revision/namespace/畸形grid拒绝，结果见`/tmp/table-alignment-bridge-final-green.log`。独立production TypeScript检查通过，配置`/tmp/table-alignment-production-types.json`，日志`/tmp/table-alignment-production-types.log`为空、exit0。未在本子任务运行产品build或完整测试，主任务负责统一入口/UI/HTTP验收。
