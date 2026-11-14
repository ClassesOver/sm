# 演讲者备注面板来源与范围

固定来源 GenOffice 提交 f8c17004fb730df11f0f743164ffd8b4281bb38c（Apache-2.0），本地只读参考 /home/junge/pros/genoffice-source-full。许可证见 vendor/genoffice/LICENSE。

- apps/slides/src/renderer/App.tsx 4402–4432 行：普通 textarea 展示并编辑备注，默认展开，支持折叠，失焦 flush。本地采用相同行为，保留一个 textarea 节点，避免每次输入丢失光标。
- apps/slides/src/shared/notes-draft.ts：草稿绑定来源，换页前提交，并维护已加载/已提交基线。本地面板以来源 slideIndex 绑定同步回调；文档 SHA、作用域、修订身份由主编辑器复核。

notes-draft.ts 的 SHA-256：f8c8ba26b2e473b3ba33f313aa66b26147b2c5a1719fff026951124c31f4d809。

## 接口与失败处理

validateSlidesNotesDraft(changes, slides) 校验 notesEdits 精确 {slideIndex,text} 结构、每来源唯一、可编辑能力、删除和来源复制冲突，返回独立规范化结果而不修改其他草稿。每条原始字符串最多 20000 个 UTF16 码元，批次最多 200 项及 200000 个原始码元。拒绝 C0（保留 tab/LF/CR）、孤立代理和 U+FFFE/U+FFFF；CRLF/CR 转 LF，仅移除末尾 LF，保留空格和内部空行。

createSlidesNotesPane(host,{onChange,onError?}) 返回 update({slideIndex,text,editable,reason?,visible}):boolean、flush():boolean、setVisible(boolean):boolean、dispose():void。输入同步回调，已提交文本不重复回调；IME 结束前不提交，期间 flush 返回 false。blur/flush 收尾规范化显示。换页、隐藏或转只读先提交旧绑定；提交失败保留文字和原因并返回 false。主编辑器须据此阻止相应换页、保存和历史动作。

同来源刷新不会覆盖未收尾/未提交输入，回调重入也不会覆盖输入；已提交基线可由外部 undo 更新。只读内容采用 textarea.value 与 textContent 展示。dispose 是取消与销毁，不隐式写入；旧节点事件无效。选择器 .slides-notes-pane、[data-notes-panel]、[data-notes-text]，textarea 的 aria-label 为“演讲者备注”。

slidesNotesReadOnlyReason 将 notes_edit_master_* 与其他 notes_edit_* 内部原因转换为中文只读提示，保留已有自然语言原因；仅影响显示，不改变来源能力或允许写入。备注输入框通过实例独立的 aria-describedby 关联只读说明，仍允许选中复制原文。

可选 onVisibleChange(visible) 仅在面板可见状态实际变化时通知主编辑器，使本地折叠按钮与 View 按钮共享状态；同状态 update、提交失败和销毁后不通知。

这是备注编辑面板，不代表演讲者视图、计时器、双屏输出等能力已实现。验证见 slides-notes.test.ts；未扩展固定源的拖动调高等交互。
