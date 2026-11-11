# notes 引用段落边框底纹与正文组合

固定 GenOffice f8c17004 的 `setParaAttrs` 经 `runSetParagraphAttrs` 合并段落 attrs，不排除内联 noteRef，且保留正文。本批关闭本地 notes 来源边框/底纹与正文、局部格式、notes insert/update/delete 的组合限制。

可信能力：只有普通 editable 来源，或成功建立 notesPlanner 并满足 editableNoteReferenceBlock 的来源，才会进入原 shading/borders writer 的只读可写性探测。两项独立 capability 可为 true，原全局 editable 仍为 false；复杂图案、主题属性、非单实线、保护、损坏 notes 和未知 inline 均保留限制。前端共享 capability 目标允许 noteRef，normalizer 逐一核对来源 marker 的 kind/id 和 notes entry.references(block/hash/referenceIndex)，包括同一 note 的多个引用。草稿仍按原 hash 先恢复段落属性，再用原 notesModel、notes操作和最终 run 计划恢复，客户端不提供 XML。

后端复用同一 generated block 当前 rawPPr 合成路径；note部件和引用身份继续由 planner 分配、校验及回读。未放开样式、分页及其他未知属性组合，不提升全局 editable。

证据：新增真实 Editor18项和 ZIP24项通过，涵盖脚注/尾注、existing/insert/update/delete、两方向、清除/auto、撤销、草稿、重复引用、capability/身份/字段/保护/复杂源/损坏notes/未知inline。相关前端最初80项通过、一个旧伪造 notes model 用例发现缺少来源entry核对；加严格来源核对后该文件及新增测试22项通过，另一个多引用ordinal窄测通过。相关后端12项通过，tsc退出0。原限定“不允许notes+装饰”的历史测试已更新为新行为。

真实 Chromium140 两个dev GUI均exit0：已有脚注起步，以及普通来源起步后本批新增脚注和尾注。每种三次真实patch保存下载：双装饰+正文局部格式+update/insert；重开后正文局部格式+双装饰+update/delete；重开后clear+正文+delete全部notes。草稿刷新、undo/redo、最终修订4重开通过。来源正文run/noProof、keepNext、非notes部件和未改段落保留，pageErrors=[]，4194释放。

独立入口：`smoke/docx-notes-decorations-gui-smoke.mjs`（fresh来源加`DOCX_NOTES_DECORATIONS_FRESH=1`）。日志：`/tmp/word-notes-decorations-front-red.log`、`/tmp/word-notes-decorations-zip-red.log`、`/tmp/word-notes-decorations-front-green2.log`、`/tmp/word-notes-decorations-zip-green.log`、`/tmp/word-notes-decorations-source-trust-green.log`、`/tmp/word-notes-decorations-reference-ordinal.log`、`/tmp/word-notes-decorations-backend-regression.log`、`/tmp/word-notes-decorations-tsc.log`、`/tmp/word-notes-decorations-gui3.log`、`/tmp/word-notes-decorations-fresh-gui.log`。

该GUI在来源marker前的文字边界续写，未据此宣称所有 notes 邻接输入已正常：重开后terminal noteRef之后直接键入会继承marker rawRPr，被既有最终run编译器拒绝。该独立BUG已经真实GUI定位（`/tmp/word-notes-decorations-gui-debug.log`），由后续独立计划修复，不通过放宽opaque校验掩盖。本批不构建前端、不改static/workbook/vite；统一构建由根任务安排。

后续独立修复：末尾来源 marker 后输入 BUG 已由 `NATIVE_WORD_NOTE_REFERENCE_INPUT_ACCEPTANCE.md` 的真实 Editor/ZIP/dev GUI 覆盖；此处原始失败与本批在标记前输入的证据仍保留，不追溯改写历史结果。


2026-11-10 最终生产构建验收：统一 tsc+Vite exit0（40.09秒），预算及预算契约通过。以下 Chromium built GUI 仅各执行一次，所有JS返回200、实际响应SHA与static一致、pageErrors=[]。共同加载 `lazy-docx-main-BhWm8x5A.js`（SHA256 `ad79e0ef59b854dc475643b0e808cd74f876bc8633a040974e2bae806b7213c4`）和 `lazy-native-docx-engine-Ct5Ep5gD.js`（`312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c`）。

`notes-decorations` built通过；日志 `/tmp/word-notes-decorations-built-final.log`。真实patch保存/下载并ZIP回读3次，最终修订4重开通过；最终实际文件 `/tmp/docx-insert-gui-wGbFnp/revision-4.docx`，38193字节，SHA256 `f4f1f3eb71b9797f2e6ce2bc193598d085f7cc2f5bfa112abacc8e29247fa38e`。独立ZipFile.testzip()及document.xml SHA检查通过。

`notes-decorations-fresh` built通过；日志 `/tmp/word-notes-decorations-fresh-built-final.log`。真实patch保存/下载并ZIP回读3次，最终修订4重开通过；最终实际文件 `/tmp/docx-insert-gui-OjlsVF/revision-4.docx`，38180字节，SHA256 `92db866e89e88d53c67dc9d6795823ea199d784e2c12da89f46ee51aebfa4ab0`。独立ZipFile.testzip()及document.xml SHA检查通过。

三场景共8份新修订的实际路径、size、SHA256及document.xml SHA保存在 `/tmp/word-final-built-identities.json`；4194已释放，无static修改或重复全测。
