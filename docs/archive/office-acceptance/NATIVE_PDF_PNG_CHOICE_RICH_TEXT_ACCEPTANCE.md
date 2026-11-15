# PDF PNG 混合、已有下拉选项与 XLSX 富文本验收（2026-11-11）

固定 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。继续用户授权的文字、表单、转换三域，不含 OCR。以下增量已完成限定范围验收；整体 PDF 对齐和转换完整保真仍未通过。未提交、部署或启用生产开关。

## 本批实现

文字：安全 RGB/RGBA PNG 可与样式改字、文字标注及已支持的矢量绘图交错保存。复用既有图片 Stamp writer，新增 canonical base64、PNG chunk/CRC、有界解压、scanline/filter 和像素预算检查，以及实际 AP/矩阵/RGB/SMask 复核。图片保持来源坐标，不跟随改字重新排版。仅 8-bit、静态、非交错 PNG；运行时依赖 Node 内置 crc32（22.15+），本次实际 Node v24.18.0，不以此代替完整生产镜像验收。

表单：`editFormWidget.choiceOptions` 支持已有安全单 Widget 下拉字段修改未选项和排列。保留现值、默认值、原始引用、字段树、外观和正文；拒绝移除现值/default、复杂动作、多选/可输入/列表和多 Widget 等不支持来源。选项须单独保存。恢复草稿补齐完整 operation 透传。此项属于用户授权的更多属性增量，固定源仅新建字段有选项 UI，不能声称迁移了固定源已有选项编辑功能。

转换：PDF→XLSX 保留单元格内混合字体、粗斜体、下划线和删除线。复用既有 workbook `applyCellEdits` 富文本 API，未修改共享 workbook engine。只对拼接结果严格等于原正规化 cell text 的混排文字补写，并中和 cell font 四开关以防普通 run 继承 dominant 样式；数值优先、原表格式和图片保留。超限、控制字符等不匹配时明确 plain fallback；补写异常保留调用前完全相同的工作簿 bytes 并返回原因。

## 冻结构建与真实链路

- Static：`/tmp/pdf-png-choice-rich-static`；manifest SHA-256 `2b48f07ae8e5feba57e4068880a916886679c06ae35888e872e55398e95ff70f`。
- Runtime：`/tmp/pdf-png-choice-rich-runtime`；CLI SHA-256 `6248ae2516e65a1f7a0d255f210f0a28a15d0f19a7f19c98538726be49056fad`。
- Vite、bridge bundle、runtime package 均 exit 0；前端只构建一次。45 个 PDF 前端生产源、172 个引擎冻结文件保持不变；952 个实际 bundle inputs 在打包后无修改且最终哈希一致。
- LOCAL 171 项匹配；converter 48 项 local hash 匹配，source hash 逐项与固定上游 Git blob 核验。运行包 converter 清单、转换引擎许可与 WASM 身份匹配。
- 三域同一 static/runtime 真实浏览器均 exit 0；每域 37 个实际 JS 响应与冻结文件一致，三域资源集合一致。来源未变，asset/page/console/HTTP errors 为空。
- 使用真实 PDF.js、grant/cookie/CSRF、原生引擎、预览确认、签发和授权下载；测试仓储为内存实现，不能代替生产持久化、真实权限/网络或完整镜像验收。
- 总证据：`/tmp/pdf-png-choice-rich-final-evidence-20261111.json`。

370 个 JS 分块的全站预算检查有一项失败：共享工作区 Word 入口 `lazy-docx-main-4VAQTYic.js` 为 258710 bytes（252.6 KiB），超过 250 KiB。PDF main 248158 bytes、form controls 31982 bytes 均在对应预算内。本轮未修改预算或扩围修改 Word。`globalBudgetPassed=false`，不能称全站预算通过。

## 实际下载与独立回读

PNG：`/tmp/pdf-png-choice-rich-png-browser/mixed.pdf`，14616 bytes，SHA-256 `e19dd2f159136b79a7878b0579061e480804baf8352c502fbe771a82898f0a89`。真实 file input→canvas 规范化→pointer 放置，与 AA/BB/CC 选区字体/字号/粗斜体/红色、underline、arrow 交错共 5 项，Undo/Redo、预览确认、保存、下载、重开通过。独立 pypdf/Pillow 核验实际 RGB/透明通道、AP/矩阵/页引用、字体/基线及其他页正文；已目视最终 UI。

表单：`/tmp/pdf-png-choice-rich-form-browser`，创建 choice/code、删除当前值拒绝、改为 Three/Two/Four、Undo/Redo、实际预览确认、重开回显、后填 Three，共四次保存通过。选项修改下载 SHA-256 `aab514a0da7189fafa18b41d030f0352f89ec8736250fc67b42324d3178730a4`；后填值下载 `bb2ad1afdd582161a1c327f3c5f4295ad07e74aefd9bd0c40ac394a078995290`。独立 pypdf 比较目标 Opt、现值、AP、树/引用、正文及无关 code；已目视最终 UI。

XLSX：`/tmp/pdf-png-choice-rich-xlsx-browser/converted.xlsx`，5644 bytes，SHA-256 `52c226c294572d2be86ba06d661d10e804e140957c859bab3c4aff3fd9e82606`。独立 openpyxl 检查六段原生富文本、dominant/minority 四开关、数字类型/数值、原表百分比与图片。对该实际下载仅一次 Calc 渲染，临时 profile/output 均在 `/dev/shm`，exit 0；实际 PDF SHA-256 `616efb53032d60767d5f73eb8d5ec91638130941efa8136daeebd2b07bd4a21c`。独立实际字体/矢量装饰检查通过，最终 rich-text PNG 已目视。

XLSX 整体保真仍为 false：`Chrom Sans PS` 在 host 回退为 NotoSans-BoldItalic；存储数值 12345.67 和数字类型保持，但既有 General 格式/列宽打印为 12346；两页来源被默认打印重排为六页。真实转换 UI 明确显示验收未通过、具体限制及人工复核，下载照常签发。不得将富文本专项通过等同于来源图文/数值视觉/分页完整保真。

## 定向测试、审阅与非阻断

- PNG native 最终核心 6/6，加仅新增边界 2/2；前端最终 4/4。覆盖 CRC/deflate/scanline、四分之一旋转、保护/表单/单位来源及七类后置输出故障保留实际 bytes。form agent 只读交叉审阅无新增阻塞。
- 下拉选项 native 最终文件 6/6；此前新 5+受影响旧 7 共 12/12。前端新 3+旧 13 共 16/16。日期 AA 被误许的边界经真实 RED→GREEN，仅在 choice 纯读器拒绝 A/AA，保持普通日期支持。
- XLSX 新专项 5/5，随后仅新增 UTF-16/LF 恰好上限边界 1/1。真实 RED→GREEN，独立读取修复前 XLSX 明确失败。未重复完整测试。
- 恢复下拉草稿新增 host 用例真实 RED→GREEN，仅定向 1 PASS/12 skipped，日志 `/tmp/pdf-png-choice-rich-restore-ui-{red,green}.log`。
- 本批签发新增检查为 PNG 输出复核、PNG writer 故障、下拉选项输出复核、XLSX plain fallback 回执，另签发静态守卫，共 5 个唯一检查通过。初次 4 PASS/1 FAIL，下拉测试错误地只接受 Opt 字符串；原生库实际输出合法的 export/display 二元组。仅修正断言核验两值均匹配，只重跑失败用例 1 PASS，没有生产变更。日志 `/tmp/pdf-png-choice-rich-http-green.log`、`/tmp/pdf-png-choice-rich-http-choice-green.log`。
- XLSX 原生专项真实注入 helper writer 异常；HTTP 用例模拟其 fallback 回执并核对真实工作簿的下载字节/身份，不声称在 HTTP 内注入 Node helper。
- 已生成且身份可读时，后置复核失败保留实际产物及下载，具体原因写入告警，validation 不伪称通过。无新增 Python 生产签发函数。

新 PNG helper 与前端 scoped strict tsc 通过；全项目仍有既有依赖/宿主/union 诊断，未声称全项目 typecheck 通过。

## 仍开放

任意编辑混合、页面完整游标与复杂文字重排；已保存图片 Stamp 编辑/删除；复杂多 Widget、XFA、签名字段；完整 Office/Markdown/HTML 内容与版式保真。PPTX 首行基线约 +6.350708pt 仍未解决，本轮没有经验常数补偿。OCR 按用户要求排除。

分域细节见 `NATIVE_PDF_TEXT_PNG_MIXED_ACCEPTANCE.md`、`NATIVE_PDF_FORM_CHOICE_OPTIONS_ACCEPTANCE.md`、`NATIVE_PDF_XLSX_RICH_TEXT_ACCEPTANCE.md`；总体状态见 `NATIVE_PDF_ALIGNMENT_STATUS.md`。
