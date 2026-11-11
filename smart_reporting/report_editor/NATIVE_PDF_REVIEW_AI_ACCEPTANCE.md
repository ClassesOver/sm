# PDF AI 处理批注验收记录（2026-11-11）

## 源语义及实现边界

- 固定源：/home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c，apps/pdf/src/renderer/ai/pdf-skill.ts 的 Review workflows。
- 逐根便签读取完整线程及对应正文。明确修改意见经 propose_replace_text 产生实际原位改字候选，再经 propose_reply 产生 AI Assistant 回复；歧义提出澄清回复，纯讨论和 AI 自身批注具体跳过，不删除便签。
- 真 Agno Agent 工具循环，复用 read_pages/search_text/read_annotations/get_outline。作者从同一已核验 PDF 字节的 /T 读取，不接受模型自报作者。任务候选不直接修改来源。
- 仅支持唯一完整原位文字对象，不做 PDF 文本重排。已由人工草稿改写的同一对象不叠加覆盖；不能可靠重绑的批注/文字具体跳过。原位草稿只在实际预览及严格来源映射下使用原始对象和便签身份，最终由引擎再核验。
- 混合操作沿现有 replaceText/replyNote；author 由服务固定为 AI Assistant。实际改字跳过时，关联声称改字成功的回复被丢弃并重新真实预览。
- 候选需显式采纳，采纳只返回完整草稿操作，保存仍由原生保存链处理，不覆盖源修订。

## 后端合同

三个专属模块：native_pdf_review_ai.py、native_pdf_review_ai_tasks.py、native_pdf_review_ai_api.py。

基础路径：/reports/v1/native/{document_id}/{revision}/api/ai/review。

- POST /start：clientRequestId、expectedSha256、operations（完整现有草稿）、instruction（可选）；全文批注授权，无旧文字 selection 必填项。
- GET /{edit_id}?waitMs=20000：长轮询使用 shield，不因轮询超时取消实际任务。
- POST /cancel：clientRequestId；支持开始回执前取消，迟到 start 不能重启模型。
- POST /{edit_id}/accept：expectedSha256、operations（同一完整 base）、snapshotSha256。
- 状态为 running/succeeded/failed/cancelled；成功回执为 proposal，包括完整 operations、实际 previewDigest、appliedOperationIndices、skippedOperations、逐根 notes、coverage、issues、sourceSha256/baseSnapshotSha256、可选实际 projection。
- 采纳再次真实预览并校验来源/context/完整 base/previewDigest/执行清单；取消和关闭先写终态再等待依赖，吞取消/超时不得恢复候选。
- 会话 cookie、同源 CSRF、文档/版本及 scope 与原生编辑路由共用。启动要求 PDF 编辑及原位文字编辑均已启用；只读总结不受此处理配置影响。

## 已完成专项证据

本轮按变更分批运行，没有重复运行完整项目测试。两个专属测试文件共 20 项已分别验证：

- test_native_pdf_review_ai.py：8 项，涵盖完整读取证据、唯一文字对象、未知/真实作者、AI 自身跳过、真实 Agno scripted 循环、长批注游标、未读批注明确未处理、重复外观父批注精确 ref 映射。
- test_native_pdf_review_ai_tasks.py：12 项，涵盖提前取消、完整请求幂等与快照、先终态关闭、CSRF/来源域/跨版本、长轮询及采纳竞态、关闭文字编辑、吞超时、无归属改字拒绝。
- 正常实际闭环：真实 pypdf 便签 + 原位 Amount due 500 → Amount due 700 + 实际 /T=AI Assistant 回复；显式采纳复读，完整 base 变化拒绝，原来源字节保持不变。
- 实际 skip：过长原位文字被真实引擎跳过，关联成功回复删除并重新预览；PDF 中仍只有原始便签。
- 实际未保存草稿：另处人工 MANUAL DRAFT 保留，新批注修改和回复使用原来源身份进入同一候选。
- 实际 AI 回复后去重：从混合预览输出重新读取完整线程，最后回复作者为 AI Assistant 时不产生重复改字或回复。
- 新增 Python 模块通过 py_compile，新增文件通过 ruff F 检查；浏览器辅助通过 node --check。

真实 Agno scripted 循环仅证明工具/候选协议，不代表真实 provider 验证。

## 独立引擎审查

独立 probe 发现原重绑对 PDFRef 只比引用、不比所指值：同 ref 的间接 /T 被替换后仍允许重绑。主任务已修复为有界遍历引用实际值、比较解码 stream 字节；独立同一 probe 现明确拒绝 pdf_reply_text_parent_dictionary_changed。来源原 hash、精确父 ref、完整字典及最终 append 新精确 hash 的验证不得放宽。引擎变更及 bundle 由主任务负责。

## 待统一构建后的浏览器验收

专属辅助：frontend/smoke/pdf-ai-review-server.py、frontend/smoke/pdf-ai-review-smoke.mjs。在 frontend 目录运行，PDF_AI_REVIEW_SMOKE_DIRECTORY 指定全新证据目录；辅助自身不 build。

五场景：normal/overflow/clarify/discussion/cancel。真实 HTTP/cookie/CSRF、工作区、引擎、真 Agno scripted 循环；normal/clarify 通过新面板显式采纳，逐字比较 localStorage 草稿，再真实预览并独立 pypdf 回读正文和回复作者。记录实际构建 manifest、所有实际响应 JS SHA、截图、请求、源不变及没有 save/export。

上轮只读/草稿总结 manifest 不可作为本轮处理批注证据。

### 首轮冻结构建浏览器：实际失败，未标通过

- 证据目录：/tmp/pdf-ai-review-built-final-20261111。
- 实际 manifest SHA：e13de64ff923e7fb122a0e0b053331d7de3729247c7526f1f32d859c3868b210；实际 PDF bridge dist/cli.mjs SHA：e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711，与主任务冻结值一致。
- normal 真 Agno 候选 succeeded，实际 accept HTTP 200；页面未完成刷新，30 秒等待“建议已进入草稿”失败，脚本 exit 1。其余四场景尚未执行。
- 实际根因：frontend/src/pdf-replies.ts 旧本地守卫仍拒绝 replyNote+replaceText，故 view.refresh 在发起 preview HTTP 前失败。真实 failure DOM 明确提示“回复与原位改字、页面尺寸或裁切请分别保存重开”。
- 截图目视还发现新 .native-pdf-review 未继承既有阅读面板的有界高度及滚动样式，长建议内容与下方选区 AI 面板重叠。已告知主任务最小同步新引擎契约与布局样式；本 agent 未改主任务负责的前端，也未自行 build。
- 保留 failure.html、failure.png、server.log、http-evidence.json；后续修复必须在新冻结构建及新证据目录重跑本轮五场景。

主任务已报告真实 provider 单独证据 /tmp/native-pdf-review-real-provider-20261111.json；本 agent 未重放 provider 请求，浏览器辅助仍明确为 ScriptedModel，不混同两种证据。

### 修复后最终五场景：通过

- 最终完整证据：/tmp/pdf-ai-review-built-final2c-20261111/summary.json；脚本 exit 0，normal/overflow/clarify/discussion/cancel 共五场景全部通过。
- 实际 manifest SHA：e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa。运行前后磁盘身份一致；21 个实际响应 JS 字节 SHA 全部与当前构建文件匹配，逐文件清单见 summary.json 及 diagnostics.json。
- PDF bridge SHA 仍为 e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711。最终来源 SHA：9cb8b3c1bacb5c696411ce1cfa14abd15e7fe926f187fa37c9f86d48c2e47da6，全部场景保持不变。
- Chromium 140.0.7339.16，始终使用原 1550×1100 视口，未增大视口掩盖问题。
- normal：新面板生成真实候选并显式采纳，localStorage 操作与私有候选精确一致；独立 pypdf 回读实际正文 Amount due 700、唯一回复作者 AI Assistant。
- overflow：真实文字替换跳过，保留 Amount due 500，无成功回复写入；UI 显示具体 skipped 原因及 replyOmittedReason。
- clarify：显式采纳澄清回复，正文保留 Amount due 500，实际回复作者 AI Assistant，内容包含具体确认问题。
- discussion：实际零操作、无新回复；AI 自身与纯讨论批注逐条跳过。cancel：依赖吞取消后仍为 cancelled，未恢复 proposal。
- 所有场景均无 save/export 请求；pageErrors、consoleErrors、httpErrors、assetFailures 均为空。五次模型调用均为 ScriptedModel 经真 Agno，不是重新调用真实 provider。
- 布局自动断言实际找到跨容器后方选区 AI 面板：正常建议底部与后方助手顶部均为 1039px，无重叠；建议面板高度 495px，clientHeight 494px，scrollHeight 613px，实际可滚动 119px。其他长场景同样满足有界滚动，取消态恢复较小面板。
- 已目视正常/滚动末尾/跳过/澄清/取消截图及最终六图总览；长内容在独立滚动区内，未与后方选区助手重叠。截图见各 mode.png、normal-scrolled.png、contact-sheet.png。
- 原主画布在仅采纳草稿后仍展示来源正文，这是既有 refresh 与显式“实际 PDF 预览”分离机制；本轮通过独立真实预览输出验证改后正文，不将原画布冒充改后预览。面板明确提示核对实际 PDF 预览、确认后保存。

中间 /tmp/pdf-ai-review-built-final2-20261111 运行在 normal/overflow 通过后被合法 HTTP 304 缓存响应触发辅助断言中断。仅修正辅助：通过 Chromium CDP 禁用 HTTP 缓存，保留实际 200 响应字节 SHA 严格校验，并统一保留错误诊断；没有修改产品或重建。final2b 已完整通过；final2c 进一步将不重叠断言收紧为必须找到跨容器真实后方面板，并再次完成同一新五场景。首轮产品失败与中间辅助失败证据均未覆盖。

本 agent 本轮未 build、未提交部署、未重复 provider 或旧只读整套；浏览器与本地验收服务均已退出。

### 追加窄 normal 用户实际预览：功能通过，布局失败待修复

- 按主任务追加要求，仅运行 PDF_AI_REVIEW_SMOKE_NORMAL_PREVIEW=1，不重复五场景。证据目录 /tmp/pdf-ai-review-normal-ui-preview-final-20261111；仍为 e2fadd... 构建，无重建。
- 正常采纳后切编辑页签并点击实际“校验当前修改”按钮。真实 /api/preview 和 /api/preview.pdf 对同一 replaceText+replyNote batch 均返回 200；页面进入 data-pdf-preview=true。
- 实际 PDFjs textLayer 包含 Amount due 700、不含 Amount due 500；确认清单恰好两条“已执行”原位改字及便签回复，确认复选框初始未选。返回实际 PDF 7819 字节，SHA 55befb1526054ce673c31be2c1ad2458b0a799dcfad0cb02414c1cea708f302a，与独立候选预览输出精确相同。
- 21 个实际 JS 身份匹配；page/console/HTTP/assetFailures 全空；源未变、无 save/export 请求。
- 末尾严格布局断言实际失败：确认清单显示新增 108px，但固定容器中建议面板仍 flex:none 高度495px，bottom=1147，后方选区助手 top=1039，产生真实108px覆盖。截图目视证实覆盖，脚本 exit1，未标此窄用户流程验收通过。
- normal-ui-preview.png、failure.png/html、diagnostics.json 保留。已通知主任务修复布局；本 agent 不放宽几何断言、不扩大视口、不改生产或自行 build。后续只需新冻结构建下重跑此窄流程。

## root 引擎、面板与真实模型补验

- root新增 review-note-combined.test.ts 七项最终通过：真实改字与重复外观便签第二个精确父ref回复、AI作者、默认手工作者兼容、任意作者/过期身份拒绝、父字典变化及ref移除拒绝、八进制字符串转义等价、间接作者及外观流变更拒绝、超长间接作者有界拒绝。日志 /tmp/pdf-review-engine-final-green-20261111.log。
- 既有 note-replies.test.ts 五项受影响兼容通过。原测试硬编码/workspace产物目录在本机不可写，仅改为隔离系统临时目录，未放宽断言，失败历史与 /tmp/pdf-note-replies-compat-green-20261111.log 均保留。
- 最终 PDF桥 /tmp/pdf-review-engine-build-complete-20261111.log，dist/cli.mjs SHA e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711。重绑保留原source精确hash、父ref与页映射，并有界遍历引用对象、解码外观流比较；仅排除根/P允许改变正文的页面反向引用。
- 新面板 native-pdf-review.ts：中文说明、实际SVG、逐批注作者/处理/澄清/skip、真实previewDigest和执行清单，完整候选只在显式采纳后进入同一NativeDraft。四项面板专项通过，覆盖取消/迟到结果/完整base/Undo及采纳请求中的草稿变化。API两项专项通过，保留CSRF、完整base、编码路径和keepalive取消。受影响API与功能区另14项通过。
- 上下文新增独立pdfReviewAIEnabled，AI+PDF编辑+原位文字编辑联合授权；四项HTTP上下文专项及最终应用启动路由/关闭登记专项通过。只读pdfReadAIEnabled不被错误收紧。
- 真实生产模型探针 /tmp/native-pdf-review-real-provider-20261111.json 为ok:true，deepseek-v4.1-flash，9.15秒。真实Agno/service/preview/accept后独立pypdf回读700及AI作者，未选择文字/源不变，保留一次中间解析warning。合成输入/内存仓储及探针实际引擎版本边界见 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md。
- 最终统一前端build 39.53秒，budget及budget contract通过，manifest SHA e13de64ff923e7fb122a0e0b053331d7de3729247c7526f1f32d859c3868b210；最终浏览器结果仍需以下追加，不以manifest单独计功能验收。

仍有源能力缺口：未保存新增便签的AI改文+回复、合并/拆分页后的可靠处理、复杂原位重排、全部源AI工具与流式进度尚未全覆盖；不能将本增量称为PDF AI全部完成。

## 首轮浏览器真实失败与前端修复

冻结e13de64首轮normal虽经真实HTTP得到候选及accept200，实际view.refresh被pdf-replies.ts残留的旧混合守卫拒绝，页面仍显示原文；/tmp/pdf-ai-review-built-final-20261111/保留failure.html/png及HTTP证据，不能标该轮normal通过。root新增pdf-review-replies.test.ts先RED，随后仅同步引擎已验证边界：保存根replyNote可与replaceText同批，author仅允许AI Assistant；replyPendingNote与改字、回复与crop/size、过期父身份及任意作者继续拒绝。新3项与旧2+3项受影响专项通过。

同一截图另暴露新面板未套用滚动限制、长结果与已有选区AI面板重叠；仅将既有PDF只读助手的flex:none/max-height:45vh/overflow:auto及Office控件规则并列用于review面板，并增加证据长文本断行。未通过扩大smoke viewport掩盖问题。root还新增一项预览刷新异常回归，明确已采纳到草稿的候选不能报成未采纳，保留草稿并显示具体错误；RED→GREEN后面板五项通过。最终修复构建及五场景浏览器待追加，不能以旧e13de64替代。

一次最终构建因新增测试fixture缺少SavedPdfNote.removalReason类型而中断，保留/tmp/four-format-review-pivot-types-fixture-failure-20261111.log；只补测试字段，未据此修改产品逻辑。

## 最终 CSS 修复后的窄 normal 用户实际预览：通过

- 主任务仅将 review 面板改为 flex:0 1 auto、min-height:0，保留 max-height:45vh 和 overflow:auto；阅读助手规则不变。辅助只同步 flexShrink=1 的实现断言，未放宽高度、滚动、实际后方面板几何或预览内容断言。
- 新证据目录：/tmp/pdf-ai-review-normal-ui-preview-final3-20261111；summary.json 为 ok:true、validationMode=normal-user-preview，脚本 exit0。仅重跑 normal 实际用户预览，未重跑完整五场景或真实 provider。
- 实际 manifest SHA：82958436439e2cf17b4035f8a60378a29d459e927ff32b87d4998bfd2735cbb9；21 个实际 JS 响应字节与磁盘构建身份全部匹配。PDF bridge SHA 仍为 e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711。
- 新面板显式采纳后，经编辑页签“校验当前修改”进入 data-pdf-preview=true；真实 /api/preview、/api/preview.pdf 均200，同一完整混合 batch 与草稿精确匹配。PDFjs textLayer 显示 Amount due 700，不含 Amount due 500；确认清单恰两条已执行（原位改字、便签回复），确认复选框初始未选。
- 实际 HTTP PDF 为7819字节，SHA de46bb0aa45a43871320b1695d37caafd9ba551bc8ebc1b084c8357abdb90558，与独立候选预览输出精确相同；previewDigest 为08db5272865a0251235b52ecef873267e79e2c7509318d55dbd7aaf679bafbcf，独立 pypdf 回读700及唯一 AI Assistant 回复。
- 原1550×1100视口下，确认清单出现后的 review 高度387px、clientHeight386px、scrollHeight613px、实际滚动227px；review bottom 与实际后方选区 AI 面板 top 均为1039px，无重叠。maxHeight=495px、overflowY=auto、flexShrink=1。
- 已目视 normal-ui-preview.png 和 normal-scrolled.png：实际700画布、执行清单及未选确认框清晰，末条建议可滚动到达，后方助手独立显示。pageErrors、consoleErrors、httpErrors、assetFailures 均为空；来源SHA 173fde711aab6ed0519371d7206dd32122c171e9de409eadad0e0af1ddd6d5c6 保持不变，无save/export请求。浏览器和专属服务均已退出。
- 证据边界：完整 normal/overflow/clarify/discussion/cancel 五场景通过属于 e2faddb5... 构建的 final2c；最新82958436...构建仅有本次CSS修复后的窄normal实际预览通过，不能声称最新构建完整五场景重跑。ScriptedModel经真Agno调用一次，不混同主任务单独真实provider证据。此前产品失败及辅助失败记录均保留。
