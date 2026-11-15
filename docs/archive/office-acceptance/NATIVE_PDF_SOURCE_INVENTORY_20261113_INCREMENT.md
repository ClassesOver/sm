# Native PDF 源码盘点（2026-11-13 增量）

这是一份增量证据清单，不代表整个 PDF 编辑器已完成源码级盘点。本文记录一个完整的固定源码功能族（Page 功能区）和完整的固定源码缩略图叠层功能族。本文补充 [pdf-SOURCE.md](./frontend/src/pdf-SOURCE.md)，不替代该文档，也不改变其中关于桌面版、发布、文字编辑和 OCR 的范围说明。

参考源码为 GenOffice `apps/pdf/src/renderer/App.tsx`，固定提交为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`；`PdfThumb.tsx`、`DrawLayer.tsx`、`PdfPage.tsx` 和 `text-edit-preview.tsx` 来自同一源码树。下文中的源码路径均位于 `/home/junge/pros/genoffice-source-full/apps/pdf/src/renderer/`。源码 `control.ts` 是处理 `goto` 和 `selection` 的 shell IPC handler（`control.ts:1`、`control.ts:21`），并非功能区分发器。功能区命令是 JSX 按钮，其 `onClick` 调用 App 闭包。

## Page 功能区

固定源码的 Page 选项卡有四个视觉分组，共 17 个命令（`App.tsx:8882`、`App.tsx:8884`、`App.tsx:8919`、`App.tsx:9009`、`App.tsx:9034`）。本地语义 ID 由宿主定义，因为固定源码按钮没有稳定的命令 ID 契约。`sourceCommand()` 负责赋予这些 ID（`pdf-main.ts:331`）；分组定义位于 `pdf-page-ribbon.ts:13`；`pageActions` 分发这些 ID（`pdf-main.ts:1064`）；分组控件绑定到对应回调（`pdf-main.ts:1109`）。当前 17 个 ID 都有回调项。`pdf-page-ribbon.test.ts` 固定了顺序、分组和 ID，但该测试本身不验证回调行为。

本地“页面操作”（Page Operations）分组当前与固定源码顺序对齐：“压缩 PDF”位于“插入 PDF”之后、“插入空白页”之前（`pdf-page-ribbon.ts:23`；固定源码：`App.tsx:8941`、`App.tsx:8951`、`App.tsx:8975`）。两边都有对应命令回调。

| 固定源码命令及处理器 | 本地回调与实际行为 | 盘点状态 |
| --- | --- | --- |
| 向左旋转，`App.tsx:8889`、`App.tsx:5026` | `pdf-main.ts:1084` 针对当前页面身份暂存 `rotatePage`，角度增量为 270。 | 作为绑定来源页面的草稿操作实现；实际 PDF 预览和修订保存走宿主工作流。 |
| 向右旋转，`App.tsx:8899`、`App.tsx:5026` | `pdf-main.ts:1085` 针对当前页面身份暂存角度增量为 90 的操作。 | 作为绑定来源页面的草稿操作实现；实际 PDF 预览和修订保存走宿主工作流。 |
| 旋转全部页面，`App.tsx:8909`、`App.tsx:5028` | `pdf-main.ts:1086` 调用 `rotateAllPdfPages`；`pdf-operations.ts:394` 覆盖所有保留的来源页面并保留页面身份。如果操作会超过 500 条草稿操作，界面会禁用该命令（`pdf-main.ts:1846`）。 | 已实现，并受明确的操作预算限制；仍需预览并保存为修订。 |
| 删除页面，`App.tsx:8924`、`App.tsx:5040` | `pdf-main.ts:1090` 暂存 `deletePdfPage`；`pdf-operations.ts:399` 禁止删除最后一页，并保留原页面身份供撤销和历史记录使用。 | 已实现为可撤销的草稿操作；仍需预览并保存为修订。 |
| 提取页面，`App.tsx:8934`、`App.tsx:6532` | `pdf-main.ts:1067` 打开 `bindPdfExtractDialog`（`pdf-main.ts:1027`）；`pdf-extract-dialog.ts:5` 解析有序页码范围并提交 `api.extractPages`。该操作从已保存的来源提取，并返回产物/编辑器链接，不会改动当前草稿。 | 已实现为独立产物工作流，仅允许使用干净的已保存来源。`pdf-extract-entry.test.ts` 覆盖功能区入口及未保存/只读门控。 |
| 插入 PDF，`App.tsx:8944`、`App.tsx:6563` | `pdf-main.ts:1065` 打开 `pdf-external-pages.ts:67`；对话框计算 PDF 哈希并上传，随后调用 `api.externalPages`（`pdf-main.ts:1043`）。 | 已实现为新修订，不是桌面版的原位插入。输入限制为 6 MiB，并检查来源和外部文档结构（`pdf-external-pages.ts:8`、`pdf-external-pages.ts:15`）。 |
| 压缩 PDF，`App.tsx:8955`、`App.tsx:6549` | `pdf-main.ts:1068` 调用 `api.shrinkPdf`，核对来源 SHA、大小和结果 SHA，之后只下载更小的副本（`pdf-main.ts:1072`）。 | 已实现为独立且经过校验的下载，不会替换当前修订；要求来源已保存且没有未保存修改。 |
| 插入空白页，`App.tsx:8978`、`App.tsx:6577` | `pdf-main.ts:1094` 暂存 `insertBlankPdfPage`；`pdf-operations.ts:428` 绑定新页面 ID 和插入位置邻页。 | 已实现为可撤销的草稿操作，并受操作预算门控。 |
| Bates 编号，`App.tsx:8989` | `pdf-main.ts:1102` 打开 Bates 编辑器；`pdf-bates.ts` 构建绑定来源的操作和预览。 | 已实现，但受引擎能力检查门控；是否验收通过取决于实际 PDF 预览和发布流程。 |
| 替换页面，`App.tsx:8999`、`App.tsx:6645` | `pdf-main.ts:1066` 打开 `pdf-external-pages.ts:67`；选定的父级页面和外部 PDF 摘要通过 `api.externalPages` 提交。 | 已实现为新修订，而非原位重写。仅支持受支持的外部/来源结构，并保留原修订。 |
| 裁切页面，`App.tsx:9014`、`App.tsx:6698` | `pdf-main.ts:1082` 打开裁切界面。`pdf-main.ts:903` 支持当前页或全部页面并暂存 `cropPage`；`pdf-operations.ts:301` 根据来源页面校验可见裁切范围。 | 已实现为绑定来源的草稿操作，并受能力门控；裁切会改变可见区域，不等于删除敏感内容。 |
| 页面尺寸，`App.tsx:9024`、`App.tsx:6663` | `pdf-main.ts:1083` 打开尺寸界面；`pdf-operations.ts:27` 校验所选纸张预设。操作应用于所有保留页面，并立即准备实际 PDF 预览（`pdf-main.ts:947`）。 | 已实现为预设尺寸选择，并带有兼容性限制；需要确认预览。 |
| 反转页面，`App.tsx:9039`、`App.tsx:5031` | `pdf-main.ts:1105` 按当前可见顺序暂存 `reversePdfPages`（`pdf-operations.ts:388`）。 | 已实现为可撤销的草稿操作；仍需预览并保存为修订。 |
| 拆分 PDF，`App.tsx:9049`、`App.tsx:6599` | `pdf-main.ts:1080` 打开延迟加载的拆分宿主（`pdf-main.ts:1030`），随后进入独立文件拆分流程。 | 已实现为独立输出文件，不会改变页面布局。受来源干净/刷新、修改状态和输出链接条件限制（`pdf-split-host.ts:16`）。 |
| 合并 PDF，`App.tsx:9056` | `pdf-main.ts:1081` 打开合并宿主（`pdf-main.ts:1039`），并通过原生 API 生成独立的合并 PDF。 | 已实现为独立输出流程，当前编辑器修订保持不变；是否可用取决于保存/刷新完成和输入校验（`pdf-main.ts:1034`）。 |
| 合并页面，`App.tsx:9065` | `pdf-main.ts:1103` 打开布局对话框；`pdf-operations.ts:275` 构建 `mergePages`，随后进行实际预览（`pdf-main.ts:971`）。 | 已实现为新修订的布局操作，不是桌面版的文件输出流程。操作必须独占执行，并受支持的表单/签名结构限制（`pdf-main.ts:964`）。 |
| 拆分页面，`App.tsx:9075` | `pdf-main.ts:1104` 打开布局对话框；`pdf-operations.ts:278` 构建 `splitPages`，随后进行实际预览（`pdf-main.ts:971`）。 | 已实现为新修订的布局操作，不是桌面版的文件输出流程。仅支持 2/4/9 分割，并受支持的表单/签名结构限制（`pdf-main.ts:964`）。 |

现有源码盘点文档记录了更广范围的应用验收与功能开关，见 [pdf-SOURCE.md](frontend/src/pdf-SOURCE.md)。本次增量盘点未重新运行这些验收流程。上表区分固定源码行为与原生编辑器的修订/产物模式；“已实现”不代表已通过发布或验收。

## 缩略图叠层功能族

固定源码明确说明 `ThumbPendingOverlay` 是只读镜像，并禁用其指针事件（`PdfThumb.tsx:133`）。源码缩略图分支位于 `App.tsx:9383`：渲染 PDF 位图、可选的擦除补丁，随后只对可见缩略图渲染待处理编辑镜像（`App.tsx:9410`）。`stampPreview` 本身也只处理可见行（`App.tsx:5107`）。

| 源码分支 | 固定源码行为 | 本地宿主状态与边界 |
| --- | --- | --- |
| 页面缩略图栅格 | `PdfThumb.tsx:31` 为每个可见的 `(doc,page,rotation,width)` 渲染一个 PDF.js canvas，并释放屏幕外 canvas 像素（`PdfThumb.tsx:46`）。 | 本地 `thumbnailForPage()` 使用可见槽位观察、取消和延迟 canvas 绘制（`pdf-main.ts:2468`）；具备与源码相近的栅格行为。 |
| 擦除实时预览 | `App.tsx:9392` 叠加来自 `livePreview` 的裁剪 PNG；同时把已擦除文本行的 key 传给文字编辑渲染（`App.tsx:9435`）。源码补丁由文字编辑预览管线生成（`App.tsx:6056`）。 | 原生宿主没有等价的栅格擦除补丁。原生 `redact` 会预览待处理的涂黑区域，并在实际 PDF 预览中执行结果；这是另一种操作，不计作源码擦除对齐。根据 `pdf-SOURCE.md:87` 和 `pdf-SOURCE.md:115`，OCR 仍不可用并排除在本次范围外。 |
| 标记 | `ThumbPendingOverlay` 将待处理 `markups` 传给 `MarkupOverlay`（`PdfThumb.tsx:188`）；源码几何和四种样式位于 `PdfPage.tsx:141`。 | 本地缩略图将身份匹配的待处理 `addMarkup` 四边形映射到 PDF viewport（`pdf-markup-thumbnail.ts:14`、`pdf-main.ts:2656`）。`removeMarkup` 和已保存批注记录不属于缩略图叠层；移除效果由实际预览呈现。 |
| 绘图 | `ThumbPendingOverlay` 将待处理绘图传给 `DrawLayer`，但不提供活动工具或修改回调（`PdfThumb.tsx:189`）。 | 本地缩略图为支持的待处理 `addDrawing` 形状构建只读 SVG，并复用 `paintDrawing`（`pdf-main.ts:2671`、`pdf-drawing-shapes.ts:7`）。链接/图像保持为内联草稿数据，不会引入外部图像源。 |
| 插入文字 | `ThumbPendingOverlay` 使用 `textInsertPreviewStyle` 显示插入的文字（`PdfThumb.tsx:210`）。 | 本地 `insertText` 绑定来源和页面身份（`pdf-static-text.ts:15`、`pdf-static-text.ts:85`）。待处理文字现在通过 `pendingPdfTextInsertsForThumbnail()` 校验身份，并按当前旋转后的 PDF viewport 映射基线和样式（`pdf-static-text-thumbnail.ts:7`、`pdf-static-text-thumbnail.ts:16`、`pdf-main.ts:2672`）。实际 PDF 预览时，既有 `!previewDocument` 守卫会移除待处理镜像，避免与已写入页面重复（`pdf-main.ts:2648`）。 |
| 编辑文字和已擦除文本行 | `textEditPreviewParts` 绘制遮盖和替换文字（`PdfThumb.tsx:219`）；如果实时栅格已擦除旧文本行，`erasedText` 会阻止再次绘制旧文本行遮盖（`PdfThumb.tsx:223`）。 | 本地 `replaceText` 已补受限的待处理缩略图遮盖及替换文字：绑定来源页面/对象/原文摘要，PDF.js layout与可信PDFium ink bounds联合覆盖旧字，唯一水平LTR PDF.js文字项定位，成功渲染后逐对象采样底色并继承不透明填充颜色。实际PDF预览移除两个镜像。页面rotation=0/90/180/270、UserUnit=1、单行且无styleRuns/colorRuns的受限范围已有精确几何和实际短文预览验收，见[本批记录](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)。歧义或缺少可信颜色时跳过；复杂背景采样/长文本仍有限制。擦除实时栅格补丁仍缺失，保存仍需显式核对实际PDF预览。不以OCR替代来源对象检查。 |
| 图像编辑 | `ThumbPendingOverlay` 将待处理 `imageEdits` 传给 `ImageEditLayer`（`PdfThumb.tsx:166`）。 | 本地新增图像绘制保留 `addDrawing` SVG 路径。续批为 `transformExistingImage` 接入来源/页面/图像身份绑定的待处理缩略图，覆盖矩形移动缩放、替换、翻转、裁剪、透明度与四分之一转；PNG 回执摘要/尺寸检查、挂载后 ready、异步取消和实际预览去重均在限定路径内。13 项定向测试通过；真实像素及四页面旋转几何的浏览器结果另见[续批记录](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)，不能据此关闭整个图像功能族。 |
| 印章 | `ThumbPendingOverlay` 将每页印章映射为带矩形区域和透明度的 PNG（`PdfThumb.tsx:179`）；源码印章预览只处理可见行（`App.tsx:5108`）。 | 本地待处理 `setStamps` 按来源/页面身份筛选，并映射到旋转后的 CropBox viewport（`pdf-stamp-thumbnail.ts:10`、`pdf-main.ts:2666`）。显示实际预览 PDF 时会隐藏这些叠层（`pdf-main.ts:2648`）。 |
| 原生静态表单填写（宿主扩展） | 固定源码 `ThumbPendingOverlay` 的 props 中没有对应的 `staticFill` 分支（`PdfThumb.tsx:137`）。 | 本地待处理静态表单填写 PNG 是额外的原生能力：校验来源/页面身份，并在相同的非预览分支渲染（`pdf-static-fill-thumbnail.ts:12`、`pdf-main.ts:2650`）。这是宿主扩展，不宣称与固定源码对齐。 |

本地所有待处理缩略图分支都位于非预览判断之后（`pdf-main.ts:2648`），因此不会在显示实际 PDF 预览时重复叠加。叠层会禁用指针事件，或使用现有 `.pdf-pending-drawings` 规则（`pdf.css:126`），保留缩略图点击、拖动和上下文菜单交互。与固定源码只在 `visibleThumbs` 页面上创建待处理叠层（`App.tsx:9411`）不同，宿主当前会为 `state()` 列表中的每一页创建待处理 DOM 叠层；只有栅格 canvas 工作按视口延迟。这是大型文档的性能差异，不代表视觉叠层缺失。

### 已有图像的像素与合成仍需分开验收

续批窄验收证明 transformed PNG 的几何与像素，不代表底图合成已等价。固定源 `ImageEditLayer.tsx` 明确依赖先擦除旧图像的 live page patch：`App.tsx` 的 `livePreviewRects` 为每个非 insert 图像操作收集 `oldRect`，调用 `pagePreviewPng(excludeRects)`；`image-edit.ts::renderPagePreviewPng` 仅在内存副本中移除指定图像，再渲染仍保留背景/文字的区域；该 patch 也覆盖缩略图原位图，之后才叠加新图像。

本地 `pdf-existing-image-thumbnail.ts` 尚未接入该背景 patch，仅在矩形变化时叠加 62% 白色 veil。原位透明度、翻转、替换等仍将新 PNG 叠在旧图像上；移动时旧图像也可能残留。root 目视 `pdf-browser-full-attempt/thumbnail-opacity.png` 并检查挂载/CSS 路径后，保留这一合成/ghosting 缺口，不能用 PNG 内 Alpha 或 RGB 校验替代整体缩略图视觉验收。后续应复用固定源移除目标后重绘区域的方式；简单不透明白块会丢失背景/文字，不是等价修复。证据根同[续批记录](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)。

已经存在于来源 PDF 中的已保存标记、绘图和印章由页面位图渲染，不属于 `ThumbPendingOverlay` 只处理待提交内容的契约。因此，本地盘点没有把已保存对象缩略图列为差异。

## 证据边界

相关现有测试包括 `pdf-page-ribbon.test.ts`（仅验证命令顺序/ID）、`pdf-extract-entry.test.ts`、`pdf-external-pages.test.ts`、`pdf-static-fill-thumbnail-host.test.ts`、`pdf-markup-thumbnail.test.ts`、`pdf-stamp-thumbnail.test.ts`、`pdf-drawing-canvas.test.ts` 和 `pdf-drawing-appearance.test.ts`。`pdf-static-text-thumbnail.test.ts` 覆盖来源/页面身份及 90/270 度 viewport 几何；`pdf-static-fill-thumbnail-host.test.ts` 覆盖宿主投影、样式及实际 PDF 预览去重。两文件的定向测试共 6 项，全部通过。

真实浏览器证据由 `smoke/pdf-static-text-thumbnail-smoke.mjs` 提供，最终产物位于 `/tmp/pdf-static-text-thumbnail-20261113-run16/`。该次复用隔离生产主 bundle `/tmp/pdf-static-text-thumbnail-20261113-run5/static`，74 个浏览器资源逐个校验 SHA-256；当时的 Vite 插件仍将 PDF.js sidecar 复制到默认共享 `static`，因此这批旧证据不能支持“共享 static 未写入”的结论。插件现已修复为 sidecar 跟随 `build.outDir`；另有后续隔离构建与 shared SHA/mtime 核验记录，不回写 run16 原始证据。真实 PDF.js 读取来源 SHA-256 为 `3828263cd8facb3f446cb0c5a3417148e32408a6993e6119561dc440f8e37375` 的两页 PDF，页面旋转分别为 90°/270°，CropBox 均为 `[20,30,280,370]`，MediaBox 均为 `[0,0,300,400]`。截图为 `pending-90.png`、`pending-270.png` 和 `actual-preview-270.png`；真实 `/api/preview` 返回 `appliedOperationIndices: [0]`、`skippedOperations: []`，实际 PDF 预览状态为 true，重复 pending overlay 数为 0，浏览器 console/page/http 错误均为空。stdout/stderr、HTTP 请求、资源哈希和服务日志分别保存在 `smoke.stdout.log`、`http-evidence.json`、`evidence.json` 和 `server.log`。该探针没有保存或下载修订，也没有覆盖长文本边缘和所有字体。

## 替换文字缩略图的受限真实验收

最终静态资源为 `/tmp/pdf-replace-text-thumbnail-20261113-final6/static`，Vite manifest SHA-256为 `5cf73c83e35c10ad6dfe09a184f3cb3da5432303c50ebc919d4edad1c37bcf01`。`smoke/pdf-replace-text-thumbnail-smoke.mjs` 使用真实HTTP、Chromium、PDF.js和隔离源码引擎 `/tmp/pdf-replace-text-thumbnail-root-engine-20261113`；该目录不含旧dist，避免Python优先使用旧bridge而缺少fillColor。它不是生产授权/签发验收，没有保存或下载修订。

`/tmp/pdf-replace-text-thumbnail-20261113-color5/evidence.json` 对来源 `154ac7b15ec3d24a7fdfa861a1170d44de23de6bc637669464f55bdd1cb4b64c` 的第一页执行单一 `replaceText`，没有显式font/color覆盖。初始HTTP模型的fillColor为 `[18,52,86]`；待处理文字及遮盖均为浅黄底 `rgb(255,242,204)`，文字保留 `rgb(18,52,86)`。实际预览执行 `[0]`、跳过为空，回读替换文字fillColor仍为 `[18,52,86]`，预览状态true且overlay+cover为0。77份实际响应资源SHA匹配磁盘；777份静态文件起止manifest一致，摘要 `913fdd180012a80c7fd3f1097c0b6645c13bd456a122ed2f16bb10897771c674`。此摘要是全文件清单，不是上段Vite manifest摘要，也不证明构建前后共享static未写入。

root逐资源核验并目视pending/actual-preview两截图，独立pypdf回读两页CropBox `[20,30,280,370]`、MediaBox `[0,0,300,400]`、旋转0/270及浅黄/浅绿填充与深蓝原字；本次替换只操作第一页，不能据第二页存在就宣称旋转页替换通过。证据及静态资源分别归档 `/home/junge/codex-evidence/smart_reporting/office-parity-review-print-20261113/pdf-replace-thumbnail-color/`、`pdf-replace-thumbnail-static/`，独立记录为 `root-independent-proof.json`。

早期color4的原始`ok:true`没有覆盖宿主showError状态；root从截图及TypeScript检查发现ready回调变量作用域错误，已拒绝该轮并保留 `pdf-replace-thumbnail-prior-attempts/root-color4-rejected.json`。final6修正后真实cover和文字颜色均核对。该冻结的现有预算仍有SlideThumb、workbook-main两项超限（480份JS），详见 `office-pdf-replace-final6-budget-root-20261113.json`；未提高限额，不将Vite构建成功说成全部构建门槛通过。

随后在同一final6资源上补宿主状态断言，最终浏览器目录 `/tmp/pdf-replace-text-thumbnail-20261113-color7/`，归档 `pdf-replace-thumbnail-color-final/`。pending阶段必须为未保存修改状态且无scope错误，实际预览状态必须为正常提示；同时断言cover背景，不再只检查文字背景。root重新目视该次两截图并独立核对77资源及777文件。原始JSON未序列化两段status字符串，因此状态证据来自断言脚本及截图，不伪称JSON包含这些字段。

`pdf-static-fill-thumbnail-host.test.ts` 新增延迟render与IntersectionObserver显示→隐藏取消→再次显示的回归，验证未执行的采样订阅保留、cover/背景更新、白字对浅底重算ink及无scope错误。该文件最终5/5通过，原始日志 `pdf-replace-text-thumbnail-20261113-host-lifecycle-vitest-final.log`；root读取日志和断言，没有重复整套测试。root修正后TypeScript命令以0退出，日志 `office-parity-pdf-scope-fix-types-root-20261113.log`；不改写此前exit2的失败记录。上述日志均在同一归档根目录。

本文不声明整个 PDF 功能的对齐百分比：部分 Page 命令会生成独立产物或新修订，待处理文字编辑的多样式/复杂字体、长文本及复杂背景采样、已有图像编辑和擦除缩略图叠层仍有差异；已验证的四种页面旋转短文范围另见[续批记录](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)。
