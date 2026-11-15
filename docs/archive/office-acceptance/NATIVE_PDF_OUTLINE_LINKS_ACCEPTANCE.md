# PDF 来源回调复核与外部目录链接专项（2026-11-13）

固定来源：`/home/junge/pros/genoffice-source-full`，HEAD
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文件只记录本批 PDF
源码检查和定向行为证据，不用既有功能清单的“已完成”替代实际行为。
证据目录：`/tmp/office-pdf-source-gaps-20261113`。

## 本批确认并修复的缺口

来源 `apps/pdf/src/renderer/OutlinePanel.tsx` 的 `OutlinePanel.onGo`
优先检查 `node.url`，通过用户点击打开外部链接，否则交给
`onGoToDest`；`Item` 递归显示目录子节点。`App.tsx` 的
`viewNavGroup` 和目录侧栏将文件自己的目录传入该组件。

本地原 `pdf-view-ribbon.ts:resolvePdfOutline` 只处理 `dest`，将实际
PDF 的 URI 书签丢掉；`pdf-main.ts` 原渲染循环还要求每条记录都对应
来源页面，外链无法进入侧栏。真实双页 PDF 的目录解析复现了三条
外链丢失，未以字符串搜索代替缺口实证。

本批修改：

- `ResolvedPdfOutlineItem` 区分来源页目标与外部 URL；保留目录遍历顺序、
  嵌套深度及现有内部页解析。
- 外部 URL 采用与现有 `pdf-saved-links.ts` 一致的 http/https/mailto
  协议范围；无效地址不创建可点击入口，不降级执行其内部 `dest`。
- `appendPdfOutlineLinks` 创建真正的 `<a target="_blank"
  rel="noopener noreferrer">`。浏览器由实际用户激活打开，未在目录加载或
  重绘时调用 `window.open`。内部目录仍是来源 `pageId` 绑定的按钮，已删除
  页面仍过滤；原目录长文本滚动逻辑原样迁入 helper。
- `pdf-main.ts` 只将原目录逐条渲染循环交给该 PDF 专用 helper，未改
  保存、下载、签发、发布门禁、后端授权或其他格式。

## 本批来源回调/读写映射

这些是本批实际核读的路径，不能充当 PDF 全应用动态状态的穷尽分母。

| 固定源真实回调/操作 | 当前本地落点 | 复核结论 |
| --- | --- | --- |
| `OutlinePanel.onGo` → 外部 URI / `onGoToDest` | `resolvePdfOutline` → `appendPdfOutlineLinks` → `jumpToPageForIdentity` | 外部 URI 为本批修复；内部跳转、嵌套顺序定向验证 |
| `App.startBookmarkEdit/finishBookmarkEdit/addBookmarkForCurrentPage/renameBookmarkAt/deleteBookmarkAt` → 保存请求 `outline` → `main/save-pdf.ts:applyOutline` | `pdf-main.ts` 只有只读目录；`pdf-operations.ts` 无目录编辑操作 | 新增/重命名/删除书签及保存尚未接入，外链阅读修复不等于书签编辑 |
| `App` 文档加载时 `getOutline` 为空后 `buildHeadingOutline` | 本地仅 `document.getOutline()`，未接标题推导 | 无嵌入目录 PDF 的标题目录生成仍缺 |
| `OutlinePanel.Item` 的 `bold/italic`、`MAX_OUTLINE_DEPTH` | 本地目录模型未读粗斜体；resolver 递归未对齐来源深度上限 | 目录样式和深度防护仍待专项；本批不扩大修复范围 |
| `App.runCompare` → `preload.compareReadPdf/compareReadOpen` → 比较及交换两侧 | `pdf-view-ribbon.ts` 的 `view.navigation.compare` 明确 disabled | 第二来源授权、比较计算/视图仍未接入 |
| `App.splitPdfToFolder/mergePdf` → `preload.splitPdf/mergePdf` | `pdf-page-ribbon.ts` 对 `page.splitPdf/page.mergePdf` 明确 disabled | 文件级拆分/合并仍缺；现有“合并页面/拆分页面”是不同能力，不能算替代 |
| `App.rotateSelected` → `transformExisting(...quarterTurns)` / PNG 像素旋转 | `pdf-existing-image.ts` 仅移动/缩放/替换及 flip/crop/opacity | 图像 90° 旋转未接入；三种既有像素编辑不能重复算成全缺 |
| `App.openImageDialog('cutout')` → `removeBackground` | 同上，无 cutout 类型/UI | 去背景仍缺；未新增 Plotly 或其它无关功能 |
| `preload.listDigitalSignatures/pickCertificate/inspectCertificate/signWithCertificate` | `pdf-main.ts` 证书签名、数字签名面板明确 disabled | 证书/数字验证链仍未接入；本批未探测或持有证书/私钥 |
| `preload.listSavedSignatures/addSavedSignature/removeSavedSignature` | 本地可视签名对话框只负责本次绘制/键入和放置 | 已保存签名库复用仍缺；可视签名不等同证书签名 |
| `App` 转换动态菜单 → `convertTo(docx/xlsx/pptx/md/html)`、PNG/JPG 导出 | `pdf-convert-office.ts`、`pdf-export-text*.ts`、`pdf-image-export.ts` 和已有服务 | 入口已存在，不能重复报为缺失；完整转换保真须沿用各专项边界，本批未重验所有转换 |
| `App.arrangeSelected` 与字段创建/删除动态状态 | `pdf-form-create.ts`、`pdf-form-design.ts`、`pdf-main.ts` 的安全子集 | 已有字段增删/排列不能全部报缺；签名字段、自动检测和完整设计预览仍在本地 disabled |
| `App.runAiPreset`、来源 AI tool services | `native-pdf-assistant.ts` → `native_pdf_ai.py` 的 Agno `Agent`，及 review/form AI 独立链 | Agno 入口已有，不应重复造框架；本批未运行真实 provider，不声称完整 AI 编辑/生成等价 |
| `preload.readFile/save/onCloseSaveRequest/onSaveAsRequest/onPrintRequest` | 本地 context/file API、`NativeDraft` 与保存新修订、`renderPdfPrintHost` | Web 修订/下载并非桌面任意路径写回；本批只读导航未触碰发布/导出/签发契约 |

## RED/GREEN 与真实浏览器

1. `red.log`：新增外链保留/优先级契约后，两例按预期失败。
2. `red-actual-pdf.log`：pypdf 生成的真实 PDF 经 PDF.js 解析，来源中的
   Website/Contact/HTTP 三个 URI 明确存在，而旧 resolver 的结果只有
   First page/Second page；DOM helper 缺失也失败。共四失败、一通过。
3. `green.log`：上述两文件五个专项用例通过。实际 PDF 解析未 mock。
4. `regression.log`：现有 `pdf-ribbon.test.ts` 11 例和
   `pdf-saved-links-host.test.ts` 20 例通过。合计 36 个不同定向契约，
   未运行完整测试套件。
5. `browser/evidence.json`：Vite 开发宿主、真实 Chromium，实际双页 PDF
   2196 bytes，SHA256
   `2657c89ccdf6d8b3eee480439fef10b68886e85b7ba4448795408892ebf1919e`。
   五条目录、嵌套缩进、两条内部页目标和三条 URI 阅读入口保留；实际点击
   Website、实际键盘 Enter 激活 HTTP 均打开受控新页，`window.opener`
   为 null；Second page 跳转到来源第 2 页且 `aria-current=page` 只落在
   内部条目；无草稿编辑操作；`errors=[]`。
6. 1440×900 和 390×600 截图已人工查看，目录文字/缩进和点击区域位于
   可见侧栏内。短屏图只证明目录区域，本批不声称整个 Ribbon 同时展开。
7. 补充类型验证发现 `a | button` 联合类型让 `keydown` 推断为 `Event`。
   严格单模块 tsc 先复现六项 TS2339（`type-red.log`），仅将公共控件声明
   为 `HTMLElement` 后 `type-green.log` 退出 0，事件保持原生
   `KeyboardEvent` 语义；两文件五例再次定向通过（`type-fix-tests.log`），
   不重复计为新增用例。
8. 最终统一冻结构建已在 `http://127.0.0.1:5191` 通过本专项真实浏览器
   验证，`browser-built-final.log` 退出 0；证据为
   `browser-built-final/evidence.json` 和两张同名截图。构建目录
   `/tmp/office-four-format-source-increment-20261113/static`，manifest
   SHA256 `8d4ca1394b78848aed62e1dbfc80add3b9b629cac8b91683c5d0976ee5cef2b4`。
   smoke 实际响应逐资源核对 50 个 JS/CSS 资源（40 JS、1 MJS worker、
   9 CSS）的内容 SHA256 与磁盘冻结文件一致，全部 HTTP 200。
   PDF main 为 `assets/lazy-pdf-main-Ckj9WSdl.js`，245401 bytes，SHA256
   `247adb2e66882ef88f0dd8c115767104cebaf17ff73de0a0186a3d929acde332`。
   五个目录条目、真实 click/Enter 外链打开及 opener=null、内部来源第 2 页
   导航/当前项、无草稿编辑在最终构建再次通过，`errors=[]`；1440 和 390
   截图已重新目视，目录区域没有文字/点击区域溢出。冻结构建测试未使用
   开发模块替代产品 bundle，也未重新运行完整测试套件。

最新冻结构建因 XLSX 菜单 SVG 尺寸调整而更新，manifest 为
`9bd8828c7813c0958cb9cde714449fbaa1ceb1c102e6b4a8eba82eaadf84707c`。
本批保留前述 `browser-built-final` 完整交互证据，未覆盖原回执/截图，也未
重复完整交互矩阵。旧完整 static 从
`/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final/static`
读取；`browser-built-final-9bd/comparison.json` 对上一批实际加载的 50 个
JS/CSS 资源逐个比较：46 个原字节不变、4 个仅已配对资源的 import/hash
文件名变化，规范化后无功能内容变化、无未匹配资源。比较只替换明确配对
文件名，不把同名的不同 index chunk 随意合并。

新构建在 5191 上执行最小 PDF 目录入口与实际资源身份检查：
`browser-built-final-9bd/minimal-entry.log` 退出 0，目录入口可用、五条目录
和 mailto 阅读入口正确、`errors=[]`；新实际加载 50 个资源的 SHA256
全部匹配新冻结文件，并与归一比较的预期资源闭包完全相同，见
`minimal-evidence.json` 和 `reconciliation.json`。新 PDF main 为
`assets/lazy-pdf-main-CsZoS79g.js`，245401 bytes，SHA256
`2be4cbc3a888ef98686a76457d056215813ec3f085538e9d3625fd608166f83f`。
这次最小检查没有重跑外链 popup 和两视口截图；对应交互证据沿用
8d4 批，成立范围由实际资源无功能差异比较限定。首次最小脚本执行由于
从仓库根目录启动而无法解析 frontend 的 playwright 包，改为 frontend
工作目录后通过；失败日志保留为 `minimal-entry-resolution-failure.log`，
未为此修改产品代码。

XLSX 原生 pointerup 双击合成隔离随后触发再次冻结，最新 manifest 为
`6bb0f8ab4f0d66993c135a6174e1e1437dcda38ee61c0c6efa850c82f4b96b09`。
复用相同确定资源配对方法，`browser-built-final-6bb/comparison.json`
再次确认原 50 资源中 46 个字节不变、4 个纯引用/hash 变化、0 个功能内容
变化、0 个未匹配；新实际加载 50 资源的 SHA 与新磁盘冻结文件及预期闭包
一致。最小目录入口检查退出 0，五条目录和 mailto 入口正确、按钮可用、
`errors=[]`，见 `minimal-evidence.json`、`reconciliation.json` 和
`minimal-entry.log`。新 PDF main 为 `assets/lazy-pdf-main-Cc2G_Qf4.js`，
245401 bytes，SHA256
`8f0d6f4d42600e582110e55409bf9364b24f4241a1652e2e7b56be1c2067764b`。
8d4 完整交互/截图和 9bd 最小核对目录均保持原样；未重跑完整交互或测试。

XLSX 图表历史分流修复后的最终冻结 manifest 为
`0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`。
本次另存 `browser-built-final-0015`，保留 8d4、9bd、6bb 原证据，未改写
历史回执。`comparison.json` 继续直接对照 8d4 完整交互实际加载的 50 个资源：
46 个原字节相同，4 个仅明确配对资源的引用文件名变化，0 个功能内容变化、
0 个未匹配。比较仍只替换唯一确定配对的文件名，其余字节不变；该结论限于
PDF 实际加载闭包，不外推为整个应用无变化。

新冻结构建在 5191 的最小真实浏览器入口检查退出 0，目录按钮可用，五条
目录和 mailto 入口正确，`errors=[]`。实际 50 个 JS/MJS/CSS 响应的 SHA256
全部匹配当前冻结磁盘文件，且集合及身份与比较预期完全一致；结束后再次
核对 manifest 未变化，见 `minimal-entry.log`、`minimal-evidence.json` 和
`reconciliation.json`。当前 PDF main 为
`assets/lazy-pdf-main-CWraN-bG.js`，245401 bytes，SHA256
`5c7836215365519f870f0a3f7658f5e3def9459b0ed459da6a6d74cb23be30a2`。
本次只续验入口和资源身份，没有重跑外链 popup、完整交互矩阵、双视口
截图或测试集；对应完整交互/视觉结论仍属于 8d4，并由上述实际依赖身份
连续性限定复用范围。

浏览器初次执行有两次夹具问题：默认 `/usr/bin/chromium` 不存在，改用项目
已有 Playwright 安装；随后将既有内部目录点击误期望为页面标签抢焦点，
实际函数保留目录按钮焦点，断言改为现有行为。未为通过夹具而修改产品焦点。
这些失败记录摘要在证据目录，不计为产品缺陷修复。

## 可复用验证命令与边界

```bash
cd smart_reporting/report_editor/frontend
./node_modules/.bin/vitest run src/pdf-view-ribbon.test.ts src/pdf-outline-source.test.ts
PDF_OUTLINE_SMOKE_BASE=http://127.0.0.1:5191 \
PDF_OUTLINE_SMOKE_OUTPUT=/tmp/office-pdf-source-gaps-20261113/browser-built-final \
PDF_OUTLINE_SMOKE_STATIC_DIR=/tmp/office-four-format-source-increment-20261113/static \
PDF_OUTLINE_SMOKE_MANIFEST_SHA256=8d4ca1394b78848aed62e1dbfc80add3b9b629cac8b91683c5d0976ee5cef2b4 \
node smoke/pdf-outline-links-smoke.mjs
```

脚本只要求指定宿主已提供 `/reports/v1/editor/assets/native.html`。其 context
和文件 API 是显式路由夹具；实际目录由 PDF.js 读取真实文件，外链目标由
Playwright 路由控制，未对公网发送请求。它不证明生产授权、数据库、邮件
客户端启动、系统读屏、系统输入法、桌面 Office 或已有 PDF 保存保真。

本批不构建/覆盖共享 static，不改 source/hash/统一审计或总索引，不提交、
推送或部署。统一冻结构建由主任务产出，本专项已完成该冻结构建的 built-host 核验；
它不等于生产部署通过。四格式整体目标仍未完成。
