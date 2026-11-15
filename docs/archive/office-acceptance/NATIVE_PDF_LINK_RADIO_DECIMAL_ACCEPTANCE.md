# PDF 链接混合、单选组改名与 XLSX 小数字体验收（2026-11-11）

固定 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。继续用户授权的三域增量，不含 OCR。限定范围验收已完成，整体 PDF 对齐与完整转换保真仍未完成。未提交、部署或启用生产开关。

## 本批实现与范围

文字：样式改字可与安全新增 HTTP/HTTPS、mailto 和内部跳页链接同批保存，仍复用固定 `addLinkAnnot` writer。内部目标绑定来源页表，写后核对实际目标页引用、页顺序、XYZ/null 和完整字典；外链核对实际 URI。来源动作、目标、页面和几何在任一 writer 前校验；原操作索引及后置失败保留实际字节的契约保持。

真实探针确认固定 writer 的 `PDFString.of` 会截断原始中文/emoji URI。因此新 mixed 路径限定可打印 ASCII，合法百分编码 UTF-8 可保存；凭据、控制字符及编码 CR/LF 拒绝。新增 link 时拒绝 catalog OpenAction/AA、Names/JavaScript、page AA 和来源 annotation A/AA/Dest；保留无关 Names。此为当前路径列举的来源边界，不是整 PDF 主动内容的穷尽清洗。未改变旧独立链接入口或共享 writer。

表单：已有安全互斥单选组支持同父层级叶子改名，2–64 个 Widget，可任选组内精确旧 Widget 为锚点。整组校验选项、V/DV/AS、Parent/Kids/页面引用、动作、独立状态外观及所有兄弟资格；原生只改字段 `/T`，保留所有其他间接对象、原始流和引用。UI 明示整组改名，恢复草稿继续完整验证。非单选多 Widget、共享外观、非互斥组、跨父、XFA 和签名字段仍拒绝。这是更多字段属性增量，不声称固定源已有组名编辑 UI。

转换：非指数裸小数与分组小数按来源小数位写原生格式，继续保持数字类型和值。仅非表格固定小数行，使用来源 ink 宽与既有 font-metrics 输出 advance 的较大值，加既有 padding 提出最小列宽；保留更宽 table claim，未全局 autofit。整数、指数及普通正文不扩宽。

`Chrom Sans PS` 的 exact alias 复用既有 Helvetica 候选，installed-first 和无候选原名保持。映射依据为固定 PDF 的 Helvetica-BoldOblique 字典、实际 PDFium base/family/embedded API 与原始 CFF 名称，未猜测其他 PS 家族。新 probe 可复现该证据。

## 统一冻结与实际下载

- Static `/tmp/pdf-link-radio-decimal-static`，manifest SHA-256 `61aa2ab4abf61dd82b8d6c7e769f558a025eb2ab8ec6ebe47be825a89a46a376`。
- Runtime `/tmp/pdf-link-radio-decimal-runtime`，CLI SHA-256 `c0830a036e669d3b4ba7a65899bf3fbd83826b604eb58e6d4d8d0ea3f040d867`。
- Vite 一次构建、bridge bundle、runtime package 均 exit 0。45 个 PDF 前端源、176 个引擎冻结文件及 953 个 bundle inputs 最终无漂移；bundle inputs 在打包后无修改。
- LOCAL 175 项、converter 48 项 local hash 匹配；上游 hash 逐项核验固定 Git blob。运行包来源清单、转换引擎许可和 WASM 身份匹配。
- 三条真实浏览器链路均 exit 0，各自 37 个实际 JS 响应与冻结资源匹配且集合相同，来源未变、asset/page/console/HTTP errors 为空。
- 本次共享工作区构建共 373 个 JS 分块，预算零超限。PDF main 249133 bytes，form controls 32602 bytes；本批没有修改预算或无关 Word 代码。前批 Word 预算失败保留在其历史验收中，不作为本次构建结果。
- 总证据：`/tmp/pdf-link-radio-decimal-final-evidence-20261111.json`。

链接实际下载：`/tmp/pdf-link-radio-decimal-link-browser/mixed.pdf`，13292 bytes，SHA-256 `b2dd5107cadc37375cd58426fe9c68cab1c7d869d9e7a65fab2a0953b24cb178`。真实 pointer/dialog 添加 HTTPS、选区改字、underline、内部第2页、mailto，共5项；Undo/Redo、实际预览确认、保存、签发下载及重开通过。独立 pypdf 核对 URI、严格 Link/A/Dest 字典、实际页引用、字体/基线/颜色及其他页。最终 UI 已目视；无 AP 的 Link 不添加可见装饰。

单选组实际下载：`/tmp/pdf-link-radio-decimal-form-browser`。创建 party.answer/party.code，以第二按钮锚定拒绝重名，再改为 party.renamedAnswer，Undo/Redo、预览确认、下载重开及新名填 No，共4次保存通过。改名文件 SHA-256 `9377033c760a7df0ca8fabfae5cd70bfe556c377055ff7b4073cc9f9a3e8fa12`；后填值文件 `68178d8efe351e30b55fb504b07faa7d4c627d78ab45128b00337252186fbc55`。独立 pypdf 比对全原始对象仅 `/T` 例外、AP/引用/正文及选择状态；最终 UI 已目视。

XLSX 实际下载：`/tmp/pdf-link-radio-decimal-xlsx-browser/converted.xlsx`，5751 bytes，SHA-256 `a46ab075cbd8563aaa3c52279d1b32e3aa9dead9d1a39f88c4efbcd2c1828da8`。独立 openpyxl 核对数字类型、原精度格式、14.09 字符列宽、原富文本/表格/图片保持。对该实际下载仅一次 Calc 渲染，临时 profile/output 均在 `/dev/shm`，exit 0；实际 PDF SHA-256 `346c6dc1b5ca6baf0e78755c6e5e2721277e4d4b7d6db327eccb050b814c6f6e`。

实际显示 `12345.67`、`12345.6789`、`-31.10`、`12,345.678`，无 `###`；指数仍按旧策略显示 1250。完整 PDF BaseFont 和嵌入 TTF PostScript 名均确认 LiberationSans-BoldItalic，之前已确认的字体回退已在该测试来源修复。首次 host verifier 误将 MuPDF 的31字符名称截断当成字体变化；经实际资源和嵌入字体核验，只修 verifier 的精确识别，复读同一产物通过，没有重复 Calc 或修改生产。`rendered-decimal-font.png` 已目视，混合样式和四组小数清晰。

来源两页仍默认打印为六页，图片参考区不等于来源图文原位排版。`overallFidelityPassed=false`，转换 UI 明确验收未通过与人工核对，实际下载照常签发。不能据本专项宣称所有字体、数字表现及 Office 版式完整保真。

## 专项、审阅与非阻断

- Link native 核心5项、URI新增2项、Names JavaScript新增1项分阶段通过，均有真实 RED→GREEN；未重复全文件。前端新4项通过，frontend/helper scoped strict tsc 通过。覆盖七类输出故障与 append writer 异常实际 bytes 保留。
- 单选组 native 新4+受影响旧name3共7 PASS；前端新2+旧name/choice6共8 PASS。根/层级/跨页/未选中组、旧身份/冲突/动作/AS/V/DV/共享外观等边界有专项。
- 小数/字体新4+受影响旧字体7共11 PASS；其后只新增宽度专项1 PASS，验证输出 advance、较宽 table claim 保持、整数/指数不扩宽。
- 恢复组改名 host 集成1 PASS/13 skipped。首次 fixture 错误地继承了 append payload 且缺少第二选项，修正测试 fixture 后通过；不将该首次失败冒称功能 RED。
- 新增 HTTP 登记：styledLink、styledInternalLink、styledLinkWriterFault、renameRadioGroup，另签发静态守卫，共5个唯一检查通过。首次4 PASS/1 FAIL来自测试沿用文本单流 AP 断言；修正为 radio 每个状态流及引用核验后，只重跑失败用例1 PASS，没有生产变更。日志 `/tmp/pdf-link-radio-decimal-http-green.log`、`/tmp/pdf-link-radio-decimal-http-radio-green.log`；旧 runtime 三个功能用例真实 RED 在 `http-red.log`。
- 文字 URI 截断由 root 审阅发现，文档级脚本遗漏由转换 agent 只读交叉审阅发现；均补真实失败用例后最小修复，最终只读复审无新增阻塞。

已生成且身份可读时，后置验收失败保留实际产物与下载，明确原因且 validation 不伪称通过。没有新增 Python 生产签发函数。仅运行新增及受影响专项，没有重复完整测试；全项目仍有已知宿主/依赖类型诊断，不声称全项目 typecheck 或完整生产镜像验收通过。浏览器使用真实 grants、CSRF、原生引擎及下载，但 fixture 仓储为内存实现。

仍开放：完整游标和复杂文字重排、任意混合编辑、任意复杂多 Widget/XFA/签名字段、完整 Office/Markdown/HTML 保真；PPTX 首行基线约 +6.350708pt 未解决。详见三个分域验收文档及 `NATIVE_PDF_ALIGNMENT_STATUS.md`。
