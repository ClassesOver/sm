# PDF 矢量混合、字段叶子改名与 XLSX 装饰验收（2026-11-11）

固定 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。按用户授权继续文字、表单、转换三域并行，不含 OCR。未提交、部署或启用生产开关；整体 PDF 对齐未完成。

## 本批范围

文字：在已有样式改字、文字标注与矩形/椭圆混合保存上，增加安全箭头、多边形和手绘。复用固定源 writer，不新增绘图引擎；保持来源坐标、原操作索引和文字标注 pending mapping。任意编辑混合、复杂文字重排和完整游标仍未完成。

表单：安全单 Widget 字段可在同一父层级改叶子名称，保留字段值、树/引用、外观与正文。复用 `editFormWidget.newFieldName`，原字段完整身份绑定；重名/前缀/跨父/无变化/多 Widget 与混合属性修改写前拒绝。固定源 `FormDesignLayer.tsx` 明确名称 generated/not shown，因此这是用户授权的字段属性增量，不能称为固定源已有名称编辑 UI 的迁移。另修复恢复草稿时漏传 `newFieldName` 的接线。

转换：修复 PDF 已识别下划线/删除线在 XLSX 中丢失；仅本地 converter 两个文件 8 行，输出原生字体 `<u/>`/`<strike/>`，继续采用既有 dominant-cell-font 语义。没有增加单元格内逐段富文本，也没有改共享 workbook engine。

## 冻结构建与统一链路

- Static `/tmp/pdf-vector-rename-convert-static`，manifest SHA-256 `966b4faa9c14b76dac3158ead6ed85eed0986702442c8cc286e47c6409b9d90d`；runtime `/tmp/pdf-vector-rename-convert-runtime`，CLI SHA-256 `67e76c76e660a96417e0ea97be994eb94051a4f6efd84afb3edd8b9064cda025`。
- Vite、bridge bundle、runtime package 均成功；370 个 JS 分块预算零超限，PDF main 246489 bytes、form controls 30608 bytes，没有修改预算。45 个 PDF 前端生产源与 146 个引擎源文件在冻结后保持不变。
- 三域真实浏览器均使用上述同一 static/runtime，各自 37 个实际 JS 响应 SHA 与冻结文件逐一一致，来源未变，asset/page/console/HTTP errors 全为空。使用真实 grant、cookie/CSRF、原生引擎、签发和授权下载；fixture 仓储为内存实现，不能代替真实生产持久化/权限/网络验收。
- LOCAL 166 项与 converter 48 项 local SHA 全匹配；converter sourceSha256 逐项对固定上游 Git blob 核验，运行包携带的 converter 来源清单一致，没有覆盖上游身份。
- 总证据：`/tmp/pdf-vector-rename-convert-final-evidence-20261111.json`。

文字实际 PDF SHA-256 `6df2d11b206e5272382e289acbcaba85d9a5bae298d0e6f9b13724c828ed93e4`，证据 `/tmp/pdf-vector-rename-convert-vector-browser`。真实 UI 箭头、选区样式、下划线、多边形、手绘交错 5 项，Undo/Redo、预览确认、保存、下载与重开通过；独立 pypdf 检查字体/基线、Line 两个头部、Polygon 闭合、Ink 全路径与 AP/页引用及其他页正文。

表单实际改名 PDF SHA-256 `007c4d200fff36679eded381971a261d62ed68b627adea0fa2ee36c8efab674d`，后续新名称填写 PDF SHA-256 `d347b8121ba7fb814f05e4f48e49223181a7ada7402deea66322e24cfc51c8af`，证据 `/tmp/pdf-vector-rename-convert-form-browser`。UI 创建 name/code、拒绝重名、同父叶子改名、Undo/Redo、实际预览确认与下载重开、新名称填写，共 4 次保存通过。独立 pypdf 核对改名仅改 `/T`，保留值、树/引用、AP、正文，后续填写新名称及无关 code 正常。

XLSX 实际下载 SHA-256 `c1f7051de8237740d19be73020eee1685fdbdcc038df0e53e395aaa1cc1ac904`，证据 `/tmp/pdf-vector-rename-convert-xlsx-browser`。独立 openpyxl 和一次 host Calc 渲染通过四种字体装饰、原表数值/百分比与图片检查；实际 host PDF SHA-256 `c07364986cbfd3077b2585a2d502eef4a6b4ea6fc7627d6e4c6932ecbd771634`。两个 worksheet 打印为 6 页，整体保真仍 false，转换验收失败与人工复核原因在真实 UI 明示，实际下载照常签发。三域最终画面及 Calc 装饰图均已目视。

## 专项、审阅与非阻断契约

- 新 native 专项：`text-vector-mixed.test.ts` 最终 10/10、`form-widget-name.test.ts` 新 3/3、`xlsx-text-decoration.test.ts` 新 2/2 通过，均登记默认测试清单；仅执行新增和受影响专项，不重复完整测试。资源图修复后另对旧 rect/ellipse 健康混合定向 1/1 通过。
- 字段改名后端新 3 项及受影响旧 4 项通过；前端新 3 项及旧 10 项通过。恢复草稿新用例真实 RED→GREEN：`/tmp/pdf-vector-rename-restore-ui-{red,green}.log`。 字段专项原 stdout 当时未落盘，现从原实际工具输出逐字恢复为 `/tmp/pdf-next-form-name/{engine,frontend}-green.transcript-copy.log`，恢复来源/原命令/退出码记录 `green-log-provenance.json`，不是新跑测试或当时 shell 重定向。文字前端新 2 + 旧 2 共 4 项通过，日志 `/tmp/pdf-next-vector-mixed-ui-green.log`。
- XLSX 新 2 项真实 RED→GREEN；独立 openpyxl 读取字体、数值/百分比、图片关系；宿主 Calc 验证实际矢量装饰。完整来源打印版式保真继续为 false。
- 交叉审阅发现新矢量 AP Matrix 与旧 AP 间接资源两处遗漏，均以真实故障注入 RED→GREEN 修复并只读复审。新 Matrix 限缺失/精确单位矩阵；旧 AP 递归包含引用、字典/数组、流和资源，4096 节点/64 层预算写前检查。字节保留基线为 `styled.bytes → append`，允许 PDFium 改字阶段合法重编码。
- HTTP 故障登记扩展现有签发用例：`styledVector`、`styledVectorWriterFault`、`renameFormWidget`，同新运行包共 3 项通过；签发静态守卫另 1 项通过。日志 `/tmp/pdf-vector-rename-convert-http.log`。实际产物可核验身份时，后置复核失败返回具体告警并继续签发，未伪称验收通过。

## 保持开放的边界

PPTX 首行基线约 +6.350708pt 尚未修复。诊断说明改 lineExact 会同时改变首行与后续行距，补默认 run 字号无效，字体表度量不足以可靠推导宿主偏移；没有加入经验常数补偿。详见 `NATIVE_PDF_PPTX_BASELINE_DIAGNOSTIC.md`。

矢量混合仍拒绝保护/表单来源及不支持的混合对象；来源图形不随替换文字重新排版。已有字段跨父移动、父节点改名、任意复杂多 Widget、XFA 与数字签名字段不开放。XLSX 的图片参考区与默认打印分页不等于源页图文保真。

详见 `NATIVE_PDF_TEXT_VECTOR_MIXED_ACCEPTANCE.md`、`NATIVE_PDF_FORM_WIDGET_NAME_ACCEPTANCE.md`、`NATIVE_PDF_XLSX_TEXT_DECORATION_ACCEPTANCE.md`。全项目 typecheck、真实生产身份/持久化/网络及完整镜像不能由本批专项与内存 fixture 结果替代。
