# PDF 样式改字与矩形/椭圆同批验收（2026-11-11）

## 范围和边界

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。在已验收的样式改字与新增文字标注组合上，只增加既有 `addDrawing` 的 `rect`、`ellipse` 子集。文字仍用现有 `replaceStyledText`，绘图复用固定源 `applySaveRequest` 的矢量 AP writer；没有新造图形写入器，不包含 OCR。

允许交错输入 styled `replaceText`、新增 `addMarkup` / `highlight`、矩形及椭圆；回执与 pendingMarkupMapping 保留输入原索引。绘图和文字标注使用来源 PDF 坐标，不跟随改字重排。仍不开放其他绘图、旧批注修改、便签、回复、表单或页面结构混合。

所有显式 sourceSha256、页身份、绘图 schema 白名单、矩形/颜色/线宽及 CropBox 均在任一 writer 前核验。受影响页包括只改字的页面，必须 UserUnit=1；未涉及页不加限制。受保护、Perms、AcroForm 来源仍拒绝这条混合路径。写后验证页数、新增 annotation 槽位、原 annotation 前缀引用和字典身份、Square/Circle、页 P 绑定、线宽扩展后的 Rect、颜色、BS.W、AP.N 非空、BBox 及 inspectPdf census。

第二阶段 writer 失败使用 `pdf_text_drawing_writer_failed_generated_bytes_retained`；第二阶段已生成字节后的复核失败使用 `pdf_text_drawing_output_review_failed_generated_bytes_retained`。本轮所有 additions 按原索引标记 skipped，已完成 styled 决策保持；实际 bytes、SHA、size、previewDigest 不回退。标注沿用 `pdf_text_markup_*` 告警。后置故障不丢弃实际产物，不将未复核通过的绘图冒称 applied。

## 定向验证

- Native 新增四项先真实 RED（旧排他限制），实现后最终四项 GREEN：交错 rect / styled多行 / underline / ellipse、原索引与 pending mapping、实际字体及其他页正文；source/geometry/shape/extraneous 参数及另一页 UserUnit=2 在 native writer 前拒绝；append writer 故障保留实际 styled bytes；append 后复核故障保留实际 styled 与三个 annotation bytes，回执如实告警。日志 `/tmp/pdf-next-drawing-mixed-red.log`、`/tmp/pdf-next-drawing-mixed-green.log`。
- 无文字标注、仅 styled + rect + ellipse 的新增专项 1/1 PASS，pendingMarkupMapping 为空，Square/Circle 实际存在。日志 `/tmp/pdf-next-drawing-only-green.log`。
- strict tsc 发现 pdf-lib 不提供 PDFRawStream 的 lookup 类型重载，已缩小为无类型 lookup 后 `instanceof PDFRawStream` 原生判断。随后健康混合与无 marker 两项 2/2 PASS，日志 `/tmp/pdf-next-drawing-type-narrowing-green.log`。未重复完整套件。
- 前端新 drawing 两项与既有 marker mixed 两项共 4/4 GREEN；新项先真实 RED，日志 `/tmp/pdf-next-drawing-mixed-ui-red.log`、`/tmp/pdf-next-drawing-mixed-ui-green.log`。
- strict 定向依赖闭包仍有既有 operations 后段 union、process.resourcesPath、未解析 GenOffice UI 类型及并行表单类型诊断，不能标记全量 typecheck 通过。本批 mixed 分支与新测试自身无诊断，日志 `/tmp/pdf-next-drawing-mixed-typecheck-final.log`。
- `node --check frontend/smoke/pdf-text-drawing-mixed-smoke.mjs` 与本批生产文件 `git diff --check` 通过。

## 浏览器与统一交付入口

`frontend/smoke/pdf-text-drawing-mixed-smoke.mjs` 复用真实 HTTP server、grant/cookie/CSRF、冻结生产资源、PDF.js、packed engine 和实际发布下载重开。仅 fixture 持久化仓储为内存实现。UI 真正 pointer drag 创建矩形 → 选区字体/字号/粗斜体/红色改字 → underline → pointer drag 椭圆，检查 undo/redo、交错草稿、预览确认、下载 SHA 和重开修订。独立 pypdf 核验 AA/BB/CC 的实际字体/字号/基线、选区颜色、Underline QuadPoints、Square/Circle Rect/颜色/线宽/页绑定/BBox/矢量路径及其他页正文。

运行环境：`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_DRAWING_MIXED_SMOKE_DIRECTORY`、可选 `PDF_TEXT_DRAWING_MIXED_SMOKE_PORT`（默认 4337）。本分支不单独重建 static/runtime，统一冻结构建与浏览器运行由 root 收口；初次交接时仅脚本就绪；最终统一浏览器结果见下文。

HTTP `styledDrawing` / `styledDrawingWriterFault` 场景已由 root 登记并完成定向验证，结果见下文。本分支不改共享签发测试、哈希清单或总体完成状态。

## 统一冻结后的实际浏览器与 HTTP 结果

root 已完成 `/tmp/pdf-three-increment-drawing-browser-root02/{summary,independent}.json`：真实 UI 矩形→样式改字→下划线→椭圆、Undo/Redo、实际预览确认、签发下载和重开全部通过。实际下载 PDF SHA-256 `bf04af65f1ac169119fe35eb286a6ff288538ca2f2d8990a69e327b7f2799272`；来源保持，37 个实际 JS 响应 SHA 与同一冻结 static 对照一致，page/console/HTTP/asset errors 为空。最终重开画面已目视。

首轮浏览器实际下载成功，独立 verifier 曾把解引用后的 `/P` 字典与被 pypdf 补充 CropBox 的 PageObject 作结构比较而误失败；现改为严格比较原始 IndirectObject 页引用。先对首轮已下载字节独立复验，再完整重跑专项通过，没有更改生产代码或放宽 AP、几何、字体断言。`independent-reverified.json` 保留初轮字节核验记录。

HTTP 故障登记 `styledDrawing`、`styledDrawingWriterFault` 通过：输出复核告警或第二阶段故障回执仍保留真实改字文件和可核验下载；不把实际未通过复核的编辑标为验收通过。日志 `/tmp/pdf-three-increment-http-final.log`。统一身份见 `NATIVE_PDF_DRAWING_OVERFLOW_ORIGIN_ACCEPTANCE.md`。
