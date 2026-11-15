# PDF 非 OCR 交付批次验收

验收日期：2026-11-11。此文档记录 PNG/JPEG 图片 ZIP、保护 PDF、PDF→PPTX、外部 PDF 插入/替换的真实 UI/HTTP/下载闭环；不包含 OCR。

## 实际结果

- 浏览器验收通过：/tmp/pdf-delivery-batch-browser-20261111-root01/summary.json，ok=true。
- root 执行日志：/tmp/pdf-delivery-batch-browser-root01-20261111.log。
- 使用 Playwright bundled Chromium 140.0.7339.16、真实 PDF.js、grant/cookie/CSRF、原生路由、实际转换/编辑引擎、发布和下载；仅 scope 内仓储为内存实现，无 HTTP 替身。
- 冻结 manifest SHA-256：5a02fa3eca66d4a4392813c5f6f5db287c77fd527ad6814019c475df2c4f7aa8。
- 23 个 .js/.mjs 网络响应逐个与磁盘 SHA 对齐（含 PDF.js worker），manifest 前后不变；pageErrors、consoleErrors、httpErrors 均为空。
- 后置只读回查再次核对当前 manifest、23 个资源、4 份持久下载文件身份及原 PDF 身份，均匹配 summary。
- 原 PDF SHA-256：9ebe0152b5fb9d1fe9af1c9cd85727b33e36f998c60423393f7fae7e3ce9b6d7。运行后来源保持不变。

## PNG / JPEG 图片 ZIP

- UI 分别点击 home.convert.exportImagesPng 和 home.convert.exportImagesJpg，选择原页码 3,1、72 DPI，真实 POST export-images。
- 校验 X-Native-Export-Sha256、X-Native-Export-Size、X-Native-Source-Sha256 与真实响应；通过 UI 的 Blob 下载链接取得 ZIP，文件与 HTTP 响应 SHA 相同。
- 独立 ZipFile/PIL 回读 manifest.json、顺序 [3,1]、格式、DPI、每图 SHA/size、PNG/JPEG 编码、300×400 像素及非纯白内容。
- 证据：export-png.zip、export-jpeg.zip、对应 export-*-receipt.json、verify-png.json、verify-jpeg.json。
- 这是会话内 ZIP 下载，关闭对话框后 Blob 链接失效，不宣称持久化图片下载授权。

## 密码保护 PDF

- UI annotate.protection.protect，经真实 protect-pdf 和授权下载取得 protected.pdf。
- 独立 pypdf 检查真实加密、AES-256 revision 6、打开密码可解密、复制权限关闭，以及全部三页正文保留。
- 密码输入提交后清空；实际 localStorage 不含打开密码或所有者密码，结果回执不含密码。
- 保护文件是独立下载，不登记在线编辑修订。validation.ok=false，native_protected_pdf_download_only 告警与下载链接同时保留；不得改称业务/版式验收通过。
- 证据：protected.pdf、verify-protection.json、protected.png。

## PDF → PPTX

- UI home.convert.toPowerPoint，真实 convert-office 创建独立派生文档并发布 converted.pptx；来源 PDF 身份仍指向原文档修订 4，派生登记成功。
- 独立 python-pptx 回读 3 张幻灯片，每页存在可编辑文字，分别包含 source page one / two / three；不是将整个文字页冒称可编辑的纯图片方案。
- validation.ok=false，保留 native_conversion_review_pending / native_conversion_warning 和实际 PPTX 下载；此验收不宣称复杂版式、字体或全部内容保真。
- 证据：converted.pptx、verify-pptx.json、converted.png。

## 外部 PDF 插入 / 替换

- UI page.insertPdf 上传真实两页外部 PDF，在原第 1 页后插入：修订 4→5，输出 5 页。
- 通过新 grant 重开修订 5 后，UI page.replace 替换第 1 页为外部两页：修订 5→6，输出 6 页。
- 每次校验父 SHA、parentRevision/revision、真实下载 SHA/size；pypdf 独立验证完整页序、正文和页框，再经新 grant 重开核对新修订源 SHA。
- 修订 5 页序：source one、external one、external two、source two、source three。
- 修订 6 页序：external one、external two、external one、external two、source two、source three。
- 证据：external-insert.pdf、external-replace.pdf、verify-insert.json、verify-replace.json、两张 *-reopened.png。原修订未覆盖。

## 目视与复现

已目视 export-png.png、protected.png、converted.png、external-insert-reopened.png、external-replace-reopened.png：下载链接与告警可见，对话框内容未裁断，新修订页数/缩略图/正文一致。

脚本：frontend/smoke/pdf-delivery-batch-server.py、pdf-delivery-batch-smoke.mjs。端口 4303。node --check、Python 服务和嵌入独立 verifier 的 py_compile 已通过。启动需要项目 .venv、已冻结 static 产物、实际引擎运行时及 Playwright bundled Chromium。代理隔离 shell 初始化挂起，因此本次由 root 普通 shell 执行；没有提权或伪造 HTTP 回执。
