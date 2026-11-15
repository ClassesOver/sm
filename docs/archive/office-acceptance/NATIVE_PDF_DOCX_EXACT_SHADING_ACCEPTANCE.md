# PDF→DOCX 精确字符底色适配（2026-11-11）

固定 GenOffice 源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。这是本地转换保真适配：实际 PDFium 提取与分析已经为文字 Span 记录来源 `highlight` RGB，但 DOCX 重建仅调用最近命名高亮色映射。浅色 `FFF2CC`、`E2F0D9` 最近白色时被丢弃，相同其它样式的两个 run 随后合并成无底色文字。当前共享 DOCX 引擎已有 `Run.shading` 和 `w:shd w:fill` 写入能力，无需另造颜色或布局引擎。

## 最小变更和白色规则

生产仅修改 `pdf_engine/vendor/pdf2docx/src/rebuild/index.ts`：合法 6 位 RGB 先精确匹配既有命名高亮调色板，保留 15 个非白命名色的既有映射行为；精确白色 `FFFFFF`（大小写不敏感）沿用“不写 highlight/shading”的规则。其它合法颜色通过已有 `run.shading` 写为大写 RGB 字符底纹，不再近似为命名色。无颜色或非法 RGB 仍不写底色。`sameRunStyle` 增加 shading 比较，防止不同底色和普通文字合并。

既有导出辅助函数 `nearestHighlight` 保留兼容，没有更改其调用方 API。没有修改共享 DOCX writer、字体替换、版式、页面几何、依赖或其它导出格式。正文、表格 run 与 canvas 页面 frame 复用现有路径；脚注 `NoteRun` 当前不支持 highlight/shading，脚注底色明确不在本批支持范围。现有命名调色板行为保留，不把本批描述为重新定义 Word 所有命名色的色度语义。

## RED→GREEN 与类型检查

新增 `bridge/docx-exact-shading.test.ts`，首轮真实 RED 为 4 失败、1 个既有命名色/白色/非法值边界已通过，随后 GREEN 5/5：

- 真实 PDF 的浅色矩形经实际 PDFium→IR 后，DOCX 分别保留 `FFF2CC`、`E2F0D9`，黄色仍为 named yellow。
- 15 个既有非白命名色，以及 white、missing、非法长度/字符/带井号/带 alpha 的边界。
- 同一段落相邻不同 RGB、普通文字不串色、不合并。
- 表格单元格字符底色与 cell fill 分离，canvas frame 字符底色保留。
- 添加底纹后，除新增 `w:shd` 外，文字、字体、粗斜体、下划线/删除线、字距及段落几何 XML 不变。

证据 `/tmp/pdf-docx-exact-shading/{red,green}.log`，没有重复完整测试。生产单文件窄 strict tsc exit 0，证据 `production-types.log`。新测试入口闭包仅剩既有 `src/main/wasm-path.ts` 的两条 `Process.resourcesPath` 宿主声明诊断，见 `test-types.log`；不声称全项目 typecheck 通过。

## 专属来源和独立字节验核

专属文件 `frontend/smoke/pdf-docx-exact-shading-{source.py,server.py,smoke.mjs,verify.py}`。ReportLab 一页确定性来源含两种非调色板 RGB、原黄色命名色、普通文字和白底文字。来源 SHA-256 `d72b198cf0251a74ecbf4f9f3e4b3fbc50043528c72fcbf678ecb036e21f11cf`；独立 verifier 与重新生成工厂字节完整比较。

原生实际 DOCX SHA-256 `ee780393e1ef7108dabe31814e324b5af3adba85e91ec77e87dfdb44a46752de`，4599 bytes。`/tmp/pdf-docx-exact-shading/native-independent.json` 通过：实际来源 PDF 绘制 fill 与 DOCX 中两个精确字符底纹匹配，黄色保留 named highlight，普通/白色文字无底纹，来源前景色 `123456`、12pt、输出字体声明与可编辑 run 保留，无栅格化替代。转换返回仍为 `validation.ok=false` 和人工复核告警。

独立 verifier 对丢底色、近似色、错误 RGB、扩大颜色范围、普通文字串色、黄色命名语义变化、缺正文、字号、前景色、来源身份共 10 种实际 DOCX/来源变异均拒绝，证据 `verifier-mutations.json`。专属 Node 语法与 Python 编译检查通过。

## 浏览器与宿主验收状态

root 已完成真实浏览器实际签发下载和唯一一次 LibreOffice Writer 转 PDF。环境 `PDF_DOCX_EXACT_SHADING_SMOKE_DIRECTORY`、`PDF_DOCX_EXACT_SHADING_SMOKE_PORT`（默认 4345），其它 frozen static/runtime/Chromium 环境沿用。运行入口：

```sh
node smart_reporting/report_editor/frontend/smoke/pdf-docx-exact-shading-smoke.mjs
```

专属 smoke 使用真实 grant/cookie/CSRF、转换、发布和实际签发下载；DOCX 的 API 产物键使用既有 `artifacts.word`。收到转换响应后，在其它断言和下载之前先写 `conversion.json` 与 `conversion-checkpoint.json`；收到下载 body 后先保留 `download-response.bin` 和实际 status/SHA/size，再断言身份并保存 DOCX。独立 verifier 前另写 `saved-checkpoint.json`，记录实际 artifact、来源/下载/manifest SHA、实际资源身份与错误；失败记录保留 conversion result、实际下载身份和 asset map，不重复已完成 UI。

本次实际浏览器目录 `/tmp/pdf-shortcuts-nudge-shading-docx-browser`，`summary.json` 为 `ok=true`，来源 SHA 保持前述 `d72b198c…11cf`。实际 DOCX 4601 bytes，SHA-256 `c5db2b6712885cb0368f460028ee15957abbe80bf3dfb58c2f7ac954a3fd57f3`；实际返回 `validation.ok=false` 和人工复核告警，同时正常签发下载。独立 XML 核查通过，两个精确 RGB 底纹、named yellow 与普通/白色文字规则保持。

这条 DOCX 浏览器链使用 r1 static，manifest SHA-256 `c22dc903c579bb21472d9d8eab2ad7c16f0af1cce99537ed4cdb2a591f74a370`；37 个实际 JS 响应身份检查通过，asset/page/console/HTTP 错误均为空。浏览器目录已保存实际 manifest、conversion/download/saved checkpoint 和产物。r1 静态快照已归档到 `/tmp/pdf-shortcuts-nudge-shading-static-r1`，只读复审再次逐一核对该快照 manifest 和 37 个实际响应文件 SHA，全部匹配浏览器记录；未用随后可切换的同名 static alias 替代来源身份。后续最终构建包含表单并发 render 重复 overlay 与 detached controller 监听释放的窄修，DOCX 链未重复执行，本节只记录实际 r1 证据，不宣称后续版本重跑。

root 仅执行一次 Writer 打开/转 PDF，profile/output 分别为 `/dev/shm/pdf-shortcuts-nudge-shading-writer-profile`、`/dev/shm/pdf-shortcuts-nudge-shading-writer-output`，日志 `/tmp/pdf-shortcuts-nudge-shading-writer.log`。实际 `rendered.pdf` SHA-256 `4668c89a6b45ab935c0a9e3f71ccc69fe41cf95a09c9feb74e6350f08c5b83c8`，实际 1 页。该次宿主独立核查使用以下入口：

```sh
.venv/bin/python smart_reporting/report_editor/frontend/smoke/pdf-docx-exact-shading-verify.py DIR/source.pdf DIR/converted.docx --rendered DIR/rendered.pdf --output DIR/host-independent.json
```

`host-independent.json` 为 `hostExactShadingVerified=true`：直接读取实际 PDF 对应文字位置最终绘制的背景 fill，Peach/Green/Yellow 分别为 `FFF2CC`、`E2F0D9`、`FFFF00`，与来源匹配；普通/白底文字未串色，已知正文保留。root 已目视 `host-render.png`（SHA-256 `a733933808c8f2431c4e90a4a513a52bc9d2120d40a8f7ac5baec6707896a07f`）。只读复审确认实际 source、DOCX、rendered PDF 与 summary/host-independent 身份一致，没有重复 browser、原生测试或宿主转换。

此结果只验收本样本的精确底色，不扩大对齐、脚注或任意复杂版式支持承诺。完整内容/版式保真和脚注底色未通过，`overallFidelityPassed=false`；已有文件和非阻断下载契约保持。未自行构建、打包或运行宿主转换。
