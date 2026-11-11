# Word 行内跨页设置验收

2026-11-10。本专项已完成真实浏览器分页及保存验收；全量 Word／XLSX 对齐仍开放。固定来源与缺口证据见 `NATIVE_WORD_TABLE_ROW_BREAKS_INVESTIGATION.md`。

新增独立 `setTableRowBreaks`：以来源 blockId／expectedObjectSha256 和有序 `{top,bottom,allowBreak}` 步骤修改真实选中行带。允许跨页时删除直属 cantSplit，禁止时插入规范元素；仅局部补丁，保留行高、重复标题、隐藏续格和其他内容。严格拒绝额外键、非布尔值、非法坐标及同表混合修改。选择语义使用真实 selectedRect，合并 owner 可自然覆盖多行，不按其他列额外扩张。

已确认固定来源在合法成对 `<w:cantSplit></w:cantSplit>` 上存在清除失败／重复节点问题，本地局部补丁同时支持成对和自闭合声明；不把该来源缺陷固化为行为契约。

当前定向证据：

- core／projection4项通过：`/tmp/row-breaks-green.log`。
- bridge6项通过：`/tmp/row-breaks-bridge-final-green.log`，包含成对元素、布尔变体、缺失／自闭合trPr、tblPrEx后插入的schema顺序、非目标XML／ZIP保真与严格来源边界。
- UI5项通过，覆盖mixed／noop／Undo、草稿回放、过期保护、属性能力独立与合并选择；旧边距交互窄回归4项通过：`/tmp/word-row-breaks-margin-regression.log`。
- Python真实保存7项通过：`/tmp/word-row-breaks-python.log`（15.46s），包含开关与成对元素清除、行高／正文／其他ZIP部件、非法值、身份／保护／同表批次和独立节布局。
- 新模块限定types通过：`/tmp/row-breaks-production-types.log`。初始主Python用例因缺少rowBreakEditable失败，证据 `/tmp/word-row-breaks-python-red.log`；实际bridge bundle已生成 `/tmp/word-row-breaks-bridge-build.log`。

统一构建、体积门槛、独立入口review和真实 Chromium 分页变化／保存下载重开仍待核验。不能仅凭 cantSplit 属性或窄测试证明实际分页行为，亦不把本项视作完整表格属性页交付。未运行完整测试、提交或推送。


完整前端types已通过：`/tmp/office-row-breaks-types.log`（exit0）。独立入口review未发现本次集成回归；额外真实探针验证两表逆序修改加其他段落插删后的flags为[false,true]且索引正确，另一次前序有效、后序非法操作失败且output不存在。证据 `/tmp/row-breaks-integration-review/{result.json,invalid-late-result.json}`。未重复已通过测试。真实分页验收仍待统一产物后运行。


## 最终浏览器验收

统一 `/tmp/office-row-breaks-trace-pane-build.log` exit0（Vite40.55s），budget／contract exit0，未提高cap。四来源普通／合并隐藏续格／RTL／合法成对cantSplit分别保存修订2／11／21／31，每次三条有序允许→禁止→允许步骤，实际Python保存、HTTP下载SHA、ZIP保真和修订重开通过。

真实分页预览两态均为2页：禁止时18条目标文字整体位于第二页；允许时第一页出现00–11、第二页12–17，切点280.7→533.3。再次禁止恢复初态，草稿与保存重开均匹配live允许分页。只mask直属cantSplit后document.xml全文与其他部件保持，合并续格内容保留。

普通／合并证据 `/tmp/docx-row-breaks-built-bVv3NZ/`；RTL `/tmp/docx-row-breaks-built-6AwFKZ/revision-20-result.json`；paired `/tmp/docx-row-breaks-built-7A7E0F/revision-30-result.json`，最终 `/tmp/word-row-breaks-built-smoke.log` exit0、ok=true/errors=[]，121JS200及SHA匹配。总证据 `/tmp/word-row-breaks-built-evidence.json` 保存四下载SHA及资源身份。前两来源逐source结果从已保存HTML／ZIP恢复，未持久化的逐行数组明确缺失，不伪造；原实际运行中的逐行可见断言通过。smoke文档包含精确分段执行记录。

早期RTL Undo断言仅受异步class token排序影响，改为紧邻事务捕获并canonical排序class，不移除其他属性／样式／文字比较；paired mask错误把先前自闭合标记误作开标签，最小真实diff `/tmp/word-row-breaks-paired-exact.diff` 证明实际只删目标成对cantSplit。两处均仅修探针，从失败来源窄续跑，未改产品或重复已过来源。

root目视合并来源禁止与允许分页截图，确认目标行起始页与跨页内容变化。授权／修订路由为夹具，不代表生产HTTP、桌面Word或PDF等价；完整表格属性页和全量对齐目标未完成。
