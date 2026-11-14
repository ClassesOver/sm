# PDF 多段文字插入增量验收（2026-11-14）

本批使纯 insertText 草稿支持连续、跨页插入后统一预览保存，最多沿用 500 项操作预算。每段独立参数/来源/页面/落点校验；全部原来源身份在写入前校验，中间文件身份仅由引擎按原页序重绑。前端追加草稿并逐次 Undo/Redo，持久草稿可重建。

复用单段字体、对齐和可提取文字 writer；回执保留原来源及原操作索引，previewDigest 绑定全部输入和实际最终字节。后段溢出保留实际文件并报告跳过/复核提示；后段中间加载异常保留前段字节和真实失败索引。不改发布与下载协议。

## 验证

- 引擎：node --import tsx --test bridge/static-text.test.ts，15 通过，0 失败。实际 PDFium 回读覆盖跨页文字保留、确定性摘要、旧字/几何、四旋转既有契约；pypdf 独立回读原单段字体/基线测试也通过。新增跨页测试使用 PDFium，未冒称独立 pypdf 跨页核验。
- 前端：pdf-static-text.test.ts、pdf-static-text-dialog.test.ts、pdf-static-text-thumbnail.test.ts、pdf-operations.test.ts，54 通过，0 失败；DOM 环境为 jsdom，不等于真实浏览器验收。
- 服务：现有预览确认/保存/真实下载测试新增双段参数，沿 NativeEditorService、实际隔离 CLI 与下载 stream 执行，独立 pypdf 读取两段文字和未改正文，检查实际预览字节等于下载字节，来源文件不变。fixture 使用既有内存仓储/工作区，并非生产身份或 HTTP 浏览器验收。
- 全局 tsc --noEmit：退出 2，632 条工作簿等诊断；未出现修改的 PDF 文件诊断。不能声明全局构建验收通过。
- 独立代码审查发现后段加载异常保留问题，新增故障注入验证 RED 后修复，最终 15 项包含该回归。git diff --check 通过。

日志保留于本次执行环境 /tmp/pdf-multiple-text-{engine-reviewed,frontend-reviewed,service-reviewed,types,bundle-reviewed}.log；原失败另保留 engine.log、fault-red.log、service.log 和 bundle.log。隔离 CLI 在 /tmp/pdf-multiple-text-runtime/dist/cli.mjs，复用安装的运行依赖，不是自包含发布包。

## 剩余边界

文字插入仍只允许纯 insertText 批次，不与原位改字、批注、页面结构或表单等混用；来源安全限制保留。顺序复用单段 writer 会重复加载/测量，大批量性能未验收。完整页面游标、段落 reflow、插入文字块移动/编辑/删除工具、最终生产包的真实浏览器整体验收仍开放。未提交、部署或开启生产开关，不声明 PDF 全量对齐完成。

## 后续宿主核验修正

同日后续宿主测试发现 pdf-main 的公共独占按钮门控遗漏，上一批独立配置/引擎/服务验证不能证明用户通过公共入口连续插入。本批后续已修复并完成真实Chromium公共入口验证，见 NATIVE_PDF_PENDING_TEXT_ACCEPTANCE_20261114.md；不改写上述原始验证范围。
