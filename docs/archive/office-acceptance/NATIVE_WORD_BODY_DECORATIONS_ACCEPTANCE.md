# 普通段落正文、局部格式与边框底纹组合验收

固定源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`Ribbon.tsx` 的边框及底纹走 `setParaAttr`；`ribbon-tabs.tsx:116` 转发 `setParagraphAttrs`；`ai/ops.ts:590` 使用 `{ ...p.node.attrs, ...patch }` 设置段落属性并保留正文。源没有同段改字后必须先保存的互斥规则。

本批关闭普通可编辑段落的完整 composition 缺口：改字、插删字、局部格式可以与单独边框、单独底纹或两者同时保存。不是增加新的协议类型；前端复用最终 `patchParagraphRuns`，两项段落属性保留原独立操作。既有组合只支持边框与底纹，不包含正文；本批覆盖了剩余部分。

实现仅涉及两个生产文件：

- `docx-note-paragraph-layout.ts`：对无正文投影复用 `docxOperations` 的属性与 capability 校验；只有普通 editable 来源且 source/current 都没有 noteRef 时，允许提取边框和底纹。保留 notes 来源四项布局边界，不改 main。
- `bridge/edit-docx.ts`：最终 run 计划按原始 hash 编译后，允许与各一次边框、底纹共存；对 generated block 当前 rawPPr 的段落壳依次应用原有 writer，将属性写回同一个 block，最终 run 不被 originalXml 覆盖。引擎 `generateParagraphXml` 在 rawPPr 存在时直接透传，因此不重建未知属性、不做第二次保存。

独立的 shading/borders capability、字段白名单、原始 hash、保护文档、复杂源、重复操作及未知 inline 保持严格。最终 runs 含新 noteRef 时也拒绝进入普通来源组合，避免 source 原来普通却通过本批 insertNote 越界。

验证证据：

- RED：四项前端真实 Editor 正规化场景报原布局白名单错误；九项 ZIP 组合报原 `note_body_batch_conflict`。新增 noteRef 边界及原 notes-layout 负向用例也经历 RED→GREEN。
- 前端相关四文件24项通过（新增5项）：notes模型存在/不存在、两种编辑方向、完整三者组合、独立清除/auto、撤销重做、草稿最终 run 恢复、capability/只读、未知 inline、notes 来源及其他布局混编拒绝。
- 新增 ZIP21项通过：三操作六种排列、单属性两方向、删除/auto、样式继承、rich rPr/noProof 继承、局部斜体/颜色和原粗体、keepNext、未改段落、其他部件 SHA；重复/hash/字段/保护/复杂源/伪造note marker/既有及新增notes来源拒绝。既有相关后端31项最初30通过、1项准确发现上述新noteRef越界；一行收紧后该项及其他四项相关故障窄测全部通过，没有重复完整测试。
- `tsc --noEmit` 退出0；相关 diff whitespace 检查退出0。
- 独立入口 `smoke/docx-body-decorations-gui-smoke.mjs` 复用真实 Chromium 与 Python `patch_docx` 设施。端口4194两种 dev GUI均退出0：普通 notes 模型、真实重复 footnotes 导致全局 notes 不可用。每种样本三次保存下载：先边框底纹再改字/局部粗体；重开后先改字/局部斜体再改边框底纹；重开后清除两项同时继续改字。刷新草稿、undo/redo、最终修订4重开均通过；所有非 document 文件部件 SHA、原 noProof/keepNext 和未改段落保留；pageErrors=[]。端口已释放。

日志：`/tmp/word-body-decorations-front-red2.log`、`/tmp/word-body-decorations-zip-red.log`、`/tmp/word-body-decorations-front-regression.log`、`/tmp/word-body-decorations-zip-green.log`、`/tmp/word-body-decorations-zip-boundaries.log`、`/tmp/word-body-decorations-inheritance.log`、`/tmp/word-body-decorations-new-note-green.log`、`/tmp/word-body-decorations-backend-regression.log`（包含已修复的一项RED）、`/tmp/word-body-decorations-tsc.log`、`/tmp/word-body-decorations-gui.log`、`/tmp/word-body-decorations-no-notes-gui.log`。

剩余独立缺口：含既有/新增 notes 引用的段落，正文与边框/底纹仍不能组合。样式切换、分页或其他段落布局与这组三者的组合仍为后续独立评估范围。本批未修改 workbook/main/vite/static，不执行完整套件、提交或推送；统一构建及最终构建预览由根任务安排。

最终构建验收：根任务统一 tsc+Vite 退出0（37.76s，`/tmp/office-zoom-stats-body-decorations-build.log`），预算和契约均退出0并冻结 static 后，两种来源分别运行一次 built GUI，均退出0、pageErrors=[]。每种包含三次真实保存下载及最终重开，正文、局部格式、两项段落属性的合成和清除、来源继承/其他 ZIP 部件保留全部通过。所有实际 JS 响应 HTTP200且响应 SHA256 与当前 static 一致；关键入口 `lazy-docx-main-uUigo26P.js`：`b9e0352cb4eee6618106fdd9abe370456bd451759b80c82e38e856f4aaf31227`，引擎 `lazy-native-docx-engine-DsROsJBD.js`：`29e787ebfd5fe24856ad8b1d9a5eadc96cbb2ca04e8b2f9d7711f39c42af35a6`。日志：`/tmp/word-body-decorations-built-preview-final.log`、`/tmp/word-body-decorations-no-notes-built-preview-final.log`。4194端口已确认无监听；未重复 unit/backend 测试。
