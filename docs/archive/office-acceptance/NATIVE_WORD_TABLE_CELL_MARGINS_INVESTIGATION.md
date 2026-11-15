# Word 表格单元格边距调查

2026-11-10。只读生产调查，仅新增本文及 `/tmp/word-cell-margins-investigation` 探针；未实现功能、未运行完整测试、未构建产品、未提交。DOCX 当前引擎归属 `reporting/doc_engine`，不再属于 slides_engine。

## 当前入口与完整缺口

`frontend/src/docx-ribbon.ts:116` 已列 `table-cell-margins`“单元格边距”，但 `docx-tables.ts` 未为它提供路由，target 对未知 action 返回“此表格命令尚未接入”。已有表格文本、方向、九宫格对齐、AutoFit 等支持不能视为边距支持。

不仅是对话框没接：本次直接用实际本地 `docxOperations` 收集器运行两类 source PM 改动，整表 `cellMar/cellMarEdited` 得到“暂不支持修改表格布局”，单格 `cellMar/tcPrEdited` 得到“暂不支持修改单元格结构或样式”。真实输出见 `/tmp/word-cell-margins-investigation/local-refusal.jsonl`。服务端也没有边距专用操作/锚点/capability。解析器和渲染器已有 cellMarTwips/cellMar 只证明能显示来源属性，不能证明可保存编辑。

## 固定来源及入口语义

仓库 `/home/junge/pros/genoffice-source-full`，实际 HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 来源文件 | 关键位置 | SHA256 |
|---|---|---|
| `apps/docs/src/renderer/components/TableDialogs.tsx` | 215–277 CellMarginsDialog | `08ec3b80d2ea04314adcc0281e4c9dcdd7519bd344fcb61a7944a98f4a7b4791` |
| `components/TablePropertiesDialog.tsx`（同 renderer 根） | 58 tableValueOf、86 applyTableValue、232 selectionOf、340 commitCell | `45eaefe31e49748964b959957fa8550e402326b86c056266b4ea4737f52d2036` |
| `editor/table-ops.ts` | 688 selectedCells、734 setCellProps | `d47b69d719287f3126b97bb157b548451a234102351f95ddcfd6af3d44a5adbd` |
| `editor/table-properties.ts` | 25 updateSelectedTableAttrs | `bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f` |

Ribbon.tsx:3414 调用 `onTableDialog('cellMargins')`，App.tsx:9024 打开真实 CellMarginsDialog。**此入口修改整表默认边距，不是当前选中格覆盖**：对话框读取 docTable.attrs.cellMar，OK 调用 `applyTableValue(editor,value,new Set(['margins']),sectionContentWidthPx)`；其只写 table `cellMar:{top,right,bottom,left}` 和 `cellMarEdited:true`，由 updateSelectedTableAttrs 定位当前表。选中一个格/矩形只是定位表，并不限制默认值作用范围；有 tcMar 覆盖的格仍保留覆盖。不能把该按钮实现成仅改 selected cells 后声称来源一致。

另一个来源入口是 TablePropertiesDialog 的 Cell 页：读取当前选择首个逻辑 owner 的 cellMar；缺省各边回退 tableMargins，再回退 top/bottom=0、left/right=108 twip。`sameMargins` 初始是 `cellMar===null`，不通过四边数值相等推断。Cell 页改变 margins/sameMargins 后调用真实 `setCellProps({cellMar:null|四边对象})`；null 表示“与整表相同”，删除覆盖而非写四个0。该命令在 selectedRect 中逐slot去重 owner，普通光标改当前格，CellSelection 矩形改其中所有 owner，gridGap 跳过；设置 tcPrEdited=true。整表节点选择需宿主按来源 enterSelectedTable 转成全表选择，不能把无法执行的裸 NodeSelection 当已支持。

### 单位与零值

内部均为 twip（1/20 pt，1/1440 inch）；CSS `cellPadPx` 用 twip/15，保留至0.001px。LengthInput 接受用户偏好单位及显式 cm/in/pt 等，向父级回调 twip。来源组件中间状态以 cm 存储，用常量567 twip/cm；tableValueOf 先把来源 twip/567 四舍五入到2位cm，提交再 `Math.max(0,Math.round(cm*567))`。对话框输入范围0–50*567=28350 twip。不能把它误作像素或0–50 twip。

真实向量证明 0.31cm→176、0.23cm→130、0.17cm→96 twip；top=0 必须显式保留。原108/109 twip都显示约0.19cm，故仅打开后直接提交也可能按来源中间值量化。长期实现建议以整数twip保留未改边、复用LengthInput单位解析；若不照搬来源无操作量化，应明确记录为保真适配，不能暗改源数值。

## 真实来源保存证据

探针 `/tmp/word-cell-margins-investigation/probe.ts` **调用固定来源真实函数** `tableValueOf/applyTableValue/setCellProps/tableModelToPmNode/pmDocToSavePlan`，没有仿写命令代替来源。链路：buildDocx真实ZIP→parseDocx→source converter→PM EditorState/CellSelection→source命令→source SavePlan→saveDocx→parseDocx。探针只是独立/tmp bundle，不是应用build。

```sh
node /tmp/word-cell-margins-investigation/build.mjs
node /tmp/word-cell-margins-investigation/probe.mjs > /tmp/word-cell-margins-investigation/normal.jsonl
MARGINS_MERGED=1 node /tmp/word-cell-margins-investigation/probe.mjs > /tmp/word-cell-margins-investigation/merged.jsonl
MARGINS_RTL=1 node /tmp/word-cell-margins-investigation/probe.mjs > /tmp/word-cell-margins-investigation/rtl.jsonl
MARGINS_LOCAL_ONLY=1 node /tmp/word-cell-margins-investigation/probe.mjs > /tmp/word-cell-margins-investigation/local-refusal.jsonl
```

普通、纵合并、bidiVisual 三类，各运行整表默认、selected override、selected reset，共9个真实来源保存向量；原/输出 DOCX 均保留于探针目录。原默认 T/L/B/R=0/108/7/109；owner原覆盖0/33/7/109，第二行物理格覆盖0/71/7/109，其他格无覆盖。

| 向量 | 真实source观察 |
|---|---|
| 普通表修改默认 | table attrs cellMarEdited=true；默认变0/176/96/130；owner33和第二行71的tcMar保留，未设置所有格tcPrEdited |
| 普通表selected override | 仅owner cellMar改0/175/96/130且tcPrEdited=true；默认与其他格不变 |
| 普通表selected reset | owner cellMar=null，输出移除其tcMar；默认保留，第二行71覆盖仍在 |
| 纵合并在下方continue slot选择override | PM仅有owner；保存owner和物理continue都得到0/175/96/130 |
| 纵合并reset | owner和物理continue都移除tcMar |
| bidiVisual | 相同逻辑slot、相同字段写入；四边数值不因RTL互换，普通表三向量数值一致 |

source serializer 的局限也有真实证据：所有操作重生成表后 `rsidR=00ABCDEF` 消失，原grid 2001/1999 twip变1995/1995；纵合并continue原隐藏文字“hidden”变空。纵合并“只改默认”甚至将continue的71覆盖替成owner33。这不是默认边距命令主动修改续格，而是整体serializer重建副作用。**本地不得把这些副作用迁为保真合同**：修改默认只应补tblPr/tblCellMar，保留所有physical tcMar与内容；selected覆盖/清除才向owner对应physical continue传播目标margin，仍保留continue隐藏段落、方向与其他属性。

以上没有证明浏览器布局/HTTP/下载/undo/reopen完成，也没有执行 source NodeSelection、所有样式/修订/单位向量；源码与运行证据明确分开。

## 默认、覆盖与RTL的可信来源边界

本地引擎 `parse-props.ts:1289 cellMarginsOf` 接受无type或dxa的非负值；先读top/left/bottom/right，再把start/end回退映射left/right，不按bidiVisual做交换。遇非dxa会忽略。`parse.ts` 还将 table style、conditional tc style、row tblPrEx 与实际tcMar叠加进有效 cellMarTwips，所以**解析model/PM cellMar不一定等于原文件的显式覆盖**。仅凭 `cellMar!==null` 可能把样式值错当“自定义”，reset还可能重新暴露row/style值，不能从client PM反推要删除的XML。

实现须同时签发/核对“显式声明”与“有效显示”快照。直属raw tblCellMar/tcMar决定要改哪层；effective值用于对话框预览。局部缺边按每边继承，不得将缺边和0混为一谈。表格RTL镜像column的视觉次序不改logical map，边距标签是top/left/bottom/right，与段落的logical align无关。对于start/end别名，固定reader的处理只能作为来源兼容依据，复杂双重声明需进一步真实fixture确定或保守只读，不能自行猜RTL转换。

现有渲染cellPadCss以表级CSS变量供默认值，cell左右只覆盖声明边；垂直边距参与rowPadVarsCss整行共同计算。验收不能只检查某td.style.padding：要观察实际内容盒、同排混合覆盖、exact/atLeast行高与合并格、RTL、竖排换行。无需新增布局算法，应复用这套现有来源renderer。

## 最小完整方案（待实施）

先精确交付 Ribbon 对应的“默认单元格边距”：单一独立意图，例如 `{kind:'setTableCellMargins',blockId,expectedObjectSha256,scope:'table',margins:{top,right,bottom,left}}`。入口在光标/矩形/全表时定位同一表；不改所选范围的tcMar。若需求同时包括来源 Cell 页覆盖，则在同一已验证语义中显式区分 `scope:'cells'` 和逻辑矩形steps，margin四边对象=设覆盖，null=恢复继承；不要以按钮名字推断把两种scope混为一个。

1. 前端独立core/project：复用已存在的source table owner/map边界，不借通用tcPrEdited重建所有字段；记录可回放严格意图并验证可信基线。表默认与cell override对话框展示明确，整数twip存储、单位控件复用。只投影cellMar/cellMarEdited或所选owner.cellMar，保其余attrs、marks/content。撤销重做/草稿必须恢复同一意图。
2. 服务端 `doc_engine/bridge/` 新边距模块：scope/hash/文档保护校验；从原XML判断直属tblPr/tblCellMar或tcPr/tcMar，建立physical owner/continue映射；table scope只改默认容器，cell scope只改目标owner及其physical continue margin。复用共享几何与XML定位，新增属性特定安全检查；不接受client原XML、effective边距、bidi或自报physical索引。
3. 原标签只补/清目标margin子树，按source T/L/B/R与tblPr/tcPr schema顺序插入；缺容器、自闭合容器均正确展开；保raw unknown siblings、段落rsid、隐藏内容、nested table、宽高/borders/noWrap/textDirection、修订与ZIP其他part/metadata。四边全0保标签；cell reset删tcMar以恢复继承，不写零。table默认不能全表删tcMar。
4. 可信capability分别陈述 tableDefaultsEditable 与 cellOverridesEditable 及各自原因，不把已支持方向/width的capability当边距已验证。对重复容器/边、非法单位/负值/NaN、nested控制、未知target属性、样式/row exception不能消歧、修订混淆等先拒绝本次编辑并说明；原非目标opaque XML尽量保留，避免整表因不相关富内容泛化只读。普通源表不应绑定fixed-layout gate；exact行高不禁止边距本身，但显示风险需真实验证。
5. 后端操作白名单、收集/replay、同表意图冲突以及验后回读必须一起接通。首版同表边距与其他布局/文字结构编辑可明确先保存边界，独立页面/节设置不应无依据冲突。具体协议需实施前定稿，此处不创建生产API。

## 实施验收范围

- Ribbon默认行为：caret/矩形/全表均修改同一table默认；保每个显式tcMar；四边0/奇数twip/不同单位、范围边界/无操作提交保真。
- 如纳入Cell页：普通格/多格/横纵合并owner去重、下方continue slot、重叠steps后写覆盖、set/reset/部分继承；table/style/row例外与显式tcMar快照一致。
- LTR、bidiVisual、显式/推断RTL段落、vertical text、全表布局与exact/atLeast行高，证明四边不会被错误镜像；真实computed内容盒、行高与换行，不仅按钮状态/PM字段。
- 原XML/ZIP保真：2001/1999 grid、行高、rsid、unknown属性、run/图片、nested表、continuation隐藏文字方向、shading/border/noWrap、修订与非目标部件；样式支持不足有独立原因且原文件不变。
- 篡改scope/hash/坐标/额外字段/未知单位原子拒绝；无部分事务。HTTP真实保存/下载、源修订不变、重开/草稿刷新/undo/redo/再次修改；新旧包路径及bundle隔离运行。只跑相关定向契约与必要built smoke，不重复完整测试。

本文是下一缺口调查与设计依据，不计入Word单元格边距已交付或完整表格scope完成。

## 本轮独立 core/project/bridge 实施证据（2026-11-10）

本轮随后获授权实现 **Ribbon整表默认边距**；上文“待实施”描述的是调查时状态，不能继续当现状。`Cell` 属性页单格覆盖/set/reset仍未由本项实现。前端UI、operations、Python与edit-docx接线及统一built验收由root/其他子任务负责，以下只记录本子任务范围。

新增：

- `frontend/src/docx-table-cell-margins-core.ts`：`TableCellMargins` 四整数0..28350twip，`applyTableCellMargins` 只改table.cellMar/cellMarEdited，整个content与所有cell attrs保持原对象；复用PM TableMap验证矩形/owner网格，不创建新布局算法。
- `frontend/src/docx-table-cell-margins.ts`：`DocxCellMarginsAnchor`、`projectDocxCellMargins(source,anchor,margins,schema)`，意图 `nativeTableCellMargins:{margins}`。旧六种表格投影新增此意图互斥；本投影同时拒绝其他同表结构意图与过期默认/单格快照。
- `doc_engine/bridge/docx-table-cell-margins.ts`：`tableCellMarginsAvailability(block)`、`editTableCellMargins(block,margins)`、`verifyTableCellMarginsResult(block,result)`，不使用固定layout/方向cap作为边距前置。cap签发 `tableCellMarginsEditable/ReadOnlyReason` 和 `tableCellMarginsSource:{defaults,raw,cells}`；defaults是解析后的有效整表默认partial|null，raw是直属tblCellMar显式原XML|null，cells是非continue owner的有效cellMar有序快照（含style/row/partial tcMar）。project只接受与真实PM默认/单格快照一致的来源；原文件/表身份仍由root接线核验，不接受client自报raw XML来写入。

实际保存只改直属tblPr/tblCellMar，保留所有physical tcMar与行例外、隐藏continue和嵌套内容；没有source整表重生成的rsid/宽度/隐藏文字损失。新默认为四边对象后，原parsed cellMar未被自动填入新default：它们本来表示cell/style/row覆盖，renderer会对其缺边继续继承新默认。这一点用真实含 table style+firstRow条件+row tblPrEx+partial tcMar+纵合并+bidiVisual 的DOCX，保存后再次parse并调用真实source converter逐owner比较得到确认；不是根据client猜测有效值。

目标默认容器内接受无type/dxa的整数与单独start/end别名，覆盖时规范写T/L/B/R；重复同义边、未知目标属性/子节点、非dxa/负值/越界、重复默认容器、默认属性修订、命名空间局部声明歧义等只读。非目标unknown tblPr/tcPr sibling原字节保留（含单引号）。当前保守边界仍拒绝带局部xmlns声明的整个table来源、hMerge/gridGap与无法映射的畸形/过大表；没有声称通用namespace编辑或Cell页能力。缺tblPr/自闭合tblPr按顺序补容器，显式四零完整保留。

定向证据：

- core/project缺模块真实RED `/tmp/cell-margins-core-project-red.log`，首4例GREEN后，旧六project互斥新增RED `/tmp/cell-margins-mutual-red.log`，最小补守卫后最终5例GREEN `/tmp/cell-margins-core-project-final-green.log`。
- bridge先RED缺模块 `/tmp/cell-margins-bridge-red.log`，最终6个真实DOCX用例GREEN `/tmp/cell-margins-bridge-final-green.log`；其中首例逐字比较去掉**首个默认容器**后的完整table XML，并比较所有非document ZIP部件；因此包括physical续格tcMar/隐藏内容/row例外未变。另覆盖missing/selfclosing容器、全零、上限/非法输入、别名、单引号、unknown sibling、namespace/revision/重复与伪造parsed模型。
- production-only严格类型检查最初暴露7项never箭头函数导致的null narrowing问题，改为显式never函数声明后退出0，最终 `/tmp/cell-margins-production-types.log` 为空；临时配置 `/tmp/cell-margins-production-types.json` 保留。该配置仅列本轮core/project/bridge入口，并复用现有frontend aliases及类型，不是全量产品build。

本子任务未运行产品build、未重复完整测试、未提交；最终完整UI/HTTP保存/下载/草稿/undo/redo/built证据以root后续验收为准，不能用本节替代。
