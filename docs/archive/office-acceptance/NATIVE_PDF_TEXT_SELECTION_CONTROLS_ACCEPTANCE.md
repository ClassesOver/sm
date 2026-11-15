# PDF 选区样式继承与状态验收（2026-11-11）

## 固定源依据及本批范围

固定上游 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`apps/pdf/src/renderer/App.tsx:3506–3578` 的 `applyDraftStyle` 明确：whole-draft 改样式后，仅把本次涉及字段用 `patchStyle(key,{field:null})` 清回继承；其他字段和 UTF-16 位置保留。上游统一样式栏把 collapsed/select-all 当 whole，本项目保留已经存在的显式整对象栏与选区栏，不引入完整 caret 或自动 reflow。

仅修改 `frontend/src/pdf-replace-text-style.ts`、`pdf-text-selection.ts`；新增专项 tests/smoke。本批没有 native writer、operation schema、pdf-main、公共 server、生产 bundle/hash 变化。

## 行为与接口

- 选区 binder 新增 `clearFields(touched)`，支持 `font/size/color/bold/italic`；直接复用已逐字固定源 helper `patchStyle`，所有 ranges 的触及字段清回 inherit，空 ranges 自动 compact 丢弃。
- 整对象栏真实 input/change 事件映射到该方法。字体、字号、颜色（含指定颜色开关）、粗体、斜体各自仅清同字段；对齐与行距不改 selection runs。程序性 `fill` 不触发清除。
- 新只读“当前选区”逐字段显示统一 override / 继承整对象 / 混合，不改变待应用的样式控件。dataset 状态供专项 browser 验证；明确反映 override，未冒称已经识别原始 PDF 每字符的有效字体。
- select、keyup、pointer/mouse、input、textarea 活跃时 document.selectionchange 更新状态；选区失效或 collapsed 时应用禁用，选区没有 override 时清除禁用。
- 清除仅作用选区字符；保留外侧 ranges，并恢复 textarea 焦点及 UTF-16 start/end/direction。复用既有源 splice/encode/decode/compact 算法，没有新增 caret/reflow 排版器。

## 专项测试

`src/pdf-text-selection-controls.test.ts` 初始三项全部 RED：whole 同字段 override 未清、缺少当前状态。最小实现后四项 PASS：

1. whole 五字段清除只影响本字段，其他字段、范围与 backward direction 保留；align/leading 不改 runs。
2. keyboard 与 selectionchange 切换统一、mixed、inherit；只读状态不变更 runs；collapsed 应用禁用。
3. 清除 keyboard selection 仅拆分当前范围，恢复 focus/direction。
4. whole 字段变更遍历所有 ranges，最后 override 清除后不残留空 run。

既有 `pdf-text-selection.test.ts` 与 `pdf-replace-text-style.test.ts` 共四项在实现后通过。未重复完整项目测试，无 native 修改而未重跑 native 全集。

## 真实浏览器专项

新 `frontend/smoke/pdf-text-selection-controls-smoke.mjs`，`node --check` 和专项 `git diff --check` 通过。沿用真实原生编辑 HTTP、PDF.js、grants、CSRF、preview/save/download/reopen，仅fixture持久化仓储使用内存。读取 `PDF_SMOKE_STATIC_DIRECTORY` 的 manifest/assets，与浏览器实际响应字节逐一核验。

计划覆盖真实键盘选区 uniform→mixed→inherit，整对象五字段逐个清除而保留未触及字段，选区 clear/focus/direction，重新 apply 后保存修订4→5、下载实际SHA、new grant reopen、pypdf独立字体/基线/正文保留。运行目录使用 `PDF_TEXT_SELECTION_CONTROLS_SMOKE_DIRECTORY`，端口 `PDF_TEXT_SELECTION_CONTROLS_SMOKE_PORT`；大临时产物建议 `/dev/shm`。

真实浏览器专项使用冻结 manifest `e84e640cc9d665b0d472de5eca28906ec1416f8e796f9ad577365d946b4a1b5e`，Chromium 140。summary `/tmp/pdf-continue-text/summary.json`，独立 PDF 回读 `/tmp/pdf-continue-text/independent.json`，实际下载 PDF SHA-256 `6cc02e625a887933a2900be4183db3393350ca9a871f691a3443aef9d9624265`，来源 SHA-256 `71765df49f5d913c987ff556d96663a906f8b7000eb0b4896b55135e8d1b146b`。结果 `ok=true`、`sourceUnchanged=true`、无页面/控制台/HTTP/资源错误；uniform→mixed→inherit、整对象触及字段清理、外侧 run 保留、清除后焦点与 selection direction 均通过。画面证据见 `/tmp/pdf-continue-text/whole-fields-cleared.png` 与 `selection-cleared.png`。
