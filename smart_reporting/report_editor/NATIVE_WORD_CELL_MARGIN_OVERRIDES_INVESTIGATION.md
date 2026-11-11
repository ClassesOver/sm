# Word 单元格边距覆盖与恢复继承调查

2026-11-10。本文只调查 TablePropertiesDialog 的 **Cell 页**，与 Ribbon“单元格边距”的整表默认值功能分开。整表默认值实现及其边界见 [默认边距调查](NATIVE_WORD_TABLE_CELL_MARGINS_INVESTIGATION.md)。本轮只新增本文及 `/tmp/word-cell-margin-overrides-investigation` 探针，没有改生产或测试代码，没有运行产品构建、完整测试或 HTTP 验收；不能据此声称 Cell 页已实现。

## 结论

Cell 页的四边对象表示给选中逻辑单元格设置显式 `tcPr/tcMar`；`null` 表示删除该层覆盖、恢复继承，绝非四边清零。选择纵合并的 continuation slot 实际命中 owner，设置/清除应传播到该 owner 对应的全部 physical cells，但必须保留各物理格原段落、隐藏文字和其他属性。

**解析后的 PM `cellMar` 是混合来源的显示属性，不是 raw `tcMar`。** 没有显式 `tcMar` 的格，也可能因条件表样式、行 `tblPrEx` 得到非空 PM 值；reset 命令临时写 `null` 后，保存重开会重新得到这些继承值。不能把 `cellMar!==null` 当显式自定义状态，也不能把 reset 后永久投影为 `null` 当成重开等价。实现前必须由服务端签发 raw 声明、effective PM 和 reset 后 effective PM 的可信快照。

## 固定来源与真实调用链

来源仓库 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。沿用默认边距调查中的同一来源，不切换分支或重新下载。

| 来源文件（相对此仓库） | 依据 |
|---|---|
| `apps/docs/src/renderer/components/TablePropertiesDialog.tsx:219` | selectionOf 读首个 owner 的 cellMar；253 行以 margins===null 初始化 sameMargins |
| 同文件 `:328` | commitCell 仅在 margins/sameMargins touched 时发出 cellMar；344 行 true→null，false→完整四边整数 |
| `apps/docs/src/renderer/editor/table-ops.ts:688` | selectedCells 在逻辑矩形中按 owner position 去重，跳过 gridGap |
| 同文件 `:734` | setCellProps 合并 patch，并设置 tcPrEdited=true；表外选择拒绝 |
| 同文件 `:783`、`:792` | tableCellsSelection、enterSelectedTable 把整表 NodeSelection 转成全表 CellSelection |
| `apps/docs/src/renderer/editor/convert.ts:1489`、`:1649` | structure signature 包含 cellMar/tcPrEdited，属性改变也清除原 continuationCells 快照 |
| `packages/docx-engine/src/parse-props.ts:1289` | cellMarginsOf 解析 partial margin；物理边优先，start/end 仅回退映射 left/right |
| `packages/docx-engine/src/parse.ts:6000`、`:6083` | 行例外、条件样式与 cell 自身值逐边合成；raw cell 优先于 row，row 优先于 conditional |

真实探针调用 `buildDocx → parseDocx → tableModelToPmNode → EditorState/真实选择 → setCellProps → pmDocToSavePlan → saveDocx → parseDocx → tableModelToPmNode`，使用固定来源的实际实现，没有用仿写命令替代。动态最小 schema 保留该来源 converter 发出的 attrs/marks；它不是浏览器实际编辑器，因此不证明 UI、DOM、布局、undo 或下载链路。

```sh
node /tmp/word-cell-margin-overrides-investigation/build.mjs
node /tmp/word-cell-margin-overrides-investigation/probe.mjs > /tmp/word-cell-margin-overrides-investigation/styled.jsonl
OVERRIDE_MODE=rtl node /tmp/word-cell-margin-overrides-investigation/probe.mjs > /tmp/word-cell-margin-overrides-investigation/rtl.jsonl
OVERRIDE_MODE=merged node /tmp/word-cell-margin-overrides-investigation/probe.mjs > /tmp/word-cell-margin-overrides-investigation/merged.jsonl
```

这是 `/tmp` 独立探针 bundle，未执行应用构建。`source-*.docx`、各 accepted 操作输出 DOCX 和 JSONL 均保留。另以 Python ZipFile + ElementTree 直接读取输出 `word/document.xml` 核对物理 tcMar、文字和段落 rsid，结果保存在同目录 `zip-xml-verification.json`，避免依赖 PM 对隐藏内容的表示。

## 样式、行例外与 partial tcMar 的证据

2×2 fixture 的实际表默认为 T/L/B/R=0/108/7/109 twip；表样式另外包含默认 top13/right109，firstRow 条件 `tcMar={left:41,top:23}`。第一行 `tblPrEx/tblCellMar={bottom:17}`，第二行 `{bottom:29}`。每格含 `noWrap`、`textDirection=tbRl`、段落 `jc=end` 和 `rsidR=AABBCCDD`。

| 物理格 | 原始直属 tcMar | 来源 PM cellMar |
|---|---|---|
| A1 owner | `{right:0}` | `{top:23,left:41,bottom:17,right:0}` |
| B1 styled only | 无 | `{top:23,left:41,bottom:17}` |
| A2 hidden（普通模式为普通格） | `{left:71}` | `{bottom:29,left:71}` |
| B2 row only | 无 | `{bottom:29}` |

因此 PM 属性既不是 raw partial，也不是包含 table defaults 的完整四边。B1 缺 right 时由渲染层继续取 table right109；B2 缺 top/left/right 时取 table 的0/108/109。A1 的 right0 必须保留为显式零，不能当“缺失”。raw partial 与 effective partial 应分别表示，不能相互覆盖。

来源 UI 对 B1/B2 的 `sameMargins` 会因 PM 非空初始化为 false，尽管 raw tcMar 根本不存在。应保留来源“删除覆盖恢复继承”的命令含义，但不要把这个 UI 判断缺陷迁为本地真实性契约。建议本地文案明确“使用继承边距”，状态由 trusted raw 覆盖是否存在决定，四边预览使用 effective 显示值；混合多选不能只展示首格并暗示全选一致。

## 命令、保存与重开结果

每个向量从相同原始 DOCX 单独开始，不依赖上个向量留下的状态。set 使用 `{top:0,right:130,bottom:96,left:175}`，单位是 twip；这里直接调用命令，没有经过来源 cm 输入控件，175 不能误记为来源0.31cm量化结果（该控件0.31cm→176，见默认调查）。共10次真实命令尝试，9次 accepted 并真实保存，1次拒绝。

| 模式与选择 | 结果 |
|---|---|
| styled caret set | 仅 A1 改四边、tcPrEdited=true；重开仍为四边对象，其他格继承/partial 不变 |
| styled caret reset | 命令中 A1=null；输出删 A1 tcMar；重开 A1 恢复 `{top:23,left:41,bottom:17}`，A2 left71保留 |
| styled 全2×2矩形 set | 四个 owner 全改四边，重开一致 |
| styled 全2×2矩形 reset | 四格命令均null；所有直属tcMar移除；重开第一行均 `{top:23,left:41,bottom:17}`，第二行均 `{bottom:29}` |
| styled bare NodeSelection set | accepted=false，文档不变，没有保存结果 |
| styled enterSelectedTable 后 reset | accepted=true，结果与全2×2矩形reset一致；包装步骤是必要语义 |
| bidiVisual 全2×2矩形 set/reset | 与 LTR 相同 logical owner 集合、相同四边和值；未交换left/right；reset重开继承与styled一致 |
| merged lower-slot set/reset | A1 restart 与 A2 continue 纵合并；下层slot定位同一owner，仅一个PM owner改变；保存时两个physical cells均设四边或删tcMar |

reset 后不应将 `cellMar=null` 与“没有 padding”混淆：它只代表编辑瞬间清除此层值。保存重开得到的 style/row effective 值应成为本地投影的最终语义，`tcPrEdited` 是保存标志、重开为false，也不能作为覆盖来源标志。

## 合并续格与序列化副作用

merged 原A2含自己的 `tcMar={left:71}`、文字 `hidden`、方向/noWrap及带rsid的段落，PM只暴露三个非continue owner。来源下层slot set会给 A1/A2 都写完整目标tcMar，reset会删两者tcMar；但两次源保存都把 A2 文字清空、rsid丢失。普通格的 `jc=end` 被序列化为 `right`，全表 grid2001/1999也重生成1995/1995。这些是 converter/serializer 的重建副作用，不能作为本地边距功能必须复制的行为。

源码原因可直接追踪：margin/tcPrEdited 参与 structure signature，改变后清除 continuationCells；重新生成 continuation 时回退 owner 属性与空段落。保真方案应复用来源的选择/owner语义，服务端仅替换或删除已定位 physical `tcPr/tcMar` 子树，保留隐藏正文、段落属性、方向、noWrap、合并标记和其他XML。

额外的 **parser-reference-only** 实验明确与真实命令分开：在原XML中仅删除A1 tcMar，走真实saveDocx的xml保存和parse/converter；普通、RTL、merged都重新得到A1 `{top:23,left:41,bottom:17}`，其他原字节保持。merged另对A1+A2的tcMar同时set/reset，再真实封包重读：显示PM与来源命令保存结果一致，A2 `hidden` 与rsid仍保留。文件为 `parser-reference-merged-all-physical-{set,reset}.docx`。这证明“保存目标margin+保持隐藏段落”的解析参考可行，不等于已有本地安全patch实现，也没有证明schema插入顺序的生产实现完成。

## 建议冻结的严格 steps 协议

与已实现 `setTableCellMargins` 整表默认意图分开，新增操作可命名为 `setTableCellMarginOverrides`，不要靠 scope 字段复用旧默认操作后静默改变含义：

```json
{
  "kind": "setTableCellMarginOverrides",
  "blockId": "已签发表格ID",
  "expectedObjectSha256": "原始表格身份摘要",
  "steps": [
    {"top": 0, "left": 0, "bottom": 2, "right": 1,
     "margins": {"top": 0, "right": 130, "bottom": 96, "left": 175}},
    {"top": 1, "left": 0, "bottom": 2, "right": 1, "margins": null}
  ]
}
```

- 顶层、step、margins均严格键集合，拒绝额外字段、字符串数值、布尔值、NaN、负值与小数。四边set必须齐全，每边整数0..28350twip；null是删除完整raw tcMar恢复继承，不支持在同一个对象中以缺边/null猜测逐边reset。
- steps非空，建议上限50；坐标为零起始logical grid半开矩形，整数且 `0<=top<bottom<=height`、`0<=left<right<=width`。不能使用视觉RTL序号或自报physical tc索引。来源owner-map去重语义保持；若触及合并owner的任意slot，作用该完整owner及其physical continues，同一step只处理一次。无效网格/slot不能静默部分执行。
- 严格按steps顺序处理，重叠owner后写覆盖；set→reset重置为来源继承，而非恢复原显式值；reset→set最终为新四边。服务端先完整校验全部steps与身份/可编辑性，成功后一次提交，不在中途失败后保留半次编辑。
- 前端caret可生成当前owner矩形，CellSelection使用来源selectedRect，整表NodeSelection显式采用enterSelectedTable语义生成全表矩形；不把bare-node直接执行能力记为来源支持。RTL只影响视觉映射，不交换物理四边。
- 首版沿现有同表专用意图互斥边界：不与表默认、合并拆分、布局/方向/文本等同表原生修改混写；不为无关页面操作新增冲突。撤销/重做和草稿恢复必须回放同一有序steps。

以上为下一步协议建议，尚未注册生产API。50步上限是建议的本地资源边界，不是此次源码实验测出的来源限制。

## 可信来源快照与前端投影

服务端基于原对象hash、原DOCX包及真实parser签发独立 `tableCellMarginOverridesEditable/ReadOnlyReason/Source`，不可复用“默认边距editable”当覆盖能力。Source至少包含：logical owner几何与顺序、每owner raw partial tcMar或缺失状态、rawPresent（owner直属容器）、hasPhysicalOverrides（任一physical容器）、原effective PM partial/null、resetEffective PM partial/null、各physical continuation的服务器内部身份与raw声明。原XML不必发送客户端；存在partial/别名时，raw“存在状态”必须与normalized值分开，避免把空容器误判为无容器。

resetEffective不能从当前effective对象删几个键得到：raw与style可声明同一边，删raw后应暴露较低层的值；合并continue还可能有各自行例外。优先复用 **当前doc_engine真实parser**，在同一原包上下文的临时副本中，按已核验owner映射仅移除目标physical tcMar，然后parse并调用真实converter，取得reset effective；也可先移除全表所有可编辑owner的tcMar，一次解析形成继承基线，因为本意图不改变样式/行例外/表默认/几何。实际实现须核对该批量优化与按owner参考等价，不能把优化推测当已验证事实。

前端纯project应验证来源PM的每owner effective快照与几何，再回放steps：set投影四边；reset投影服务端签发的resetEffective。保持其他attrs、marks、content不变，专用native意图记录steps，不借通用tcPrEdited来打开方向/noWrap/段落重建权限；override存在状态另随专用意图回放。后续set/reset仍用同一继承基线，最后由服务端实际修改后的重解析结果验证。不能接受客户端自行提交resetEffective、styles、raw XML、bidi状态或physical映射作为权威。

此策略避免另写表样式继承引擎，复用Agno之外的现有DOCX解析能力；当前解析兼容范围就是投影范围，不额外声称完全覆盖Word所有样式优先级。

## 服务端局部修改和验收边界

1. 复用现有XML索引、owner/continue几何与对象身份校验，定位直属tcPr/tcMar；防止nested tc误匹配。校验目标处重复容器/重复同义边、非dxa单位、非法数值、修订覆盖、namespace歧义等；无法安全消歧则拒绝该编辑并给出具体原因，原文件不变。保留当前共享能力对hMerge/gridGap等的保守边界，除非另有真实向量和实现支持。
2. set按schema顺序仅补/替换目标tcMar，规范输出T/L/B/R；reset仅删除其tcMar，不清样式/行例外/表默认。没有raw override的reset可无修改，但UI不能因此伪造“从自定义改继承”。继续保留所有tc其他属性、隐藏段落、nested表、unknown sibling与非目标ZIP部分；不整体序列化PM表格。
3. 修改后使用原DOCX上下文真实parse/converter核对：目标raw与final step一致、各owner effective与project一致、非目标raw/所有正文及样式例外未变。仅验证PM不够，隐藏续格必须直接核对XML/ZIP。
4. 针对partial/style/row、四边零、重复steps、横纵合并与下层slot、bare/entered NodeSelection、RTL、单位边界、篡改hash/坐标/额外键、未知单位及原子失败建立定向测试。补真实浏览器内容盒/行高/竖排、重开/undo/redo/草稿、HTTP保存下载及隔离built smoke；本轮没有执行这些验收。
5. 如果后续改动触及导出/发布，必须维持项目既有“验收失败仍签发已生成且身份可读PDF/Word链接”的非阻断契约；不能把编辑能力拒绝与报告产物签发门禁混为一体。本轮未触及这些链路。

当前可执行下一步是按上述边界实现独立覆盖意图、可信reset快照和physical tcMar补丁；整表默认边距已完成的能力不因此扩大为Cell页覆盖支持。

## 随后授权的独立模块实施（2026-11-10）

上文是调查时状态；随后主任务授权实现独立core/project/bridge及窄测试，故不能把“未改生产代码”的调查范围说明当作实施后的状态。共享入口、UI、operations/Python、统一bundle和built验收由主任务/另一子任务负责；本节不声称这些工作已经通过。

新增前端 `docx-table-cell-margin-overrides-core.ts`、`docx-table-cell-margin-overrides.ts`，类型为 `TableCellMarginOverrideStep`、`TableCellMarginOverrideCell`、`TableCellMarginOverridesSource`、`DocxCellMarginOverridesAnchor`，project函数 `projectDocxCellMarginOverrides(source,anchor,steps,schema)`。cap字段采用上文独立命名；意图为 `nativeTableCellMarginOverrides:{steps}`。重复调用会追加steps并验证当前PM等于原来源回放结果；重叠后写生效，reset投影可信resetEffective，不打开通用tcPrEdited，不改正文/方向/rawTcPr。`replayTableCellMarginOverrides`返回各owner的margins/raw/rawPresent/hasPhysicalOverrides/touched数组，供UI真实区分覆盖状态。

新增 `reporting/doc_engine/bridge/docx-table-cell-margin-overrides.ts`：

```ts
await tableCellMarginOverridesAvailability(block, parsed)
await editTableCellMarginOverrides(block, steps, parsed)
verifyTableCellMarginOverridesResult(reopenedBlock, result)
```

`parsed`是实际parseDocx返回的`ParsedDocFull`（包含saveDocx所需extras），必须与block属于同一解析上下文。WeakMap缓存每份ParsedDocFull的Promise：一次把该包所有安全候选表的physical tcMar删除并保存重读，形成继承基线；同次inspect多表并行请求复用它。不会另写style/row解析器。局部patch处理missing/selfclosing tcPr，新增tcMar在textDirection等后继属性之前插入；已有tcMar只替换其自身，非目标属性/未知sibling、grid2001/1999、段落rsid和hidden文字原字节保留。

source cell增加强制 `hasPhysicalOverrides:boolean`，同时保留owner自己的 `rawPresent`：当owner没有tcMar但hidden continuation有left71时，前者true、后者false，仍允许用户清除整个合并owner的覆盖。空`<w:tcMar/>`则rawPresent=true、normalized raw=null，不能被误判为无容器。

实际窄测试结果：前端4项通过，bridge7项通过；日志 `/tmp/cell-margin-overrides-final-green.log`、`/tmp/cell-margin-overrides-bridge-final-green.log`。bridge测试包含实际DOCX set/reset保存重开、合并两物理格tcMar传播且hidden/rsid/非document ZIP部件保真、样式与行例外继承、空tcMar、owner无覆盖但continue有覆盖、两表批量继承基线与逐owner真实parser参考等价、非法单位/重复别名/修订/过期上下文/非法steps拒绝。hidden-only场景先出现expected true/actual undefined失败，修复后通过，失败证据 `/tmp/cell-margin-overrides-hidden-red.log`。

当前仍保守拒绝局部xmlns歧义、hMerge/gridGap、属性修订及畸形逻辑网格；未宣称通用Word样式完全兼容。没有在本子任务运行产品构建或完整测试，也没有提交。

独立production TypeScript检查通过：`tsc --noEmit -p /tmp/cell-margin-overrides-production-types.json`，日志 `/tmp/cell-margin-overrides-production-types.log` 为空（exit0）。此检查未替代主任务的统一产品构建。
