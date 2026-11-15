# Word 表格替代文字（标题／说明）独立调查

2026-11-10；固定完整源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只新增本文档与 `/tmp/word-table-alt-investigation/`，不改production/vendor/AUDIT，不触发产品build，不跑旧测试。

## 下一项选择与当前差异

选择 Table Properties → **Alt页标题／说明**，即 `tblPr/tblCaption` 与 `tblPr/tblDescription`。固定源有真实文本input、textarea、changed状态、确定按钮和完整命令/保存路径，本地目前没有对应控件/专用意图/operation/严格保存。该项小且独立，适合继Cell wrap之后补齐。

先核对当前代码而不是旧审计矩阵：均分行列、指定尺寸、AutoFit、九宫格、文字方向、边距、行跨页、整表对齐和本批wrap都已有实现或在验收，不能误报未接。`tcFitText`仍无固定源UI，不发明“适应文字”。固定Ribbon的Table Layout Data组只有repeat header rows，未找到表格排序/文字转表的实际控件和执行路径，不拿本地/Office印象推断固定源功能。nested table属性范围更大，本次不捆绑。

本地 `frontend/src/docx-tables.ts` 的properties导航和各独立模块无Alt页；`docx-operations.ts`仅通用表格属性变化拒绝。实际source命令变更后喂给当前本地collector，24次均报“暂不支持修改表格布局”。现有桥接模块只在schema顺序列表/保真fixture中提到tblCaption/Description，没有编辑operation；Python白名单也没有此操作。source/vendored PM已具attrs不等于本地端到端支持。旧审计的笼统表格属性状态不能覆盖当前逐项事实。

## 固定源证据

| 文件 | 事实 | SHA-256 |
| --- | --- | --- |
| `apps/docs/src/renderer/components/TablePropertiesDialog.tsx` | Tab union/TABS有alt；`:285`读原tblCaption/Description；`:356`commitAlt；`:718`实际input/textarea；`:383`确定提交 | `45eaefe31e49748964b959957fa8550e402326b86c056266b4ea4737f52d2036` |
| `apps/docs/src/renderer/editor/table-properties.ts:25` | updateSelectedTableAttrs真实PM命令，修改当前选中表attrs | `bbff51fa2da6198df69fb290b8dd5624c00c87713c381b32713d9cf36fd0001f` |
| `apps/docs/src/renderer/editor/convert.ts` | `:1332`model→PM；`:1509`签名；`:1976`只在edited/new时发caption/description saved model | `7b05f77cd9d6a4859ad51993170d22252f9798c0dc62dddb726b6b99be8781fa` |
| `packages/docx-engine/src/parse.ts:5832` | 读直属tblCaption/Description/@val，非空才入model | 固定ref |
| `packages/docx-engine/src/generate.ts:2850` | defined caption/description替换或移除直属标签，XML转义；tblPr schema尾部caption→description | 固定ref |

commitAlt只有用户改动才执行，给真实命令的patch精确为：`tblCaption: altTitle.trim() || null`、`tblDescription: altDescription.trim() || null`、`tblAltEdited:true`。标题与说明作为一个完整值对提交；不是文内可见题注编号/References caption功能。中文hint“为无法看到表格的读者描述表格内容”，不得承诺本地renderer/屏幕阅读器已将它转成完整可访问表格语义。

`extensions.ts:3059`仅声明tblCaption/Description与edited attrs；本次未找到对应table renderHTML生成ARIA-label/description，故该项可落地目标是DOCX表格替代文字保存和属性dialog回读，不冒称浏览器无障碍输出已完成。

## 可执行真实source探针

`/tmp/word-table-alt-investigation/`：`probe.ts/build.mjs/results.jsonl`、6 source DOCX、24结果DOCX；执行 `node build.mjs`、`node probe.mjs > results.jsonl`。只临时bundle探针，不构建产品。

直接导入固定源 `updateSelectedTableAttrs`、`enterSelectedTable`、`tableModelToPmNode`、`pmDocToSavePlan`、`parseDocx/saveDocx`。UI commit patch按上述源码trim/null规则构造，未复制table命令实现；不是浏览器dialog点击。动态Schema保留converter实际attrs；输入真实PM selection，不stub命令/serializer。

6模式：absent、existing（已有自闭合标签）、paired（已有成对标签）、merged、RTL、floating。每种set、clear、description（只给标题旧值并改说明）、bare-node、entered-node五次=30次尝试，24接受并真实保存重开，6裸NodeSelection拒绝；显式enterSelectedTable后的node路径可接受。普通caret修改整张外层表，与单元格矩形大小无关。

- set：输入首尾空白的中文/`& < > "`及多行说明；命令trim，源parse重开正确回读转义字符和内部换行。
- clear：标题说明全空白→PM null；保存删除两个标签，重开均null。
- paired：原`<w:tblCaption ...></w:tblCaption>`/description同样正确替换、删除，没有发现行跨页旧regex那类paired清除bug。
- RTL/floating：命令不修改对应PM标记；源保存会整体再生成，不能以此推断非目标XML无损。
- merged：源A1 rowspan2 owner，A2 continuation有独立hidden正文。Alt变化参与structure signature，清continuationCells导致保存后hidden消失；普通段落rsid AABB丢失，grid2001/1999量化1995/1995，unknown tblPr custom也被整表生成丢失。这些是source重建副作用，后续本地不得照搬。
- local collector：24接受源命令的结果均被当前严格保存拒绝“暂不支持修改表格布局”，不是只静态查按钮。

`verify.py`对24结果独立用ZIP+lxml核验：set/description各恰好一个caption和description，clear两者均无；除document.xml/core.xml之外实际ZIP部件原字节；完整事实在`zip-xml-verification.json`。本轮实际变化是document.xml。未运行Word/LibreOffice/屏幕阅读器或真实产品GUI；不声称生产HTTP/下载修订验收。

### 多行说明的重要互操作差异

源generate的escapeXmlAttr输出**属性内字面换行**，源fast parser重开保留换行；但独立lxml遵XML属性归一化规则读成空格。paired-set.docx真实raw为`w:val="第一行\n第二行 ..."`，lxml结果为“第一行 第二行 ...”。后续无损adapter应把属性中的LF/CR/TAB编码为`&#10;`/`&#13;`/`&#9;`，并以源parser与标准XML解析器双重回读证明一致。不能因源自读成功就声称多行说明对标准Word消费者等价；实际Word显示仍须验收。

## 最小可落地方案（尚未实现）

新增专用`setTableAltText`，严格外层仅kind/blockId/expectedObjectSha256/title/description（也可按项目既有命名caption，但只能一种固定wire）。完整值对，均为字符串，应用同source trim/空值删除；长度/控制字符边界明确测试，不引AI、题注编号、跨表模板或直接XML请求。标题换行若UI单行应拒绝而非静默篡改；说明允许标准多行，保存使用正确属性字符引用。

capability签发直属raw两标签及parser当前值；namespace遮蔽、重复标签/属性、属性修订、畸形容器明确只读；空标签/paired/缺tblPr/自闭合tblPr按真实合法输入处理。字段不继承表style，不应拿cell margin/legacyIndent等逻辑推导替代文字。边界可先沿现有安全table身份几何；nested属性另立后续范围。

前端只project tblCaption/Description和专用native intent；不写通用tblAltEdited，不改rawTblPr/continuationCells/单元格、尺寸或显示缩进，避免开放整个source regeneration权限。重复提交替换最终值对；collector/replay从可信source PM按完整值重投影并exact比较，与其它同表修改互斥，来源/选区/文档变化对dialog stale拒绝，锁定不写。已保存来源可改，新表先保存后用来源表身份。

bridge对同一来源快照整批验证hash/protection/strict fields后，只patch直属tblPr的tblCaption/Description两个元素，删除或以转义值替换；按schema在tblLook之后、caption再description、tblPrChange前插入。保留unknown siblings、tblInd、width、bidi/floating、所有物理cell/隐藏continue正文和非document ZIP parts，不能调用整表generator。XML save block后按finalBlocks实际索引验证raw与parser值，保core metadata；迟到无效operation不得有产物。

首版验收：真实source输入语义/trim/清空；paired/selfclosing/missing标签/容器；中文和XML特殊符号、多行说明标准解析器与source回读一致；只改title或description另一值保留；undo/redo/draft/reopen；无效长度/控制字符/额外wire字段/hash/protection/修订/伪造PM拒绝；同表意图互斥；合并hidden与unknown raw保真；多表逆序+段落增删索引及迟到无效operation无输出；实际下载revision DOCX属性回读。不得只验证按钮或声称完整无障碍浏览器语义；仅跑新增窄回归及受影响集成，不重复完整旧测。
