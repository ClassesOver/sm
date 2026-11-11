# PDF→PPTX 测量文本框位置专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。上一批复杂页面的实际签发下载 `/tmp/pdf-continue-pptx/converted.pptx` 在 host LibreOffice 中左/右列 X 为 36.793999/321.760986pt，而源 PDF 文本基线 X 为 32/317pt。四边 `lIns/tIns/rIns/bIns` 已明确为 0，不应把偏差归因为缺少 margin，也不能用猜测的字号偏移消除。

## 因果诊断与最小修复

`/tmp/pdf-next-pptx-position/probe-results.json` 比较七个独立 XML 诊断变体。仅移除 `spAutoFit` 或替换为 `noAutofit` 就使 X 变为 32.966999/317.990997pt；强制 paragraph marL/marR/indent、spaceBefore/After、master 缩进和 shape noFill 没有改善。`spAutoFit` 是本地共享引擎 `addElement(kind:'textbox')` 的编辑器默认值；PDF box 的几何已经测量，不应继续 resize。

本批仅在 `pdf_engine/vendor/pdf2docx/src/rebuild-pptx/rebuild.ts` 为每个测量文本框调用现成 `setElementTextBodyProps(slide, element.id, {autofit:'none'})`，不修改共享 slides writer，不写新 XML 排版器、不补猜测坐标。原样保留 wrap=none、anchor=t、四边0、来源 lines/font/size/color、既有16pt baseline pitch、table/image 和 page scaling。`SOURCE-SHA256.json` 只更新本地哈希和 adaptation，原始 sourceSha256 保留。

## 真实专项

`bridge/pptx-text-position.test.ts` 两项 RED→GREEN：旧输出二项失败均因自动 resize 未取消；修复后二项通过。覆盖真实两页不同scale、左中右对齐测量文本框，以及复杂PDF原生转换中的两列8行、16pt行距、1表/1图与monospace caption。日志 `/tmp/pdf-next-pptx-position/{red,green}.log`。

`frontend/smoke/pdf-pptx-text-position-verify.py` 复用上一批独立 geometry verifier，并验证所有顶层文字框明确 noAutofit 和零边距、两列实际渲染 X 残差不超过1.1pt。对旧实际下载及其 host render 真实失败，对最终原生输出及 host render 通过。证据 `/tmp/pdf-next-pptx-position/{render-red.log,render-green.json}`。没有重复完整测试。

最终 native `fixed.pptx` SHA-256 `d80a26ed19ecc404ed5ffe7f1da21655f4cdf2c8d5ebe73c4f25c2140c5ea505`；host LibreOffice 渲染 PDF SHA-256 `13ae39bfe654de421f2ef3215ee22cd92a2b970fcf4ad4dfb09827cddfa72326`。实际渲染两列 X 残差0.967/0.991pt，16pt行距仍在0.03pt误差内，1表无意外折行、1图和Mono caption保留；`fixed-render.png` 已目视核验。

## 仍未通过的保真

横向约1pt的残差来自现有 IR 用 tight glyph box 而非 authored baseline X；首行 baseline 仍从90变为96.350708pt。后者混合 glyph ink top、字体 ascent/leading 和 Office importer 基线语义，当前没有足够可靠的可逆映射，未添加常数补偿。`overallFidelityPassed=false`，manual review 与实际下载非阻断契约保持。复杂文字/字体/任意排版整体保真继续未通过。

root 已完成统一冻结构建后的真实浏览器签发下载：`/tmp/pdf-next-pptx-position-browser-root01/{summary,independent}.json`，实际下载 PPTX SHA-256 `def96d700564eef6e51e9f6169143ce92e1afc21d096a50ebc2786b6e501dc4c`。无 page/console/HTTP/asset errors，37 个 fetched JS 的 SHA 与冻结文件一致，来源 PDF 保持。实际下载文件经 host LibreOffice 渲染，PDF SHA-256 `799d867f98ca0b35d5b50a4cfd640bd5154a49432466880c40eb815621d95b36`；独立 position verifier `/tmp/pdf-next-position-lo-verification.json` 通过，7 个文本框均 noAutofit，X 残差 0.967/0.991pt，行距/表格/图片/Mono caption 保持。最终 rendered.png 已目视核验。首行残差与整体保真未通过状态保持，仍提供实际下载。统一身份见 `NATIVE_PDF_MIXED_FONTS_POSITION_ACCEPTANCE.md`。
