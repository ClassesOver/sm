# PDF 已有文本字段标准字体选择验收（2026-11-11）

## 本批范围

固定上游为 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。固定源 `FormDesignLayer.tsx` 不是现有字体选择面板的逐字移植依据；本批按用户明确列出的“已有字段字体编辑”缺口，沿用既有安全文本属性适配器和 pdf-lib 原生字体/AP API 实现。

`editFormTextProperties` 新增可选 `fontName`。白名单复用 `inspectDesignTextProperties` 已使用的 12 个标准 Latin 字型：Helvetica、Times、Courier 各常规/粗体/斜体/粗斜体，名称与 pdf-lib `StandardFonts` 一致。省略 `fontName` 继续保持原字体；只有显式变更才选择另一标准字体。UI 展示原字体、拒绝无属性变化的空草稿，Undo/Redo 与既有确认预览流程继续复用。

仍只开放 ASCII 当前值、单 Widget、来源 DA/AP 可证一致的未保护未签名普通文本字段。CJK/自定义字体、Symbol、ZapfDingbats、密码、富文本、组合格、日期/动作字段和复杂多 Widget 不因本批扩大。原值、来源身份、字段/Widget 引用与无关 AP 保留；新目标 AP 的 BaseFont 和回读 metadata 必须等于所选字体。复核异常仍通过原 receipt 返回告警和实际 bytes/SHA。

## 最小实现与定向测试

生产改动：`reporting/pdf_engine/bridge/form-design.ts` 保持原检查接口并 reexport 共用纯读器与白名单；`bridge/form-text-properties.ts` 添加一个严格可选属性、目标字体选择及写后预期核验；`report_editor/frontend/src/pdf-form-text-properties.ts` 添加同范围校验与字体选择控件。填值保存器的共用纯读器修复见下文。没有新增 operation kind，没有修改 public server 或签发函数。

新增 `bridge/form-text-fonts.test.ts`，真实 RED 为 12 个合法字体用例被旧 validator 拒绝（12 failed / 1 passed）；最小实现后新 13 项与受影响旧 5 项共 18/18 PASS。每个字型都以当前值 `Alice` 的真实 PDF 生成 AP，并逐个比对全部原间接对象（仅排除允许修改的目标字段和 Widget）、字段/Widget 引用、正文与目标 AP BaseFont。非法 Symbol/ZapfDingbats/custom/空/null 名称仍被拒绝；旧来源安全边界测试同时通过。

新增 `src/pdf-form-text-fonts.test.ts`，真实 RED 为新属性被拒绝及控件不存在（2 failed）；最小实现后新 2 项与受影响旧 4 项共 6/6 PASS。验证全部 12 字型 staging/restore、未知字体拒绝、默认原字体、未改不生成 operation，以及只改字体时只序列化该属性。日志位于 `/tmp/pdf-next-form-fonts/{engine-red,engine-green,frontend-red,frontend-green}.log`。首次测试 fixture 漏传 required 的运行不是行为 RED，已修正后取得上述真实 RED。未重复完整测试。

## 浏览器验收与已知边界

专属真实链 smoke：`frontend/smoke/pdf-form-text-fonts-smoke.mjs`，使用 `PDF_FORM_TEXT_FONTS_SMOKE_DIRECTORY`、`PDF_FORM_TEXT_FONTS_SMOKE_PORT`（默认 4342）、统一 `PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR` 与 Chromium 路径。复用现有表单创建 server 和 grant/cookie/CSRF/原生预览/保存/签发/下载/重开，浏览器依次核验 Helvetica → Times-BoldItalic → Courier-BoldOblique，再实际填写 `Alice Updated`。

独立 `frontend/smoke/pdf-form-text-fonts-verify.py` 不依赖引擎模型，按实际下载 PDF 检查目标 AP/DA 字体、非空现值、字段树与引用、无关 code 字段/字体/AP、正文/页面几何保留。Node syntax、Python compile 与本批 `git diff --check` 已通过。

root 统一冻结构建的真实 browser 已通过：`/tmp/pdf-next-form-fonts-browser-root01/{summary,independent}.json`。Helvetica/Times-BoldItalic/Courier-BoldOblique 三个阶段与后续填写真实回读均匹配；修订属性 PDF SHA-256 `c7242f618aa5406416d7cdc2ac7ed13427bbabbab14677f52069b737d11107e7`，Courier 属性 PDF `aa65633010a3c49528c495d60d49501e53060897c282ec4002c5c5e5abfbaaf7`，最终填写 PDF `b5166aaf163d2cc4f059e62860e1b50b8e61287f9346f5cc1c7ab64f3b5424c9`。最终 AP 保留 Courier-BoldOblique 18、黑色和 Alice Updated；字段引用/无关 AP/正文保持。37 个 fetched JS 的 SHA 与冻结文件一致，无 page/console/HTTP/asset errors，最终重开画面已目视核验。构建身份见 `NATIVE_PDF_MIXED_FONTS_POSITION_ACCEPTANCE.md`。

## 填值字体重置的回归修复

额外原生同序列探针确认：原有 `save-pdf.ts::refreshFieldAppearances` 统一使用默认 Helvetica，导致选择 Courier/Times 后再填写文本时字型被重置，字号仍保留。证据 `/tmp/pdf-next-form-fonts/fill-{before,after}.pdf`、`fill-probe.log`、`fill-ap-probe.json` 保留，不将这一失败掩盖为通过。

最小修复把既有 `DesignTextProperties`、12字体白名单与纯读检查移至 `src/main/form-text-properties.ts`，由 bridge import/reexport 保持旧接口；保存流程复用该无 bridge/save 循环依赖的纯读器。仅 dirty 且原 DA/AP 可证明标准ASCII独立文本字段使用 `embedStandardFont` 保留原字体，其余字段保持原默认字体及 NeedAppearances fallback。检查中的原 `lookupMaybe(PDFRawStream)` 改为原始 lookup 加 instanceof 窄化以满足 pdf-lib 类型定义，不放宽语义。

新 `bridge/form-text-font-fill.test.ts` 真实全桥 `setFormValue`，Courier-BoldOblique18 与 Times-BoldItalic16 两项先因实际AP变成Helvetica而 RED；修复后通过，并以独立 pypdf 核对实际 AP BaseFont、DA 字号、非空现值。断言原字段/Widget引用、字号/对齐、无关code字段/AP和原正文不变。原始 `SOURCE-SHA256.json` 的 save-pdf `sha256` 未改，仅添加 localSha256 与适配说明。

另已实际确认：120pt宽控件使用 Courier-BoldOblique18 时，`Alice Updated` 文宽140.4pt、可用宽116pt，AP clip x=[2,118]、文字起点-22.4，左侧24.4pt被裁切；证据 `fill-reselected.pdf`、`fill-clip-ap.json`、`fill-clip-probe.log`。本批不新增自动适配或静默缩字号。字体专项smoke仅将name控件加宽240pt，code控件保持原120pt，以独立验证填值字体保留，明确不以其证明超宽自动适配完成。
