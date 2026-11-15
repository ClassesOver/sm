# PDF→XLSX 货币精度及百分数列宽专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。先只读定位两页来源打印六页的布局模型原因，保留为未解决诊断，不用页面缩放掩盖；本轮仅修复货币/百分数可独立验证的数字显示缺口，未执行 OCR。

## 真实缺陷与局部改动

既有 parser 将 `$12345.678` 写成 `"$"#,##0.00`、`€31.1` 写成 `"€"#,##0.00`、`-£0.0500` 写成 `"£"#,##0.00`；真实数值虽保留，number format 固定两位会舍掉或补出未经来源声明的小数。百分数原有精度解析正确，但非表格行没有列宽 claim，仍可能出现 `###`。上一批普通小数列宽不能用于证明独立货币列已正确。

生产仅改 `vendor/pdf2docx/src/rebuild-xlsx/numbers.ts` 与 `rebuild.ts`。货币沿用现有可接受符号、前后缀、负号、千分组及 ¥/￥ 归一化规则，把既有固定 2 位模板改为按来源小数位数生成；裸数字、整数、指数和百分数的值解析/format 规则保持。全部仍是 `<v>` 真数字。

已有非表格数值最小宽度扩展到已识别货币和百分数，继续取 source ink 宽与当前输出字体 advance 的较大值，加既有 5 px Excel padding。货币既有 `#,##0` 格式会为未分组来源加逗号，因此按整数位数计算所需 comma 数，扣掉源中已有 comma，用同一字体的实际 glyph advance 计入宽度。没有通用 formatter、自造近似字符宽度或新依赖；保留更宽 table claim，普通整数/指数仍走旧路径；未更改 slot/打印布局或公共 workbook/slides/doc engine。

## 专项及独立验收

新增 `bridge/xlsx-currency-precision.test.ts` 三项真实 RED→GREEN：前/后缀多种货币原小数位；单个独立货币及百分数行的输出 glyph/分组 comma 宽度；真实稳定复杂 PDF 的 B8–B12 数值及 format。日志 `/tmp/pdf-xlsx-print-currency/{currency-red,currency-green}.log`，最终 3/3 通过。只运行受影响旧 decimal 专项三项并通过（`affected-decimal.log`），覆盖普通小数精度、独立小数宽度、保留更宽 table claim/整数指数旧路径，没有重跑旧 native 或完整测试。

新稳定 `frontend/smoke/pdf-xlsx-currency-precision-source.py` 复用 decimal/font 工厂，在第二页 x=300 的独立 B 列追加五行货币/百分数，避免既有 A 列宽掩盖本次缺口；原 complex PDF 页及原六段 rich、普通小数和字体证据保持。两次生成字节相同，来源 PDF SHA-256 为 `db01c13b8865a262ae9ce0123a38201b0071782e815f5091d401b9b455c3f373`。当前原生 XLSX SHA-256 为 `d4154d8e0d4b6fc0a669c453aa7b3d2cadcd843bddf1957dbc2d4d344731f9a1`，A/B 列宽分别为 14.09 / 14.83 chars。

独立 `pdf-xlsx-currency-precision-verify.py` 复用前批 openpyxl rich/decimal/font verifier，再核对 B8–B12 真数字及小数格式。它对保留的真实 pre-fix XLSX 明确失败于 B8 的旧 `"$"#,##0.00`，证据 `independent-red.log`；对修复后来源/XLSX 通过，证据 `/tmp/pdf-xlsx-currency-precision/green/independent.json`。可选实际 host PDF 时还要求无 `###` 且可提取 `$12,345.678`、`€31.1`、`-£0.0500`、`12.345%`、`0.0007%`，并复验前批普通小数、实际嵌入 BoldItalic 字体、矢量装饰及 minority 普通样式。目前尚未计入最终真实 host 通过。

## 浏览器入口与范围

`frontend/smoke/pdf-xlsx-currency-precision-smoke.mjs` 设置独立 `currency-precision` variant，默认证据目录 `/tmp/pdf-xlsx-currency-precision-browser-20261111`。专属 server/source/verifier 复用既有真实 native grant、cookie/CSRF、转换及签发下载流程；既有分支保持。生产及 engine 测试已冻结，等待 root 统一 bundle/package/browser，再仅对该实际下载执行一次 Calc。没有覆盖旧批证据。

两页来源默认打印六页的布局缺口尚未解决；本轮通过仅限已识别数值格式及宽度。未知输出字体测量不可用时仍退回 source ink，不能宣称所有字体/货币/区域格式、源页图文和打印分页保真。总体继续 `overallFidelityPassed=false`、manualReview=true、validation false，实际产物身份可读时照常非阻断签发下载。

## 本批统一最终验收

上述统一验收前的等待状态已完成：`/tmp/pdf-measure-radio-currency-xlsx-browser`真实browser exit0，37个实际JS与冻结资源匹配、四类errors为空、来源未变。实际下载5895 bytes，SHA `1236f4ff311b19611ad1f40a342cdfe4a3be2c2c4e25d4826df167fc485a6f63`。仅对此下载一次Calc（profile/output均/dev/shm）exit0；实际PDF88584 bytes/SHA `3d2f8b85f325eadd0fc9dfdbe6c774ef476449ce92b696ef025f9646c2d32dea`。独立host verifier通过，五组货币/百分数显示完整且无###；普通小数、富文本和完整嵌入字体也复核。`rendered-currency.png`已由root目视。仍六页，不将数值专项通过当作总体转换保真通过。统一证据见 `NATIVE_PDF_MEASURE_RADIO_CURRENCY_ACCEPTANCE.md` 和 `/tmp/pdf-measure-radio-currency-final-evidence-20261111.json`。
