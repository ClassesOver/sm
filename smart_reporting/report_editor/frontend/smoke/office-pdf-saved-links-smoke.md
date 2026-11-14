# PDF 已保存链接交互验收

本批接续添加链接窗口：文件内已有链接还必须能在浏览器宿主中操作。产品使用当前 PDF.js 原生 AnnotationLayer，宿主只提供外部 URL 属性和目标页导航。外观沿用 Office 主题焦点环，绘图/保存期间暂停链接；只读阅读可以使用链接。

```bash
# 在 frontend 目录执行；仅定向测试，不重复完整套件。
TMPDIR=/dev/shm node_modules/.bin/vitest run src/pdf-saved-links-host.test.ts src/pdf-link-desktop.test.ts src/pdf-object-host.test.ts

TMPDIR=/dev/shm \
PDF_SMOKE_STATIC_DIRECTORY=/dev/shm/your-frozen-build \
PDF_SAVED_LINKS_OUTPUT=/dev/shm/your-new-evidence \
PDF_SAVED_LINKS_SOURCE=/dev/shm/previous-link-evidence/downloaded.pdf \
PDF_EXPECTED_MANIFEST_SHA256=your_manifest_sha256 \
node smoke/office-pdf-saved-links-smoke.mjs
```

必须使用不存在的新证据目录；重复目录在服务、浏览器启动之前失败。端口默认 4394，可用 `PDF_SAVED_LINKS_PORT` 调整。`PDF_SAVED_LINKS_BASELINE=1` 只记录前十五个场景；旧构建可以缺少链接层，不因此创建保存。构建保留项目 Vite 插件、别名和分包，仅隔离输出、缓存与 PDF.js 资产复制位置；cmaps、standard_fonts、wasm 必须来自当前 node_modules/pdfjs-dist，不能复用旧 static。

输入必须是前批三页真实下载的链接 PDF（包含网页、邮件、页内链接及旧链接/便签）。Python 服务器只读该文件，使用 pypdf 派生明确夹具：named destination、恶意 URI/Launch 动作及带 CropBox/UserUnit=2/Rotate=90 的链接页。授权、源文件接口、浏览器 PDF.js 和前端构建为实际链路；修订仓储沿用内存夹具，外部网页响应为显式路由夹具。不得称作生产数据库或桌面 Acrobat 实机验收。

PyMuPDF 独立提取链接矩形；`get_links()['from']` 已含旋转，不再次乘 rotation_matrix。第三页已知参照严格断言宽高 700×520、链接矩形 [460,80,520,320]。浏览器相对页面位置与独立参照误差小于 1px。祖先裁剪按 CSS 变换后的内容框计算，不能把 AnnotationLayer 未旋转的 clientWidth 直接当屏幕宽度。

初始三页×五种视口共十五场景；全幅/裁切×0/90/180/270°×0.5/1/1.5 缩放共二十四场景；清除草稿后重开一个场景。共四十场景、一百三十个链接检查。每个链接真实 Tab/Shift+Tab 回返，检查焦点环、可访问名称、URL/target/rel、可见区域五点命中。阅读区能容纳的焦点区域须完整可见；超出视口的高链接不要求一次全可见，但 start/end 分段必须连续覆盖完整区域并保持命中。所有布局检查前后草稿不变。

真实 Enter 打开外部网页，断言窗口 opener 为空；显式和命名目标都到第三页并回焦页标签；绘图模式链接 inert、tabIndex=-1，恢复选择后可用。JavaScript/Launch 不成为可用链接。真实裁切/旋转仅写本地草稿，随后逐项撤销并重开为空。

本批全程不保存：`savedRevisions=0`、无 `/api/save`、原文件下载接口字节与派生夹具 SHA 一致，前批下载 SHA 不变。实际加载的 JS/CSS/wasm 响应逐字节核对隔离构建，不覆盖项目 static、不部署。

完整目标参数和坐标映射使用独立真实浏览器夹具验证。该夹具以仓库 `test_native_pdf_extract.source_pdf()` 为只读三页输入，不依赖前批临时下载文件；再派生 named destination、Fit/XYZ 目标、旋转裁切页。它与四十场景点击层验收是独立证据，不能把测试输入说成用户下载文件。

```bash
TMPDIR=/dev/shm \
PDF_SMOKE_STATIC_DIRECTORY=/dev/shm/your-frozen-build \
PDF_DESTINATION_OUTPUT=/dev/shm/your-new-destination-evidence \
PDF_DESTINATION_SOURCE=/dev/shm/your-read-only-three-page-source.pdf \
PDF_EXPECTED_MANIFEST_SHA256=your_manifest_sha256 \
node smoke/office-pdf-destination-smoke.mjs
```

检查 XYZ（含命名目标、显式/空 x-y、保留/应用缩放）、Fit/FitB、FitH/FitBH/FitV/FitBV 的显式与省略参数、FitR、CropBox/UserUnit=2/90° XYZ 与 FitR，以及非法 zoom。十五类目标参数分别在1440×900、768×720、320×640、640×360、390×320验证，共七十五场景。每次键盘 Enter 后检查活动页、精确缩放、目标点仍在阅读区、焦点回到阅读视口、状态提示及草稿不变；页面居中且宽度无需滚动时不强求目标点贴左边缘。

缩放语义以当前 PDF.js scrollPageIntoView 和官方 PageViewport 为参照：XYZ 零/空缩放保留当前值；Fit 家族适配页面或轴；FitH 的空 y 保留当前 PDF 位置，省略或负 y 回到页顶；无效目标在改变阅读状态前软告警。宿主定位期间，更新草稿、保存、关闭、其他用户输入或后续链接会取消旧目标；排版自身触发的 scroll 不取消目标。类型用例以实际 PDF.js PageViewport 建立 CropBox/UserUnit/旋转转换。

目的地构建登记在 `/dev/shm/office-pdf-destination-fixed-freeze-20261112/`，manifest `b932dac13f9da0ac771d8e2300e88c1b4e784f4ce376ec849dcb45eab089d777`；394个JS包预算通过，类型检查通过，static未改写。最终目录 `/dev/shm/office-pdf-destination-final-verified-built-20261112/` 共75场景、51个真实JS/CSS/wasm资源、0保存修订；来源是明确仓库测试夹具、内存修订仓储，不代表生产数据库或桌面Acrobat。

邮件链接检查属性和命中，未启动系统邮件客户端。只读、延迟导航、目标删除/重排、旧 generation 与保存/销毁保护有定向宿主测试；不把这些 jsdom 夹具称作浏览器几何证明。
