# Word 已有批注回复增量验收（2026-11-11）

## 固定源与设计

固定源码 /home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c。

- apps/docs/src/renderer/review-actions.ts:235–252 的 replyToComment：分配新 ID，通过 addReplyToCommentRange 复用父批注全部文字范围，新 CommentInfo 必须携带 parentId；作者使用 authorName()，日期为 UTC 秒精度 ISO。没有把普通根批注当作回复。
- editor/comments.ts:116–137：给每个含父 ID 的真实文字 mark 追加新 ID；不重新选择全文段落，不在父锚点消失后另选范围。
- packages/docx-engine/src/parse-package.ts:155–201：comments.xml 最后段的 w14:paraId 与 commentsExtended.xml 的 w15:paraIdParent 构成父子关系。
- 同源 patch.ts:2837–2860：commentEx 同时记录 paraId、可选 paraIdParent 和 done；本项目不调用源 saveDocx(options.comments) 重建整族，而是保留原 bytes 后做最小追加。
- 来源 SHA256：review-actions 2b856090cb56b26ffd3b96a693a72c4b76dbbccc43ceb05e7abc83baccf61d8a；editor/comments 9bd8ef6b1d065e7aceafc27c2b56a9a016adb4ccd09d42bfaad2296bbad89e40；parse-package 4fc4c90c043602cbd8fdda623d896d2a232c8d74f0d46f0c04ead1e0e82b6147；patch 42a30f34525620c3700d08883a47954111aceeaaf682ffd5f2ec5f1c4ba9a218。

root 已确认本受限增量设计与必要 Word 局部改动。实施顺序：可信父身份/真实 OOXML 关联 → PM 历史/草稿/保存宿主 → 真实 HTTP、独立 ZIP/lxml 与统一构建后浏览器；每层先观察缺能力的 RED，再实施并验证。

## 最小实现

- 新增 engine bridge/docx-comment-reply.ts：从授权原 bytes 取得 sourceId、targetId、comments/object SHA；客户端只传父目标与回复文字/作者/时间，不传 parent OOXML 或自定父 ID。仅原版本既有根线程可授予回复；已有子回复明确提示回复根线程。
- 从父原 commentRangeStart/End 推导准确 UTF16 范围，复用 docx-comment-create 的可信来源、分段锚点及全实际 XML/content-type 身份避碰 helper。新数字 ID 与 paraId 全包避碰，保留父原 markers/文字和非目标部件。部分/跨段范围与普通内部空段保持原范围，不扩大成整段。
- replies 必须通过 commentsExtended commentEx 的 paraIdParent 指向唯一父最后段 paraId。父缺 paraId 时仅补该最后段开标签；缺扩展时添加标准 part、关系与 content type；已有扩展只追加新回复记录及必要缺失根记录，原旧节点/属性/未知子节点不重建。people、commentsIds、commentsExtensible 与未知部件不改写。
- 扩展关系、实际 part、content type 必须一一对应；拒绝异类关系别名、重复/孤立/无效 paraId、悬空父和循环父链。整批先校验原父身份，任一后续非法操作拒绝整批，不输出半份结果。
- edit-docx.ts 增加 inspect 的 commentReplies 和独立 replyComment 分支；delivery/docx_native.py 仅加 Word 专属白名单。没有修改 app.py、公共 native-api、发布/签发链或其他格式模块。
- 新 frontend/docx-comment-reply.ts：将真实父目标的 replyComment 记录在同 PM doc 的 nativeCommentReplyOperations，沿用 Guard、NativeDraft、Undo/Redo、恢复、保存前 flush。输入取消不入草稿；未失焦可直接保存；来源变化时保留输入并报具体原因。正文/改字/新根批注不能与回复混批。
- 现有批注面板加“回复此批注”，并在重开后的既有回复显示“回复根批注 #ID”；服务端模型须与实际 parsed parentId/作者/文字逐项一致才授权。草稿回复在专属列表显示，真实子关联在保存后的 DOCX 中建立；不声称增加实时多人线程服务。

## RED / GREEN 与失败记录

- /tmp/word-comment-reply-core-red-20261111.log：3 项因缺少 commentReplies 失败，证明薄桥尚未提供回复能力。
- /tmp/word-comment-reply-frontend-red-20261111.log：缺 docx-comment-reply 模块；实现后 /tmp/word-comment-reply-frontend-green-20261111.log：3 passed。
- /tmp/word-comment-reply-main-red-20261111.log：真实主控制器缺回复按钮；/tmp/word-comment-reply-main-green-20261111.log：1 passed / 52 skipped，覆盖取消、未 blur flush、Undo/Redo、恢复、混正文拒绝与 native-session 保存请求。
- 首次 core 实现经历新增模块传输转义导致正则缺反斜线（compile fail/paraId 检查拒绝），保留 green/green2 日志；按准确日志修正后 green3 为 3 passed。不是既有生产故障。
- /tmp/word-comment-reply-alias-red-20261111.log：异类关系指向同 commentsExtended 部件仍被授权，严格 RED；新增同部件关系身份守卫后纳入最终 GREEN。
- /tmp/word-comment-reply-core-final-20261111.log：5 passed / 28.15 秒。覆盖缺扩展的两条真实回复、既有现代记录/people/未知 XML 保全、伪造/旧源/非根/非法后续批次、异类关系别名拒绝、部分跨段/内部空段父范围及多段 Unicode 回复。
- /tmp/word-comment-reply-affected-core-20261111.log：受影响原新建批注 core 5 passed，验证提取的共享身份扫描未改变原范围/ID/metadata 行为。
- 受影响前端首轮暴露新增回复面板先插入导致旧 .docx-comment-panel 选择器取到错误面板；已将新增面板放回原面板之后，未改旧断言遮掩。/tmp/word-comment-reply-affected-frontend-final-20261111.log：20 passed / 51 skipped，含回复三项与已有批注/主入口定向回归；未运行完整 suite。
- 首轮 tsc 暴露本模块 const fail 的控制流收窄及 root PPTX 测试类型错误；本模块改用明确 never 函数，PPTX 由 root 修复。/tmp/word-comment-reply-types-final-20261111.log exit0；最后冻结检查另见 /tmp/word-comment-reply-types-freeze-20261111.log。

## 实际文件与 HTTP

核心测试在每个临时 runtime 中隔离 bundle，不改生产 dist。/tmp/word-comment-reply-core-final-20261111/test_reply_creates_real_parent0/{source.docx,saved.docx,zip-lxml.json} 为缺扩展产物；test_reply_preserves_existing_0/{modern-source.docx,modern-saved.docx} 为现代来源；test_reply_uses_partial_cross_0/{cross-source.docx,cross-saved.docx} 为跨段来源。独立 Python ZIP/lxml 回读确认新增回复通过真实 paraIdParent 指向父、共享准确范围、原文字/旧元数据保持、全部 XML 合法。

必要生产 doc 专属 bundle：原 SHA256 abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71 → 新 SHA256 900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897，日志 /tmp/word-comment-reply-doc-bundle-20261111.log。没有自行构建共享前端。

/tmp/word-comment-reply-http-20261111.log：新增真实 FastAPI middleware/grant/session/CSRF、生产打包 Node 桥和实际下载 router 专项，1 passed / 24.31 秒。缺 CSRF、伪造父身份和旧源拒绝；真实 preview/save/revision2、幂等重试一次完成、下载 SHA 与身份一致、新修订重开仍 parentId=1。故意 validator raise 时 validation=false、具体 issues 与实际 Word 下载链接均保留，不标记验收通过。证据 /tmp/word-comment-reply-http-20261111/test_reply_http_save_download_0/{source.docx,downloaded.docx,evidence.json}。

HTTP 使用既有内存仓储与合成 DOCX，不是部署生产登录或真实用户数据验收。保留环境 imghdr DeprecationWarning 以及结束时已有 Agno/OpenTelemetry exporter 对已关闭 capture stream 的日志错误，测试进程 exit0；不声称零 warning 或零环境日志。

## 8c3 构建完整回复浏览器闭环

root 统一 build/budget/contract exit0 后，Chromium 140.0.7339.16、4310 端口单次执行 smoke exit0。日志 /tmp/word-comment-reply-browser-final-20261111.log；完整证据 /tmp/word-comment-reply-browser-final-20261111/evidence.json，ok=true。API 路径 /reports/v1/native/fixture-comment-reply/{1,2} 明确为 fixture，真实保存使用生产 Python/Node bridge；不与真实 HTTP 鉴权专项拼成部署生产数据库整链。

- manifest SHA256：8c3baa3ed28283fb6e443e22b4590ee3ab82c38fd1f592a0bbcb06076c300a9c；bridge SHA256：900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897；122 个实际加载 JS response 原始字节与磁盘 SHA 逐一匹配。
- lazy-unified-main-C2S5zkAw.js：16812 bytes，SHA256 0e877373d45d66313472c72018a11a2a4312eb0f66ad0e62662529ea5fa8a5c1；lazy-native-main-b9RhOxTl.js：22664 bytes，SHA256 67750f3b3c82771dcda8bb007485e1102e230ff2c24d6ee0e2b0bbe6c44218f1；lazy-docx-main-HIBoZObN.js：196687 bytes，SHA256 e2c30f13d5a4ceb0145b9754e272fc85d077891e8a125161edec24140e143288。
- 取消回复不入草稿；第一条添加、Undo/Redo、reload 恢复通过；第二条未失焦保存通过。实际新增 ID0/ID3，原 ID1/ID2 保留；两条新回复均通过 commentsExtended 的 paraIdParent 指向根 ID1，准确共享原“Anchor text”范围，未伪造根批注。
- 原 DOCX SHA256 08753c726c4acb5d4ba2f841f436ea15c74b889c19f8b3a4c97da6686b193132 不变；下载输出 SHA256 6c69ff3b3648224c26d5174844227bb32d52b93b2d4706ba8ebd6d98726b5259。独立 ZIP/lxml 确认仅 document.xml、comments.xml、commentsExtended.xml 改变，全部 XML 合法，旧评论对象/扩展片段/people/未知 XML 保全。
- 验收失败 fixture 显示具体原因“批注回复版式验收待复核”与实际下载链接；revision2 重开可读“未失焦保存的回复😀”和“回复根批注 #1”，嵌套回复按钮禁用；实际 bridge 拒绝旧 source 操作。
- pageErrors、consoleErrors、failedResponses 均为空。reply-history.png、reply-unblurred.png、reply-delivery.png、reply-revision-2.png 已逐张目视；中文输入、根批注引用、交付原因/下载、新修订真实父关系均可读。端口 4310 收尾已关闭。

目视另发现真实 UI 缺陷：reload 恢复后回复输入已可用，但状态行可能残留瞬时“当前文档不可编辑或正在保存”。功能闭环通过不能掩盖该陈旧提示；已报告 root，新增 controller 严格 RED，修复/后续构建验收另追加。未擅自修改冻结产品或重新 build。

浏览器本轮覆盖同一原根的两个文字回复及既有现代扩展；部分跨段/普通空段父范围仍对应 core 专项，不冒称均在浏览器重测。完整批注族未完成。

## 明确边界

本增量仅创建对原版本既有根线程的文字回复；根线程父身份必须唯一，正文锚点必须可安全投影为标准主 story 的简单文字范围。普通表格及跨段安全范围复用现有锚点能力，但本轮新增专项明确实测的是主正文及跨普通空段父范围；不冒称所有复杂对象均测试。

不支持回复草稿中新建的未保存根批注、对子回复再创建嵌套回复、图片回复、解决/重开/删除线程、作者身份服务或多人协作。复杂内联/域/超链接/修订/SDT/非主 story、受保护文档、未知或歧义现代扩展 schema 仅查看并报因，不缩小范围后冒称成功。保留现代/未知 XML 是原 bytes 增量保存合同，不等于完整实现其功能。受保护文档 comments-only 模式尚未由本宿主授权开放。

## 状态提示定向修复与 final2 补验准备

root 确认修复 8c3 目视发现的陈旧只读提示。/tmp/word-comment-reply-status-red-20261111.log 严格复现：锁解除后 textarea 已可用，状态仍包含“不可编辑”。仅在 frontend/docx-comment-reply.ts 将持久 message 与瞬时 blocked 分离，refresh 始终显示 blocked??message，成功/错误/新输入提示分别维护；没有修改父身份、范围、OOXML 或保存语义。/tmp/word-comment-reply-status-green-20261111.log：4 passed，含原 3 项与锁解除状态恢复回归。原冻结前 tsc /tmp/word-comment-reply-types-freeze-20261111.log exit0；本次由 root 新统一 build 再核类型。

准备 DOCX_COMMENT_REPLY_STATUS_ONLY=1 的独立窄补验：使用当前来源合法父目标在本地添加一条回复草稿作为恢复夹具，再 reload；检查中文回复入口、正常提示、真实 editor 临时只读/解除后提示恢复与输入可用、PM doc/草稿未改变、逐 JS 响应原始 SHA。该模式零 save/export、真实桥仅 inspect，不重复完整回复保存整链；最终 manifest、执行和截图事实待 root 新构建后追加。

## final2 最终构建状态窄补验

root 最终统一 build/budget/contract 均 exit0（41.04 秒），最终 manifest SHA256 971b7a2a8eb3461e2cee46a38af23f544631c519c786902ac9d52e9106b646d9。仅执行 DOCX_COMMENT_REPLY_STATUS_ONLY=1，Chromium 140.0.7339.16 / 4310 单次 exit0。日志 /tmp/word-comment-reply-status-final2-20261111.log；独立证据 /tmp/word-comment-reply-status-final2-20261111/evidence.json，mode=built-browser-comment-reply-status-only、ok=true。

- 使用当前真实来源的合法父目标，在本地添加一条“状态补验已有回复草稿”作为恢复夹具，然后 reload；服务端只接收 GET context/file 与 operations=[] preview。没有保存/导出请求，没有 Node patch，也没有 revision2 或下载产物；真实生产桥仅 inspect。
- 草稿恢复后中文“回复此批注”入口可用；回复输入可用，提示为“回复将在添加或保存时加入草稿”。真实 editor 临时只读时输入禁用并显示只读提示，解除后输入重新可用、正常文案恢复；锁前后 PM JSON 和已恢复 NativeDraft 完全一致。saveRequests=0、exportRequests=0。
- 实际加载 122 个 JS response，响应原始字节的大小/SHA 均逐一核对当前最终磁盘，收尾再次全部匹配。lazy-unified-main-BbENNWS9.js：16812 bytes，SHA256 09576cad04e0fcc898e61c1b85e1630fdcf0650981735f6a2ebd83ac9d939ff3；lazy-native-main-BTnyjClZ.js：22664 bytes，SHA256 bd6797d8dba3917e06c5ae30f511de67c0045bad79ca3225e858a3e7f7d7e25b；lazy-docx-main-_Yy5wQuN.js：196771 bytes，SHA256 dcaaeb6ad6fe701daf7ca2efa028197318d69055cd1ebf82ab92aaa8876ea8fa。
- 生产 bridge 保持 900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897。pageErrors、consoleErrors、failedResponses 均为空。reply-status-recovered.png 与 reply-status-unlocked.png 已逐张目视，中文引用/草稿/输入/恢复后的正确状态均可读，未再出现陈旧只读提示；端口 4310 已关闭。

最终状态补验只覆盖恢复/锁解除提示修复和最终入口资产，完整保存、真实父关联、下载及修订2重开仍使用 8c3 构建证据及独立真实 HTTP 证据，不冒称在 final2 重做完整保存整链。8c3 当时成功与当时陈旧 UI 提示事实均保留。

## 多根空输入切换缺陷与窄回归

独立审阅用真实 Tiptap/JSDOM 复现 P1：打开根 A 后不输入，再打开根 B，引用标题显示 B，但内部 pending 仍绑定 A，随后输入并 flush 的实际操作错误写到 A。此前单根浏览器成功不覆盖该场景；不把历史通过冒称为多根通过。

/tmp/word-comment-reply-empty-root-switch-red-20261111.log：新增两可信原根回归，1 failed / 5 passed，实际 targetId 为 A，期望 B。最小修复仅将 openFor 的初始化条件改成 !pending||pending.targetId!==targetId；新根空输入切换同时刷新 targetId 与当前 PM doc snapshot，非空切换仍拒绝并保留原输入。/tmp/word-comment-reply-empty-root-switch-green-20261111.log（04:37:20）：7 passed；空串和含空白/换行输入均在一次合法 reply-only PM 变化后切 B，引用/清空/真实草稿 B 目标一致，无错误；非空切换仍保留 A 引用与输入，后续 flush 仍归 A。仅运行此控制器文件，未重复完整 suite。

新增 DOCX_COMMENT_REPLY_SWITCH_ONLY=1 built smoke：基于现代来源夹具去掉第二批注的 paraIdParent，经真实生产 inspect 得两可信根，再用真实界面 A 空输入切 B、提交只归 B、A 无新增、Undo/Redo 目标保持；A 非空输入切 B 被拒，引用与输入保留，取消不入草稿。此模式零 save/export，不调用 Node patch，不重跑完整保存/HTTP；原 DOCX、manifest、bridge、实际 JS 响应字节身份逐一核对。node --check smoke/docx-comment-reply-smoke.mjs exit0。生产修复已冻结交 root 统一构建，构建后实际执行结果另追加，不以旧资产冒报新修复通过。

## final4 双根切换最终构建窄验收

root 统一 final4 build/budget/contract exit0 后，仅执行 DOCX_COMMENT_REPLY_SWITCH_ONLY=1，Chromium 140.0.7339.16 / 4310 单次 exit0。日志 /tmp/word-comment-reply-switch-final4-20261111.log；证据 /tmp/word-comment-reply-switch-final4-20261111/evidence.json，ok=true。manifest SHA256 7536053f7c47638639d26d3f4ac63285b33cd05f64fdb7d7a82229106710696d；生产 bridge SHA256 900ece6a48c11b43682cb9f9284cee1f5c3fa1aa64fabea52fdff81679fd8897。

- 真实生产 inspect 得到两可信原根 ID1/Alice 与 ID2/Bob，均 parentId=null、canReply=true。界面 A 空输入切 B 后显示 Bob 引用，提交“只回复第二根线程😀”，实际 NativeDraft 和 PM intent 只有一条 targetId=24df745389e21b5b88ca639963680dbc1dc3632707dbcc6a1c82044193c792f8，精确等于 B；A 无新增。Undo 后草稿为空，Redo 后目标/操作完全保持。
- A 非空输入尝试切 B 被拒：回复引用仍为 Alice，输入“保留第一根未提交输入”和具体提示均保全，已有 B 草稿不变；取消 A 输入不新增操作。reply-switched-second-root.png 与 reply-nonempty-switch-preserved.png 已逐张目视，中文输入、引用与正确提示可读。
- API 明确为 fixture，仅 GET context/file 与 operations=[] preview；真实生产 Python/Node bridge 仅 inspect。saveRequests=0、exportRequests=0，无 Node patch、revision2 或下载产物；未重复旧状态测试、完整保存/HTTP 链。
- 原 DOCX SHA256 67b67d4fd063d953bd259ab6dcebedf6729ce6615526c617a200194149c8e464 不变；122 个实际加载 JS response 原始字节大小/SHA 逐一与磁盘一致，收尾再次全部复核。pageErrors、consoleErrors、failedResponses 均为空；4310 端口已关闭。
- lazy-unified-main-BoR_kbPT.js：16812 bytes，SHA256 a5e4302356133a3009444c78165c2552558489c0f5a26d856da46024e0b723cb。
- lazy-native-main-DDFk4vaK.js：22664 bytes，SHA256 4248d5c4569cdb53bf48a7900d7baf34bd1296d8cf3792c1b8bde3535e8781fa。
- lazy-docx-main-CxC0HC1X.js：196790 bytes，SHA256 8510da68ba6f6bbc3ea0b849f3a32e7c96722a5cb78d31891d1aa0e7adba639b。

final4 仅补验本次多根切换修复及当前入口资产；保存、真实 OOXML 父关联、下载与修订2重开仍以既有独立证据为界，不冒称本次重做。
