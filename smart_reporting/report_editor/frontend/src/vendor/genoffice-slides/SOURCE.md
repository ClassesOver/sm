# GenOffice Slides Ribbon Sources

2026-11-11 相对图片原始尺寸：`slides-geometry-pane.ts` 适配固定源
`FormatPane.tsx` 的 `naturalSize`、`relOriginal` 与 `scaleBasis`，复用当前渲染树
图片 dataUrl 的浏览器解码；以 naturalWidth/naturalHeight 为96dpi像素基准，
默认启用，关闭后使用选中会话基准。切换仅改变百分比显示，沿用现有geometry、
厘米和裁切保存链路。来源切换、待保存图片替换和销毁使旧异步结果失效；
解码失败或替换待保存时回退会话基准并说明原因，不提交未完成厘米输入。
这是宿主行为适配，未复制完整FormatPane、修改引擎或新增wire字段。
来源文件与中文文案SHA沿用已登记身份；验收记录：
`report_editor/NATIVE_PPTX_ORIGINAL_SIZE_ACCEPTANCE.md`。

2026-11-11 会话基准百分比缩放：`slides-geometry-pane.ts` 扩展固定源
`FormatPane.tsx` 的 `scaleBaseRef`、`commitScale`、`stepScale` 行为，选中时尺寸为100%，
同目标编辑和历史回填保留基准，切对象、结束选择或刷新后重建。百分比输入与厘米、
纵横比锁定和1%步进共享现有geometry提交；显示整数百分比不舍入写回真实尺寸，
可选%后缀保持相同的无变化语义。图片会话基准仍用选中时可见框；后续原始尺寸基准见下项。
验收记录：`report_editor/NATIVE_PPTX_SCALE_ACCEPTANCE.md`。

2026-11-11 填充与轮廓分组：`slides-shape-format-pane.tsx` 是固定源
`FormatPane.tsx` 的简单填充/线条分组宿主适配，复用已登记的共享颜色图库与 ColorWell。
侧栏和功能区共享明确来源值，分别限制复杂填充与复杂轮廓，保留真实颜色/线宽，
支持无填充、无线条、逐字段恢复来源、单笔历史及保存前 flush。
bridge 仅摘要明确简单 RGB 轮廓及简单 noFill，不用显示默认值覆盖复杂或继承来源。
不宣称完整 FormatPane 或复杂样式编辑已对齐。
验收记录：`report_editor/NATIVE_PPTX_SHAPE_FORMAT_PANE_ACCEPTANCE.md`。

2026-11-11 大小与位置分组：`slides-geometry-pane.ts` 是固定源
`FormatPane.tsx` 的厘米输入、0.1cm步进、`sizeCommit`纵横比锁定与独立水平/垂直
参考点行为适配。来源FormatPane和中文pane文案沿用根`SOURCE-SHA256.json`登记的
字节身份，不将宿主DOM实现标作逐字复制。宿主使用原始96dpi geometry，不含画布
viewScale；限定现有geometry协议及arrangeEditable来源，合并裁切框、单笔历史与
保存前flush，保留未编辑维度的来源精度。原生模式替换可见像素输入，legacy模式
保留原输入。会话百分比缩放的后续适配见上项；旋转及完整FormatPane仍未对齐；原始图片尺寸基准见上项。
验收记录：`report_editor/NATIVE_PPTX_GEOMETRY_PANE_ACCEPTANCE.md`。

2026-11-11 chart format section: `ui/color-picker.tsx`, `ui/color-picker.css`
and `color-input.ts` are byte-identical copies of the pinned shared picker and
Slides native color-input helper. Their upstream/local hashes, plus the reference
FormatPane/ColorWell and Simplified Chinese pane strings, are recorded in root
`SOURCE-SHA256.json`. `slides-chart-format-pane.tsx` is a host behavior adapter:
source data-point grouping, 74×26 ColorWell trigger and shared theme/shade/standard
palette; top-layer positioning, draft-safe 200ms coalescing and save-time flush.
Native custom-color inputs remain mounted across same-target color refreshes.
The host retains the earlier reset action and modal entry point. This ports only
the chart data-point section, not the complete general-purpose FormatPane.

2026-11-11 chart gallery: `components/chart-style-preview.tsx` extracts
`chartPresetActive` and `ChartStyleThumb` from the pinned `components/Ribbon.tsx`.
Both function bodies, the 64×40 SVG geometry and sample colors are unchanged;
only exports, standalone type imports and `StringKey` → `string` are adapted.
The host maps `barH` / `barPercentStacked` to the source render-tree's bar family,
and passes current source-plus-draft style values, without persisting a preset ID.
`slides-native-chart-gallery.css` scopes the source chart card/row rules and binds
them to existing office chrome tokens. The source 440px scrolling row, 68px color
cards and first-four-color swatches remain; a browser top-layer popover adapts
the dropdown to this host's scrolling Ribbon. Source Ribbon/styles and local
preview SHA-256 values are recorded in `components/SOURCE-SHA256.json`.
The ten preset values continue to use the shared, previously accepted
`reporting/slides_engine/bridge/pptx-chart-design.ts` data; no engine or wire
protocol is changed. Existing named selectors remain an additional entry point.

2026-11-11：原生版式中文显示复用本地 `slides-native-ribbon-locales.ts`，
按固定版本 `apps/slides/src/renderer/layout-names.ts` 的六个标准布局名及
`i18n/ribbon/zh.ts` 的文案显示：标题幻灯片、标题和内容、节标题、两栏内容、
仅标题、空白。布局类型与 `packages/pptx-engine/src/builtin-layouts.ts` 保持对应。
来源标准名必须同时匹配布局类型；已知 `builtin:<key>` 也只按该固定枚举识别。
自定义布局名保留原文，仅按已知类型附中文提示；未知类型和缺少类型的来源名
保持原文。对象名称（例如 `TextBox 1`）不属于内建布局枚举，保持来源名称。
显示规则覆盖新建/更改版式的初始与刷新选项、右侧版式以及待保存的新建页预览；
option value、布局路径、对象 ID 和 `editSlides` 操作身份均不改变。
新增独立 `slides-layout-locales-review.test.ts`：界面两项先 RED 后 GREEN，
六枚举/英文模式/自定义名称边界另单独通过；未重复整套或执行构建。
固定源 `layout-names.ts` SHA-256：
`acf85c54a8fb11b6b6b7e787af506642a6cf6210b810ed298e5ae42f53ab9d2c`。

Upstream repository: `https://github.com/genspark-ai/genoffice`
Pinned commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`

`slide-size.ts` is copied unchanged from
`apps/slides/src/renderer/slide-size.ts`; its matching and preset-orientation
helpers drive Design's 16:9, 4:3, A4 and A3 choices. Both source and local hashes
are recorded in `SOURCE-SHA256.json`. Preset selection preserves orientation;
the orientation control only swaps the current dimensions. Custom source
sizes within the native schema's 1–56 inch bounds can also swap orientation
without replacing their dimensions with a preset.

`components/icons.tsx` is adapted from
`apps/slides/src/renderer/components/icons.tsx` (upstream SHA-256
`191d76ff69a597f140b4841b232f51ee4409c408fd24b0ad9e0aaf2c8c984975`). Its
only external type import (`AnimEffectKind` from the desktop app's shared IPC
types) was replaced with the same string union locally. All icon definitions
and SVG paths are retained unchanged; the React UI imports this browser-safe,
self-contained module for native Ribbon SVG glyphs. SHA-256 of the adapted file
is recorded in `components/SOURCE-SHA256.json`.

The Home Clipboard group in `slides-native-ribbon.ts` follows the pinned
`Ribbon.tsx` source order and callbacks: `onPaste`, `onCut`, `onCopy`, and
`onFormatBrushClick`. It uses the source `IconPaste`, `IconCut`, `IconCopy`,
and `IconFormatPainter` glyphs. Since those callbacks require GenOffice's
desktop clipboard bridge or format-painter selection state, all four controls
carry their source callback identity and remain disabled in the browser editor.
The English and Simplified Chinese labels in
`components/ribbon-home-clipboard-locales.ts` are adapted from the pinned
`apps/slides/src/renderer/i18n/ribbon/en.ts` and `zh.ts` entries; hashes for the
source Ribbon and locale files are recorded in `components/SOURCE-SHA256.json`.

The upstream application license and notice are retained in
`smart_reporting/reporting/slides_engine/LICENSE` and `NOTICE`.

2026-11-06: `slide-size.ts` is copied byte-for-byte from the same fixed
commit's `apps/slides/src/renderer/slide-size.ts`; root `SOURCE-SHA256.json`
records its upstream and local SHA-256. The native Design controls reuse
`SLIDE_SIZE_PRESETS`, `presetSize` and orientation helpers for 16:9, 4:3,
A4 and A3. This historical preset-only checkpoint is superseded by the custom-size
follow-up below. The unchanged imported conversion helpers now drive custom
size entry; new-presentation defaults still have no creation consumer.

2026-11-05 PR #190 continuation: the Web adapter now reuses the unchanged
`lengthToEmu`/`emuToLength` helpers for a custom-size dialog (cm/mm/in).
Both native API and bridge validate integer EMU coordinates in the ECMA-376
1–56 inch range. Draft history and restore use the existing slideSize operation.
New-presentation defaults remain explicitly disabled because this host has no
blank-presentation creation path. This supersedes the earlier preset-only
writeback limitation; the pinned upstream files and hashes are unchanged.

The follow-up also aligns source identities with fixed `Ribbon.tsx`: custom
size calls `onCustomSlideSize`, whereas the disabled new-deck default action
directly invokes the upstream local helper `saveDefaultNewSlideSize`. Preset
state uses the source matching helper without an aspect-ratio fallback.

2026-11-09: `components/shape-gallery-data.ts` adapts the pinned `packages/ui/src/shape-gallery.tsx`
`SHAPE_GALLERY_GROUPS` (7 groups, 109 presets, unchanged order) with Simplified Chinese labels from
`packages/i18n/src/common-ribbon.ts` (`ribbonCommonZh`) and `apps/slides/src/renderer/i18n/ribbon/zh.ts`.
Only the data is taken; the React previews depend on the renderer's preset geometry. Insert ▸ Shapes
uses it with the pinned insert defaults (`default-shape.ts` factory fill `#C43E1C`; line presets get a
1pt black stroke per `insert-actions.ts`). Hashes are in `components/SOURCE-SHA256.json`.

2026-11-10: `components/chart-gallery-data.ts` adapts the pinned `apps/slides/src/renderer/insert-presets.ts`
`CHART_GALLERY` and `chartSampleData` (13 kinds, unchanged order and sample values) with Simplified Chinese
strings substituted for the i18n keys. Insert ▸ Chart uses it with the pinned frame
(`insert-defaults.ts` `graphicFrameInsertFrame`: 2/3 slide width, 3:2, centred) and `barH` → `bar` +
`barDir: 'bar'` as in the pinned main process. Hashes are in `components/SOURCE-SHA256.json`.

2026-11-10: `components/smartart-gallery-data.ts` adapts the same pinned `insert-presets.ts` `SMARTART_GALLERY`
(7 layouts, unchanged order and default items) with Simplified Chinese strings; inserted with the same
`graphicFrameInsertFrame` placement through the pinned engine's `addSmartArt` (1–8 nodes).

2026-11-10: `src/slides-animation-sequence.ts` (outside this directory; behaviour port, no upstream file copied)
follows the pinned `apps/slides/src/renderer/animation-actions.ts`
(SHA-256 `d8b6af35e80646ef698a43425db90e48079802823a4fe76cff6eb8303c2274fb`: whole-page overwrite, `animDefaultDur`,
none / add / motion path / by-paragraph / move / delete / timing), `components/AnimationPane.tsx`
(`8d55896be2ea47340cce8da9aec43531fa232aa4b2f47520a774098d4c69cefd`: step numbering and row content) and the five
`MOTION_PATHS` strings in `components/Ribbon.tsx` (`6a261cf18bbdbf2b39fa51add3d30383a10ded4a072303e0012cb7e5cde00aba`),
copied verbatim. The bridge keeps the same five path strings as its allow-list.

Table Design follow-up: `components/table-shading-colors.ts` is byte-identical to pinned renderer source (Git blob `3b568af4ba4bfdc717345e873a7322ceaa2b801e`). Ribbon onEditTableStyle shading and all/none borders are adapted for whole-table selection; pinned editTableStyle remains unchanged. No table-style gallery or cell-range styling parity is claimed.

2026-11-11 布局中文 built-browser 专项首轮保留失败证据：
manifest 9ee998908ab65f7c2ca8f8551b3a67954c9423fccd49d89bce549746bb987141，
/tmp/pptx-layout-locales-built-20261111/{initial-layouts.png,failure.png,failure.html} 与同名前缀 log。
标准中文选项、原路径、TextBox 1 源名均通过，但右侧选择 Revenue Review 后功能区
当前值仍为空白。这是真实 UI 同步缺口，不作为最终通过，也不以 Undo/Redo 刷新绕过。
新增双向同步窄回归先 RED 后 GREEN，日志 /tmp/slides-layout-current-sync-{red,green}-20261111.log；
右侧 change 仅补既有 ribbon.setValue，同步全部功能区版式控件，反向功能区操作也核对
右侧值与同一 NativeDraft 的原 layoutPath。独立浏览器脚本
frontend/smoke/pptx-layout-locales-smoke.mjs 保留原严格断言；最终通过须以 root 后续新构建记录为准。
本脚本使用明确标识的 Playwright 原生 API route fixture 和真实 PPTX inspect/patch/render，
不能当作生产鉴权、真实 AI provider 或完整保存下载链路验收。

2026-11-11 布局中文最终 built-browser 专项通过：
证据目录 /tmp/pptx-layout-locales-built-final3-03-20261111，日志为同名前缀 .log；
Chromium 140.0.7339.16，独立端口 4307。冻结 manifest SHA-256
f76a3d6903e283f50fbffaf9cc28850bd16024d7f09811e4c71242cfe3fbc5ec，运行后磁盘身份仍一致。
实际加载的 108 个 JavaScript 响应逐个与磁盘静态文件核对 SHA-256；入口
lazy-unified-main-9N9_cYwd.js 为 b6a7ff635d86b378e01e2c3a3c84cad32956071b7133a51c097e259ffdca4eeb，
lazy-slides-main-CAGa8yLB.js 为 b2ee228a694f92e4652f8e8bc1d93d8a8111ce4e9a61530750a82c9017ccf8e5。
已实际目视 initial-layouts.png、title-layout.png、custom-layout.png、new-blank-layout.png：
空白、标题幻灯片中文正常，Revenue Review 来源名保留并附“标题和内容”，TextBox 1 在对象及 AI
上下文保留。右侧改版式立即同步全部功能区当前值；功能区反向改版式同步右侧。NativeDraft
保留 slideLayouts.layoutPath=ppt/slideLayouts/slideLayout2.xml，以及
newSlides.withLayout=ppt/slideLayouts/slideLayout7.xml；源 PPTX 调用内 SHA-256 保持
7a2121818936412c957ae681a58378a8d0d1b65fc16097463fa09b63344e506b。
96 个功能区按钮均恰有一个含实际绘图节点的 SVG，pageErrors、consoleErrors、failedResponses 均为空。

保留同一最终构建的两次测试脚本校准失败目录：
/tmp/pptx-layout-locales-built-final3-20261111 将源 IconEquation 的 SVG text 绘图节点误判为缺图；
据固定源 TextGlyph 校准为接受真实 SVG text，仍检查实际绘图节点。
/tmp/pptx-layout-locales-built-final3-02-20261111 的顶层路由初始化误在 about:blank 辅助 iframe 执行，
触发 SecurityError；仅将 fixture 初始化限定到顶层 HTTP 页面，保留零 pageErrors 严格断言。
这两轮未改生产代码或构建资产，不覆盖首轮真实同步缺陷及其 RED/GREEN 记录。最终成功范围仍为
Playwright API route fixture 加真实 PPTX 引擎的布局专项，不代表生产鉴权、真实 AI 或完整保存下载链通过。

2026-11-11 final4 最小入口与 PPTX 资产连续性补验通过：
使用既有 route fixture 的 PPTX_LAYOUT_INITIAL_ONLY=1 模式，独立证据目录
/tmp/pptx-layout-entry-built-final4-20261111，日志为同名前缀 .log。实际加载最终 native.html →
lazy-unified-main-DCSB-Cqw.js → lazy-native-main-CsPU594W.js / lazy-slides-main-CAGa8yLB.js；
manifest SHA-256 为 9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba。
108 个实际 JavaScript 响应逐个核对磁盘字节；新 unified-main 的 16812 字节响应 SHA-256 为
8cfafc4293918025fde090b9be1035ef58c749b1605afd3c06dbc635e7979905。PPTX slides-main
实际响应仍为 159359 字节、SHA-256 b2ee228a694f92e4652f8e8bc1d93d8a8111ce4e9a61530750a82c9017ccf8e5，
与 final3 的真实响应身份完全一致，无需 import 文件名规范化；原始比较记录见 asset-continuity.json。
初始新建/更改版式及右侧布局选项的标准中文、自定义来源名与原路径均核对，TextBox 1 在对象与
AI 上下文保持来源名；initial-layouts.png 已实际目视。96 个按钮 SVG 检查通过，pageErrors、
consoleErrors、failedResponses 均为空。Chromium 140.0.7339.16，端口 4307。
本次只验 final4 入口及资产连续性，未重跑 final3 的新建、双向更改和 Undo 完整交互链，
不能将前述 final3 全部专项表述为 final4 重跑；鉴权仍为明确标识的 API route fixture，
不代表生产鉴权、真实 AI provider 或完整保存下载链路验收。
