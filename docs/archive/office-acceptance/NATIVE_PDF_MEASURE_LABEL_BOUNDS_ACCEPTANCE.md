# PDF 测量标签包围框验收

本批修复共享 measure writer 的 Rect / AP BBox 估算裁切，不改变线条、标签从线条中点起写的位置、9pt Helvetica、原 Tm / literal Tj /颜色/字体资源或 caret 图形。单独绘图和样式改字混合绘图共用该 writer，混合输出审核同步使用新包围契约。

## 实现边界

`pdf_engine/src/main/measure-label-bounds.ts` 使用 pdf-lib 公开 StandardFontEmbedder、其正式 Standard14 Helvetica FontBBox（[-166,-225,1000,931]）、WinAnsi 编码及 glyph WX。每个字形原点处合并**全字体保守包围框**，并非逐字形精确 ink box。原 Tj 没有 TJ 字距调整，因此逐字符累加 WX，不调用会加入 pair kerning 的整串 widthOfTextAtSize。包围框使用实际写入、舍入至两位小数的六值 Tm；与原端点和实际舍入线段端点合并，保留原有 width+2 pad。

现有桥接入口仍只允许可打印 ASCII。固定 writer 使用 low-byte literal Tj；真实探针：é 输出233与WinAnsi233一致，€输出172而WinAnsi编码128，中文截成75。helper明确拒绝不能与 literal 字节一致的输入，不以“字体能编码”为依据默许错误字符，也不声称新增 Unicode 支持。

## 本次定向验证

- 真实 RED：`/tmp/pdf-measure-label-bounds-red.log`，水平3.00 m正式包围角 y214.379 超出旧 Rect ymax210。
- 最终原生测试：`bridge/measure-label-bounds.test.ts`，`/tmp/pdf-measure-label-bounds-final-native.log`，2/2通过。真实单独/样式混合writer涵盖水平、2pt短线24W、AV/To、括号/反斜线、垂直、反向、斜向、64W与舍入Tm。
- 原有混合正向回归仅定向执行：`/tmp/pdf-measure-label-existing-positive-green.log`，1/1通过；保留精确原AP全文断言，仅更新变动Rect预期。
- helper / mixed reviewer 窄strict tsc：`/tmp/pdf-measure-label-bounds-types.log`，exit0。
- `frontend/smoke/pdf-measure-label-bounds-verify.py`：独立pypdf解析、ReportLab正式Helvetica逐char度量，对照实际AP矩阵和FontBBox契约；再同时扩大诊断副本Rect/BBox保持1:1，与Poppler144dpi实际渲染比对。`/tmp/pdf-measure-label-bounds-final/independent.json`：standalone/mixed均1800×1400、差异像素0。
- 旧裁切证据保留：`/tmp/pdf-next-measure-caret-visual/diagnostic.json`，原水平标签少46像素、24W短线少1166像素。
- 真实浏览器复用 `pdf-text-measure-caret-mixed-smoke.mjs`，增加 `PDF_MEASURE_LABEL_BOUNDS_SMOKE=1` 场景：首测量80,200→240,200、末测量80,300→82,300。浏览器、最终冻结资产与HTTP证据由root统一执行后记录，不能将原生验证冒称浏览器验收。

## 统一实际链路补验（2026-11-11）

最终冻结与总证据见 NATIVE_PDF_LABEL_REQUIRED_SLOTS_ACCEPTANCE.md。真实 browser 最终 `/tmp/pdf-label-required-slots-text-browser-retry/summary.json` 通过，37 个实际 JS 响应匹配统一资产，来源不变且四类 errors 为空。下载 mixed.pdf SHA `03a68461c5527839bb0b91c42d1599b4ad0886b88e937af1a0d6b688026d098a`，14434 bytes；固定 3.00 m / 0.04 m 水平线 geometry 独立核验通过，600×800 真实渲染与扩大 BBox 诊断副本差 0 像素，root 已目视。

首次 browser 最后 verifier 仍预期旧斜线的 1.50 m，保留失败目录；只修 verifier 后同产物复读 GREEN，默认旧契约仍保留。为获取失败进程未持久化的实际资产集合/summary，只重试这条失败专项，其他通过项未重跑。HTTP 新 styledMeasureBounds 验证短线 24W 的实际 Rect/AP BBox 与后置故障保下载通过；不把脚本旧预期当生产 RED。

## 仍保留的差异

标签仍从线条中点起写，与UI草稿的居中标签可能不同；本批不修改caret CSS/AP视觉语义。保守Rect/BBox不会解除页面CropBox裁切，接近页面边界的长标签仍需人工核对。本批不含OCR。
