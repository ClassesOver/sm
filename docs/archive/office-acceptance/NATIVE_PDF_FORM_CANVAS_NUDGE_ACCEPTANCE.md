# PDF 安全单控件画布选择与键盘微调

## 固定源与本批边界

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`：

- `FormDesignLayer.tsx:35–36`：`NUDGE_PTS=1`，Shift 乘十。
- `FormDesignLayer.tsx:327–335,431–449`：点击已有控件选择，显示选中状态。
- `App.tsx:7526–7545`：只在表单设计标签且非 editable 目标处理方向键。
- `App.tsx:4374–4399`：屏幕方向增量经每页 `viewToPdf` 映射，之后 `clampRectToPage` 限制在本页。

本批仅为已保存、安全、字段本身只有一个 Widget 的来源增加画布点击选择和箭头微调。复用原 `editFormWidget.rect`，不增加 native operation、capability、HTTP 或字段元数据；不做多控件字段、拖动、resize、框选、吸附、OCR、签名或 XFA。

微调 1pt，Shift 为 10pt，仅限默认 UserUnit。既有 `bridge/form-design-create.ts:26` 对整个来源拒绝非默认 UserUnit，相关能力不开；root canvas current 另检查 PDF.js `userUnit===1`，不扩展非默认单位支持。

## 实现与接线

生产独立模块 `frontend/src/pdf-form-canvas.ts`：

- `mountPdfFormCanvas` 以已有页面 viewport 绘制精确 Widget 命中矩形；root 保存包含 source SHA、pageId 与全部四重 Widget 身份的 selection，跨页面重绘恢复选择。
- `stagePdfFormWidgetNudge` 复用已有页面几何与属性校验，按实际旋转把屏幕方向转换为 PDF 坐标，clamp CropBox，不改尺寸、不改页面归属。
- 连续按键累计更新同一项 rect-only 操作，不向 operations 追加多项；回到原始矩形时清除此项。每次实际变更通过原 NativeDraft 历史机制支持 Undo/Redo。
- 只允许空草稿或本来源、本控件、严格 rect-only 的单项操作；拒绝其他字段、属性、未知键和其他操作草稿。完整身份和页面在每次按键时重新校验。
- 文档级 keydown 先尊重 `defaultPrevented`，排除 Ctrl/Meta/Alt 快捷键、editable、整个 Ribbon、四类字段面板和打开的 dialog/alertdialog；editor 外部实际 pointer/focus 清选择。
- root 全重绘移除原焦点后，body/documentElement 仅作为保留选择的临时按键目标；不重新点击也可继续微调。外部实际活动会取消该选择。
- `sync()` 表示生命周期：已连接且未 dispose 返回 true，包括 inactive 状态，以支持从 Home 切到 Form Design 后启用；脱离 DOM 或 dispose 返回 false。首次 mount 尚未 append 的 host 不误清选择。
- `dispose()` 只拆 DOM/监听，不清 root selection；`clear()` 显式清选择。root refresh 重建控制器时保留选择，离开表单设计/预览/销毁等边界显式清理。

root 接线位于 `pdf-main.ts` 的 formCanvases 生命周期、`overlays` mount、`formCanvasCurrent` 和 `syncDrawingCanvases` 联动；样式位于 `pdf.css` 的 `.pdf-form-canvas` / `.pdf-form-canvas-widget` / `.is-selected` / `.is-disabled`。root 负责共同来源、tab、mode、只读、保存、预览、打印、未完成文字及默认 UserUnit 状态门控。模块自己判断是否兼容本控件 rect 草稿，不使用会阻止自身 dirty 草稿的旧 objectDesignUnavailable。

native 保存仍走原有矩形属性编辑：目标 Widget 可正式重新生成 AP；本批没有改变 native writer，也不承诺目标 AP 引用保持或 PDF 对象数量零增长。对实际独立验收产物，除目标 Rect/AP 外逐个核对全部原始对象及流。

## RED / GREEN 与类型检查

不重复完整测试；新增与受影响项分批运行：

- `/tmp/pdf-next-form-canvas-red.log`：先仅提供接口空壳，10 个真实 DOM/行为专项失败（无命中框、nudge 未实现）；最初“模块不存在”的加载错误不当作行为 RED。
- `/tmp/pdf-next-form-canvas-green.log`：10 PASS，覆盖真实 NativeDraft 单项累计、1/10pt、四种旋转各两种缩放、非零 CropBox、边界 no-op、回源清空、四重身份及来源、共享字段拒绝、其他草稿拒绝、editable/面板/快捷键不抢键、跨 refresh 重建、外部活动、Escape、禁用/断开/销毁。
- `/tmp/pdf-form-canvas-inactive-red.log` → `inactive-green.log`：仅新增项 RED→GREEN，修复 inactive controller 的 sync 返回值，验证 Home→Form Design 可重新启用。
- `/tmp/pdf-form-canvas-ribbon-red.log` → `ribbon-green.log`：仅新增项 RED→GREEN，覆盖普通 Ribbon 命令按钮及打开弹窗时 body fallback 不触发微调。
- 合计 12 个专项分项通过，没有重复跑全套。
- `/tmp/pdf-form-canvas-tsc.log`：独立模块及其依赖的 strict/noEmit 类型检查通过，输出为空；ES2022 / ESNext / Bundler / DOM / DOM.Iterable / skipLibCheck。
- Node smoke 语法检查与 Python verifier `py_compile` 通过。

## 四旋转真实 native / 独立 pypdf

证据目录 `/tmp/pdf-next-form-canvas/independent/`。通过本模块真实 helper 构造 identity-bound 操作，调用既有 `editDesignWidget`，再由独立 pypdf 复读输出；不是 mock，不新增 engine 文件，不需要额外构建。

来源 SHA：`31fb7a659b728227cb7e78a75e077842ba30f36499186b6ba0700b51dfde4363`。四页包含文本和已选中复选框、非零 CropBox、四种旋转。每项先 Right 1pt，再 Shift+Up 10pt：

| 旋转 | 类型 | PDF delta | size | 输出 SHA-256 |
|---:|---|---|---:|---|
| 0 | text | `[1,10]` | 9093 | `eb30cba528201acb68fac33e1e567917c76471d8024fb1597705a49a09415bcc` |
| 90 | checkbox | `[-10,1]` | 8714 | `759f164b4b70b570bca34560fa34db518761869f884def172c47ef5943ffc582` |
| 180 | text | `[-1,-10]` | 9096 | `b942ad2b8cd28fc589c48cc5f0bdcb00ca3b05e28ae4287e2568d8f1b8967369` |
| 270 | checkbox | `[10,-1]` | 8715 | `6d5b42458bde6edadbf04ca5ce9cd39f98e206398feda134385ac7e2a73cc08e` |

`pypdf.json` 四项 PASS，每项复读全部 37 个原始对象及 raw/decoded 流。只允许目标 Widget Rect/AP 变化；独立验证屏幕方向对应 PDF delta、大小保持、正文、字段树、Annots、V/DV/AS、未选控件 AP 与页归属保持。未承诺对象数量零增长。

## 浏览器脚本与真实验收状态

专属脚本 `frontend/smoke/pdf-form-canvas-smoke.mjs`，独立复读 `pdf-form-canvas-verify.py`。本子任务未自行构建或执行完整浏览器专项；root 已使用统一冻结资产完成五次实际保存验收，最终证据见下文。

```bash
PDF_SMOKE_STATIC_DIRECTORY=<统一冻结静态目录> \
PDF_FORM_CANVAS_SMOKE_DIRECTORY=/tmp/pdf-form-canvas-browser-20261111 \
PDF_FORM_CANVAS_SMOKE_PORT=4350 \
node smoke/pdf-form-canvas-smoke.mjs
```

真实既有 `pdf-form-create-server.py`，grant/cookie/CSRF/生产资源/实际 preview-save-publication-download-reopen：

1. UI 在第一页创建独立 text（初始值 Canvas Alpha），第二页创建已选中 checkbox，各自实际保存。
2. 初始 Home 控制器不丢失，切到 Form Design 后点 text canvas，Right 后不重选/不重新聚焦，继续 Shift+Up；核单项操作、实际屏幕 boundingBox 与 zoom、Undo/Redo，预览确认后保存下载重开。
3. 真实把第二页旋转 90 度并保存，再点 checkbox 重复相同屏幕按键；核 PDF delta 为 `[-10,1]`，实际屏幕仍向右 1pt、向上 10pt。
4. 两次 nudge 对实际下载 PDF 用 pypdf 逐原对象核验。

总计五次保存。每次保存回执立即记录 `checkpoint.json`，下载核验后继续记状态，每个实际 JS asset 也核响应/磁盘摘要并持久化；失败保留源 server，可用相同目录/端口/冻结资产继续，不重复已经完成的 UI 保存。会核 server 保存数、原来源身份、已有下载身份及冻结资源身份；server 丢失时拒绝静默重放。

业务验收仍按实际 `validation` 报告；技术专项通过不意味着业务事实或完整版式验收通过。已有失败不阻止已生成且身份可核验的 PDF 下载签发。

## 独立模块冻结

`frontend/src/pdf-form-canvas.ts` SHA-256：`96064fbb7eb90668259216185a4e8c5b9ebde61a574663897a638ea7f008939a`。

未修改 `pdf-main.ts` / CSS / Vite / 共享 operations / HTTP / engine / LOCAL / SOURCE / 包清单；这些由 root 统一处理。

### 首次真实浏览器的应用级 RED 与保留检查点

root 首次运行目录 `/tmp/pdf-shortcuts-nudge-shading-form-browser/`（port 4382）。text/check 两次真实创建保存已通过，revision 5/6 的实际下载身份与重开均已记入检查点，没有重做。

在 `nudge0-select` 真实失败：预期第一页一个 Widget 命中框，实际两个。只读 `failure.html` 计数为三页共六个 `pdf-draft-overlays`、两个字段共四个 Widget 命中框。root 定位为 `renderPage` 同 generation 的并发任务在等待 TextLayer 后，过期任务仍追加 overlays；这是实际应用渲染生命周期缺陷，不是通过 selector 隐藏重复项。

root 以当前宿主仍包含该任务 canvas、且页面仍可见为条件阻止过期任务追加，并准备独立 final 前端冻结构建。r1 静态快照和原检查点完整保留，旧 manifest/assets 逐项核验后，在检查点显式记录 `buildTransitions`，仅把当前静态身份切到 final 构建，清空当前轮 assets。存活源 server 的固定路径可通过 final 构建的 symlink 继续服务；原来源与两次已保存 PDF 身份不变，原脚本从 revision 6 重开续跑 nudge/rotation，不重做已通过保存。

未进行浏览器验收的中间构建已被 final 构建替代，不作为通过证据。root 另在接线的 sync=false 分支 dispose 控制器，清理脱离 DOM 的监听。

本模块生产冻结未改变。此处记录真实失败和修复验证流程，不预先宣称final 构建续跑后浏览器通过；最终实际续跑证据已补入下文。

### final 构建续跑中的 QA 测量纠正

final 构建已通过 nudge0 的实际保存及页面旋转保存，共四项保存检查点。nudge90 的 staged 最终 PDF rect 正确、Widget 命中框唯一，但旧脚本的 client boundingBox 位移断言失败。

确定的只读浏览器探针 `/tmp/pdf-form-canvas-bbox-probe.json` 证明：选中 checkbox 的 SVG width/getBBox/getBoundingClientRect 均为 20，screen CTM a=d=1，描边 2px；Playwright `boundingBox()` 却包含描边，返回宽 22。旧脚本用 `22/20` 得出错误 scale=1.1，将正确的向上 10px 当成应有 11px。此前 text 的含描边宽 82/原宽80 得出1.025，仅因误差0.25小于原容差而通过。失败 HTML 的 Widget SVG x=181、y=50，精确符合旋转90页面的 Right1/Up10。

只修 QA，不改生产、资产或容差：scale 由 SVG width 属性/来源显示宽计算；客户端坐标另保留诊断，实际位移使用 Widget DOMclient 减所在 SVG DOMclient 的页内相对坐标，避免滚动平移影响。按键前落盘 beforeMeasurement，取得 afterMeasurement 后先写检查点再做位移断言。记录包含两类 client bbox、页内坐标、SVG 几何和描边。Node 语法检查通过；未重复任何已通过专项或前四次保存。

修正后 smoke SHA：`0441f4a0986f4f9e8c6ac1d985ececb907a54a05f30eff941e6da212d242e435`。root 使用同目录、同 port、同存活源 server，从最后已保存 rotated revision 继续尚未保存的 nudge90。最终通过状态仍以实际续跑 summary 为准。

历史测量区分：`nudge0Gesture` 保留原检查点，旧 scale=1.025 是含描边比例，已作废，不改写成新测量结果，也不重复该次保存。其原始 client 坐标明确记录位移 `[+1,-10]`，staged PDF rect 对应 `[+1,+10]`。最终修正后的 DOM/pageRelative 测量只用于尚未保存的 nudge90；nudge0 的最终产物保真另由独立 pypdf 对实际下载文件核验，不能表述为使用新 measurement 重新验过 nudge0。


## final 构建真实浏览器最终证据

`/tmp/pdf-shortcuts-nudge-shading-form-browser/summary.json`：`ok:true`。本子任务只读核对 summary 和五份实际下载 PDF，全部 SHA/size 与保存回执一致，未重跑任何测试或浏览器专项。

- Chromium `140.0.7339.16`；原来源 SHA `ae3d39ece3a0447af796296d8a7bf8158d16d60c4eeee1aed117781946d7298e`，`sourceUnchanged:true`。
- 静态固定 alias：`/tmp/pdf-shortcuts-nudge-shading-static`，指向 final 快照 `/tmp/pdf-shortcuts-nudge-shading-static-final`。
- final manifest SHA：`6c4e0445b2d9e0038a8b1a84eec85fcb5d22a16d6cf0a4555e5c46ea572bb0cc`；37 个实际 JS 资产摘要核验通过。
- r1 快照 `/tmp/pdf-shortcuts-nudge-shading-static-r1`，manifest `c22dc903c579bb21472d9d8eab2ad7c16f0af1cce99537ed4cdb2a591f74a370`。检查点 `buildTransitions` 保留旧资产摘要以及已完成 text/check 两次保存；nudge0 / rotated / nudge90 三次保存使用 final 构建。没有用中间未验收构建作为通过证据，没有重复已完成保存。
- 五次保存 text / check / nudge0 / rotated / nudge90，revision 连续 4→9，parentRevision 连续，每项均 `downloadVerified:true`、`reopened:true`。
- `pageErrors` / `consoleErrors` / `httpErrors` / `assetErrors` 均为空。重复 overlay 的实际应用 RED 已在 final 构建续跑中闭合，命中控件唯一性检查通过。
- 两次微调均在第一次 Right 之后不重新点击、不重新聚焦，继续 Shift+Up，`continuedWithoutReselection:true`；单操作累计、Undo/Redo、实际预览确认、保存、下载、新 revision 重开均通过。

| 微调 | revision | 实际下载 size | 实际下载 SHA-256 | 独立 pypdf |
|---|---:|---:|---|---|
| nudge0（text，0度） | 7 | 6164 | `5c7959bd375b3096569103dd75aebb9bf5bed934401c47bb81bb377c98fe50dc` | 28 个原对象，PDF delta `[1,10]`，Rect `[31,190,111,214]` |
| nudge90（checkbox，90度） | 9 | 6403 | `967ba91de40e1c5ec92735720f577c307525e9b7a2b8c987548b6a94085fedda` | 31 个原对象，PDF delta `[-10,1]`，Rect `[50,181,70,201]` |

两次独立复读均通过全部原始对象和 raw/decoded 流，只有目标 Widget Rect/AP 例外；正文、字段树、Annots、字段值/状态、未选控件 AP 与页归属保持。不承诺对象数量零增长。

最终 nudge90 的无描边 scale=1：页内 DOM 与 SVG 几何均从 `[180,60]` 到 `[181,50]`，对应屏幕 `[+1,-10]`；保留的 DOMclient 从 `[808,822]` 到 `[809,812]`，Playwright 含描边 client 从 `[807,821]` 到 `[808,811]`。旧 nudge0 检查点仍原样保留 scale=1.025，不以此错误比例背书：只依据其记录的 client delta `[+1,-10]`、staged PDF delta `[+1,+10]` 及本次实际下载的独立 pypdf。没有宣称 nudge0 使用新 pageRelative 测量重新验过。

全部五个保存回执仍如实报告 `validation.ok:false`、`native_source_review_pending`；文件与下载链接正常交付。**本次通过的是浏览器技术和产物结构专项，不等于业务事实或完整版式验收通过。**

root 已目视核对最终 `final-render-1.png` / `final-render-2.png` / `final-render-3.png`。本子任务本次只读核 summary/下载身份、补文档并读回，未运行任何测试/浏览器，独立模块冻结 SHA 保持 `96064fbb7eb90668259216185a4e8c5b9ebde61a574663897a638ea7f008939a`。
