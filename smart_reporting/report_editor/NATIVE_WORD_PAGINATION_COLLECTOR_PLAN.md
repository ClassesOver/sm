# Word 注释与多栏分页接线：下一阶段最小计划

2026-11-10，只读调查结果；本阶段未修改生产代码、未执行构建。固定参照 `/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。这是尚未完成的全量对齐范围，不能据普通单栏 HF 验收计为完成。

## 可定位的实际差异

| 输入 | 固定源 App.tsx | 当前 native docx-main.tsx | 直接影响 |
| --- | --- | --- | --- |
| 脚注占位 | 3622 `footnoteBandsOf` 扫正文和表格 run；3750 `blockMetaOf` 合入 `footnoteExtraPx/footnoteBands`；3813 `pageFootnotesOf` 用引用行位置归页 | Preview 与 prepareEdges 均未传 `blockMetaOf`；Preview 未传 `pageFootnotesOf` | 脚注占用的正文容量缺失，跨页引用分配及末页奇偶可能错误 |
| 尾注流 | 3534 `noteRenderInfoOf` 用 DOM 测量富文本；3869 `endnoteItems` 按末节宽度；9167 交给 Preview | 两入口均未传 `endnoteItems` | 共享 measurement 已有 appendEndnotesBlock，但实际接收空数组；尾注不会增加真实 cuts |
| 多栏 | 3897 `colMode`，3923 `colFlow`；8242 uniform 栏宽和 measuring-columns CSS；mixed 另有逐块布局通道 | 两入口固定 `colMode:none/colFlow:null`，正文宽度跟随 activeSection | slice 会主动清除 cols；直接改 props 也无法修正浏览器测量宽度 |
| 当前内容 | 源 noteNo 从编辑器标记、parsed.noteNumbers、列表顺序逐级读取，测量缓存随注释/修订显示失效 | 注释支持 draft 操作与 `nativeNotesOperations`，`projectedDocxNotes` 输出文本身份；当前PM存正文引用标记，注释正文富文本在parsed NoteInfo中 | 只读初始 parsed 注释会漏新增/删除/修改草稿；引用标记的当前位置/编号须读实时PM |

已 vendored 的源实现可以复用：`editor/note-dom.ts::measureNoteHeightDom`、分页 `applyBlockMeta`、`appendEndnotesBlock`、`sectionColumns/sectionColGeom`。应机械提取源 App 的小型 collector，不另写估算分页器。`DocxNotesModel` 只声明文本/身份，不能假设其自带源 NoteInfo 全部富文本/样式；当前PM没有注释正文富文本节点，须把实时引用位置/编号、注释操作及parsed原始富文本建立明确投影。

## 最小推进顺序与验收

1. 先做注释分页 facts adapter，输入 parsed、当前 PM doc、当前节和现有注释草稿；复用源样式/DOM测量、编号规则与正文/表格引用扫描。输出 blockMetaOf、pageFootnotesOf、endnoteItems、beneathText，Preview 和 prepareEdges 共用同一份当前事实。不得把 readonly/复杂注释一律禁用作为修复。
   验证：先用下列脚注/尾注浏览器失败探针建立 RED；再验证新增、修改、删除、格式草稿与下载重开后的 cuts 一致。字体等待结束后测量，仍保留异步过期保护。
2. 提取源 colMode 判定，先接 uniform 的完整 CSS 与测量宽度，再接 mixed 每块布局/column-flow 通道，均供正文、Preview、prepareEdges 共用。不能只把 colMode 从 none 改成 uniform/mixed。
   验证：固定源和本地同夹具比较实际测量 blocks/cuts/regions；正文光标换节不应改变同一文档的分页事实。uniform 完成不能据此计 mixed 完成。
3. 最后补 live blockPlans 与分页语义接线审计：源 blockMetaOf 还含 keepNext/keepLines/widow/tableRowFlags/现代兼容属性。注释占位接入时不能覆盖这些原有约束。先检查本地 DOM 已携带的事实，只补缺项，不重复注入。
   验证：标题 keepNext、不可拆表格行、跨页脚注引用行、continuous/nextColumn 和页码重启组合；统一 build 后只跑受影响定向回归与最终静态 GUI。

## 明确的失败探针规格（尚未执行，不作为通过证据）

- 尾注：单节正文高度略低于一页，插入/修改一条足够高、可拆为多行的尾注，使固定源从一页变两页。开启奇偶不同。实际 UI 打开 Preview 记录 cuts，再从 Insert 插入 footer 页码；断言目标为 even 且下载 ZIP 的 even footer 改变。当前两入口遗漏 endnoteItems，预计仍按正文一页选择 default。使用真实 DOM 宽度/字体，不以手工高度 stub 代替浏览器失败。
- 脚注：两段正文累计约一页，首段含一条多行脚注，让脚注带占位后第二段移至下一页。另补引用在长段末行和表格第二行的夹具，核对引用行归页。当前未传 blockMetaOf，预计分页容量及末页变体与源不同。beneathText 单独核对落点，不只数页。
- uniform 多栏：相同双栏的长正文，在源上刚好一页、在全宽单流上需要两页；比较实测行宽/blocks/cuts 与源，最后检查 footer 变体。当前固定 none 会清除 cols。
- mixed：首节单栏、后节双栏且 continuous/nextColumn；比较 regions、连续节的物理页复用和最后 logical pageNo。增加光标在首/末节间移动后重复打开菜单，确保分页不随当前光标纸张宽度变化。
- 异步失效：fonts.ready 或图片 decode 等待中改变注释、注释格式、栏数/栏宽，旧菜单结果必须拒绝提交；新开菜单重新测量。保持不写草稿、不移动正文 selection 的既有契约。

以上需要运行真实 Chromium 和实际 Python patch/ZIP；当前 HTTP mock 验证不能升级表述为生产 HTTP/桌面 Office 等价。

## 脚注第一项真实失败证据（2026-11-10）

隔离 `frontend/smoke/docx-footnote-pagination-probe.mjs` 复用既有GUI路由夹具，通过临时副本注入5英寸页面、10行正文和实际Python `insertNote` 生成的480字脚注；不修改既有共享smoke/prod/static。真实Chromium打开本地Preview，另从实际文件解析同一NoteInfo，以vendor `resolveNoteStyle/noteRunStyle/noteRowMetrics/measureNoteHeightDom` 得到200.546875px脚注（正文页容量384px）。对同一当前DOM blocks调用共享slice，唯一增加源footnoteExtraPx/footnoteBands输入后得到2页；当前Preview仍为1页。`/tmp/word-footnote-pagination-probe-red.log` 退出1，断言明确为当前cuts须等于带脚注占位cuts，pageErrors=[]。首轮探针误传ArrayBuffer给Uint8Array API的测试错误已修正，不作为产品失败证据。

当前actual `[0,269.6642]` 一页，对照cuts为 `[0,166.6017]`、`[166.6017,269.6642]`；引用行band offset由真实DOM的noteRefOffsets测得，不是手工位置。该探针证实占位遗漏，尚未验证复杂表格/拆段归页或固定源整个App运行等价。

进一步源码调查纠正：服务端 `bridge/docx-notes.ts:118` updateNote虽删除中间NoteInfo.richParas，实际保存经源 `notes.ts::buildNotesXml`，对同段落数量文本改动使用 `patchParagraphTexts` 保留真实run格式；不能把纯文本projectedDocxNotes直接给DOM测量，也不能保留旧richParas导致显示旧文字。接线前优先复用该写回后的实际注释XML再由源parser读取（必要时复用现有ZIP/parse-off-thread做仅注释part变更的内存投影，不提交草稿或保存），而非另写字符格式继承算法。未变注释可直接使用parsed NoteInfo；新增/删除/修改按现有操作id分配和同源XML规则更新。若要抽取更轻的reader，需连同源noteParagraphReader的样式解析上下文机械抽取，不能用standalone无样式reader替代。当前不改共享生产以免构建竞态。

## 脚注单阶段共享接线（2026-11-10）

root开放生产窗口后新增宿主 `src/docx-footnote-pagination.ts`，未修改解析协议、源parser或保存协议。`currentFootnotes` 无脚注操作直接返回parsed富文本列表，不读取ZIP；有脚注操作才按已有projectedDocxNotes分配id，复用源loadDocxZip（既有解压边界）和buildNotesXml在内存替换footnotes.xml，再用现有parse-off-thread解析实际保存同规则的富文本/样式。updateNote按服务端相同方式移除中间旧richParas，让buildNotesXml决定原XML最小文本补丁或回退重建；绝不拿旧run文本当新文显示。

`footnotePagination` 从当前PM顶层正文/表格后代读取docNoteRef位置、id、首见编号（包括合法0）；保留NoteInfo.richParas/noRefMark/spacing，使用源resolveNoteStyle/noteRunStyle/noteRowMetrics/measureNoteHeightDom和源估算回退。源footnoteExtraPx/footnoteBands交给同一分页器，其noteRefOffsets读取真实标记行；pageFootnotesOf按同band位置和源pageOfY归页。每次请求独立测量缓存，在fonts.ready之后建立。

main的Preview与prepareEdges共用prepareFootnotePagination。两者都等待当前投影/字体，并用正文doc、草稿操作、activeSection和生命周期身份拒绝迟到结果；Preview额外用request id，关闭后旧请求不得再打开。没有新增ribbon/Insert菜单代码。尾注及多栏输入仍未接线，保持后续缺口。

验证记录：

- 原始真实占位探针 `/tmp/word-footnote-pagination-probe-red.log` exit1 → `/tmp/word-footnote-pagination-probe-green.log` exit0；实测480字/200.546875px脚注，使当前Preview准确从1页变2页，cuts与相同当前DOM的源bands输入一致。
- 扩展真实GUI `/tmp/word-footnote-pagination-live-gui.log` exit0：titlePg文档长脚注2页，Insert footer页码命中default；未保存改短注释后Preview1页且只显示新文，删除后仍1页且无脚注，再Insert footer页码命中first；同一次实际Python保存/ZIP回读确认default+first目标操作及notes=[]，pageErrors=[]。身份/修订HTTP仍为替身，未把它当生产HTTP证明。
- `src/docx-footnote-pagination.test.ts` 4项GREEN：无改动返回原rich NoteInfo且空bytes无需解包；实际Python生成含粗体脚注的ZIP，改文字投影保持粗体且run文本为新文，删除及新增id；等待ZIP后身份变化拒绝；实时表格标记编号7、split band在第二页归页、移除当前引用不占位。日志 `/tmp/word-footnote-collector-tests.log`（另最近定向四项在 `/tmp/word-footnote-final-directed.log` 中均通过，该次额外main测试因既有mock不完整而失败，不能称整批通过）。
- main四项既有边缘/生命周期定向GREEN `/tmp/word-footnote-main-regression.log`；新增真实主视图在fonts等待中经合法UI删除注释，旧prepareEdges在分页测量前拒绝，1项GREEN `/tmp/word-footnote-font-stale-green.log`。最初测试直接插入无身份引用被现有Guard拒绝，已改为合法UI删除，不把夹具错误当产品错误。

本阶段未执行build；最终静态产物由root统一构建后做受影响窄验收。复杂拆段、嵌套表格和beneathText的源全App截图对比未全覆盖，不据普通夹具宣称Word分页全量等价。

最终本批tsc `/tmp/word-footnote-collector-typecheck-final.log` exit2，未报Word错误，报当前并行CF的workbook-main.ts:1371 NativeRule类型及conditional-formatting-read.ts:47可空字符串两项；已交root处理，不能记全仓tsc通过。Word相关 `git diff --check` exit0；生产代码冻结等待root统一验证。

root review补编号有效性：源docNoteRef schema默认num=1、convert用parseInt(run.text)||1；异常undefined/null/NaN不能经Number转换写入编号map吞掉fallback。现仅采typeof number且finite，保留合法有限0，其他回退parsed.noteNumbers再列表顺序。新增一项七组边界定向RED→GREEN，`/tmp/word-footnote-number-red.log`、`/tmp/word-footnote-number-green.log`。隔离真实脚注脚本已支持 `NATIVE_GUI_PREVIEW=1`，built模式验证期望页数/实时改删/目标变体/实际保存，避开dev源模块对照import，并检查所有实际JS200/SHA；等待root统一构建后执行。

最终测试readonly attrs构造修正后，全仓tsc退出0 `/tmp/word-footnote-final-typecheck.log`。root统一最终build/budget/contract通过后，`NATIVE_GUI_PREVIEW=1 DOCX_SMOKE_PORT=4196 node smoke/docx-footnote-pagination-probe.mjs` 真实静态验收退出0：长脚注2页→短注释1页→删除1页，页底文本同步改变/消失；prepareEdges目标default→first，实际Python保存/ZIP回读notes=[]，pageErrors=[]。115个实际JS全部200且SHA与磁盘一致，`builtChunkIdentityVerified:true`。日志 `/tmp/word-footnote-final-built-live.log`，身份 `/tmp/word-footnote-final-built-identities.json`；main `lazy-docx-main-CqLnApu1.js` SHA256 `ee875305eacf99ac7d98e63b293c48bda795a955a911f75c5a54a63a65e232f6`。未重复旧HF全链或select-all整链；尾注、多栏及复杂表格覆盖限制保持上述状态。

## 尾注下一阶段只读真实RED（2026-11-10）

固定源App.tsx:3869以末节内容宽度、实时noteNo和源noteRenderInfoOf生成endnoteItems（含richParas/noRefMark/metrics）。共享分页已有appendEndnotesBlock：在正文totalHeight+trailingSpaceAfter之后追加虚拟尾注块，首条加FOOTNOTE_SEPARATOR_H，每个尾注对应lineBox，widowControl=false，section沿正文最后节。当前main未传endnoteItems，算法存在但无输入。

新增隔离 `frontend/smoke/docx-endnote-pagination-probe.mjs`，临时复用既有脚注真实GUI夹具改为实际Python插入尾注，不改生产/static。两项有效失败：

- `/tmp/word-endnote-pagination-probe-red.log` exit1：正文269.6642px本应加尾注后两页；真实472字尾注DOM测量200.546875px，经源appendEndnotesBlock后flow494.211075px、cuts两页，当前Preview仍一页；pageErrors=[]。
- `DOCX_ENDNOTE_EDGE_ONLY=1` 的 `/tmp/word-endnote-edge-probe-red.log` exit1：titlePg文档实际Insert footer center并由Python保存，提交variant=first；长尾注应使末页为第二页/default，断言明确first!=default。没有只拿算法推断目标，实际保存操作证明缺口。

待root确认的最小提炼：共享XML投影按kind参数化（脚注wrapper保持现接口）；源note DOM度量提小helper；新增endnoteItems使用最后节宽度+实时PM编号；main既有共享准备返回脚注props和endnoteItems，Preview与prepareEdges同传。既有appendEndnotesBlock无需修改。仅有尾注草稿才内存ZIP重解析，未变仍直接用parsed NoteInfo；新增/改/删保持同保存richRuns规则和await身份失效。当前此阶段仅探针/文档，未实施生产改动、未重复脚注完整测试。

## 尾注最小实现与dev验证（2026-11-10）

root确认窗口后，`currentDocxNotes(kind,...)` 参数化原XML投影，保留currentFootnotes wrapper。`noteNumbers`和`measuredNote`机械复用现有度量路径，`endnotePagination`只按源规则生成末节宽度的PageNoteItem列表；main共享prepareNotePagination同时为Preview和prepareEdges传endnoteItems。未改Ribbon/菜单、解析协议、保存协议或vendor分页算法。无尾注草稿仍直接返回parsed列表；有改动保持实际保存XML的richRuns继承和等待后身份校验。

两项真实RED的根因已在同一个完整dev链验证GREEN：`/tmp/word-endnote-pagination-probe-green.log` exit0。初始长尾注2页，cuts逐字段等于源appendEndnotesBlock输入；titlePg的footer准确default；未保存改短尾注后1页且页底只显示新文，删除后1页无尾注；再Insert footer命中first；实际Python保存/ZIP确认endnotes=[]、default+first操作，pageErrors=[]。`/tmp/word-endnote-edge-probe-green.log` 为edge模式的同链补证（该模式初次只记录页数，最终实际保存仍断言default+first）。未重复脚注完整GUI保存链。

定向 `/tmp/word-endnote-shared-regression.log` 9项GREEN：7项collector含原脚注契约、新增尾注无改动零解包、实际保存XML保粗体且run文本更新、新增/删除、ZIP等待失效、末节宽度与实时编号；2项主视图fonts等待中删除注释拒绝迟到分页。末项测试随后改为真实endnote标记，单独重跑 `/tmp/word-endnote-font-stale-green.log` 1项GREEN。最终全仓tsc `/tmp/word-endnote-final-typecheck.log` exit0，Word相关diff check exit0。生产freeze等root统一build后跑built尾注live探针；尾注当前未记为最终静态验收完成，多栏尚未实施。

root统一最终build（`/tmp/office-endnote-cf-cellis-budgetfix-build.log`）、budget/contract通过后，`NATIVE_GUI_PREVIEW=1 DOCX_SMOKE_PORT=4196 node smoke/docx-endnote-pagination-probe.mjs` 最终静态验收exit0，日志 `/tmp/word-endnote-final-built-live.log`。长尾注2页→短改1页→删除1页，当前页底文本同步；prepareEdges default/first与实际Python保存ZIP endnotes=[]断言通过，pageErrors=[]。115实际JS全部200且SHA与磁盘匹配，builtChunkIdentityVerified:true；身份 `/tmp/word-endnote-final-built-identities.json`。main `lazy-docx-main-93HcAAgm.js` SHA256 `50bbd1517ea3530990aa42b27e6fb4ed94bec7e0df41ef30cc87e25ca30f6261`。未重复脚注旧完整GUI链，生产/static保持freeze；多栏与前述复杂分页覆盖范围仍是后续缺口。

## uniform 多栏第一阶段（2026-11-10）

固定源App3897判uniform/mixed，8242统一多栏CSS及measuring-columns真实栏宽；3690 canvasSection固定首节，5395 mixed另需columnLayoutSpecs、5411跨节sectionWidthSpecs和收敛通道。当前先接uniform，mixed未完成，不以none适配计为源等价。

隔离 `smoke/docx-columns-pagination-probe.mjs` 实际Python生成5英寸纸、20短段/双栏/间距24px。`/tmp/word-uniform-columns-red.log` exit1：当前Preview2页，同当前DOM按源栏宽180px（border-box含padding276px）和源分页器为1页/两列regions。另两节差宽光标probe `DOCX_COLUMNS_CURSOR=1`，最初未先定位首节、初始光标本就在末节导致假通过，修正夹具后 `/tmp/word-columns-cursor-width-red.log` 有效exit1：首节测量end1281.85、末节测量end886.54，同文档仅光标变化便改变cuts。

root授权后新增docx-columns.ts机械保留源判定，并独立返回sourceMode（mixed事实）和当前已接通的colMode；uniform CSS使用源column-count/gap/fill与测量栏宽，复用现有shared measurement class恢复机制。syncSection仍向Ribbon更新activeSection编辑锚点/页码格式，但canvas用首节几何；Preview及prepareEdges均从同column facts取section/colFlow/colMode。未更改源分页算法。mixed当前仍走none，测试这一行为仅阶段记录，后续mixed接线必须改为源期望，不能固化为最终契约。

dev证据：

- `/tmp/word-uniform-columns-green.log` exit0：原uniform RED变1页，真实栏宽输入与源cuts相等。
- `/tmp/word-columns-cursor-width-green.log` exit0：光标明确首节→末节的cuts完全不变；这证明分页不再随光标变化，尚不证明跨节差宽每段已按源sectionWidthSpecs渲染，后者仍为mixed/width后续。
- `/tmp/word-uniform-columns-edge-save-green.log` exit0：真实canvas computed cols2、width480、首段left600.5/末段804.5跨栏；Preview退出后测量class已恢复。titlePg的一页footer正确first，实际Python保存ZIP columns保持2且未产生layout操作，正文保留；重开Layout切1栏后computed column-count:auto/width480/无uniform class/page-gap0。pageErrors=[]。此夹具未覆盖多物理页CSS列/脚注/表格组合，不能声称正文布局全面完成。
- `/tmp/word-uniform-columns-directed.log` 5项GREEN：源uniform判定/首节几何、mixed阶段边界、测量变量/移除栏恢复，以及既有main固定首末目标/等待几何失效两项。

当前uniform代码冻结等待统一build；mixed的逐块width/column specs及收敛、continuous/nextColumn/RTL/不等宽组合仍在完整目标内。

## mixed/continuous/nextColumn 共享宿主布局桥（2026-11-10）

真实RED `/tmp/word-mixed-columns-red.log` exit1：首节单栏、后节continuous双栏24短段，当前Preview2页；同当前DOM调用源columnLayoutSpecs/setColumnLayout/widthPassGate收敛后为1页，两个regions和双列cuts明确。早期12段夹具两路径恰好1页，不计失败证据。

授权后 `docxColumnFacts` mixed已正式返回mixed，不再none降级；原阶段测试同步改为源mixed期望。新增 `docx-mixed-columns.ts` 同步布局桥，正文调度/Preview/prepareEdges都以当前节、HF/注释facts调用同一入口。复用源measurement/slice、sectionWidthSpecs、columnLayoutSpecs、setColumnLayout和LayoutBatch，合并时列宽优先、dx/dy相加；源widthPassGate窄宽循环钉住，最多8轮仍未收敛返回显式诊断，由main作为软警告，不当完成/不阻断下载。正文只对docChanged/native-section-layout调度RAF，纯deco事务不触发草稿循环；关闭/新请求/正文及草稿改变使异步准备失效。

实际native extensions.ts:7381/7401注册PaginationGapsExtension/ColumnLayoutExtension，scoped.css:2995有--col-w，3032用:not(.measuring-columns)中和transform，未重复造另一套CSS布局。多物理页复用源PageGapSpec pullUp=usedPx-physUsedPx、源effectiveTopPx/effectiveBottomPx，source gapLedgerOf/applyGapLedger/pagePaperEdges决定最后纸张高度。初次接ledger漏overlayPages参数导致Preview超时，已修为gapLedgerOf(gaps,[])后重新验证，失败中间日志不计通过。

dev实际浏览器/保存证据：

- `/tmp/word-mixed-continuous-layout-green.log` exit0：24段continuous单→双1页，正文首区width384/后区180，左右栏x600.5/804.5，cuts与同源算法regions一致，footer first实际Python保存。
- `/tmp/word-mixed-nextcolumn-final-green.log` exit0：同栏数nextColumn真实下一栏，2物理页、1gap、height988（2*480+28），当前正文width180/左右栏与源regions对应，footer default实际保存。
- `/tmp/word-mixed-multipage-final-green.log` exit0：continuous64段3物理页、2gap、height1496（3*480+2*28），第二/三页正文位置跨纸张带正确。实际Python保存独立回读body和各节startType/columns全部保持，只有目标HF操作；上述pageErrors均[]。这些正文几何在Preview前读取，不以Preview自身克隆当正文证明。
- `/tmp/word-mixed-columns-directed.log` 7项GREEN：列/节spec合并、源uniform/mixed分类、宽度恢复、main首末目标/等待几何及尾注变化失效。最终Word相关diff check exit0；生产冻结后root统一tsc/build、静态验收另记。

尚未全覆盖的真实差距：源App更完整的表格row/cell gap/重复表头、notes/footer/header gap绘制与effective HF组合、差纸张居中/mirror、RTL/不等宽列循环/长段跨栏的复杂可视效果。当前通用row/cell fallback为cut标记，没有把这些组合当等价。它们仍需逐项源对照探针和增量实现，不能据continuous/nextColumn普通夹具称多栏全部完成。

最终全仓tsc `/tmp/word-mixed-columns-final-typecheck.log` exit0。root统一budgetfix4 build40.04s/budget/contract exit0且未提高cap；按source自然模块新拆section-layout/column-layout后，最终built三链全部进程exit0：

- `/tmp/word-columns-final-built-uniform.log`：1页，实际canvas双栏width480、左右x600.5/804.5、测量class恢复，实际footer first保存、文件columns保持2，重开恢复单栏通过。
- `/tmp/word-columns-final-built-continuous.log`：3页/2gap/height1496，真实正文两栏width180，当前分页、footer default目标及实际Python保存正文/分节startType+columns一致。
- `/tmp/word-columns-final-built-nextcolumn.log`：2页/1gap/height988，下一栏regions及正文几何、footer default目标、实际Python保存分节保持通过。

均pageErrors=[]，各117实际JS全部200且SHA与磁盘一致，builtChunkIdentityVerified:true。新 `lazy-native-docx-section-layout-Ba0OEXDG.js` SHA256 `4d5dfaaeef2755a49a570c2b50afbcf7c592a01a3e08ee86cd0eb9436ca0b046`，`lazy-native-docx-column-layout-C77rvZlZ.js` SHA256 `75c5bc0e7ddc31c9855b18304214c74a2ad8b108759e2024d0af196ea797d710`，main `lazy-docx-main-CycaUIDb.js` SHA256 `6bc8c7f845dad6e9bd9858a15b64836e0a19676453ecf0b40c012f4bf71b5f4b`；汇总身份 `/tmp/word-columns-final-built-identities.json`。未重跑旧脚注/尾注完整链；prod/static继续freeze，上述具体复杂组合缺口仍未宣称完成。

## 单栏不同节纸宽/边距宿主桥（2026-11-10）

固定源 App5411 在单栏时仍应用 sectionWidthSpecs，App8097/paperWidthPx 以最宽纸张建立共享画布，pageLeftPx 居中较窄纸张。原 main 在 colMode=none 时清除布局，遗漏该通道。真实 `/tmp/word-single-column-section-width-red.log` exit1：首节5英寸、末节7英寸时，末节正文仍384px（源期望528px），画布480px（源期望672px）。

最小实现保持 colMode=none，独立标记 sectionWidths；facts 返回最宽 paperWidth，main 仅在非mixed且没有差宽时清除旧布局。既有共享布局桥对差宽单栏调用源 sectionWidthSpecs，并以源 pageLeftPx/pageWidth 生成gap几何。共享测量在节纸宽/左右边距有差异时中和逐块transform，避免宿主平移被重复算进flow坐标。没有新增保存协议或改写文档节属性。

`/tmp/word-single-column-section-width-green.log` 与扩展 `/tmp/word-single-column-width-body-save-green.log` 均exit0：画布672px，首节正文384px、x=paper+144px（96px居中+48px边距），末节正文528px、x=paper+96px。实际末节Insert footer只产生一条可信sectionId操作；Python保存ZIP的body及全部sections等于原件，pageErrors=[]。定向 `/tmp/word-single-column-width-directed.log` 8项通过，最终全仓tsc `/tmp/word-single-column-width-final-typecheck.log` exit0。

冻结前仅补受影响状态恢复窄探针，没有重复旧完整GUI保存链。`/tmp/word-width-uniform-none-state-green.log` exit0：uniform→none→uniform，class true→false→true，width始终480，height空、decos/gaps=0。`/tmp/word-width-mixed-none-state-green.log` exit0：mixed→none→mixed，height480px→空→480px，decos12→0→12，gaps=0；均pageErrors=[]、saveRequests=0。生产freeze ready，等待root统一build后的当前静态差宽验收；旧chunk身份不能作为本轮证据。

## 镜像边距独立RED，暂缓实施（2026-11-10）

隔离 `smoke/docx-mirror-margins-probe.mjs` 使用左右96/48px、逻辑页号从12开始的真实DOCX。`/tmp/word-mirror-margins-red.log` exit1：cuts页号12/13正确，但两页正文均x=paper+96；源mirrorMarginSpecs要求偶数12页x=paper+48，奇数13页x=paper+96，pageErrors=[]。只记录此缺口，未改生产。

后续最小方案待当前静态验收完成后再开窗口：将源mirrorMarginSpecs与当前spec合并，以cuts实际pageNo判断奇偶，并同步gap左右inset；镜像即使节宽相同也需在测量时中和transform。必须以正文实际几何及逻辑页码重启夹具验证，不把物理页序号当逻辑页号。复杂表格/重复表头、HF及注释gap、RTL/不等宽栏等既有未覆盖组合仍保留。

root统一build `/tmp/office-cells-cf-word-width-build.log` 39.81s exit0，budget/contract同prefix均exit0、未提高cap后，本轮唯一差宽built链 `/tmp/word-single-column-width-final-built.log` exit0：真实画布672px，首节正文384px/x=paper+144，末节528px/x=paper+96，3页；末节footer实际Python保存可信sectionId，body及所有sections保持，pageErrors=[]。117实际JS全部200且SHA与当前磁盘匹配，builtChunkIdentityVerified:true；身份 `/tmp/word-single-column-width-final-built-identities.json`。main `lazy-docx-main-Bn6cIeWi.js` SHA256 `bed0a3b003e7199f577e6620ff7b889bd03f8a0d22f67ce54aa01894fd7f168a`；section-layout `lazy-native-docx-section-layout-DauQ5BBm.js` SHA256 `b9523846eb432f59bf664838f3e1176001d9656fd48d8c2b4dc2fda8e2fe4346`；column-layout `lazy-native-docx-column-layout-H-MhHfzD.js` SHA256 `edc6cb9a2604ecb2baa1f1c8345e60951d33748fb8454199b19bf9c7720622f0`。未重跑旧uniform/mixed/notes完整链，生产/static继续freeze，镜像仍为独立RED。

## 镜像边距最小接线与dev验收（2026-11-10）

root开放生产窗口后，复用源mirrorMarginSpecs按snapshot.cuts.pageNo生成位移，先与sectionWidthSpecs相加、再合并列spec以保持列宽优先；单栏仍colMode:none。gap inset改用源pageMargins(nextSection,cut.pageNo,mirror)，没有以物理页序号替代重启逻辑号。共享measurement新增可选mirrorMargins，Preview、正文桥及prepareEdges显式传同一个parsed标记，保证同宽单栏也中和视觉transform。原HF section身份、保存操作协议及source算法不变。

新增测量测试先RED `/tmp/word-mirror-measure-red.log` exit1，修复后 `/tmp/word-mirror-directed-green.log` 两文件5项GREEN，包含原spec合并与共享测量恢复。真实DOM/实际Python保存两组dev均exit0：

- `/tmp/word-mirror-body-edge-save-green.log`：逻辑页号12/13，正文宽336px，左右x=paper+48/+96；gap inset96/48px；evenOddHf=true时Preview分别even/default，prepareEdges实际保存footer default。
- `/tmp/word-mirror-restart13-edge-save-green.log`：逻辑13/14，正文x=paper+96/+48；gap inset48/96px；Preview default/even，实际footer even，证明下一页gap和HF目标都按逻辑奇偶。

两组只产生一条可信来源sectionId的HF操作，body及全部sections逐字段保持，word/settings.xml SHA保持（含mirrorMargins/evenOdd原属性），pageErrors=[]。未重跑旧uniform/mixed/notes全链、未build/static；source/local清单刷新仅SOURCE.md和两个共享分页文件。本轮尚待最终tsc及root统一构建后的静态镜像验收；复杂表格/重复表头、HF/notes gap内容绘制、RTL/不等宽列组合仍按原范围保留。

最终全仓tsc `/tmp/word-mirror-final-typecheck.log` exit0，Word相关diff check exit0，3项本轮vendor清单身份匹配。生产已freeze，等待root统一build；built镜像探针可用 `NATIVE_GUI_PREVIEW=1 DOCX_SMOKE_PORT=4196 node smoke/docx-mirror-margins-probe.mjs`，另以 `DOCX_MIRROR_START=13`覆盖偶数末页。旧差宽built身份不作为本轮镜像证据。

root统一镜像build `/tmp/office-cf-rename-word-mirror-build.log` 40.37s exit0，budget/contract同prefix均exit0且未提高cap后，两项当前built独立链均exit0：`/tmp/word-mirror-final-built12.log`（逻辑12/13，正文paper+48/+96、gap96/48、实际footer default）及 `/tmp/word-mirror-final-built13.log`（13/14，正文paper+96/+48、gap48/96、实际footer even）。两链正文宽336px，body/全部sections/settings.xml SHA保持，只有一条可信sectionId HF操作，pageErrors=[]。每链117实际JS全部200、SHA与磁盘匹配且builtChunkIdentityVerified:true；身份分别 `/tmp/word-mirror-final-built12-identities.json`、`/tmp/word-mirror-final-built13-identities.json`。main `lazy-docx-main-BTvLnO9j.js` SHA256 `7f2ed0fa62ec6bca654ddcedd26ca586fdeb8c51bcab0fbbec6831b22fe7b1ee`，section-layout `lazy-native-docx-section-layout-CtJHosyh.js` SHA256 `35158d2c8a18926b6859e267e44cae184d4c46f6e9c3bea8b12ec653f445810b`，column-layout `lazy-native-docx-column-layout-D3t4TDeD.js` SHA256 `4d4728802d707b86d3e84f1939d4f4befd5bff236da9d185c0adaa02fbabe4bf`。本轮镜像普通段落范围完成静态验收，未重复旧完整链，生产/static继续freeze；复杂表格、notes/HF gap内容绘制、RTL/不等宽列等范围不扩大结论。

## 不等宽长段跨栏独立只读调查（2026-11-10）

镜像built完成后保持生产/static/manifest冻结，仅新增独立 `frontend/smoke/docx-unequal-columns-probe.mjs`。实际Python生成5英寸纸、左右各0.5英寸、显式w:equalWidth=0的120/240px双栏、24px栏距，3个长段（每段重复12次）与titlePg。没有扩展复杂表格/notes组合。

有效RED `/tmp/word-unequal-columns-final-readonly-red.log` exit1：同一未编辑文档首次Preview4页，cuts end为602.7501375、1275.1095125、1918.2501375、2057.492325；只读同DOM共享source snapshot与首次cuts完全一致。源sectionColGeom明确equalWidth=false和widths=[120,240]，columnLayoutSpecs三个长段均返回width240及floatPx120的split，真实正文也装载doc-col-split-float。这证明不等宽算法和columnLineSplits已接通，不能再将缺口写成“完全不支持”。关闭后再次打开Preview变3页，end为544.336075、1275.0470125、1919.086075，pageErrors=[]；无编辑、无保存、probe未调用setColumnLayout或修改布局，分页稳定性断言失败。尚未证明这三页就是源App最终正确页数，不固化该具体页数为目标。

调查初期复用旧mixed参考曾在probe内执行setColumnLayout却未同步gap，出现4→3页；该中间 `/tmp/word-unequal-columns-investigation.log` 不计有效RED。最终独立probe已去掉该写入及旧uniform/cursor分支，仅通过当前生产Preview真实入口重排，再只读观测。

`DOCX_UNEQUAL_EDGE_ONLY=1` 的 `/tmp/word-unequal-columns-edge-only.log` exit0仅为保存边界补证：显式跳过稳定性断言后实际Insert footer，prepareEdges提交一条可信sectionId的footer default，Python保存body及全部sections保持，pageErrors=[]，输出stabilityAccepted=false。首次4页与重排3页都非first末页，因此该夹具只能证明HF身份/保存保持，不能证明prepareEdges页数与Preview已稳定等价。

下一最小方案（尚未实施）：先将宿主widthPassGate历史按当前文档/节布局生命周期持有，真实编辑时reset，普通Preview/prepareEdges重入不重置；按源App.tsx:4036/5402/5550/5794的history、followUp、wrap-width提交顺序调查，不另造分页器。当前桥在每次调用layoutMixedDocxColumns时newWidthPassState，局部最多8轮；源widthPassGate到maxRuns返回false只表示不给下一pass，并不保证所有split shape已经固定，因此宿主不能仅凭gate=false和width签名不变宣称几何收敛。需在下一生产窗口以此RED驱动，核对split几何/flow是否稳定，并复用源后续测量调度及必要诊断；保留非阻断软警告，不能以稳定性失败阻断产物下载。必须补同文档重复Preview、Preview→prepareEdges、真实编辑后重置的窄验证，再单独新增能区分first/default目标的边界夹具。当前只提出源证据支持的候选根因，未把history生命周期差异当已完成根因验证。

## 不等宽重入漂移最小修复：稳定入口与未收敛诊断（2026-11-10）

root授权实施后先复核固定源App:4036的effect内WidthPassState、5402的gate、5550的followUp和5794真实编辑reset。宿主现为同一编辑器持有source history，文档identity、当前节/草稿及图片解码尺寸身份改变才reset；正文RAF、Preview和prepareEdges复用已提交布局，同一未编辑输入不再次推进bounded宽度循环。只持久history仍RED（`/tmp/word-unequal-history-trial2.log`），因此该项不能单独当根因修复。source gate在maxRuns后false并不表示split已固定，桥额外读取source history.sig的split签名变化；变化仍需测量，8轮仍变明确返回converged=false并展示现有软警告。

新增真实main定向 `/tmp/word-unequal-lifecycle-directed.log` 两项GREEN：重复prepareEdges复用布局；正文真实编辑触发重排且同history清空forced pins；原spec合并保持。最终真实浏览器 `/tmp/word-unequal-final-dev-green.log` exit0：同一文档两次Preview cuts完全相同，且与只读同DOM source snapshot相同；真实编辑后两次Preview也相同。实际Python只保存一条可信来源footer default操作，body和全部sections保持，pageErrors=[]。没有固定3页作为期望；probe仅断言同输入稳定。

该证据同时明确 `.docx-notice` 为“多栏布局在 8 次测量后仍未收敛，当前分页需要复核”。因此仅将“重复入口继续推进引起页数漂移”记为修复，**不将不等宽长段最终视觉收敛/源App最终页数对齐记为完成**。保留同输入最后一次bounded产物与软警告符合非阻断原则；下一独立范围需调查split形状最终固定点并与源App真实运行终态对比，不能靠增大轮数或缓存隐藏警告当最终对齐。

本轮未改vendor算法/manifest/static，Word diff check通过。全仓tsc `/tmp/word-unequal-final-typecheck.log` exit2，仅 `workbook-main.ts:1763` 的CF sourceXml类型不匹配，未修改其他agent文件；Word自身无类型错误。等待root处理该并行类型项及统一build，本轮当前静态验收未进行。

root统一build `/tmp/office-removal-word-stability-build.log` 40.45s exit0、budget/contract exit0后，最终built `/tmp/word-unequal-final-built-stability.log` exit0：原文档重复Preview cuts相同，真实编辑后重复Preview也相同；实际Python只保存一条可信sectionId footer default，body/sections保持，pageErrors=[]。117实际JS全部200且SHA与磁盘匹配，身份 `/tmp/word-unequal-final-built-identities.json`；main `lazy-docx-main-wUtPVnqd.js` SHA256 `de8dceb59a2f8523fbc061bae5a8401841abf0dab476922b0601cadf01de77e2`，column-layout `lazy-native-docx-column-layout-B-JU8jYM.js` SHA256 `fb0ce06d13d42f4bbaf7e6b8c37daaa8291702c32fa05cc6592da0cc038682f6`。built未导入dev算法，明确sourceCompared=false。notice保留“8次仍未收敛”；仅重入稳定修复完成静态验收，不代表源App最终split形状或视觉固定点已对齐。

## 源App最终停止协议后续只读核查（2026-11-10）

固定源 `App.tsx:4015–4036` 同时持有FollowUpChain与WidthPassState；`pagination-loop.ts` 的MAX_FOLLOW_UP_PASSES=6、MAX_SAME_REASON=3，重复cause被标repeat、总轮数触顶标cap，均记录stops/log。因此源“停止调度”本身也不保证几何固定点；不能将源最大轮数直接迁为“成功收敛”，也不能凭本地主入口缓存稳定反推源最终shape。App:5618后的只读__pageDebug提供retriggerLog、followUps、loopStops、layoutHealth、colSpecs与slices，适合下一次原App同fixture真实比较。

固定源checkout当前没有node_modules及vite可执行文件；本次尚未启动原App renderer、未取得同fixture的源最终页数/shape。下一步需独立临时renderer配置复用既有依赖、desktop bridge注入同一DOCX，观测上述source debug和真实doc-col-split-float；保持原源checkout与宿主生产/static不变。本段只是协议事实与运行前提调查，不作为源终态验收证据。

## 固定源App真实终态与同字节CSS缺口（2026-11-10）

新增独立 `smoke/docx-unequal-source-app-probe.mjs`：临时Vite配置只alias到固定源packages原文件及已有宿主/engine依赖，缓存/fixture在/tmp；desktop仅注入文件/偏好IO，源App/分页器未mock、未改源checkout、未安装node_modules。初期boot错误为CJS named-export互操作，临时预打包或选择现有ESM分发后，`/tmp/word-unequal-source-app-attempt10.log` exit0、errors=[]。源结果 `/tmp/word-source-unequal-eTGgY2/result.json` 三次间隔1秒采样均2页，followUps=1、loopStops=0、retriggerLog=[width,columns]，layoutHealth无flips。该证据取代之前“未跑原App”的状态，不以早期boot失败当shape证据。

严格同输入复核：两端均读取 `/tmp/word-source-unequal-eTGgY2/fixture.docx`，SHA256 `9bc28e294c02b1eb9767ad5ddc171c1a1788617a25e9e470693ba7c634b0901b`，viewport1600x1000。源 `/tmp/word-unequal-source-final-fonts.log` exit0及 `/tmp/word-source-unequal-9Eq8LL/result.json`：字号14.6667px、lineHeight19.7677px、Cambria/Caladea等完整fallback链、100% zoom，与宿主相同；docDefaults相同（spaceAfterTwips200、line276/auto、sizeHalfPoints22）。源段后距13.3333px，宿主原为10.6667px。

根因：vendor静态CSS已加 `.docx-native .doc-page p` scope，宿主动态docStyleCss仍是 `.doc-page p`，静态8pt的specificity压过文档docDefaults10pt。浏览器断言先RED `/tmp/word-doc-style-scope-browser-red.log` exit1。root授权后新增宿主 `docx-style-scope.ts`，利用浏览器CSSOM只改CSSStyleRule.selectorText内的.doc-page作用域，递归group规则；@font-face声明/条件规则不做文本prefix。没有现成scope helper可复用，使用CSSOM避免手写CSS解析。main挂载动态style后调用，并标记source HF测量原有data-doc-css识别属性；未改vendor/manifest或8pass算法。

GREEN `/tmp/word-doc-style-scope-browser-green.log` exit0：同SHA源docDefaults段后距13.3333，重复Preview稳定、真实HF1条操作保存保持body/sections，pageErrors=[]，8轮未收敛警告消失。宿主当前2页cuts end744.1876375/1391.304825；**仍不同源744.2813875/1350.961075**。源split高度373.78/415.08/156.36，宿主372.78/355.78/56.53，故本批只修CSS覆盖缺口，不以同为2页称完整视觉对齐。剩余split/flow差异单独只读调查，下一方案需基于真实同条件证据。

最终定向 `/tmp/word-doc-style-scope-final-directed.log` exit0：两文件2项，CSSOM多个选择器/:is、media内规则递归且font-face原文保持、原main重复边缘准备/history reset保持。Word diff check0；root要求本子修复freeze，等最终types及统一build。原App probe含临时依赖路径与desktop IO注入，验收范围为真实renderer，不冒充桌面Office或生产HTTP。

最终CSS子修复全仓tsc `/tmp/word-doc-style-scope-final-typecheck.log` exit0，生产freeze，root统一build处理中。剩余flow只读新增候选：固定源App4383在measure/slice/anchor期间加measuring-natural，5391在setPageGaps前移除；styles3127+显式隐藏旧inline/block gap，避免旧cut强制换行影响自然flow。宿主共享snapshot当前仅measuring-columns，没有该App通道。此为下一独立RED方向，尚未改生产或验证为唯一根因，不合入当前CSS窗口。

CSS子修复最终built `/tmp/word-doc-style-scope-final-built.log` exit0（root统一build39.11s/budget/contract均0）：同SHA fixture三个段后距13.3333px，原文档2页且重复cuts相同，无8轮未收敛警告；真实编辑后重复cuts也相同，实际HF一条可信操作保存保持body/sections，pageErrors=[]。117实际JS全部200且SHA匹配，身份 `/tmp/word-doc-style-scope-final-built-identities.json`；main `lazy-docx-main-Nn3ro9Eb.js` SHA256 `94453e94eb4b18c7647c538cccbd34b4ad81b6f88a041bd34ca371b7658e189a`。源cuts/shape剩余差异保持未完成；生产/static继续freeze，下一natural方向只写独立probe/docs。

独立 `smoke/docx-unequal-natural-probe.mjs` 的 `/tmp/word-unequal-natural-readonly-red.log` exit1：同SHA fixture，在CSS修复后的当前正文不提交任何布局，仅临时加source measuring-natural并finally恢复。normal cuts end744.1876375/1391.304825，natural变743.7813875/1212.6017，第三split高度从36.77变234.42，pageErrors=[]，自然flow一致断言失败。这证明旧gap确实污染当前测量；**尚未证明加class后一步就达到原App终态**（源end744.2813875/1350.961075仍不同）。后续最小窗口应复用源App完整状态顺序：measure/slice/anchor在natural，setPageGaps前移除，commit后后续pass再自然测量；用同fixture与源原Appcuts/shape持续比较，不以本次只读natural结果固化目标。当前生产未变。

## natural生命周期与源Preview布局协议最小修复（2026-11-10）

root开放下一窗口后，仅宿主bridge/main修改：每轮measure/slice/spec/anchor期间加源measuring-natural，setPageGaps前移除，try/finally恢复调用前class。bridge返回同轮source PageLayout（cuts/geoms/hfHeights/rowSplits等）；main向原Preview已有layout prop传已提交布局，prepareEdges复用同cuts，不重切带display gap的DOM。原App9122/9179及Preview1085正是该布局/清gap协议，未改vendor或另造分页器。宿主Tiptap在React effect中clearPageGaps曾触发flushSync警告，故宿主在render Preview前同步清gap，关闭后RAF恢复正文，避免effect内突变。

原独立RED转GREEN `/tmp/word-unequal-natural-readonly-green.log` exit0：同SHA normal和临时natural cuts完全一致，end743.7813875/1291.6642，pageErrors=[]。定向 `/tmp/word-natural-directed.log` 4项、`/tmp/word-natural-edge-directed.log` 1项均GREEN，覆盖class异常恢复（原本有/无）、原merge/HF身份、重复边缘准备和真实编辑reset、prepareEdges使用已提交natural cuts而不重新测display gaps。`/tmp/word-natural-final-dev.log` exit0：重复Preview、真实编辑后重复Preview、实际Python HF单操作保存保持body/sections，pageErrors=[]。补充关闭恢复 `/tmp/word-natural-body-restored-green.log` exit0：natural=false，正文1gap、height988px，HF保存后原body/sections保持。

同SHA/字体/CSS条件下，宿主当前两页end743.7813875/1291.6642，split float高度372.78/355.78/234.42；原App仍744.2813875/1350.961075和373.78/415.08/156.36。当前只证明旧gap测量污染已修与三入口同一事实，不称最终split/flow源等价。生产freeze，Word diff check0。全仓tsc `/tmp/word-natural-final-typecheck.log` exit2，仅并行workbook-main-calculation.test.ts:56的泛型mock返回false|R问题，Word无类型错误，未修改其他agent文件；等root修复及统一build。

natural子修复最终built `/tmp/word-natural-final-built.log` exit0，root统一build `/tmp/office-name-removal-word-natural-build.log` 40.09s、budget/contract均exit0。sameSHA重复cuts743.7813875/1291.6642完全一致，实际编辑后也稳定；关闭Preview正文natural=false/1gap/height988，实际HF一条可信操作保存body/sections保持，pageErrors=[]、无收敛警告。117实际JS全部200且SHA匹配，身份 `/tmp/word-natural-final-built-identities.json`；main `lazy-docx-main-BhHCTG4W.js` SHA256 `67d530721bdde72ec2fe003f72c5545b86752ada24fc7e0043ecdd313dacd946`，column-layout `lazy-native-docx-column-layout-BYocAmIm.js` SHA256 `8623bcd31928bbe2fb7c7d750785b255c0b57f469372de4a085499eb576b18fd`。仅natural生命周期/三入口共享事实完成当前静态验收，不扩大为源长段最终视觉等价。

下一阶段剩余只读块证据 `/tmp/word-natural-source-blocks.log` 与 `/tmp/word-natural-host-blocks.log` 均exit0：源三块nLines26/21/20、高527.234375/428.40625/395.3125；宿主25/18/21、高507.46875/369.109375/415.078125。两端canvas480px、padding48px、border0、line19.7677px及首block top0.00795相同，首块高度恰差一行19.765625px，说明剩余差异在line wrapping/split几何而非全局测量origin。未在本批添加修复，生产/static保持freeze。

## Caladea真实字体缺失根因与同源终态闭环（2026-11-10）

下一窗口先读同SHA正文DOM：文本及run marks完全相同，差异仅split/gap。调用两端原probeColWrap(120,240)得源36行/宿主30行；隐藏clone computed fontFamily/字号/lineHeight/宽度也相同，故仅CSS字符串不能证真实字体相同。真实字体证据 `/tmp/word-font-evidence-source.log` 与host.log均exit0：源document.fonts含loaded Caladea，14.6667px同句measureText=273px；宿主faces=[]，Caladea缺失后默认serif=251.525009px。源main加载fonts/fonts.css，宿主之前未迁入任意对应字体二进制，确认为实际glyph宽度缺口而非分页器终态算法。

root授权最小资产迁入：宿主 `src/assets/docx-caladea/` 保留源四款Caladea二进制与原@font-face的family/weight/style映射、Apache LICENSE、来源README和独立provenance.json；只Word懒加载main入口导入CSS，未改vendor/预算/分页算法。6项资产/提炼CSS身份校验通过。现有prepareNotePagination在应用docStyleCss后等待document.fonts.ready，真实浏览器证明初次布局前Caladea regular已加载，probe另实际load四款确保映射可用。

`/tmp/word-caladea-same-input-green.log`、扩展 `/tmp/word-caladea-final-dev.log` exit0：同SHA glyph273px、三段probe均36行；正文nLines26/21/20、高527.234375/428.40625/395.3125、split float373.78/415.08/156.36及第二段inset218.42，全部与原App真实终态逐字段一致；cuts744.2813875/1350.961075误差小于1e-12。原严格deepEqual在float末位误差失败，probe改用1e-6数值容差而不固定页数。重复Preview、真实编辑后重复Preview、关闭正文gap恢复、实际HF一条操作保存body/sections保持，pageErrors=[]、无收敛警告。

本夹具“源长段不等宽split/flow差”已获得同输入实际等价证据；未泛称全部Word字体或复杂组合完成。其他源bundled字体（Carlito/Calibri、Liberation三族、源生成别名、CJK及复杂文字等）仍是完整对齐范围内具体缺口，尚未由本批Caladea四款覆盖。等待最终types与root统一build，生产freeze。

## 中文后备字体最小迁入（2026-11-10）

root新需求“多支持中文字体”授权后复用固定源两个原woff2：NotoSansCJKsc 2,102,776字节、NotoSerifCJKsc 2,809,656字节，总4,912,432（约4.69MiB）。SIL OFL1.1，GB2312子集7445常用字及全角标点；SC全族及GO unicode-range限定四条原@font-face共享二进制。宿主assets/docx-cjk附原许可证、README、4项provenance SHA，均校验匹配，不改vendor算法。Word与XLSX懒入口共享资产；root及criteria agent补两内置思源+五系统菜单选项。Noto不等同宋体/黑体/仿宋/楷体专有原字形，生僻字、源未迁入其他族、服务器PDF注册/嵌入仍有边界。

真实 `/tmp/word-cjk-final-dev.log` exit0：四family均actual loaded、中文12长段4页重复Preview cuts稳定，Home输入Noto Sans CJK SC并Enter，实际formatRange只改4字、Python ZIP确认eastAsia新值、原Latin槽保持，pageErrors=[]。最初业务已成功但保存后revision加载尚未结束即关闭context导致route.fetch失败，probe明确等待networkidle后重跑exit0，未吞异常。后续checkbox agent负责已有东亚槽即时预览链，最终built探针追加选后computed chain断言。

全仓tsc `/tmp/word-cjk-final-typecheck.log` exit2仅并行workbook-ribbon.test.ts:968/969类型错误，Word无类型项，按root要求不重复types。生产assets/import已freeze，等root统一build后分别跑Caladea同SHA终态与中文加载/选择/保存两新链，不重跑旧完整suite。浏览器woff2加载并不证明后端PDF已注册或DOCX嵌入字体；此批只验浏览器与OOXML字体信息保存。

中文首轮built `/tmp/word-cjk-final-built.log` 与只读补证 `/tmp/word-cjk-final-built-diagnostic.log` 均exit1，不能沿用较早仅验FontFace/OOXML的dev成功宣称即时预览完成。实际选中“中文字体”4字的mark已正确含font/eastAsiaFont=Noto Sans CJK SC、fontAscii仍Noto Serif CJK SC，但内层`.doc-east-asian-font` computed chain仍指向旧Serif；这是已保存槽位与即时渲染不一致的真实缺口。后续probe进一步以PM selection.from/to定位每个选中文字text node，读取其computed fontFamily与EA变量并逐段断言Sans，避免仅观察页面任意新字体元素。源resolver对宿主已加载Noto的可用性识别由独立adapter窗口处理，本段不记作已修。

## 浏览器内置CJK字体可用性注册与最终静态验收（2026-11-10）

独立adapter窗口复用源setFontMetricsProvider，只注册两款已迁入SC真实woff2的vertical metrics，先实际load和prefetch再初始化编辑器；其他family仍源fallback，不改vendor算法。本轮源身份与13项adapter定向由root核对，最终统一build `/tmp/office-cjk-browser-font-final-build.log` 40.40s exit0，budget/contract均exit0，未提高cap。

最终中文built `/tmp/word-cjk-registered-reopened-built.log` exit0。probe选PM范围1–5的“中文字体”四字，避开domAtPos在run边界返回outer span的陷阱，读取选中文字内部text node父元素：computed family明确为Noto Sans CJK SC/PingFang SC/Microsoft YaHei/sans-serif，EA变量也为Sans。实际Python生成的修订ZIP含w:eastAsia=Sans且原w:ascii=Serif保持；显式open(2)再次读实际text node，Sans仍保持。四family实际加载，中文12长段首次及重复Preview均6页且cuts逐数值稳定，pageErrors=[]。先前未注册真实metrics的4页不作为期望，修复后未对源App同中文fixture作逐页等价声明。117实际JS全部HTTP200/SHA匹配，两个woff2响应HTTP200且SHA与原资产匹配，身份 `/tmp/word-cjk-registered-reopened-built-identities.json`；Sans SHA c3ed44a467b3a42ad06bd1d95147f169753b6675d244a63c1f1101899de48c42，Serif SHA 8805e730c330fd4940eefa8618b57abc196a0bd1dfe393b7492b88aad0130f37。

同adapter镜像的非CJK字体回退回归 `/tmp/word-caladea-registered-built.log` exit0，117实际JS及四Caladea/两CJK字体HTTP200/SHA通过，身份 `/tmp/word-caladea-registered-built-identities.json`。额外离线严格比较当前built结果与固定源原App `/tmp/word-source-unequal-eTGgY2/result.json`，输出 `/tmp/word-caladea-registered-source-comparison.json`：同fixture SHA9bc28e294c02b1eb9767ad5ddc171c1a1788617a25e9e470693ba7c634b0901b，两cuts end744.2813875/1350.961075误差<1e-6；三块宽240及split style逐字相同（float高度373.78/415.08/156.36、第二段inset218.42），Caladea glyph宽273px相同。重复Preview、真实编辑后的重复Preview、关闭后自然正文恢复、实际HF单操作保存body/sections保持均通过；未仅按同为2页判断源等价。

本轮完成浏览器中文内置字体加载/即时选择/OOXML保存/显式重开与Caladea源夹具静态验收。GB2312子集、生僻字fallback、粗体合成、未迁入源其他族、服务器PDF注册或字体嵌入仍保留既有边界；没有将浏览器验证泛化为完整中文排版或后端PDF字体覆盖。生产/static继续freeze，未重复旧完整测试链。
