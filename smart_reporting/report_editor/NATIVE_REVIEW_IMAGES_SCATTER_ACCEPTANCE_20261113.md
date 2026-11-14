# 修订视图、图片缩略图与散点图续批

日期：2026-11-13。目标仍为 Word / XLSX / PDF / PPTX 对齐固定 GenOffice，包括实际命令、中文、图标、交互、原生文件链与 Agno AI；本批不是全量完成声明。参考源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

证据根：`/home/junge/codex-evidence/smart_reporting/office-review-images-scatter-20261113/`。所有本轮日志和构建身份只支持各自列明的检查，不能继承为旧验收或整个 dirty 工作区通过。

## Word 恢复测试 fixture

`docx-recovery.test.tsx` 的轻量 schema mock 缺少生产使用的 `trackChanges` storage。root 先定向复现 `external refresh establishes a new undo baseline and allows new edits afterwards`，报错位置为 `docx-main.tsx` 初始化 `editor.storage.trackChanges.enabled`。在 mock 的 `editorExtensions` 中加入真实 `TrackChangesExtension`，没有给生产代码加 optional chaining，也没有改变生产跟踪修订逻辑。

- 原失败单项 RED → GREEN：`root-tests/word-recovery-track-storage-{red,green}-20261113.log`。
- 另 8 项相关用例通过：刷新锁、刷新回滚、回滚后的导航、已解决线程恢复、未失焦批注文字、节设置恢复、只读/保存锁、脚注共享历史。日志 `root-tests/word-recovery-track-storage-related-20261113.log`。
- 62 项文件没有整套重跑；本轮这组检查覆盖其中 9 项，其余 53 项不在本轮通过声明内。此前 50 失败/12 通过的历史记录保留；不能把 fixture 修复推断为所有历史失败均已关闭。

## PPTX 保存快捷键

固定源桌面文件菜单 `main/slides-main.ts` 提供 `CmdOrCtrl+S`，由 `App.tsx` 的 menu command 回调进入 `file-actions.ts::save`，先提交活动编辑。本地已有保存新修订的完整传输链，缺少快捷键入口。

`frontend/src/slides-main.ts::onClipboardKey` 增加原生 PPTX 编辑器的 Ctrl/Cmd+S，提交失焦输入后调用既有保存按钮，沿用当前修订保存、身份校验、草稿锁和下载链。组合键不含 Shift/Alt，组合输入和 dialog 不路由保存；重复按键、加载中、锁定中或保存按钮禁用时不重复保存；dispose 移除同一个 window listener。

- `root-tests/slides-save-shortcut-red-20261113.log`：新 6 项中 5 失败/1 通过，失败为缺少快捷键路由。
- `root-tests/slides-save-shortcut-green-20261113.log`：6/6 通过，包括 Ctrl/Meta、未失焦备注、blur 提交、输入法、modal/外部焦点、重复按键、禁用及 dispose。
- 相邻打印快捷键回归 3/3，通过日志 `root-tests/slides-save-shortcut-print-regression-20261113.log`；另外 2 项未重跑。
- `smoke/pptx-save-shortcut-smoke.mjs` 已准备真实 HTTP 导入、快捷键保存、下载及新修订重开探针；浏览器验收须另按实际执行结果登记，单测不代替文件闭环。

保存新修订仍不同于桌面原路径覆盖；打开、另存为、AI 命名、正式 PNG/JPEG 导出及矢量/链接/字体 PDF 导出等缺口继续保留。

## 本批集成复核记录

- root 在 Review 主机接线后重验恢复测试的 `external refresh establishes a new undo baseline and allows new edits afterwards`，1 项通过、61 项未运行，见 `root-tests/word-recovery-review-integration-20261113.log`。这不是恢复测试整套通过声明。
- 首次全局 `pnpm exec tsc --noEmit` 失败，3 项错误均在新 `docx-review-view.test.ts` 的 ProseMirror decorations 测试类型。改用实际渲染 DOM 断言后续验 exit 0，分别保留 `tsc-20261113.log`、`tsc-after-review-types-20261113.log`；后续源文件变更的覆盖范围须按最终冻结记录判断。
- PDF 缩略图透明度曾错误使用 `1 - bake.alpha`；UI 已将透明度换算成不透明度，bridge 和固定源均直接乘 `alpha`。root 发现测试与探针也沿用反值后要求同步纠正。`agent-tests/pdf-existing-image-thumbnail-green11-20261113.log` 记录校正后 pixels 3 项与 thumbnail 10 项通过。此结果不等于浏览器像素验收。
- PDF 四旋转几何 oracle 依据 PDF.js `PageViewport`，非零 CropBox 平移后的 180° 为 `[w - px, py]`。源像素方向与页面矩形投影分别核验，不能把四页 fixture 的存在当成四旋转浏览器覆盖。
- Word 原始视图使用固定源近似投影，不代表完整拒绝全部复杂格式修订。`PaginationPreview.revisionView` 是气泡测量用的 `EditorView`，不是显示模式；当前内联模式不因缺少该 prop 而判为缺陷。气泡和高级修订选项继续明确禁用。
- XLSX 散点图下一批轴标题、两轴网格线、显示单位、全局数据标签及按轴 ID 定位的编辑路径仍有缺口，详见 [散点图视觉缺口盘点](NATIVE_XLSX_SCATTER_VISUAL_GAPS_20261113.md)。本轮线条和 marker 修复不包含这些项目。

`agent-tests/` 保留原始尝试日志，文件名带 `green` 不保证该次执行通过，应读取实际退出信息与测试计数。早期未单独落盘的失败、被重用路径覆盖的日志不补造证据。

## 空间恢复与证据保留

本轮定向测试遇到 `ENOSPC`，根分区可用空间一度为 0。root 逐文件核对相对路径、大小和 SHA-256，只删除已完整持久归档的 8 份 `/tmp` 静态构建重复副本。各归档未删改，工作区未执行 reset/clean。

核验与移除列表分别为 `duplicate-static-cleanup.json` 和 `duplicate-static-cleanup-additional.json`。这些记录保留原临时路径、仍存在的持久归档、文件数及内容清单摘要；旧文档中的 `/tmp` 路径是历史运行位置，不再被当作当前文件存在证明。

后续根盘再降至约 15 MiB，root 仅在本任务三份已知归档（本批、`office-parity-review-print-20261113`、`office-mailmerge-pivot-next-20261113`）内，将至少 64 KiB 且逐字节一致的副本硬链接去重。所有逻辑路径和字节保留，未处理存在清单外硬链接的 inode，未触碰外部图片任务证据。`duplicate-evidence-hardlink-record.json`、`cross-batch-evidence-hardlink-record.json` 保存旧 inode/mtime、SHA、大小和目标；跨批去重回收 585160425 字节。文件时间差异应依这些记录解释，不能伪称归档元数据从未变化。

## 最终协调冻结构建

前两次普通 CLI 构建期间，另一路 XLSX 图片任务修改了共享工作区输入。这两份候选完整保留在 `source-drift-build/`、`source-drift-build-2/`，不列为冻结验收通过。经协调，2026-11-13 20:25–20:28（UTC+8）窗口完成第三次 `pnpm exec vite build --outDir <证据根>/static`，日志 `vite-build-20261113.log`，退出 0；同窗口 `pnpm exec tsc --noEmit` 退出 0，见 `tsc-coordinated-freeze-20261113.log` 和 `tsc-command-results.json`。

- 最终 `.vite/manifest.json` SHA-256：`e75ae6f085329fa7020e14104401724af3f15bcb7cbf6007f0e9fa3539b3c360`。
- 指定源码/配置树 3549 文件前后 identity 一致，其中 1745 个非测试 runtime 文件集合 identity 为 `960bf137cd877fe6a3e74ee0863675a5168ffae3d54453428366ac7779327bc9`。范围为 frontend/src、scripts、public、doc/workbook/slides engines 的 packages/bridge 和指定配置，不涵盖整个仓库、全部传递依赖或 PDF 后端全部输入。
- 485 个 JS chunks 按既有 `checkBuildBudget` 检查无超限，未放宽预算；203 个共享 pdfjs/licenses sidecar 的 SHA、大小、mtime 不变。见 `build-budget.json`、`build-integrity.json`、`build-inputs-{before,after}.json`。
- `frozen-asset-files.json` 登记最终 783 个静态文件。相同构建副本仅在逐文件 SHA/大小一致后做硬链接去重，逻辑路径和字节保留，见 `duplicate-build-hardlink{,-final}-record.json`。

构建完成后，外部 XLSX 图片任务继续独立修改共享工作区，已通知其 main 源码后续 SHA 为 `b27c3aa8293fe395c2dd3a618d4c3ee15851866da6b4343512b7420b7e5176f3`。本批仅验收上述 immutable static，不将其结果覆盖到后续 dirty 工作区或对方 v2 构建。`source-final/` 只归档本批 21 个产品/测试文件，不能称为全仓源码归档。

## 冻结资源上的浏览器验收

### Word 修订视图与 story 作者过滤

`word-browser-2/summary.json` 及 `word-browser-run-2.log` 记录正文、页眉、脚注的四模式矩阵：All 显示插入和删除，Simple/None 保留插入并隐藏删除，Original 保留删除并隐藏插入；格式修订 All 为 bold、Original 为 italic。包内 7 位作者及界面集合已独立核对。Specific People 隐藏 Body Alice 后保留插入文字、去掉修订墨色。普通独立段落上的真实编辑和 Undo 探针确认视图切换未改 live JSON/localStorage，Undo 仍有效；只读状态下显示视图可用，页面错误为空。

全模式目录的 `operations.json` 是测试预期描述，非 raw NativeDraft，详见 `operations-record-note.json`；不能据此宣称真实用户编辑后的 Word 草稿为空。新增窄验收 `word-story-filters/summary.json` 直接保存 editor JSON 与 raw draft 前后值，二者均不变：隐藏 HF Bob/Note Bob 后删除隐藏、插入保留；隐藏 HF Alice/Note Alice 后文字保留并去修订样式。本次没有编辑、保存或 history 操作。两组各实载 177 个 JS/CSS 资源，摘要与冻结文件逐项匹配。

单测 `agent-tests/docx-review-view-green-9.log` 的 61 项通过对应 review view 4、ribbon 49、notes pagination 8。root 最终恢复集成仅 `root-tests/word-recovery-frozen-review-20261113.log` 的 1 项通过、61 项未运行，不能扩展为恢复文件全通过。气泡、高级选项及 Original 的复杂修订边界仍按前文保留。

### XLSX Scatter 样式

`xlsx-browser/evidence.json`、`xlsx-browser-run.log` 和 `scatter-style.png` 记录 Chromium 上真实 XLSX 的四图检查：marker-only、红色 4px lineMarker、noFill、绿色 marker:none。Canvas 顶点、宽度和 marker 可见性符合 fixture；红 marker 首击选 series、再击选 point:0:0，绿色折线点击仅选 chart。NativeDraft 前后均为空，保存修订与 planner 调用均为 0，301 个实载 JS/CSS 摘要逐项匹配，page/console/http errors 均为空。独立 ZIP/XML 核对确认 OOXML 的 scatterStyle、38100 EMU 线宽、noFill 和 marker:none。

定向 reader 4/4、renderer 2/2 通过，另 119 项未运行。样式修复不包含轴、全局标签或 writer 按 axId 编辑，仍以[下一族盘点](NATIVE_XLSX_SCATTER_VISUAL_GAPS_20261113.md)列明边界。

### PPTX 快捷键保存文件闭环

`pptx-browser/summary.json` 与 `pptx-browser-run.log` 记录真实 HTTP import、本地授权/仓储 fixture 和 native bridge：在备注输入保持焦点时按 Control+s，产生恰好一次保存，下载 49952 字节，修订 2 重开读到 `快捷键保存：未失焦备注 😀`。166 个实载资源摘要匹配，page/console/http errors 均为空。

root 的 `verify-pptx-save.py` 独立检查下载包，结果在 `pptx-browser/independent-package-verification.{json,log}`：51 个非目录文件部件仅 `notesSlide1.xml` 改变，其余 50 个部件字节相同，XML/rels 均可解析，备注正文正确。首次检查器将 JSZip 新增的 16 个空目录误当文件集合变化，已在 `independent-validator-first-attempt.json` 记录并改为比较非目录部件、要求目录为空；没有为此重做保存。重开截图中的画布仍显示载入中，因此本探针只证明备注保存、下载、重开闭环，不证明 PPTX 画布完整渲染。

### PDF 像素与预览组合证据；底图合成仍有缺口

PDF 缩略图 pixels 3 项、thumbnail 10 项的定向测试通过不能代替真实浏览器。`pdf-browser/` 至 `pdf-browser-attempt6/` 保留 fixture、模型、构建及失败运行证据；早期失败涉及共享图像不允许替换、旧后端 bundle 缺少 bakeable/imagePixels 协议，随后改用隔离、从源码构建的真实 bridge runtime，未伪造模型字段。

attempt5/6 的 Node smoke 被 SIGKILL，内核日志 `pdf-kernel-oom-20261113.log` 明确记录 20:43:08 和 20:47:03 两次 OOM，Node 匿名 RSS 分别为 10986236、10511300 kB。后续 `stage-memory.jsonl`、受限 heap/RSS 的窄诊断将失败定位到大型 RGBA 数字数组的比较路径：imagePixels 是 480×360 的对象栅格，不是嵌入文件的 9×4；opacity 的浏览器 Canvas RGB 量化差异使大型 `assert.deepEqual` 生成差异文本，强烈支持其为原始 OOM 的触发路径。没有为证明这一推断再次重放 OOM。harness 改为 base64 传输和逐字节比较，失败只给前 20 个差异及摘要，不降低像素精度。

`pdf-browser-diagnostic8/diagnostic.json` 的透明度窄检查通过：Pillow 从原始 PNG 解码、独立计算 Alpha 乘数 0.45，原始期望 Alpha 精确为 115；期望 PNG 经过同一 Canvas roundtrip 后，与实际 mounted 图像的 691200 个 RGBA 字节完全一致。原始 RGB 230→可见 231、45→44 是预乘/反预乘量化；没有用统一 ±1 容差掩盖方向或 Alpha 错误。其余不透明翻转/裁剪/旋转仍按精确 RGBA 比较。

`pdf-browser-full-attempt/` 是保留的完整专项失败运行，源 SHA 为 `27fc4202a33266861338fd2066cdde1372d0ff9a041b2618407a109e32bba079`。四页 0/90/180/270 几何、移动缩放、替换、六种 bake、cached-ready redo、延迟像素请求撤销的断言均位于最终失败之前；15 条真实暂存操作及 7 张缩略图截图已保存。该次最后在 preview flag 置为 true 后立即断言 overlay=0，得到 1，因此没有成功 `evidence.json`，也没有补造已丢失的内存中 bakes 数组。源码时序证实 flag 先设置，之后才 await rebuildTextIndex/refresh；这属于 smoke 等待条件缺陷。harness 已永久改为等待四页面/缩略图节点和 overlay 清零，再滚到目标页检查 canvas，语法检查通过；没有重跑完整套件。

最后只补实际预览窄探针，目录 `pdf-preview-proof/`：重用同一来源和完整运行的最后一条 geometry 操作，真实 bridge 返回 applied `[0]`、skipped `[]`，预览 PDF SHA 为 `f5a762d8e8e214af0f09723b08fbd2efa6023ca9d739f0d5266e1f5d5713275b`。4 个页面节点、4 个缩略图 canvas、目标第 4 页 canvas 580×450、overlay=0；虚拟化视口当时只有 3 个页面 canvas，不能称四页全部栅格同时渲染。60 个实载 JS 资源逐个摘要匹配，page/console errors 为空；CSS 未被该 JS observer 单独列入实载资源清单。`verify-pdf-preview.py` 独立回读确认来源和最后操作一致，4 页旋转、MediaBox/CropBox、原始 9×4 图像像素与文字保持。没有保存修订或签发下载的验收声明。

窄探针早期有分支过晚而误重复前序 bake、对中间 3 个节点即时断言，以及缺实载资源记录等尝试，均原样归档在 `pdf-preview-probe-rejected/`、`pdf-preview-initial-attempt/`、`pdf-preview-intermediate-structure-attempt/`、`pdf-preview-without-resource-proof/`，不作为最终预览通过证据。`pdf-diagnostics-and-preview-archive.json` 记录持久化清单。最终原始 JSON 的 `runtimeAfter` 字段只是 before 对象 alias，不算独立采样；另以退出后的 `runtime-after.json` 和 root 当前文件哈希复核 before。bundle SHA 为 `90cbf67471581a586da84dbbca5bd937d4b9102675809661a45c90c85380d4c1`，外部 PDFium WASM SHA 为 `5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa`，Python wrappers 也逐项相同。`pdf-runtime/` 保留 bundle、metafile、WASM 和 wrappers；不是全部传递依赖或所有 PDF 功能的自包含冻结证明。

root 用实际 PDF.js PageViewport 对 `pdf-browser-diagnostic3` 的四旋转几何独立复核，最大归一化误差为 0.0001343（阈值 0.001）。前两版独立检查器误用了当前库不存在的 API，失败已在 `pdf-viewport-validator-attempt-note.json` 明确记为验证器问题，未重跑浏览器。

**本批未关闭底图合成缺口。** 目视 `thumbnail-opacity.png` 后对照固定源发现：源先在内存 PDF 副本移除旧图像、重绘保留背景/文字的区域，再叠加 transformed PNG；本地仍叠在原 thumbnail 上，仅矩形变化时加 62% 白 veil。PNG 像素正确不能证明合成等价，原位透明度/替换/翻转及移动残影仍需补真实 live-erased patch，详见 [PDF 源盘点](NATIVE_PDF_SOURCE_INVENTORY_20261113_INCREMENT.md)。下一最小修复限定现有单目标 `transformExistingImage` 缩略图，不顺带增加主画布实时预览或多目标抽象；保存、发布和非阻断下载协议保持原链路。

## 独立资源核验

`verify-runtime-evidence.py` 的结果为 `independent-runtime-resource-verification.json`：逐项复核 Word 177、story filters 177、XLSX 301、PPTX 166、PDF 窄预览 60 个资源摘要、各 fixture 文件身份、Word 作者与 XLSX chart XML；全部 783 个冻结资源和本批 source-final 摘要仍匹配。PDF 只覆盖上节明列的预览和身份，不覆盖尚未修复的待处理缩略图合成；JSON 单列 openGaps。总目标继续进行，本批通过项不等于四格式命令族或整体 GenOffice 对齐完成。

`harness-final/` 及 `harness-final-manifest.json` 补充归档四格式的 13 个 smoke/本地 helper，保留源码相对路径、大小和 SHA；这不是全部 Python 业务模块或 node_modules 的自包含归档。PDF 实际窄运行版本另在 `pdf-preview-proof/harness-preview-only.mjs`，修正等待条件后的主 harness 仅做语法检查，未重跑完整套件。探针直接用 Node 和环境变量启动，无新增 package script。`runtime-version-supplement.json` 记录补充盘点时的 Node/Python/依赖版本，不冒充各次原始运行已经采集的版本日志；XLSX 原始 evidence 单独记录了 Chromium 版本。Word story 两张截图的视觉复核在 `word-story-filters/visual-review.json`，页面高于视口，截图未覆盖整页。

后续独立批次已补单目标 PDF 缩略图的真实背景擦除，并完成白底残影、彩底/底层文字及四旋转局部 clip 验证，见 [PDF 图像背景补齐验收](NATIVE_PDF_IMAGE_BACKGROUND_ACCEPTANCE_20261113.md)。该批使用另一份受控构建与后端 bundle；本文件原始失败、`e75a...` 的通过范围及其 `openGaps` 历史记录保持不变。
