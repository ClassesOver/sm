# XLSX 高级透视与允许编辑区域（2026-11-11）

本次在已有工作区基础上同时接通第 4、5、6 项的本地入口与可保存能力。以下区分编辑器行为、实际文件状态和桌面 Excel 控件能力。

## 切片器与时间线入口

- 插入页签支持成员多选、日期区间筛选；默认保存透视成员选择，可另外勾选“保存原生控件”。
- 原生控件保存切片器/时间线定义、缓存、工作簿和工作表扩展、关系、内容类型及 DrawingML 锚点和兼容回退。重开通过严格关联校验识别本工具支持的控件。
- 原生时间线仅支持带日期格式的真实数值日期，保留用户的完整起止区间，刷新时按原区间过滤新增日期。ISO 日期文本仍可执行成员筛选，不能创建原生时间线。
- 当前仅支持非 OLAP、单透视缓存、未分组行/列字段；同一透视表可为不同日期字段创建多个原生时间线，按各自区间共同筛选。外部或结构损坏的控件保留且只读。已有本工具控件随透视编辑和刷新同步，不能将未知缓存孤立改写。
- 筛选对话框支持删除当前原生控件并保留当前成员筛选；清理该控件专属定义、缓存、关系、命名项、内容类型和绘图锚点，其他控件保留。损坏关联或额外所有者引用时拒绝删除。
- 筛选对话框可编辑原生控件左上角单元格和宽高像素，支持保存重读；未勾选原生控件时禁用几何输入，成员筛选不受这些参数限制。位置和尺寸保存前执行边界校验。
- 工作表画布显示通过所有权校验的本系统原生控件，支持成员勾选与日期区间筛选；位置和尺寸可通过筛选对话框或画布移动/尺寸句柄编辑，支持取消、保护校验、撤销/重做及保存重开。未对桌面 Excel 执行实测，不把 XML/独立读者验证称为 Excel 兼容认证。

## 高级透视

- 本地配置可定义日期/数值分组、计算字段、报告筛选；列轴允许多个值字段。
- 来源可以绑定工作簿内的命名 Excel 表；表名引用忽略大小写，读取及保存使用实际表名，刷新时读取表的当前区域，不含合计行。表格改名同步迁移标准缓存来源和本系统透视状态；仍被透视引用的来源表禁止转换为普通区域。
- 完整自有状态且所有原生控件可完整校验时，支持列数和物理位置不变的来源字段更名，标准缓存、计算公式、私有状态和本系统切片器/时间线字段引用同步迁移；分组、筛选索引和控件选择保留，用户刷新后才重算输出。不完整导入状态、未知/损坏控件、删列或挪列仍受保护限制。
- 重排共享缓存中的单个透视表会隔离其缓存和记录，并保留兄弟透视表原定义及缓存。
- 人工成员选择与标签/值规则的派生隐藏分开保存，字段重排后按字段名称跟随筛选归属。
- 日期分组按工作簿日期系统计算。无空值的真实数值区间及可表达的日期序列使用标准 `fieldGroup/rangePr/groupItems`，保留原始类型缓存及记录，并使用完整分组成员索引。文本、空值、1900 日期序列 60 等不能保真的来源保留私有兼容分组，记录具体原因，不宣称标准分组。
- 无法保真的外部高级透视结构仍保持只读。公式来源刷新仍需要确认计算结果，不能把陈旧缓存当最新结果。

## 允许用户编辑区域

- 审阅页签支持定义、编辑、删除不带密码的区域，标准 `protectedRanges` 写入完整 XLSX 后可重开读取。
- 工作表受保护时，仅区域内的值和公式可编辑；越界、格式、结构和表头元数据变更仍拒绝。命令端校验实际写入位置，保存端再次校验。
- 兼容真实键盘提交附带的空富文本清理标记及局部字体补丁。保护路径在完整验证写入区域和载荷后，只将值/公式交给原生命令，剥除附带的样式字段以保留原格式；纯格式请求仍拒绝。
- 带密码、用户权限描述符或不支持属性的原有定义保留且只读；不支持密码解锁、Windows 用户权限或基于 `xf` 的解锁单元格权限。

## 验证与证据

- 引擎原生控件和标准分组定向回归 16 项通过；包含原始缓存/分组索引、刷新、损坏关联拒绝、日期区间保留及新增日期过滤，标准分组还经 openpyxl 独立解析。
- 前端筛选/对话框/保护定向回归 17 项通过，保存桥集成另 1 项通过。首次并发运行保存桥用例超时，单独复验通过；未重复完整测试。
- Python 原生保存协议经真实 Node 引擎写出切片器后，openpyxl 和 ZIP/XML 独立读取通过。openpyxl 不支持控件扩展，仅用于读取，未用它回存产物。
- 前端 `npm run build`、引擎 `npm run typecheck` 通过。拆出 Ribbon、透视纯计算及图表纯函数模块后，构建预算通过，未提高阈值。最终主包 182.6 KiB、引擎 396.4 KiB；日志 `/tmp/xlsx-controls-budget-final.log`。
- 实际构建 Chromium 验收 `/tmp/xlsx-pivot-protection-built/receipt.json`：`ok=true`、`saveCount=2`、`errors=[]`。覆盖 Ribbon 区域管理、保护区域真实键入、多值透视、原生切片器、原生时间线、撤销/重做、保存修订 2、重开后黄色区域键入、再保存修订 3。
- 独立回读确认两个原生控件部件存在，时间线保存完整 2026-01-01 至 2026-01-31 区间，透视金额 10/数量 1，工作表仍受保护，修订 2→3 的 `xl/styles.xml` 完全相同。产物与截图在上述证据目录。
- 浏览器脚本 `frontend/smoke/workbook-pivot-protection-built-smoke.mjs` 使用真实保存引擎；HTTP 身份及修订登记为本地夹具，不代表生产授权链路或桌面 Excel 验收。

## 多时间线继续实施

- 移除同一透视表仅一个时间线的限制；不同日期字段可使用各自独立的原生区间，共同约束透视结果。同一字段重复控件及未知外部结构仍拒绝。
- 同步先完成全部透视重建，再统一写回所有原生控件、日期缓存和筛选。原生 filter 原位更新，保留多个筛选的顺序，避免后一次重建覆盖前一个控件。
- 定向验证：引擎控件 9 项、前端保存桥及筛选对话框 4 项通过；覆盖双日期字段变化、区间外新成员隐藏、独立区间修改。前端完整构建、引擎类型检查、体积预算及预算契约通过；没有重复完整测试或提高阈值。
- 实际构建浏览器最终证据 `/tmp/xlsx-multi-timeline-built/receipt.json`：`ok=true`、`saveCount=2`、`errors=[]`。本地入口创建一个切片器和两个时间线、全部刷新、撤销/重做、保存重开及黄色保护区域再保存均通过。openpyxl/ZIP 独立确认两个 `dateBetween` 筛选及各自完整日期边界；金额 10、数量 1；两修订间 `styles.xml` 字节不变。仍未进行桌面 Excel 实测。

## 原生控件删除继续实施

- 共享 Node/Python 协议增加严格 `removePivotControl` 操作，本地按钮复用草稿身份核对、保护检查、预演失败回退及原生撤销/重做。
- 引擎 11 项、前端定向 4 项和 Python 真实保存回归通过。引擎类型检查及 Vite 实际构建通过，体积预算和预算契约通过且阈值不变。
- 全局前端类型检查仍被并行 Word 改动阻挡：`src/docx-ruler.test.tsx:25` 的 `extendedIndents` 不在 `Options` 中；日志 `/tmp/xlsx-control-delete-frontend-tsc.log`，未修改该区域或宣称全局门禁通过。
- 实际构建浏览器证据 `/tmp/xlsx-control-delete-built/receipt.json`：`ok=true`、`saveCount=2`、`errors=[]`。重开修订 2 后在本地入口删除一个时间线，撤销/重做后保存修订 3；独立回读确认已删控件、缓存、命名项和锚点不存在，兄弟时间线、切片器、当前透视金额 10/数量 1、工作表保护与样式均保留。

## 控件位置与尺寸继续实施

- 复用现有 `anchor` 操作协议，增加左上角单元格及整数像素宽高；支持小写地址输入并规范化显示。工作表地址和尺寸必须在现有引擎约束内。
- 前端保存桥和筛选对话框 4 项、引擎控件 12 项定向验证通过；覆盖非法位置拒绝、重开位置恢复、控件移动/缩放及兄弟控件、缓存、透视状态保留。
- 引擎类型检查、Vite 实际构建、体积预算和预算契约通过；没有提高阈值或重复完整测试。全局前端类型检查仍受 `docx-ruler.test.tsx:25` 的既有 `extendedIndents` 类型错误阻挡，见 `/tmp/xlsx-control-geometry-tsc-final.log`。
- 实际构建浏览器最终证据 `/tmp/xlsx-control-geometry-built/receipt.json`：`ok=true`、`saveCount=2`、`errors=[]`。重开后将原生切片器设为 M5、320×180 像素；撤销/重做、重新打开对话框读取几何值、保存修订 3 均通过。独立 XML 回读确认锚点 row=4/column=12、宽高 EMU=3048000/1714500；兄弟时间线、筛选金额 10/数量 1、工作表保护和 `styles.xml` 均保留。对话框截图 `control-position.png` 已检查，未出现遮挡或裁切；仍不代表工作表画布拖动或桌面 Excel 实测。

## 工作表控件显示与交互继续实施

- 复用 Univer 官方范围浮层与 React 组件注册，按已保存的单元格锚点和尺寸显示本系统创建的原生切片器、时间线。仅投影通过引擎所有权校验的控件，未知或损坏外部控件不作为本地可编辑控件。
- 支持成员勾选、全选、日期边界和应用筛选；完整日期区间保留。应用前重新读取当前草稿，确认透视定义、控件和成员没有变化，复用既有透视事务、保护校验及撤销/重做，保留无关单元格编辑。
- 切换工作表和重新载入时清理组件、浮层及旧事件；挂载失败回收部分注册。通过可编辑状态订阅、保护切换通知及宿主 `inert` 属性观察同步禁用状态，避免解除保护或事务解锁后控件一直禁用；刷新状态不会丢弃未提交的勾选。
- 21 项前端定向回归通过，包括控件模块 8 项、筛选 5 项、原生宿主 4 项、对话框 3 项、保存桥 1 项。独立只读评审发现的保护解除问题已修复并复核通过。没有重复完整测试。
- Vite 实际构建、既有体积预算和预算契约通过；主包 185.6 KiB、引擎 399.0 KiB、控件模块 6.5 KiB，未提高阈值。全局 `tsc` 仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 类型错误，见 `/tmp/xlsx-canvas-unlock-tsc.log`。
- 最终构建浏览器证据 `/tmp/xlsx-canvas-controls-unlock/receipt.json`：`ok=true`、`saveCount=2`、`errors=[]`。覆盖切片器勾选、时间线区间往返、缩放（控件宽度 188→207.1875）、滚动、跨表隐藏恢复、初始保护控件解除保护后恢复输入、原生历史及重开后已有无关单元格编辑时应用筛选。独立回读确认透视金额 10/数量 1、Inputs 仍保护且 B3=`reopened`、Pivot 已解除保护、两修订间 `styles.xml` 字节相同；删除和 M5 几何保存也保留。`canvas-controls.png` 已检查，三个控件完整可见且不重叠。HTTP 身份与修订登记仍是本地夹具。
- 控件位置和尺寸仍通过对话框编辑；未实现画布拖动和尺寸句柄。此阶段浏览器范围为普通 LTR 工作表；冻结窗格和 RTL 的后续验证见下节，桌面 Excel 尚未实测。

## 冻结窗格与 RTL 控件继续实施

- 实际构建先复现 RTL 方向切换后控件仍在旧坐标、切表后才恢复的问题。控件现在订阅原生 RTL mutation，在下一帧重新读取单元格几何并挂载；同帧事件合并，销毁后不再挂载。只重建会话浮层，不改变保存的 OOXML 锚点。
- 会话内保留未应用的成员勾选及开始/结束日期，方向切换或跨表重新挂载不会丢弃这些输入；完整工作簿事务重载仍从真实文件状态初始化。新增回归先失败后修复，控件模块 9 项定向测试通过；只读评审通过。
- 增加 `--viewport-only` 定向浏览器入口，通过 `WORKBOOK_SMOKE_SOURCE_XLSX` 复用既有保存产物，不重跑区域管理、创建透视表及创建控件的完整流程。测试比较控件间的锚点间距，避免把定位产生的一致视口平移误判成控件漂移。
- 最终证据 `/tmp/xlsx-controls-viewport-rtl/receipt.json`：`ok=true`、`saveCount=1`、`errors=[]`。覆盖 LTR 与 RTL 冻结 14 行/1 列后滚动、冻结带内切片器按钮真实命中、RTL 切换及跨表恢复、未应用成员和日期输入保留、RTL 筛选、保存重开。已检查 `frozen-controls.png`、`rtl-frozen-controls.png`、`rtl-reopened.png`。
- ZIP/openpyxl 独立确认 `rightToLeft=true`、`freeze_panes=B15`，原生 `drawing1.xml` 及 `styles.xml` 与来源字节相同，两个时间线和既有筛选、Inputs 保护及可编辑值保留。
- Vite 构建、原有体积预算及预算契约通过，主包 185.6 KiB、引擎 399.0 KiB、控件模块 6.8 KiB，未提高阈值；全局 `tsc` 仍只有既有 `docx-ruler.test.tsx:25` 错误，见 `/tmp/xlsx-controls-rtl-tsc.log`。
- 已确认的边界：控件跨越冻结分隔线时会按原生范围浮层规则裁切；本轮只验收控件完整位于冻结带内或可滚动区的场景，未把跨分隔线标为完整支持。画布拖动/尺寸句柄与桌面 Excel 实测仍未完成。

## 跨冻结分隔线控件继续实施

- 实际构建先复现 B3 冻结后纵向滚动导致切片器底部按钮被裁切；增加控件外框、真实命中及布局生命周期回归。通过官方 `CanvasFloatDomService.updateFloatDom` 包装本系统控件的布局流：冻结锚点所在轴保持整体尺寸，仅在网格外边缘裁切；非冻结轴继续使用原生规则。位置使用当前 skeleton 和冻结视口偏移，尺寸使用原生缩放结果，不修改 OOXML 几何。
- 冻结切换后原生内部对齐状态滞后到下一次滚动，产生 2 像素跳动；订阅 `SetFrozenMutation`，复用已有下一帧重挂载和未提交草稿保留。先失败后修复，控件模块 11 项定向测试通过；只读评审及冻结事件增量复核通过。
- 最终实际构建证据 `/tmp/xlsx-controls-crossing-built/receipt.json`：`ok=true`、`saveCount=1`、`errors=[]`。覆盖 B3 跨行冻结线、K3 跨双向冻结线、125% 缩放与双向滚动、RTL 冻结列、RTL 跨行冻结线、按钮真实命中及保存重开后再次滚动。已检查 `crossing-both-dividers.png`、`rtl-frozen-columns.png`、`rtl-reopened.png`。
- ZIP/openpyxl 独立确认 `rightToLeft=true`、`freeze_panes=B3`，`drawing1.xml` 与 `styles.xml` 和来源字节完全一致；两个时间线、原生筛选、金额 10/数量 1、保护区域和可编辑值保留。视口定向 smoke 固化冻结、RTL 和绘图字节保留断言。
- Vite 实际构建、原有体积预算和预算契约通过，主包 185.6 KiB、引擎 399.0 KiB、控件模块 8.5 KiB，未提高阈值。全局 `tsc` 仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 类型错误，见 `/tmp/xlsx-controls-crossing-tsc-final.log`。未重复完整测试。
- 控件彼此重叠时仍遵循原生绘图层顺序；跨线支持不代表改变绘图遮挡关系。画布拖动/尺寸句柄和桌面 Excel 实测仍未完成。

## 画布移动和尺寸句柄继续实施

- 本系统原生切片器和时间线增加标题“移动”按钮及右下角尺寸句柄。移动按原生 viewport/skeleton 命中吸附单元格；尺寸按当前缩放换算并保存整数像素。手势期间仅预览当前控件浮层，松开后才写入几何；Esc、指针取消、滚动、布局变化、销毁或锁定取消预览，工作表保护及事务忙状态禁用句柄。
- 几何提交重新核对原控件身份、来源和保护状态，仅追加一个 `upsertPivotControl` 操作，复用现有保存、失败回退及撤销/重做。未应用的成员勾选和日期输入通过稳定控件身份保留在会话中，不随几何操作写入文件或重算透视结果。
- 27 项定向测试通过：几何手势 13 项、控件模块 12 项、真实保存桥 2 项。包括实际 RTL `SpreadsheetSkeleton` 在非零滚动与 100%/125% 缩放下命中，修复重复扣除滚动偏移的问题；严格 JSON 和真实 NativeDraft 回归防止可选字段携带 `undefined`。只读评审及修复复核完成，未重复完整测试。
- 最终实际构建 Chromium 证据 `/tmp/xlsx-controls-drag-built/receipt.json`：`ok=true`、`saveCount=1`、`errors=[]`。覆盖保护切换、时间线尺寸修改及独立撤销、Esc 取消、125% 下切片器缩放、移动、RTL K3 冻结视图拖动、撤销/重做、未提交筛选保留及保存重开；最终切片器为 M5、320×180 像素。已检查 `dragged-and-resized.png`、`rtl-geometry.png`、`geometry-reopened.png`，覆盖布局中句柄和控件内容可读。
- 独立 ZIP/XML 证据 `/tmp/xlsx-controls-drag-built/ooxml-preservation.json`：目标锚点 row=4/column=12、尺寸 EMU=3048000/1714500；`styles.xml`、透视表定义、两个时间线定义及缓存字节完全一致，兄弟时间线 DrawingML 锚点不变。重开仍保持原成员和完整日期筛选，金额 10/数量 1、保护及允许编辑区域保留，确认会话中待应用筛选未被几何保存误写入。
- Vite 实际构建、原有体积预算及预算契约通过，未提高阈值。日志 `/tmp/xlsx-control-drag-vite-final.log`、`/tmp/xlsx-controls-drag-budget-final.log`、`/tmp/xlsx-controls-drag-budget-contract.log`。全局 `tsc` 仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 类型错误，见 `/tmp/xlsx-control-drag-tsc-final.log`。浏览器使用真实构建与 Python/Node 保存引擎，HTTP 身份和修订登记仍为本地夹具；桌面 Excel 实测仍未完成。

## 几何保存保留断言继续实施

- 将上轮独立 XML 检查固化到 `--geometry-only` 的正常验收中。首先注入透视值字段名称误改，确认旧检查仍返回成功，再增加部件清单及内容保留断言，避免仅凭透视数值和目标位置正确就漏过其他结构误改。
- 检查透视定义/缓存、时间线定义/缓存、切片器缓存、样式、内容类型及关系字节保留；目标切片器定义只允许私有请求中的 anchor 变化，绘图只允许目标的位置和尺寸变化。兄弟锚点、目标外观/关联保持一致，目标元数据必须与实际 M5、320×180 绘图一致。此断言针对既有几何 smoke 的固定夹具，不扩张为任意工作簿兼容认证。
- 新增 `--geometry-only --inspect-only` 入口，使用 `WORKBOOK_SMOKE_SOURCE_XLSX`、`WORKBOOK_SMOKE_SAVED_XLSX` 指定已有文件，通过 `WORKBOOK_SMOKE_EVIDENCE_DIR` 输出独立回执，不启动 Chromium。真实产物验收 `/tmp/xlsx-geometry-preservation-inspection/inspection-receipt.json`：`ok=true`、`inspectionOnly=true`；记录源/保存文件 SHA256、14 个字节不变部件、兄弟锚点保留、目标外观保留及元数据一致。
- `frontend/smoke/workbook-pivot-controls-preservation.contract.mjs` 使用同一组源/保存文件做故障注入：透视定义、时间线定义、时间线缓存、兄弟锚点、切片器标题、切片器缓存、部件新增、部件缺失，共 8 类。有效文件通过，8 类误改均由明确的“几何保存保留”断言拒绝，而非依赖 openpyxl 解析偶然失败。先失败日志 `/tmp/xlsx-geometry-preservation-red.log`，通过日志 `/tmp/xlsx-geometry-preservation-green.log`；两项脚本 `node --check` 通过。
- 本轮仅修改定向验收脚本及文档，未重复应用完整测试、构建或浏览器创建流程。本地提供 LibreOffice，但没有可用桌面 Excel，未用其他读者替代 Excel 实测结论。

## 独立验收回执生命周期继续实施

- 复现 `--inspect-only` 本轮验收失败后，证据目录仍遗留上轮 `inspection-receipt.json` 成功回执的问题。独立验收现在于参数校验和输入读取前清除旧回执，只有本轮所有文件检查通过后才重新写入成功结果，避免旧结果被下游误用。
- 扩展既有文件保留契约：同一证据目录预置成功回执，依次注入 8 类结构误改，并补充来源文件缺失、保存文件缺失；10 种失败均返回非零状态且不留下成功回执。有效文件首次通过，失败后再次输入有效文件仍能生成真实 SHA256 对应的新回执。
- 先失败日志 `/tmp/xlsx-geometry-receipt-red.log` 明确报告“失败后仍遗留成功回执”；修复后 `/tmp/xlsx-geometry-receipt-green.log`：`ok=true`、`validFiles=2`、`staleReceiptsCleared=10`、`recovery=true`。两项脚本 `node --check` 及定向 `git diff --check` 通过；仅运行受影响的验收契约，未重复应用完整测试、构建或浏览器创建流程。桌面 Excel 实测仍未完成。

## 动态透视来源表大小写继续实施

- 修复透视来源匹配与既有表格编辑不一致的问题：本地创建、现有透视读取及保存引擎按忽略大小写匹配表 `name`/`displayName`，读取返回实际表名，创建/刷新将实际表名写入标准缓存来源和私有透视状态。`sAlEs` 引用现有 `Sales` 不再被误判为来源缺失。缺失表、非单行表头和不支持表结构的保护限制继续保留；本轮不涉及来源表改名迁移。
- 新增 4 项回归先失败后通过，覆盖混合大小写创建、绕过前端 planner 的直接保存、带/不带本系统元数据的导入重开及来源表扩容后刷新。前端 31 项、引擎 15 项定向测试通过，日志 `/tmp/xlsx-pivot-table-case-final.log`、`/tmp/xlsx-pivot-table-case-engine-tests.log`。没有重复应用完整测试。
- 定向检查另发现 2 项旧刷新测试失败；通过内存恢复本轮修改前代码，确认两项在修复前同样失败（`/tmp/xlsx-pivot-table-case-baseline.log`）。缓存归属失败改为校验错误类型，减少对旧文案的依赖；外部高级透视夹具移除本系统元数据后再注入不支持结构，保留未知结构只读测试的原意。
- 引擎类型检查、共享 Node 桥打包、Vite 实际构建、原有体积预算及预算契约通过，未提高阈值；前端全局类型检查仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 错误，日志 `/tmp/xlsx-pivot-table-case-frontend-tsc.log`。本地引擎源码哈希已登记并定向核验，未改写原始来源快照。
- 复用 `workbook-pivot-refresh-built-smoke.mjs --table-case-source` 验证真实构建。最终证据 `/tmp/xlsx-pivot-table-case-built/summary.json`：`ok=true`、`tableCaseSource=true`、`saveCount=1`、`errors=[]`，144 项运行时资源与实际构建文件身份一致。导入 `worksheetSource name="sAlEs"` 后，初次及保存重开编辑对话框均选中 `Sales`；涵盖原有无关草稿、刷新结果增长/收缩、撤销/重做、草稿恢复、保存下载及重开。
- openpyxl/ZIP 独立回读确认缓存引用规范为 `Sales`，汇总 180、旧输出尾部清空、来源手工编辑保留；`xl/tables/table1.xml` 和 `xl/styles.xml` 与来源字节完全相同。已检查 `initial-table-source.png` 与 `reopened-table-source.png`，来源表及字段可读。HTTP 身份和修订登记仍为本地夹具，桌面 Excel 实测仍未完成。

## 动态透视来源表改名继续实施

- 修复表格改名后留下旧透视来源的问题。共享保存引擎在同一 ZIP overlay 内迁移匹配的标准 `worksheetSource@name` 和通过验证的本系统透视状态；支持原名/显示名别名、仅改大小写及同批连续改名。只迁移来源身份，不重算缓存记录、输出、筛选或控件；标准导入透视保留原定义，外部来源或来源/缓存归属不一致时拒绝迁移。
- 仍被透视表作为动态来源使用的表不能转换为普通区域，保存端同样拒绝 `remove`。Ribbon 转换入口先使用当前完整草稿执行真实引擎预演，失败时不移除网格表格、不改变草稿；普通无依赖表仍沿用既有转换和撤销流程。
- 前端 50 项、引擎 35 项定向测试通过；涵盖改名后刷新、仅改大小写、连续改名、导入定义保留、原生控件保留、转换拒绝、归属不一致、命名空间/实体/注释及外部来源拒绝。先失败证据 `/tmp/xlsx-pivot-table-rename-red.log`（5 项）、`/tmp/xlsx-pivot-table-source-guard-red.log`（2 项）；最终日志 `/tmp/xlsx-pivot-table-rename-frontend-final.log`、`/tmp/xlsx-pivot-table-rename-engine-final.log`。旧“孤立表关系应可删除”测试与现有严格来源读取冲突；内存移除本轮迁移调用后仍复现同一失败（`/tmp/xlsx-pivot-table-rename-baseline.log`），已调整为拒绝未登记关系并验证源文件不变。
- 引擎类型检查、共享 Node 桥打包、Vite 实际构建、原体积预算及预算契约通过，未提高阈值。5 个新增/修改引擎源码及测试哈希登记并定向核验；前端全局类型检查仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 错误，见 `/tmp/xlsx-pivot-table-rename-frontend-tsc.log`。未重复应用完整测试。
- 实际构建 `workbook-pivot-refresh-built-smoke.mjs --table-rename-source` 验收通过：`/tmp/xlsx-pivot-table-rename-built/summary.json`，`ok=true`、`tableRenameSource=true`、`saveCount=1`、`errors=[]`，144 项资源身份与构建一致。覆盖 Ribbon `Sales→CurrentSales`、撤销恢复 `Sales`、重做跟随 `CurrentSales`、转换拒绝后表格和草稿保留、刷新增长/收缩、草稿恢复、保存下载及重开。
- 独立证据 `/tmp/xlsx-pivot-table-rename-built/independent-source-identity.json` 确认表 `name`、`displayName`、标准缓存引用及私有状态均为 `CurrentSales`，范围 `A1:B5`，`styles.xml` 字节不变；openpyxl 汇总 180、旧输出尾部清空、手工草稿保留。已检查 `reopened-table-source.png`，来源与字段可读。HTTP 身份和修订登记仍为本地夹具，桌面 Excel 实测仍未完成。

## 动态透视来源表标题行保护继续实施

- 复现动态命名来源允许关闭标题行、保存后无法刷新的缺口，3 项新增回归先失败（`/tmp/xlsx-pivot-header-red.log`）。保存引擎在改写表格前复用标准缓存/私有状态依赖检查，拒绝关闭仍被动态透视引用的标题行；支持标准导入来源及同批改名后检查，失败不改源文件。普通表、固定区域透视来源和保留标题行的样式编辑继续允许。
- Ribbon 在清空原生字段名单元格前，用当前完整草稿执行真实引擎预演；失败保留标题行勾选、单元格、表格、草稿和撤销记录。前端 44 项、引擎 25 项定向回归通过，日志 `/tmp/xlsx-pivot-header-frontend.log`、`/tmp/xlsx-pivot-header-engine.log`；只读代码评审未发现具体回归问题，未重复完整测试。
- 引擎类型检查、共享 Node 桥打包、Vite 实际构建及原体积预算/预算契约通过，两个修改引擎源文件的来源哈希已登记核验。前端全局类型检查仍只有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 错误，日志 `/tmp/xlsx-pivot-header-frontend-tsc.log`。
- 扩展现有 `--table-rename-source` 浏览器定向验收，通过拒绝关闭标题行、草稿不变、上一条改名直接撤销/重做、刷新、草稿恢复、保存下载和重开验证。证据 `/tmp/xlsx-pivot-header-built/summary.json`：`ok=true`、`saveCount=1`、`errors=[]`，144 项运行时资源身份与构建一致；已检查拒绝截图和重开来源对话框。
- openpyxl/ZIP 独立证据 `/tmp/xlsx-pivot-header-built/independent-source-header.json` 确认 `headerRowCount=1`、字段名 `Category/Amount`、来源 `CurrentSales`、范围 `A1:B5`、汇总 180 及样式字节不变。HTTP 身份和修订登记仍为本地夹具；字段更名/删列的透视身份协同迁移及桌面 Excel 实测仍未完成。

## 动态透视来源字段保护继续实施

- 保存引擎在表格列改写出包前，检查标准缓存与私有来源状态仍引用的字段，拒绝更名、清空或收缩移除；按旧物理列对应的新名称比较，避免交换表头但名称集合不变时放行并取错数据。保留普通表、固定区域来源、行数伸缩，以及未进入缓存的新列新增/撤销；自动字段身份迁移仍未实现。
- 前端将同一字段依赖检查接入基础值 mutation、输入/清空、合并后的粘贴计划和表格调整范围，在单元格、汇总行和历史变动前拒绝。按原表身份匹配文件缓存，普通表复用来源旧名不被误拦截。缓存 XML 完整验证，忽略外来命名空间/注释并兼容实体、大小写、导入 ST_Xstring 和旧本地 `_xNNNN_` 字面字段。
- 浏览器首轮复现粘贴拒绝成为未处理页面异常（`/tmp/xlsx-pivot-source-fields-browser.log`）。修复仅捕获本模块计划标记的拒绝，在官方公共剪贴板入口反馈并返回 `false`，未知异常继续抛出，销毁恢复原方法。清空采用官方 `CustomCommandExecutionError` 取消；重新粘贴先撤销原批次的边界通过原 undo 元素身份核对及官方 Redo 精确恢复，真实 Univer 测试验证格式、字段名及 undo/redo 指针不变。
- 前端分组定向回归合计 64 项、引擎 36 项通过；前端主体日志 `/tmp/xlsx-pivot-source-fields-frontend-final.log`，新增粘贴/清空/重新粘贴最终 15 项见 `/tmp/xlsx-pivot-source-fields-paste-clear-final.log`，引擎见 `/tmp/xlsx-pivot-source-fields-engine-final.log`。初始保存缺口、转义/大小写、旧名复用、循环更名及粘贴取消均有先失败证据。只读评审发现的问题均已修复并复核，未重复完整测试。
- 引擎类型检查、共享 Node 桥打包、最终 Vite 构建及原预算/预算契约通过，4 项引擎源码/测试来源哈希已登记核验。前端全局类型检查仍仅有既有 `docx-ruler.test.tsx:25` 的 `extendedIndents` 错误，见 `/tmp/xlsx-pivot-source-fields-frontend-tsc.log`。
- 实际构建 `--source-field-guard` 验收通过：`/tmp/xlsx-pivot-source-fields-built-final/summary.json`，`ok=true`、`sourceFieldGuard=true`、`saveCount=1`、`errors=[]`，144 项运行资源身份与构建一致。覆盖普通表复用旧名后编辑/撤销、字段输入/粘贴/交换/清空拒绝、范围收缩拒绝及草稿保留、上一条改名撤销/重做、新增未缓存列撤销/重做、刷新、草稿恢复、保存下载与重开。重新粘贴恢复另外由真实 Univer 定向测试验证，未声称浏览器覆盖该特殊入口。
- 独立文件证据 `/tmp/xlsx-pivot-source-fields-built-final/independent-source-fields.json` 确认主表及透视来源为 `CurrentSales`、范围 `A1:B5`、字段名 `Category/Amount`、汇总 180；普通 `Other` 表仍为 `E1:F3`，新增列撤销完成，`styles.xml` 和普通表定义字节不变。已查看拒绝对话框及重开来源截图；HTTP 身份/修订登记为本地夹具，字段自动迁移和桌面 Excel 实测继续保留为未完成。

## 自有动态透视来源字段更名继续实施

- 在原列数及物理位置不变、完整自有状态、无原生切片器/时间线的范围内开放字段更名。保存端先核对全部关联缓存、透视所有者及工作簿登记，再在同一 ZIP overlay 内迁移标准缓存名称/公式和私有字段/公式；公式复用已有 AST 同时更名，支持交换、连续更名及同批表名更名。原始附加元数据保留，缓存记录及输出不因更名重算，分组、标签筛选和报告筛选索引保持原归属。
- 前端按文件来源预检能力，只放行已核对的来源；连续草稿更名仍检查计算字段名称冲突。缺少完整状态、缓存归属不一致、无所有者、控件或列结构未刷新时拒绝自动迁移，删除及移动已缓存列继续受保护。
- 保存测试覆盖更名、交换、连续更名、引号和 `&`、计算公式、分组/筛选保留、未知元数据、同批表名修改及不支持状态拒绝。只读评审发现属性空格/单引号兼容和第二条关系遗漏共享所有者问题；均补充先失败回归并修复，修复复核通过。标准缓存属性仅改真实 token，保留属性值内相似文本，完成后重新核对实际字段和公式。
- 本轮前端分组定向回归共 85 项（透视相关 47 项、表头/粘贴/范围入口 38 项），引擎 36 项通过；没有重复完整测试。日志 `/tmp/xlsx-owned-field-rename-frontend-final.log`、`/tmp/xlsx-owned-field-rename-fixtures-final.log`、`/tmp/xlsx-owned-field-rename-entry-tests.log`、`/tmp/xlsx-owned-field-rename-engine-tests.log`。新增共享所有者失败证据 `/tmp/xlsx-owned-field-rename-shared-red.log`。
- 引擎类型检查、Node 桥打包、Vite 构建、原预算契约通过；3 项本地引擎源码哈希已登记核验。当前全局前端检查未全绿：TypeScript 在另一路 `slides-parallel-edit.test.ts:71` 报 TS7053，见 `/tmp/xlsx-owned-field-rename-frontend-tsc.log`；体积预算为 Word 的 `lazy-docx-main` 250.1 KiB 超 250 KiB，见 `/tmp/xlsx-owned-field-rename-budget.log`。未改预算阈值或修复无关模块，XLSX 主 chunk 为 190.0 KiB。
- 实际构建 `--source-field-rename` 验证标准导入首次刷新后取得自有状态，再进行字段更名、连续更名、撤销/重做、增长/收缩刷新、草稿恢复、一次保存下载及重开。`/tmp/xlsx-owned-field-rename-built/summary.json`：`ok=true`、`sourceFieldRename=true`、`saveCount=1`、`resourceCount=144`、`errors=[]`，所有资源与实际构建身份一致。已查看更名及重开来源对话框截图。
- 独立 ZIP/openpyxl 证据 `/tmp/xlsx-owned-field-rename-built/independent-field-rename.json` 确认表定义、标准缓存和私有状态均为 `Category/Revenue`，来源 `CurrentSales`、范围 `A1:B5`、汇总 180，旧输出尾部清空、手工草稿保留、样式字节不变。HTTP 身份和修订登记仍为本地夹具；无完整自有状态的导入自动迁移、原生控件字段迁移、删列/挪列协同迁移及桌面 Excel 实测继续待做。

## 自有原生控件来源字段协同更名继续实施

- 在既有固定列数和物理位置、更名前完整透视状态的边界内，放开通过全部保真校验的本系统原生切片器及多个时间线。标准透视缓存/公式/私有字段与控件 `sourceName`、请求字段一并迁移；未设置标题时默认标题与 fallback 随字段更新，显式标题、成员选择、日期区间、几何和关系保留。更名本身不重算输出及缓存记录，用户明确刷新后才更新结果。
- 含控件时，保存端从当前 ZIP overlay 获取完整字节快照，前端能力预检使用相同规划器；支持交换更名、同一表格编辑批次内连续更名，避免第二次编辑退回原始快照。时间线只放行关联 owner 确有已验证控件的精确已知缓存扩展。未知/损坏控件、额外关系所有者、不完整状态、增删或挪动已缓存列继续拒绝。
- 独占引用校验同时用于 identity 预检和实际迁移，复用已有命名空间关系解析器，覆盖非自闭合元素、单引号/属性空格、前缀、百分号编码目标及注释 decoy；无关外链不作为包内目标解码。真实保存回归先复现相关漏检、误拦截和外链 URIError，修复后通过；只读评审及问题修复复核完成。
- 前端分组定向回归按文件去重合计 84 项，引擎 48 项通过；主体日志 `/tmp/xlsx-control-field-rename-frontend-final.log`、控件/保存补充 `/tmp/xlsx-control-field-rename-targeted.log`、最终 10 项新回归 `/tmp/xlsx-control-field-rename-fixtures-final.log`、同批 overlay 专项 `/tmp/xlsx-control-field-rename-overlay-final.log`，引擎见 `/tmp/xlsx-control-field-rename-engine-tests.log` 和 `/tmp/xlsx-control-field-rename-guard-engine.log`。未重复应用完整测试。
- 引擎类型检查、Node 桥打包、最终 Vite、原体积预算和预算契约通过，未调整阈值；3 项引擎源码哈希登记核验。本次全局前端 tsc 未通过，无关 `pdf-form-canvas.test.ts:34` 的 `sourceSha256` 重复属性报 TS2783，见 `/tmp/xlsx-control-field-rename-frontend-tsc.log`；没有改动该模块。
- 复用已有三控件文件的 `--field-rename-only` 实际构建验收通过：`/tmp/xlsx-controls-field-rename-built-final/receipt.json`：`ok=true`、`saveCount=1`、`resourceCount=145`、`errors=[]`。覆盖真实字段输入、连续更名、撤销/重做、无关草稿、草稿恢复、刷新、一次保存、下载及重开。首轮下载失败定位为 Chromium download 导航绕过路由 mock 导致 Vite 404，下载夹具改为真实 HTTP 响应后定向复验通过；没有修改应用保存/签发代码。
- 独立 ZIP/openpyxl 验收 `/tmp/xlsx-controls-field-rename-built-final/independent-field-controls.json` 确认命名来源 `Sales`、表定义/标准缓存/私有状态字段均为 `OrderDate/Area/Revenue/Qty/ShippedDate`；三个控件字段分别为 `Area/OrderDate/ShippedDate`，显式标题、锚点尺寸、成员选择及两条 `2026-01-01` 至 `2026-01-31` 区间保留，6 个类型化日期保留，金额/数量汇总为 10/1。下载与保存 SHA256 相同；绘图、关系、缓存记录、样式等 15 个无关部件字节不变，无关草稿保留。已查看更名及重开截图。
- HTTP 身份和修订登记仍为本地夹具；未知/导入控件自动迁移、不完整导入状态、删列/挪列协同迁移及桌面 Excel 实测继续待做。openpyxl 只用于读取值和结构，未用它另存原生控件文件或替代桌面 Excel 兼容实测。

## PR 隔离分支验证（2026-11-11）

从 `origin/code` 的 `9f2c4944` 提取 XLSX 变更及其未合入的工作簿基础依赖；保留基线 Word/PDF/Slides 宿主、引擎及业务代码。共享 API 仅补读取上下文类型，前端依赖仅增加运行时 XML 解析器，Vite 仅引入工作簿分包规则；中文字体及授权随依赖一并保留。

- 前端透视/保护/允许编辑区域定向 130 项通过；首次缺导入夹具和表头测试同步断言共 3 项失败，补齐夹具并等待既有异步依赖预检后，仅复验对应 2 文件 20 项通过。
- 引擎透视/保护定向 108 项通过；首次 26 项因隔离分支未配置 Python 环境失败，配置项目现有环境后仅复验对应 4 文件 42 项通过。没有重复完整测试。
- 前端 `tsc --noEmit`、引擎 `typecheck`、Node 桥打包、Vite 构建及预算契约通过。前端全局类型检查的历史工作区错误没有带入隔离分支。
- 原体积预算仍失败：工作簿引擎 409.7 KiB 超 396 KiB，图标包 274.2 KiB 超 274 KiB。没有提高预算阈值，PR 以 Draft 提交，待预算收敛后再转为可合并状态。
- 引擎补丁登记和条件格式本地登记更新为隔离分支实际文件 SHA256。浏览器及独立文件证据沿用上述开发阶段记录，本次没有重跑桌面 Excel，也不将其声明为已验证。
