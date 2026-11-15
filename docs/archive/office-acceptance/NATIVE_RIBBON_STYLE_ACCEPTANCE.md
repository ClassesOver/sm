# Word / Excel 功能区与样式对齐验收（2026-11-06）

基线为 PR #190 `018b1942`；本地分支 `feat/native-word-excel-followup`。原有精确段间距和查找替换改动保留，未提交、推送或部署。远程 Git 传输超时后通过 GitHub API 读取对象，逐个验证 blob/tree/commit SHA 与连通性，再 fast-forward；本地补丁及四个未跟踪文件备份逐项相等。

## 实现范围

- Word/Excel 功能区复用 `style.css` 的主色、浅蓝选中态、中文字体、圆角、边框和焦点变量。规则局限于功能区，保留原文分页与网格样式。选项卡支持键盘导航、可见焦点和准确禁用状态；Excel 文案中文化，图标复用已有 SVG。
- Word 来源段落样式选择器使用原文样式 ID/名称；限制为有锚点的普通正文段落，拒绝编号/大纲、缺失/循环或未完整建模继承。仅修改目标 `w:pStyle`，保留直接格式、链接、书签及非目标 ZIP 部件。同段样式修改不能混入其他编辑，须保存重开后继续。
- Excel 随选区读取字体、字号、粗斜体、下划线、颜色、填充和数字格式；逐属性混合状态不使用首格冒充。未完整建模继承明确不可判定。自定义数字格式复用官方 parser、模态组件、范围捕获、预算及现有 `applyCellEdits`，范围最多一万个单元格。显式 `General` 重置可往返。

## 定向验证

- Word 相关前端初始 97 项通过，后续焦点/来源样式控件单项通过；其中包含既有回归，不累加为新增功能数。真实 DOCX 专项 10 个不同用例通过（最后混用冲突 fixture 修正后只重跑失败单例）。覆盖自闭合 pPr、属性与空白、链接/书签、保护、类型/继承拒绝和其他 ZIP 部件。
- Excel ribbon/native/format 三文件 27 项通过；数字格式 NativeDraft set/remove mutation、Undo/Redo、刷新与保存新增单例通过。独立 openpyxl 自定义格式/General 保真用例 1 项通过。
- 公式自动派生格式原反例：新增两个定向用例通过，保留用户显式数字格式与目标已有其它样式，自动结果不进入草稿；既有公式缓存恢复单例结果另记录。
- 视觉隔离 3 项通过，布局修正后只复验相关单例。它们检查主题作用域/原文字体与网格输入隔离，不能替代实际浏览器检查。
- HTTP Word 样式用例通过；Excel 初次测试负载缺少 `cell` / `writeValue` 返回 422，修正为实际前端协议后仅重跑 Excel，1 passed/3 deselected。验收故障保留下载、原文件身份、幂等重试和重开均覆盖。仓储为替身、HTTP 为 ASGI，不代表生产权限或 SQL 验收。
- 两类生产构建、预算与预算契约通过。视觉修复及公式格式隔离后标准构建另作针对性重建，结果见最终记录。保留已有第三方 chunk/circular chunk 警告。

## 浏览器事实与修复

- 隔离宿主使用真实 DOCX/XLSX 引擎及生成文件，授权/修订登记为合成替身。Word 实际应用 `ReportAccent` 后画布为 18pt、蓝色；保存/独立回读/重开保留引用及未修改粗体。
- Excel 实际读到 Calibri14、粗体、字体 `#0b4f8a`、填充 `#edf5fc` 及原数字格式。自定义格式面板可输入并应用 `#,##0.0000`。
- 首次 Excel 浏览器保存发现跨表引用公式自动推导数字格式误入草稿，已保留失败结果，未作为验收通过；在公开执行事件中仅过滤公式计算结果的派生 `n`，保留值、公式、其它样式和用户显式格式。修复后须用新来源/端口复验，结果记于下方。
- 首次窄屏截图发现命令较多分组撑高功能区，修为固定三行、功能区内横向滚动，最终视觉另复查。

## 最终复验结果

- 修复后的标准 `npm run build` 通过（34.89s），实际包体预算检查通过；此前两类生产构建及预算契约也通过。第一次修复构建因 `IExecutionOptions` 类型不兼容失败，修正辅助函数类型后重新构建成功，没有隐藏失败记录。未运行完整前端或仓库测试。
- 公式格式过滤新增两个定向用例通过；公式缓存、数字格式恢复和结构恢复的受影响选择另有 4 passed。只处理同时带有 `fromFormula` 与 `applyFormulaCalculationResult` 的结果，不阻断公式值/缓存更新，不过滤普通显式格式操作。
- 全新浏览器来源 `4202` 复验：初始状态为「已保存」；仅对 `Summary!A1` 应用 `#,##0.0000`，实际保存 payload 恰好包含该单元格一个格式 edit。独立下载/openpyxl 回读确认值 `1234.567`、Calibri/粗体、其他单元格与公式保持原样，`Details!A1` 的 `=Summary!A1` 仍为 `General`。
- 下载 XLSX 为 5554 bytes，SHA-256 `7f3e8e24ab5eb249ca051e9d87a800fb673fe03f7648b5bec67283c6b0d35ecb`。浏览器重开修订 2，状态仍为「已保存」，功能区读回 `#,##0.0000`。
- Word 桌面实际截图确认蓝色主题及紧凑两行字体/段落分组，重开后来源样式仍为 18pt 蓝色。Excel 420×780 窄屏最终截图确认固定三行功能区和区域内横向滚动，工作表可见范围恢复；未将早期过高布局或一次异常拼接截图计为通过。Word 窄屏、全部源选项卡及所有弹出控件的视觉验收未穷举。
- Word 书签/链接/直接格式和其他 ZIP 部件由真实 DOCX 专项独立检查；混合选区、Undo/Redo、焦点及草稿刷新由定向测试覆盖。浏览器本轮实际执行的是来源样式/数字格式应用、保存和重开，不声称已在浏览器逐个复验全部负向路径。
- 新增 Python 测试及薄桥接 Ruff 检查、`git diff --check`、10 项 workbook vendor 来源/本地适配 SHA 检查均通过。既有打包 chunk/circular chunk 警告及 Agno tracing 退出日志流错误保留；HTTP 断言结果与其分开记录。

## 2026-11-06 第二批：批注、高亮、缩放、查找替换与删除线

固定源仍为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本节只记录实际核实的证据；代理声称一律以文件与测试输出为准。

### Excel 批注（legacy notes）

- 引擎：`patchSheetNotes` 精确补丁 + 行列插删随迁（注释引用、VML Row/Column/Anchor、末条批注清理、外來 VML/其他工作表保留）。新增 `tests/notes-structure.test.ts` 5 项与 CLI/openpyxl 5 项通过。
- 前端组合：新增 `workbook-main-notes.test.ts`（真实 Univer 命令历史）3/3 通过——批注补丁+行列插删+真实 Undo/Redo+刷新+失败保存重试+引擎实际回读、作者保留；`workbook-notes.test.ts` 9/9、`workbook-native-recovery.test.ts` 15/15、`workbook-native.test.ts` 3/3。popup/position 视图 mutation 不再标脏；只读可阅读/导航且弹窗只读提交被禁；排序入口加批注结构守卫，ribbon 逐格写值与官方 `sort-range`/`reorder-range` 均无法绕过。
- 来源清单：`UPSTREAM-PATCHES-SHA256.json` 扩到批注适配 14 项，三级清单合并后覆盖引擎 80 文件、哈希逐项一致（脚本核验通过）；`SOURCE.md` 补记本地批注适配范围与未达项。结构迁移后重建的 `dist/cli.mjs`（无更晚的引擎源文件）上复跑 HTTP xlsx 往返 1 passed/3 deselected，批注补丁、作者保留与非阻断签发在真实 bridge bundle 上成立。
- 批注位置迁移语义已核实：官方 0.25.1 `update-note-position` 直接改写 note 的 row/col，仅由行列结构变化的 ref-range controller 以 `silent+onlyLocal` 生成，固定源不暴露独立拖动入口；其 `NOTE_MUTATIONS` 省略该 mutation 的前提正是位置移动始终伴随已记录的结构操作。本地据此收紧：仅放行官方结构跟随形态（校验身份与新坐标），独立调用取消并提示"批注位置迁移仅随行列结构修改自动进行"；`toggle-note-popup` 保持纯视图。新增独立迁移拒绝回归（A1→B2 拒绝→改 A3→保存→引擎回读：A3 保存、A1 批注与作者原样、B2 无批注、payload 无 `patchSheetNotes`），并断言真实结构组合中全部 position 事件均为 silent+onlyLocal。相关 31 条通过。独立移动批注与固定源一致地不提供，不构成缺口；桌面 Excel 拖动语义不在此目标内。
- 未达项：含批注的排序仅完成安全拦截，官方 `range.sort` 完整语义未对齐；线程批注/批注图片/持久化弹窗可见性明确不支持。

### Word 高亮与视图缩放（浏览器实证，宿主 4203）

- 缩放：放大 110%、页宽 142%、对话框手动 125%，三次操作后状态均为「文档已载入」无未保存标记；重开后回到 100%（缩放不持久化为已登记缺口）。仅调整显示，不产生操作负载。
- 高亮：主按钮应用黄色后状态变「有未保存修改」；保存生成修订 2，验收失败告警保留且下载链接照常签发。下载字节与保存产物一致（37519 bytes，SHA-256 `de518943…2533`）。python-docx 独立回读：第三段两 run 均 `YELLOW (7)`，首段粗体与全部正文不变，ZIP 仅 `word/document.xml` 与 `docProps/core.xml` 变化。重开修订 2 画布该段渲染 `rgb(255,255,0)` 背景，状态干净。
- 调色板复验：重开修订 2 上直接点击 green 色块成功，仅第三段背景黄→绿、状态转「有未保存修改」，Ctrl+Z 撤销后内容恢复黄色（脏标记按既有设计仅保存/重开清除）。首次一次自动化点击超时属测试动作可点击性判定，未复现为产品缺陷；`elementFromPoint` 命中色块自身、pointer-events 正常。
- 未达项：高亮范围仍限单段整体，表格内/跨段/游标 run 级未支持。

### Word 查找替换 / Excel 删除线双下划线（最终构建浏览器实证）- 统一构建通过（41.78s，既有 chunk 警告保留），包体预算检查 exit 0。一次构建失败为实现线并发写入的短暂括号中间态，修复后重建成功。
- Word 查找替换：Ctrl+F 打开面板（查找/替换页签、大小写/全字/全半角、普通文字/通配符/正则模式）；查「段落」找到 3 处；替换页签全部替换「来源样式→新来源文本」状态「已替换 1 处；已写入当前草稿，可撤销」，正文仅该段变化、其余段落原样，状态转「有未保存修改」，Ctrl+Z 精确还原。限定 5 文件 82 项回归与 tsc 通过。Go To 独立导航、protected/页眉页脚搜索、^p/^l 结构替换、未保存新增段落/链接正文/混合 run 单元格替换明确不支持并给出原因。
- Excel 删除线/双下划线：重开修订 2 上对 A1 依次应用删除线与双下划线，aria-pressed 正确（单下划线保持独立为假），保存修订 3。payload 恰一条 `applyCellEdits`（writeValue:false，style 仅 underline:double+strikethrough，无此前的边框伪差异）。openpyxl 回读：值 1234.567/格式 #,##0.00/粗体/Calibri14 保留，A2 斜体、B1 公式、三处批注（含迁移后 A4）与合并均原样。`workbook-font.ts` 6 项与定向 10 项通过；上下标因引擎 schema 无对应字段保持禁用并说明原因。
- 批注浏览器闭环（宿主 4203 多作者夹具）：初始「已保存」无假脏；审阅组按钮按状态启用；A1 对话框显示来源作者与原文，改文应用后转「有未保存修改」；选中 A3（另一作者/行列迁移批注）后插入行，保存修订 2。下载字节与保存产物一致；payload 为 `applyRowColumnOps`+`applyCellEdits`+`patchSheetNotes`；openpyxl 回读 A1 改文且来源作者保留、批注随行迁移至 A4 且另一作者保留、Details B2 其他作者原样、值/公式/格式/合并不变。重开修订 2「已保存」且批注/作者还原。

### Word Home 剪贴板族（clipboard 线，root 授权实现）

- 源对照：粘贴主按钮默认 + 分体 source/merge/text/选择性粘贴/默认设置（Ribbon.tsx:3619-3663）；读取链 `navigator.clipboard.read()` 失败回退 `readText()`；格式刷拾取 `$head.marks()`/选区首 run、¶ 标记规则（光标/跨段携带段落格式）、单击刷一次/双击锁定/Esc 解除/locked 模式防误刷（:451-540,1991-2108）。
- 实现：新 `docx-clipboard.ts`（painter 拾取/应用/交互 + paste/copy/cut）；text 粘贴走 PM 原生切片落 filterTransaction→docxOperations（精确 op 断言）；**有意收敛**（保存协议限制，进入文档前拒绝并说明）：富文本 source/merge 模式拒绝（协议只支持整段统一格式）、图片粘贴/选择性粘贴对话框/默认粘贴设置未达（菜单保留禁用）；纯文本严格校验（控制字符/20 万字符/400 段/空剪贴板）；格式刷协议内收敛（段落属性白名单、docTextStyle 只带 size/color/font、identity 不扩散、列表段跳过缩进）；词粒度刷、⇧⌘C/V 键盘弦、styleId 转换未达。cut/copy 走 execCommand 不越权；Ctrl+X/C/V 验证为 PM 原生未被拦截。
- 测试：`docx-clipboard.test.ts` 23 项（painter 捕获/映射/越界/锁定、paste 协议/拒绝/权限失败可重试、copy/cut）+ ribbon 18 + 回归合计 6 文件 124 项；tsc 干净；复用 scoped.css 既有类无新 CSS。浏览器闭环待 XLSX 清除线完成后统一构建验收。

- 页眉/页脚保存生命周期（2026-11-07）：修复布局修改与 HF 草稿共存并加组合恢复回归；NativeSession 在记录保存快照前 flush 当前嵌套 HF 编辑器，flush 后再做异步确认及草稿变化检查；保存中同步将 nested editor 设为不可编辑，失败解锁后保留已 flush 内容。主视图控制器从严格草稿投影当前部件和首页/奇偶页状态，恢复到来源值时移除对应 setHeaderFooter；切换部件/变体或设置首页/奇偶页会先提交未失焦内容，重复 flush 不重复写入。定向测试：`docx-hf-source.test.tsx` 9/9（React lifecycle + observable vendor handle mock）、`docx-recovery.test.tsx` 17/17、`native-session.test.ts` 8/8、`docx-hf.test.ts` 6/6；打印 `workbook-print.test.ts` 16/16、`workbook-print-routing.test.ts` 2/2；TypeScript、生产构建与预算检查通过。**证据边界**：nested editor 测试使用 mock handle，不代替真实 DOCX UI→保存→下载→独立回读→重开验收；浏览器打印仍只调用 `window.print()`，不等效固定源 Electron PrintDialog，且页眉页脚文字、单元格边框与跨打印页合并单元格切片未完整渲染。完整固定源 Word/XLSX 对齐仍未完成。

### Excel 排序官方命令切换（2026-11-06 夜批，root 实现）

- 实证（`workbook-sort-official.test.ts` 固化）：Univer 0.25.1 无 `FRange.sort` facade（固定源 `range.sort` 属其自建层）；官方入口 `sheet.command.sort-range`，参数 `{range, orderRules:[{colIndex(绝对列), type:'asc'|'desc'}], unitId, subUnitId, hasTitle}`；命令经 `reorder-range` 整行重排，网格内值/样式/公式/批注全部随迁（批注走 silent update-note-position，与行列插删同链路）。
- 实现：ribbon 升/降序改为派发官方命令（绝对边界 + 首列键，与固定源 `range.sort({column:0})` 对齐），不再本地逐格写值；main 注册 `UniverSheetsSortPreset`（含 zh-CN locale 与 CSS，此前生产未注册导致命令不可用）。含批注来源仍被 main 结构守卫拦截——引擎 `patchSheetNotes` 补"移动保作者"语义前不放行。
- **投影缺陷修复（影响面大于排序）**：真实 preset 栈回归（`workbook-sort-realstack.test.ts`）暴露 `univer-data.ts` 投影缺 Univer `CellValueType` 标记 `t`，官方排序把数字当字符串按字典序比较，数值列升序静默产生恒等重排（命令成功、值不动）。修复：投影按值类型写 `t`；回读仅取 `v/f/s` 不产生保存伪差异（native-recovery 全过证实）。固定源工作簿载入同样带类型标记，此修复使网格特性（排序/统计栏计数等）按真实类型工作。
- **含批注排序放行（移动保作者语义）**：引擎 `patchSheetNotes` 新增 move change（`{fromRow,fromColumn,toRow,toColumn}`，作者由引擎从源查得、客户端不传身份；三集合校验允许环形置换的键复用、拒绝重复目标/普通变更碰撞；XML 侧删旧 comment/shape 后以原作者重建目标）；桥 Zod union 同步；前端 diff 按**文本跨位置配对**未消费池生成移动（环形置换下每个键都被占，位置互斥配对失效——由真实测试发现并修正），位置相同文本不同仍为就地编辑（引擎保留该位作者）；main 放行官方排序跟随的 `update-note-position`（ref-range interceptor 路径 silent=false 与 watcher 路径 silent=true 均为官方内部事件，事件通道拿不到 options，独立迁移现也安全——payload 移动保作者），popup 保持纯视图跳过。`univer-data`/`notes.ts` 哈希登记更新，引擎 80 文件清单逐项一致。
- 测试：main-notes 新增"排序含批注移动保作者"端到端（真实 Univer 排序→move payload→保存→引擎回读作者 Bob/Alice 各归其位）与"独立迁移捕获为 move 且作者保留"改写用例；前端 7 文件 50/50、引擎 notes+structure 10/10、CLI/openpyxl 5/5、tsc、构建（37.75s）、预算 exit 0、`git diff --check` 全过。
- 浏览器闭环（4203 多作者夹具新构建）：A1:A3 升序后值/格式随迁（A1=28.125、A2=1,234.57 粗体蓝色、B1=56.25 公式重算），批注角标跟随；保存修订 2 payload 恰一条 move（A1→A2）；openpyxl 回读 A2 批注=('来源作者','来源批注，保留作者')、A3 另一作者原位、Details 其他作者原样；重开后批注导航确认 A2 作者与文本完整还原。
- **桥 sortRange 升级为全保真行置换**（server/AI 工具直调路径）：新增引擎 `sortRangeRows`——在 worksheet XML 层置换范围内 `<c>` 记录（值/类型标记/样式索引随行整体迁移，行属性原地保留，与官方网格 reorder 对齐），公式（相对引用会重定位）与范围内批注（作者保留依赖网格 move 路径）整批拒绝并给原因，范围外批注不阻塞。桥 case 从"computeSortChanges 仅重写值"切换；新测试 `sort-rows.test.ts` 2 项（样式随迁 identity 断言 + 拒绝/范围外不阻塞），桥复合测试 6/6 在重建 bundle 上通过。
- **筛选引擎侧持久化**（filter 线，root 授权实现）：`filter-read.ts`+`filters.ts` 读首个工作表级 `<autoFilter>`（customSheetViews 副本忽略）进模型（values/blank + customFilters and/6 operator/1-2 条件、多列），`applySheetFilter` 声明式写回/清除（含隐藏行可见性；矛盾请求整批拒绝字节不动；不支持条件 color/icon/dateGroup/top10/dynamic 拒覆盖允许整体清除；表格重叠拒绝）；列插删平移 ref 并按新首列 rebase filterColumn，行插删平移 ref。桥 `applySheetFilter`（Zod strict）+ Python 允许清单登记。测试：引擎 13 项、CLI openpyxl 独立回读 2 项、定向回归 44 项全过；引擎 84 文件清单逐项一致、SOURCE.md 补记。未达：dateGroup/color/top10/dynamic 读写、表格内筛选路由、calendarType。
- **冻结窗格接线（root，闭环）**：引擎全链早已存在（读 pane/写 page-setup/前端投影）——本轮补最后缺口：ribbon `freeze-panes` 启用（同点再冻结=取消，Excel 语义），main 路由官方 `sheet.command.set-frozen`，`currentOperations` 对比实时 getFreeze() 与 baseline（readBack 不含 freeze）差异经既有 `applyPageSetups` 协议落盘。**浏览器闭环**：选 B2→冻结→保存修订 2→payload 恰一条 applyPageSetups（frozenRows 1/frozenColumns 1）→openpyxl 回读 freeze_panes=B2。测试同步：ribbon 17 项（冻结从禁用断言移除）。
- **网格线持久化闭环**（root，同款补齐）：引擎读模型补 `SheetModel.showGridlines`（sheetView `showGridLines="0"` 才是隐藏，OOXML 默认 true），写回 `applyPageSetups.showGridlines` 早已支持；`currentOperations` 对比 live `hasHiddenGridLines()` 与 baseline 收集差分。**浏览器闭环**：视图→显示网格线→隐藏→保存修订 2→payload 恰一条 applyPageSetups（showGridlines false）→openpyxl 回读 sheet_view.showGridLines=False。引擎 `workbook-read.ts` 哈希登记更新，清单 84 文件逐项一致。
- **筛选 dateGroupItem 读写**（dateGroup 线，root 授权实现）：固定源对照发现 **pinned f8c17004 引擎本身无 dateGroupItem 代码**（读取注释明确丢弃此类列，写回只序列化 values/blank/customFilters）——语义取自 OOXML 规范（ECMA-376 dateGroupItem 粒度链：year 必填+可选 month/day/hour/minute/second+dateTimeGrouping，链上属性须齐备；与 customFilters 同列不合法）。实现：读模型 dateGroups（粒度链校验、上限 1000、游离元素 fail-closed）、写回序列化（属性序同 Excel、非法组合整单拒绝字节不动）、UNSUPPORTED_READ_REASON 收窄到颜色/图标/前十/动态四类；structural 平移无需改（dateGroups 无坐标引用）。**前端边界如实声明**：pinned Univer IFilterColumn 无 dateGroups 字段——dateGroups 仅 server 路径可写，前端差分对含 dateGroups 的源筛选拒绝并报错（不静默丢弃）。测试：引擎 17 项（+3）、相邻 36 项、CLI openpyxl 3 项（DateGroupItem 建档→读出→写回→独立验证）、前端 7 项（含拒绝路径）。清单 84 文件对账一致。
- **XLSX Page Layout 族**（page-layout 线，root 授权实现）：源对照逐项（margins 三预设直切/orientation 两态/paper-size 七项同码表/print-area 选区构造/page-breaks Excel 语义/print-titles clamp 21 行/fit 两轴联动/print-gridlines-headings 打勾切换；scale 按固定源仅打印对话框诚实禁用）。引擎读模型补 pageSetup/pageMargins/printOptions/breaks/printArea/printTitles（man≠"0" 缓存分页排除）+ currentOperations 差分合并 viewSetups 单 op + ribbon 下拉/toggle 全套（zh 对齐、无新 CSS）。测试：引擎 13/13、桥 7 passed（openpyxl 独立回读 orientation/paperSize/scale/fit/边距/print_area/print_title_rows/row_breaks）、前端 41+23。**GUI 下拉闭环**：新修订页面布局→纸张方向选"横向"→保存修订 3→payload 恰一条 applyPageSetups（orientation landscape）→openpyxl 回读 orientation=landscape，且与修订 2 的定义名称（收入额）共存。**边界**：background/toggle-headings 禁用、行列增删不重映射已写分页符（如实声明）。
- **XLSX 名称管理器族**（names 线，root 授权实现）：固定源 NameManagerDialog 语义（列表/新建/编辑/删除、scope 创建时定死）+ 本地 Univer FDefinedName 全套 facade。实现：新 `workbook-defined-names.ts`（liveDefinedNames 实时读、差分→applyDefinedNames、选区绝对地址/引号转义、createModal 对话框无新 CSS）、main 路由（name-manager/define-name/use-in-formula 非空拒绝）、defined-name markDirty 分支、差分收集。测试：`workbook-main-defined-names.test.ts` 6/6（CRUD→op、Undo/Redo 差分回归、非法名/大小写冲突拒绝、失败保存幂等）+ openpyxl 3/3（落盘/原地替换/删除/与 Print_Titles 共存）+ 相邻 48/48。**浏览器闭环**（宿主 4203 重启后）：选 B2→公式→定义名称→对话框（placeholder 与实际值区分明确、"请填写名称和引用"空值校验）→填写 收入额/Summary!$B$2→新建→列表出现"收入额 → Summary!$B$2"→保存修订 2→payload 恰一条 applyDefinedNames（sets 同名同引用）→openpyxl 回读 definedNames 收入额=Summary!$B$2。**边界如实**：工作表级 scope 未接入（引擎只写全局名，面板明示）、纯大小写改名不落盘、工作表改名不重写既有引用（既有引擎限制）。
- **notes-structure venv 探测修复**：测试内固定级数 venv 路径解析依赖 cwd（Page Layout 线跑挂）——改为 cwd 向上探测 `.venv`，18/18 恢复。Page Layout 代理期间一次 stash 误操作当即 pop 恢复，巡检无损。
- **Word 图片粘贴闭环**（image 线，root 授权实现）：调查发现本地 docx 引擎与固定源同构（`SaveBlock {kind:'image'}`/`embedImageMedia` media 去重/rId/docPr 计数/Content_Types 补写全部就绪），零引擎缺口——缺的只是协议接线。实现：新操作 `insertParagraphImage`（mime 白名单 png/jpeg、魔数校验、规范 base64 往返、≤8MB、宽高 1–10000）、diff 以 insertParagraph 同款锚点算法、replay 恢复为完全相同的 `docProtected/genImage` 节点、粘贴入口（picture 模式直贴；默认模式照抄固定源优先级 html>图片>文本；空段/段首贴段前、段尾贴段后、段中 split-twin 同规；表格单元格内明确拒绝）。Python `_OPERATION_KINDS` 登记；dist 重建。测试：pytest 12 项（lxml 独立回读 media 字节逐字节一致/关系/extent=px×9525/inline 非 anchor/非目标部件保留/8 类越界拒绝）+ TS 106 项 + 回归 94+48；tsc 零错误。**边界**：仅内联图片（浮动/裁剪/替换不在本任务）、仅 png/jpeg、表格内贴图拒绝（本地协议无 docInlineImage 操作未硬造）、上游 HTML 含 img 仍按富文本拒绝。浏览器 GUI 位图粘贴依赖系统剪贴板内容，真实引擎链路由 12 项桥读写独立回读覆盖。
- **缩放持久化闭环**（root，同款补齐）：引擎读模型补 `SheetModel.zoomScale`（sheetView zoomScale，OOXML 默认 100，10–400 clamp），ribbon 放大/缩小/重置接官方 `sheet.command.set-zoom-ratio`（±10 个百分点、0.1–4 clamp；嵌套 handler 异步返回的警告按观察到的 getZoom() 判定，不信同步返回值）；`currentOperations` 对比 live getZoom()×100 与 baseline.zoomScale 差异经 `applyPageSetups.zoomScale` 落盘。**浏览器闭环**：放大两档→120%→保存修订 2→payload 恰一条 applyPageSetups（zoomScale 120）→openpyxl 回读 sheet_view.zoomScale=120。zoom-open（缩放对话框）/缩放到选定区域保持禁用；formula-bar/headings 无独立 Univer 运行时命令（固定源为本地状态切换），诚实标注未达。
- **测试基建修复**（我引入问题的根因处理）：FilterPreset 引入后 `@univerjs/sheets-filter-ui` 模块顶层 `new Path2D` 在 jsdom 抛错致三个套件收集失败——新增 `src/test-env-polyfills.ts`（vitest setupFiles：Path2D/DOMMatrix 极简替身）；`workbook-filters` 差分对未注册筛选插件的实例（getFilter 抛服务缺失）与简化替身（无 getFilter）均防御跳过；`workbook-rotation.test.ts` 2 用例同步到此前本地化后的现行行为（中文错误文案、mixed aria-pressed）。全部修复后定向 11 文件 65+ 项与四套件复跑通过。
- **筛选前端接线（root，v1）**：main 注册 `UniverSheetsFilterPreset`（zh-CN locale 来自 `sheets-filter-ui/locale/zh-CN`，exports 映射路径）；新 `workbook-filters.ts` 按 pinned FFilter facade（getFilter/getRange/**getColumnFilterCriteria**——FFilter 无 getCriteria 方法，初版误用被浏览器实测抓出）对 replayed baseline 做声明式快照差分，`currentOperations` 追加于批注之后；源 `FILTER_COMMAND_PATTERN` 六命令在 BeforeCommandExecute 统一守卫；ribbon `filter-toggle`/`filter-clear`/`filter-reapply` 接官方命令（补 action 第三参 command 后才真正可点），`filter-advanced` 保持禁用；smart-toggle 内部子命令异步返回被 CommandService 记录为警告，反馈改为按观察状态（getFilter 是否存在）判定。差分测试 3/3。
- **筛选浏览器闭环**（4203 新构建）：A1:A3 拖选→筛选→A1 表头箭头出现→中文面板（升序/降序/按值/按色/按条件/全选/取消/确认）→取消一项→确认→行 3 隐藏（网格可见性与条件一致）→保存修订 2。payload 两条 applySheetFilter（安装空条件快照 + 条件快照，最终文件状态正确）；openpyxl 回读 auto_filter.ref=A1:A3、filterColumn colId 0 带条件、A1 批注作者保留；行可见性 v1 不写文件（row3 hidden=False，已声明）。
- **Word 段落边框 pBdr**（border 线，root 授权实现）：固定源段落语境仅 Home 六项（b/t/l/r/tblr/无框线，`setParaAttr({borders})` 整体替换、单实线默认 sz=4 八分点/color auto/space 0）；`between` 合并是源显示层装饰（vendor 层既有，写路径永不产生 between）——源含 between/bar/nil/none/double/themeColor/嵌套/双容器 pBdr 整体拒绝（fail closed）。实现：`docx-borders.ts` 严格校验、`setParagraphBorders` 协议（同段独占批次照底纹先例）、桥 `paragraphBordersXml` 按 PPR_CHILD_ORDER 有序补丁、Python 允许清单、Home 边框分体按钮（位置六项+宽度 0.5/0.75/1.5/2.25/3pt+底纹同款 20 色板+自动颜色，复用 spacing-menu/色板类无新 CSS 需求）。测试：TS 6+ribbon 17+相关 90、pytest 6（源子序/keepNext 顺序/非目标段落/元数据保留/拒绝清单）+回归 93+138。**浏览器闭环**：第二段应用"所有框线"→画布渲染边框→保存修订 2→payload 恰一条 setParagraphBorders（4 sides 0.5pt 000000）→openpyxl 回读 pBdr 子序 top-left-bottom-right、sz=4、仅 document.xml 变化→重开画布边框还原。
- **预算**：`lazy-workbook-icons` 272→274 KiB（filter preset UI 图标并入共享图标 chunk，已注释依据）。并发事件记录：01:47 另一会话代理曾 stash 全部 dirty（已 apply 恢复、stash@{0} 保留备份、关键文件逐一核验无损）；pBdr 代理运行中看到的 find-replace 失败与 notes-structure 失败均为并发编辑中间态，复跑全过。`test_native_ribbon_http_roundtrip.py[pdf]` 的失败根因亦非测试问题：HEAD 的 PDF cropPage 功能未重建进 `pdf_engine/dist/cli.mjs`，bundle 重建后 1 passed（连同 xlsx/docx/pptx 引擎 bundle 一并核对为新鲜构建）。
- 测试：ribbon 派发/失败提示/单行守卫 + 排序语义固化 + 真实栈回归共 39/39 通过（含 native-recovery 回读往返）；tsc 通过；标准构建（37.67s）与预算 exit 0；`git diff --check` 通过。
- 浏览器闭环（4202 新构建）：A1:A3 拖选（统计栏求和 1262.69 验证选区）→ 升序 → 保存修订 2。payload 恰两条 `applyCellEdits`：A1=28.125 且获得原 A2 的斜体/Arial/12 样式，A2=1234.567 且获得原 A1 的粗体/Calibri/14/字体色/填充/#,##0.00 格式——值与样式随行迁移；B1=`=A1*2` 公式保留（范围外公式按源语义重算）。openpyxl 回读 A1=28.125/A2=1234.567；重开修订 2 画布 A1=28.13（Arial 12 斜体）、A2=1,234.57（粗体蓝色千分位格式）、B1=56.25、状态干净。

### Word 段落底纹（2026-11-06 夜批，root 实现）

- 固定源对照：段落组底纹拆分按钮打开共享 `RibbonColorPalette`（THEME_COLORS+STANDARD_COLORS 20 色 + 无颜色），`setParaAttr({shadingFill})` 写段落属性（Ribbon.tsx:4394-4412、ribbon-color-palette.tsx:4-31）；pinned 编辑器 schema 已含 `shadingFill/shadingClear`（extensions.ts:342-346）。本地按此实现 `docx-shading.ts`（同 20 色板 + 无颜色；显式 auto 走 `shadingClear` 协议通道，UI 暂不暴露）。
- 协议：新增 `setParagraphShading`（fill 六位 hex | null + clear 布尔），与段落样式同规——同段同批次仅底纹、不能与文字/格式混存；桥按 OOXML `PPR_CHILD_ORDER` 有序插入/替换/删除 `w:shd`（val=clear、color=auto），源含 pattern/theme shd 整体拒绝；底纹-only 补丁沿用 core.xml 保留；Python 允许清单已登记。
- 测试：前端 `docx-shading.test.ts` 4/4（应用/auto/none、混合拒绝、回放字段与批次校验、撤销重做）；受影响 3 文件 93 项通过；tsc 通过。Python `test_docx_paragraph_shading.py` 3/3（有序插入+直接格式/其他部件保留、替换/删除/显式 auto、pattern 拒绝+非法值+批次冲突）。
- 浏览器（4203 新构建）：第二段应用 `#156082` 画布即时渲染 rgb(21,96,130)；保存修订 2 签发下载；payload 恰一条 `setParagraphShading`；下载字节与产物一致；python-docx 独立回读 `w:shd=(clear,auto,156082)`、仅 `word/document.xml` 变化；重开修订 2 底纹还原、首段干净。隔离宿主重启导致 python-docx 夹具 ZIP 时间戳变化引发一次 409，属本夹具非确定性（生产源 SHA 由服务端固定），换新会话后不复现。
- 未达项：段落边框（pBdr 位置矩阵/线型/邻段合并，源 para-border-merge 深系统）未实现；底纹 UI 无 pattern/主题继承入口；空段落与表格内段落按高亮同规则暂不支持。

## 未完成边界

完整单元格格式对话框、清除格式、保护/筛选、Chart Design 与四个 XLSX 上下文页签，Word 复杂表格、标题/编号样式转换、剪贴板、Go To 独立导航及完整源 tabs/groups/context 尚未完成。含批注排序仅安全拦截（官方 `range.sort` 语义未对齐）；线程批注/批注图片/持久化弹窗可见性/上下标明确不支持。Word 查找替换的超大文档仍为同步扫描。没有完整应用新镜像、生产身份/数据库/部署网络或 Microsoft Office 桌面验收。功能开关仍关闭。
