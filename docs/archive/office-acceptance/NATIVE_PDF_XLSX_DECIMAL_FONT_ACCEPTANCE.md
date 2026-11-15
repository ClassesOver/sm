# PDF→XLSX 小数显示与 PDFium 字体别名专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。承接上一批真实下载富文本验收暴露的两个具体缺口：Helvetica-BoldOblique 被 PDFium 报告为 `Chrom Sans PS`，输出字体缺少此 exact alias 而由 Calc 回退 NotoSans-BoldItalic；数字 `12345.67` 虽保留真实数值类型及存储值，但 General 加默认窄列打印为 `12346`。本轮未执行 OCR，也未更改公共 workbook/slides/doc engine 或下载签发流程。

## 映射依据与最小生产改动

先复读上一批实际来源 PDF 的字体字典：第二页 `/F5` 为未嵌入 `/BaseFont /Helvetica-BoldOblique`。对相同 bundle 的 PDFium 直接调用 `FPDFFont_GetBaseFontName`、`GetFamilyName`、`GetIsEmbedded`，得到 `Helvetica-BoldOblique`、`Chrom Sans PS`、false；`GetFontData` 输出的 16418 字节 CFF SHA-256 为 `555ce45924338e2e4b32821910221ce85da691fd59a9723c4c971a7c5627fc8b`。fontTools 独立读取 CFF 得到 PostScript name `ChromSansPS-BoldItalic`、FamilyName `Chrom Sans PS`、FullName `Chrom Sans PS Bold Italic`、Weight `Bold`、ItalicAngle `-12`。这是实际 substitute 与源 BaseFont 的配对证据，不是凭相似名称扩张所有 PS family。

可复现脚本 `frontend/smoke/pdf-xlsx-decimal-font-probe.mjs` 读取指定来源和当前 PDFium wasm，落盘 `font-evidence.json` 与原始 `.font`，记录 source/wasm/font SHA 和 native API 返回值。当前新稳定来源重做探针证据为 `/tmp/pdf-xlsx-decimal-font/reproducible-probe/`，其中 wasm SHA-256 为 `5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa`；目标 CFF 身份及元数据与旧实际来源一致。运行方法：

```bash
node smart_reporting/report_editor/frontend/smoke/pdf-xlsx-decimal-font-probe.mjs SOURCE.pdf OUTPUT_DIRECTORY
```

`rebuild/fontmap.ts` 仅为 normalized exact key `chromsansps` 复用已有 HELVETICA 候选，保留 installed-first、无可用候选保留源名及 unknown family 不变的原规则；没有新增其他 PS 家族映射。逐 run 的粗体/斜体/装饰开关继续由上一批原生 rich text 路径表达。

`rebuild-xlsx/numbers.ts` 仅对已有可解析的裸/逗号分组、非指数小数，按原小数位数生成 `0.00…` 或 `#,##0.00…`，包括非零尾数及原有尾零。整数、科学计数、百分比、货币及代码/日期分类策略保持。真实数字继续存为 `<v>`，不改成字符串。

只设置固定精度仍不足：对上一批实际 XLSX 的临时副本仅将 A3 numFmt 改为 `0.00`，Calc 显示 `###`，证据 `/tmp/pdf-xlsx-decimal-font/format-only-probe.log`。因此 `rebuild-xlsx/rebuild.ts` 只对非表格固定小数行提出该列最小宽度，取 max（source block 实际 ink 宽、复用已有 font-metrics `advanceWidths` 测得的 dominant 输出字体 advance），加既有 Excel 换算公式中的 5 px cell padding。保持已有更宽 table/其他 claim，不对普通正文、整数、指数执行全局 autofit；无法测量输出字体时退回来源宽度。没有写经验补偿量。

## 专项与原生独立验收

新增 `bridge/xlsx-decimal-font.test.ts` 首轮 4 项真实 RED：普通小数仍为 General；exact 字体别名未映射；单个小数行无宽度 claim；真实新稳定 PDF 的 rich run 仍含 Chrom Sans PS。最小修复后这 4 项及受影响的既有 7 项 font alias 专项共 11/11 通过，日志 `/tmp/pdf-xlsx-decimal-font/{red,green}.log`。之后只运行新增宽度专项 1 项并通过（`width-claims.log`），覆盖源 ink 刻意窄于实际 advance、保留 200 pt table claim，以及整数/指数不扩宽。未重复完整测试。

新稳定 `pdf-xlsx-decimal-font-source.py` 复用上一批 mixed rich 源工厂并确定性追加 `12345.6789`、`-31.10`、`12,345.678`、`1.25e3`，保留既有原页、六段混合文字和原 `12345.67` 行；两次生成字节相同。来源 PDF SHA-256 为 `e947cf562a61d211494383d579deece505dc78952c39e18a23f9dbce0c517bb0`。当前原生转换 XLSX SHA-256 为 `70a3e0825db5eb9ecf14fc335ff364af2edbca79d572f2d09cb6dc24a8c604a1`。

独立 `pdf-xlsx-decimal-font-verify.py` 复用 openpyxl rich reader，要求 dominant 粗斜体 run 的 family 为 Liberation Sans，逐项核对 A3–A6 的真实数值类型/值/小数格式、指数 A7 的原 General 策略、原表数字/百分比、六段样式及源图片。原生 `native/independent.json` 已通过，固定小数列宽为 14.09 chars。可选传入实际 host PDF 后还要求全部 authored decimal 文本可提取、无 `###`、dominant 实际字体为 `LiberationSans-BoldItalic`，并复验真实粗斜体/矢量装饰及 minority 普通样式；统一冻结后的实际 host 结果已通过，见末节。

## 浏览器入口与范围

`frontend/smoke/pdf-xlsx-decimal-font-smoke.mjs` 选择独立 `decimal-font` variant，默认证据目录 `/tmp/pdf-xlsx-decimal-font-browser-20261111`。专属 server 复用既有真实 native grant、cookie/CSRF、转换及签发路由，只替换稳定 source factory；既有 decoration、rich-text、PPTX 分支保持。Root 已对冻结生产统一 bundle/package 后完成真实 browser；本支对该实际下载执行了单次 host Calc 与上述独立验收，身份和证据见末节。未覆盖旧批证据。

本专项仅针对已识别字体及裸/分组小数显示，不能据此宣称完整源页图文、字体字形、打印分页或所有数值格式保真。总体继续 `overallFidelityPassed=false`、manualReview=true、validation false；真实生成且文件身份可读取的 XLSX 仍按现有非阻断机制签发下载。


## 统一冻结后的真实浏览器下载与单次 host 验收

实际浏览器证据目录 `/tmp/pdf-link-radio-decimal-xlsx-browser/`，summary `ok=true`、来源保持、asset/page/console/HTTP errors 均为空；冻结 manifest SHA-256 为 `61aa2ab4abf61dd82b8d6c7e769f558a025eb2ab8ec6ebe47be825a89a46a376`。实际签发下载 XLSX SHA-256 为 `a46ab075cbd8563aaa3c52279d1b32e3aa9dead9d1a39f88c4efbcd2c1828da8`，来源身份仍为本节上述稳定工厂 SHA。

对实际下载仅执行一次 Calc，exit 0。临时 profile/output 分别在 `/dev/shm/pdf-link-radio-decimal-xlsx-profile`、`/dev/shm/pdf-link-radio-decimal-xlsx-render`；`host-calc.log` 保留命令输出。实际 `rendered.pdf` SHA-256 为 `346c6dc1b5ca6baf0e78755c6e5e2721277e4d4b7d6db327eccb050b814c6f6e`。打印仍为 6 页；第 6 页实际可提取并目视显示 `12345.67`、`12345.6789`、`-31.10`、`12,345.678`，没有 `###`，指数沿用旧策略显示数值 `1250`。`rendered-decimal-font.png` 已目视，SHA-256 为 `9844cf8cc131396a0de14013dccf2bf7a37e9697f3e10b480df67ab382e1e5cc`。

实际 host 字体证据比 span 字符串更严格：第 6 页资源 F10 的 PDF BaseFont 为 `KAAAAA+LiberationSans-BoldItalic`，内嵌 TTF name ID 6 为 `LiberationSans-BoldItalic`，name IDs 1/2 为 Liberation Sans / Bold Italic；实际内容以 `/F10 14.003 Tf` 绘制 Dominant，span flags 包含 bold+italic，装饰仍为真实矢量横线。PyMuPDF span 将 32 字符 subset-prefixed BaseFont 截为 31 字符后再去前缀，返回 `LiberationSans-BoldItali`。初版 verifier 的完整 span 名精确比较因此失败；复读 PDF 字典和嵌入字体后，仅调整 smoke verifier，要求 exact 完整 BaseFont 与 embedded PS name，并只允许完整 span 名或这一实际 31 字符截断表示，未放宽为任意 prefix。

对同一已渲染 PDF 再读的 `host-independent.json` exit 0，确认小数真实显示、Liberation Sans Bold Italic 实际嵌入/绘制、六段 rich 样式、minority 无误装饰、原表与图片保持。没有再次 Calc、browser 或原生测试；生产与 engine 测试冻结保持。总体版式保真继续 false，下载签发继续非阻断。

统一构建、373个JS分块预算、三域浏览器及签发故障证据见 `NATIVE_PDF_LINK_RADIO_DECIMAL_ACCEPTANCE.md`。本次实际下载的host画面也已由root目视；完整保真仍为false。
