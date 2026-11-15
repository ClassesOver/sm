# Word 表格行允许跨页断开调查

2026-11-10。本轮只新增本文和 `/tmp/word-row-page-break-investigation` 探针，不实现生产功能、不改共享audit、不构建产品、不提交。DOCX引擎位于 `reporting/doc_engine`。

## 选定缺口与范围

本次选定 TablePropertiesDialog **Row页“允许跨页断行”**，即行 `cantSplit` 的可编辑闭环。这是长报告表格分页的实际缺口：本地原生分页器已经消费该标记，但用户不能通过当前UI和严格保存链修改它。已有指定行高/均分行高专项只保留 `cantSplit`，不能视为本项已完成。本项不包含整表对齐、浮动环绕、左缩进或Cell noWrap，也不重复边距、宽度、AutoFit、单元格九宫格对齐与文字方向。

| 固定来源属性页 | 来源提供 | 本地当前证据与专项 |
|---|---|---|
| Table | AutoFit、整表left/center/right、浮动none/left/right与位置/距离、默认边距 | AutoFit/default margins已专项；对齐/浮动尚无对应保存操作。此来源Table页没有独立左缩进输入，不能据Word常识虚构来源能力 |
| Row | 高度与exact/atLeast、allowBreak、首行repeatHeader | 高度/分布/repeat header已有实现；allowBreak未接，现有专项明确保留cantSplit |
| Column | 选中列宽、前/后一列 | 宽度已有专项，本轮不重复 |
| Cell | 列宽、垂直对齐、覆盖边距/恢复继承、wrap→noWrap | 宽度/对齐/边距已有专项，noWrap另属未接能力，本轮不扩展 |

本地 `docx-tables.ts:528/531` 的 `table-properties` 实际路由至 marginOverridesTarget/Dialog，展示的是单元格边距子集，并非来源四页完整属性框。搜索现有前端命令、operations、bridge与Python操作白名单，没有行跨页专用操作。更直接的运行证据：将真实来源 `rowPatchFor→setRowProps` 产生的PM改动交给**当前真实本地** `docxOperations`，24个accepted来源向量全部被“暂不支持修改表格布局”拒绝；因此缺口不止是缺一个checkbox。

相比另两个未接的Table布局候选，本项对多页业务报告的分页有直接影响，且能复用现有source分页器和row定位/局部XML补丁，适合作为下一项独立闭环。不为此改造整个TablePropertiesDialog。

## 不可变来源

仓库 `/home/junge/pros/genoffice-source-full`，固定ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 相对来源文件 | SHA256 |
|---|---|
| `apps/docs/src/renderer/components/TablePropertiesDialog.tsx` | `45eaefe31e49748964b959957fa8550e402326b86c056266b4ea4737f52d2036` |
| `apps/docs/src/renderer/editor/table-ops.ts` | `d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd` |
| `apps/docs/src/renderer/editor/convert.ts` | `7b05f77cd9d6a4859ad51993170d22252f9798c0dc62dddb726b6b99be8781fa` |
| `packages/docx-engine/src/generate.ts` | `a339c97330a1551f3ca657f96b5abfd6d41473f9bdabddade3d62208be74e624` |

真实来源语义：

- `TablePropertiesDialog.tsx:219` selectionOf 取selectedRect第一行，`allowBreak:!rowNode.attrs.cantSplit`。多行混合状态的source UI只读首行，不能据此宣称全选状态一致。
- `:176` rowPatchFor 仅当allowBreak touched时写 `{cantSplit:!allowBreak,cantSplitEdited:true}`，不触碰height/header。commitRow调用真实setRowProps。其firstRow参数只影响repeatHeader，与allowBreak无关。
- `table-ops.ts:747` setRowProps 在 `selectedRect.top<=rowIndex<bottom` 的**每一整行**合并patch，不以所选列限制作用。bare整表NodeSelection在表外，命令拒绝；宿主可先enterSelectedTable转为全表CellSelection。
- `convert.ts:1350` PM row从model.rowCantSplit读取布尔值，缺省false；`:1670` 仅cantSplitEdited或新表把显式bool传给保存model，否则null保留原trPr。
- `generate.ts:2728` true写 `<w:cantSplit/>`，false移除该声明；插入在trHeight/tblHeader之前。`parse.ts:5759` 逐行boolProp读取，`:5830` 任一true才保留model数组。`xml-utils.ts:80` 缺节点=false，存在无val=true，val的0/false/none/off（忽略大小写）为false，其他字符串被宽松视为true。本地严格编辑不应把宽松reader当任意值都安全的依据。

## 真实命令与DOCX保存证据

探针直接导入固定来源 `rowPatchFor/setRowProps/enterSelectedTable/tableModelToPmNode/pmDocToSavePlan`，链路为实际ZIP buildDocx→parseDocx→converter→PM选择→真实命令→SavePlan→saveDocx→parseDocx/converter。没有仿写命令冒充source。每向量从原文件单独开始。

```sh
node /tmp/word-row-page-break-investigation/build.mjs
node /tmp/word-row-page-break-investigation/probe.mjs > /tmp/word-row-page-break-investigation/normal.jsonl
ROW_MODE=merged node /tmp/word-row-page-break-investigation/probe.mjs > /tmp/word-row-page-break-investigation/merged.jsonl
ROW_MODE=rtl node /tmp/word-row-page-break-investigation/probe.mjs > /tmp/word-row-page-break-investigation/rtl.jsonl
ROW_MODE=paired node /tmp/word-row-page-break-investigation/probe.mjs > /tmp/word-row-page-break-investigation/paired.jsonl
```

这是/tmp独立probe bundle，不是产品构建。4模式×7命令尝试，共28次；每模式bare-node拒绝，实际accepted并保存24次。`source-{mode}.docx`及各输出DOCX、JSONL保留。另用Python标准ZipFile/ElementTree读取真实word/document.xml，结果 `/tmp/word-row-page-break-investigation/zip-xml-verification.json`，核对节点数、正文、段落rsid，避免只检查PM。

Fixture：3行×2列，grid2001/1999；原row0 cantSplit=true、300/exact、tblHeader，row1显式cantSplit val0、337/atLeast，row2无cantSplit、374/atLeast。所有行保有unknown sibling，格含noWrap/tbRl，段落rsidR/keepNext/粗体文字。表样式另带trPr/cantSplit，但来源parser仍将无直属标记的row2解释为false；这只证明当前来源解析边界，不能声称Word完整样式继承一致。merged模式前两行首列vMerge restart/continue，continue含独立hidden文字；rtl模式bidiVisual；paired模式row0改为合法成对cantSplit元素。

| 普通/RTL向量 | 命令后cantSplit | 保存重开 |
|---|---|---|
| 首行caret allow=true | `[false,false,false]` | row0节点移除；row1显式val0保持；其他trPr属性不变 |
| 最后行caret allow=false | `[true,false,true]` | 仅row2新增cantSplit，插在trHeight之前 |
| 前2行矩形 allow=false | `[true,true,false]` | row1 val0变无val的true节点，row0true保持 |
| 前2行矩形 allow=true | `[false,false,false]` | 前两行cantSplit都移除；height/header/unknown保持 |
| bare NodeSelection | 拒绝、PM未变 | 无保存结果 |
| enterSelectedTable后 allow=true | `[false,false,false]` | 全3行清除cantSplit |
| 单行下方slot allow=false | `[true,true,false]` | 仅row1被设true，整行生效 |

RTL结果与普通一致，不镜像行索引；allowBreak是布尔行为，没有twip或单位转换。PM `cantSplitEdited` 在命令后true、重开false，不能作为原文件声明是否存在的证据。

### 合并选择的行范围

merged首列owner跨row0/row1。首格caret与下层continuation slot选择均经PM owner映射，selectedRect为 `{top:0,bottom:2,left:0,right:1}`，所以setRowProps修改两行。不能将UI点击的下层物理行误当只改row1，也不能复制cell override的“给一个owner所有physical tcMar传播”算法：本项最终目标是selectedRect行带中的直属trPr，所选列只用于确定行带。

普通caret在row0只改row0；多行矩形无论覆盖一列或多列，都应影响这些完整行。真正实现时应复用来源selectedRect（含合并闭包），NodeSelection需显式全表语义，前后行按钮若加入应沿来源moveCaretInTable，不另造物理行定位规则。

### 成对cantSplit的source保存缺陷

paired原row0 `<w:cantSplit></w:cantSplit>` 在parse阶段为true。真实allow=true命令使PM=false，但source generator只用删除自闭合节点的正则，成对节点仍留在输出，重开又变true。前两行prevent写true时，原成对节点未删又追加 `<w:cantSplit/>`，输出产生两个直属cantSplit。该问题在 `paired-caret-allow.docx`、`paired-rectangle-prevent.docx` 与paired.jsonl中有实际证据。

本地应支持合法空成对元素的完整替换/移除，拒绝原本重复或内容异常的目标容器，不复制source regex缺陷。设allow=true表示按来源清除直属cantSplit，而不是写val0；当前来源parser未解析表样式trPr/cantSplit，遇实际行样式继承歧义应单独陈述能力边界，不能以parser成功就宣称Word继承一致。首版可对确有未解析cantSplit样式声明的来源保守只读，并返回具体原因；普通style存在本身不是拒绝理由。

### 整表重生成的副作用与局部参考

所有source操作重生成表格，原段落rsid丢失，grid2001/1999量化为1995/1995；merged隐藏continue文字消失。即使仅修改最后一行，前面合并continue仍受整体重建影响。这些是source serializer副作用，不属于行跨页命令应复制的行为。

额外两个**parser-reference-only**（非source命令）实验仅在原XML移除首行直属cantSplit，调用真实saveDocx的xml模式并重parse：`parser-reference-paired-allow-first.docx`重开row0=false且不再有成对残留；`parser-reference-merged-allow-first.docx`保留hidden、每行2个原rsid段落及其他原字节。它们证明局部补丁+真实重读的参考可行，不是生产patch实现或浏览器分页验收。

## 严格协议建议

新增独立 `setTableRowBreaks`，不在现有行高协议里塞可选字段：

```json
{
  "kind": "setTableRowBreaks",
  "blockId": "已签发表格ID",
  "expectedObjectSha256": "原始对象身份摘要",
  "steps": [
    {"top": 0, "bottom": 2, "allowBreak": false},
    {"top": 1, "bottom": 2, "allowBreak": true}
  ]
}
```

严格顶层/step键集合；steps为1..50条；top/bottom为零起始logical row半开范围整数，`0<=top<bottom<=真实行数`；allowBreak必须JSON boolean，拒绝字符串、数字、null、缺失字段、额外字段。无left/right参数，因为最终操作是整行，不能让客户端误报列索引改变作用域。UI先按来源selectedRect确定行范围，协议不接受client自报rowXml或effective cantSplit。

按steps顺序回放，重叠后写覆盖，全部校验成功后一次保存；false→加/替换为一个true cantSplit，true→删该节点，不更改height/rule/header。首版同表与其他布局/结构/内容意图互斥；其他表及独立页面设置无需无依据冲突。cap建议 `tableRowBreaksEditable/ReadOnlyReason/Source`，Source至少 `{rows:[{cantSplit:boolean,raw:string|null}]}` 加已验证行几何；raw仅用于来源/保真核对，不接受客户端XML写回。原缺失、显式false、true、空成对元素分别记录，未选行原字节保留。

project只修改选中row.cantSplit，专用 `nativeTableRowBreaks:{steps}`承载有序意图；可沿来源设置cantSplitEdited用于PM兼容，但本地保存不得借该标志开启通用表重建权限。重复调用追加steps，并从原来源回放验证当前值；collector完整比较确定性投影以拒绝同表文字/其他attrs夹带；草稿replay核对hash、strict keys和同表互斥。mixed多选应展示多个值，用户明确选择“允许”或“不允许”，不因source首行初值默默覆盖全选。

## 最小实现与验证建议

1. 新独立core/project复用PM selectedRect/共享owner几何，不写新布局算法；front UI仅增加Row页“允许跨页断行”小节，明确范围，不把现有边距对话框冒称完整TableProperties。打开对话框冻结来源doc/selection，提交时验证未过期；cancel无修改，undo/redo、草稿恢复重放同steps。
2. 新bridge复用已有XML分层定位与直属row索引，校验原包hash/保护/表身份/行数/几何。仅补/删直属trPr/cantSplit；支持缺trPr、自闭合trPr、空成对cantSplit，true按CT_TrPr顺序放在trHeight/tblHeader之前，false后空trPr可保容器避免无关字节改动。保留unknown sibling、row属性、tblPrEx、height/header、全部tc/隐藏段落/nested表/图片、ZIP其他部分和metadata。
3. 目标重复cantSplit/重复trPr、未知目标属性或内容、非法val、namespace歧义及属性修订不能静默归一化，应给明确只读原因；先保证hMerge/gridGap等共享保守边界，不为“不改格网”就跳过来源几何核验。非目标opaque内容不能无依据扩大只读。
4. 保存后在实际原包上下文parse核对每行cantSplit与有序step结果、实际直属节点数量和schema插入顺序、原XML除目标子树外一致；验证必须读取真实输出，不能只验证命令PM。只需该专项定向测试及统一built smoke，不重复完整测试。
5. 浏览器分页必须形成独立闭环：现有vendor `editor/extensions.ts:3294`已有cantSplit/cantSplitEdited属性，renderHTML输出data-cant-split；`pagination-lines.ts:791` overlayLiveRowFlags刷新缓存，`pagination-slices.ts:2256`按标记切行或整体移页。应复用它们，检查切换后缓存立即更新、内容不丢、页数/切分位置改变；不另写分页器。
6. 真实浏览器场景需含接近页尾的多行文字行、允许/禁止跨页两态、header/exact/atLeast、纵合并、RTL、竖排、nested表与超整页长行。注意现有source明确对超页header/cantSplit行采用拆分而非Word溢出裁切，不能承诺“禁止”在超页长行时永不拆；该边界应作为具体警告而非阻断报告产物下载。

本轮没有证明实际浏览器的行分页变化、HTTP下载、undo/redo或Word桌面一致性；也没有实现上述协议。下一步可按此范围实施独立行跨页意图，不能把本调查计入完整属性页或完整Word表格已交付。

## 随后授权的独立模块实现（2026-11-10）

主任务随后授权独立core/project/bridge及窄测试；上文“未实现”是调查阶段状态，不代表本节实施后仍无代码。共享入口、operations/Python及旧project互斥、UI/统一bundle由主任务与另一子任务负责，本节不声称它们已验收。

新增 `frontend/src/docx-table-row-breaks-core.ts` 与 `docx-table-row-breaks.ts`，导出 `TableRowBreakStep`、`TableRowBreakSource`、`DocxRowBreakAnchor` 与 `projectDocxRowBreaks`。实际Source为 `{cells:[{top,left,bottom,right}],rows:[{cantSplit:boolean,raw:string|null}]}`；cap采用 `rowBreakEditable/ReadOnlyReason/Source`。步骤严格三键，1..50条；重复调用project会追加pending steps并核对当前值等于原可信快照回放；其他同表native意图被拒绝。core只改整行cantSplit/cantSplitEdited，复用PM TableMap校验，不扩张协议行带，不改变row content/marks或其他attrs。

新增 `reporting/doc_engine/bridge/docx-table-row-breaks.ts`，同步接口为：

```ts
tableRowBreakAvailability(block)
editTableRowBreaks(block, steps)
verifyTableRowBreakResult(reopenedBlock, result)
```

bridge对真实XML geometry和parser.rowCantSplit核对，raw声明与effective布尔分开签发；只补/删直属目标子树。missing trPr如有直属tblPrEx则插在其后；selfclosing trPr正确展开；新增cantSplit在trHeight/tblHeader及其后继之前。既有paired target整体替换/删除，保留unknown sibling、row属性、行高/表头、hidden continuation正文、grid及ZIP其他part。未扩展style继承解析；与当前source/row-height显示边界一致。

测试先观察有效失败：前端3个具体行为失败、bridge2个具体行为失败（`/tmp/row-breaks-red.log`、`/tmp/row-breaks-bridge-red.log`）。额外schema向量先复现missing trPr被错误插在tblPrEx前（`/tmp/row-breaks-schema-red.log`），修复后通过。当前前端4项通过（`/tmp/row-breaks-green.log`），bridge6项通过（`/tmp/row-breaks-bridge-final-green.log`），包含实际DOCX保存重开、paired/val0/false/on/off/true/1、missing/selfclosing容器、schema顺序、unknown sibling和row属性原字节、hidden内容及非目标ZIP部件、revision/重复目标/非法值/伪造model与grid/merge拒绝。独立production TypeScript检查通过（`/tmp/row-breaks-production-types.json`，日志`/tmp/row-breaks-production-types.log`为空、exit0）。没有在本子任务运行产品build或完整测试。
