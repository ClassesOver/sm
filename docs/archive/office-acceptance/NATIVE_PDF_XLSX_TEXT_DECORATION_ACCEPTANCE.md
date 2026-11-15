# PDF→XLSX 原生文字装饰专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮没有执行 OCR，也没有把可编辑文字替换为图片。

## 真实缺陷与局部修复

在既有复杂 PDF 原页后追加四行文字和真实矢量装饰：下划线、删除线、普通文字、双装饰。既有提取器/分析器已经为对应 Span 输出 `underline:true` 或 `strike:true`，并消费原线条；但 XLSX 的 `fontOfSpan` 和本地 `FontSpec`/字体序列化未传递这两个属性，实际输出三种装饰全部丢失。

本次生产改动仅 8 行，位于本地 converter 的 `vendor/pdf2docx/src/rebuild-xlsx/rebuild.ts` 与 `workbook.ts`：传递两个布尔属性、扩展既有 FontSpec，并输出标准 SpreadsheetML `<u/>`、`<strike/>`。未修改共享 workbook_engine、PPTX writer、operations 或应用 Python。继续采用现有单元格 dominant-font 策略；混合富文本逐段样式不在本次已实现范围。

## 专项与独立证据

新增 `bridge/xlsx-text-decoration.test.ts` 两项真实 RED→GREEN：字体池区分并序列化四种状态；实际复杂 PDF 端到端验证 IR 已正确识别、真实 XLSX 保留装饰、普通文字无误装饰，同时保留原页两列正文、表格数值/百分比及图片。证据 `/tmp/pdf-xlsx-decoration/{red,green}.log`，最终 2/2 通过。未重复完整测试。

原生专项文件身份：

- PDF SHA-256：`453e951ed62f237535f43e6facb949dce908e56b679cfba9fbc03af41c36848b`。
- XLSX SHA-256：`9efc8eaa48ae69fd16c1f7fd9501e14204b6436fd848e7dfd2b486384d15dc70`。
- Host Calc 渲染 PDF SHA-256：`0c91ac11033d02c05b8c368c3a376e278e966fee0c2c61755a0ff39bb8e0b48b`。

独立 `frontend/smoke/pdf-xlsx-text-decoration-verify.py` 使用 openpyxl 读取实际单元格字体和数值，要求 A1 下划线、A2 删除线、A3 无装饰、A4 双装饰；核对字号/字体、原始数值、百分比格式和图片包关系。它对修复前真实 XLSX 失败（`independent-red.log`），对修复后真实 XLSX 通过。可选第三参数读取实际 host Calc PDF，用 PyMuPDF 核对四行可提取文字及其相邻真实矢量横线，不能只凭 styles.xml 宣称渲染正确。原生 + host 证据 `/tmp/pdf-xlsx-decoration/green/independent.json`，`rendered-labels.png` 已目视确认。

## 可复现浏览器入口

`pdf-xlsx-text-decoration-source.py` 使用 Reportlab `invariant=1` 加 pypdf，从仓库 complex-layout.pdf 稳定追加装饰页；两次生成字节相同，PDF SHA-256 为 `dfd46c97c8c07387fac4363bec6add0457473ff30e2bf265b4a6ab4be184b269`。不依赖 `/tmp` 已有文件。该工厂来源经当前原生转换和独立 verifier 通过，XLSX SHA-256 为 `7089f71c34c21c626acc9059908d99c21d530c25bc78d5999492bfd5505adc62`，证据 `reproducible-independent.json`。

`pdf-xlsx-text-decoration-smoke.mjs` 复用已有 browser smoke 的真实 native grant、cookie/CSRF、转换、签发下载与冻结资源 SHA 检查。显式 XLSX 分支只选择 Excel 命令、新 fixture server 和独立 verifier，原 PPTX 默认及 source-origin 模式保持。运行目录/端口继续使用 `PDF_PPTX_TEXT_GEOMETRY_SMOKE_DIRECTORY`、`PDF_PPTX_TEXT_GEOMETRY_SMOKE_PORT`。新 server 复用既有 delivery batch 工厂与真实路由，只替换来源工厂。统一冻结后的浏览器下载及 host 验收已完成，实际身份和范围见本文末节及 NATIVE_PDF_VECTOR_RENAME_CONVERSION_ACCEPTANCE.md。

XLSX 仍按单元格/图片参考区语义重建，不保持源页打印版式：本原生专项 2 个 worksheet 的 host Calc 默认打印输出为 6 页；图片存在不代表相对图文位置保真。`overallFidelityPassed=false`、manualReview=true，validation 继续不通过，实际可读产物的下载保持非阻断。

## 统一冻结后的实际浏览器下载与 host 验收

Root 已完成真实浏览器转换与签发下载，证据 `/tmp/pdf-vector-rename-convert-xlsx-browser/summary.json`：固定 assets manifest SHA-256 为 `966b4faa9c14b76dac3158ead6ed85eed0986702442c8cc286e47c6409b9d90d`，无 asset/page/console/HTTP 错误，来源保持。实际下载 XLSX SHA-256 为 `c1f7051de8237740d19be73020eee1685fdbdcc038df0e53e395aaa1cc1ac904`，与签发 artifact 身份相同；来源 PDF SHA-256 为上述可复现工厂身份。

对该实际下载只执行一次 host Calc 渲染，命令 exit 0，日志 `host-calc.log`；实际 `rendered.pdf` SHA-256 为 `c07364986cbfd3077b2585a2d502eef4a6b4ea6fc7627d6e4c6932ecbd771634`。专属独立 verifier 对来源、实际下载和实际渲染三者复读 exit 0，`host-independent.json` 确认四种可编辑字体样式、普通文字无误装饰、原表数字/百分比、1 张源图片和实际绘制的矢量装饰。6 页打印输出中装饰文字位于第 6 页，已生成并目视核对 `rendered-decorations.png`，PNG SHA-256 为 `8d76f7c5bbdccb025d0e90920a35037346d1f1105dd6fa6f599741e66024066c`。本轮未重复原生测试或完整测试；整体保真继续不通过。
