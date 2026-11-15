# 同段正文、注释、布局与边框底纹组合

固定 GenOffice f8c17004 的 `components/ribbon-tabs.tsx:116 setParaAttrs` 调用 `setParagraphAttrs`，`ai/ops.ts:700 runSetParagraphAttrs` 合并段落 attrs，不排斥正文、noteRef、布局和装饰同时修改。本地独立新测试首次真实 Editor16项失败于 `docxOperations` 的装饰/布局互斥，真实DOCX16项失败于桥接 decoration batch conflict；RED日志 `/tmp/word-layout-decorations-front-red.log`、`/tmp/word-layout-decorations-zip-red.log`。

实现继续使用原协议：alignment、左/右缩进、段前/段后/行距四类布局操作，与 shading/borders 一起提取。装饰差分比较只剥离已有允许的布局与装饰 attrs，正文仍保持相同约束并交给可信 final-run 编译器处理。草稿和桥接同段冲突仅额外允许这四种布局，字段白名单、hash、独立 capability、保护与未知inline限制保持。未提升全局 editable，未新增客户端 XML 或新协议。

后端无需新生成流程：最终正文和notes runs先放入generated block，布局修改其当前format/rawPPr，最后原shading/borders writer合成当前rawPPr。不会用来源XML覆盖已编辑正文，也不会用来源pPr覆盖已修改布局。

新增真实Editor19项通过：脚注/尾注 × existing/insert/update/delete × 两方向，四类布局和双装饰、正文局部格式、撤销重做、草稿、clear/auto；普通无notes来源两方向；capability/hash/字段/未知段落属性拒绝。受影响的底纹/边框/段落布局前端23项通过。日志 `/tmp/word-layout-decorations-front-green2.log`、`/tmp/word-layout-decorations-front-affected.log`。

新增真实ZIP22项通过：两种notes/四种动作/两方向16项，普通无notes两方向2项，以及伪造hash、raw字段、无效布局值和保护4项；读取实际对齐、左右缩进、段前段后行距、边框底纹、notes身份、noProof和未改段落。受影响后端2项通过。旧“装饰与alignment应拒绝”断言改为仍禁止的direct formatParagraph。日志 `/tmp/word-layout-decorations-zip-green.log`（22项79.30秒）、`/tmp/word-layout-decorations-zip-affected.log`（2项17.24秒）。tsc退出0（`/tmp/word-layout-decorations-tsc.log`）。未重复上批93/44或完整测试。

已有notes起步的真实dev Chromium GUI exit0：正文局部格式、四类布局、双装饰、注释update/insert同批保存；重开改变布局及装饰、正文、update/delete；重开清除布局/装饰、正文、删除全部notes，三次真实Python patch保存下载、ZIP回读、最终修订4重开。刷新草稿和undo/redo通过，保留来源noProof/keepNext和未改段落，pageErrors=[]。日志 `/tmp/word-layout-decorations-gui2.log`。

第一次GUI已完成三次实际保存，但旧非notes部件全字节不变断言误把合法core属性保存更新当失败（`/tmp/word-layout-decorations-gui.log`）。固定源 `patch.ts:692` 明确布局真实保存仅更新core的modified/revision；改为校验这两项格式与revision逐次+1、其余core字段不变，其他非notes部件仍逐字节比对。没有改生产保存行为或隐藏失败记录。

普通来源起步、当批新增脚注和尾注的fresh dev GUI同样exit0（`/tmp/word-layout-decorations-fresh-gui.log`），三次真实patch保存下载/ZIP回读、草稿/undo、最终修订4重开通过，pageErrors=[]。两场景共6份新修订，4194已释放。

独立GUI入口 `smoke/docx-layout-decorations-gui-smoke.mjs`；新notes起步设置 `DOCX_LAYOUT_DECORATIONS_FRESH=1`。本批不构建static，最终生产构建由根任务统一安排。


最终生产构建：root统一tsc+Vite退出0（40.26秒，`/tmp/office-function-values-layout-build-budget-fixed.log`），预算与预算契约通过。existing/fresh两个built GUI顺序各执行一次，均exit0：三次真实Python patch保存下载/ZIP回读、刷新草稿、undo/redo、最终修订4重开通过；pageErrors=[]。所有实际加载JS返回200、响应SHA与static一致，未修改生产或static。

实际入口 `lazy-docx-main-BqX_pacj.js` SHA256 `03f304873bc085bf71c9a0ef152742489bb83d08f43febe322f4248d9b3a152b`，引擎 `lazy-native-docx-engine-Ct5Ep5gD.js` SHA256 `312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c`。

`layout-decorations`日志 `/tmp/word-layout-decorations-built-final.log`；最终实际文件 `/tmp/docx-insert-gui-rtqlrS/revision-4.docx`，38258字节，SHA256 `806bad502b8a271a1c4d0801469fe9bdf199e94451bddd6b041b66a07ce05065`。

`layout-decorations-fresh`日志 `/tmp/word-layout-decorations-fresh-built-final.log`；最终实际文件 `/tmp/docx-insert-gui-oIuiDu/revision-4.docx`，38258字节，SHA256 `288bb21723c2d32d1197c4e7d3aa4d7feb1ce74ac2a1e2247b8f9649205ecea9`。

六份新修订的实际文件路径、size、SHA256、document.xml SHA和构建chunk身份保存在 `/tmp/word-layout-decorations-built-identities.json`，独立ZipFile.testzip()均无错误。4194已释放；没有重复42/24项定向或全套测试。
