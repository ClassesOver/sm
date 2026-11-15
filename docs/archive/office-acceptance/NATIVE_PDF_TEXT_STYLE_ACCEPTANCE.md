# PDF 文字样式与多行对齐验收

日期：2026-11-11。固定比较源：GenOffice full source，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`；源码目录 `/home/junge/pros/genoffice-source-full`。

## 源能力与本次范围

- 固定源 `apps/pdf/src/shared/ipc.ts` 的 `TextInsertInput`（496–519）已提供 `font/bold/italic/lineLeading/lineXOffsets/align`，换行生成逐行文字对象。`src/main/text-edit.ts` 的 `applyTextInserts`（2121–2290）实际解析、子集化并嵌入字体，按页旋转设置文字矩阵。本项目继续复用该 writer。
- `apps/pdf/src/renderer/App.tsx`（5212–5236）的 `textInsertOffsets` 才计算对齐偏移；`align` 是元数据，不能仅转发 `align` 就声称居中/右对齐已经落盘。本项目从 writer 的真实嵌入字体经 PDFium 读取 glyph advance，再把偏移交回同一 writer 从不可变来源重写。没有实现另一个 PDF 排版引擎。
- 固定源插入对话框（11400–11510）有多行、字号、颜色、左/中/右对齐；其 UI 未提供字体/粗斜体选择。新增字体/样式 UI 依据的是已存在的引擎能力，不能说该源 UI 已有完全同样的选项。
- 固定源 `TextEditInput`（430–490）原生支持替换的字体、字号、颜色、粗斜体、多行、行距、逐行偏移、`styleRuns`、`translate`。`rebuildRun` 通过 paragraph `origin` 规范化用户空间，再以原 writer 重建。本轮已接整对象样式、手动多行、同源不同对象批量。
- 固定源 `resolveRebuildFont`（1034 起）明确：保留原字体时粗体可用同字形描边合成；显式选择字体才优先加载真实 bold variant。验收同时读取 native render mode 与 stroke width，不能仅凭 fontName 不含 Bold 就误报无粗体。
- 固定源仍可能因缺字或未安装的变体使用 fallback。本项目不会把 fallback 伪装成用户指定字体：真实生成输出保持可用，验收返回具体字体/样式替代告警。

## 已实现闭环

1. 插入文字：字体 Arial/Times/Courier（Linux 对应 Liberation Sans/Serif/Mono）、粗体、斜体、6–72pt、颜色、手动换行、空行、默认 1.2 倍或显式正数行距、左/中/右对齐；保持原有独立保存/来源 SHA/落点/真实预览确认机制。旧草稿省略新字段仍有效。
2. 原位替换：源 `sourceSha256/pageId/objectId/expectedTextSha256` 严格绑定；整对象字体、字号、颜色、粗斜体、左/中/右对齐、手动多行；允许空文本删除。保留现有 4000 字符上限，只有 LF 是控制字符例外。不同对象可同批替换，混合页面结构/图片/插入等其他 kind 明确要求分别保存。
3. 源对象始终从同一不可变来源 census 解析，不能以预览/重排后的索引冒充来源身份。重复目标、伪造来源、失效文本摘要、显著重叠歧义被拒绝使用。独占 Form 由 pinned matcher lift；共享模板由 native matcher 返回具体不支持原因。
4. 替换样式首版支持 PDF 用户空间中水平正向 baseline。对原文本矩阵旋转、倾斜或反向的对象明确跳过。页面自身 `Rotate` 与文字对象矩阵的旋转是不同概念。
5. 实际 writer 已返回的 PDF 字节不会因后验失败丢失。溢出、字体 fallback、native 复核异常均返回实际 PDF、实际 SHA/size、具体逐项告警；不把其标为验收通过。发布/下载由既有非阻断签发链继续处理。
6. 对齐的二次 writer 每次仍使用原来源；摘要绑定来源、完整操作、实际 output SHA、applied/skipped，重复同输入的 preview digest 稳定。原文、其他对象及页面边界均经实际产物重读核验。
7. Pinned replacement failure 的协议是 `{pageIndex,oldText,reason}`，并非 insertion 使用的 `editIndex`。同批部分 writer 失败后仍验收其他已生成修改，不会因为其中一项跳过就漏掉另一项的溢出告警。

## 定向测试证据

执行目录 `smart_reporting/reporting/pdf_engine`：

- `node --import tsx bridge/static-text.test.ts`：10 条通过（扩展当时完整专属文件）；包含四旋转、原文保护、真实字体、多行空行、pypdf 独立读取、测宽后验故障保留实际字节。
- 后续新增 `automatic font bold` 定向回归：1 条通过，核实自动字体的真实合成粗体，避免假 fallback 告警。
- `node --import tsx bridge/replace-text-style.test.ts`：初始 6 条通过，覆盖同源双对象、独占/共享 Form、post-write 故障以及独立 pypdf 实际字体、字号、颜色、基线和原文保护。
- 后续新增 `partial native writer`：RED→GREEN，1 条通过；一个对象原生 `FPDFText_SetText` 失败时另一个生成的越界对象仍保留并产生 overflow 告警。
- 后续新增 `actual selected font|keep original synthetic`：2 条通过；真实 Noto CJK fallback 告警保留可搜索中文、保留字体合成粗体、空文本删除。未重复完整项目测试。
- 后续新增同 stream 同 baseline 邻居回归：replacement BB 实际右对齐基线 233.2pt、static insertion 不因原文抽取合成尾空格误报，两条均 RED→GREEN。

执行目录 `smart_reporting/report_editor/frontend`：

- `vitest run src/pdf-static-text.test.ts src/pdf-static-text-host.test.ts`：31 条通过；真实宿主菜单配置、落点、Undo/Redo、预览确认、只读/来源失效/取消保护，旧无新字段草稿保持一致。
- `vitest run src/pdf-replace-text-style.test.ts`：2 条通过；独立整对象样式 binder 的显式序列化、fill/changed/disabled/dispose，以及来源/目标/混合批次校验。
- `node --check smoke/pdf-text-style-smoke.mjs`：通过。真实浏览器/冻结产物结果见下一节，不能将语法通过当成浏览器通过。

## 真实浏览器验收

专属 smoke：`frontend/smoke/pdf-text-style-smoke.mjs`，复用既有 `pdf-static-text-server.py`。服务器采用真实 grant/cookie/CSRF、生产静态资源、packed native engine、真实预览/保存/发布/下载路由；仅持久化仓储使用既有内存夹具。

root 统一构建/package 后运行：

```bash
PDF_TEXT_STYLE_SMOKE_DIRECTORY=/tmp/pdf-text-style-browser-20261111-root03 PDF_TEXT_STYLE_SMOKE_PORT=4306 node smoke/pdf-text-style-smoke.mjs
```

验收顺序：Courier BoldItalic 居中多行插入 → Undo/Redo → 实际 preview 确认 → revision 4→5 → 下载 SHA/readback → 新 grant 重开已有文字对象 → Times BoldItalic 右对齐多行替换 → 实际 preview 确认 → revision 5→6 → 下载 SHA/readback → 重开。独立 pypdf 检查嵌入 FontFile2、实际字体、字号、颜色、基线、旧目标删除和其他正文保护；JS/mjs 响应 hash 与冻结文件核对。

状态：**root03 实际通过**，证据目录 `/tmp/pdf-text-style-browser-20261111-root03`。Chromium `140.0.7339.16`；统一生产 manifest SHA `6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8`；30 个 JS/mjs 资源响应与冻结磁盘文件逐项 hash 一致。page/console/HTTP/asset errors 均为空。

- 来源 SHA：`9be3021d75a424cb1dc11462415b5733ce0405570ab5158fa9654886962eade5`；原来源仍未改变。
- 插入 revision 4→5，实际 PDF 7861 bytes，SHA `39bc1df67d374da87704d0e6f9156c55ec05e8ecef265912c7faff30b61184f9`；preview applied `[0]`、skipped `[]`，真实下载与新 grant 重开身份一致。
- 原位替换 revision 5→6，实际 PDF 13899 bytes，SHA `d44179468095973c4f53dceff2467a90eaab5f5c7ad8d66ab38777b7470a0b89`；preview applied `[0]`、skipped `[]`，真实下载与重开身份一致。
- 独立 pypdf 读回四行：Courier BoldItalic 18pt 的 `First insert` 基线 `[85.199997,200]`、`Next insert` `[90.599998,164]`，RGB `[.2,.4,.6]`；Times/Liberation Serif BoldItalic 14pt 的 `Changed` `[33.105999,200]`、`Again` `[50.213997,164]`，RGB `[.6,.2,.4]`。均存在实际嵌入 FontFile2；旧目标已替换，Next insert 与原三页正文/页面框保留。另对实际磁盘三份 PDF 重新计算 SHA 与独立读回结果一致。
- 已人工查看 `insert-configuration.png`、`replacement-configuration.png`、`replacement-preview.png` 和 `reopened-final.png`：配置选项与真实预览中已确认的执行清单相符；Changed/Again 的右对齐终点一致，Again 与保留的 Next insert 同 baseline 仍有清楚间隔，字体/颜色区分清晰；页面缩略图与重开内容一致。

历史记录：root01 的 asset listener 读取 302 redirect body 错误已修。root02 虽跑通链路，人工复核发现 PDFium 抽取追加的页面合成空格污染了 advance，Again 的错误基线 x=36.214；旧 smoke 只核对首行漏检，因此不列为最终通过。修复后使用请求逻辑 line 测实际字体 glyph advance，同 stream 同 baseline 邻居两条 regression 均 RED→GREEN；root03 四行独立断言已实际捕获正确 x=50.214。


## 仍存在的源对齐缺口

- 插入继续沿用本地早期安全范围：含任何 Annots、AcroForm、保护/签名、非默认 UserUnit 的源文件暂不开放。此为本地接入边界，不能表述为 GenOffice 引擎本身没有插入能力。
- 完整 caret/点击字符定位、连续键盘编辑、选区样式 `styleRuns`、选区字号/颜色/字体混排尚未接入。固定源 `App.tsx`（3356–3416、3507–3539）已有 caretRangeFromPoint 与选区维护机制；不是上游不支持。
- 段落聚类、自动折行/宽度重排、跨原对象段落编辑、`blockSource` 草稿重开尚未移植。固定源 `App.tsx`（3576 起）已做段落 reflow。
- 原文本矩阵旋转/倾斜/反向对象样式替换、同批文本与图片/页面结构修改暂未开放；不以自动改写源几何来假装支持。
- “取消原有已粗体/斜体”需要明确选择普通字体族；保留原字体不保证把原嵌入 face 从 bold/italic 变回 regular。源引擎的变体降级必须继续通过实际产物告警暴露。
- 共享 Form、复杂字体/缺字、无法无歧义定位的文字对象保留真实 native 原因；不能把局部支持表述成任意 PDF 完整编辑器。
