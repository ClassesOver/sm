# PDF 未保存新增便签 AI 改文与回复（2026-11-11）

## 固定源与本轮目标

- 固定源 /home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c，apps/pdf/src/renderer/ai/pdf-skill.ts 的 Review workflows：逐线程读批注与对应正文、执行明确修改后回复；歧义澄清、纯讨论或 AI 自身批注跳过。
- 上轮已保存根便签的闭环不作为本轮未保存新增便签的验收替代。本轮补齐 addTextAnnotation 草稿根与 replaceText、replyPendingNote 同批的身份链路。

## 根因及最小实现

- 原 review._original_note 只可映射原始 PDF 已保存根，未保存新根无法重绑；引擎和前端另显式拒绝 replyPendingNote 与 replaceText 混用。
- 引擎复用现有 normalizeAddedNoteDates 的严格有序 append 检查：新引用不得与旧引用复用；根便签不能带 IRT/RT；输出数量、位置、正文、矩形及同页父引用必须复读一致。在该可信位置收集精确新 PDFRef 与完整字典摘要，最终输出再按同一引用与摘要复读，生成 pendingNoteMapping，纳入 previewDigest。
- 映射绑定 operationIndex、原 pageId、原 localId（如有）、实际 effectivePageId、annotationId、sourceRef、expectedAnnotationSha256。根实际未执行或最终引用/摘要不一致时不签发其映射；不凭便签文字匹配，不把有效预览的 ref 冒充原始 sourceRef。
- NativePDFReviewReader 仅用于批注处理，在已有真实预览/完整 base 快照上核验映射属于 applied 原操作、同一原页与有效页、同一 localId、实际安全根、新引用和唯一归属；空缺映射不能得到 pending 回复目标。共享 native.py 经 root 授权仅追加该回执字段透传。
- 文字对象新投影分支核对 objectId 尾段（绑定对象路径、正文、完整矩形）与 expectedTextSha256，并继续拒绝同一原对象已有草稿改字；页面几何变化不放宽。不能只按正文认领对象。
- AI 私有回复候选携带原 parentOperationIndex 与可信 parentLocalId。旧草稿根无 localId 时，以完整 base 摘要与 operationIndex 确定性产生 localId，仅在候选副本中补入；任务原 base 与采纳完整快照保持不变。新回复固定 author=AI Assistant；引擎完成真实文字修改后，使用现有原生 localId/replyToLocalId 写根和回复并核验 IRT。
- 真实改字跳过时丢弃关联成功回复，撤销仅为该回复补入的 localId，并重新真实预览；原根操作保留原貌。取消、过期 base、原文冲突与来源校验继续沿原任务机制。
- 前端只同步已验证的 pending+replaceText 组合，保留裁切/尺寸、父 localId、原页、任意作者/额外字段拒绝；评论树显示已核验的 AI Assistant 作者。

## RED 与分批验证

- 新引擎回归先因缺少 pendingNoteMapping 失败；客户端回归先由旧 pending+replaceText 守卫失败；实际 service 回归先为 failed；作者显示回归先得到空作者；真实 text-skip 回归先暴露多余生成 localId。均先观察失败，再作对应最小修改。
- test_native_pdf_review_pending.py 五项已分批通过：真实 Agno ScriptedModel 工具循环→service→preview→accept→pypdf；同外观第二个无 localId 根精准收到 AI 回复、正文700、IRT指向第二个新根；过期完整base拒绝；长文本实际skip后无成功回复且根原貌保留；吞取消不复活；未执行/外来页/ref/hash/重复/错localId映射拒绝；同页无关 MANUAL DRAFT 保留、已有人工改字对象禁止覆写（/tmp/pdf-ai-review-pending-tests-20261111/manual-draft.log）。未重新调用真实 provider。
- 新 bridge/review-pending-note.test.ts 两项先RED后GREEN；受影响 local-note-replies 与 note-timestamps 合计10项通过，日志 /tmp/pdf-ai-review-pending-tests-20261111/engine.log。覆盖重复根精确映射、实际72正文、AI作者/IRT、任意作者/外来属性/错根拒绝，以及既有本地回复与日期兼容。
- 既有已保存根实际service/accept仅复核受影响单项通过，日志 /tmp/pdf-ai-review-pending-tests-20261111/saved-root-compat.log；没有重复上轮完整专项。
- 客户端 pdf-review-replies 4项、受影响 pdf-local-replies 3项、pdf-comments 7项合计14项通过。ruff F、py_compile、node --check通过；pytest保留环境已有 imghdr 弃用warning。
- 当前实际 PDF bridge dist/cli.mjs SHA：d47b98af3458a09104a5fe207f5c93f4da82cb60571a4bcbacca40e9e91ccddb。仅为真实Python回归单独bundle PDF bridge；本 agent 未构建共享前端。
- 为保留实际文件，仅追加一次带证据目录的首项窄回归，未重跑完整文件或旧套件：/tmp/pdf-ai-review-pending-actual-20261111/ 下保存 source.pdf、preview.pdf、actual-evidence.json。实际来源SHA d6e888dc8de7437d605f653147a7535497756e06e4224ce79dda8776ea684aaf；预览9486字节、SHA ef017ed422bded6c3f6077efe3b05c058d4ebc48d9e2e846141e30b141c7ebb9；previewDigest ed2f40ed95062f47dc865979bb90aa519462ac32057bf2ba11313cbb9246b413。另从磁盘独立pypdf回读700、AI Assistant和IRT=23R，精确指向第二根23R、非第一根21R，来源与输入base保持不变。证据记录仍明确为ScriptedModel经真Agno，不代表真实provider。

## 专属 built-browser 方式与当前边界

前端统一构建由 root 负责。辅助新增仅 pending 窄用户流程，不能将上轮五场景结果算成本轮结果。在 frontend 目录运行：

    PDF_AI_REVIEW_SMOKE_DIRECTORY=/tmp/pdf-ai-review-pending-built-20261111 PDF_AI_REVIEW_SMOKE_PENDING=1 node smoke/pdf-ai-review-smoke.mjs

- 只 seed 两个重复外观、无 localId 的真实待保存根。真 Agno 按实际 append 映射 operationIndex=1 处理第二个；其余来源批注与重复根保持原样。
- 必须显式采纳，核对 localStorage 完整候选、原根不变、第二根仅补身份及 parentLocalId。通过实际编辑页签“校验当前修改”验证画布700、四项已执行清单、确认框未选；实际HTTP PDF身份须与独立预览相同，pypdf核对AI作者及IRT精确第二新根。
- 同时严格记录实际manifest及JS响应字节SHA、原视口可滚动且不重叠、页面/控制台/HTTP/资产错误、来源不变及没有save/export。
- 本文创建时新冻结构建及本轮浏览器尚待 root 完成；不得声称已完成 built-browser 验收。未保存新根之外的复杂重排、合并/拆分后映射等既有能力边界仍保留。

## 冻结构建 pending 窄 built-browser：通过

- root统一构建后仅运行上述pending命令一次，脚本exit0：cases=1、assets=21。证据 /tmp/pdf-ai-review-pending-built-20261111/summary.json，validationMode=pending-user-preview、ok=true；没有重跑normal、旧五场景、真实provider或构建。
- 实际manifest SHA 8c3baa3ed28283fb6e443e22b4590ee3ab82c38fd1f592a0bbcb06076c300a9c，与root冻结值精确一致；21个实际JS响应字节SHA均与磁盘构建匹配。PDF bridge SHA仍为d47b98af3458a09104a5fe207f5c93f4da82cb60571a4bcbacca40e9e91ccddb。
- 两个无localId、同外观/文字/位置的真实初始草稿根随start完整传入。候选生成前localStorage原base不变；显式采纳后完整操作精确匹配候选：第一根原貌保留，第二根只补可信localId，后接replaceText及固定AI作者的replyPendingNote，parentLocalId指向第二根。没有凭相同便签文字选择父线程。
- 编辑页签实际点击“校验当前修改”，真实 /api/preview、/api/preview.pdf 对相同四操作batch均200；页面进入data-pdf-preview=true，PDFjs textLayer为 Amount due 700 和保留原段，不含Amount due 500。实际执行清单恰四项均已执行（两根文字批注、原位改字、待保存便签回复），确认复选框初始未选。
- 实际HTTP PDF9652字节、SHA 1185acbd9af925c4d36d2521bc9a2f1211507c016cc17481d55bf8f7ca66847b，与独立候选真实预览字节精确相同；previewDigest 416ae8296b6023e2b400a1a3d885ffabf7961369cda823e21ba986df0b3da5ef。另从保存的normal-ui-preview.pdf独立pypdf复读700、唯一AI Assistant回复；IRT=23R精确对应operationIndex1的新根23R，非operationIndex0根21R。
- 原1550×1100视口，review高343px、clientHeight342px、scrollHeight779px、实际滚动437px；maxHeight495px、overflowY=auto、flexShrink=1。review bottom与真实后方选区AI面板top均为1039px，无重叠。已目视normal-ui-preview.png、pending-scrolled.png：700画布、四项清单、未选确认框清晰；滚动末条为第二个待保存根处理与AI回复，后方助手独立显示。
- pageErrors、consoleErrors、httpErrors、assetFailures均空。来源SHA 0ce9b16b1fe2e16503bb17d64f743e3d536dc4b1a1d90fca8d61de0ad6ff8027 保持不变；HTTP记录零save/export。ScriptedModel经真Agno仅一次，不混同真实provider证据。浏览器和专属服务已退出；生产源保持冻结，未修改产品或重构建。


## 2026-11-11 独立只读审阅

独立 agent 复核 pendingNoteMapping、parentOperationIndex/localId 授权、完整 base snapshot、实际 append 新 PDFRef 与字典摘要复读、mapping 纳入 previewDigest、applied 拒绝认领未执行根、同外观根精确归属、legacy localId 仅候选补齐，以及取消和过期采纳检查；指定范围内未确认可触发缺陷。

本次为源码、既有证据与窄测试源码的独立审阅，未重跑 provider、浏览器或测试；未动态注入采纳过程中的并发取消或过期故障。editor.preview_file 回执属于服务内可信边界，不能将此结论外推为任意外部回执可被接受。现有浏览器使用真实 Agno 加 ScriptedModel，不是实际 provider。
