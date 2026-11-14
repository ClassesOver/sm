# PDF 链接窗口 PC 验收

运行对象是实际前端构建、PDF.js、授权/CSRF/API、打包 PDF 引擎、发布与 HTTP 下载。修订仓储使用已有内存夹具，不代表生产数据库或桌面 Acrobat 实机验收。

构建时保留项目 Vite 配置与分包规则，将输出和缓存指向 `/dev/shm`。隔离构建的 `pdfjs/{cmaps,standard_fonts,wasm}` 必须来自当前 `node_modules/pdfjs-dist`，不能复用缺少新版本 wasm 的旧 static 目录。不要覆盖项目 static 或部署。

```bash
TMPDIR=/dev/shm \
PDF_SMOKE_STATIC_DIRECTORY=/dev/shm/your-frozen-build \
PDF_LINK_OUTPUT=/dev/shm/your-new-link-evidence \
PDF_EXPECTED_MANIFEST_SHA256=your_manifest_sha256 \
node smoke/office-pdf-link-smoke.mjs
```

证据目录必须不存在；重用会在启动服务、浏览器和保存前失败。`PDF_LINK_BASELINE=1` 仅记录初始五视口并退出，不保存，也不要求旧构建满足新布局断言。`PDF_LINK_PORT` 可指定本地端口。基线原始夹具与最终富内容夹具不同，布局对照只代表窗口结构和尺寸，不代表文件差异对照。

定向单元测试：

```bash
TMPDIR=/dev/shm node_modules/.bin/vitest run src/pdf-link-desktop.test.ts src/pdf-object-host.test.ts src/pdf-operations.test.ts
```

检查初始、非法网址、超长网址、越界页码和重开五种状态，每种覆盖 1440×900、768×720、320×640、640×360、390×320。记录控件尺寸、字体、Tab/Shift+Tab、焦点环、圆角内五点命中、标题/操作区边界、截图与不变的输入/草稿。取消、标题关闭和 Escape 真实操作不入草稿；网页、邮件、页内链接分别写入一个操作，验证撤销、重做和刷新。链接不属于强制预览确认操作，实际预览后不勾选隐藏的确认框。

一次保存 revision 4→5，校验验收告警未阻断下载、下载 SHA/长度及重开原文件接口字节一致。该批运行时宿主尚无已保存链接的点击层，因此该批不声称在编辑器内点击过链接跳转。后续点击层与交互证据见 `office-pdf-saved-links-smoke.md`，两批证据不混用。

独立检查在服务退出后执行，不再保存：

```bash
TMPDIR=/dev/shm .venv/bin/python smart_reporting/report_editor/frontend/smoke/office-pdf-link-verify.py /dev/shm/your-new-link-evidence
TMPDIR=/dev/shm .venv/bin/python smart_reporting/report_editor/frontend/smoke/office-pdf-link-verifier-faults.py /dev/shm/your-new-link-evidence
```

以上 Python 命令从仓库根目录执行。检查三个链接的 URI/页索引/矩形、原有链接/便签、正文流、资源、图像、页框、目录、用户元数据以及全部页面像素相同。PDF 头由原序列化器从 1.3 写成 1.7，单独记录，不将其当成用户元数据。11 种损坏副本必须分别触发对应语义断言，重序列化正例须通过；损坏校验跳过下载 SHA 校验以防只靠身份断言掩盖语义检查，原始下载仍必须通过 SHA 校验。
