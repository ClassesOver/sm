# PDF→XLSX 原生混合富文本专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮针对普通受限 PDF 转换补齐单元格内混合字体、粗体、斜体、下划线和删除线；未执行 OCR。文字继续保留为可编辑 SpreadsheetML rich text。

## 真实缺陷与最小路径

在仓库复杂 PDF 原页后追加 `Plain Bold Italic Under Strike Serif` 六段，以及 dominant 粗体、斜体、下划线、删除线均开启、minority 普通样式关闭的混合行。提取 IR 已保留逐段样式，但原 XLSX 只有单个 `<is><t>` 和单元格 dominant font，丢失段内差异。

本次仅在 PDF converter 的 `rebuild-xlsx/rebuild.ts`、`workbook.ts`、`bridge/xlsx-rich-text.ts`、`bridge/convert-office.ts` 增补元数据及补写步骤。复用既有 `textBlockParagraph(block).runs` 与共享 workbook_engine 的正式 `applyCellEdits(bytes, CellEdit[])`、`CellEdit.rich` 序列化接口；未修改共享 workbook_engine。既有列表、TOC、source hard break 和 table 多 block 换行沿用原段落规则。

已有 rich serializer 对 false 开关省略写入，Office 会继承单元格字体。因此仅在实际补写混合 rich text 时，通过既有 copy-on-write 样式 API 中和 cell font 的 bold、italic、underline、strikethrough 四个开关，并让各 run 表达自己的 family、size、color 和样式。fill、border、numFmt、alignment、merge 等现有格式保留；均匀样式仍走既有整单元格样式路径。

数值解析优先，数字单元格不附加 rich text、不改写 `<v>`。逐 run 拼接必须与最终 cell text 按 UTF-16 严格相同，且既有 sanitizer 不会改变正文，才允许补写。超过 32767 个 UTF-16 code units、253 个换行或含控制字符等需原有正规化的文本，保留原 canonical plain bytes，返回含工作表及单元格坐标的 plain fallback warning。恰好上限且合法的文本仍支持 rich text。补写接口抛异常时保留调用前完全相同的 source bytes，并报告原异常；已生成且身份可读产物继续可签发，验收状态不冒认通过。

## 专项与独立证据

`bridge/xlsx-rich-text.test.ts` 首先出现 2 项真实 RED：实际复杂 PDF 缺失 native `<r>`；重建 metadata 未输出 rich candidate。修复后 5 项专项通过，涵盖实际混合六段、dominant 与 minority 开关继承、table/list/TOC 元数据、数值 XML 字节保持、原有格式保持、超限/控制字符回退及 writer 异常非阻断。其后只运行新增边界 1 项并通过：恰好 32767 UTF-16（末尾完整代理对）及 253 个换行。日志分别为 `/tmp/pdf-xlsx-rich-text/{red,green,exact-boundaries}.log`；未重复完整测试。

专属 `frontend/smoke/pdf-xlsx-rich-text-verify.py` 使用 openpyxl `rich_text=True` 复读实际 XLSX，要求六段逐一保留字体及四开关、base cell 四开关关闭、minority 普通样式还原、真实数字类型/数值、原表百分比及图片包关系。对修复前真实 XLSX 明确失败于“must contain native editable rich text”（`independent-red.log`）。可选第三参数读取 host Calc 的实际 PDF，按真实字体 flags 及对应文字相邻的矢量横线检查装饰，不能仅凭 XLSX XML 宣称渲染正确。

原生专项证据 `/tmp/pdf-xlsx-rich-text/green/host-independent.json` 通过：

- 来源 PDF SHA-256：`40539befaa47da5688cea77a90a2ece4e0d1f670846682993de1ebcc4c96afee`。
- XLSX SHA-256：`1cac5d439ac0db517b33b2334d5ec96e39834f227a504020998c35a28a04665a`。
- 实际 host Calc 渲染 PDF SHA-256：`201abd441025bf12d99abcb595a6316fb315589253fa34f2009134cd786fdb56`，Calc exit 0。
- 已目视 `rendered-rich.png`，SHA-256：`52d1c2b4cef1f07c9b6bc061e4783f1ef1ccdd760a26b8c9150fb53b5d3e78c6`。

六段实际字体依次为 LiberationSans、LiberationSans-Bold、LiberationSans-Italic、LiberationSans、LiberationSans、LiberationSerif，下划线/删除线真实绘制。dominant 混合行末尾 minority 普通文字实际恢复 LiberationSans regular 且无装饰。默认 host 打印为 6 页，rich text 在第 6 页。

## 可复现浏览器入口与当前范围

`pdf-xlsx-rich-text-source.py` 使用 Reportlab `invariant=1` 加 pypdf，从仓库 `complex-layout.pdf` 稳定追加混合文字页，两次生成 bytes 相同，PDF SHA-256：`ce7e4822f554336b43419d5361c96a9dd7151c683b39e45652a02aace4145b2b`。该工厂经当前原生转换和独立 verifier 通过，XLSX SHA-256：`4ae8b6996ad9136987305c46a651f65ba438ae2302e6aa14f80f4735bdd4289d`，证据 `reproducible-independent.json`。

`pdf-xlsx-rich-text-smoke.mjs` 复用既有 XLSX smoke 的真实 native grant、cookie/CSRF、转换、签发下载及冻结资源 SHA 检查，通过 `PDF_XLSX_GEOMETRY_SMOKE_VARIANT=rich-text` 选择新 source server 和 verifier。默认目录 `/tmp/pdf-xlsx-rich-text-browser-20261111`；PPTX 默认和既有 decoration 分支保持。统一冻结后的真实浏览器下载及该实际文件的单次 host Calc 验收已完成，身份和证据见下节。

整体保真继续不通过，`overallFidelityPassed=false`、`manualReview=true`、validation false。已确认的剩余限制包括 PDFium 将 Helvetica-BoldOblique 输出为 `Chrom Sans PS`，现有字体 alias 未覆盖，host 实际 fallback 为 `NotoSans-BoldItalic`；本轮未扩围修改 alias。数字单元格真实值 `12345.67` 及数值类型保持，但既有 General 格式和默认窄列宽导致 host 打印显示 `12346`，不能据此宣称数值视觉保真。默认打印重排、图文相对位置和源页版式均不属于本专项已通过范围。


## 统一冻结后的实际浏览器下载与 host 验收

Root 真实浏览器转换与签发下载已 exit 0，证据 `/tmp/pdf-png-choice-rich-xlsx-browser/summary.json`；来源保持，实际下载经独立 openpyxl verifier 通过。下载 XLSX SHA-256：`52c226c294572d2be86ba06d661d10e804e140957c859bab3c4aff3fd9e82606`，来源 PDF 与上述稳定工厂身份一致。

对该实际下载只执行一次 host Calc 渲染，exit 0；临时 profile 为 `/dev/shm/pdf-png-choice-rich-xlsx-profile`，临时输出为 `/dev/shm/pdf-png-choice-rich-xlsx-render`，命令日志为浏览器证据目录的 `host-calc.log`。实际渲染复制为该目录 `rendered.pdf`，SHA-256：`616efb53032d60767d5f73eb8d5ec91638130941efa8136daeebd2b07bd4a21c`。专属 verifier 对来源、实际下载和实际 host 渲染三者复读 exit 0，`host-independent.json` 确认 native 六段、dominant/minority 开关、数字及原表/图片保持，以及真实 host 字体、矢量装饰与 minority 无误装饰。实际打印仍为 6 页，混合文字在第 6 页；对应 `rendered-rich.png` SHA-256：`52d1c2b4cef1f07c9b6bc061e4783f1ef1ccdd760a26b8c9150fb53b5d3e78c6`。字体 fallback、数字显示与源页排版限制仍成立，整体保真继续不通过。本轮未重跑 browser 或原生专项。
