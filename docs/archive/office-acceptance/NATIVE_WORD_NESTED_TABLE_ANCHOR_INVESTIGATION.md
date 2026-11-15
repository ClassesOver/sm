# Word 嵌套表格可编辑来源 anchor 调查

调查日期：2026-11-10。范围：独立嵌套表来源身份、文字编辑闭环、选择与表格命令的边界。只读源码调查并在 `/tmp` 执行独立真实 DOCX 探针；没有修改生产代码或测试，没有运行项目测试套件、服务或后台进程，没有提交或推送。

## 结论

当前并非“嵌套表不能输入”：固定源的 `docNestedTable` NodeView 已为第一层嵌套表中不含更深表格的单元格创建可输入 DOM island，离焦后写回 `attrs.model`。但本地协议没有内层表/单元格来源身份，`docxOperations` 会把变化归到包含它的外层单元格并因其只读而拒绝。因此它尚不构成可保存、可恢复草稿的编辑能力。

最小完整交付应先实现“有独立来源身份的第一层嵌套简单单元格文字编辑”，保留现有原子节点与源引擎补丁；不为该节点宣称行列结构、重复标题行、内层 PM 选区能力。若交付目标包含这些表格命令，则必须另补内层表选择与命令定位，不能只扩展 bridge anchor。

## 固定源与证据口径

固定仓库：`/home/junge/pros/genoffice-source-full`；实际 `git rev-parse HEAD` 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。以下固定源行号针对该提交，链接给出不可变 ref；本地行号是调查时共享工作区快照，已有大量在途修改，不代表干净提交。

### 1. 模型记录的是阅读顺序，尚非编辑来源身份

- [types.ts:1479](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/packages/docx-engine/src/types.ts#L1479)：`TableCell.nestedTables?: TableModel[]`；`nestedTableAnchors?: number[]` 表示每个内层表前有多少直属段落。它不是 blockId、XML hash 或稳定持久 ID。
- [types.ts:1549](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/packages/docx-engine/src/types.ts#L1549)：`TableModel` 保存行列、宽度及其他显示/格式属性；内层表没有正文 `Block.docxIndex` 或独立 `originalXml`。
- [parse.ts:6209](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/packages/docx-engine/src/parse.ts#L6209)：遍历单元格的 `w:p`/`w:tbl`，遇表递归建模并记下当时 `cell.paras.length`；结果在 6343 写入 `nestedTables`/`nestedTableAnchors`。
- [parse.ts:5445](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/packages/docx-engine/src/parse.ts#L5445)：深度上限 8，之后退化为 flattened model。因此不能将所有显示模型都视为可逆、可编辑 XML 来源。
- [convert.ts:1456](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/docs/src/renderer/editor/convert.ts#L1456)：按阅读顺序把 `{type:'docNestedTable', attrs:{model}}` 插入父 cell，而非递归创建 `docTable`；反向转换在 1783 收集 `attrs.model` 和段落位置。

### 2. 原子节点中已有文字输入，PM 表格选择仍属于外层

- [extensions.ts:3390](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/docs/src/renderer/editor/extensions.ts#L3390)：`atom:true`、`selectable:false`，唯一自定义属性是 model。注释“read-only”不能替代实际行为判断。
- 同文件 3410–3522：NodeView 自己渲染 HTML 表格。`ownTds()` 排除更深表 td；`applyEditable()` 只开放 `editor.isEditable && !cell.nestedTables?.length` 的本表 cell。dirty td 在 focusout（离开整个岛）或 `ai-docs-commit-tables` 事件时提交；变化更新 `paras`、删除该 cell 的 `richParas`，以 `setNodeMarkup` 回写 model。`ignoreMutation:true`、`stopEvent` 拦截输入岛事件；PM 不拥有这些内部文字选区。
- [table-ops.ts:777](https://github.com/ahaodev/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/docs/src/renderer/editor/table-ops.ts#L777)：表格选择支持的是 PM `docTable`、CellSelection 与 `selectedRect`，没有 `docNestedTable` 内部 DOM 选区到 TableMap 的转换。
- 本地 `frontend/src/docx-main.tsx:176–200` 选择上报从 `$from` 祖先找 docxIndex，再按 PM 行/cell 坐标取顶层 anchor.cells。岛内 DOM caret 不会自动成为独立内层来源选区；不能据此给 AI 或 Ribbon 发送内层 cellId。
- 本地 `docx-tables.ts:126–175`：`selectedRect` 后按 `rect.table.attrs.docxIndex` 查 anchors，并在 `baseline.content` 顶层查源表。结构与标题行命令都没有内层表定位。`docx-table-headers.ts:5–21` 只是投影/校验已提供的 source/anchor，不负责发现内层来源。

### 3. 现有 blockId/hash 无法独立定位内层表

本地 `reporting/slides_engine/bridge/edit-docx.ts`：

- 675：blocks 仅为 `parsed.blocks.filter(!hidden)`；817 indexed 仅索引这些正文 block。
- 725–726：`blockId = sha256(sourceSha256 + ':block:' + docxIndex)`；`cellId = sha256(sourceSha256 + ':cell:' + docxIndex + ':' + row + ':' + column)`。
- 851–865：块 hash 是整块 originalXml；直属 cell hash 是 `cellXmls` 提取的完整 `w:tc`。含嵌套表的父 cell 因 `editableCell` 在 450 检测 `w:tbl` 而不可文字编辑。
- 439–444：cellXmls 用深度感知 xmlSegments 提取外层行/格；并没有递归签发 inner table/cell 身份。外层 block hash 可以绑定整个来源快照，但既不表达内层路径，也不能区分同一个父 cell 中两张内容相同的内层表。
- 1007：所有普通操作先从顶层 indexed.get(op.blockId) 找 block；1055–1067 的 replaceCellText 在该 block 直属 cells 中找 cellId，再校验 cell hash/能力；1377–1395 的修改也只落在该外层表状态。

现有 sourceSha256/blockId 可以继续作为根容器身份；内层目标至少需要“由服务端签发、可反查到 XML 路径的 tableId/cellId + 原对象 hash”。仅增加 hash 不够：两张完全相同的内层表 hash 相同，不能靠 XML 字符串全局替换或文本搜索选择目标。

### 4. 本地采集/恢复与提交时机尚未闭环

- `frontend/src/docx-main.tsx:64–71` 只验证顶层 block 的 type、hash 与 blockId；没有验证内层模型与内层 XML 对应关系。
- `docx-operations.ts:351–358` 以顶层 doc.content 与 docxIndex 建立 diff；447–470 的表格分支只遍历直属 cells。内层 attrs.model 改变使父 cell 不相等，在 466 被 `cellAnchor.editable:false` 拒绝；也没有白名单验证 nested model 只能改指定简单 cell 的文字。
- 同文件 653 起 replay 只建立顶层原节点和 blockId 表，没有恢复内层 model 的独立分支。
- `docx-main.tsx:645` 的公开 flushPendingEdits 只调用 pendingHfEditor.flush；本文件未发出 `ai-docs-commit-tables`。必须覆盖光标仍停留输入岛便保存/预览/导出的路径，不能依靠点击按钮恰好触发 blur。

## 最小可行的完整方案

以下是建议设计，尚未实施。

1. **在 inspect 增加独立内层清单，保留顶层 blocks。** 每个内层 anchor 绑定 root blockId，记录从外层表开始的 `{row,column,nestedOrdinal}` 路径、tableId、整张内层表 expected hash；可编辑叶 cell 另签发 cellId 与完整 cell XML hash。ID 由 sourceSha256、根 docxIndex、规范化路径与对象类型派生，避免相同 XML 的同胞冲突。第一版只签发直接嵌套一层、XML/model 坐标完全一致的简单叶 cell；更深层、合并/SDT/修订/不支持标记仍显示并带明确只读原因。路径保留服务端，提交只接受已签发 ID，不接受任意 XML/客户端路径。
2. **逐层使用直属 XML child 定位。** 复用引擎 splitXmlChildren/xmlSegments；在当前 `w:tbl` 的直属 tr、tr 的直属 tc、tc 的直属 tbl 中按 ordinal 寻址。校验 model 坐标映射与原 XML；遇网格占位/跨列等首版不支持情况关闭该目标编辑。禁止全文 indexOf(innerXml) 或仅凭 nestedTableAnchors 选表。后者只表示阅读位置；同一位置可有多张表。
3. **接通输入能力与来源身份。** 本地适配扩展为 NodeView 注入已核验的内层 anchor/cell 能力，只给已签发简单 cell 开输入岛。监听岛 focus/blur 上报内层 tableId/cellId，清空过期目标；不用 `$from` 猜内层选区。根 anchor 与 nested anchor 分开查找，避免破坏现有顶层 commands/section 定位。
4. **采集、草稿重放与 flush 同时落地。** 建议一个明确操作 `replaceNestedCellText`，字段为 root blockId、tableId、cellId、expectedObjectSha256、paragraphs。先把 model 差异严格限制为该 cell.paras 的变化及源 NodeView 既有 richParas 删除，其他内层 table/model 属性必须相等；从父 cell 的变化中剥离已确认的 nested diff，再走现有外层 diff。重放必须验证完整来源身份/原始 hash，再确定性重建同样 model 投影。统一 flush 在读取 editor.getJSON/提交草稿前广播既有 commit event，同时保留 HF flush；不可只补一个保存按钮。
5. **bridge 整批校验、最小字节补丁、回读。** 在原始来源快照上校验所有 ID/hash/能力，随后按请求顺序应用到根表当前 XML。复用固定源 `generate.ts:750` 的 patchTableCellTexts 和 783 的 patchNestedInCell：向根表目标父 cell 提供 `{nested:[..., innerGrid]}`，innerGrid 仅放目标 cell 的段落文字，其余 null。同一批允许不同内层简单 cells 组合；拒绝同目标重复、父 cell 替换、根结构修改、覆盖祖先的格式/标题操作与内层编辑混批，直到有明确组合规则。每次从当前根 XML 取片段，避免先前补丁长度变化使 offset 失效。回读输出实际目标段落并比较，确认补丁生效；同时检查非目标片段字节保持，不能把引擎可能的静默 no-op 当成功。
6. **明确 UI 支持范围。** 本次完成标准是嵌套简单文字可输入→草稿→刷新恢复→保存→重新打开内容一致。对内层结构/重复标题操作返回明确不支持原因，不让 PM 外层选区误操作外层表。`docx-tables.ts` 与 header target 应识别活动输入岛并拒绝对应命令。若要求内层标题行等功能，需要专用 nested active target、表级 hash、模型投影、草稿回放与根 XML 内层替换；现有 `patchTableRepeatHeaders` 可用于抽出的 inner XML，但不能绕过选择与来源验证直接接入。

固定源已具备需要复用的补丁基础：`generate.ts:732–799` 的 CellTextsPatch/patchTableCellTexts/patchNestedInCell；`convert.ts:3356–3381` 的 nested diff 调用及 3416 的 nestedTextsDiff 可作 diff 语义参考。不要把源 convert 的直接 SaveBlock 流程搬进本地保存协议；本地仍应只提交受控操作、由 bridge 校验并生成产物。

## 可验证用例与通过标准

以下均为待实现验证，没有声称已运行通过。

| 用例 | 必须检查的结果 |
| --- | --- |
| 一个外层 cell 有两张字节完全相同内层表 | tableId/cellId 各不相同；改第二张只影响第二张，不依赖 hash 唯一 |
| 内层表位于父 cell 两段文字之间，后接空段 | 修改后表前后文本、空段数量、顺序、父 tcPr 与未改 XML 原样保留 |
| 改内层简单 cell，光标未离开便快捷键保存 | flush 后草稿/请求含新文字；重新打开一致，无丢字 |
| 同 cell 的多段、尾部空段、制表符、换行、中文/emoji、`$&` | 编码/分段契约明确；回读等于预期，非目标段落不被重排 |
| 两个不同内层 cell 连续改字且新文本长度不同 | 两者均保留，第二次定位不使用第一次之前的旧 offset |
| 草稿刷新恢复、撤销/重做、只读/保存中切换 | 模型与 DOM 一致；无权限时岛不可输入；恢复不新增伪来源身份 |
| 篡改 root/table/cell ID、交换同胞 ID、错误 hash、使用旧 sourceSha | 校验失败；没有对另一个目标或新文件套用旧草稿 |
| 内层含更深嵌套、SDT、合并、修订、域/图片等不支持对象 | 显示保留、对应 cell 只读且说明原因；不展平、不误签发简单 cell 能力 |
| 岛内点击结构/重复标题行命令、切换岛外父表 | 岛内明确拒绝；不会错误修改外层；切回外层后其原有命令正确恢复 |
| 内层改字混合根表结构/父cell替换/覆盖祖先操作 | 前后端采用同一冲突规则，错误不产生部分保存 |
| 故意令底层补丁返回原 XML | 输出回读检测到未生效，不能报告成功 |
| 不编辑任何内层 cell | 不产生 nested operation；原文件非目标字节与原有顶层功能保持 |

建议先做限定的 frontend 单元验证（采集、回放、flush、命令目标）与 bridge fixture 验证（来源清单、重复内容身份、局部字节保留、回读），再用真实浏览器输入岛做保存/刷新/快捷键路径验证。无需全量重复测试。本调查未改变发布/导出签发代码；实际实现若触及签发链路，必须保持项目 AGENTS.md 的产物非阻断契约，并为新增可能失败的签发步骤登记故障注入用例。


## 恢复调查复核与真实 DOCX 探针（2026-11-10）

恢复时已复核固定源 HEAD、NodeView、bridge inspect/操作定位、前端 diff/replay 与表格命令。上述主要结论仍成立。以下补充区分已执行证据与待实现能力。

### 已执行范围与结果

探针目录 `/tmp/word-nested-anchor-resume/`，保留 `source.docx`、`inspect.json`、`inspect-output.json`、`probe.mts`、`patched.docx`。源 DOCX 用 Python 标准库 zipfile 写入合法 OPC 最小部件，一个外层 cell 中是段落 before、两张 XML 完全相同的一行一格内层表、段落 after。没有调用浏览器或桌面 Word，因而不代表桌面兼容性或输入岛交互验证。

实际执行命令（仓库根目录）：

```sh
smart_reporting/reporting/slides_engine/node_modules/.bin/tsx smart_reporting/reporting/slides_engine/bridge/edit-docx.ts /tmp/word-nested-anchor-resume/inspect.json
smart_reporting/reporting/slides_engine/node_modules/.bin/tsx /tmp/word-nested-anchor-resume/probe.mts
```

两条命令最终退出 0；探针断言结果：

```json
{"nestedCount":2,"nestedTableAnchors":[1,1],"inspectBlockCount":1,"parentEditable":false,"secondOnlyExactXmlPatch":true,"reread":[["same"],["changed第二张"]]}
```

这证明 `nestedTableAnchors` 不能唯一标识同一段落位置的两张内层表；本地 inspect 未签发独立内层身份；`patchTableCellTexts(root, [[{nested:[null,[[['changed第二张']]]]}]])` 可以只修改第二张。探针对目标文本元素之外的整个根表 XML 做完全相等断言，再重新压包并 parseDocx 回读两张内层表文字。目标 `w:t` 会由引擎添加 `xml:space="preserve"`，不能要求被编辑文本元素自身字节不变。

初次探针曾因环境没有 `python`、系统 Python 没有 python-docx 而未创建 fixture，随后改用 python3 标准库；首轮 XML 断言漏算引擎添加的 `xml:space` 而失败，按真实输出修正目标元素预期后才通过。没有将这些失败记作产品缺陷，也没有隐藏未完成的浏览器验证。

探针导入的是本地 vendored 引擎：已逐字核验固定源与本地 `CellTextsPatch`、`patchTableCellTexts`、`patchNestedInCell` 源片段一致，但 generate.ts / parse.ts 全文件已有差异。因此结果是本地运行证据加固定补丁片段一致性证据，不应声称对固定源整套 runtime 做过运行验证。

### 两个需要写进实现契约的细节

1. 固定源 `extensions.ts:3475–3476` 用 `paras.join('\n')` 比较新旧文本。`['a','b']` 与 `['a\nb']` 会碰撞；`tdParas`（5234）也有依赖 DOM 结构的 fallback。新协议既然传 `paragraphs: string[]`，diff、输入岛 commit、回放与输出回读必须按数组比较，并明确段内换行/制表符编码，不能沿用 join 比较充当完整语义等价。
2. `xmlSegments`（generate.ts:562）只追踪指定 tag 的同名深度，不是通用“直属 child”解析器。原调查的逐层定位要求应实际用 `splitXmlChildren` 验证父壳和直属 `w:tr/w:tc/w:tbl`，或先严格排除 SDT/修订等包装；不能把 `xmlSegments` 本身误认为已拒绝跨包装后代。首版保守能力规则需同时覆盖根/父 cell/内层表，不能仅对叶 cell 调用 editableCell。

### 可独立实施的下一步分工

先冻结一个具体协议：inspect 的根 table anchor 增加 `nestedTables` 清单；每项包含 `tableId`、`expectedObjectSha256`、只读的 model 映射路径、叶 `cells`。客户端路径仅用于匹配已经签发的原模型，patch 不接收路径。操作采用 `replaceNestedCellText {blockId, tableId, cellId, expectedObjectSha256, paragraphs}`，其中 expectedObjectSha256 是原叶 cell hash；bridge 同时通过注册表校验 tableId 属于 blockId、cellId 属于 tableId。首版同根只允许多个不同内层叶 cell 改字，不允许任何其他同根操作混批，避免前后端冲突规则分叉。

- **bridge 实施任务**：新增独立 `bridge/docx-nested-tables.ts`，负责来源清单、路径反查、能力检查和补丁回读；edit-docx.ts 只接 inspect、整批校验和执行入口。先让上面的双同胞 fixture 通过 inspect 身份区分→请求修改第二张→重新 inspect 读出新文字，补错 ID/hash、包装标记、同根混批拒绝用例。该任务不需要修改 frontend。
- **前端协议任务**：新增 `frontend/src/docx-nested-tables.ts` 的纯映射/diff/replay，扩展 DocxAnchor 与 docx-operations 的表格分支。用冻结的清单 fixture 验证只改指定 model cell.paras，允许固定源行为导致的 richParas 删除，其余属性一律拒绝；同时验证不同 nestedOrdinal 的相同内容表与旧来源草稿拒绝。可以与 bridge 按同一 schema 并行实现，集成前必须交换真实 inspect fixture。
- **前端交互集成任务**：在上述两项稳定后接带 anchor 能力的本地 NodeView 适配、输入岛活动目标、统一 flush 和 table/header 命令拒绝；不要修改共享 vendor 来绕过来源验证。以真实浏览器“保持岛内焦点→快捷键保存→刷新草稿→重新打开”验证输入不会丢失，并核验 Ribbon 点击不误改外层表。这一步依赖前端协议与真实 inspect，不适合先宣称完成。

该拆分按文件划分所有权，避免多个任务同时修改 docx-main.tsx 或 edit-docx.ts。验收是可保存和恢复的文字编辑闭环，内层行列结构与重复标题行仍须另立范围；本次独立探针没有证明这些能力。

### 本地前端 diff/replay 实施（2026-11-10）

`frontend/src/docx-nested-tables.ts` 现提供 `getDocxNestedTableTargets(root, anchor)`：仅接收不可变 baseline 根 `docTable`，返回已校验的 `{anchor,node}` 列表。映射使用父 cell 的直属 `docNestedTable` 节点顺序；中间直属段落不影响 `nestedOrdinal`。签发清单的 model 行列、叶 cell 原段落数组逐项校验，重复 table/cell 身份和重复路径拒绝。只读、无可靠 XML 身份的 cell 可保留空 hash/空段落，不能取得编辑能力。

采集先验证已签发 cell 的 `paras` 改动和 NodeView 对 `richParas` 的删除，再将这些变化还原，完整比较整个根表；任何其他 model、祖先、同根普通操作混批均拒绝。草稿回放校验来源、字段、叶 hash、能力、重复目标和整批冲突，再在副本重建相同模型。两个同内容同胞表以及同根不同叶 cell 可独立改字，不按文字搜索或 hash 唯一性定位。

`isDocxNestedParagraphs` 与 bridge 的文本提交约束一致，供输入界面复用：1–1000 段，总 UTF-16 长度最多 20000；空字符串段允许，tab/CR/LF 和其他控制字符、DEL、U+FFFE/U+FFFF 不允许。段落之间的换行使用数组边界表达。真实引擎 `TableCell.paras` 对源 `w:tab/w:br` 无法无损回读，这些来源单元格由 bridge 保持只读；本版不宣称支持段内 tab/换行。

实施阶段验证记录：嵌套 diff/replay 定向用例 27 条通过，另有直属表标题行/底纹/边框 47 条通过。原 `docx-operations.test.ts` 59 条中发现一条既有空正文与 fontSlots 误判回归，已交由 root 处理，不能将该组记作全通过。没有运行全量测试或构建。

跨边界真实 fixture 检查脚本 `/tmp/word-nested-anchor-resume/frontend-map.mts` 读取真实 `source.docx` 的 parseDocx 内层模型与 bridge `nested-inspect.json`，只构造对应 PM 原子节点壳进行纯映射/diff/replay（不是浏览器转换或输入验证）；输出 `{"realInspectTargets":2,"secondSiblingDiffReplay":true}`。断言两个相同内容同胞有不同 tableId，修改第二张生成正确 tableId/叶 hash，回放完整 JSON 等于编辑模型。
