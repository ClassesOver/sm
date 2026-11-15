# PDF 样式改字与新增文字标注同批验收（2026-11-11）

## 边界与最小实现

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。固定源 `save-pdf.ts:applySaveRequest` 本身先改内容流再追加批注；本项目样式改字因需分段字体、真实 advance 及写后复核而走既有 `replaceStyledText`。本批仅将该既有写入器与固定 `applySaveRequest` 的新增 markups 路径接合，没有重造排版器或批注写入器。

接受 styled `replaceText` 与新增 `addMarkup` / `highlight` 的组合；`addMarkup` 四类高亮、下划线、波浪线、删除线维持既有 schema。仅无加密、Perms、AcroForm 的来源，所有受影响页（含仅改字的页）须使用默认 UserUnit，标注页来源标注须可读；未涉及页不额外限制。所有标注来源页身份、显式 sourceSha256、quad 形状、颜色与 CropBox 范围先于任一写入器核验。每个替换仍由原写入器以不可变 sourceSha256/objectId/expectedTextSha256 预检；失效目标按既有回执跳过，其他有效目标和新增标注可继续。

文字改写先执行，新标注后追加，这是固定源写入顺序；输入可交错，回执的 applied/skipped 与 pendingMarkupMapping 保留输入原索引。来源页序不变，标注只使用来源 PDF 坐标，不会按新文字长度自动调整范围；实际 PDF 预览继续要求人工确认。已有标注删除、便签、回复、插入静态文字、表单、页面结构和任意混合仍不开放。

writer 异常以 `pdf_text_markup_writer_failed_generated_bytes_retained` 告警，保留已经生成的样式改字 bytes，新增标注原索引标记未应用。writer 返回 bytes 后的映射/复核异常以 `pdf_text_markup_output_review_failed_generated_bytes_retained` 告警，保留同时含实际改字和标注的 bytes，不冒称对应标注复核通过。最终 SHA/size/previewDigest 都绑定保留下来的实际字节，不回退来源也不重抛后置复核异常。

## 定向验证

- `bridge/text-markup-mixed.test.ts` 首轮 3 failed / 1 passed（确认为原排他限制导致）→ 四项 GREEN：交错两替换/两标注及原索引、所有标注预检在 native writer 前、失效文字目标只影响本索引、运行阶段标注 writer 故障保留实际改字。
- 新增两项专项单独运行 GREEN：保护来源在两个 writer 前拒绝；标注写后复核故障保留实际改字和两条标注但回执如实告警。
- 交叉审阅再补两项定向验证：另一页的样式替换目标含 UserUnit=2 时，原实现未拒绝（RED），最小补丁扩到所有受影响页后 GREEN；来源已有安全标注的 Subtype/QuadPoints/AP 解码字节 SHA 保留，新 pending mapping 只指新增槽位。PDFium 会把颜色的 0.3/0.4 序列化为 0.30000001/0.40000001，因此颜色按 1e-6 数值容差比，未宣称 PDF 字节级原样保留。证据 `/tmp/pdf-next-mixed-crossreview-red.log`、`pdf-next-mixed-crossreview-green.log`。
- `src/pdf-text-markup-mixed.test.ts` 原 1 failed / 1 passed → 2 passed；既有 `pdf-replace-text-style.test.ts` 两项同步通过。前端 validator 仅缩小原排他条件，全部整对象/UTF-16选区样式逻辑保留。
- engine 日志 `/tmp/pdf-next-mixed-red.log`、`pdf-next-mixed-green.log`、`pdf-next-mixed-extra-green.log`；前端日志 `/tmp/pdf-next-mixed-ui-red.log`、`pdf-next-mixed-ui-green.log`。
- 前端一次 `tsc --noEmit` 未通过，当前唯一错误在并行 Word 变更 `docx-ruler.test.tsx` 的 `extendedIndents` 属性；不能把该检查标记全项目通过。本批文字文件未报告错误，日志 `/tmp/pdf-next-mixed-typecheck.log`。
- 引擎定向 strict tsc 仍受既有 `form-design.ts` 与原 operations 分发后段类型错误影响；本批新增段与新测试的类型问题已修正，最后的新测试入口日志未再报告 `text-markup-mixed.test.ts` 诊断，不能标记依赖闭包全 typecheck 通过。日志 `/tmp/pdf-next-mixed-test-typecheck-strict.log`。

## 浏览器交付入口

专项 `frontend/smoke/pdf-text-markup-mixed-smoke.mjs` 沿用实际 HTTP/grant/cookie/CSRF、冻结生产 assets、packed PDF engine、实际预览确认、签发下载和重开；fixture 持久化仓储为内存实现。脚本从 UI 执行 underline → 选区样式改字 → squiggly，检查 undo/redo、原始交错顺序、下载 SHA，使用 pypdf 独立核验分段实际字体/基线、两个批注的 QuadPoints/颜色/AP 与其他页正文。

环境为 `PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_MARKUP_MIXED_SMOKE_DIRECTORY` 与可选 `PDF_TEXT_MARKUP_MIXED_SMOKE_PORT`（默认 4336）。`node --check` 已通过。

root 已用统一冻结构建完成真实浏览器验收：`/tmp/pdf-next-mixed-browser-root01/summary.json`、`independent.json`，`ok=true`、来源保持、37 个实际 fetched JS 资源与冻结字节逐一匹配，page/console/HTTP/asset errors 全部为空。最终实际下载 PDF SHA-256 `5af44a552aa70448ad05058d7709fc00a96da4ced9b5e3df29314e9ba9753aa9`。独立 pypdf 核验 AA/BB/CC 分段字体/字号/基线、红色选区、Underline/Squiggly 的来源坐标/AP 和另外两页正文保持；最终重开画面已目视核验。统一构建身份见 `NATIVE_PDF_MIXED_FONTS_POSITION_ACCEPTANCE.md`。

`test_http_publication_lineage.py::test_static_text_postwrite_review_warning_keeps_verified_http_download` 登记 `styledMarkup` 和 `styledMarkupWriterFault`。前者实际生成两阶段字节后注入复核失败，后者模拟第二阶段失败回执并保留第一阶段真实改字字节；实际 HTTP 下载与回执 SHA 一致，告警不阻止签发。两个新增场景、字体属性故障场景与签发静态守卫共 4/4 通过，日志 `/tmp/pdf-next-three-domains-http-final-green.log`。源无效/保护边界在写前拒绝，与后置告警非阻断区分。
