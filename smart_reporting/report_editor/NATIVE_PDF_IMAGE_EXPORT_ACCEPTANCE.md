# PDF 页面 PNG/JPEG 导出增量

2026-11-11。固定 GenOffice 来源为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本记录仅覆盖独立服务与对话框模块；HTTP、Ribbon、打包与真实浏览器由主线程统一接入验收，尚未由本记录证明。

## 来源与 Web 适配

- GenOffice `apps/pdf/src/renderer/App.tsx` 的 `exportImages` 使用 PDF.js canvas，150 DPI，PNG 或 JPEG（质量 0.92），将页面图片交给桌面 IPC 写文件；`apps/pdf/src/main/export-images.ts` 处理页码与路径。
- Web 使用已有已保存来源身份与服务端 PyMuPDF 渲染，按请求页码顺序打包 ZIP。默认 144 DPI，可选 72–216 DPI；JPEG 质量 90。与桌面默认分辨率和质量存在明确适配差异。
- ZIP 在当前会话直接下载，不登记持久产物，不签发 grant，不宣称发布。`manifest.json` 记录来源 SHA、页序、格式、DPI、每张图片尺寸、字节数和 SHA。

## 实现与边界

- 后端 `native_pdf_image_export.py` 暴露 `export_pdf_images(editor, context, expected_sha256, pages, image_format='png', dpi=144)`。校验已保存来源 SHA 与实际读取字节 SHA，使用已有 `run_office_engine`。
- 仅支持不重复的 1-based 页码 1–50 项、PNG/JPEG、整数 72–216 DPI；来源上限 24 MiB，输出上限 64 MiB。加密或需密码来源拒绝。
- 渲染前检查所有所选页面尺寸：单页不超过 2000 万像素，合计不超过 1 亿像素；渲染包含页面批注。使用 RGB、无 alpha，ZIP 固定条目时间且保持请求顺序。
- 前端 `pdf-image-export.ts` 复用页码解析；提交时检查来源是否可用。收到结果后复核 source SHA、实际 ZIP 字节数、SHA256、ZIP 文件头及上限，再提供 Blob 下载。关闭/销毁释放 URL，迟到结果不创建 URL 或重新绘制。
- 尚未声明 CPU 超时、进程隔离、大型复杂 PDF 保真或生产环境验收通过；像素与字节预算不是这些性质的证明。

## 定向验证

- `/tmp/pdf-images-red.log`：缺少后端模块的 RED；`/tmp/pdf-images-green.log`：14 项 PASS。真实 ReportLab 红蓝两页经 PyMuPDF 渲染、PIL 回读中心像素、200×300 尺寸、页序、ZIP 清单与确定性 SHA 均通过；同时覆盖非法参数、巨页像素预算与来源身份变化。
- `/tmp/pdf-images-ui-red.log`：缺少前端模块的 RED；`/tmp/pdf-images-ui-green.log`：7 项 PASS。覆盖请求页序/JPEG、来源 SHA/ZIP SHA/字节数/文件头不匹配、输入与可用性限制、关闭后迟到。测试用短 ZIP 头只验证传输边界，实际 ZIP 内容由后端真实渲染测试证明。
- 不重复完整测试。最终主线程接入后的统一类型检查、HTTP 原生会话/CSRF 与实际下载、真实浏览器点击和视觉验收需单独记录。
