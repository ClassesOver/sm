# Word 源尺规冻结构建冒烟

只启动 Vite preview，不触发构建。先冻结统一前端产物和 DOCX engine，再运行：

    DOCX_TEST_DIST=/dev/shm/word-static \
    DOCX_TEST_ENGINE=/dev/shm/word-doc-engine \
    DOCX_EXPECTED_MANIFEST_SHA256=<冻结manifest的sha256> \
    DOCX_TEST_OUTPUT=/dev/shm/word-ruler-smoke \
    node smoke/docx-ruler-smoke.mjs

可选 DOCX_RULER_CASE=readonly 或 editable、DOCX_TEST_PORT=4287。

验证：
- 只读/可编辑模式均可显示源尺规；纯显示不改文档、草稿、保存状态。
- 原封 GenOffice 标记与刻度、缩放后尺规和纸张几何对齐。
- tabs、left、firstLine、hanging 显示禁用与原因，键鼠不能绕过。
- 只读模式右缩进及页边距也不可写。
- 可编辑模式源右缩进键盘写回、撤销重做及左页边距写回。
- 捕获的真实保存操作交给 patch_docx，独立 python-docx 回读右缩进90、左边距1530、右边距1440。
- 验收失败仍可下载Word，下载文件身份与保存结果一致；重开修订2后尺规反映保存值。
- 浏览器实际加载JS与冻结磁盘文件逐份哈希一致，manifest与engine运行前后身份不变。

产物输出 result.json、两种模式截图、重开截图、下载的真实DOCX。失败保留failure.html与failure.png。

单测 src/docx-ruler.test.tsx 另覆盖拖动开始后的文档/选区/节/缩放/锁变化，以及隐藏和销毁时源document监听与辅助线清理。禁止用完整测试替代此次窄测试。
