# PPTX 当前草稿打印增量验收

日期：2026-11-13。完整四格式 GenOffice 对齐目标仍未完成。本记录只覆盖浏览器打印等价链，不代表桌面打印机驱动、PPTX 导出 PDF／图片或全部文件菜单已经完成。

## 固定源与实际实现

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`：

- `apps/slides/src/renderer/components/PrintDialog.tsx`：全部／当前／自定义范围、隐藏页筛选、五种布局、方向、加框、预览宽度缩放和系统打印入口。
- `apps/slides/src/shared/print-html.ts`：范围解析、页数及整页／2张／3张／6张讲义／备注页 HTML，原字节复制至 `frontend/src/vendor/genoffice/shared/print-html.ts`，原始身份见同 vendor 的 `PRINT-SOURCE-SHA256.json`。
- `apps/slides/src/renderer/export-render.tsx`：逐页离屏 Konva PNG 渲染。本地 `slides-print-render.tsx` 复用现有原字节 `SlideThumb`，增加仅内嵌图像读取和取消清理。

本地原“打印”按钮永久禁用。本增量由 `slides-main.ts::openPrint` 捕获当前来源 SHA、完整 NativeDraft 操作与当前页，读取相同请求身份的 `render-tree` 和 `preview`，再由 `slides-print-dialog.ts` 使用实际输出页序、隐藏状态和备注生成静态快照。弹窗、加载、确认与卸载检查陈旧身份。没有保存、导出或改写演示文稿。

打印设置包括全部／当前／自定义范围（去重并按页序）、隐藏页、整页／2张／3张／6张／备注布局、纸张方向与整页加框。预览按固定源通过 iframe body zoom 适配面板宽度；真正打印使用独立 iframe 和非 preview HTML，避免打印预览页码徽标。打印机、份数、双面由浏览器系统对话框提供，不伪造 Electron 打印机队列接口。

修复了并行复核发现的生命周期问题：每次打印独立 AbortController；图片成功、失败、取消均解绑 load/error/abort 监听器；重新打印和关闭时取消旧任务。保留输入验证与过期快照错误，取消不改草稿。

## 测试与冻结浏览器证据

统一证据目录：`/home/junge/codex-evidence/smart_reporting/office-parity-review-print-20261113/`。

- `slides-print-red-20261113.log`：新增弹窗行为的 3 项 RED。
- `slides-print-ribbon-red-20261113.log`、`slides-print-host-red2-20261113.log`：入口／真实宿主未接线的 RED。首次 host RED 因测试环境缺 ResizeObserver，补夹具后重新验证缺少入口行为，不把环境异常当功能 RED。
- `slides-print-listener-red-20261113.log`：图片加载结束后取消监听器仍未移除的 RED。
- `slides-print-zoom-red-20261113.log`：预览没有缩放的 RED；后续按固定源实现并 GREEN。
- `slides-print-current-unit-20261113.json`：弹窗 5 项、宿主 1 项、功能区 40 项，共 **46/46 通过**。覆盖范围／隐藏页／转义备注／无保存／取消／陈旧快照／监听清理／预览缩放。仅运行受影响文件，未重复全项目测试。
- `office-slides-print-build-final-20261113.log`：隔离 Vite 构建 exit 0，50.02 秒。未覆盖共享 static、未部署。它是 Vite 构建证据，不能代替全量 TypeScript 检查。
- `static-final/.vite/manifest.json` SHA256：`bf48c37530771c91428c2540bf8c79ae7d8ddeded30a11560b06b4d1ec839f5d`。
- `browser-final/summary.json`：真实原生导入、当前草稿读取和 PNG 渲染；全部默认排除隐藏页，启用后 3 张；无效范围保持错误，讲义 3 张／横向／备注页，390px 窄窗，关闭无草稿变化、无保存、新修订数 0。页面／控制台／HTTP 错误均为空。
- 浏览器捕获 373 份脚本，其中 **158 份为应用冻结资源，逐字节与磁盘 SHA 匹配**；另外 215 份来自 Chromium 自身 PDF viewer 的 `chrome`／`chrome-extension`，不将它们计为应用资源身份。系统 `window.print` 被明确的可观察替身替代，测试不会调用真实打印机。
- `browser-final/print-full.png`、`print-handout.png`、`print-notes.png`、`print-mobile.png`：已目视核对，修正了初版未缩放的预览。窄窗整体弹窗可滚动，按钮可到达；没有横向溢出。
- `browser-final/printed.pdf`：另以真实 Chromium print-to-PDF 生成所选备注页。`pdf-readback.json` 独立 pypdf 确认 1 页、MediaBox `841.91998 × 594.95996` pt（A4 横向）；Poppler 渲染见 `printed-rendered.png`，已目视检查。HTML 备注确为“空白页讲稿”，但 PDF ToUnicode 抽取为“空⽩⻚讲稿”，**纯文本完全往返一致性未通过，不宣称已通过**。不以自定义替换表掩盖此差异。

`current-source-identities.json` 为构建后的当前源码身份快照，明确不把同时发生的其他工作区改动冒称为冻结构建。运行时结论绑定上述实际加载的冻结文件。

## 首批冻结时的开放边界（后续状态见续记）

1. 桌面打印机列表、驱动选项、静默打印与实际纸张输出未验证；浏览器系统对话框是本增量的实际设备入口。
2. 五种布局均有实现；本次真实浏览器覆盖整页、3张讲义和备注页，2张／6张只有共享原字节 builder 与定向逻辑证据，不能说全部视觉场景已验收。
3. 独立 PDF 中文文本抽取含兼容部首，尚未定位为系统字体或 Chromium ToUnicode 的哪一层。
4. 当前完整工作树 TypeScript 检查曾报告其他并发 DOCX/XLSX/表单/3D 适配诊断，不能以本次 Vite 成功声称全量类型通过。
5. `build-budget.json` 对同一冻结构建仍失败：native-docx-engine 424.5/420 KiB、pdf-main 272.8/250 KiB、slides-main 253.4/250 KiB、three.module 729.3/250 KiB、workbook-main 265.1/253 KiB。打印独立两块为 9548/1902 bytes；没有提高任何预算。完整产品发布准备状态未通过。
6. 导出 PDF／图片、其它文件菜单及四格式穷尽盘点仍是独立工作。无提交、推送、部署。

## 加载清理、快捷键与五布局续验

后续真实检查发现两项增量：离屏渲染的内嵌图片在成功／失败／取消后未清理回调，以及源 `main/slides-main.ts` 的 `CmdOrCtrl+P` 尚未接通浏览器打印。现已清理 load/error/abort 回调；一张失败即取消同批其它未完成图片，移除待加载 src；成功保留已解码图片供画布读取。新增三个 renderer 用例先 3 项 RED 再 GREEN。

`Ctrl/Cmd+P` 在本编辑器有焦点时进入相同的 `openPrint`，不拦截其它编辑器焦点、额外 Alt/Shift 组合、输入法组合或已有模态框。快捷键测试先 2 项 RED；进一步复现活动输入晚于快照提交的问题，现先 flush 属性／备注／批注并使当前输入提交，再捕获 NativeDraft。保留弹窗关闭后的焦点返回。受影响三个文件最终一轮为 **13/13**，另追加焦点断言后只复跑该用例 **1/1**；精确日志 `slides-print-lifecycle-shortcut-final-20261113.log`、`slides-print-shortcut-focus-green-20261113.log`。未重复全项目测试。

新独立冻结输出 `static-lifecycle/`，Vite exit 0、48.29 秒；manifest SHA256 `8b65083db8cd37249fd4023e7d44bac30ffd81ccd29aadef0fb872e429438e59`。它与上方 `static-final/` 是不同构建，不相互替换历史证据。真实 Chromium `browser-lifecycle/summary.json`：

- 五布局整页／2 张／3 张／6 张／备注均实际打开；2 张讲义显示 3 张幻灯片分 2 页，6 张为 1 页，截图已目视检查；其它原有范围／隐藏页／横向／窄窗检查保留。
- `Control+p`、`Meta+p` 均在关闭后重新打开实际原生快照并成功渲染；全部过程无保存、新修订 0、草稿不变。
- 页面／控制台／HTTP 错误均为空。共 398 份捕获脚本，**183 份应用资源与该冻结目录逐字节 SHA 匹配**；其余为 Chromium PDF viewer 内部脚本，不计作应用身份。
- 本轮独立 print-to-PDF 再次回读为 1 页 A4 横向，MediaBox `[0,0,841.91998,594.95996]`；中文仍抽取为“空⽩⻚讲稿”，精确纯文本往返缺口未消除。系统打印仍使用已声明的可观察替身。
- `build-budget-lifecycle.json` 用现有未修改预算检查脚本检查该冻结构建，**0 预算失败**。共享工作树现有 Vite 配置增加源模块分包：Word engine 417841 bytes、PDF main 202114、Slides main 250208、Workbook main 253009，打印两块 9548／2201。预算通过仅代表包大小合格，不代表分包后全部 3D、Word、PDF、XLSX 路径均已运行验收。
- TypeScript 收敛记录见四格式续记；不再把首批类型失败当作当前持续失败。打印专项通过也不改变其余文件命令缺失的事实，见[文件菜单八项逐源盘点](NATIVE_PPTX_FILE_SOURCE_INVENTORY_20261113.md)。

续验目录和日志追加到同一持久证据归档，首批资源及结果保留。完整四格式对齐仍未完成。

另在同一个 `static-lifecycle` 冻结构建上新增非空草稿验收 `browser-draft/`：实际修改演讲者备注为“尚未保存的打印备注”，确认 NativeDraft 非空，直接在备注输入框按 `Control+p`，当前页备注打印 HTML 精确显示新内容；关闭后草稿与打开前逐项一致，一次原生 Undo 恢复原备注和空草稿。无保存、新修订0；183份应用资源身份再次匹配，三类错误均为空，截图 `print-draft-notes.png` 已目视确认。此项补充证明打印读取未保存备注，而非只用干净来源文件冒称当前草稿；没有新增保存或历史操作。日志 `slides-print-draft-browser-20261113.log`，摘要 `unsavedDraftNotes: true`。

后续在旧 `static-lifecycle` 上复现了独立3D路径的Three分块初始化错误。新的依赖有序分组已通过真实GLB→PNG→草稿专项，见[Three运行时专项](NATIVE_THREE_RUNTIME_ACCEPTANCE_20261113.md)。两者是不同冻结资源；本打印记录不覆盖其它运行路径，也不把新资源的通过结论追溯到旧构建。
