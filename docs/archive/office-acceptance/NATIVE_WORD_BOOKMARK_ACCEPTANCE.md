# Word 书签增量验收

书签按固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的实际 Bookmark 管理器范围实现：列出、定位、在普通正文精确选区创建，以及删除。固定源管理器创建的是光标所在段落属性，不支持按选区界定书签；本地新增的精确选区能力因此使用独立受信操作，不改变正文文本或段落属性。

本地只接受已由原 DOCX 字节核验的书签模型与操作。创建支持顶层普通段落/标题跨文本 run、跨连续段落的 UTF16 精确范围；删除只移除可信书签的范围端点。普通已有书签可列出、定位、删除；复杂包装中的书签保留在列表并只读。重复名称/ID、孤立端点、保护文档、命名空间歧义、域或内联对象范围拒绝修改。保存只外科修改 `word/document.xml`，其它 ZIP 部件保持原字节。

独立回归：bridge `bridge/tests/docx-bookmarks.test.ts` 7 项，frontend `src/docx-bookmarks.test.ts` 5 项。最终冻结网页与真实 Python/Node bridge 验收已通过，证据由 smoke/docx-bookmarks-smoke.mjs 写入 /tmp/sr-word-high-priority-20261111/bookmarks-final/evidence.json。

最终构建目录 /tmp/sr-word-high-priority-20261111/final2-static，manifest SHA-256 ae3123670680d5fc2a0e4529d61a560072b26c44cd67f4935fd10da223c3526a。真实 Chromium 通过普通正文精确选区创建、一次 Undo/Redo、reload 恢复、定位，以及创建保存下载→新修订2删除保存下载→新修订3重开。两次均只改变 word/document.xml，所有 XML 有效；122 个浏览器 JS 文件与磁盘 SHA 一致，errors=[]。来源/保存 API 为本地授权及修订夹具，保存调用真实 Python/Node bridge，不能冒充生产鉴权、桌面 Word 或打印等价。

真实鼠标曾暴露列表在 blur 事务重绘时吞 click：定位/删除按钮新增 mousedown.preventDefault 保持 PM 选区，5 项 frontend 测试含该事件回归；主视图恢复结束后重刷控件解除临时锁。最终脚本使用 locator.click，不绕过事件链。此前诊断证据保留在 /tmp/word-bookmarks-browser-20261111。

创建下载 36941 字节，SHA-256 c5a5b8fe4e818265b4d6c8e64de6bbd8be47f2aca9c5887739be0b5fb92bf626；删除下载 36912 字节，SHA-256 7e99ef97d888b6ab2cefa00950eacbbd046ee26746a1d3be9e7ed30c4fdaacc2。保存响应中的验收失败原因仍展示且下载照常保留，没有将验收失败标成通过。
