# 来源注释标记后的原生输入

真实浏览器定位：保存重开后在末尾 source noteRef 后直接输入，ProseMirror 会继承标记的 marks/rawRPr；固定 GenOffice f8c17004 的 runsToInline 和原生输入同样如此。本地编译器只允许从 text 继承，导致拒绝合法键入。原始证据 `/tmp/word-notes-decorations-gui-debug.log`。

前端仍要求严格相同 opaque 格式，在找不到同格式来源 text 时允许借用同源 noteRef 的格式。来源 kind/id/block/hash/referenceIndex 必须与 notes model 注册引用一致。协议继续只接受 text/inheritFrom/style；草稿从可信标记 marks 构造普通 text，去掉标记 attrs，并经原编译器复验。与普通来源 text 继承一致，不额外要求 marker 最终保留或邻接；删除原引用仍需匹配 deleteNote。

后端克隆可信 Run，仅移除 noteRef 身份。实际 ZIP 检查发现固定源 noteRef 解析仅留 rawRPr，普通生成器因此把未建模的 superscript/rStyle 等视为删除。本地 parse.ts 的该分支现复用已有 buildRun(...keepEmpty=true) 补齐格式模型，原 rawRPr 与标记输出保持原样，不增加第二次文档解析。源码归属和 SHA 更新于 slides_engine/SOURCE.md 与 UPGRADE.md。

真实 Editor 新测试脚注/尾注2项通过：原生 insertText 经过实际 guard，连续输入、部分加粗、草稿、undo/redo；同批删除 marker 保留文字可恢复，伪造 block/hash/ordinal 拒绝。ZIP新测试5项通过：两种 note 的普通文本继承、noProof/superscript 保留、原标记不重复、保存后再删marker编辑、同批删除并在非邻接位置复用同源样式，以及无删除意图/坏坐标/raw字段/来源乱序拒绝。前端相关25项通过，另6个现有notes/普通段落回归文件68项通过。新ZIP与既有notes/decorations三文件共44项通过（138秒），未重复完整测试。日志 `/tmp/word-note-reference-input-front-regression.log`、`/tmp/word-note-reference-input-notes-regression.log`、`/tmp/word-note-reference-input-zip-regression.log`。

独立dev GUI `smoke/docx-note-reference-input-gui-smoke.mjs` exit0：真实键盘 End 后确认前一节点是 docNoteRef，再连续输入并局部加粗；撤销重做、刷新草稿、真实 Python patch 保存下载并 ZIP 回读；重开再输入、删除注释、再保存重开，无重复引用，pageErrors=[]。最终日志 `/tmp/word-note-reference-input-gui-final.log`；Editor和ZIP前后失败/成功证据保存在 `/tmp/word-note-reference-input-front-*.log`、`/tmp/word-note-reference-input-zip-*.log`。

未声称新增 pending marker 提供任意原始格式，未知复杂 inline、保护来源仍保留原限制。前端构建和三个 built GUI 由根任务统一执行，本文件当前仅记录dev证据。


2026-11-10 最终生产构建验收：统一 tsc+Vite exit0（40.09秒），预算及预算契约通过。以下 Chromium built GUI 仅各执行一次，所有JS返回200、实际响应SHA与static一致、pageErrors=[]。共同加载 `lazy-docx-main-BhWm8x5A.js`（SHA256 `ad79e0ef59b854dc475643b0e808cd74f876bc8633a040974e2bae806b7213c4`）和 `lazy-native-docx-engine-Ct5Ep5gD.js`（`312f2efe536c5c087b1d8eb5d4969b640258b3f4064273c09cdca43c760ff09c`）。

`note-reference-input` built通过；日志 `/tmp/word-note-reference-input-built-final.log`。真实patch保存/下载并ZIP回读2次，最终修订3重开通过；最终实际文件 `/tmp/docx-insert-gui-m2V0PE/revision-3.docx`，37758字节，SHA256 `d4c7fbb6a0c1cf070c39fbf255f4e0cea72b1f193b2f24616b70c396be83b239`。独立ZipFile.testzip()及document.xml SHA检查通过。

三场景共8份新修订的实际路径、size、SHA256及document.xml SHA保存在 `/tmp/word-final-built-identities.json`；4194已释放，无static修改或重复全测。
