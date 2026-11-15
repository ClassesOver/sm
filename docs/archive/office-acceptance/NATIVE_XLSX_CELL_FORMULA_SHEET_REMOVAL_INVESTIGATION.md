# 普通单元格公式：工作表删除原子性调查

本轮仅新增真实浏览器探针与本文档，不修改生产、来源清单或构建。固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 referenced-removal 契约为拒绝删除；本地 `sheet-ops.test.ts` 已有被普通公式引用时拒绝的既有回归。本轮未重跑旧套件，也不以 CF/DV 前置检查通过推断普通公式已保护。

## 真实 RED

`frontend/smoke/workbook-formula-sheet-removal-gap-probe.mjs` 用真实 openpyxl ZIP，仅 Source 与 Other 两表；Other!C1 为 `=Source!A1`，没有 CF 或 DV。Vite 独立端口 4227，调用官方 `sheet.command.remove-sheet`。

日志 `/tmp/formula-sheet-removal-browser-investigation.log` 首行记录：

- before：`[["=Source!A1"]]`。
- deleted：false，但工作表已只剩 `["Other"]`。
- after：`[["=#REF!"]]`。
- undo 与 redo 均返回 false，Source 没有恢复，公式仍为 #REF。
- 随后反馈 `本地草稿暂未更新：工作表 "Other" 的公式仍引用 "Source"，已拒绝删除。`
- pageErrors 为空；原子拒绝与公式保留两条断言均真实失败。

这一边界比只返回 true 的后端迟到拒绝还严重：删除 command 返回 false 不能证明工作簿没有变化。官方 remove-sheet 先执行基础删除，再执行引用 followers；其 `sequenceExecute` 仅在整批成功后登记 undo。实际结果符合中途失败后基础 mutation 已变、历史尚未登记的状态，具体哪个 follower 返回 false仍需后续定位，不能仅凭本日志断言调用栈。

## 最小后续范围

1. 在基础删除及任何 followers 前检查存续表当前单元格公式，复用已有公式引用识别；使用实际 live 公式而非缓存计算值，保持字符串、外部簿、大小写与同簿限定符边界。
2. 隐藏表、范围外公式、共享公式等不能只按可视区域推断；不可完整读取的原始公式须使用实际文件来源保护，并绑定模型与结构签名。
3. 用户已解除引用时，当前普通单元格编辑也必须在文件删除验证前写入；单加前置拒绝会留下清除后删除的旧源阻断问题。
4. 新增返回 false 时 snapshot/history/draft 必须原样的断言，及引用新增/清除、rename/reorder/结构移位、真实保存与重新打开回归。定义名称和图表是另行边界，本探针没有验证。

本缺口尚未修复；本轮 CF+DV main 变更的只读审查未发现新增阻断问题，不能把此独立既有普通公式边界归因于它们。

## 引擎与同簿限定符边界

独立 `packages/xlsx-engine/tests/cell-formula-sheet-removal-investigation.test.ts` **6 通过**，日志 `/tmp/formula-sheet-removal-engine-investigation.log`：本地 bare、lowercase、quoted case 引用均拒绝；字符串与 quoted/unquoted 外部簿允许，存续 worksheet/styles 字节相同。文件引擎没有 Univer unitId，不能自行把任意 `[book]Sheet` 当成本簿；同簿 unitId 规范化必须由有实际 runtime 身份的前端负责，其他外簿保持原样。

探针允许 `CELL_REMOVAL_FORMULA` 提供单一公式变体，并始终检查名称、原公式及 undo/redo 状态，而不只检查删除返回值。quoted `[report-workbook]SOURCE` 小写 A1 变体（`/tmp/formula-sheet-removal-internal-quoted.log`）观察到删除 true、公式原文未变、undo/redo均成功、没有草稿拒绝消息；该变体区别于 bare 删除 false 无历史的结果。运行时身份另由输出 unitId 核对，不将外部簿当成本簿进行引擎误判。

unquoted `=[report-workbook]source!a1` 变体（`/tmp/formula-sheet-removal-internal-unquoted.log`）输出实际 `unitId="report-workbook"`，确认是本 runtime 限定符；删除仍 true、Source 消失、公式保留旧引用、undo/redo成功且反馈为空。此例说明仅在 bare 公式上复用文件引用扫描还不够，同簿限定符的小写边界必须归一后扫描并在持久化前去掉本簿标记，不能误当外簿跳过。

## 前端修复及开发态闭环

新增独立 `assertCellFormulaSheetRemoval`，使用Worksheet稀疏cell matrix遍历所有存储单元格，不依赖可视区域、隐藏状态或dimension。带f/si的节点由官方FRange.getFormula（FormulaDataModel）读取，普通f可raw回退，si无法解析明确拒绝。`normalizeInternalSheetFormula`只归一确切runtime unitId，工作表名大小写等价，保护字符串、其他外部簿和转义单引号；DV复用同helper修复unitId大小写误判。

源码核实当前reader只读有正文f，共享follower未展开且si不导入。因此root可信raw callback以 `unprojectedCellFormulaNodes` 识别sheetData内自闭f或t非normal节点（shared/array/dataTable/unknown），只对这些特殊原公式补查；普通已解除的旧f、CF/DV公式不纳入cell fallback。未知sheetData前缀/其内部未知f前缀明确来源无法核对。未完整投影shared组仍受原始引用保护，本轮不声明共享组解除依赖已支持。

模块缺失RED `/tmp/workbook-cell-formula-removal-helper-red.log`；特殊组sheet另有旧普通依赖误拒RED `/tmp/workbook-cell-formula-removal-raw-scope-red.log`，修为仅special f；CF/DV合法xm:f误识别RED `/tmp/workbook-cell-formula-removal-namespace-scope-red.log`，修为f前缀只看sheetData。最终helper12项 `/tmp/workbook-cell-formula-removal-helper-final-green.log`，新增namespace控制 `/tmp/workbook-cell-formula-removal-namespace-scope-green.log` 通过。collector-before-original与特殊ID测试 `/tmp/workbook-cell-formula-removal-scope-green.log` 通过；`/tmp/workbook-cell-formula-removal-final-types.log` tsc exit0。

4228真实开发态 `/tmp/workbook-cell-formula-removal-dev-refusal.log` exit0：删除false时整workbook snapshot深比较一致，Source/Other和原公式保持，undo/redo均false，localStorage草稿与saveLabel不变。`CELL_REMOVAL_CLEAR_SOURCE=1` `/tmp/workbook-cell-formula-removal-dev-clear-source.log` exit0：先拒绝，再官方setValue(1)解除Other!C1引用，允许删除/undo/redo/draft/Python/openpyxl保存和修订2重开。payload严格先applyCellEdits Other C1=1，再applySheetEdits移除Source；剩余值与styles.xml字节保持，pageErrors=[]。root负责可信source绑定与pre-removal cell持久化，普通其他cell/style保持既有保存顺序。

4229纯UI脚本 `smoke/workbook-cell-formula-removal-built-smoke.mjs` 已准备，真实标签删除、File history、goto+键盘编辑解除引用及draft/Python/rev2/JS200SHA，等待统一build预算READY。context/save/revision HTTP由probe提供、文件处理为真实Python，不宣称生产HTTP端到端或定义名称/图表等全部依赖已原子支持。

## 原生 Python 与未投影公式边界

新增 `reporting/tests/test_workbook_cell_formula_sheet_removal.py`，真实 openpyxl ZIP 调用现有打包 engine，**11 通过**（`/tmp/formula-sheet-removal-native-python.log`）：local/quoted/case、隐藏存续表、最右下角 XFD1048576 和真实 shared anchor/follower XML 均拒绝；Other、字符串及两种外部簿公式允许，存续 worksheet/styles 字节一致；`applyCellEdits` 先解除依赖再删除成功，除实际被改 C1 外的 XML、其他值和字体填充保留。仅跑新增文件，未改生产。

shared fixture 用实际 `<f t="shared" si="0" ref="C1:C2">Source!A1</f>` 加 `<f t="shared" si="0"/>`，openpyxl 独立读回 C1/C2 均为跨表公式。该通过仅证明原始 anchor 仍存在时文件删除检查拒绝，不证明清除 anchor 后 follower 安全。

只读源码确认：`workbook-read.ts::parseWorksheetCells` 扫描全部 c 节点但只投影带正文 f；共享 anchor 会导入 formula，而自闭合 follower 不展开、只保留缓存值。`univer-data.ts` 枚举所有 ModelCell 并将 formula 转为 f；`sync.ts::readBackSnapshot` 枚举 sheetOrder 和全部 cellData，不限定可视区域，因此隐藏/远处的普通已投影公式可从 snapshot 检查，但 snapshot 无法恢复导入时缺失的 shared follower。array anchor 的 ref 覆盖范围也不能由单一 ModelCell 代表。

最小来源保护建议：实际文件中有 shared/array 或不可识别公式结构的表，缓存真实 XML 并绑定实际 WorkbookModel/最新结构签名；对这些未完整投影来源保守检查依赖，不因 live 清除了 anchor 就推断全组依赖已解除。不要从客户端提供的 raw/si 字段授权，也不要为这轮删除实现新共享公式展开器。若未来需要允许这类编辑，须另有源结构完整的物化/更新及回读证据。

## 最终静态产物验收

统一构建 `/tmp/office-cell-removal-word-style-build.log` 用时39.11s、exit0，同批budget与contract均exit0，未提高预算上限。随后 `CELL_REMOVAL_CLEAR_SOURCE=1 node smoke/workbook-cell-formula-removal-built-smoke.mjs` 最终通过（session98758 exit0，`/tmp/workbook-cell-formula-removal-built-final.log`），覆盖实际静态包，不访问dev route或注入runtime。

真实UI先右键标签删除并确定，拒绝后Source、Other与引用公式保持；实际点击File undo/redo仍保持原状，localStorage与saveLabel不变。通过goto定位Other!C1并键盘输入1/Enter解除依赖后，删除、undo/redo、草稿重载、真实Python保存及修订2重开通过。最终仅Other，C1=1、B1:B5=[1,2,3,4,5]，styles.xml字节保持。保存操作严格依次为applyCellEdits Other!C1=1与applySheetEdits移除Source。

333个JavaScript实际HTTP200且SHA与磁盘一致：main为`lazy-workbook-main-B6Kmq1fR.js`，engine为`lazy-workbook-engine-Buxs6LHL.js`，collector为`lazy-workbook-structure-followers-BYTmT2Sq.js`；pageErrors=[]。此结果关闭本轮普通公式原子拒绝与普通单元格解除引用保存缺口；HTTP context/save/revision仍由probe提供，不能据此声明生产HTTP端到端、共享公式组解除依赖、定义名称或图表依赖已经全部对齐。
