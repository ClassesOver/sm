# PDF 样式改字与 PNG 图像同批验收（2026-11-11）

## 范围与固定来源

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用 `apps/pdf/src/main/save-pdf.ts:316–352` 的 `addImageStamp`，把待保存 PNG 纳入既有 styled replaceText + markup + vector 混合路径，没有修改 writer 或新增解码依赖。像素解码复用 pdf-lib `PNG.load`；不含 OCR、任意格式图片直传、已保存 Stamp 的编辑/删除、视觉签名元数据或复杂文字对象编辑。

输入保持原 operation 索引与 pendingMarkupMapping。文字先经既有 PDFium 样式改字，图片、矢量与标注按各自既有 writer 追加；图像保持来源页面坐标，不随文字重排。受影响页仅支持 UserUnit=1、整数 quarter-turn 旋转，含 180/270/-90/450 的归一化方向已实测。无加密/Perms/AcroForm、安全来源批注与 AP 资源闭包边界沿用上批契约，原始 AP 编码身份比较基线仍为 styled.bytes → append 最终 bytes。

## PNG 写前检查

服务端在任一 writer 前完成 canonical 标准 base64 roundtrip、PNG signature、唯一首块 IHDR、完整 chunk framing/CRC、连续 IDAT、末尾 IEND 和静态 chunk 白名单校验。仅接受 8-bit RGB/RGBA、非 interlaced、标准 compression/filter；允许的 ancillary 仅固定长度 sRGB/gAMA/pHYs/cHRM，拒绝 APNG 与其他 chunk。Node zlib 有界 inflate 核对精确 scanline 长度，每行 filter byte 必须为 0–4，再交既有 PNG.load 解码，记录 RGB/alpha 像素 SHA。

单张每边最多 2000、最多 400 万像素、base64 字符长度最多 6,000,000；同批最多 800 万像素及 12 MiB PNG 编码字节。图片仅允许 rect/image 几何载荷，拒绝 formFieldName、URL、标签或其他 shape 属性。前端做 canonical base64、header、静态 chunk framing 和同等像素/字节预算筛查；CRC、deflate 和真实像素以服务端预检为准。

CRC 使用 Node 内置 `zlib.crc32`，要求 Node 22.15+ 或 24；旧 Node 在调用新 PNG 路径时明确拒绝，不导致整个模块导入失败。本次环境为 Node 24.18，Docker 使用 Node22-slim；不将未验证的旧 runtime 标记为支持。

## 输出复核与非阻断

实际输出 Stamp 仅允许已知字典项，核对 Type/Subtype、F=4、目标页 P、Rect 与页旋转身份；AP 仅 N/Form/XObject、准确 BBox、缺失或精确单位 Matrix。解码 AP 必须恰为 `q <cm> cm /Im0 Do Q`，cm 按固定 writer 的旋转及两位小数结果一致；Resources 只含 XObject/Im0，且为间接引用。

实际 Im0 必须为尺寸匹配的 DeviceRGB/8-bit/FlateDecode，拒绝 Decode、ImageMask 或额外属性；复核实际解码 RGB 长度与 SHA。透明图必须有间接引用 DeviceGray/8-bit SMask、Decode [0 1]，实际 alpha 长度与 SHA 一致；不透明图不得出现 SMask。沿用页数、批注槽位、来源 annotation 引用/字典/AP 资源图身份复核。

第二阶段 writer 或输出复核异常继续使用 `pdf_text_drawing_writer_failed_generated_bytes_retained` / `pdf_text_drawing_output_review_failed_generated_bytes_retained`。保留实际生成 bytes/SHA/size、既有 styled 修改决策和原索引告警，不把验收失败伪装为通过。HTTP 签发与故障注入由 root 统一收口。

## 定向验证证据

- 初轮新 native 4 项因旧 image shape 排他限制真实 RED，最小扩展后 4/4 GREEN；日志 `/tmp/pdf-next-png-mixed-red.log`、`/tmp/pdf-next-png-mixed-green.log`。
- 交叉审阅发现 filter5 未拒绝，专项真实 RED→GREEN；日志 `/tmp/pdf-next-png-extra-red.log`、`/tmp/pdf-next-png-filter-green.log`。补丁只增加 scanline filter0–4 检查。
- 最终新 native 6/6 PASS，日志 `/tmp/pdf-next-png-final-native.log`。涵盖 opaque PNG/styled text/underline/alpha PNG/arrow 交错、真实 RGB/alpha/AP cm、其他页正文、digest 重现、原 indices/mapping、所有 quarter turns、写前输入预算与元数据边界、append writer 故障，以及 RGB/alpha/Matrix/cm/Decode/Resources/签名元数据 7 类后置故障实际产物保留。
- 生产冻结后仅新增两项边界回归，2/2 PASS，日志 `/tmp/pdf-next-png-boundaries.log`：坏 CRC/deflate/短长 scanline、图片独占另一页 UserUnit=2、Perms/AcroForm 来源，全部在 native SaveAsCopy 前拒绝（writes=0）。未因补测重复运行完整测试。
- 前端初轮真实 RED→GREEN；非 canonical unused padding bits 再次真实 RED→GREEN。最终新前端 4/4 PASS，日志 `/tmp/pdf-next-png-stage-ui-green.log`；此前新 PNG +旧 vector 共 4/4 PASS，日志 `/tmp/pdf-next-png-mixed-ui-green.log`。
- 前端 strict scoped tsc 通过（`/tmp/pdf-next-png-ui-typecheck.log`）；新 helper strict scoped tsc 通过（`/tmp/pdf-next-png-helper-typecheck.log`）。测试入口闭包仍有 operations.ts 后段旧 union、Electron resourcesPath、缺失 GenOffice UI 等诊断（`/tmp/pdf-next-png-typecheck.log`），本轮 helper/测试无诊断，不声称全项目 typecheck 通过。
- form agent 对最终 PNG 预检/输出检查只读交叉审阅无新增阻塞。未提交或部署，未运行全量项目测试。

## 真实浏览器入口

`frontend/smoke/pdf-text-png-mixed-smoke.mjs` 使用冻结生产资源、真实 PDF.js/grant/cookie/CSRF/packed engine/publication/download/reopen；仅 fixture 持久化仓储为内存实现。UI 从真实隐藏 file input 上传 RGB/RGBA fixture，经现有 canvas normalization 和 pointer 放置，与 AA/BB/CC 选区字体字号粗斜体颜色、underline、arrow 交错；验证 5 个 operations、undo/redo、预览确认与签发下载 SHA。

独立 `frontend/smoke/pdf-text-png-mixed-verify.py` 由 Pillow 生成 fixture，并用 pypdf/Pillow 复核下载的文字字体/字号/基线/嵌入字体、其他页内容/页面框/旋转、underline、Stamp/P/AP/BBox/cm/Im0/SMask、实际 RGB/alpha bytes 与 arrow 路径。预期像素来自真正 staged 的 canvas-normalized PNG，避免将全透明像素 RGB 归零误判为生产错误。

环境：`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_PNG_MIXED_SMOKE_DIRECTORY`，可选 `PDF_TEXT_PNG_MIXED_SMOKE_PORT`（默认 4339）。脚本 node --check 与 Python compile 通过。统一冻结 runtime 后真实 browser 已 exit 0，证据 `/tmp/pdf-png-choice-rich-png-browser/summary.json`，37 个实际 JS 响应与冻结资源匹配，来源未变且错误列表为空。实际下载 `mixed.pdf` SHA-256 `e19dd2f159136b79a7878b0579061e480804baf8352c502fbe771a82898f0a89`；独立 pypdf/Pillow verifier 通过，root 已目视最终 UI。PNG 两项 HTTP 非阻断检查通过，详见 `NATIVE_PDF_PNG_CHOICE_RICH_TEXT_ACCEPTANCE.md`；全站 Word 分块预算失败和完整保真边界仍保留。
