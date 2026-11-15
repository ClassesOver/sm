# Word 第一层嵌套表 bridge 文字编辑

2026-11-10，实现范围限于 bridge 与 Python kind 白名单，不宣称浏览器、桌面 Word 或内层结构命令已经验收。

顶层 table anchor 新增 `nestedTables`，每项为 `{tableId, expectedObjectSha256, row, column, nestedOrdinal, cells}`，cells 是二维 `{cellId, expectedObjectSha256, editable, paragraphs, readOnlyReason?}`。row/column 指外层父单元格；nestedOrdinal 为该格直属内表索引。ID 绑定 sourceSha256、根 blockId、docxIndex、全部坐标，内容相同的同胞表也具有不同身份。

操作为 `replaceNestedCellText {blockId, tableId, cellId, expectedObjectSha256, paragraphs}`，hash 指原始叶格完整 XML。严格拒绝额外字段、错误父子身份、错误 hash、重复目标、同根其他操作混批；同根可组合不同叶格。原始快照整批验证后，在当前根 XML 上逐步定位，避免前一补丁导致 offset 失效。

能力规则使用 `splitXmlChildren` 核验根表、行、父格、内表的直属来源、完整段落数组、nestedTableAnchors 与 model 网格。根或父映射不可靠时省略清单；内表网格不可靠时按 model 维度输出只读格。修订、包装、合并等来源保守只读。所有格 paragraphs 都取 model.paras，只有 XML 投影逐项相等的简单叶格可编辑。受保护文档不签发 editable。

paragraphs 至少一项；支持多段、空段及尾空段、中文、emoji、XML 转义和 `$&`。**当前拒绝项内制表符、换行和其他控制字符**：真实探针发现 parser 的 TableCell.paras 会丢失 w:tab/w:br，而 richParas 保留；未经模型契约专项修复不能承诺往返。这类来源格亦不会签发编辑能力。

复用引擎 `patchTableCellTexts`，未变化段落用 null 保留原 XML；每次补丁重新定位目标、逐项回读段落，并验证目标外根 XML 字节不变。最终 DOCX 再经 parseDocx 回读对应内表 model，避免底层静默 no-op 或保存时丢字。

验证（均直接运行源码，未构建 bundle、未跑全套）：

- `test_docx_nested_tables.py`：最初双同胞测试在缺少 nestedTables 处 RED；实现后前 16 用例 GREEN，另增同内表多叶格与旧 source 身份用例 GREEN。覆盖真实 DOCX 第二张定位、目标外 document.xml 完全一致、多段/空段、多目标、包装合并只读、错误身份/hash/字段、混批与控制字符拒绝。
- `bridge/tests/docx-nested-tables.test.ts`：3 个 helper 用例 GREEN，覆盖静默 no-op、数组 join 碰撞、未变段落保留、目标外字节变化拒绝。
- 新 helper 独立 TypeScript 检查通过。edit-docx.ts 完整依赖检查另报现有 note helper 的 String.isWellFormed lib、Run.ref 与 RelInfo.external 类型错误，本次未改这些相邻功能。

真实调查 fixture 的当前 inspect 位于 `/tmp/word-nested-anchor-resume/nested-inspect.json`，可供前端协议集成；此路径为本机会话证据，不是仓库持久测试依赖。

补充复核：来源能力签发与操作提交共用段落 predicate（1–1000 段、总 UTF-16 长度至多 20000、拒绝控制字符）。超限来源原文保留并标只读，不影响其他简单内表格编辑；新增单段超长、总长超限、段数超限三条真实 DOCX 用例先 RED 后 GREEN，未重跑全套。
