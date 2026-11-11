# PDF 静态文字插入专项验收

> 2026-11-11 后续扩展：本文保留早期单行/左对齐验收记录；当前字体、粗斜体、多行、居中/右对齐及原位样式替换以 [文字样式与多行对齐验收](NATIVE_PDF_TEXT_STYLE_ACCEPTANCE.md) 为准。

2026-11-11；固定来源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本项为有边界的首批实现，不代表完整 PDF 对齐或生产部署。

## 实现与范围

- 开始 Ribbon 的“插入文字”进入内容、字号、颜色、左对齐配置，随后点击页面落点；以 PDF.js 逆视口转换得到来源页首行基线。取消、Escape、失效草稿、只读、保存中和来源能力限制均有守卫；支持撤销/重做。
- 使用固定源 `applySaveRequest(textInserts)` / `applyTextInserts` 写入 PDFium 文字对象，可提取检索，并非便签、Stamp 或栅格图片。来源 SHA256、pageId 与基线绑定；旋转由不可变来源派生。
- 当前每次仅一项插入、单行左对齐、1–1000 字符、字号 6–72、RGB；禁止控制/格式字符及换行。不提供字体选择、粗斜体、居中/右对齐、多行或与其他编辑混合。来源含表单、批注、保护、签名结构、非默认 UserUnit 或非正交旋转时不开放。字符可用性取决于实际写入字体，须核对预览。
- 复用 `pdf_text_enabled`，预览、预览 PDF 和保存均检查开关。保存强制匹配实际预览摘要与用户确认；开关未在生产开启。
- 输出回读核对所有原文字及位置、新文字唯一性、字号与几何；实际 PDF 溢出或回读失败保留已生成字节并返回告警。写入资源失败则保留来源字节。前后端插入告警明确要求以实际 PDF 为准，不能误称复核失败为“未执行，保留原文”。

## 真实浏览器与独立回读

`/tmp/pdf-static-text-browser-20261111-final01/summary.json`：`ok=true`。使用统一冻结构建、实际 PDF.js、真实 grant/cookie/CSRF、已打包 PDF 引擎、发布、签发下载及新授权重开；文档/授权/产物仓储为作用域内存 fixture，没有 HTTP 或 PDF 字节替身，不代表生产数据库/完整应用镜像验收。

浏览器配置 `Report inserted 123`、18pt、`#336699`，点击转换为来源基线 `[60,200]`；撤销/重做后草稿不变。实际预览回执 applied `[0]`、skipped `[]`，勾选确认后保存修订 4 → 5，提交摘要与预览相同。下载身份、来源不变、重开修订及 textLayer 检索通过；独立 pypdf 确认三页原文和 MediaBox/CropBox 保留，新增文字可提取，无批注/表单。root 目视检查配置后的实际预览及重开截图。

来源 SHA256 `2db8035ded6c8ba2739a377cf27bea37c29952676bceab7572b67ea44832b6a0`；输出 SHA256 `f27849ea3f683fdd117543b0564426f0075c638f5c0dd8141312baac3db9bd73`。manifest SHA256 `000be7f5abfd4d62859a6786cd6525349a30f1cfe3b61744ffc82d74de9302ae`；加载 JS 均与磁盘 SHA 匹配，page/console/HTTP 错误均为空。证据目录含 configuration、preview、reopened 截图及来源/下载 PDF。

## 定向验证

- 引擎 7 项通过：`/tmp/pdf-static-text-final-20261111.log`；独立 pypdf 验证有效 `Tm × CTM` 基线矩阵、字号和颜色，覆盖四旋转、伪造身份、混合草稿、来源结构、写入资源失败及输出溢出。
- 前端静态文字模块/宿主 24 项通过：`/tmp/pdf-static-text-guards-green.log`。最终文案新增回归先 RED 后 GREEN；受影响宿主与裁切对话框 14 项通过：`/tmp/pdf-static-crop-warning-green.log`。这些是重叠专项结果，不累加作独立测试数。
- 服务与必须保持的发布非阻断合同共 78 passed、2 deselected：`/tmp/pdf-static-text-service-contracts-20261111.log`；默认排除的两个集成参数沿用上一批 1 passed/1 原有 skipped 的证据，未重复运行。
- 新故障点登记 `test_http_publication_lineage.py::test_static_text_postwrite_review_warning_keeps_verified_http_download`：真实写入后注入复核失败，validation=false，但 HTTP 下载保留实际新增文字及正确 SHA。文案断言先 RED 后 GREEN，最终只重跑该受影响测试，1 passed：`/tmp/pdf-static-warning-http-green.log`。没有新增签发函数。
- PDF 定向 TypeScript 与 Vite 构建通过；桥接重新 bundle 且 LOCAL-SHA256 四个静态文字相关记录匹配；budget contract 通过。日志 `/tmp/pdf-static-crop-tsc-20261111.log`、`/tmp/pdf-static-crop-vite-20261111.log`、`/tmp/pdf-static-text-bundle-20261111.log`、`/tmp/pdf-static-crop-budget-contract-20261111.log`。

完整 `pnpm run build` 在其他会话修改的 docx-bookmarks.ts/workbook-main.ts 类型错误处失败（`/tmp/pdf-static-crop-build-20261111.log`），不能宣称全项目构建成功。本轮首次统一产物的 workbook-main 为 251.8 KiB，超过既有 250 KiB budget；PDF chunk `lazy-pdf-main-DhY2NLc1.js` 为 202.2 KiB。没有放宽预算、修改无关模块、重复完整测试、提交或部署。


## 共享构建变化后的补验

首轮验收完成后，其他会话重建了共享 static 目录。因资源身份变化而补验，并非无变更重复完整测试。文字 `/tmp/pdf-static-text-browser-20261111-final02/summary.json`、裁切 `/tmp/pdf-crop-handles-final-preview02/summary.json` 均 ok=true；实际加载资源匹配且运行期间 manifest 稳定，SHA256 为 `6a34663ff0c246aec181d1aa7dfb985be956a6e33d7a8c3d79af476a4595c9de`。两项沿用原先明确的真实服务/替身边界，错误列表均为空；独立 pypdf、实际预览、下载和文字重开检查再次通过。root 读取两份 summary 并目视最新文字重开截图。只读独立复核未发现新增严重问题。

补验文字来源 SHA256 `748315b850b6bc48e3e5579d4fbcd372cba9623c06311efe8b16567d487b5247`，下载 SHA256 `c5997d5b68c5115775d2a63896334ba0b68bcb7b67737e20992ab66dfcfbd34e`。
