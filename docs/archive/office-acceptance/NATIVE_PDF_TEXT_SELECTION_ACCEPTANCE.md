# PDF 文字选区样式验收（2026-11-11）

## 固定上游与边界

对齐源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- 协议复用 `apps/pdf/src/shared/ipc.ts` 的 `TextEditInput.styleRuns`：升序、不重叠的 UTF-16 code-unit 半开范围；支持字体、字号、RGB、粗体、斜体，缺省继承整对象样式。
- 前端 `pdf-selection-style-source.ts` 原样复用 pinned `color-runs.ts` 的 encode/decode/patch/splice/compact helpers。输入、粘贴、IME 结束后的 textarea input 按共同前后缀重定位样式范围，继承左边界样式。
- 原生 `replace-text-runs.ts` 使用源 exported `plannedCharStyles` 预测样式边界；实际分段、字体子集、缺字 fallback、glyph advance 由固定源 `applyTextEdits` 完成。
- 当前为显式选中 textarea 字符后应用/清除样式。保留 selectionStart/End/direction 并恢复焦点；不宣称页面内完整 caret 编辑、段落自动 reflow、源文档样式识别或富文本内容粘贴。
- 整对象样式栏变更清同字段 selection override 的后续实现与独立验收记录见 `NATIVE_PDF_TEXT_SELECTION_CONTROLS_ACCEPTANCE.md`；本文件保留原选区样式轮次的验收证据。

## 已验证

- 原生专属 `bridge/replace-text-selection.test.ts`：9 项分别通过（原 8 项一次定向集运行 + 新增 explicit-false 单项运行）。包含真实 AA/Courier12、BB/Times18 粗斜红、CC/Courier12 分段；实际 glyph advances 连续、整行 right/center 对齐；跨 LF 范围与行距；UTF-16 代理对/非法范围；选区显式 false 覆盖整对象粗斜体；字体 fallback；measurement 降级；保存后验收异常；大字号越界及跨行自覆盖。
- 独立 pypdf 读取实际 PDF 的嵌入 FontFile2、字体/字号/红色、基线、相邻 advance、right anchor，以及旧对象删除、邻近正文保留。
- 前端 `pdf-text-selection.test.ts` 与既有 `pdf-replace-text-style.test.ts`：4/4 PASS。覆盖 supplementary scalar、选区保留、输入继承范围、清除、fill/changed、disabled/dispose。
- native 失败和验收失败均保留已产生的实际 bytes/SHA，警告不标为验收通过；签发集成由公共链路负责。

## 浏览器验收

专属 `frontend/smoke/pdf-text-selection-smoke.mjs` 已通过 `node --check`。读取 `PDF_SMOKE_STATIC_DIRECTORY` 的 manifest/assets 并核验 HTTP 实际字节；真实键盘选区、焦点、样式、Undo/Redo、preview、保存 4→5、下载 SHA、new grant reopen、独立 pypdf。

真实浏览器 root01 已通过：`/tmp/pdf-text-selection-browser-20261111-root01/summary.json` 与 `independent.json` 均复读确认，另复看 `selection-configuration.png`、`reopened-final.png`。

- Chromium `140.0.7339.16`；固定静态目录 `/dev/shm/pdf-next-static-20261111-root02`；manifest SHA-256 `4f618f6766d44112982ccf8fd18384db72fec7bd8ba2e245d14c5f169fa68e09`；浏览器实际加载 36 个 JS/MJS 资源并逐个与磁盘字节比对。
- 独立 native 包 `/dev/shm/pdf-next-runtime-20261111`；CLI SHA-256 `d57204f18ee14eb55d9ac3d1b98a4e3cfa4b1e2dc941417072d64bdfaac2c270`（root 构建证据）。本域未改共享生产 static/dist。
- 真实键盘选中 `[2,4)` 后应用 Times18、粗斜体、红色，textarea 焦点与范围保留；撤销/重做后的 staged operation 完整一致；preview 回执 `appliedOperationIndices=[0]`、`skippedOperations=[]`。
- 实际保存修订 4→5，注册成功，下载 12,030 字节，重新签发 grant 打开修订5，来源 SHA 与下载一致。源 SHA `74aaedc01a5e958ac888f8dcd006dd08b56abfe79d49b109803253be83e9a7a9`；输出 SHA `b384cc94051c6fa4653b6060464f1cb2fdaa14f9244b466b77c853dc1ad57329`。
- pypdf 独立确认实际嵌入字体：AA 为 LiberationMono/12，基线 `(24,350)`；BB 为 LiberationSerif-BoldItalic/18，基线 `(38.400002,350)`；CC 为 LiberationMono/12，基线 `(62.375999,350)`。这是实际 native 字形 advance，不依赖浏览器字体估算。红色 `[1,0,0]`、另外两页正文、页面 box 均保留，无注释/表单替代文字。
- 页面、控制台、HTTP、资源校验错误数组全部为空；source 未改写。
- 保存返回 `validation.ok=false`、`native_source_review_pending`，明确业务事实与完整版式尚待重新核验；实际 PDF 仍正常签发、下载、重开，不把该软告警冒称为业务验收通过。

运行参数：`PDF_TEXT_SELECTION_SMOKE_DIRECTORY`、`PDF_TEXT_SELECTION_SMOKE_PORT`、`PDF_SMOKE_STATIC_DIRECTORY`。
