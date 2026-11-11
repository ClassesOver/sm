# PDF 样式改字与箭头/多边形/手绘同批验收（2026-11-11）

## 最小范围

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用 `apps/pdf/src/shared/ipc.ts:DrawingInput` 和 `src/main/save-pdf.ts:addDrawingAnnot` 的既有 arrow、polygon、ink writer；在上一批 styled replaceText + markups + rect/ellipse 路径上增加三种矢量，不重造 writer，不包含 OCR、链接、图像、测量标签、便签或视觉签名元数据。

箭头只允许 from/to，端点在来源 CropBox 内且长度至少 2pt；多边形 3–200 有限顶点，全部在 CropBox 内且二维 extent 至少 1pt；手绘 1–20 条路径，每条 2–2000 点、偶数有限坐标、全部在 CropBox 内。各 shape 仅允许自己的 geometry 参数，拒绝 formFieldName、其他形状字段及附加标签。颜色和线宽沿用既有严格 schema。矢量使用来源坐标，不随替换文字重排。

写前复用 source SHA、pageId、受影响页 UserUnit=1、无加密/Perms/AcroForm、安全来源批注检查；未涉及页不额外限制 UserUnit。输入可交错，回执、pendingMarkupMapping 保留输入原索引。文字仍先经既有样式改字，批注再经固定源 writer 追加。

## 写后复核与非阻断

输出页数、每页 annotation 槽位总数、所有来源 annotation 引用和字典均须保持；另补 AP 普通流/状态流及完整资源闭包的有界递归指纹：包含 PDFRef 原身份和解析对象、规范化字典、数组、stream 字典及原始编码字节。visited 防引用环；每个 AP 指纹限 4096 节点、64 层，写前遍历来源全部 AP，超限或悬空资源引用先于任一 writer 拒绝。避免同一引用背后外观流或 ExtGState 透明度变化但表面字典 SHA 未变的漏检。

新增矢量检查 subtype、页 P 引用、C、BS.W、Rect、AP Form/XObject、BBox、inspectPdf census；AP Matrix 仅允许缺失或精确 identity，拒绝旋转、缩放、镜像或其他额外变换。箭头复核 L 以及主线和两个头部；多边形复核 Vertices、全部路径与 h/S 闭合；手绘复核 InkList、全部路径和每条 m/S。解码 AP 的操作符顺序、参数数量及数值须与来源几何一致，坐标按固定 writer 两位小数序列化使用 0.0051pt 容差。

固定 polygon writer 的 annotation Rect 和 AP BBox 为顶点包围盒，不加 stroke pad；本项目如实沿用并核验，未声称消除了上游粗边界裁切风险。矩形、椭圆、箭头与手绘仍按 writer 的 width+2 扩展包围盒；箭头先计入两个头部。

资源原始编码指纹的比较基线是 `styled.bytes → append 最终 bytes`，不声称跨 PDFium 样式改字阶段保持原始编码逐字不变。最小探针确认 PDFium 可合法把旧 AP 的未压缩流转为 FlateDecode，而解码字节 SHA 保持；写前来源遍历只验证图可在预算内完整审阅。

第二阶段 writer 或后置复核异常沿用 `pdf_text_drawing_writer_failed_generated_bytes_retained` / `pdf_text_drawing_output_review_failed_generated_bytes_retained`，标注沿用 `pdf_text_markup_*`。保留实际生成 bytes、SHA、size、digest 和既有样式修改决策；本轮 additions 原索引告警，不冒称复核通过。下载非阻断由统一 HTTP 回归收口。

## 定向证据

- 新 native 四项真实 RED（旧 rect/ellipse 排他限制）后 4/4 GREEN：arrow/styled/polygon/markup/multi-stroke ink 交错、来源 Square 的引用与 AP 保持、原索引/mapping、真实文字与另一页正文、digest 重现；source/geometry/禁用 payload/UserUnit 在 native writer 前拒绝；append writer 与后置复核异常保留实际字节。日志 `/tmp/pdf-next-vector-mixed-red.log`、`/tmp/pdf-next-vector-mixed-green.log`。
- AP 路径破坏专项验证缺失箭头头部可被复核捕捉，且返回的实际字节仍保有完整头部。来源 Square 的 AP 流原 Ref 下变更专项先真实 RED，补 AP 身份比较后 GREEN。两专项与健康混合共 3/3 PASS，日志 `/tmp/pdf-next-vector-ap-review-red.log`、`/tmp/pdf-next-vector-ap-review-green.log`。
- Perms 与 AcroForm 来源在两个 writer 前拒绝，native SaveAsCopy 计数为 0；专项 1/1 PASS，日志 `/tmp/pdf-next-vector-protection-green.log`。全页来源 annotation 身份复核调整后健康混合 1/1 PASS，日志 `/tmp/pdf-next-vector-boundary-green.log`。
- 交叉审阅补 AP Matrix 旋转注入真实 RED→GREEN，实际字节保留、返回原索引告警；日志 `/tmp/pdf-next-vector-matrix-red.log`、`/tmp/pdf-next-vector-matrix-green.log`。旧 AP 的 GS1 间接 ExtGState CA/ca 在原 ref 下变更、4100 节点超预算写前拒绝，两项真实 RED→GREEN；日志 `/tmp/pdf-next-vector-resources-red.log`、`/tmp/pdf-next-vector-resources-green.log`。form agent 对两个最终契约只读复审 PASS。
- 上批 rect/ellipse 健康混合定向回归 1/1 PASS，日志 `/tmp/pdf-next-vector-rectangle-regression.log`。
- 最终资源图改动后按 root 要求仅运行受影响专项：本批 native 文件 10/10 PASS、旧 rect/ellipse 健康 1/1 PASS；日志 `/tmp/pdf-next-vector-final-native.log`、`/tmp/pdf-next-vector-final-rectangle.log`。
- 前端新 vector 两项先 1 failed / 1 passed，扩展后与既有 drawing mixed 两项共 4/4 GREEN，日志 `/tmp/pdf-next-vector-mixed-ui-red.log`、`/tmp/pdf-next-vector-mixed-ui-green.log`。
- 前端新测试入口 strict tsc 通过，日志 `/tmp/pdf-next-vector-mixed-ui-typecheck.log`。引擎定向 strict tsc 依赖闭包仍有既有 form-design-properties、原 operations 后段 union、Electron resourcesPath 与缺失 GenOffice UI 类型诊断；本批 mixed 分支与新测试无诊断，不能标记全项目 typecheck 通过。日志 `/tmp/pdf-next-vector-mixed-typecheck-final.log`。
- 新 smoke 的 `node --check`、内嵌独立 Python verifier 的 compile、定向生产文件 `git diff --check` 通过。未运行全量测试、未提交或部署。

## 浏览器交付入口

`frontend/smoke/pdf-text-vector-mixed-smoke.mjs`：真实生产资源、PDF.js、grant/cookie/CSRF、packed engine、预览确认、保存签发、下载、重开；仅 fixture 持久化仓储为内存实现。UI 使用 pointer 箭头、选区样式改字、underline、逐顶点 polygon/Enter 完成及 pointer 手绘折线，验证 5 个交错 operation、undo/redo、实际 SHA。独立 pypdf 验证 Line/L/两个头部、Polygon/Vertices/闭合、InkList/全部路径、AP/Rect/BBox/P 以及实际字体/基线和其他页正文。

环境：`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_VECTOR_MIXED_SMOKE_DIRECTORY`、可选 `PDF_TEXT_VECTOR_MIXED_SMOKE_PORT`（默认 4338）。统一冻结后的实际浏览器已通过，证据 `/tmp/pdf-vector-rename-convert-vector-browser/summary.json`，37 个 JS 响应与同一 static SHA 一致、来源保持且各类 errors 为空。实际下载 PDF SHA-256 `6df2d11b206e5272382e289acbcaba85d9a5bae298d0e6f9b13724c828ed93e4`，5 项交错操作及 Undo/Redo、预览确认、下载/重开和独立 pypdf 核验通过，最终画面已目视。HTTP styledVector / styledVectorWriterFault 两项同新运行包通过，日志 `/tmp/pdf-vector-rename-convert-http.log`；静态/运行包身份及完整边界见 `NATIVE_PDF_VECTOR_RENAME_CONVERSION_ACCEPTANCE.md`。
