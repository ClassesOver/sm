# PPTX 审阅批注专项盘点

后续状态（2026-11-11）：本文“本地已有与未接线”为早期调查快照。经典根批注查看、新增、逐条删除现已接通，32项后端、19项前端、1项HTTP以及冻结构建浏览器经典/只读边界两链已通过；精确身份和证据边界见 `NATIVE_PPTX_CLASSIC_COMMENTS_ACCEPTANCE.md` 的“最终冻结浏览器与 HTTP 验收”。回复/解决仍不属于本固定源能力。

日期：2026-11-11。只读源码调查；固定 GenOffice HEAD
f8c17004fb730df11f0f743164ffd8b4281bb38c。未运行源 Electron、未构建、未运行完整测试，也未修改生产代码。本文仅覆盖 PPTX 批注族，不另列四格式总清单。

## 固定源的实际范围

| 能力 | 源 UI 与持久化链路 | 结论 |
| --- | --- | --- |
| 查看当前页批注 | Ribbon 的 onToggleComments → App.openComments / getComments → CommentsPane；页切换、路径变化及 annotationsNonce 后重新读取 | 已有真实读取与窗格状态；不是只画标签 |
| 新建根批注 | Ribbon.onNewComment 聚焦窗格；CommentsPane.submit → App.addComment → preload slides:add-comment → main.sessionTxn 的 addComment → pptx-ops → engine.addSlideComment | 已有可执行写入链，作者由 main.commentAuthorName 提供，使用经典批注部件 |
| 删除既有根批注 | CommentsPane 每条卡片删除按钮 → App.deleteComment → slides:delete-comment → sessionTxn 的 deleteComment → engine.deleteSlideComment | 已有按当前页、authorId、idx 定位的删除链；不是“删除全部批注” |
| 回复 | CommentsPane Props、SlideComment、IPC、pptx-ops 均无 reply / parent / thread 操作 | 本专项范围未发现实现；新增另一条根批注不能称作回复 |
| 解决／重新打开 | SlideComment 无 resolved 字段；UI、IPC、ops、engine 无对应操作 | 本专项范围未发现实现；隐藏窗格或删除批注不能称作解决 |

源读写身份是经典 p:cm 的 (authorId, idx)，另以 slide 作用域定位。不是现代线程批注的 thread/person 身份。引擎 comments.ts 的数据模型只有 authorId、author、initials、dt、idx、text；不应把现代批注、回复或解决状态视为已支持。

### 源码锚点

相对于 /home/junge/pros/genoffice-source-full/：

- apps/slides/src/renderer/components/Ribbon.tsx:2513：两个可用入口按 hasDoc 控制；没有回复／解决入口。
- apps/slides/src/renderer/components/CommentsPane.tsx：onAdd、onDelete、onCollapse，textarea 提交及每条删除；没有回复、解决或线程展开。
- apps/slides/src/renderer/App.tsx:2039-2086、4489：列表读取、dirty 状态、窗格；annotationsNonce 在 UndoRedo 后触发重读，批注不放进 RenderSlide。
- apps/slides/src/shared/ipc.ts:1003-1014、1685-1689；preload/index.ts:336-338：AddCommentOp / DeleteCommentOp 和 get/add/delete IPC。
- apps/slides/src/main/slides-main.ts:1475、4534-4577：sessionTxn 承载快照历史，批注写入后 markMetaDirty；4644 的保存经 writeDeckFile / commitSaved。
- packages/pptx-ops/src/ops/slide-ops.ts:687-728：addComment、deleteComment 注册与真实引擎调用。
- packages/pptx-engine/src/comments.ts:96、168、219：getSlideComments、addSlideComment、deleteSlideComment；archive.entries 写入经 savePptx 保存。

持久化写入 ppt/commentAuthors.xml、对应 ppt/comments/commentN.xml 及关系／Content Types。最后一条删除会清理已空的批注 part、所属关系和 override，作者表不等同于随之清空。源已有 notes-comments.test.ts 对新建后保存重开、不同作者／页面和最后删除清理的断言；本次只读了测试，没有把未执行的测试当成本轮运行证据。

## 本地已有与未接线

本地以下路径相对于 smart_reporting/：

- reporting/slides_engine/packages/pptx-engine/src/comments.ts 已有上述 get/add/delete，src/index.ts:286-290 已导出。comments.ts 与固定源逐文件 SHA 相同：83e5c0e5136bca600c8630f3f03a4e37343774135276f76965f108baecb74b5b。已有对应引擎测试，不需要重写批注格式或自建并行存储。
- reporting/slides_engine/bridge/edit-pptx.ts 的 inspect.slides 尚未投影 comments；Request 和 edit 分支无批注操作，因此原生宿主目前不能调用这些已有函数。保存时保留已有不透明部件，不等于已提供批注读写。
- report_editor/native_office.py::_ALLOWED_KEYS、_pptx_arguments 未接批注字段；report_editor/slides.py::_run_engine 无批注参数。不能只把前端按钮放开就声称可保存。
- report_editor/frontend/src/slides-main.ts::DeckSlide、SlideChanges、slideChanges、restoreNativeDraft 没有批注模型或 journal；不存在批注窗格的读取、历史／恢复或保存接线。
- report_editor/frontend/src/slides-native-ribbon.ts:202-203 的 newComment、commentsPane 虽保留源 actionId／中文图标，但均明确 unavailable:noWrite。只有入口外观，不是可执行能力。
- 本地 getSlideComments 仍是经典批注读取，不能把现代／不完整来源的无法解析误报成“没有批注”。报表 Markdown、Word 或 PDF 的审阅能力不补足此 PPTX 缺口。

## 最小可实施下一项

**先接当前来源页的只读经典批注窗格**：在现有 inspect 模型增加按原始 slide 身份的 comments 投影；在现有原生 PPTX 请求与 Ribbon commentsPane 接入列表、折叠、切页刷新。复用 getSlideComments；newComment 仍保持不可用。来源含现代或无法可靠核对的批注关系时给出具体只读提示，不把未知当作空列表，不阻断已有文件下载。

这项最小增量只关闭“查看”缺口，不能关闭新建／删除，更不能关闭源本就缺少的回复／解决。若下一项要求实际写入，优先在其后接**经典根批注新增**：复用 addSlideComment 和同一 NativeDraft／源 SHA／原始页索引，不自建文件外评论库；作者应来自宿主可信身份，不从任意客户端 author 值冒认。删除应另做 (authorId, idx) 来源身份与最后一条清理验收，不顺带批量开放。

### 真实验收边界

- 只读窗格：用至少两张来源页、两作者和相同 idx 不同 authorId 的实际 PPTX；中文／emoji／XML 特殊字符应按文本显示。切页、隐藏页及已重排来源定位正确；关闭重开窗格不改 draft，不发送 save/export。实际 built JS 身份、pageErrors 与布局几何要可核验。
- 只读读取：独立 ZIP/lxml 核对作者关系、当前页关系和 (authorId, idx, text)，区分无批注、经典批注和现代／无法识别来源。不能只用 mock 数组或截图证明实际 OOXML 来源。
- 根批注新增（后续写入项）：先用真实来源复现缺口，再验取消、空白／超限校验、UndoRedo、刷新恢复、来源重排、删页冲突、新建／复制页身份边界、未失焦保存及下载／修订2重开；原批注与未授权部件保留，正文文本及渲染不被评论写入改变。独立 ZIP/lxml／python-pptx 回读 comments/author/relationships，不能只检查 API 返回值。
- 新增任何签发步骤仍须遵守现有非阻断发布契约；批注来源拒绝使用不等于拒绝签发已生成且身份可信的文件。

本次结论来自限定符号链与逐文件身份核对；未对源桌面运行时、本地真实用户 HTTP 会话或未实现的回复／解决作验收通过声明。
