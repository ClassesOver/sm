# Word 重复标题行最小对齐（2026-11-10）

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只处理已有来源表格的重复标题行开关，不扩合并/拆分或其他行列命令。

## 源语义与缺口证据

源 `apps/docs/src/renderer/editor/table-properties.ts:131` 的 `toggleRepeatHeaderRows` 通过 `selectedRect` 取得选区，只接受 `top===0`，检查行 `[0,bottom)` 是否全为 `repeatHeader=true`：全true时全部关闭，否则全部打开；前缀外保持。行其余attrs逐字段保持，目标前缀每行均置 `repeatHeaderEdited=true`，包括开关前已经为目标值的行。源不要求单格、固定宽度、矩形或structureEditable。源Ribbon `components/Ribbon.tsx:3431`、App命令表 `App.tsx:757` 已接通。

独立真实built RED `/tmp/word-repeat-header-gap-built-red.log` exit1，由 `frontend/smoke/docx-repeat-header-gap-probe.mjs` 实际Python生成3×3、总宽9000twip且每列3000twip的DOCX，在HEADER0内定位。插入行已enabled，重复标题命令存在但disabled，title明确“尚未接入严格写回协议”，pageErrors=[]。因此缺口在命令和严格写回，并非来源夹具不可编辑；不以整个复杂表格完全不支持概括现状。

## 最小实现与可核验边界

- 宿主 `docx-tables.ts` 复用现有PM selectedRect/tr.setNodeMarkup，按上述源前缀语义调用，保全部未目标attrs。直接来源table/hash由既有加载身份建立；前端不使用structureEditable或固定宽门槛。嵌套表未有独立顶层来源anchor，当前仍不能借用父表身份执行，作为明确剩余范围。
- 单一新操作 `setTableRepeatHeaders` 带blockId、expectedObjectSha256、expectedRowCount、prefixRowCount和完整headers布尔终态。prefixRowCount为本轮触及的最大前缀，使多次不同前缀切换的结果及源repeatHeaderEdited标记均可精确草稿回放；不只记录最后一步导致前序切换丢失。后缀必须与来源相同。null、行数不符、外来hash、额外XML/字段均拒绝。
- `docx-table-headers.ts` 在操作提取时只允许这些row标记变化；其余table、row、cell、文字等必须与来源完全一致，同表其他编辑先保存。开关还原原标记则不产生持久操作。PM真实history支持Undo/Redo，draft由既有NativeDraft持久化。
- bridge `docx-table-headers.ts` 复用源引擎splitXmlChildren处理直接tr/trPr/tblHeader；不枚举嵌套tr，不重新生成表格。只对实际布尔状态变化的行插入/去除tblHeader，原本off值0保持原字节；其他tblPr、行属性、单元格、合并和嵌套内容保留。桥先检查可信源table身份/行数/前缀/严格字段，再写入，保存后独立parseDocx检查最终headers，并保core及其他部件。

## 当前验证

helper首次RED `/tmp/word-repeat-header-helper-red.log`（新增模块尚不存在），实现后 `/tmp/word-repeat-header-helper-green.log` 两项GREEN。PM首轮 `/tmp/word-repeat-header-pm-directed.log` 30GREEN/1RED，发现仅headers终态不能回放源对已true首行的repeatHeaderEdited标记；补prefixRowCount后 `/tmp/word-repeat-header-pm-green.log` 两文件31项GREEN，覆盖两行混合前缀全on/alloff、非首行不可用、真实Undo/Redo、draft逐字段回放、无structureEditable门槛、XML嵌套表/原off值/其他属性保留与身份行数拒绝。

新 `reporting/tests/test_docx_table_headers.py` 用真实合并DOCX检查保存/重读、全部部件原字节恢复、原行属性保持及5种拒绝。首轮 `/tmp/word-repeat-header-python.log` 5项拒绝通过，正向因仍调用旧dist/edit-docx.mjs、旧bundle无新kind而RED；按root统一bundle约束未单独构建，不作为生产实现失败或成功结论。最终GUI探针已扩展首次开关→Undo/Redo→刷新草稿→实际Python保存revision2→显式open2→关闭→保存revision3→显式open3，等root统一引擎bundle和frontend build后执行。

生产实现当前冻结等待root统一types/build/budget与本轮窄Python/GUI验收。尚未宣称完整表格对齐、桌面Office或报告后端PDF分页验收。

root要求补齐源active状态后，表格命令新增header专用active查询，Ribbon `aria-pressed` 在初始化及选区/undo变化时更新。标题由“仅六个命令”更正为“六个结构命令及重复标题行”。新真实PM合并首格（colspan=2）夹具以首两行CellSelection切换，明确structureEditable=false仍可用，合并属性保持、exact replay及Undo通过。最终 `/tmp/word-repeat-header-merged-active-green.log` 两文件32项GREEN。普通/合并表均无固定宽门槛；同表其他未保存编辑明确提示先保存。生产再次冻结，等待root统一构建。

root统一bridge bundle `/tmp/word-repeat-header-bridge-bundle.log` exit0后，真实Python最终 `/tmp/word-repeat-header-python-final.log` 6项全部GREEN：合并表前两行开→关、parse/python-docx重读、原行属性c14n及全部文件部件原字节恢复，5类身份/字段拒绝保持。首轮新bundle正向仅因测试误将ZIP目录记录与成员顺序视为文件身份失败，修正为非目录成员集合及逐文件原字节比较后通过；未放松文件内容断言。frontend最终统一build/GUI尚待root READY。
