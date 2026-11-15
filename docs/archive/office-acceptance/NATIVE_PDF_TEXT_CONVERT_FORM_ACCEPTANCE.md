# PDF 文字、转换、表单并行批次验收

2026-11-11。固定 GenOffice 来源：f8c17004fb730df11f0f743164ffd8b4281bb38c。
本批是用户所选三域的实质增量，不是 PDF 全功能对齐、业务内容验收或生产上线通过。OCR 未启用，未部署、未提交、未开启生产功能开关。

## 实际交付

- 文字：可检索静态插入与正向水平既有文字整对象替换，支持 Arial/Times/Courier 对应字体、粗斜体、字号/颜色、手动多行、行距、左/中/右对齐。不同既有对象可同批替换；身份均来自不可变来源。PDFium 原生实际字体度量参与定位，修复提取文本合成尾空格污染测宽的真实问题。完整游标、选区 styleRuns、自动段落重排、任意种类混合编辑仍未完成。
- 转换：PDF→DOCX/XLSX 使用固定源重建器并登记独立派生文档；Markdown/HTML 下载真实 DOCX、核来源/SHA/size 后复用 Word 解析器、编辑器和固定源序列化。扫描页保留图片，不执行 OCR；Markdown/HTML 图片自包含，序列化失败仍显示已生成的 Word 下载。
- 表单：text/checkbox/date/choice/radio 新建；日期四格式与精确内建动作白名单；radio 多 Widget 原子组；安全控件 rect/required 编辑与十一种同页排列。来源及四项 Widget 身份绑定，恢复删除草稿也重新校验这些身份。保留旧删除仅支持安全独立单控件的限制。
- PPTX：复杂样本保留双栏、可编辑表格、图片与 Unicode。独立 LibreOffice 渲染暴露并修复表格尾空白误作巨大内边距导致的断字符；补 PDFium Chrom 字体别名，恢复等宽文本。仍有文本位置、行距与字体替代差异，整体保真 validation=false。

## 最终实际浏览器证据

三项均使用真实生产构建、授权交换/cookie/CSRF、真实 PDF.js、引擎、预览确认、签发、下载和重开。仅仓储为测试内存实现，不等于生产数据库/权限/部署验收。

共同冻结 manifest：6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8。
独立运行包：/tmp/pdf-text-convert-form-runtime-20261111。
CLI SHA-256：bee0f6d26a262f66b0183862ecaa9ff70607268f8195428ef4dde9e27fb6c667。
浏览器 Chromium 140.0.7339.16；Node 24。临时目录放在 /dev/shm 后串行执行。

| 项目 | 实际证据 | 结果 |
| --- | --- | --- |
| 文字 | /tmp/pdf-text-style-browser-20261111-root03/summary.json | 插入/替换修订4→5→6；真实下载/重开；pypdf 四行字体/颜色/基线，包含 Again 的第二行右对齐；30 个资产哈希；无浏览器/HTTP/资产错误 |
| 表单 | /tmp/pdf-form-extended-browser-20261111-root03/summary.json | 日期→下拉→单选→填写→属性→排列，修订4→10；六份实际 PDF 字段树/AP/值/几何独立回读；30 个资产哈希；无浏览器/HTTP/资产错误 |
| 转换 | /tmp/pdf-convert-formats-browser-20261111-root03/summary.json | DOCX/XLSX 实际授权下载，python-docx/openpyxl 回读；Markdown/HTML 实际 Blob 下载；扫描 PNG 内嵌并独立解码；120 个资产哈希；无浏览器/HTTP错误 |
| 复杂 PPTX | /tmp/pdf-complex-fidelity-20261111/root-visual-review.json | 独立 LO 渲染与源图目视比对，表格断字符及等宽字体两项修复确认；不声明任意文档完整保真 |

总归档：/tmp/pdf-three-domain-final-evidence-20261111.json。共同资产的记录哈希一致，原 PDF 来源均保持不变。验收完成后共享 static 已被另一轮全局构建替换；此处证据仅绑定上述冻结 manifest，不将后续全局资产冒称本次验收版本。未覆盖他人构建。

## 定向回归与非阻断契约

- 实际 Office 转换引擎7项、服务12项；新增 DOCX/XLSX HTTP 后置回执/复核/登记/写入/持久化故障10项通过。
- 新样式替换 HTTP 后验告警1项、控件属性/排列 HTTP 后验告警2项通过：实际文件可读且身份匹配时保留下载，明确实际编辑或复核告警，不能误报“原文未改”。
- 对象设计未确认预览不得预约，以及签发静态守卫等必要定向契约通过；最终签发链守卫单项通过。
- 插入/替换、表单、源身份与安全约束的分域专项及独立 pypdf 校验记录见各专属验收文档；未重复运行全项目完整测试。
- 共享前端集成22项及恢复删除四身份 host4项通过；PDF 范围 TypeScript 检查通过；生产 Vite 构建通过。PDF 主包约244KiB，未放宽250KiB阈值。
- 全量 TypeScript 仍有本批未修改的 Word/Slides 文件错误；全局预算也有非 PDF 包失败，未改阈值或顺手修改其他域。未重建完整生产镜像或声称 Node22 容器通过。

来源清单：PDF LOCAL-SHA256.json 共141项；转换固定源48项原始/本地哈希分别记录，原始上游哈希不被本地适配覆盖。运行包保留三类 Office 引擎来源说明/许可证、WASM身份及新的 esbuild 闭包元数据。

## 保留的失败记录和剩余边界

root01 文字/表单 smoke 资产监听误读302被修正；文字 root02 虽通过旧断言，复核发现第二行合成空格测宽缺陷，本批以 root03 增强断言结果为准。表单 root02 在第五次保存后重开请求遇浏览器资源错误，前五份 PDF 独立验证通过但未当作完整成功；root03 六阶段才记完整通过。所有原失败记录保留。

剩余：任意混合编辑、完整 caret/选区样式、自动段落/跨对象 reflow；旋转/倾斜文字矩阵；任意复杂来源的插入。转换还存在复杂版式/字体完整保真、XLSX 普通页浮动图像装饰、MD/HTML 页眉页脚/分页差异。表单还存在任意层级创建、既有单选组扩展、复杂多 Widget 语义、跨页排列、已有字段字体/名称编辑、CJK初始值、自动检测、XFA及数字签名。真实证书服务仍需外部配置。

专属记录：NATIVE_PDF_TEXT_STYLE_ACCEPTANCE.md、NATIVE_PDF_OFFICE_TEXT_CONVERSION_ACCEPTANCE.md、NATIVE_PDF_FORM_DESIGN_ENGINE_ACCEPTANCE.md。整体功能族差异以 NATIVE_PDF_ALIGNMENT_STATUS.md 为准。
