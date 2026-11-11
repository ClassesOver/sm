# Word 自动目录与批注线程增量

2026-11-11，固定 GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。

“引用 → 目录／更新目录”复用源 generateTocFieldXml，按已保存标题生成真实 Word 目录域。目录需独立保存，插入位置限已授权段落首尾；更新只接受可完整识别的目录域，支持普通 Word 目录内容控件外壳，保留同容器目录标题、尾部分页符与非目标 ZIP 部件。目录域前后同段正文、锁定内容控件、无法核实身份的结构拒绝修改。浏览器暂不计算缓存页码，Word 更新域后计算页码；不把这一阶段称作完整目录排版对齐。

已有批注面板新增删除、解决和重新打开。根线程操作同时处理直接回复；删除单条回复只影响该回复。来源文件、批注片段和整部件身份均核验，现代扩展记录定点修改，正文文字、格式及无关部件保持。Undo/Redo 和草稿恢复沿现有文档事务；批注线程动作独立保存。身份歧义仅限制该能力，不阻止普通正文编辑。

验证范围：

- 两条新增 Python 主链测试真实 bundle、inspect、patch、ZIP/lxml 独立回读及再次 inspect，共 2 passed；包含过期来源拒绝，目录只改 document.xml，重新打开线程只改 commentsExtended.xml，删除后正文不变。
- TOC 独立 bridge 4 项、前端 TOC 与主视图恢复 55 项通过。交叉审查发现的同段正文丢失、归一化 loader 改写无关页眉均有实际反例与回归。
- 批注独立 bridge 3 项、前端线程与面板 11 项通过。根线程解决/重新打开/删除、取消、恢复、只读与混批约束分别覆盖。
- 最终 TypeScript exit 0；Vite build exit 0，44.22 秒；预算与预算契约 exit 0，未提高上限。main 208.3 KiB，render 697.4 KiB，engine 413.4 KiB。构建 manifest SHA256 eaa5778616f0096c0aab4d76f199a33e59606839bd8f6fe02e0bb7f6887fd055。
- 共享 Node bridge 最终 bundle exit 0，SHA256 346cdd3c26c2e43e46f4f4eb94fdfcd0b7fa74ed9b3c8357bc9d64641eb3a964。Python 测试与浏览器分别使用独立打包 bridge，防止沿用旧运行产物；两者不混写为同一执行环境。

构建日志 /tmp/sr-word-parity-build.log；最终类型 /tmp/sr-word-parity-final-types.log；预算 /tmp/sr-word-parity-budget.log。最终冻结构建的真实浏览器验收结果另附；单元与桥接证据不替代浏览器、生产鉴权或桌面 Word 验收。

复杂长报告分页是本轮独立对照任务，结果见 NATIVE_WORD_COMPLEX_PAGINATION_ACCEPTANCE.md；已确认差异，未在这次目录／批注增量中修复。

真实浏览器补验（2026-11-11）

最终使用当前资产的独立冻结副本，manifest SHA256 为 06d74ba89a53ab85fcb0b5c1a31bb6a5db536995a8952c8252be187425d51d19（与前述构建后首个 manifest 不同；期间有其他并行构建，Word 主入口仍为 lazy-docx-main-BfewvS8i.js）。两条流程实际加载的每个 JS 都与冻结磁盘 SHA 对照，开始与结束 manifest、bridge 身份相同。Node bridge 为上述共享最终 bundle，SHA256 346cdd3c26c2e43e46f4f4eb94fdfcd0b7fa74ed9b3c8357bc9d64641eb3a964；本浏览器补验未使用 pytest 临时 bridge。

- 目录：真实 Chromium 点击“引用 → 目录”，显示两个标题项；真实 Python 保存修订 2、下载字节校验、重新打开仍可见。点击“更新目录”，保存修订 3、下载并重开仍有两个标题项。两次保存请求分别只有 insertToc、updateToc；ZIP/XML 回读只有一个真实 TOC 域，dirty=true，原正文保留。未改变已保存标题时，更新结果字节与上一修订相同，此次更新没有伪造内容变化。共 2 次成功保存。
- 批注：真实点击解决线程并成功保存修订 2；随后直接使用已有修订 2 下载、重新打开，再重新打开线程、保存修订 3，最后先取消删除再确认删除根批注及其回复、保存修订 4。下载哈希、每次重开与 ZIP/XML 回读符合预期；重新打开只修改 commentsExtended.xml，删除后保留 Anchor text，移除批注范围和引用。共 3 次成功保存，其中第 1 次成功后因探针绝对 URL 断言停下，后续从已存在文件恢复，未重复保存；最终 evidence.requests 只包含后续两次请求，修订 1/2 文件和首次 root-comment.log 保留前一次成功事实。
- 两条最终流程均 errors=[]，实际外壳、Word 功能区、预览模型、保存生产 Python/Node bridge、DOCX 下载和再次解析均执行。HTTP 文档、保存与下载路由为显式夹具；validation.ok=true 为夹具回执，不代表运行了线上发布门禁或非阻断故障注入。
- 人工查看截图：toc/insert-draft.png、toc/updated-reopened.png、comment/resolved-draft.png、comment/deleted-reopened.png；目录项、重开正文、已解决线程和删除后正文均符合预期。截图与逐次 DOCX、JSON 位于 /tmp/sr-word-native-actions-20261111/root-final；两条完整 evidence.json 与 screenshots.png 同目录。浏览器缓存页码未计算，桌面 Word 更新域后的页码未验收。

复现脚本为 frontend/smoke/native-word-toc-thread-smoke.mjs，参数 toc 或 comment，配套 native-word-toc-thread-fixture.py。需设置 DOCX_EXPECTED_MANIFEST_SHA256；可通过 DOCX_TEST_DIST 指向冻结 static、DOCX_TEST_OUTPUT 指向独立输出目录、DOCX_TEST_PORT 指定端口。已有 revision-N.docx 会回读并继续后续动作，避免重复成功保存。首次旧桥接失败、pytest 临时目录被清理、manifest 漂移、端口冲突和 URL 探针断言均是本次验收环境／探针问题，已与最终通过证据分离。
