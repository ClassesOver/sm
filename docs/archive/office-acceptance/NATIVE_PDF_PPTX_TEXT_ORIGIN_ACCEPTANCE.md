# PDF→PPTX 来源基线 X 专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。此前取消文本框自动缩放后，复杂页面左/右列仍存在约 0.967/0.991pt 的横向偏差。真实 PDFium 探针确认首个字符的 `originX=32`，但 tight glyph box 的 `x0=32.979999`；这两者语义不同，不应对所有文字框统一补偿常数。

## 最小变更与安全边界

提取器记录 `_FPDFText_GetCharOrigin` 是否实际成功，使用可选 `PdfChar.originMeasured`。分析器只给真实测量、水平 LTR、同一 baseline 且没有可见生成字符的行携带可选 `Line.originX`。合成表单文字、Widget glyph 以及 Widget 位置修正明确使测量标志失效，避免把重新构造的 box 当成原始基线。

PPTX 重建只对左对齐 LTR、非列表/目录且所有行共享同一来源 X 的文字块使用该锚点，保留原宽度、Y、字号、行距和既有页面缩放。缺失或无效来源、旋转、RTL、居中/右对齐/两端对齐、行首缩进不同或混合生成字符均保留原几何分支。使用既有 PPTX API，不修改共享 slides writer。上游 sourceSha256 保留，仅更新四个本地源文件哈希和 adaptation。

## 测试与独立渲染

`bridge/pptx-text-origin.test.ts` 的真实 RED→GREEN 覆盖正负 glyph bearing、测量失败/缺失、旋转/RTL、生成复选框与真实标签混合、各行锚点不同以及两页不同缩放。最终专项 4/4 通过，日志 `/tmp/pdf-next-pptx-origin/green-frozen.log`。失败证据包括 `red.log`、`measured-origin-red.log` 和 `synthetic-origin-red.log`。未重复完整测试。

独立 `frontend/smoke/pdf-pptx-text-origin-verify.py` 复用前批 geometry/position 验证，进一步要求实际 PPTX X 等于源 PDF baseline X（误差小于 0.0001pt），host LibreOffice 渲染的 X 误差不超过 0.03pt。对旧输出真实失败，证据 `render-red.log`；最终原生输出与 host 渲染通过，证据 `/tmp/pdf-next-pptx-origin/render-green.json`，渲染图 `frozen-render.png` 已目视核验。

最终原生 PPTX SHA-256：`0b933fec7ff4861af10bc60548e9499fdd187d6b6e4713414503a1527e9c564f`。

Host 渲染 PDF SHA-256：`9bca54b1fe3714a1108044e8c2dba39c0d8c12b74a180389d13b5c8870394abd`。

源 PDF 两列 X 为 32/317pt，host 渲染为 32.002998/316.997986pt，残差分别为 +0.002998/-0.002014pt。两列 16pt 行距误差仍在 0.03pt 内，7 个文字框保持 noAutofit 与零边距，表格无意外折行，图片和等宽 caption 保留。

## 未完成的保真

首行 baseline 仍从 90pt 变为 96.350708pt。字体 ascent/leading 与 Office importer 的基线语义没有可靠的逆映射，本次未猜测 Y 偏移或缩小字号。`overallFidelityPassed=false`，复杂字体/任意排版整体保真继续未通过。已有生成文件在验收失败时仍保留，实际下载非阻断契约不变。

以上身份对应原生专项输出；统一冻结后浏览器实际签发下载的身份与验收见下文。

浏览器专项入口 `pdf-pptx-text-geometry-smoke.mjs` 新增显式环境变量 `PDF_PPTX_TEXT_GEOMETRY_X_MODE=source-origin`。默认 `tight-box` 继续严格校验旧输出的 X；新模式调用独立 OOXML verifier 的 `--source-origin source.pdf`，以 PyMuPDF 从实际来源读取两列各 8 行基线 X 并换算 EMU，同时保留原 Y、16pt 行距、表格/图片/字体/行号检查，新增 noAutofit/零边距和来源 SHA 校验。未放宽旧断言。

本轮第一次浏览器下载 `/tmp/pdf-three-increment-pptx-browser/converted.pptx` SHA-256 `ac758ba053c15e653e56591be870f47cd15c155efe8062a4cd42ad034fcea9c9` 已通过新模式独立复读，证据 `independent-source-origin.json`。旧模式对旧 tight-box 产物仍通过，新模式真实拒绝该旧坐标；额外变异 X 一 EMU、Y 一 EMU和行距一单位均被严格拒绝，5 个局部回归检查通过。浏览器原轮曾因旧坐标断言失败，此处不将其声称为完整浏览器通过，最终重跑结果见下文。

## 统一冻结后的浏览器实际下载

root 使用显式 `PDF_PPTX_TEXT_GEOMETRY_X_MODE=source-origin` 重跑完成 `/tmp/pdf-three-increment-pptx-browser-root02/{summary,independent}.json`，实际下载 PPTX SHA-256 `a05f154f8d169e0335924cb53b2c51f12f4158f7da90ae0aa25d963bf0821720`。来源保持，37 个 JS 响应 SHA 与冻结 static 一致，page/console/HTTP/asset errors 为空；实际签发状态继续返回 validation=false 和人工复核告警。

该实际下载文件经 host LibreOffice 渲染并通过 `pdf-pptx-text-origin-verify.py`：证据 `/tmp/pdf-three-increment-pptx-host-verification.json`，左右列实际 X 误差 +0.002998/-0.002014pt；7 个文字框 noAutofit/零边距、16pt 行距、表格、图片与等宽 caption 保持。首行 Y 仍 +6.350708pt，`overallFidelityPassed=false`。`/tmp/pdf-three-increment-pptx-rendered.png` 已目视。统一构建与回归见 `NATIVE_PDF_DRAWING_OVERFLOW_ORIGIN_ACCEPTANCE.md`。
