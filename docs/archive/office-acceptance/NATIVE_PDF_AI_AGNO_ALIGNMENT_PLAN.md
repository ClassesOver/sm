# PDF 原生 AI 与 Agno 对齐方案

日期：2026-11-11。第 1–5 节保留最初只读源码调查与实施方案；当时没有修改生产文件或运行验收。**本轮已实现范围与运行证据见第 6 节**，不能把历史“未实现”描述当成当前状态，也不能把本轮只读里程碑当成完整 AI 对齐。上游目录 `/home/junge/pros/genoffice-source-full` 的 HEAD 已只读核实为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。下述上游路径均相对于该目录，本地路径均相对于仓库根目录。

## 1. 结论与范围

本地已有真实 Agno 结构化候选、不可变文件身份、真实 PDF 引擎预览、显式采纳与独立修订保存；缺少的是能读取整份 PDF、回答问题、读取/处理批注并调用编辑工具的原生任务层。不能把“完整 PDF AI”替换成只接一个总结接口，也不能让只读回答伪造非空编辑操作来通过现有 schema。

最小正确架构是：一个绑定原生会话和草稿快照的真实 Agno 任务，提供受限 PDF 工具，允许纯回答、澄清、编辑候选和混合结果；写操作先进入任务私有候选，经现有引擎真实预览和用户采纳后才进入 NativeDraft，保存仍由现有原生发布链签发新修订。沿用 Agno 工具循环与取消能力，沿用现有结构化执行器做最终严格结果/候选校验；不重写 provider 协议循环，不借用报告正文 rewrite 路由越过原生身份。

## 2. 固定源的实际语义

### 2.1 四个入口不是同一种编辑请求

| 上游入口与精确位置 | 实际行为 | 本地对齐要求 |
| --- | --- | --- |
| `apps/pdf/src/renderer/App.tsx:7696` `runAiPreset`；`:8232` 总结按钮 | 打开/展开 AiPanel，推送一次 preset；有 `aiSelection` 时使用选区总结，否则总结全文 | 选区可为空；有选区默认限定选区，无选区读取全文；输出回答即可，不需要任何编辑 |
| 同文件 `:8249` 关键要点按钮 | 同一任务入口，选区/全文两种 prompt，输出逐条要点 | 不能仅用当前页或最多一段的内容冒充全文；必须记录实际阅读覆盖 |
| 同文件 `:8355` 总结审阅 | `aiReviewSummaryPrompt`；不随 `readOnly` 禁用 | 读取全文批注便签及标注，按页/作者归纳；不修改 PDF；不能因未开放原位改字而关闭 |
| 同文件 `:8368` 处理便签 | `aiProcessNotesPrompt`，按钮明确 `disabled={readOnly}` | 逐条定位相关正文，按意见修改并回复；模糊意见提问，不猜；必须有写权限与真实可用工具 |

中文 prompt 事实位于 `apps/pdf/src/renderer/i18n/strings.ts:497–523`。审阅总结要求“谁提了什么、哪些已解决、哪些待处理、需要用户决定的事项”，同时明确不修改文档；处理便签要求定位、修改、回复和汇总。不能只依据“处理批注”文字名称把它实现成批注摘要。

### 2.2 真正 Agent 与技能合同

- `apps/pdf/src/renderer/ai/AiPanel.tsx`：`AiPanel` 用 `new AgentLoop`（约 418 行）绑定 `createPdfSkill(deps)`，而非一次静态 completion；工具活动回显由 `onToolExecuted` 收集。`send` 冻结本次选区，`stop` 调用 `loopRef.current?.cancel()`；`requestFileOpConfirm` 使用 AbortSignal，文档更换/面板卸载否决悬挂确认；preset 在忙碌时进入 composer，不能静默丢弃。
- `apps/pdf/src/renderer/ai/pdf-skill.ts`：`createPdfSkill` 返回动态 tools、systemPrompt、buildContext 和 executeTool。上下文含文档名、页数、当前原始页号、只读状态、目录、元信息、批注概况、未保存变更和可选选区（选区上限 12000 字符）。问答先读取再回答；修改才调用编辑工具。全文批注总结是只读；处理意见跳过纯讨论及 AI Assistant 自己的便签，含糊时回复澄清，不删除原意见。
- 同文件规定引用原始页号；页面尚未保存重排时原号不变，实际文件级改写后必须重读并建立新身份。回答中的页号有可点击导航，但导航不是写文件。OCR 内容必须保留识别误差说明。
- 图像生成工具只在 provider 可用时暴露，`createPdfSkill.tools` 动态去掉不可用的 `generate_image`。本地也必须按真实能力裁剪，不能通过提示词假装工具可用。

### 2.3 完整工具面及本地映射

下表覆盖 `apps/pdf/src/renderer/ai/tools.ts` 的 `AGENT_TOOLS`（236 行起）和 `executePdfTool`（3537 行起）的实际名称。上游有工具不等于本地已具备同名 AI 工具。

| 源工具 | 上游语义 / 本地现状 | 对齐方式与缺口 |
| --- | --- | --- |
| `read_pages`, `search_text`, `goto_page`, `get_outline` | 源 `readPages` 每次最多 10 页、24000 字符，标原始页号；`searchText` 从搜索索引定位。`goto_page` 仅导航。 | 本地 PDF.js 已加载页面文本、搜索、目录/阅读界面，但没有绑定到服务器 AI 的可信分页读取工具。新增服务端 verified-file 读取/索引适配；导航返回受限 UI action。目录须从实际 PDF 读取，不把空 model 字段当“无目录”。 |
| `read_annotations` | 源 `readAnnotations`（1336 行）遍历保存与未保存便签线程/标注，含作者、日期、回复层级、覆盖原文，分页截断提示。 | 本地 `inspectPdf` 有 notes/markups、父回复关系、安全读取标记；尚无 AI 工具。当前本地 note model 没有 author/date/state 完整字段，不能回答“谁/已解决”时编造；须扩充可信只读投影，缺字段明示未知。 |
| `markup_text`, `delete_markup` | 源先读精确原文后加标注；删除须先读身份且仅删用户要求。 | `markup_text` 已接入 PDF 批注 Agno adapter：完整读取批注所在页后，仅对唯一完整文字对象提出 `addMarkup`，quads 与固定源高亮色由服务器从可信 PDF 对象重建；真实预览与显式采纳已验证。`delete_markup` 已接入已保存删除及可信未保存标注撤销，支持 ID/类型筛选、来源重绑、真实预览/显式采纳；详见 6.6、6.7，仍缺自由写入口及部分复杂草稿组合。 |
| `add_note`, `reply_note`, `edit_note`, `delete_note` | 源新便签/回复作者为 AI Assistant；先 read_annotations；保留线程，处理意见不是删除意见。 | 本地 `addTextAnnotation`、`replyNote` / `replyPendingNote`、`editNote` / `removeNote` 有真实 schema、线程身份和引擎写回，尚未暴露给 AI。还需 AI 作者归属的可信桥接与复读证明，当前 operation 不接受任意 author 字段。 |
| `edit_text`, `edit_block`, `move_text_block` | 源区分短 run 替换、段落重排、整体移动，不能拿 white cover 假装删除。 | 本地 AI 仅 `replaceText`，真实 PDFium/字体预览会列应用/跳过；没有等价 `edit_block` / move 合同，不得把它们直接降级为单行 replaceText 后宣称等价。逐项补齐桥接、布局/身份及输出验证后开放。 |
| `insert_text`, `list_inserted_text`, `edit_inserted_text`, `move_inserted_text`, `delete_inserted_text`, `add_form_mark` | 源新文字块是有稳定临时 ID 的待保存对象；静态表单文字/勾选有独立工具。 | 本地静态表单入口明确尚未接入，不能用 sticky note 代替真正新增页面内容。新增文本/临时块身份及真实写回合同后开放，列表读取不得伪装成已写入。 |
| `list_form_fields`, `apply_ops` | 源 apply_ops 只接受 op 文档白名单，一次事务一次 Undo；含页面结构、字段值、元信息、新建字段等，不是任意脚本。 | 本地有现成 AcroForm 读取和 `setFormValue`、旋转/删除/重排等受限操作；无 `setMetadata` / `addFormField` 等价契约，字段设计入口禁用。工具能力以本地 schema 实际支持的 op 为准，缺项明确显示。 |
| `image_search`, `generate_image`, `list_page_images`, `insert_image`, `transform_image`, `rotate_image`, `replace_image`, `flip_image`, `set_image_opacity`, `crop_image`, `remove_image_background`, `delete_image` | 源支持读图片对象、素材生成/搜索与图片编辑；每个图片每次保存一种编辑。 | 本地手动插图 `addDrawing(shape=image)` 不能等同全部源图像工具；缺少 AI 素材任务与原图 identity/list/replace/bake 合同。媒体 provider、URL 下载边界、对象身份、预览复读逐项落地后才暴露；不引入 Plotly。 |
| `insert_blank_page`, `set_page_size`, `crop_pages`, `extract_pages`, `split_pdf`, `split_pages`, `merge_pages`, `replace_pages` | 源 blank 是待保存可撤销；其余部分文件操作需确认、先 flush，再即时改文件/新文件，并重读。 | 本地已有空白页、pageSize/crop、mergePages/splitPages 等受限引擎能力，不能直接沿用桌面即时覆写语义。服务端统一生成独立修订或独立子产物，不覆盖源文件；缺少 extract/split-file/replace 等契约仍列待实现。 |
| `set_watermark`, `set_header_footer` | 源各次替换本次会话图章配置；不是清除来源原有水印。 | 本地手工 `setStamps` 通过固定源 buildStamps 生成位图并有结构操作约束。AI 不得伪造该位图或任意替换原水印；需要可信渲染 adapter 和同一预览摘要后开放。 |
| `create_document` | 源可将完整总结/分析另建 PDF/docx/md/html，不等同改当前 PDF。 | 本地 NativeAIService 没有对应新产物工具。应通过已有受控文档生成/登记链建任务子产物并返回真实身份/链接；不能把 Markdown 回复当已经生成的 Word/PDF。 |

## 3. 本地已经实现的边界

1. `smart_reporting/report_editor/native_ai.py::NativeAIProposal`：`summary` 必填，`operations` 为 1–100 项非空；`NativeAIOperation` 的 union 是 Word 段落/单元格和 PDF `replaceText`。`AgnoNativeProposalPlanner.__call__` 已使用 `ReportingStructuredOutputExecutor.execute`，最多两次模型调用；这是真实 Agno 结构化执行，不是 mock。
2. `NativeAIService._context` 同时依赖全局 AI enabled、原生 format enabled、PDF `pdf_text_enabled`；`start_edit` 强制非空选区（服务内 `_selected_pdf_objects` 也验证），原始 preview 重建唯一可写锚点，将人工草稿 replaceText 合入已选文字。`_pdf_candidate` 严格只准 pageId/objectId/newText，由服务器补 expectedTextSha256/sourceSha256。其 prompt 明令不准批注、页操作、图片，因此无法承接完整源工具。
3. `NativeAIService._run_job` 限时生成，复核结构化内容、对象范围，合并完整 base 再调用真实 `editor.preview`；返回应用/跳过项目与 previewDigest。`accept_edit` 二次校验 context、完整 base snapshot 和 PDF previewDigest，返回 operations 供客户端采纳，不保存文件。`cancel_edit` 取消 task 并清空 proposal；状态 GET 使用 shield，轮询请求取消不等于终止后端任务。job 保留一小时、内存中有并发/数量上限；不是持久任务系统。
4. `smart_reporting/report_editor/native_ai_api.py::NativeAIStartPayload` 强制 `selection min_length=1`；`create_native_ai_router` 使用原生会话 cookie、写请求同源 CSRF、document/revision 一致性和 context 校验，提供 start/status/accept/cancel。没有纯回答结果、工具事件或多轮澄清合同。
5. `frontend/src/native-ai.ts::bindNativeAI` 是选区修改建议面板；无 selection 时 start 按钮禁用，显式“采纳到草稿”后才 setOperations/refresh。取消有 generation/AbortController 防旧回包；前端 dispose 只 abort 请求，不能证明服务器任务已取消，尚缺“start 回执未到就取消”的关联取消机制。
6. `frontend/src/native-main.ts::startNativeEditor` 只有 `aiEnabled && editingEnabled && (docx || pdfTextEnabled)` 才挂 AI；`native_api.py::native_context` 的 aiEnabled 对 PDF 也依赖 `pdf_text_enabled`。因此只读文档/未开改字时连问答都不可用。`pdf-main.ts` 的 `home.ai.openAssistant/summarize/keyPoints`（约 301 行）及 `annotate.aiReview.summary/processNotes`（约 529 行）全部显式禁用，理由为未绑定服务端任务，不能按源按钮存在就记为完成。
7. `reporting/structured_output/execution.py::ReportingStructuredOutputExecutor` 有模型能力/传输 schema 选择、严格验证、有限纠错与调用预算；`_execute_mode` 运行 `execution_agent.arun(stream=False)`。`reporting/agent.py::create_reporting_generator_agent` 明确 `tools=[]`、无历史、无 session summaries、retries=0；它是固定阶段无工具生成器，不能仅往 prompt 写工具名冒充 Agent 工具执行。
8. `report_editor/ai.py::ReportEditorAIService.stream_rewrite` / `create_report_editor_ai_service` 使用真实 Agent 的 `arun(stream=True, stream_events=True)`，仅转发 RunContent；tools 为空、要求非空 Markdown 选区，只支持 polish/shorten/expand/professional。`report_editor/api.py::rewrite_report_selection` 用报告会话 `_write_context` 返回 StreamingResponse。可复用事件处理经验，不能直接当原生 PDF 通用 Agent：身份、内容形式、动作和工具均不同，且没有现成 PDF 工具生命周期/采纳协议。

### 3.1 现成 PDF 引擎与不能绕开的限制

`reporting/delivery/pdf_native.py::{inspect_pdf,patch_pdf_with_receipt}` 校验源/输出 SHA、大小和真实字节。`reporting/pdf_engine/bridge/operations.ts::{inspectPdf,operation,operationsSchema}` 提供稳定 source-bound pageId、文字/字段/注释身份、安全可读标记和严格操作白名单。`NativeEditorService.read_file`（native.py）经 read_verified_file 和四维 scope 绑定核对真实源文件；`preview` / `preview_file` 不覆盖源，`save` / native_publication 发布独立修订。

`frontend/src/pdf-replies.ts::validatePdfReplies` **禁止回复与 replaceText/setPageSize/cropPage 同一批**；同一批不能改/删回复根便签。后端 bridge `operations.ts::patchPdfWithReceipt` 同样有真实组合限制（约 200 行）。因此“按意见改正文 + reply_note”不能承诺一次候选一起保存。最小落地选择：先完成文字候选→用户采纳/核对→保存新修订，重读并显式重新定位便签，再生成回复候选；任务记录每条意见阶段和证据。若要求一事务完成，必须先补齐并验证引擎组合能力，不可删校验或自动绕过。当前**服务端 inspectPdf 的 notes 投影**缺作者/时间/状态，应补安全 census；前端 `pdf-main.ts` 批注列表已经从真实 PDF.js 数据显示 `node.author` / `node.timeMs`（约 1210 行），不是整个应用完全不读作者。不能直接相信浏览器自报数据来完成服务端 AI 证据合同；读不到时是 unknown/unsupported，不是没有批注。

## 4. 待实现：最小真实 Agno 任务合同

以下类型/字段是建议合同，**当前仓库未实现**；命名可沿用现有风格，但语义不可省略。

### 4.1 输入、身份与权限

- `taskId`/`clientRequestId` 关联 start/status/events/cancel，POST 幂等并绑定 scope + documentId + revision + sourceSha256 + contextDigest + baseDraftSnapshot；不能只用裸 taskId 越权访问。重开修订是新的身份，编辑中草稿变化后旧候选必须重新生成。
- 请求有 action（ask/summarize/keyPoints/reviewSummary/processNotes/custom）、instruction、expectedSha256、完整 base operations、可选 selection/page range。空 selection 对读任务合法；选区默认范围不自动扩大。正文/批注是资料，不是系统指令。服务器重建对象 ID、摘要、坐标/字体和权限，不信任客户端文件路径、字节或模型自报来源。
- 明确 `readPdf/readText/readAnnotations/proposeEdits/proposeReplies/createArtifact` 等能力：阅读由已授权 read_file 权限决定，不能依赖原位改字 enable；写操作再要求 edit、PDF 文本/特定工具能力及来源可安全编辑。只读任务不注册写工具，服务端各工具再次校验；只读回答不必取得写授权，不伪造操作触发 preview/save。
- 保留原生会话、CSRF、Origin、scope 与真实 source identity；模型不可访问任意路径、网络、shell 或通用执行工具。应用日志仍用 loguru，只记录任务/操作计数/安全错误码，不默认写全文或便签正文。

### 4.2 Agent、工具与结果

- 任务使用真正 `agno.agent.Agent`，通过显式注册的 PDF toolkit 调用读/定位/候选工具。工具循环由 Agno 驱动，前端不解析 Markdown/代码围栏当工具调用。复用已有模型配置，不自造模型路由或 provider free-form 降级。单任务有隔离状态，不修改共享 Agent 的模型/tools。
- 读工具最小集是 `read_pages/search_text/read_annotations/get_outline`；每次读取回执包含 context/source/baseDigest、稳定 pageId、原始页号、范围、对象 ID、内容、truncated/nextCursor、coverage、OCR/不可读说明。全文任务读全或明确“仅已读 X/Y 页”与未覆盖原因，不能把截断当全文。搜索不是已经全文阅读的证据。
- 写工具最小集为 `propose_replace_text/propose_markup/propose_note/propose_reply/propose_note_edit` 对应已经验证的原生操作；工具仅修改任务私有 candidate，不直接改 NativeDraft/源文件。已读对象 allowlist 不应限于用户文字选区：processNotes 可在明确授权任务范围内经 read_annotations→读引用正文→定位可信 ID 后产生候选，不能因此取得整库或其它文档权限。
- 后续按 2.3 表补齐段落/新增文字、表单、图片、页组织、图章与新产物；工具不可用就返回明确 capability error 和真实可行步骤，不能退成摘要后宣称完整 AI 对齐。最小基础合同允许这些工具按来源/权限动态可用，不把未来类型一次性塞进无验证 union。
- 结果为判别 union：`answer`（可含 page citations、issues，零 operations）；`clarification`（问题和依据，零 edits）；`proposal`（解释、operations、完整真实预览回执）；`mixed`（回答 + 可采纳候选 + 各条未处理原因）。只读任务输出非空回答即可成功，不能要求 operations 非空；编辑请求却无可应用操作时应标 unsupported/needs_input/failed，不把 summary 文本当成功改文。
- structured executor 负责末端 Pydantic 结果/候选验证与有界纠错，不承担多轮工具循环；流式 RunContent 只能做回答展示，工具调用/返回、预览、候选完成是独立事件，不能将 assistant prose 当执行回执。输出保留 `toolCallId`、工具名、状态、受限摘要、候选 ID 与 evidence references。

### 4.3 取消、事件与多轮批注处理

- 任务状态至少 running/waiting_input/proposal_ready/completed/cancelled/failed；前端以 taskId + 单调 event sequence 消费，旧 generation 不得再提交。支持 start 返 taskId 前按 clientRequestId 取消；取消 server task/Agno run、工具工作与 pending confirmation，取消完成后禁止迟到候选采纳。HTTP 轮询断开只停止本次 poll，不冒充取消任务；dispose/换文档显式通知后端并有终态。
- 用 Agno 原生运行事件/取消接口及现有服务生命周期，不另造轮询 provider。事件流可恢复或复用现有 status long-poll，但必须呈现读取、工具调用、预览、待确认、完成/失败；SSE 分段回答中断不能偷偷重跑有副作用工具。读/候选工具设计为只读或幂等，保存仍由独立显式动作。
- processNotes 为每条便签保留 note identity、作者（真实可读时）、引用正文证据、action/skip/clarify、拟修改、预览结论、待回复/已回复阶段。AI 自己的便签和纯讨论不反复处理；用户只要求总结时绝不注册/执行删除工具。不从“缺少 State 字段”推断已解决；报告 missing/unknown。
- 用户明确接受正文候选不等于接受自动保存或回复；遇引擎互斥时呈现阶段卡片，由当前 UI 正常保存新修订，校验新身份后继续。跨修订映射不能靠旧页号或“相同文字大概是同一便签”，必须有可验证线程来源/回执；缺失则要求重选，不能静默操作其它对象。

### 4.4 预览、采纳与发布

- 每个写候选调用原生真实 preview，展示 applied/skipped 索引、具体原因、结果 SHA 和 previewDigest；全部跳过不能标“已完成修改”。文本长度/字体限制不靠模型承诺，实际引擎回执是事实。工具“提出”状态不等于“已经写入”。
- 采纳复用 `NativeAIService.accept_edit` 的完整 base snapshot/context/source 校验和 PDF previewDigest 二次核验；前端再比本地操作快照，以一个 NativeDraft.setOperations 历史事务加入候选，Undo 回原 base；只读 answer 不制造 dirty，不触发保存。候选被取消/草稿变化/修订已保存均不可采纳。
- 后续保存仍由 `NativeEditorService.save` + native_publication 完成，不给 AI 直接覆盖原文件能力；文字编辑继续要求实际预览确认。导出/验收失败遵守 AGENTS.md 非阻断约定：实际 PDF/Word 产物身份可读取则保留并签发链接，同时返回 failed validation 与具体原因；安全边界只丢弃对应不可信输入，不能阻断已核验产物下载。

## 5. 建议实施顺序与定向验收

1. **任务/结果合同先落地** → 复用原生鉴权与 Agno，读任务允许无选区、零 operations；验证只读用户能问答、不能获得写工具，answer 不改变草稿，不依赖 pdf_text_enabled。
2. **可信读工具与四个入口** → 总结/要点需要选区/全文双范围；审阅总结读取全部线程/标注并引用页号；验证分页、截断、扫描/OCR、作者/状态 unknown 不编造。四入口不能全部映射同一个 summary prompt。
3. **现有写能力工具化** → replaceText/markup/note 等严格引用读取回执；复用 preview/accept/cancel 和 snapshot；验证越权对象、伪造 ID、并发草稿修改、字体变化、全部跳过、取消竞态和一事务 Undo。
4. **processNotes 真实闭环** → 先处理可实现的文本意见，再保存新修订并重建回复锚点；验证回复+改字互斥的真实分阶段行为，纯讨论/AI意见跳过，含糊请求只澄清，不删除评论。不能以“总结处理结果”冒充已修改并回复。
5. **按工具映射表补剩余能力** → 每项先有真实 engine/schema/source-bound identity/preview/output reread 再启用，覆盖格式/媒体不可用情况；单独创建新文档必须读回真实子产物身份和下载，不以聊天文本代替文件。
6. **新构建后真实浏览器** → 公开 Ribbon→Agent 任务→工具活动→真实预览→用户采纳→Undo/Redo→保存→实际下载→新修订重开，区分读任务与写任务。生产发布链改动要登记并运行 AGENTS.md 指定的非阻断定向回归，不重复完整测试。

本次没有执行这些验收；上述均为下一阶段必须满足的可验证目标。

## 6. 2026-11-11 本轮实施状态（覆盖前文“未实现”的历史描述）

本轮已实现只读 PDF Agno 任务，并接入实际应用与中文功能区。前文工具全表和完整目标仍有效；此节不把只读里程碑当成全部 AI 对齐完成。

- native_pdf_ai.py：每任务独立 Agno Agent 和模型副本，真实工具循环调用 read_pages/search_text/read_annotations/get_outline，读取已验证 PDF 字节及真实 PDFium 引擎结果。实际阅读跨度形成 coverage；搜索不冒充全文阅读，缺少作者/时间/状态为 unknown，未执行 OCR。
- native_pdf_ai_tasks.py：来源/session/context 绑定，受限输入、并发和保存时限，clientRequestId 幂等，开始回执前也能取消，长轮询使用 shield，迟到任务不得提交结果；仅回答，不创建 operations/proposal，不改变草稿或触发保存。
- native_ai_api.py：新增 /api/ai/read/start、/read/{taskId}、/read/cancel，复用实际会话、scope、CSRF、Origin 与修订校验。native_api.py 单独返回 pdfReadAIEnabled，阅读不再依赖 PDF 编辑/原位改字开关。
- pdf-main.ts/native-pdf-assistant.ts：中文真 SVG 图标入口“AI 助手/AI 总结/AI 关键要点/AI 总结审阅”，自由问答与三个不同预设指令；展示实际覆盖、工具调用回执、来源页码导航和警告。回答以 textContent 展示，关闭/卸载显式按 clientRequestId 取消。独立审查发现旧取消失败回包覆盖新任务完成状态，已增加 generation 校验并通过复现回归。

定向证据（不重复完整测试）：

- 生命周期与真实鉴权路由：/tmp/native-pdf-read-http-green2-20261111.log，7 项通过，含禁用编辑配置仍可读、完整来源不变、提前取消、幂等、无 cookie/CSRF/外 Origin/错修订拒绝。
- 实际 HTTP → NativePDFReadService → 真 Agno 工具循环 → 真 PDF 引擎：/tmp/native-pdf-read-actual-loop-20261111.log，新增 1 项通过；两页覆盖与真实内容/页码回执、原字节不变。模型使用 ScriptedModel，不能当成真实 provider 验证。
- 前端面板/既有编辑候选兼容：/tmp/native-pdf-assistant-integration-20261111.log，9 项通过；独立取消竞态 /tmp/pdf-ai-cancel-review-green-20261111.log，1 项通过。
- 可信 reader/并发 Agent 专项初始 12 项：/tmp/native-pdf-ai-final-green-20261111.log，含真实 PDF、长正文、选区/批注、Unicode 搜索及每任务模型隔离。后续新增长批注游标验收另记，不混称已覆盖。

仍未完成：正文修改/便签等写工具化与显式候选采纳；processNotes 修改并回复的真实分阶段闭环；源段落、图片、页面、新产物等完整工具面；逐事件流式输出与实时工具进度；真实 provider 和部署数据库会话端到端验证。现有仅实际对象选择可限定阅读，普通 PDF.js 自由文字选择尚未转为可信服务端对象选区。不得将这些标记为完成。未保存草稿增量状态见 6.3，不再以拒绝所有草稿代替此目标。

### 6.1 集成审查修复与中间构建（最终见 6.2）

- 满 32 个运行任务时，提前取消仍能登记受限取消回执，不得受运行任务上限错误拒绝；新回归先失败后通过：/tmp/native-pdf-read-cancel-capacity-{red,green}-20261111.log。总记录上限仍为 128，取消记录保留一小时。
- 真实浏览器严格复现只读初始化错误：/tmp/pdf-ai-read-built-20261111-initialization-red-01/read-only-initialization.json，旧代码调用 /api/preview 返回 503。现只在编辑开放时读取编辑元模型，只读 PDF 显示及 AI 阅读不请求编辑预览；最终严格浏览器验收以 NATIVE_PDF_AI_READ_ACCEPTANCE.md 的新构建段为准，早期 final-01 不计严格通过。
- 面板复用 native-ai 与 Office 控件样式；补齐 AI 审阅、绘图工具、编辑、转换导出、搜索打印属性、签名保护等组名映射；本地化先失败后与 Ribbon 兼容 6 项通过：/tmp/pdf-ribbon-locales-green-20261111.log。
- 实质取消/初始化修复后的中间构建、预算及预算契约均 exit 0：/tmp/four-format-ai-build-final-20261111.log、/tmp/four-format-ai-budget-final-20261111.log、/tmp/four-format-ai-budget-contract-final-20261111.log。manifest SHA256 为 2c6784d0ba3af88b1206e519d1a3859b2d34f56fa4f1c2a21b0af7cefa6f3b8b。
- 根线程新增任务模块/测试已通过 black(py312)、ruff 和 9 项收集校验；未重复完整测试。最终浏览器将单独记录实际来源和加载资产，不将构建成功等同功能验收。

### 6.2 最终严格浏览器验收：通过

最终构建 manifest SHA256：8f866be146d8f6475808caae7e7175d5ea14767c84867476b3c86f5e80cc6504。构建、预算与预算契约均 exit 0，日志 /tmp/four-format-ai-{build,budget,budget-contract}-verified-20261111.log；不是前轮 2c6784 构建。

真实 Chromium → uvicorn FastAPI → 原生 grant/cookie/CSRF/router → NativePDFReadService → 真 Agno 工具循环 → 真 PDFium 读取验收：/tmp/pdf-ai-read-built-20261111-final-03/summary.json，ok=true，session41906 exit0。四入口各有真实读取、两页覆盖及引用，全部正文源 SHA 一致，整个原生会话只有 5 次 read/start 和 1 次 read/cancel POST，零 preview/save POST，page/console/http errors 均为空。第五个阻塞阅读任务在页面离开后收到 keepalive cancel200，协程实际 CancelledError，后台任务终态 cancelled。根线程独立目视 reviewSummary.png，中文组名、控件、回答、覆盖和引用显示正常。

final-02 保留真实引用导航缺陷证据：新 callback 漏同步活动页高亮；修复为直接复用已有 jumpToPageForIdentity。final-03 保留并通过 is-active、精确 pageId、实际 viewport 与公开页码输入四重断言，没有通过放宽条件掩盖问题。取消传输 keepalive 也有先失败后通过单项：/tmp/pdf-ai-unload-cancel-{red,green}-20261111.log。

本验收模型使用明确标识的 ScriptedModel；真 Agno 工具执行和真实 HTTP/文件/引擎已经实测，真实 provider、外部生产数据库/部署及第 6 节所列写工具等范围仍未完成。详细证据见 NATIVE_PDF_AI_READ_ACCEPTANCE.md。

### 6.3 未保存 PDF 草稿可信投影读取增量

已实现：复用 NativeEditorService.preview_file 的真实编辑配置、来源校验和 PDF 引擎回执，对实际输出再次 inspect；完整 base 深复制与 context/snapshot 幂等，不覆盖来源。result.projection 显示 original/effective SHA、size、previewDigest、操作快照摘要、实际 applied/skipped、原始到有效页映射和选区重绑。工具覆盖采用有效页号，引用包含原始导航与有效页身份；新增空白页无原始导航。常规 replaceText 选区按原身份/expectedTextSHA/输出文字与位置/字号唯一复核后重绑，删除、几何变化、拆分或歧义拒绝。merge/split 页布局仍明确不支持安全映射，不能标记全部 PDF 草稿形态完成。

新增 18 项真实引擎专项按变更分批通过，原空草稿窄回归 6 项通过，包含真实 HTTP/Agno 选区读取不泄露其它正文，以及取消吞回后的迟到模型禁止。全部/部分 skipped 均有实际回执与明确告警。草稿浏览器严格验收已通过：/tmp/pdf-ai-draft-read-built-20261111-final-02/summary.json，4例、21个实际JS资产、零console/http/page错误，manifest为9ee998908ab65f7c2ca8f8551b3a67954c9423fccd49d89bce549746bb987141。每例独立真实preview.pdf字节SHA/size/previewDigest与AI读取投影一致，草稿快照摘要及source文件不变；反序的原始导航及新增空白页无原始导航已核验，四截图已逐张目视。初轮长替换被引擎跳过的失败夹具证据保留，未通过放宽断言处理。该smoke使用ScriptedModel，root真实provider探针是独立证据。详细RED/GREEN日志、字段与限制见NATIVE_PDF_AI_READ_ACCEPTANCE.md新草稿节。

final3最终入口增量证据：manifest f76a3d6903e283f50fbffaf9cc28850bd16024d7f09811e4c71242cfe3fbc5ec；/tmp/pdf-ai-final3-entry-single-summary-20261111/summary.json（session50112 exit0），仅1次真实草稿总结及入口加载，21个JS实际响应匹配当前磁盘SHA，零page/console/http错误。PDF chunk仅一个生成native-main导入名变化，替回旧名后SHA精确还原旧四例已记录值；unified/native入口仅生成映射变化，native-api/native-pdfjs/preload-helper原字节直接相同。新旧实际SHA与替换证据分别登记，绝不把旧四例标成新构建fullsmoke，详见验收文档final3节。

final4进一步只做入口与资源连续性：manifest9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba；/tmp/pdf-ai-final4-entry-only-20261111/summary.json（session53795 exit0，entry-only，results=[]），真实native/PDF加载和四个中文SVG按钮可见，无任何AI/provider请求，21个实际JS响应匹配磁盘且零page/console/http错误。相较final3，18模块原始SHA相同，unified/native/pdf三个模块仅生成资源文件名变化，替回旧名后SHA精确等于final3记录值。没有不等价PDF代码，但也不把final4入口检查冒充一次总结或四场景重跑；各构建范围详见验收文档final4节。

### 6.4 受限真实 provider 增量：仅空草稿两页合成 PDF

2026-11-11 使用 AgentSettings 与生产 _report_model/_reporting_phase_model 工厂、原配置 modelId=deepseek-v4.1-flash 进行真实调用；未换模型、未用 ScriptedModel 冒充 provider。该结果仅覆盖本节合成空草稿只读总结，不替代第 6.3 节草稿专项或未完成的写工具、processNotes、生产数据库部署验收。

首次 /tmp/native-office-real-provider-20261111.log 与同名 JSON 保留失败：实际阅读工具正常，但直接 Agent 沿用 OpenAI 原生 schema 能力声明，向该模型请求 JSON Schema 后实际返回 Markdown，NativePDFReadAnswer 校验报 ValidationError/model_type。安全诊断 /tmp/native-pdf-provider-diagnostic-20261111.log 仅记录合成正文、输出类型和错误位置，不输出凭据或端点。

最小修复仅在 AgnoNativePDFTaskPlanner 初始化中复用生产 VerifiedModelCapabilityResolver，按实际能力选择 JSON_OBJECT/JSON_SCHEMA；保留四个 reader tools、每任务模型副本及全部草稿投影/引用映射，不套用会清空 tools 的无工具生成执行器。独立 test_native_pdf_ai_provider_protocol.py 先 RED 后 GREEN，日志 /tmp/native-pdf-provider-protocol-{red,green}-20261111.log；直接受影响的一项草稿 HTTP/真实投影回归另通过，日志 /tmp/native-pdf-provider-draft-compat-20261111.log。

修复后 /tmp/native-pdf-provider-fixed-20261111.json 与同名 log：4.29 秒，status=completed、ok=true，read_pages/read_annotations 实际执行，fullyReadPages=[1,2]、scopeReadComplete=true、两页有效来源引用，中文答案计算 42+17=59 million，issues=[]、sourceUnchanged=true。仍保留一次 Agno 中间“Failed to parse cleaned JSON”warning，不能记为零告警。两轮分别新建同内容合成 PDF，sourceUnchanged 仅断言各轮调用内原字节不变，不声称跨轮生成的 PDF SHA 相同。

历史第 6 节“真实 provider 未验证”仅由本次明确范围覆盖；真实 provider 的未保存草稿、全部 action/选区/取消形态及生产部署端到端仍未由此探针证明。未重复构建或运行整套测试。

### 6.5 批注文字标注工具增量

PDF 批注 Agent 新增 `propose_markup`，覆盖 highlight/underline/squiggly/strikeout；服务端要求先完整读取根批注及同页正文，旧文必须唯一匹配完整文字对象，标注坐标取自该可信对象，不能由模型传入。草稿来源仍经现有唯一重绑校验；任务只接受 replaceText/addMarkup，并按操作索引唯一归属到批注，候选经过原生引擎真实预览后才可显式采纳。默认高亮色与 PDF 功能区一致。

定向验证：`test_native_pdf_review_ai.py` 加真实预览/采纳集成项共 10 项通过；上轮同一批注处理模块回归 26 项通过。ruff（生产代码、单测；任务测试另以 E/F 检查）与 `git diff --check` 通过。未重复整组任务测试或全项目测试，也未在此增量执行浏览器/真实 provider 验收。

该阶段剩余缺口随后由 6.6 部分覆盖；便签新增/编辑/删除、段落/图片/表单/页面/新产物工具及跨 Word/XLSX/PPTX/PDF 完整 AI 工具对齐仍未完成。任务现已有真实 Agno 工具开始/完成及结果状态的 SSE，不应再标记为完全没有流式进度。

### 6.6 已保存文字标注删除工具增量

2026-11-11，原生 PDF 批注 Agno 注册 `delete_markup`。工具以已完整读取的根批注为操作归属，接受同页指定标注 ID，或省略 ID 后按类型/全部筛选；支持 highlight/underline/squiggly/strikeout。未读、不唯一、跨页、重复删除、只读关联标注和错误身份被拒绝，整组通过后才登记操作，避免部分登记。生成原生 `removeMarkup`，不能由模型提供来源摘要。任务复用原生预览回执与显式采纳；修改回复仍要求存在实际操作候选。

引擎标注只读模型新增可信 `sourceRef`；已有草稿通过页面映射、引用、字典摘要、类型和 quads 重绑原始标注。不能唯一重绑的新标注明确澄清或跳过，不按坐标猜来源。读取工具返回可信 quads/color，完整页正文对象返回 rect，供模型区分同页同类型不同位置标注；提示要求无法唯一定位时澄清。

验证：新增 13 项工具边界分批通过；6 项真实预览/采纳集成分批通过，含 ScriptedModel 经真实 Agno 执行、旋转人工草稿后原始身份重绑、同页双高亮仅删除指定位置，独立 pypdf 回读正文流与原始来源不变。原批注处理/任务/未保存便签兼容 27 项分批通过；引擎删除标注回归 18 项通过。引擎 `bundle:bridges` 成功；本轮生产/新增测试 ruff 通过。共用进度新增删除工具中文名，新增定向前端测试通过。没有重复全项目测试，没有本轮浏览器或真实 provider 验收。

当时未保存标注删除的缺口由后续 6.7 部分覆盖；仍未开放脱离根批注意见的自由 PDF 写工具入口，其余复杂工具继续按完整目标推进，不能称 PDF AI 全面对齐。

### 6.7 未保存标注删除与草稿归属

2026-11-11，`delete_markup` 可撤销冻结人工草稿中的 `addMarkup` / 旧 `highlight` 操作。引擎新增 `pendingMarkupMapping`：验证实际追加槽位、旧对象前缀、新 PDFRef、全页引用唯一及真实类型/位置/颜色，最终按精确引用和字典摘要复读，再将映射纳入 `previewDigest`。无法证明归属时不给映射，不按几何猜测，不阻断已有 PDF 产出；页面尺寸变换、涂黑等暂不签发该映射。

读取器核验原操作、页面和最终标注身份，并检查类型、quads、颜色及原始剩余标注前缀后的新增顺序。交换不同位置操作的回执、甚至完全相同 quads 的回执偷换索引，均由故障测试先复现后修复。模型不能直接提供任意草稿撤销索引；工具从核验映射取得索引，以 `removedBaseOperationIndices` 单独登记，不伪装成新增 PDF 写操作或已执行项。

任务只移除这些原草稿新增操作，重排新增修改、便签父操作与回复索引，再真实预览。全部撤销后允许空操作草稿；仅撤销草稿也能提出修改回复。每项撤销仍唯一归属根批注。前端明确显示“撤销草稿新增标注 X 项”，显式采纳完整剩余草稿，支持撤销与重做。源文件和原人工草稿参数保持不变。

验证分批：新增工具/真实 Agno ScriptedModel 4 项、回执故障 2 项通过；真实未保存标注/旧便签/已保存删除集成共 14 项通过，包含重复同坐标第二项、人工旋转、未保存便签回复父引用、混合来源及空草稿预览采纳。另有跳过改字后移除回复、孤立操作拒绝及取消后不可复活 3 项定向回归通过。引擎新增 5 项通过，前端面板 6 项通过；桥接构建、Python ruff 与 diff 检查通过。未重复全项目测试，也未执行此增量的浏览器或真实 provider 验收。其余便签/图片/表单/页面/新产物等 AI 工具及四格式完整对齐仍未完成。
