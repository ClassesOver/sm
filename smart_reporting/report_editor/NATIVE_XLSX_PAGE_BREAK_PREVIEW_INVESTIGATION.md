# 下一项 XLSX 缺口：View 分页预览

2026-11-10 只读盘点。结论：**分页预览确实未交付**，不是旧 audit 没及时
更新的项目。选择此项作为下一项建议；本轮只增加此独立文档及 `/tmp` 探针，
未改生产/测试、未 build、未跑完整测试。

## 已排除的旧结论

没有按旧 audit View 行“其余 disabled”直接判定：当前高亮、goto滚动、
编辑栏、标题、RTL、缩放/选区缩放、冻结均有真实接线和后续验收记录。
也不把已有 File 打印或 Page Layout 手动分页符写回重复列成新功能。
本缺口仅是工作表网格内的分页边界/页码视图，与 File 打印文档不同。

## 固定来源的真实功能

来源仓库 `/home/junge/pros/genoffice-source-full` HEAD 已核对为
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 固定来源位置 | 真实语义 |
| --- | --- |
| `apps/sheets/src/renderer/ExcelShell.tsx:3278` | View 普通/分页预览两个互斥入口，active来自当前表pageBreakPreview；普通在已预览时发同一toggle关闭 |
| 同文件 `:1120` 附近 | 状态栏也有普通/分页预览视图切换 |
| `App.tsx:4722` | `toggle-page-break-preview` 显式路由到togglePageBreakPreview |
| `App.tsx:4424` | disposePageBreakLayers清理已有图层 |
| `App.tsx:4437` | installPageBreakLayers合成effectivePageBreaks、页面设置journal及实际表extent，再装浮层 |
| `App.tsx:4464` / `:4468` | refresh及按sheetId开关；仅会话集合，不写文件视图状态 |
| `App.tsx:2983,3221` | 与结构变化相关的重装路径；关闭文件`:4985`清图层 |
| `page-break-preview.tsx:42,56` | 纸型/方向/边距转可打印pt；累计实际px尺寸×0.75×scale计算边界 |
| 同文件 `:103` | effectivePageBreaks用会话替换集优先，否则来源分页符经结构操作映射；未知索引时返回null |
| 同文件 `:130` | installPageBreakPreview用官方registerComponent/addFloatDomToRange注册范围锚定图层 |
| 同文件 `:185` 后 | 外边框、自动虚线/手动实线、down-then-over页码水印；eventPassThrough=true |
| `styles.css:2888` / `:2952` | 蓝色边界样式及不接收指针事件的页码水印 |

固定 helper 整文件 SHA256：
`9f386d78691b4fda8b8b163d99273fc21095452f37a4432c937f638a31bf73f5`。
源有明确资源上限：extent最多20000行/2000列，各轴最多200条边界、最多60页
标签；不是百万行全量分页。源fit-to-page只用fitToWidth近似，不实现拖动分页线，
也没有由此写OOXML sheetView view=pageBreakPreview。不得扩称这些能力已在源实现。

## 当前宿主真实缺失点

`frontend/src/workbook-ribbon.ts:513` 声明“普通”“分页预览”，但`:576-577`
仍有明确disabledReasons：

- normal-view：`当前仅提供普通网格视图`
- toggle-page-break-preview：`尚无分页预览渲染和视图状态`

`workbook-ribbon.test.ts:645` 仍验证分页预览disabled及该原因。
`workbook-main.ts` 没有 `toggle-page-break-preview` / `normal-view` 路由、预览
controller或layer状态；当前`workbook-print.ts`没有网格范围浮层功能。
不是按钮已启用而audit陈旧，亦不是隐藏在别处的打印等价入口。

当前可复用的真实基础：

- File print在`workbook-main.ts:695`路由，生效setup在`:724`附近包含文件+
  pageSetupJournal，手动breaks在`:742-743`。这是隐藏iframe打印HTML，不是网格预览。
- `workbook-print.ts:279 bandIndices`与`:310 planSheetPrint`已提供真实打印
  分页计算：支持打印区域/重复标题/隐藏轴、边距、纸型、scale及fitToWidth/Height。
- `workbook-main.ts:604 mergedPageSetup`供Ribbon，但目前返回值不含scale、
  rowBreaks、colBreaks和实际自定义边距；不能原封拿它冒作完整preview setup。
- `workbook-main.ts:919`附近已有分页符插入/删除/重置，`:1847`附近已有
  rowBreaks/colBreaks差分，经applyPageSetups回写；无需为纯开关新造保存协议。
- engine `workbook-read.ts:380`只读手动`brk`（缺man视为true、man=0排除）；
  `page-setup.ts:335`已有对应writer。当前引擎不读写sheetView view模式。
- 安装包`@univerjs/sheets-drawing-ui/lib/types/facade/f-worksheet.d.ts:305`
  官方addFloatDomToRange已存在，真实运行栈已装drawing preset；无需引入自制
  canvas engine、Plotly或全局滚动DOM定位系统。

## 本轮可复现探针（已运行exit0）

`/tmp/xlsx-page-break-preview-inventory.mjs`读取当前Ribbon TypeScript AST，
确认action真实声明和精确disabled原因，断言main无该路由；同时从固定源
AST原样提取纯计算声明，经TypeScript转译执行，不手写替代算法。
结果 `/tmp/xlsx-page-break-preview-inventory.json` 和 `.log`：

- localCommandDeclared=true；localDisabledReason=`尚无分页预览渲染和视图状态`；
  mainRouteAbsent=true。
- source算例：8行，每行20px，可打印50pt，scale1，手动break4，所得边界
  是3自动、4手动、7自动。
- 默认A4常规边距的可打印大小约494.64×733.68pt；源SHA与上述一致。

此为静态接线+固定源纯计算探针，不冒计当前未实现功能的GUI通过。

## 最小完整实施建议

1. 迁入固定来源独立helper的边界/范围锚定浮层、source attribution及SHA。
   适配宿主实际类型和纸张/边距读取，复用官方registerComponent与
   addFloatDomToRange；范围浮层eventPassThrough，保持原文字/单元格交互。
   沿源保留边界/标签资源上限并明确反馈截断，避免把加载行数无限展开。
2. 每个宿主实例按真实Worksheet身份存会话预览状态，main显式接普通/预览
   两入口，Ribbon pressed互斥；只读受保护表允许阅读，loading/saving/dispose
   使用现有视图可用策略。普通/关闭/替换/删除页清浮层及component注册。
   切表、重排/新增同名表不串状态；不把开关写NativeDraft或OOXML。
3. 用当前文件模型+pageSetupJournal+真实live行列几何提供effective状态。
   页边距自定义、scale、fit及当前手动分页符须明确合成，不丢会话修改。
   更新页面设置、行高列宽、隐藏/显示、结构操作及UndoRedo后重算或重装。
   结构操作后manual break映射必须复用既有真实坐标/保存路径核对，不假定
   file索引仍等于screen索引。
4. 在固定source几何一致向量之外，优先对比现有planSheetPrint的页段，避免
   与实际打印分两套不同结果。源helper只近似fit宽且未处理全部printArea/
   title/custom-margin语义；若称“预览当前打印分页”，应复用现有打印planner
   产出的row/col页带，再绘来源样式。不能隐瞒源近似与宿主更完整planner
   的差异，也不要同时重写File打印。建议以现有planner为分页真值，来源
   helper提供范围浮层呈现；这是局部复用，不是新造分页轮子。

这里“完整”限定固定来源View预览及与宿主既有打印设置一致；不同时做打印
对话框、桌面多窗口、分页拖动编辑或sheetView模式持久化。若打印planner
遇到超预算/不支持设置，应保留正常网格并明确不能预览原因，不能假造页数。

## 必须的验收闭环

- RED→GREEN真实main/Ribbon：当前disabled原因移除前后实证；普通/预览
  active互斥，跨页每表状态，受保护/保存后阅读，失败保留普通网格且说明。
- 纯分页向量：自动/手动、方向纸型/自定义边距、scale/fit双轴、打印区域/
  重复标题、隐藏行列和自定义尺寸；与planSheetPrint同源页段一致，边界
  before-index语义不可偏一行。源资源cap透明；不拿纯算例替代实际布局。
- 真实built Chromium：蓝色实线/虚线位置与单元格像素相符、页码可读；
  冻结、150%/75%缩放、RTL、滚动/远处与快速切表；点击/编辑穿透不被遮挡。
  页面设置及结构变化/UndoRedo后位置实时正确，关闭无残影，不累积注册/DOM。
- 纯开关前后完整snapshot/样式/draft/history/保存态/revision及真实下载SHA
  不变；保存已有无关编辑时preview不新增操作。实际打印文档不带屏幕预览
  边界/水印，必要时独立打印检查，不能只看网格截图。
- 多实例同id不同Worksheet、来源替换、dispose及重复mount清理；JS200/SHA、
  无pageErrors、实际下载，source和本地SHA记录，最终统一build预算不抬高。

当前结论仅为下一项可实施的已确认缺口，未启动实现，未把本调查计为交付。


### 2026-11-10 主入口与 Ribbon 接线验证

- main 的页面设置日志采用 `createPageSetupJournal`，真实结构日志按发生顺序经 `shiftSpecOf` / `cellShiftSpec` 传入；字段 capture 不随回读破坏，Undo 能恢复坐标。
- 分页预览与 File Print 共用 `capturePrintInput`：`currentOperations()` → `applyWorkbookOperations(original, operations)` → `readModelWithStructureSource`，取保存顺序下最终页面设置；实时快照提供当前行高、列宽、隐藏轴和样式。epoch 与实际 worksheet 身份变化会拒绝过时捕获。未修改打印 exporter。
- controller 使用真实 Worksheet 身份维护会话模式，刷新/关闭/替换/销毁均释放浮层；同一微任务内的变更合并刷新。View 普通/分页预览互斥 pressed；只读、保存后和保护工作表可查看，不写文件视图配置、历史或草稿。
- 主入口窄测试覆盖只读切换零快照/撤销栈/草稿修改、普通视图释放、行插入及 Undo 后分页符重放、原缩放与打印区域保留、预览和 File Print 同输入。Ribbon 窄测试覆盖保护只读可用及互斥状态。
- 测试证据：`/tmp/page-break-main-red.log` 两项接线 RED；`/tmp/page-break-main-green2.log` Ribbon 43 项及主入口 1 项 GREEN；新增重放与打印一致性用例后 `/tmp/page-break-main-integration.log` 主入口 2 项 GREEN。最终类型与变更后窄验证结果见交接记录。

- 最终窄验证：`/tmp/page-break-main-final-tests.log` 14 GREEN（主入口2、planner/overlay9、controller3）；`/tmp/page-break-main-types-final.log` TypeScript exit0。root review 后追加显式快照 clone 与缺失 sheet/file 拒绝默认回退，`/tmp/page-break-main-review-green.log` 主入口2 GREEN；代码已 freeze，统一构建由 root 负责。
- 新真实产物 smoke：`frontend/smoke/workbook-page-break-preview-built-smoke.mjs`，Node 语法检查通过；覆盖4张受保护只读工作表（普通、冻结、150%缩放、RTL），实际水印几何/外框、关闭清理、按 Worksheet 身份恢复模式，草稿/历史/保存状态与源文件/下载 SHA 不变。此处仅记录准备状态，真实 built 执行结果须待统一构建后补录。


### 2026-11-10 新统一产物浏览器验收

- 当前统一 build（包含 doc_engine 迁移与分页预览独立 chunk）由 root 执行成功，预算及预算契约均通过，未提高上限；本 agent 未运行 build。
- 保护只读四表 smoke：`/tmp/page-break-built-readonly3.log` exit0，产物 `/tmp/page-break-preview-built-mttiys`。Plain/Frozen/Zoom150/RTL 实际浮层水印具有非零几何；普通视图清理、Worksheet 身份切换模式、草稿/历史/保存状态及源/下载 SHA 不变；118 个实际 built JS HTTP200 且与静态文件 SHA 相同，save0、pageErrors0。入口 `editingEnabled:false` 会关闭编辑器挂载，因此 smoke 使用 `editingEnabled:true` + 每表真实 sheetProtection 验证保护只读，不能将此证据称为全应用编辑能力关闭后的预览支持。
- 可编辑 smoke：`frontend/smoke/workbook-page-break-preview-editable-built-smoke.mjs`，`/tmp/page-break-built-editable-final.log` exit0，产物 `/tmp/page-break-editable-built-pox3x9`。覆盖打印区域/标题/手动分页符 → 行列插入 → 第二 epoch 新增分页符 → 行列删除 → Undo/Redo → 实时行高列宽和 outline 隐藏 → 真正 save/download ZIP。
- 7 阶段实际预览水印页数和 File Print iframe HTML 页数分别为 4/4/9/9/9/9/6，逐阶段一致；打印每页重复标题，42pt 行高按原90%缩放显示37.8pt，宽列影响打印几何，原隐藏列及新隐藏行列不出现在实际打印内容。
- 保存通过真实 Python `patch_office` 应用浏览器 operations，仅保存1次；HTTP下载 SHA 与保存产物相同。ZIP 经 openpyxl + XML 检查为 area `$A$1:$H$40`、titles `$1:$1`、rowBreaks `[10,14]`、colBreaks `[4,5]`、行高42、可见E列宽20、新隐藏行6/7与列F/G；118 built JS HTTP200/SHA，pageErrors0。打印 iframe 的测试注入限制为顶层窗口，避免对 about:blank 执行测试 history.replaceState。
- 已告知 root 的既存限制：源隐藏C在插列后为D，live preview/print 正确保持隐藏，但当前保存链额外输出 `applyColumnWidths(index3,widthChars13)`，ZIP D 隐藏标记丢失。此 smoke 仅证明新隐藏轴及可见尺寸闭环，不声称源隐藏列保存保持。失败/诊断证据 `/tmp/page-break-editable-built-AoAKGt/save-payload.json` 和 `zip-inspection.json`；本次未修改 geometryChanges 或打印 exporter。
