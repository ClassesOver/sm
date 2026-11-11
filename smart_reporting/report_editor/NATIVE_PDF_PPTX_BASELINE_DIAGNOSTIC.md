# PDF→PPTX 首行基线诊断（2026-11-11，未解决）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用上一批统一浏览器实际下载 `/tmp/pdf-three-increment-pptx-browser-root02/converted.pptx`，不重复完整测试，不写生产补偿。

## 已定位的语义差异

源 PDF 左列首字符真实 `originY=710`（页面高 800pt，即从页顶 90pt），tight glyph ink 的最高点约 717.6pt。现有文字框 Y 为 `1046480 EMU=82.4pt`，来自 ink top；段落 `lineExact=16pt`，字号 10pt，四边内边距为 0，noAutofit。Host LibreOffice 首行 baseline 为 96.350708pt，即框顶之下 13.950708pt。源 PDF 的字形墨迹顶端和 Office 的完整行盒顶端不是同一语义，保留基线间距并不能自动定位首行。

仅针对临时副本逐项改变 OOXML，原型与证据保留在 `/tmp/pdf-baseline-probe/`，不作为产品代码：

| 临时变量 | 首行 baseline（pt） | 后续 baseline pitch（pt） |
|---|---:|---:|
| 原始 lineExact 16 | 96.350708 | 约 15.987 |
| lineExact 10，字号仍 10 | 90.369690 | 约 10.006 |
| 删除 lineExact，字号仍 10 | 92.381714 | 约 12.019 |
| defRPr 显式 10pt/DejaVu Sans | 96.350708 | 约 15.987 |
| 换行 rPr 显式 10pt | 96.350708 | 约 15.987 |
| endParaRPr 显式 10pt | 96.350708 | 约 15.987 |

`variant-results.json` 说明 lineExact 影响首行完整行盒位置，补段落默认字号、换行字号和段落结束字号不能消除此偏差。修改 lineExact 虽能碰巧靠近原首行，却会破坏来源 16pt 行距，因此不可作为修复。

## 现有字体度量不能直接给出可靠逆映射

通过项目现有 `font-metrics.familyVerticalMetrics` 读取目标字体，原始数据为 `target-font-metrics.json`。四个目标 family 的 unitsPerEm 都是 2048；DejaVu Sans 的 hhea/win ascent/descent 为 1901/483，Liberation Sans 为 1854/434，Liberation Serif 为 1825/443，Liberation Mono 为 1705/615；typo 分组也不同。

8 个临时多字体/字号 probe 明确写入目标 family，实际渲染 PDF 也确认使用该 family：DejaVu Sans、Liberation Sans、Liberation Serif、Liberation Mono 各测 10pt 和 18pt，lineExact 保持字号的 1.6 倍。四种字体在 10pt 时首行从框顶偏移均为 13.950708pt，在 18pt 时均为 25.175684pt；对应 lineExact 分别为 16/28.8pt。它们并不等于各字体 hhea、win 或 typo ascent/descent 的直接映射；结果 `multi-font-results.json` 同时记录字体身份、字号、行距和实际 baseline，未把“字体相同”误当成“所有度量语义相同”。

这定位到 Office importer 的首行行盒策略，但尚未获得能跨字号、字体和 Office 消费端证明的正式可逆定位 API。未用拟合常数或经验 0.x em 补偿，也未缩字号、将可编辑文字栅格化或重写排版器。PPTX 首行 +6.350708pt 仍未解决，整体保真继续不通过；已生成产物和非阻断实际下载契约保持。转换侧本轮改为修复另一个真实可复现的 XLSX 文字装饰丢失，见 `NATIVE_PDF_XLSX_TEXT_DECORATION_ACCEPTANCE.md`。
