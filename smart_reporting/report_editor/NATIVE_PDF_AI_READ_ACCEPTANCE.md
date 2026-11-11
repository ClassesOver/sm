# PDF 只读 AI 任务验收

日期：2026-11-11。公共接口 native_pdf_ai.py::create_native_pdf_read_planner(model) 接收 context、已核验 content、operations、action、instruction、selection、session_id、user_id。没有路径/URL 工具输入，不返回编辑操作或保存产物。

## 实现边界

- 四个真实 Agno 工具：read_pages、search_text、read_annotations、get_outline。每任务私有 reader 和 deepcopy(model)，依 Agno 原生合同清除客户端及工具/schema 状态。
- 二次核对来源 size/SHA256，再真实 inspect_pdf(include_text=True)；目录由已有 pypdf 从同一字节读取。原生文字提取明确 ocrPerformed:false，缺失 textObjects 不冒充空白页。
- 正文最多 10 页/24000 字符；批注最多 100 条/24000 字符、单段 6000 字符。长批注 next={offset,text_offset} 继续同一条剩余正文；实际字符区间决定覆盖，重复首段不虚增。
- 搜索不冒充完整阅读，未读页引用丢弃并告警。全文/全部批注未覆盖软告警。零批注也必须真实调用工具才计为已全读；当前引擎缺作者/时间/状态，明确 unknown。
- 选区按真实 pageId/objectId 核验，可信 scopePages 提供给模型，只返回所选文字，拒绝其它页面、批注和目录。
- 非空未保存草稿现经 NativePDFReadService 调用授权 NativeEditorService.preview_file，复用真实编辑配置和引擎回执；从实际已应用的输出重新提取文字，不忽略 base 或绕过配置。直接 reader.from_bytes(operations=...) 未携带内部授权预览回执仍拒绝。编辑、处理意见、OCR、新文档生成不属于只读任务范围。

## 定向测试

专属 reporting/tests/test_native_pdf_ai.py 先 RED 缺模块五项，再 GREEN 五项；边界追加后一次定向文件运行十二项通过（/tmp/native-pdf-ai-final-green-20261111.log，8.75 秒）。随后仅受影响的长批注游标/预算/选区范围与目录拒绝四专项通过，没有重复全量项目测试。

真实 ReportLab PDF 经 PDFium inspect 读出两页正文、便签、目录并确认身份不变；模型侧使用 ScriptedModel，运行真正 Agent.arun 多轮工具消息回传。并发模型隔离先 RED 后 GREEN。慢目录取消特征测试未改生产即通过；源码核实 Agno models/base.py:2610 将普通同步 execute 卸载到 asyncio.to_thread，没有重复造线程包装。

这些测试**不是外部真实 provider 验证**，不能据此声称实际 endpoint 已完成本功能闭环。

额外并行页工具测试先复现 RuntimeError: dictionary changed size during iteration，再以覆盖字典快照遍历修复；最终只补跑并行账本、长批注游标和目录取消三个受影响专项，3 passed / 13 deselected，8.39 秒。ruff、Python 编译及 smoke Node 语法检查通过。不存在通过重复首段“读完”长批注或靠模型自报覆盖的路径。

## 浏览器历史

frontend/smoke/pdf-ai-read-smoke.mjs 启动 uvicorn/helper，使用真实 FastAPI 原生页面与 AI 路由、workspace、grant exchange、HttpOnly cookie、CSRF/Origin、来源读取及 PDFium。修订查询为 scoped 内存 lookup，没有连接生产数据库；模型为 ScriptedModel 的真实 Agno 循环。

初轮 /tmp/pdf-ai-read-built-20261111-final-01 四入口问答/总结/要点/审阅走完，21 JS response 与磁盘 SHA 一致；但只读初始错误请求编辑 preview，产生 HTTP/console 503，**不能作为最终验收通过**。manifest b3f8fc5a0c6b0204aba0140316a30b6fb2573e12fd4c67fbcbbc4cc78e969ca8；unified entry lazy-unified-main-BxysvhEO.js SHA 532fea1a833bb18deb09c1cb1f968dc2f648bedbdf742947bb4e595549d16c17。

随后严格目录 /tmp/pdf-ai-read-built-20261111-initialization-red-01，session21160 exit1，因整个只读会话零 preview/save POST 断言失败；read-only-initialization.json、failure.png/html 保留实际 503。旧 summary 的 ok 不表示严格断言通过。

最终脚本要求四按钮 SVG/中文组名，输入框实际可见可输入，面板 45vh/overflow:auto，真实 coverage/toolEvents/citations 及引用导航，编辑/改字开关均关闭仍可阅读，来源 SHA/草稿不变，整个会话零 preview/save POST，console/http/page errors 均为空。最终结果见下文，未自行构建。

第二次严格轮 /tmp/pdf-ai-read-built-20261111-final-02（manifest 2c6784d0ba3af88b1206e519d1a3859b2d34f56fa4f1c2a21b0af7cefa6f3b8b）初始化已满足零 preview/save POST、console/http errors；问答和布局检查走通，但 session84855 exit1，引用导航第二页后活动 is-active 高亮仍停在第一张卡片。截图显示滚动已到第二页，源码确认新增 onNavigate 漏同步活动类，而既有 jumpToPageForIdentity 会同步，因此这是新接线的真实缺陷 RED，不是可删除的无关假设。root 已改为复用既有跳转函数。最终脚本保留活动类断言，同时核对精确 source-bound pageId、viewport 可见位置和公开页码输入值；旧目录不会覆盖。

## 最终严格浏览器 GREEN

root 确认 /tmp/four-format-ai-{build,budget,budget-contract}-verified-20261111.log 均 exit0 并冻结资产后，使用全新 /tmp/pdf-ai-read-built-20261111-final-03。session41906 exit0，实际 summary 为 ok:true、四入口、21 个实际 JS response，浏览器 140.0.7339.16。独立回读 summary、HTTP 全记录、来源文件和磁盘 manifest 均一致；不是只相信终端 ok。

- manifest SHA256：8f866be146d8f6475808caae7e7175d5ea14767c84867476b3c86f5e80cc6504。
- HTML 实际 unified entry：/reports/v1/editor/assets/assets/lazy-unified-main-8W2vWazJ.js；SHA256 18147a8f2a4b9f21019ec0c8e341b255ce9c787ab87072c97c8c3bb1121c1aa4。
- 另一 HTML entry lazy-preload-helper-BPPmGX_j.js SHA256 5f7bf953208a41ae25e857ff279709d55de641ee43ba228c50f92056b8f9b5a2。全部 21 个实际 JS response 均逐个匹配磁盘 SHA256，完整清单在 summary.assets。
- 实际源 PDF SHA256：8187be3cb0d41086f7292963f32e278d3a3199aad2f469984643d3c0df9333b6；真实 workspace 复读与 source.pdf 相同，草稿快照始终不变。

四入口 ask、summarize、keyPoints、reviewSummary 均点击公开 Ribbon 按钮，真实运行 read_pages/read_annotations/get_outline；coverage.fullyReadPages=[1,2]、fullDocumentRead=true、annotationsReadComplete=true、ocrPerformed=false，issues=[]，两页引用均通过依次点击后的精确 pageId、活动 is-active 类、viewport 可见位置及全部公开页码输入值核对。四按钮 SVG 存在，开始分组显示 AI 助手/标注/编辑/转换与导出/页面与缩放/搜索、打印与属性；注释分组显示 AI 审阅/标注/绘图工具/签名与保护。输入框实际可编辑，尺寸 1390×64；面板 maxHeight=495px（1100px 视口的45%），overflowY=auto。四张 ask.png、summarize.png、keyPoints.png、reviewSummary.png 已逐张实际目视，输入、证据、按钮及第二页蓝色活动边框均正确可见。

编辑和原位改字开关均为 false，pdfReadAIEnabled=true。整个原生会话只有五次 POST read/start 和一次 POST read/cancel（全部200）；preview/save POST 为零，consoleErrors/httpErrors/page errors 全部为空。旧初始化 503 和引用高亮缺陷在此次最终资产上通过严格 GREEN，没有放宽对应断言。

第五次为真实 pagehide 取消探针：测试 helper 在任务调用模型前阻塞；浏览器确认后端已进入，导航 about:blank，实际 fetch keepalive 的 POST /api/ai/read/cancel 返回200；协程捕获真实 CancelledError，任务状态 cancelled 且没有 result。证据在 summary.cancelEvidence、http-evidence.json；不是伪造取消 HTTP 响应。四次完成任务仍使用真实 Agno 循环加 ScriptedModel，**外部真实 provider 未验证**；修订查询仍为 scoped 测试内存 lookup，不能据此声称生产数据库部署完成。

所有本 agent smoke/server 和测试 session 均已终态，pgrep 无残留 pdf-ai-read-server.py/pdf-ai-read-smoke.mjs 进程。未自行构建、未全套测试、未提交。

## 未保存草稿可信投影（后续增量）

非空草稿由任务开始时深复制的完整 operations 快照驱动真实 preview_file；pdf_enabled 关闭时拒绝，replaceText 还须 pdf_text_enabled。空草稿继续只读原文件，无需编辑开关。源码文件只读，预览输出不保存为新修订。

实际回执的 sourceSha256、sha256、size、previewDigest 和 appliedOperationIndices/skippedOperations 均核验；执行/跳过索引须恰好划分完整请求操作。Reader 对真实有效字节再次 inspect(include_text=True)，工具 sourceSha256 指向有效字节；result.sourceSha256 保留原始来源追溯，result.projection 明确 originalSourceSha256/effectiveSha256/effectiveSize/previewDigest/draftSnapshotSha256，绝不把新字节冒充原始来源。

pageMapping 明确原始与有效页号/身份。普通页面编辑、删除、完整排序、插入空白页保持可验证的一对一映射；新增页 originalPageNumber/originalPageId 为 null，引用不得伪造原页导航。mergePages/splitPages 尚无法一对一映射，明确返回 native_pdf_ai_draft_mapping_unsupported，不能标为全部草稿能力完成。工具页号和 coverage 始终指有效草稿页号；引用同时保留原始导航和 effective 字段。

原始选区须真实 pageId/objectId 唯一命中；已应用 replaceText 须再核对冻结操作的 expectedTextSha256，输出 newText 精确相符，字号与文字起点在保守容差内且唯一，才登记 selectionMapping。删页、页面几何变化、对象拆分/消失或歧义一律拒绝，不扩大选区。全部或部分 skipped 均按真实回执阅读并显式告警，不声称跳过的修改已执行。

新增 test_native_pdf_ai_draft.py 18 项以真实 NativeEditorService/PDFium/Agno 测试，按变更范围分批通过：改字、改后选区、页序、删除、过期选区、两种配置关闭、全部/部分跳过、投影期间取消和输入深复制、吞回 CancelledError 后不启动迟到模型、空白页无原始导航、merge/split 明确拒绝、伪造输出 SHA/执行分区拒绝、几何变化拒绝、真实 HTTP cookie/CSRF/Origin/选区闭环。首次 10 项全部 RED，随后 8+2 通过；取消吞回额外先 RED 后 GREEN。新增边界 5+2 和 HTTP 1 项分别通过，没有重复运行完整文件。

- RED：/tmp/native-pdf-draft-red-20261111.log；取消 RED：/tmp/native-pdf-draft-cancel-red-20261111.log。
- GREEN：/tmp/native-pdf-draft-green-20261111.log（首轮 8 通过，2 个测试脚本预期错误保留）、page-mapping-green、boundaries-green、layout-green、http-green 同名前缀日志（后续只补对应失败或新专项）。
- 原空草稿受影响窄回归：/tmp/native-pdf-draft-empty-regression-20261111.log，6 passed，来源核验、只读配置、幂等、取消及鉴权 HTTP 行为保持。
- 本增量 Python 编译、ruff、局部 black(py312) 和新增 Node smoke 语法通过。仅格式化 reader 前缀，planner 真实 provider 修复由独立任务负责。

frontend/smoke/pdf-ai-draft-read-smoke.mjs 与既有辅助服务 --draft 模式：真实浏览器恢复本地草稿并点击总结按钮，分别覆盖改字、改字+反序、跳过+旋转、新增空白页；独立 POST 原生 preview.pdf，以 expectedPreviewDigest 校验输出字节 SHA/size，对照模型读取 identity，检查原始导航、新页禁用、source/草稿不变和 console/http/page 错误。最终通过结果见下一节。默认旧只读 smoke 不改变且未重跑全轮。

## 草稿严格浏览器最终 GREEN

root 统一构建、预算与预算契约完成并冻结 manifest 后，运行新草稿脚本，不重跑旧只读完整 smoke。最终目录 /tmp/pdf-ai-draft-read-built-20261111-final-02，session79377 终态、Node 输出 ok:true/cases:4/assets:21。独立回读 summary.json、HTTP 记录、源 PDF 与四个有效 PDF 的真实摘要/大小，不只相信终端 ok。浏览器 140.0.7339.16。

- manifest SHA256：9ee998908ab65f7c2ca8f8551b3a67954c9423fccd49d89bce549746bb987141。
- 实际 unified entry：/reports/v1/editor/assets/assets/lazy-unified-main-D2U7flb1.js；SHA256 79ed27855ce32cbd352aa5b55124ae9009dd91084bb843542a6ecd812a1deb26。
- 实际 PDF entry：/reports/v1/editor/assets/assets/lazy-pdf-main-CevG_5cj.js；SHA256 f9381c380b7d748c5326dacbaf4ef27aceab67a7d0934cf8de0df8a2ce8220a1。21 个实际 JS response 全部逐个匹配冻结磁盘资产。
- 实际源 PDF SHA256：cf42fdb81057a5f07fb9cda4e377263ac307f9008ab60c5c20957a1cfc8bbd0c；source.pdf 与 workspace 复读一致，四例所有本地草稿字符串均未改写。

| 用例 | 实际回执与覆盖 | 有效 PDF SHA256 |
| --- | --- | --- |
| text | 收入改为72；applied=[0]，skipped=[]；完整有效页[1,2] | a8c6f4091d1aa20741ecf018c1f40a8d3f9fb464debf02530b361fed97cced21 |
| reorder | 收入72；applied=[0,1]；有效页[1,2]对应原始页[2,1] | 2d98149033d5435ea3a18ec10860e643631ebe35f97bd35b374aa9bbc69ffca3 |
| partial | 收入仍42；applied=[1]；操作0真实跳过，原因为pdf_text_identity_invalid_or_repeated，界面显示原因和软告警 | 5b9e277557d2a306ac0e0029e0622f2f4211bab9aaa5018fbe90c804017126ac |
| blank | applied=[0,1]；完整有效页[1,2,3]；第1页为空白，无原始页号/ID，按钮禁用；原始页1/2对应有效页2/3 | ef571b10c016e6678653584c820033ae016a822defc4213df455af73329d524d |

四例均独立请求实际 preview.pdf，携带 AI 回执的 expectedPreviewDigest；HTTP200、响应摘要与回执相同，保存的 name-effective.pdf 字节 SHA256/size 与 projection.effectiveSha256/effectiveSize 完全一致。draftSnapshotSha256 与浏览器对完整 operations 独立 canonical JSON 计算的 SHA256 一致。所有引用按钮逐一点击后核对原始 pageId、is-active 与 viewport 可见位置；新增页仅显示“草稿新增第1页（无原始页面）”禁用按钮。全部 coverage.fullDocumentRead=true、ocrPerformed=false，未读批注仍明确 annotationsReadComplete=false，没有因读正文而伪称批注已读完。

四张 text.png、reorder.png、partial.png、blank.png 已逐张实际目视：未保存版本标识、applied/skipped、有效页覆盖、原始/草稿页号按钮及原始页活动边框清楚可见。HTTP 记录有4次 read/start、4次独立 preview.pdf 和合法编辑元预览，全部200；没有 save/export，pageErrors/consoleErrors/httpErrors 全为空。所有本次 server/smoke 进程均已终态，pgrep 无残留。

首次目录 /tmp/pdf-ai-draft-read-built-20261111-final-01 保留失败证据：较长替换“Revenue is 72. Confirmed source amount.”被真实引擎以 pdf_text_overflow_or_unverifiable_output 跳过，effectiveSHA=原始SHA，严格“改字实际应用”断言因此失败。页面准确显示 applied0/skipped1、原因和收入42，没有伪造改字成功；failure.html/png/http-evidence.json 保留。只将夹具替换缩短为可应用的“Revenue is 72.”，未放宽 SHA、applied 或导航断言，未改生产代码，final-02 才是本轮 GREEN。

此浏览器使用 ScriptedModel 驱动真实 Agno、真实 HTTP/鉴权/引擎/文件；修订查询仍为 scoped 内存 lookup，不是生产数据库测试。root 另有真实 provider 协商修复与独立 endpoint 探针，其结论独立于本 smoke，不能把本节脚本模型当成外部 provider 证据。merge/split 无安全映射、自由文字选择和写工具等未完成边界仍保留。

## final3 最小入口与单次总结核验

root 最终冻结 manifest 为 f76a3d6903e283f50fbffaf9cc28850bd16024d7f09811e4c71242cfe3fbc5ec 后，只执行一次 text 草稿总结，不重复前述四场景或旧只读完整 smoke。证据目录 /tmp/pdf-ai-final3-entry-single-summary-20261111，session50112 exit0；summary.validationMode=entry-and-single-summary、results长度1、实际21个JS响应均HTTP200且逐个匹配当前磁盘SHA256。源文件/本地草稿不变、有效PDF字节SHA/size/previewDigest一致、正文覆盖[1,2]、改字实际applied=[0]、原始引用逐个active/visible，page/console/http errors均空。text.png已实际目视，所有进程已终态无残留。

实际加载的新资源：

- unified-main-9N9_cYwd.js：b6a7ff635d86b378e01e2c3a3c84cad32956071b7133a51c097e259ffdca4eeb。
- native-main-jJlafOeA.js：641f9140fe7d5421616be736a38364e742b95eb88f1bc4fd164c554aca7703dc。
- pdf-main-BYQnl_pR.js：48efa9b5abc07eaad0b6ae96f6bbe37023debb67a66d5dc48180416382d708f1。

不能把PDF chunk称为原字节完全相同：它因native-main导入文件名变化而产生新SHA。已通过独立字节验证：只将新PDF chunk中唯一一次lazy-native-main-jJlafOeA.js替回已验收旧名lazy-native-main-DnUKRjP2.js，计算SHA恰为旧PDF已记录的f9381c380b7d748c5326dacbaf4ef27aceab67a7d0934cf8de0df8a2ce8220a1；没有删除代码或宽泛正规化。因此PDF模块相较四例验收版本仅这一生成导入名变化。unified/native入口同样只替换新旧manifest列出的生成资源名后，SHA精确还原旧已记录值，证明入口字节变化范围是生成映射；native-api、native-pdfjs、preload-helper三个模块原SHA直接完全相同。

证据分别保存在asset-continuity.json（原始SHA，不掩盖差异）、pdf-core-import-comparison.json（单一PDF导入替换及次数）、entry-import-comparison.json（入口逐项资源名替换与旧SHA精确一致）。浏览器实际加载新入口并完成最小真实总结链，与这些磁盘比较相互独立。本次是最终入口接线和一次总结验证，旧四例仍明确属于9ee9989构建，未冒称已在f76a3d69重跑四例；模型替身/内存修订边界不变。

## final4 仅入口与资产连续性

root 因 XLSX selection subscription 销毁时序修复完成统一 final4 构建后，冻结 manifest 为9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba。本增量严格只做真实原生 PDF 加载、中文 AI 入口/图标和资源连续性，不启动任何 AI 总结、问答或 provider，也不重跑四场景。

证据目录/tmp/pdf-ai-final4-entry-only-20261111，session53795 exit0，summary.validationMode=entry-only、results=[]。真实浏览器打开grant/native入口并加载PDF，四个按钮“AI 助手/AI 总结/AI 关键要点/AI 总结审阅”均可见、启用、带SVG；仅打开空问答面板，输入可编辑、空问题开始按钮禁用。HTTP证据中没有任何/ai/请求，仅一次合法编辑元预览POST200；21个实际JS响应逐个匹配当前磁盘SHA256，page/console/http errors均空。entry.png已实际目视，进程已终态且无残留。

与final3单次总结记录的21个PDF入口依赖资产逐项比较：18个原始SHA完全相同（包含native-api/PDFjs/preload及其余共享模块），3个原始SHA变化且不能声称原字节相同：

- unified-main-DCSB-Cqw.js：8cfafc4293918025fde090b9be1035ef58c749b1605afd3c06dbc635e7979905；仅native-main/workbook-main生成资源名变化。
- native-main-CsPU594W.js：385f73107ff848c43d5add41164d40726652a9248e7a5e5025cf21fccc35079e；仅native-office-view/pdf-main生成资源名变化。
- pdf-main-D0v7_BSl.js：7fb73cb9f4df6f408a5f0f8d5774c96ead6d27eff95aa974cc64afdf22eeed74；仅一次native-main生成导入名变化。

上述3模块只把新旧manifest明确列出的生成文件名替回旧名后，SHA逐个精确等于final3实际已记录的原始SHA，没有删除代码或宽泛正规化。asset-continuity.json保存全部21项原始/替回后SHA、文件名替换与次数；实际浏览器响应SHA亦与此表一致，未发现不等价PDF模块。final4仅证明入口和PDF资产连续性；一次真实总结的证据仍属于final3 f76a3d69，四种草稿完整验收仍属于9ee9989，真实provider是root独立探针，本节不扩展这些结论。

## 受限真实 provider 补验：空草稿两页总结

2026-11-11 在历史 ScriptedModel 浏览器验收之外，新增真实生产模型工厂补验；本节仅覆盖原文件空草稿两页合成 PDF，不将此探针等同完整 PDF AI 或未保存草稿的真实 provider 验收。

- 模型：沿用 AgentSettings 与生产 _report_model/_reporting_phase_model，实际 modelId=deepseek-v4.1-flash；没有替换配置模型。
- 失败证据保留：/tmp/native-office-real-provider-20261111.{log,json}；/tmp/native-pdf-provider-diagnostic-20261111.log 确认工具读取后返回 Markdown 字符串，领域校验报 ValidationError/model_type。诊断只含合成正文和安全类型信息，不含凭据/端点。
- 根因修复：planner 复用现有 VerifiedModelCapabilityResolver，实际 DeepSeek 使用 JSON_OBJECT；四个可信阅读工具、模型深复制和 reader 草稿投影逻辑保留。未将无工具结构化执行器直接替代阅读 Agent。
- 新独立协议回归先失败后通过：/tmp/native-pdf-provider-protocol-{red,green}-20261111.log。草稿 HTTP/来源映射代表性一项通过：/tmp/native-pdf-provider-draft-compat-20261111.log。
- 真 provider 通过证据：/tmp/native-pdf-provider-fixed-20261111.{log,json}，脚本 /tmp/probe-native-pdf-provider-fixed-20261111.py；4.29 秒完成，实际 read_pages+read_annotations，fullyReadPages=[1,2]、scopeReadComplete=true、两页合法来源引用；答案给出 Alpha 42、Beta 17、合计 59 million，未推测未知币种/期间，issues=[]、sourceUnchanged=true。
- 保留中间 warning：日志仍有一次 Agno “Failed to parse cleaned JSON”，最终结构化结果成功且无最终 ValidationError；不能写为零告警。每轮新建合成文件，各轮 sourceUnchanged 不代表生成文件跨轮 SHA 相同。

历史“外部真实 provider 未验证”在本节范围内被后续结果覆盖；历史失败和模型替身证据均保留。真实 provider 的未保存草稿、全部四入口、选区和取消行为、生产数据库/部署仍不能由这一次原文件总结推广为全部通过。未重复构建或整套测试。
