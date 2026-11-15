# PDF→PPTX 文字链接保真适配（2026-11-11）

固定 GenOffice 源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。这是转换保真适配，不是源 UI 的新增菜单：现有 PDF 提取器已经从真实 Link annotation 为 Span 记录 `href`，DOCX 已消费该值，PPTX 重建却未传递链接目标。同样式的链接文字与普通文字还会被合并成一个 run。只读实际 PDF→IR→PPTX 探针确认有 href 的来源文字输出 0 个 `a:hlinkClick`。

## 最小范围与边界

生产只修改 `pdf_engine/vendor/pdf2docx/src/rebuild-pptx/text.ts` 和 `rebuild.ts`。前者把来源 HTTP、HTTPS、mailto URI 映射到已有 `TextRun.hyperlink`，保留既有来源过滤要求，不接收控制字符、空白或其它 scheme；严格的 `#_pdfpageN` 转为现有 `slide:N-1` 编码。后者在文字框、表格与脚注的既有构建操作前调用共享 writer 已提供的 `ensureRunLinkRels`，为正确的所属 slide 分配关系；所有 slide 仍在写内容前预建。不修改共享 slides writer，不增加依赖或格式。

链接目标参与 run 合并判定，避免链接范围越过同样式普通文字或其它目标。来源显式颜色、字号、粗斜体、装饰在 OOXML 中保留；无来源下划线的链接显式写 `u="none"`，防止解析器自动补下划线。此处描述生成文件的属性，不代表宿主最终颜色保真，见下文实际表格链接差异。重新生成的列表 marker 与目录页码没有来源 Span 的链接身份，清除它们从相邻 run 拷贝到的 target，不扩大可点击范围。其它文本、字号、几何、固定行距、零内边距及 noAutofit 分支不变。

无效页号、不存在的目的页、非严格 page anchor、危险 URI 和直接传入的 `slide:`/`action:` 伪编码不生成可点击关系，原文字保留。不把缺失目标当作已转换成功。FTP、tel 及任意 PDF action 语义不在本批适配范围；URI 是来源数据，不在测试中访问外站。

## 原生回归与类型核查

新增 `bridge/pptx-text-links.test.ts`：

- 真实 PDF Link annotations 经实际 PDFium 提取 href 后，要求正确的 `a:hlinkClick`、rId、URI/slide 关系与 TargetMode。
- 同样式的外链、普通文字和不同目标不合并；来源非主题颜色与无下划线保持。
- 表格、脚注、不同所属页及跨页双向 GoTo；多个目标互不串联。
- 危险/无效 URI 与页号保留文字而无坏关系。
- 添加链接不改变相同来源文字的其它 OOXML 几何和格式。
- 合成列表 marker/目录页码不继承相邻文字的可点击 target。

首 5 项真实 RED（4 失败，负例已通过）→GREEN 5/5，证据 `/tmp/pdf-pptx-text-links/{red-parser-preserving,green}.log`。第 6 项是在发现 marker 复制问题后单独 RED→GREEN，证据 `marker-{red,green}.log`；不声称存在新的整文件 6/6 重跑。没有重复完整测试。

两生产文件 strict 窄 tsc exit 0，证据 `production-types.log`。测试入口闭包仅剩既有 `src/main/wasm-path.ts` 的两条 `Process.resourcesPath` 宿主声明错误，见 `test-types-final.log`；测试本身新增的 IrPage 字段类型问题已修正，不声称全项目 typecheck 通过。

## 独立三页来源与字节核查

专属入口：`frontend/smoke/pdf-pptx-text-links-{source.py,server.py,smoke.mjs,verify.py}`。来源是 deterministic reportlab 三页 PDF，含 HTTP、HTTPS、mailto、表格文字、第三页跳转、第三页回到第一页及一条应被拒绝的 JavaScript annotation。原生来源 SHA-256 `a90ba465c476290b8490621ff94a428096daffde110c1372b94c3236c374d57c`；两次生成的字节通过独立 verifier 的完整相等检查。

原生实际 PPTX SHA-256 `3915576fa34024d3ef70c0057599cbbe99cc9f0a24dbe572928c525a6c51f2f0`，独立 Python Zip/XML 检查 `/tmp/pdf-pptx-text-links/native-independent.json` 通过。要求恰好 6 个 run 链接（含 1 个表格链接），正确 slide 关系与目标、无多余/悬空/重复关系，JavaScript 不产生点击，所有已知来源正文保留，文字为来源 RGB `123456`/12pt/`u="none"`，文字框 noAutofit/零内边距。原生 conversion 仍返回 `validation.ok=false` 和具体人工复核告警。

独立 verifier 对 target、缺失 rId、自动下划线、字号、颜色、坏 GoTo、丢表格链接、扩大链接范围、重复 rId、来源身份变化共 10 项变异均拒绝，证据 `verifier-mutations.json`。脚本 Node 语法与 Python 编译检查通过。没有自行构建或打包。

## 浏览器与独立宿主状态

专属 smoke 不改共享主 smoke；环境 `PDF_PPTX_TEXT_LINKS_SMOKE_DIRECTORY`、`PDF_PPTX_TEXT_LINKS_SMOKE_PORT`（默认 4344）、`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`。root 已使用本批统一冻结运行包完成真实浏览器与一次独立 LibreOffice 转 PDF，证据如下。

专属 smoke 在实际下载完成后、独立 verifier 前先写 `saved-checkpoint.json`，保存真实 artifact、conversion result、来源/下载/manifest SHA、实际 JS 响应身份及检查错误；失败文件也保存实际 asset map 与 manifest SHA，便于修复独立核查后直接复用已签发字节，不重复浏览器工作。

实际浏览器目录 `/tmp/pdf-ap-arrange-links-pptx-browser`，`summary.json` 为 `ok=true`，真实 grant/cookie/CSRF、转换请求、发布、签发下载链路完成。来源 SHA 保持本节上述 `a90ba465…d57c`；实际下载 PPTX 9458 bytes，SHA-256 `01cf7d6b0be8a8d5df406adb27480dfee3169831c5808dede1aeb04d87837d93`。实际返回仍为 `validation.ok=false` 和人工核对告警，下载正常签发。

冻结 static `/tmp/pdf-ap-arrange-links-static` 的 manifest SHA-256 `8c79637a9733aeefbbd248d7754b9fcc9b0b898bf5144c2c81078eda83519451`；37 个实际 JS 响应 SHA 与冻结文件一致，asset/page/console/HTTP 错误均为空。复审直接读取 actual download、summary、saved-checkpoint、conversion 与 independent 文件，核对来源、下载和 manifest 身份一致；实际三张 slide 与其三份 rels 在去除随机 creationId 扩展后，与本线原生样本相同。没有重复浏览器或原生测试。

实际下载的独立 Zip/XML 检查 `independent.json` 通过。root 只执行一次 Impress 打开/转 PDF，exit 0；`rendered.pdf` SHA-256 `d223298a323bce4525a35e6b22987b44896f94b221cc3388608235d7a01922cd`。`host-independent.json` 为 `hostVerified=true`，实际宿主 PDF 保留 3 页，6 个 URI/GoTo 目标完全匹配：第一页 HTTPS、mailto、跳第三页与表格 HTTPS，第二页 HTTP，第三页回第一页；来源正文（含不可点击的 `Unsafe plain`）保留。只读复审确认该 JSON 的输入 PPTX、来源与实际渲染 PDF 身份相符。三页 PNG 的目视检查由 root 协调；本记录不代替尚未完成的任意复杂字体/版式验收。

## 实际宿主表格链接颜色未通过

root 目视本次宿主 PNG 发现 `Table link` 显示为蓝色。随后直接读取同一份 source/PPTX/rendered PDF 确认：来源表格 `Table link` 和 `Table plain` 都是 `#123456`；生成 PPTX 的表格链接 run 明确包含 `sz="1200"`、`u="none"` 和 `<a:solidFill><a:srgbClr val="123456"/></a:solidFill>`。实际 Impress PDF 的 `Table link` span 却为 `#0563C1`，邻格 `Table plain` 及正文 Web、Mail、Jump、HTTP、Back 均为 `#123456`。

该蓝色恰好等于实际 `ppt/theme/theme1.xml` 的 `a:hlink` 色 `0563C1`（`a:folHlink` 为 `954F72`）。这些证据强指向本次 Impress 对表格超链接采用主题色覆盖显式 run 色，而不是来源或转换 IR 丢失颜色；尚未跟踪宿主内部具体函数，也未验证其它 Office 消费端。没有修改全局 theme 或加入经验宿主补偿。

专属 verifier 的 `--rendered` 现同时记录来源、OOXML 和宿主的 6 个链接颜色观测及表格子集，写入同一实际目录的 `host-independent.json`：`hostLinkRelationshipsVerified=true`，但 `hostSourceColorFidelityPassed=false`，`tableLinkColorObservations` 精确记录 `123456 → 123456 → 0563C1`，`hostSourceColorFidelityIssues` 和 `remaining` 返回具体原因。旧字段 `hostVerified=true` 仅表示链接目标、页数和已知正文检查完成，不能泛称宿主原色或整体保真通过。

这次新增核查只读取已有 actual download 与同一份 `rendered.pdf`，没有重复浏览器、构建或宿主转换，生产与测试文件未改变。链接目标专项通过，实际宿主颜色专项未通过，`overallFidelityPassed` 保持 false。

PPTX 已知首行基线 +6.350708pt 没有可靠的正式逆映射，本批不作经验 Y 补偿、不缩字号、不栅格化可编辑文字，原诊断继续有效。`overallFidelityPassed=false`；复杂字体与任意版式整体保真未通过，已生成产物和非阻断下载契约保持。

最终 root 已目视实际宿主PDF全部三页，文字和表格可读，并据此新增上节表格链接颜色缺口；不声称颜色或完整任意版式保真通过。统一身份、HTTP和部署边界见 NATIVE_PDF_AP_ARRANGE_LINKS_ACCEPTANCE.md。
