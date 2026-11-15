# Word 整表对齐验收

2026-11-10。专项验收通过；固定来源见 `NATIVE_WORD_TABLE_ALIGNMENT_INDENT_INVESTIGATION.md`。

单一 `setTableAlignment` 操作仅修改整表直属 `tblPr/jc`。对齐取 left／center／right；left 沿固定来源删除直属 jc，保存重开 PM 为 null，RTL 时表示起始侧。四边距、缩进、宽度、表格网格和所有单元格内容保持。浮动定位优先时仍可保存对齐值，但必须明确提示当前位置由浮动设置决定。

UI 通过现有表格属性入口增加独立对齐区域；caret／矩形／整表选择只负责定位同一表。重复对齐只保最终值；无操作不改变历史或草稿。与其他同表意图互斥，collector 以完整确定性投影比较，服务器核对来源摘要、严格字段及真实保存结果。左缩进没有固定来源控件或完整保存链，不计入本项交付。

验证顺序：固定来源向量和 core／projection／bridge 定向测试；UI 的 RTL 文案、浮动提示、无操作、连续修改、Undo／草稿及过期保护；Python 真实 DOCX 保存保真和来源保护；完整类型检查、统一构建与体积门槛；最后真实 Chromium 位置变化、Python 保存、HTTP 下载 SHA、ZIP 及修订重开。

初始 Python 主用例已有效失败：未提供 `tableAlignmentEditable`，日志 `/tmp/word-table-alignment-python-red.log`。保存与草稿入口已接线，独立 core／bridge 和 UI 并行实现中。未运行完整测试，不以接口接线代替验收。


## 当前定向证据

core／projection3项与bridge7项通过：`/tmp/table-alignment-green.log`、`/tmp/table-alignment-bridge-final-green.log`。涵盖paired／selfclosing／缺失tblPr、jc别名及非法声明、真实parser模型兼容、tblOverlap／banding／tblW后插入顺序、RTL、浮动保持及非目标原字节。

UI6项已通过，旧边距／行跨页导航4项窄回归通过：`/tmp/word-table-alignment-ui-regression.log`；raw start/end无操作保持，浮动提示下允许签发新值，连续最终值／collector／草稿和stale保护有独立证据。

Python9项已分段通过：初跑7通过，另两项仅因python-docx对不识别元素返回普通lxml节点、测试误取.xml属性失败；改用etree.tostring后floating／独立布局通过，RTL单项最终通过 `/tmp/word-table-alignment-python-rtl.log`。未改生产来迎合测试；原失败日志 `/tmp/word-table-alignment-python.log` 保留。最终bridge已重bundle：`/tmp/word-table-alignment-final-bridge-build.log` exit0。

统一前端构建、完整types及budget已通过，日志 `/tmp/office-table-alignment-watch-final-build.log`、`/tmp/office-table-alignment-watch-final-budget.log`、`/tmp/office-table-alignment-watch-final-contract.log`。随后真实浏览器发现下述显示缩进问题；修复后仍需重新构建及继续验收，不能用此前构建证明修复通过。


旧表格投影受影响回归14项通过：`/tmp/word-table-alignment-mutual-guards.log`。独立review未发现本次集成问题，新增真实probe验证逆序两表修改＋段落插删＋section marginLeft2500同批后，对齐分别center/right，全部cell与非目标parts保持；迟到非法alignment=end整批失败且output不存在。证据 `/tmp/table-alignment-integration-review/{result.json,invalid-late-result.json}`。浮动抑制来源仍按raw tblpPr签为floating，不凭显示属性误判inline。

真实 built 浏览器已通过首来源三次保存与第二来源 right 保存（共4次）；产物 `/tmp/docx-table-alignment-built-bOU9kG`。第二来源 legacy14／indent=-109 切 left 后，live left=-7.296875、保存明确重开 left=-9.5，失败日志 `/tmp/word-table-alignment-built-legacy14-indent-failure.log`。根因为来源导入器只在 left/start 扣首格左边距，而本地仅投影 tblAlign 未同步显示 indentTwips；应复用真实导入器计算显示缩进，保持原 XML tblInd。剩余20次保存通过通用 resume 继续，已过4次不重跑。当前仍未通过专项验收。

legacy 显示缩进已修复：可信 parser 基线复用 blocksToPmDoc 派生 left/center/right 映射，main 的 UI、collector、replay 共用富化 anchors，映射不进入请求协议。新增6环境×4连续切换共24次真实 XML 保存回读、collector/replay、来源显示值及 NaN 伪造拒绝通过 `/tmp/table-alignment-legacy-indent-final-green.log`。原始 tblInd=-109 保留；继承表格边距71有显式 parser 断言。统一完整 types 因新增测试引入 bridge 的显式.ts路径失败，最小修正 import 后完整构建 `/tmp/office-alignment-indent-watch-host-final-build.log` exit0（41.97s），独立 DOC bridge 重 bundle exit0。该构建后又有 XLSX 保存态导航修正，最终预算与真实浏览器以后一统一 dist 为准。

新统一 dist `/tmp/office-alignment-watch-saved-navigation-build.log` exit0（完整types，40.23s），budget/contract exit0。浏览器从4次既有成功恢复，截至 `/tmp/docx-table-alignment-built-uzsklO` 已22/24保存通过：legacy14 left修订12实时/草稿/明确重开均-9.5px，RTL legacy、pct、隐藏合并续格及真实浮动三种对齐均通过。root目视revision-12-left-reopened截图。最后 suppressed-floating left/center 尚未通过：选择手柄 not visible 超时，未执行该次修改/保存，失败日志 `/tmp/word-table-alignment-built-smoke.log` 保留；后续须从uzsklO仅续余2次，不重复已过22次，也不能将本状态标完整验收。


## 最终 built 验收

最终续跑 session43704 exit0，`/tmp/word-table-alignment-built-smoke.log` 为 `ok=true`；累计8来源24次保存全部通过，最终汇总 `/tmp/word-table-alignment-built-evidence.json`，产物 `/tmp/docx-table-alignment-built-rdefw0`。不是同一新 dist 重跑24次：首4成功取自 `/tmp/docx-table-alignment-built-bOU9kG`（原统一 dist）；新统一 dist 从其恢复新增18次至 `/tmp/docx-table-alignment-built-uzsklO`，最后从uzsklO校验22份已保存DOCX SHA并复用，仅新增抑制浮动 left72／center73 两次。每次已过保存均未重复。首来源 right2 的原截图证据在 `/tmp/docx-table-alignment-built-RvwAeo`，left3/center4与right11在bOU9kG；新dist18次截图在uzsklO，最后2次在rdefw0，全部24份下载DOCX与结果JSON在rdefw0。

最后两次问题仅为probe：对934px高表执行table.hover默认滚到中心，真实table handle位于上方视口之外，自动滚动handle又触发隐藏。改为公开首格首段真实scrollIntoView(center)+hover后正常click手柄；未force、未注入PM选区、未改生产。该NodeSelection的Undo/Redo、草稿刷新、保存下载与明确修订重开全部通过。失败日志另存 `/tmp/word-table-alignment-built-suppressed-handle-failure.log`；legacy14产品原失败另存 `/tmp/word-table-alignment-built-legacy14-indent-failure.log`。最终目视 `/tmp/docx-table-alignment-built-rdefw0/revision-73-center-reopened.png`，可见首段、首行与第二行内容，手柄处于表左上；抑制浮动各对齐位置left51.796875、width481、height934.3125保持。

Chromium140.0.7339.16；121个实际加载JS均HTTP200且本地SHA一致，console/pageerror为[]。最终主要资源：`lazy-docx-main-D0k0g1Co.js` SHA256 `405213d43fbadf081331cbe017f56b2e0b7ca4773106b7cfa152ed2ea48b060e`；`lazy-native-docx-engine-C7gMc9rN.js` SHA256 `5da009cd517635838dd7c91210647148af3cf61d73c83fba18af5f96d4fd0612`；全部实际资源与24份下载SHA见evidence。真实Python patch、HTTP下载身份、仅直属jc变化、全部物理单元格和非目标parts、live/draft/明确保存修订几何相等均通过。授权路由是本地夹具；不宣称生产授权HTTP、桌面Word或PDF等价。未运行或重复完整测试。
