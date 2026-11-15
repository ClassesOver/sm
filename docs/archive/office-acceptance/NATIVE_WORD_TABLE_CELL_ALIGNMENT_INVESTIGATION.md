# Word 九宫格单元格对齐调查

2026-11-10。只读调查与独立 `/tmp` 源码探针，不改生产、不build、不运行完整测试。文字方向已有core/bridge并处于独立built集成工作中，其最终GUI/HTTP验收不由本文宣告完成。AutoFit、行高、列宽等亦各按原范围验收，九宫格是新增完整缺口，不能用已有段落对齐冒充完成。

## 本地实际缺口

Ribbon `frontend/src/docx-ribbon.ts:110` 已列9个 `table-align-{top|middle|bottom}-{left|center|right}` action，但 `docx-tables.ts` 没有路由或意图分支，落入target后报“此表格命令尚未接入”。

已有正文段落工具栏 `onAlignment -> setSelectionAlign` 可以改变PM paragraph align；已有 `setParagraphAlignment` 保存操作存在，但 `docx-operations.ts:498–509` 对表格单元格走独立分支，只允许cellTextEditOnly。真实本地收集器探针分别只改一个cell的vAlign、只改其直属paragraph.align，均得到“暂不支持修改单元格结构或样式”。因此不是只有按钮未启用，cell内水平/垂直的可保存协议也都缺失。

`edit-docx.ts` 的setParagraphAlignment依赖顶层blockId/runs与段落generated块，不能套用到表格block来写某个pPr；表内没有现成的独立段落block anchor。新表默认vAlign=center只证明生成器能力，非源表编辑交付。不要混淆run的superscript/subscript“垂直对齐”与cell.vAlign。

## 固定源码与语义

固定仓库 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- `editor/table-ops.ts` SHA256 `d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd`；selectedCells约688行，setCellAlignment约708行。
- `editor/direction.ts`：effectiveBidi / alignAttrFor（约48/73行），实现视觉方向转换；这是必须复用的源逻辑，不是按固定措辞猜RTL。
- `components/Ribbon.tsx:3359–3370` 九按钮通过runTableCommand调用setCellAlignment(v,h)，该入口先focus、enterSelectedTable，支持表节点选择转换全表CellSelection。

选择范围与文字方向一致：selectedRect逻辑slot→去重唯一owner；普通光标只选当前cell，CellSelection矩形覆盖多个owner，合并不按物理tc编号处理。

每个selected cell：

1. `vAlign = v==='top' ? null : v`，保留其他attrs/content。源函数**不设置tcPrEdited**；因此不能把本项泛化成方向/边距/nowrap全tcPr重建。
2. `cell.forEach` 只遍历直属子节点，类型是docParagraph或docListItem时写 `alignAttrFor(h,effectiveBidi(child.attrs))`；docHeading及其他类型不改，也不递归进嵌套表/文本框。必须保持这一真实来源范围，不把“所有段落后代”当作实现。
3. effectiveBidi是 `bidi===true || bidiInferred===true`。LTR visual-left→null、right→right；RTL（显式或inferred）visual-left→left、right→null；center恒center。null意为方向的start，而不是总等于XML left。

实际OOXML还需区分视觉align与w:jc逻辑值：source generate在format.bidi/bidiInherited为真时将left/right互换，inferred仅render标志不自动添加w:bidi。不能按h给所有p统一写同一个jc，否则混合LTR/显式RTL/inferred RTL显示错误。已有source mergePPrFormat/paragraphFormatXml可作为必要字段补丁的参考闭包，但不能重建整pPr丢未知属性。

纵合并：PM owner仅一次vAlign改动，source保存会将其vAlign传播至physical continue；continue的隐藏段落不是PM owner的直属段落，源保存未把owner水平对齐复制到隐藏段落。方向桥接的“全部continue方向传播”不能直接套用成“continue所有段落也对齐”。

## 已执行独立探针

`/tmp/word-table-alignment-investigation/probe.ts` 调用真实固定源setCellAlignment，不仿写算法。真实 `buildDocx → parseDocx → tableModelToPmNode → PM EditorState/selection → setCellAlignment → SavePlan → saveDocx → parseDocx`；普通fixture A1含LTR、显式bidi Hebrew、render inferred Hebrew三个直属段落，带bold/color/hideMark/keepNext、段落rsidR、网格2000/2000与精确行高300。另运行纵合并fixture。

```sh
node /tmp/word-table-alignment-investigation/build.mjs
node /tmp/word-table-alignment-investigation/probe.mjs > /tmp/word-table-alignment-investigation/results.jsonl
DIRECTION_SOURCE=merged node /tmp/word-table-alignment-investigation/probe.mjs > /tmp/word-table-alignment-investigation/merged-results.jsonl
```

普通及纵合并各9种v×h组合，共18个真实source保存向量，断言top→null/center/bottom；另有本地收集器2个拒绝向量，以及heading/list PM直属类型向量。

| visual水平输入 | LTR PM align | 显式RTL PM align | inferred RTL PM align |
|---|---|---|---|
| left | null | left | left |
| center | center | center | center |
| right | right | null | null |

源真实保存中显式RTL-left对应w:jc right，inferred RTL-left对应w:jc left，证明仅观察PM align不足以决定XML方向。tcPrEdited始终false；src vAlign center/bottom能保存，top省略标签。直属类型探针同时放入docHeading和docListItem，visual-left后heading保原right，list变null，三个普通段落按上表更新。

本地 `docxOperations` 的两向量拒绝证据在同一results尾部，不只是静态搜索结论。source整表保存再次丢失rsidR，并把2000twip网格像素往返为1995；本地实现必须只补需要的属性，不可直接复用source SavePlan。纵合并fixture的source保存还可能用空段落重建continue，不能作为无损来源内容策略。

这不是built/browser可视验收；对列表/标题保存、style inherited bidi、图片段落、嵌套独立选区及复杂continue仍需正式fixtures。探针schema扩展heading/list仅验证真实command类型过滤，不冒称Word样式解析全覆盖。

## 拟最小完整实现

一条独立组合操作，9按钮共享，不拆成无法原子保存的垂直/水平两操作：

```ts
{ kind:'setTableCellAlignment', blockId, expectedObjectSha256,
  steps:[{top,left,bottom,right,vertical:'top'|'center'|'bottom',
          horizontal:'left'|'center'|'right'}, ...] }
```

step严格6键、1–50步，逻辑grid半开矩形，server按原文件SHA/表SHA/合法网格核验。selectedCells唯一owner规则复用已实现方向core的边界/验证思路，但不要直接改方向step接受任意patch；不收client pPr/tcPr/XML/bidi值。

共享core接受PM来源，保留所有cell/paragraph其他attrs/marks；selected owner vAlign top归null，其直属docParagraph/docListItem依source effectiveBidi+alignAttrFor计算水平值。逐step回放，重叠选区后写覆盖，不改变节点大小/网格/宽高，也不设置tcPrEdited。表节点选择、普通光标、CellSelection与source一致。

独立capability建议cellAlignmentEditable/ReadOnlyReason/Cells及每owner对应直属可编辑段落的有效语义快照。不能把paragraph type、bidi/inferred、继承值只从client PM取作server真实依据。bridge从engine解析richParas/原XML/样式解析获取对应有效bidi及类型，必要时复用可信转换逻辑生成与UI相同的PM语义；否则只支持LTR并默默把RTL算错不算完整实现。

bridge只补两个位置：目标owner及其每个physical continue的直属tcPr/vAlign；目标owner的源直属目标w:p/pPr/w:jc。top清除标签；center/bottom写值，原unknown/重复/nested控制必须判定是否可安全解释并拒绝歧义。missing tcPr/pPr插入顺序正确，已有标签尽量只改value；不改continue隐藏p的jc、不改docHeading对应段落、不递归nested table。原段落rsid、runs、drawings、unknown pPr、tcPr其他属性、width/grid/rowheight、zip部件和metadata保留。

与方向复用几何slot/owner/physical mapping、XML直属定位、scope/hash/保护、原XML验证和批次守卫；水平段落定位/有效bidi/样式类型是本项新增完整工作，不能靠方向已经绿就略过。方向初批与其他同表意图要求先保存；本项也可维持明确边界，但同节页面设置不影响对齐语义，不应照搬AutoFit节宽冲突。已有单独正文段落对齐保持原合同。

## 实施后完整定向验收（尚未执行）

1. RED/GREEN覆盖9组合，普通光标/矩形/表节点、横纵合并去重、重叠多步、top与left/right null规则、非法矩形/未知字段原子拒绝。
2. 显式RTL、inferred RTL、样式继承bidi、混合LTR/RTL同cell，docParagraph/docListItem/docHeading、空段落、图片和nested blocks；UI PM投影与server实际XML回读一致。不能仅检查按钮active或vAlign字符串。
3. complex continuation原文/方向/jc与其他属性不被覆盖，owner垂直传播但水平不污染hidden内容；原别名/未知jc如start/end的处理按source有效语义明确验证。
4. HTTP实际保存/下载、草稿刷新、undo/redo、重开再次对齐，精确保留网格2000及奇数twip、行高、paragraph rsid/富文本/parts/metadata；非fixed表、复杂cell可用性独立于width gate。
5. 只执行定向合约及必要built smoke，不重复完整测试；本项完成也不替代插删格、表格属性、边距、拆表/选择等剩余完整scope。

## 本次独立模块实现与验证（2026-11-10）

经root授权新增 `docx-table-cell-alignment-core.ts`、`docx-table-cell-alignment.ts`（project/anchor/intent）、`bridge/docx-table-cell-alignment.ts` 及三份窄测试；另在旧direction/AutoFit/rowheight/columnwidth/shape投影中补 `nativeTableCellAlignment` 互斥。operations、edit-docx、Python与UI由其他任务负责，本子任务没有修改或构建。

API：`applyTableCellAlignmentSteps(table,steps) -> {table,alignments,paragraphs}`；`projectDocxCellAlignment(source,anchor,steps,schema)` 登记 `nativeTableCellAlignment:{steps}`；capability `cellAlignmentEditable/ReadOnlyReason/Cells`、`cellAlignments` 与 `cellAlignmentParagraphs`；bridge `editTableCellAlignment(block,steps) -> {xml,cells,alignments,paragraphs,physicalAlignments}` 和 `verifyTableCellAlignmentResult(block,result)`。每owner直属段落快照含type/align/bidi/bidiInherited/bidiInferred，project验证签发来源，不能client提供任意bidi改写server语义。

core是固定source selectedCells/setCellAlignment的等效纯投影，直接复用现有vendor direction模块的effectiveBidi/alignAttrFor，保留heading/atoms/tcPrEdited与所有内容/marks。不是宣称整个source command逐字迁入。bridge从原始parseDocx已解析richParas及runs复用source inferredBidi计算真实语义，包含style inherited；实际converter对cell heading style输出docParagraph，此事实已纳入源快照一致性测试。Schema重导有bridge生产消费者（沿用既有core桥接PM依赖模式），不是测试专用导出。

bridge复用文字方向capability做已验证的grid/span/physical几何边界；因此未知textDirection当前仍保守只读，没有借本项扩大几何scope。自身额外拒绝重复/嵌套/非法vAlign、jc，以及源直属p与richParas无法对应的SDT等歧义。正常nested table与continue隐藏段落opaque保留，不用它们改水平对齐；owner垂直对齐传播全部physical。已有标签仅改value或清除，缺容器有序插入；pPr jc顺序匹配源PPR_CHILD_ORDER，tcPr vAlign following含hideMark/cellIns/cellDel/cellMerge/tcPrChange（修订标记本身原样保留；部分修订仍被继承几何cap拒绝）。不触宽高、内容、段落rsid或其他parts。

验证证据：

- core先RED缺模块 `/tmp/cell-alignment-core-red.log`，2例GREEN `/tmp/cell-alignment-core-green.log`，包含完整9组合、LTR/显式RTL/inferred、heading/list与合并slot去重、clear及非法输入。
- project先RED `/tmp/cell-alignment-project-red.log`，2例GREEN `/tmp/cell-alignment-project-green.log`；新增旧五投影互斥1例GREEN `/tmp/cell-alignment-mutual-green.log`。
- bridge先RED缺模块 `/tmp/cell-alignment-bridge-red.log`，首3例GREEN `/tmp/cell-alignment-bridge-green.log`（内含9真实保存组合、explicit/inferred/style inherited RTL、列表与heading样式、XML/ZIP精确保留、continue/nested、缺容器、多步clear和非法控制）。
- server签发语义与实际固定source converter的richParas/attrs逐字段一致 `/tmp/cell-alignment-parity-green.log`；没有把server client差异交给client任意补齐。
- root审查发现新增vAlign在cellIns后插入的顺序问题，定向RED `/tmp/cell-alignment-order-red.log` 后修复，GREEN `/tmp/cell-alignment-order-green.log`，保原revision字节。
- jc start/end来源与固定converter的有效align一致，三水平模式实际save/verify `/tmp/cell-alignment-jc-green.log`；没有把别名字面值直接当未知失败或按client字串瞎改。
- 初始 `/tmp/cell-alignment-types.log` **不是通过证据**：测试导入source converter牵入整个renderer且简化tsconfig缺paths，并暴露3处新桥类型标注问题（已修）。最终production-only检查 `/tmp/cell-alignment-production-types.log` 为0，使用既有frontend paths/jsx/vite声明，files只列新core/project/bridge。没有重复完整测试或生产build。

模块已冻结供root做真实Python/built集成，当前只声称core/project/bridge子任务完成；GUI、HTTP下载、草稿与Undo/Redo是否通过仍以root后续结果为准，其余完整Word表格scope继续保留。
