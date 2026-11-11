# Word 已有批注文字编辑：宿主最小闭环计划

日期：2026-11-11。状态更新：独立core、Node bridge与Python reporting/delivery薄桥已接通；Python薄桥通过隔离临时runtime真实执行 `bundle:bridges` 生成的Node dist，并验收ZIP输出及source/output receipt。发布宿主复用既有patch_docx路径已通过真实保存/下载/验收失败非阻断/幂等重试专项；前端UI/草稿恢复/Undo-Redo/浏览器验收未接，不能视为用户功能交付。已交付的独立core与专项证据见 [纯文字core验收](NATIVE_WORD_COMMENT_TEXT_ACCEPTANCE.md)，复杂批注背景见 [调查](NATIVE_WORD_COMMENTS_INVESTIGATION.md)。

## 首次闭环的范围

只开放服务端签发的已有批注纯文字编辑，保留原作者、日期、initials、paraId、原段数量和原富文本结构。无新建、回复、删除、解决/重开；不修改正文comment marks，不放宽普通editableParagraph。第一版可要求批注编辑独立保存：一次请求只含1–200条editCommentText，拒绝与正文、节、notes、修订等操作混批。UI若已有其它草稿操作则提示先保存/撤销，不能静默丢弃。这样能把“只改comments.xml”的字节契约作为首轮验收条件。

## 已核实的真实入口与安全边界

| 链路 | 当前源码 | 后续改点 |
| --- | --- | --- |
| 原文件授权读取 | `report_editor/native.py:216` `read_file`经bind_native_workspace+read_verified_file，核验scope下路径、size、SHA；preview:230起再核expected_sha256 | 继续使用该入口；客户端sourceId/hash仅是比较值，不是授权证据 |
| 发布时重读 | `report_editor/native_publication.py:81` save_revision核context SHA、500操作、12MiB及request digest/预约幂等；约194重读parent.source_file并调用patch_docx | 不另建旁路保存；core失败不得写修改文件或把预约标成功；已有失败预约处理约219保留 |
| Python薄桥 | `reporting/delivery/docx_native.py:13` `_OPERATION_KINDS`现含editCommentText；`_invoke:24`使用真实`run_bridge('doc','edit-docx',request)`、临时目录和source/output receipt校验 | 已接入。测试调用真实Python `inspect_docx/patch_docx` 和 Node dist；不mock `run_bridge`。隔离runtime中由现有`bundle:bridges`脚本生成临时bundle，不覆盖仓库dist |
| Node桥 | `reporting/doc_engine/bridge/edit-docx.ts` inspect根返回独立comments manifest；patch对editCommentText做专用全批/≤200/严格字段检查并调用授权原bytes helper | 已接入。混批、伪造来源、只读target与批内迟到失效均拒绝，不生成输出；成功在独立副本中只修改comments.xml，保留source/output identity及wx覆盖保护 |
| 最终文件写出 | 同桥末尾：输出回读校验后`writeFile(output,{flag:'wx'})`；source/output realpath与inode约983拒绝覆盖 | 所有批注规划及输出保真检查必须在writeFile之前；无效批次不创建output，不修改input |
| 前端来源 | `frontend/src/docx-main.tsx:57–80` WordModel、api.file+preview([])、文件SHA、服务端块/原XML身份逐项核对 | 新增独立comments公开模型；不把批注target塞入段落editable能力 |

### 真实part与关系授权：必须先于core

现有引擎 `packages/docx-engine/src/parse-package.ts:156` parseComments固定读取`word/comments.xml`，而 `resolveMainDocumentPath:30`允许主文档通过包officeDocument关系落到非标准路径；当前edit-docx桥又字面读`word/document.xml`。因此首版收窄为标准布局：真实main必须是word/document.xml，包officeDocument关系唯一且指向该part，doc自己的rels中comments关系恰好一条、非External、解析后为word/comments.xml，实际part存在且Content_Types与comments类型相符。非标准布局显示只读原因；不能一边按真实关系读取别处批注，一边让显示层仍读固定路径。

可复用 `parse-package.ts:41` resolveRelationshipTargetPath解析目标路径（实体解码后含URI/路径规范化），但须先在**原始关系XML元素列表**检查重复Id、重复comments关系、错误命名空间、DTD/实体/非法XML、异常TargetMode和root/局部命名空间重绑定。`parseRels:68`返回Map，重复Id后项覆盖前项，且会丢弃DOCTYPE；它只适合完成严格检查后查找，不足以证明唯一关系。`TargetMode`字段名是targetMode，不是external。

需核对三个层次：包 `_rels/.rels` → main，`word/_rels/document.xml.rels` → comments/settings，comments part自身 `word/_rels/comments.xml.rels` → hyperlink。路径只由关系解析得到，不接受客户端part路径。处理缺失/重复ZIP名称、Unicode path额外字段等包身份问题须沿用源zip gate，并明确实际Word看到的part；不能只看JSZip Map已选中哪项。

`loadDocxZip`（`src/zip-load.ts`）会规范化Strict/别名前缀OOXML、清理story part重复style refs，包括comments。必须用未规范化的受限原包part字节与工具读出的part逐一比对；差异来源首版只读，不把normalized字符串当raw hash。ZIP限额及Word路径处理优先复用源能力；若现有工具不能同时取得受信raw视图，先单独补最小来源检查helper并验证，不能静默跳过字节契约。raw comments UTF-8解码须拒绝替换字符/损坏编码；hash定义统一为原XML UTF-8文本字节，不混用normalized XML或浏览器序列化结果。

### protection、hyperlink与锚点

同桥694–714已有 `hasRevisionProtection`：按实际w命名空间解析documentProtection/enforcement，补vendor仅识别字面前缀的缺口。批注可复用此逻辑及`revisionProtected`结果；但先校验真实settings关系/part，不能只读字面word/settings.xml而遗漏另一路settings。强制保护、未知保护值、无法可信解释的settings/XML均只读；不要只依赖parsed.protection.enforced。首版保守拒绝所有已enforced保护模式，不解释“允许批注”的例外。

core返回每目标 `relationshipIds`，仅代表w:hyperlink的r:id集合。宿主须在comments自身rels中核对每个r:id唯一、存在且关系Type为标准hyperlink，按现有`edit-docx.ts:48` safeLinkHref规则（http/https/mailto，拒绝凭据及异常写法）区分包内/外部关系；不下载、不重写、不新建关系。错误类型、缺失、重复、未支持scheme只读；不要把外部hyperlink的合法TargetMode=External误判为“批注part不能External”的同一规则。无r:id的w:anchor内部链接需单独支持声明；首版无法证明bookmark存在时该目标只读。`text-patch`保留链接位置，但不证明目标有效。

已有批注纯文字操作无正文range授权需求。UI正文定位只是辅助显示，不是身份：w:id、作者、所选文字及PM坐标都不能当服务端targetId。首版核实正文中该id的实际anchor/reference唯一结构并提供只读摘要；重复/孤儿/多故事含糊来源只读，跨段或表格故事不能从单段PM mark猜范围。若未来允许无正文锚的批注，也须独立验收，不隐式放开。sourceId建议由宿主对 `[原文件SHA,真实comments路径,comments关系XML SHA,正文锚点快照SHA]` 派生；父scope/文档revision权限仍由native服务核验，不由字符串证明。

## inspect公开字段与操作规划

Node inspect `model()`当前只有sourceSha256/capabilities/sections/headersFooters/blocks及可选notes。ParsedDoc.comments虽有id/author/date/initials/text/paraId/parentId/done/image（`types.ts:316,2640`），只是显示数据，不含原XML hash/ordinal，也不检查重复身份，不作为授权清单。无需改公共parse或vendor CommentInfo。

计划在服务端model根新增独立结构：

```ts
comments: {
  sourceId, expectedCommentsSha256,
  readOnlyReason: string|null,
  targets: [{
    targetId, expectedCommentsSha256, expectedObjectSha256,
    originalCommentId, ordinal, author, date, initials, text,
    editableText, readOnlyReason,
    anchors: [{blockId, expectedObjectSha256, kind}]
  }]
}
```

core的sourceId在每条target上已有；公开模型可外层承载并由前端展开。不得把raw XML、包路径、任意关系目标发回当客户端写入参数。首版panel按服务端ordinal+targetId列出，parsed.comments仅用于只读兼容预览；同w:id映射不唯一时不显示可编辑按钮。前端下载的源SHA必须与此model一致，显示text/元数据与parsed.comments不一致时阻止编辑对应目标并保留查看/下载。

bridge patch专用收集阶段建议放在现有revisionGroups/notesPlan附近（1067–1106），整批先完成来源检查，再调用resolveCommentText。keys严格为：`kind,sourceId,targetId,expectedCommentsSha256,expectedObjectSha256,text`；不得接收XML/author/date/paraId/done/part/range。收集后从blockOperations过滤新kind，否则现有流程会按普通block寻找目标/报unsupported。首版先检混批并拒绝，不能把targetId强塞blockId。

core限制：source XML字符串≤4×1024² UTF-16代码单元（当前是xml.length，非字节上限；宿主须另管原part字节）、text≤65536 UTF-16单元、批≤200；保留段数，多段以LF分隔，inline原w:t有CR/LF只读；禁止新增/删除段落、孤立代理字符、非法XML字符/实体、CR新文本；支持范围是明确安全paragraph/run/简单rich property及hyperlink，复杂目标只读。重复/缺失/非规范id、重复paraId或来源保护拒绝全部target。目标身份绑定sourceId+完整comments hash+ordinal+原comment XML，整个part变化使旧目标签发失效。core不检查文件权限、ZIP关系、实际part、原保护真实性，宿主必须补齐。

必须维持多层预算：Node request≤12MiB/file≤24MiB/操作≤500；Python薄桥同限；NativeSavePayload/PreviewPayload `native_api.py:37,45`≤500；native_publication≤500/12MiB；前端NativeDraft.copyOperations≤500/12MiB，docx-main collector≤500。新增每个有效目标只产生一条操作，反复编辑同target归并，改回原text移除；200条core限制更小，不能等保存才发现。batch最后一条身份或text失败时core抛错，没有部分XML；宿主不执行writeFile，不签发“修改成功”。

### 保存最小适配

只含批注操作时优先从受信原包副本写core返回comments XML，不传saveDocx(options.comments)，不用PM重建正文。若沿用saveDocx保存空正文决策，则必须像调查适配一样排除hidden块，检查其是否触碰原parts；不满足“仅comments.xml变化”时先修最小适配而非忽略diff。现有桥1792 saveDocx及后续ZIP修补可以借鉴，但不能强行让普通blockOperations承担批注目标。

写出前回读并校验目标text/作者日期initials/paraId，非目标comment片段、原root attrs及未知siblings逐字节保留；原ZIP所有其它part与新增/删除part集合均不变，包括document、extended、Ids/Extensible/people、所有rels和Content_Types。core结果对比原XML替换切片是强证据，单靠parseDocx.comments文字相同不足。最后才执行现有wx输出、hash/size receipt。调用失败只保留原文件和原草稿，不能返回半份下载或冒充成功。

## 前端review、collector与恢复改点

1. `docx-main.tsx:57` WordModel增加独立comments模型；67–80来源核验后验证清单，创建专用controller。不要从parsed.comments反推author/id授权。`docx-ribbon.ts:47`批注按钮仍pending；约393 review分支目前只接`reviewCommands`修订面板。新增独立“显示批注”controller/面板入口，保留现有修订入口；新建批注仍禁用。普通目标可改文字，其它目标显示具体只读原因。
2. comments面板使用baseline服务端text+规范化intent投影。沿`docx-main.tsx:178` NativeTextRevisionIntent与notes doc属性模式，为doc声明`nativeCommentTextOperations`，存入可Undo的PM事务；不改变正文marks或双持可变React数组。不能直接从Node core导入前端（含node:crypto/engine generate依赖）；前端用小型类型/结构校验与既有WebCrypto，只做投影，最终权限仍在桥。
3. `collectOperations:170`在修订normalize与普通docxOperations前，验证doc级批注意图，提取并从普通diff视图移除；校验正文等于允许baseline/未伪造属性，再与现有结果组合并检查独立批次、200/500/12MiB。`docx-operations.ts`现有normalize/replayTextRevisions及普通replay入口不能把未知comment kind静默忽略或降成replaceParagraph。Guard filterTransaction:179必须能拒绝伪造intent，允许无正文变化的合法doc attribute transaction。
4. `docx-main.tsx:277` refresh恢复时，先按原服务端目标/hash验证draft.operations，再恢复doc属性与面板projection，排除新kind进入普通replay。过期/伪造目标明确报错并保留草稿，不猜w:id重新绑定。PM Undo/Redo与面板同一intent来源；通过closeHistory按提交分隔；空操作不历史/不写草稿。现有onUpdate:235负责draft.setOperations，但需验证doc attribute事务确实触发收集及历史，而非只刷新UI。
5. `flushPendingEdits:203`现只flush嵌套表及pendingHfEditor，新增pending comment textarea flush；`native-session.ts:73`保存先调用它再beginSave，可复用。切换目标/面板关闭也要flush或明确取消；来源/hash陈旧时拒绝提交。`setSaving:703`及controller editable同时检查saving/draft.saving/draft.closed/context.editingEnabled/editor.isEditable，恢复期间不写历史。`docx-main.tsx:341`PaginationPreview仍传parsed.comments，需传投影comments才会与panel一致，保持ID与锚不变。
6. NativeDraft已绑定scope/document/revision/sourceSha，重试requestId按原operations保留；同target更新要最终稳定排序/无变化删intent，避免无意义重排改变幂等身份。保存成功明确新revision重开；不能继续用旧targetId改新文件。面板/预览dispose清理，不影响已冻结的XLSX组件。

## 建议实施顺序与成功条件

1. 已完成：宿主来源helper+inspect清单；专项用例覆盖真实关系、原字节、保护、hyperlink及story/Unicode锚点边界，不启用UI。
2. 已完成：edit-docx专用批注分支与Python白名单。Node bridge和Python→Node打包薄桥测试覆盖成功仅comments.xml变化、混批/伪造source拒绝、第一项合法而尾项失效不产物、只读target、源不变与同路径覆盖拒绝；已有receipt/source校验保留。
3. 前端已接线并通过定向集成：独立面板、PM intent/collector/recovery/flush、审阅“显示批注”真SVG入口、保存/readonly/closed锁。当前生产构建已通过真实Chromium修改→Undo/Redo→刷新恢复→未blur保存→下载→新revision重开，保存调用真实Python/Node桥。GUI烟测的API路由仍为替身；新增真实FastAPI ASGI会话专项已通过实际鉴权/导入/预览/保存/下载/修订重开，证据见后节。两层独立验收不冒充浏览器直连真实部署服务，完整批注族仍未完成。

定向验收至少覆盖：

- 授权/来源：错scope/version/source/hash；孤儿/多comments关系、重复rId、External comments、错ContentType、实际路径漂移、非标准main、ZIP重复名、raw/normalized差异；错误输入不覆盖input、不创建output、不清草稿。
- protection：别名前缀/实体enforcement、无enforcement/未知值/损坏settings；只读理由准确。hyperlink r:id缺失/重复/错Type/跨part关系伪装；合法外链保留，无网络访问。
- core接入：复杂来源只读；重复comment id/paraId；中文/emoji/实体/空白/空文本/既有多段；段数变更、inline LF、CR、非法字符；200/500/12MiB边界；混批明确拒绝；尾项invalid没有半结果。
- 输出：独立ZIP+lxml解析实际HTTP字节，整个part目录不变，只有comments.xml授权切片变化，正文锚点及现代附属parts/unknown扩展/所有rels不变；保存重试不二次替换或重建meta。
- UI：无变化不历史/草稿；目标切换、未blur保存；Undo/Redo恢复文字与intent；刷新恢复、陈旧面板、readonly/saving锁；新版本重开后旧目标失效。不能仅测mock panel state或core text。
- 修改保存/签发相关路径时运行AGENTS.md列出的适用非阻断定向回归（含静态签发链守卫）；新增签发可能失败步骤登记既有故障注入测试。严格编辑输入校验失败可拒绝本次修改；产物已生成且身份可读后，验收/门禁失败不得阻止下载签发，也不能标验收通过。

初始计划阶段未改生产文件。后续Node/Python桥接、发布链与前端定向证据见本页更新；core、薄桥及组件集成通过不等于完整批注编辑已交付。

## 前端接线定向证据（2026-11-11）

- 新增browser-safe的docx-comment-text及专用controller，只有服务端source/target/hash清单授予编辑；parsed metadata只能把目标降为只读。PM doc根nativeCommentTextOperations是唯一已应用intent；collector在普通正文diff前取出，恢复先验身份，批注必须独立且≤200条，不支持段数变化。
- docx-main接入收集、Guard、refresh、Undo/Redo、保存前flush和saving/closed/readonly锁；HF直写路径也保留独立批次守卫；PaginationPreview单次投影后以Map映射文字，保持id/锚不变。功能区仅开放“显示批注”编辑既有文字，新建/回复/删除/解决仍未开放。
- docx-comment-text.test.ts 12项、docx-comment-controls.test.ts 8项定向通过。docx-recovery.test.tsx中main批注定向6项通过，使用真实main、Tiptap/PM、NativeDraft、bindNativeSession，证明未blur文字进入保存payload、Undo/Redo及持久化恢复、普通草稿不丢弃、伪造或缺失来源拒绝并保草稿、parser mismatch只读、保存后锁定及验收告警下载可见。初次整recovery文件仅两个新测试重复shell挂载失败，已修并重验上述批注项；未重复完整测试。
- review发现并修复“已有已应用批注→再输入未应用文字→Undo”后的陈旧snapshot恢复缺口：陈旧输入不自动重新授权，面板提供明确“放弃未应用输入并重新载入”；真实PM与main保存会话证明显式重载后能再编辑保存。textarea向该按钮失焦不先flush，避免点击放弃反而误提交；目标切换与关闭仍flush。
- 目视final2截图发现面板位于canvas之后，打开时可能在折叠线下；已做controller open最小修复：scrollIntoView({block:'nearest'})，再对textarea使用preventScroll聚焦（只读目标聚焦select）。新增controller单项先red后green，并复验真实main入口收集/历史/恢复单项通过；final3构建后的新来源烟测证明3次打开均在任何fill自动滚动之前使panel顶部与textarea进入viewport、焦点在textarea且sticky保存按钮可命中。checkpoint与manifest SHA绑定，不跨构建复用旧成功来源。
- docx-ribbon.test.ts原18项通过；新增主视图测试同时断言显示批注按钮包含真实svg path。tsc --noEmit及限定git diff --check通过。
- smoke/docx-comment-gui-smoke.mjs已在root统一final2 build+budget+contract全通过的生产构建上一次执行通过（独立4198端口，session30424 exit0）。真实Chromium核对加载JS与当前static逐文件SHA一致，包含lazy-docx-main-CYj69qvc.js（SHA256 0aca301522fa6097e25df5427785fb029b41a576c627fc4559b7b6b73a44c2da）及icons分包；API路由替身、真实隔离打包Python→Node保存、浏览器实际fetch下载后独立ZIP/lxml核对仅word/comments.xml变化、中文emoji一致、未blur保存、验收warning下载保留、新revision重开与旧source实际拒绝，errors=[]。日志/tmp/word-comment-gui-final-20261111.log，证据/tmp/docx-comment-gui-Aq4MGU/result.json及comments-revision-2.png；保存checkpoint保留，未重复成功来源保存。该证据不能证明真实FastAPI鉴权/HTTP发布会话。
- final3统一tsc+vite+budget+contract通过后，独立4198端口、全新来源/目录完整烟测一次通过（session92182 exit0），旧成功来源未复用未重存。证据/tmp/docx-comment-gui-GliBSX/result.json、comments-open-viewport.png、comments-revision-2.png，日志/tmp/word-comment-gui-final3-20261111.log。本次直接使用当前生产doc_engine/dist/edit-docx.mjs，SHA256 c1a55a650cbef8d9d75602cbc19f2a2300a302a946f65273fe095f5e5aa33add；manifest SHA256 184c94a96f863198c30ffcfaae1ec2169a8e6b6df2eaca50415bbd62538eada5，122个JS逐个回读SHA一致，main为lazy-docx-main-DmCXTszf.js（e367f856ef72dd0c90ab84b3c66c29c1451e6b3ccb56a1c0ec23b1ff878e2250）。3次click显示批注后、任何fill前测得panelTop=553、textarea=823.8125..973.8125（viewport=1000）、focused=true、sticky保存=13.5..45.5且enabled/hit均true；原完整修改/UndoRedo/刷新恢复/未blur保存/告警下载/仅comments.xml变化/新revision/旧source拒绝链均通过，errors=[]，resumedSuccessfulSave=false。API路由替身的限制仍保留，不据此声称真实FastAPI会话已验收。

## FastAPI ASGI会话专项实证（2026-11-11）

- 新增专属test_docx_comment_http.py，复用既有批注source/operation、test_native_ribbon_http_roundtrip.Repository及create_publication；只仓储采用现有内存fixture。实际挂载require_workspace_capability中间件、create_native_import_router和create_native_editor_router，使用真实NativeImportService、NativeEditorService.context_for_session、ReportEditorGrantService、NativePublicationService及ReportDownloadHttpService。未mock handler或context_for_session，未伪设session cookie：先通过真实workspace capability导入，再经真实签名grant兑换303并接收HttpOnly/SameSite cookie。
- 首次执行.venv/bin/pytest -q -s smart_reporting/reporting/tests/test_docx_comment_http.py，session20420 exit0，/tmp/word-comment-http-first-20261111.log记录2 passed in24.69s。真实context/file、带CSRF与Origin的inspect/preview修改、save、签名HTTP streaming下载、幂等重试及新revision入口兑换/文件/预览均通过；故无需生产修复，没有人为制造失败测试。validator唯一受控故障注入抛异常后，HTTP仍200、revisionRegistered=true、validation.ok=false，明确返回native_validation_failed与“文件已保存，但内容或版式验收执行失败。”，下载仍200可读；completions=1，重试未二次保存。
- HTTP下载字节经独立ZipFile/lxml遍历验证ZIP目录相同、全部XML与rels可读、仅word/comments.xml变化且中文emoji批注一致。实证sourceSHA 1ab382713c472cd40590f346d4ee6d2d0091c26d030ab913f801aa069ed1794f，outputSHA 6e79d1969279c8f2ba33e35bb5715f00a788e19556869c1c07a8eed7ace3484c；成功链真实执行8次inspect/patch子进程，每次CompletedProcess.args均核对为node+当前生产doc_engine/dist/edit-docx.mjs（SHA256 c1a55a650cbef8d9d75602cbc19f2a2300a302a946f65273fe095f5e5aa33add），未build、未tsx降级。wrapper仅记录并委托原run_bridge，未替换执行结果。
- 拒绝路径实际HTTP验证：无cookie、错文档/版本、缺失/伪造CSRF和外部Origin均403；旧expectedSha为409/native_source_changed；伪sourceId以及把上一修订批注target带到新revision的preview/save均422/native_operations_invalid。失败未改原文件，伪造save仅留下failed预约而无成功修订。新增第三项仅定向执行-k signed_scope，session76472 exit0，/tmp/word-comment-http-scope-20261111.log记录1 passed, 2 deselected in13.14s：未验签workspace capability导入401；真实签名但scope不匹配404、无native_editor或context摘要不匹配403、伪grant403，均未进入额外引擎或保存。未重复前两项完整测试。
- 边界：这是httpx.ASGITransport调用真实FastAPI中间件/路由/服务的HTTP集成证据，不是mock API handler；仓储为内存fixture，未接外部PostgreSQL，未启动网络listener，也没有把现有GUI浏览器切换为直连该ASGI应用。因此已补齐native router鉴权与HTTP发布会话层证据，但不声称外部部署、反向代理或浏览器→真实服务联合端到端已验收。仅新增test与本文档，未改任何生产模块或签发步骤。

## 发布链定向证据补充

`test_docx_comment_text_host.py::test_comment_publication_preserves_download_on_validation_failure` 实际通过（`/tmp/word-comment-publication-20261111.log`）：隔离打包引擎、作用域工作区、真实NativePublicationService、下载签发及流读取；仅comments.xml变动，中文批注回读一致，源文件保留；validator异常时validation.ok=false且明确native_validation_failed，Word链接仍签发，重复request_id复用修订且completions=1。测试复用现有发布路径，未新增签发步骤；该证据不代表HTTP会话和前端UI已交付。
