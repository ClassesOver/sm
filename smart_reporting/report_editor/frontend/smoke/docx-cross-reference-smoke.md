# Word → GenOffice：普通书签交叉引用增量（2026-11-11）

## 源事实与范围

固定源：/home/junge/pros/genoffice-source-full，ref f8c17004fb730df11f0f743164ffd8b4281bb38c。
apps/docs/src/renderer/components/ribbon-insert-tab.tsx 的 CrossRefModal 通过 collectBookmarks 列表插入带 refField(name) 标记的预览文字；源 generator 将其输出为真实 REF complex field，使用 begin / instrText / separate / 缓存正文 / end。

本增量采用相同的 REF 机制，但缓存取已保存普通书签的精确范围原文，不接受客户端 name、preview、number 或 genXml。初始支持单段、非空、名称合法的普通正文书签；在另一无书签的普通顶层正文或标题段落可信光标处插入。缓存不会自动更新；可在 Word 中更新域。没有新增 PAGEREF、页码交叉引用或全局域更新。

## 接口与信任边界

- bridge inspectDocxCrossReferences(bytes) 返回 sourceSha256/sourceId、targets、bookmarks、只读原因；复用书签公开 inspect，不改书签模块。
- bridge patchDocxCrossReference(bytes, operation) 仅接受 kind/sourceId/bookmarkId/targetId/expectedParagraphSha256/offset 六个字段；kind 为 insertCrossReference。
- 前端导出 verifiedDocxCrossReferenceModel、NativeDocxCrossReference、createDocxCrossReferenceControls、normalizeDocxCrossReferences、replayDocxCrossReferences、docxCrossReferencesOf、assertDocxCrossReferencesBatch。
- 每批仅一条独立意图。PM 同一事务插入只读 inline atom 与 doc attr；真正 Undo/Redo 同步恢复。normalize 逐字核对完整目标段投影后恢复基线供普通 diff；改缓存、换书签、改字段结构均拒绝。
- 拒绝保护文件、过期来源或段落身份、重复/非法书签身份、跨故事名称碰撞、复杂/跨段书签、代理对中点、非法偏移及未保存正文。插入目标包含任何书签范围时保守拒绝整段，防止端点归属歧义、自引用与循环依赖。
- 服务端从源文件再推导缓存与字段指令。仅替换授权 document.xml 目标段中的一个 run；段落属性、run 格式、未知属性及其他 ZIP 部件原字节保全。

## 已运行专项验证

bridge：node --import tsx --test bridge/tests/docx-cross-reference.test.ts，10/10 GREEN。前端：npx vitest run src/docx-cross-reference.test.ts，5/5 GREEN。均先记录缺失实现 RED，再实现；未知属性、xml:space 及实体边界增量另有 RED→GREEN。没有全套测试、全局 build/tsc、提交或部署。

覆盖真实 REF 与可信缓存、ZIP 部件身份、原文格式保全、伪造来源/锚点/缓存/XML、UTF16 代理对、自引用、重复名、跨段/复杂/跨故事书签、保护文件、空段、属性值含大于号、未知 w:t 属性、伪 xml:space 元数据与本地命名空间改绑；数字实体以原始 XML 单次解码，并将旧书签 run 边界换算成真实 UTF16 偏移；实测 parseDocx→blocksToPmDoc→Editor 与修正模型一致。字面 &amp;#22270; 等被旧核心二次解码、导致投影不一致的来源明确只读并拒绝修改，未改旧书签或核心解析器。前端覆盖真实控件点击、事务 Undo/Redo、精确投影与回放、结构篡改、锁定及模型验证。

## 冻结浏览器证据

脚本：smart_reporting/report_editor/frontend/smoke/docx-cross-reference-smoke.mjs。支持 DOCX_TEST_DIST、DOCX_EXPECTED_MANIFEST_SHA256、DOCX_CROSS_REFERENCE_EVIDENCE、DOCX_CROSS_REFERENCE_PORT；必须匹配冻结 manifest 才运行。每个实际加载 JS 均与磁盘 SHA256 核对，记录 manifest 前后身份。

脚本使用真实 locator.click 插入和保存；验证 Undo/Redo、localStorage 恢复、真实 Python→Node 保存、下载字节身份、下载后重开以及 lxml/ZIP 独立验证；成功截图为证据目录 success.png。API 路由是本地夹具，不声称生产鉴权全链；夹具明确返回验收失败及原因，同时仍返回并核对下载链接。

最终冻结浏览器专项已完成且仅运行一次：ok=true，errors=[]。证据目录 /tmp/sr-word-references-20261111/cross-reference-final，成功截图 success.png 已目视检查；完整请求、JS 摘要与文件验收记录为 evidence.json。

- 静态冻结目录：/tmp/sr-word-references-20261111/final3-static。
- manifest 前后 SHA256 均为 ee917f165ef2810a6abfbd41c0094bdc3ff258137e93735cf32d3c114efdac27。
- 122 个实际加载 JS 与冻结磁盘字节摘要一致。
- engine：/tmp/sr-word-references-20261111/final-engine，冻结桥 SHA256 ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6，执行后再次核对一致。
- 真实点击 SavedTarget 插入、真实点击保存、事务 Undo/Redo、本地草稿恢复、Python→Node 保存、下载字节身份与修订 2 重开均通过。
- 独立 ZIP/lxml：只有 word/document.xml 改变；全部 XML 有效；真实字段指令为 REF SavedTarget 加超链接开关，缓存 Trusted 😀 & cache，左右两段原 bold run 保持，原书签标记保留。
- 夹具返回“交叉引用版式待复核”的验收失败原因，浏览器仍取得可核验 Word 下载，不将验收标为通过。

新增实体前端集成测试通过 node --import tsx 子进程获取真实后端模型，避免把服务端检查器直接纳入前端 TypeScript 编译边界。最后该新增 case 定向运行 1 passed / 4 skipped。
