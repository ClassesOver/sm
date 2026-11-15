# PDF 裁切控制柄增量

2026-11-11；固定来源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，本机只读核实 HEAD。
来源 `apps/pdf/src/renderer/ImageDialogs.tsx:293` 的 CropDialog 使用八个控制柄、框内平移和 16 CSS px 的最小预览边长；`App.tsx:11888` 将其用于裁切页面。

本增量将独立 `pdf-crop-canvas.ts` 接到现有 `pdf-main.ts` 裁切对话框。
截图使用真实 PDF.js 页面的当前 CropBox 和旋转，控制柄只更新对话框四个显示方向百分比输入。
应用沿用既有 `pdfCropFromMargins` 的逆 viewport，再由 `cropPdfPage` 或 `cropAllPdfPages` 生成一批草稿操作，不改发布链或覆盖来源。
截图不包含其他未保存标注等变化，界面明确要求以“校验当前修改”核对这些变化。

异步截图绑定打开时文档、完整草稿快照、来源页身份和对话框 generation；关闭、取消或销毁取消渲染和控制柄监听。
加载期间草稿变化时丢弃迟到截图并显示重新选择原因；应用也复核打开时快照。
只读、保存、预览、打印和关闭草稿状态均保留现有守卫。

定向验证：

- `pdf-crop-canvas.test.ts`：17 项通过，覆盖八柄各自边、平移和边界、16px 最小边、数值同步、取消/禁用/销毁及异指针。
- `pdf-crop-dialog.test.ts`：5 项先 RED 后 GREEN。真实挂载 `createPdfEditorView`，从裁切按钮进入对话框，拖柄后修改数值并应用，核对未旋转 PDF 坐标和单步 Undo；其余覆盖关闭/草稿变化/销毁时迟到截图及强制保存中打开与过期应用拒绝。
- 集成测试的 PDF.js 文档和渲染边界明确使用替身，jsdom 不验证真实 canvas 像素、浏览器布局或 PDF 输出文件；不能把本层通过等同实际浏览器与下载验收。
- 复核新增滚动、滚轮导致拖动坐标失效，以及草稿变化后截图拒绝仍停留加载态的回归；新增 3 项先 RED 后 GREEN，仅运行对应过滤用例（其余 22 项跳过），未重复完整测试。
- 集成完成后 `pnpm exec tsc --noEmit` 通过；新增 smoke 脚本 `node --check` 通过。

`frontend/smoke/pdf-crop-handles-smoke.mjs` 从 frontend 目录运行：`REPORT_EDITOR_CHROMIUM_EXECUTABLE=/home/junge/.cache/ms-playwright/chromium-1187/chrome-linux/chrome PDF_CROP_HANDLES_EVIDENCE_DIR=/tmp/pdf-crop-handles-smoke node smoke/pdf-crop-handles-smoke.mjs`。脚本用当前构建与真实 PDF.js 截图，覆盖非零 CropBox、UserUnit=2、0/90/180/270 度页面拖动和数值同步，最后一页使用窄视口；保存下载后由独立 pypdf 检查四页 CropBox、正文、旋转、表单值保留，并记录实际资源哈希和截图。认证与修订 HTTP 路由明确使用替身，PDF 写回使用真实打包引擎。

## 实际浏览器尝试：未通过

证据 `/tmp/pdf-crop-handles-final`：0°页拖动应用成功，90°页真实截图及八柄显示正常，但八步拖动仅一步生效。给 smoke 增加滚动后两个 rAF 同步没有解决；`/tmp/pdf-crop-handles-final-settled` 曾因 Chromium `writev: No space left on device` 在创建页面前失败。

磁盘恢复后 `/tmp/pdf-crop-handles-final-resume02` 稳定复现同一失败。`/tmp/pdf-crop-handles-final-resume03/failure.json` 的事件诊断证明：90°页首次移动得到 1.25% / 2.5%，随后背景 `DIV.pdf-document-pages` 平滑滚动触发 document 捕获 scroll；裁切 stage 始终为 `x=421,y=222.8125,width=438,height=362.1875`，活动页身份也保持不变。全局无条件取消误伤了坐标没有变化的裁切拖动，确认为产品问题。

最小修复记录拖动初始 stage 的 left/top/width/height，scroll 只在这些实际屏幕几何变化时取消；wheel、resize、blur、pointercancel 等原守卫保持。新增背景兄弟滚动继续拖动回归先 RED（冻结在 1.25% / 2%），修复后与真实 scroll 位移及宽高变化共 4 项 GREEN，18 项跳过，未重复完整测试。

## 修复后浏览器证据：专项通过

root 统一构建后执行 `/tmp/pdf-crop-handles-final-resume04`，`summary.json` 为 `ok=true`，Chromium `140.0.7339.16`。实际 manifest SHA256 为 `0a7bb15fd8019797b68833ba6d60d20beb0355163224ee0ebfa27e042bb4c1b8`；实际加载的 `lazy-pdf-main-DHCSOcAX.js` SHA256 为 `3edeb5ea239f0e003322c829e2981f549170e918857c31289f59a29e1d4649a8`，全部 22 个 JS 响应均与磁盘字节身份一致；未沿用之前构建的哈希。

四页分别为 0/90/180/270 度、非零初始 CropBox `[10,20,390,480]`、UserUnit=2。真实 PDF.js canvas 均有非空像素，八柄存在；NW 连续拖动均得到左 10%、上 20%，再数值输入右 30%、下 10%。诊断仍记录到 39 次背景 `pdf-document-pages` 滚动，拖动均完成，证明没有靠等待平滑滚动结束避开原问题。最后一页视口为 520×740；目视四张 `crop-*.png` 的保留框、八柄、灰色遮罩和旋转方向正确，长对话框可内部滚动，Apply 在脚本中实际滚动到位并点击成功。

实际保存、下载和独立 pypdf 回读通过；四页 CropBox 分别为 `[48,66,276,388]`、`[86,66,352,342]`、`[124,112,352,434]`、`[48,158,314,434]`，与独立按旋转计算的预期一致。正文流、提取文字、MediaBox、Rotate、UserUnit 和表单值 `original` 均保留。来源 SHA256 `e85c38042f0274be2ec3775807feb483346df321bbda9ace9436f27daeafcd46`，输出 SHA256 `72f5ac1d0467929b6a79b3d5245c5831ee1d949d66b511baf6f87df68b60c90b`；浏览器错误列表为空。证据目录保留来源/下载 PDF、四张截图、资源身份和请求状态。

边界：认证、修订和保存 HTTP 路由为显式替身，PDF 写回使用真实打包引擎；这不是生产 HTTP/认证或整应用镜像验收。此脚本没有覆盖全部页批量裁切、关闭/重开及迟到截图真实浏览器场景；相关部分只有既有单元/集成证据。当时纯裁切“校验当前修改”仍未加载实际写回 PDF 预览，后续补齐见下。未开启功能开关或宣称完整 PDF 对齐。

## 纯裁切实际预览补齐（同日）

`pdf-main.ts` 将 cropPage 纳入实际 PDF 预览白名单；宿主回归先 RED 后 GREEN，核验真实预览加载、返回原稿且裁切草稿不丢失。显示尺寸沿用实际预览 PDF 的 viewport，避免重复裁切/旋转。受影响对话框与静态文字宿主共 14 项通过，日志 `/tmp/pdf-static-crop-warning-green.log`。

冻结构建后 `/tmp/pdf-crop-handles-final-preview01/summary.json` 为 `ok=true`。四旋转、非零 CropBox、UserUnit=2 和窄视口拖动再次通过；实际 preview.pdf 由真实打包引擎生成，响应摘要一致。100% 预览四页 canvas/holder 尺寸依次为 `[456,644]`、`[552,532]`、`[456,644]`、`[552,532]`；实际预览无重复草稿 overlay，编辑入口锁定；返回原稿后 operations 逐字节相同，来源未变，最后保存下载字节与实际预览完全相同。

独立 pypdf 确认四页 CropBox 为上文相同预期，正文流、提取文字、MediaBox、Rotate、UserUnit 和表单值保留。来源 SHA256 `ef50d5f47ca16cb79047f098a20642f0c9c4310c4fb690889784bcff173c31db`；预览/下载 SHA256 均为 `c82bdf7a8eeaa4b2687e1bcf99be828f8d0fc16a71ea535090e3748d102ed4af`。manifest SHA256 `000be7f5abfd4d62859a6786cd6525349a30f1cfe3b61744ffc82d74de9302ae`；JS 与磁盘匹配，errors=[]。root 目视检查 0°和90°实际预览截图，0°页表单被裁切边界截断符合样本，90°保留区域无可见正文。

仍使用明确的认证/修订/保存 HTTP 替身，实际 PDF.js、桥接引擎与下载字节真实；没有宣称生产鉴权、全部页批量、重开或整镜像验收通过。构建与预算限制见 NATIVE_PDF_STATIC_TEXT_ACCEPTANCE.md。


## 共享构建变化后的补验

首轮验收完成后，其他会话重建了共享 static 目录。因资源身份变化而补验，并非无变更重复完整测试。文字 `/tmp/pdf-static-text-browser-20261111-final02/summary.json`、裁切 `/tmp/pdf-crop-handles-final-preview02/summary.json` 均 ok=true；实际加载资源匹配且运行期间 manifest 稳定，SHA256 为 `6a34663ff0c246aec181d1aa7dfb985be956a6e33d7a8c3d79af476a4595c9de`。两项沿用原先明确的真实服务/替身边界，错误列表均为空；独立 pypdf、实际预览、下载和文字重开检查再次通过。root 读取两份 summary 并目视最新文字重开截图。只读独立复核未发现新增严重问题。

补验裁切来源 SHA256 `0c5603b4ff00191669e643244526948881faf892931dfcee8b63569c10219c14`，预览/下载 SHA256 `eec9fd1506b3f575068fba708cfd6c0adbca8f253c0f823649bbed257c86a8eb`，仍满足预览字节与保存字节一致。
