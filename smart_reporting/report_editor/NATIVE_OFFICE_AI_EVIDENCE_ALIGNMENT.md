# Office AI 证据与执行对齐增量

日期：2026-11-11。基线：`code@4cfaac23`（PR #217）；GenOffice 固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次关闭三个已复现缺口，完整四格式目标仍开放，不给完成百分比。

## 原始依据与实现

- XLSX：源 `apps/sheets/src/renderer/ai/tools.ts` 的单元格 DSL。实际合成 XLSX 经 `WorkbookAIToolkit.propose_operations` → `patch_office` 复现：`set_cell/set_formula/clear_cell` 在选区模式报 selection mismatch，整簿模式报 operations invalid。翻译器原来返回 `arguments.edits`，后续统一包装再加一层 `arguments`；现统一返回平铺参数，仅在候选 schema 边界包装一次。修复前新增六项全部失败，修复后全部通过。
- Word：源 `apps/docs/src/renderer/ai/tools.ts` 的 `read_comments` 读取线程上下文。本地原来只冻结根正文；现沿可信 `commentThreads` 的原始 comment id/parentId 收集授权根的回复，保留来源顺序、正文、作者、日期和状态，进入原有完整分页读取约束。其他根不进入快照，回复身份不获得写权限，未知/循环父关系或不可读正文拒绝生成不完整线程快照。沿用已有 comments hash 与来源文件身份拒绝过期候选。
- PPTX：源 `apps/slides/src/renderer/ai/slides-skill.ts` 的对象 dump 保留对象类型和几何。本地纯阅读曾仅收集非空 text，使无文字图表没有证据；现加入 tableCells、图表缓存、类型及几何。新增桥接只读 `chartReadData` 投影直接来自既有解析模型，包含缓存类别、系列和值，以及存在时的散点 x 值、气泡尺寸、组合系列类型。标准导入图表即使 `chartEditSafe=false` 仍可读取，写权限判定保持原有规则。缓存来源、可能过期、null 缺失值和未读取备注/图片视觉均明确进入模型指令或用户边界说明。

## 可独立复核的验证

| 范围 | 验证与结果 |
| --- | --- |
| XLSX DSL | `test_workbook_ai_tools.py`：22 passed。三种 DSL × 两种授权范围使用实际 Node 引擎预览，由 openpyxl 独立回读值/公式、未选内容和原件；原复杂筛选/表格预览与采纳测试通过。 |
| PPTX 读取 | `test_native_slides_read_ai.py`：16 passed。python-pptx 独立创建标准表格/图表并确认源值，真实桥接读取无 text 图表的 59/42；真实 Agno 使用 ScriptedModel，确认工具回执可见图表数据及服务端重建引用。涵盖冻结、连续分页、未授权内容、图片无证据、实际草稿、来源/effective SHA 和只读结果。 |
| 阅读任务宿主 | `test_native_office_read_tasks.py`：12 passed，含来源变化、取消、重排身份与范围隔离。此组与 PPTX 工具最初合跑27项通过；新增草稿图表专项后仅重跑受影响工具文件16项，不重复完整项目测试。 |
| 阅读 HTTP | `test_native_office_read_api.py`：6 passed。现有 grant/cookie/CSRF/Origin、SSE、取消及严格输入契约保持通过。 |
| Word 线程 | `test_native_word_review_ai.py`：19 项通过（完整执行18项通过，修正新增用例的fixture写入覆盖参数后，剩余服务用例单独通过）。真实 Agno ScriptedModel 回执含历史回复；真实 DOCX writer、独立 ZIP/lxml、NativeAIService 预览和显式采纳、线程/来源变化拒绝、无回复根兼容、跨线程隔离和分页均通过。 |

以上五个测试文件最终75项均通过（分批、未重复完整项目测试）。Slides `npm run bundle:bridges` 通过；目标 Python ruff 与 `git diff --check` 通过。未更改前端源码，未重复完整项目测试。合成文件与 ScriptedModel 验证不等同于真实 provider 或生产数据库浏览器端到端验收。

## 拉取源码后的本地构建事实

本地忽略目录保留了旧 `workbook_engine/dist/cli.mjs`，其中没有最新源码已有的 applySheetFilter/applyTableEdits；首次专项因此失败。核对源码协议后按 lockfile 安装依赖并重建 bundle，原测试通过，没有为旧产物改变正确的操作协议。Slides bundle 同样已按当前源码重建；Word 缺少 tsx 的依赖已按 lockfile 补齐。部署需从新源码构建引擎，不能复制工作区旧 dist。构建产物和 node_modules 不纳入本次提交。

## 整体目标仍有的缺口

1. 后续已接入 XLSX AI **已有图表格式编辑/删除**及冻结 chartPath 授权，45项专项、真实浏览器两次保存下载重开通过，见 [已有图表 AI 验收](NATIVE_XLSX_AI_EXISTING_CHART_ACCEPTANCE.md)。AI 新增图表/替换数据、真实 provider 的同名多图消歧仍缺；bar方向/零线/缺失分类后续已限定修复并通过像素验证，见 [画布增量](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md)，仍不等于完整显示保真。
2. Word 完整段落/制表位对话框、复杂多级列表、嵌套表结构与复杂修订仍未对齐，见 [当前缺口](NATIVE_WORD_XLSX_CURRENT_GAPS.md)。本次只补阅读线程，不开放嵌套回复写入。
3. 后续增量已补齐整稿演讲者备注阅读，当前对象选区不附带备注；图片视觉、解析器未返回的数据或外部数据源重算仍缺。复杂原生编辑仍按已有能力边界执行。
4. PDF 保留最新已交付能力；四旋转×两缩放的草稿/保存 AP 字体专项已限定通过（32标签独立文字栅格边界最大差1px），见 [AP字体补证](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md)；后续已补CropBox/UserUnit限定组件浏览器并修复草稿线宽比例；页边长标签、复杂表单及其他转换仍见 [剩余计划](NATIVE_PDF_REMAINING_PARALLEL_PLAN.md)。用户排除的 OCR 不加入范围。两个既有 PDF WIP stash 保持原样。
5. 真实 provider 与真实保存/下载已有分层证据，但生产数据库、浏览器真实 provider、显式采纳、新修订和下载的同一条链路仍未统一验收；本次不把 scripted 证据算作该项通过。

未合并、部署或开启功能开关，未改发布签发链。


## 后续优先其他能力（同一 PR）

[演讲者备注专项](NATIVE_PPTX_READ_NOTES_ACCEPTANCE.md) 已完成整稿备注阅读及清晰引用，并修复真实浏览器发现的助手侧栏字体覆盖造成文字不可见。对象选区不附带备注；生产构建真实HTTP/授权/Agno两格式浏览器链通过，18份实际JS与manifest身份匹配，原件/草稿不变，无写请求。

[PDF字体与四旋转组件补证](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md) 已补固定字体资产、显式回退和缩放字宽稳定性；8场景、32标签及字体失败回退通过。本次没有扩充证书、OCR或复杂表单范围。

最新依赖已按lockfile补齐；两个既有测试夹具类型问题已修且23项通过。完整tsc（Node heap 4GiB）、最终Vite50.16秒和全部JS预算通过。不会据此反推历史构建通过，仍不宣称生产数据库/真实provider整链验收。


2026-11-12 PDF续批：非零CropBox/UserUnit2与默认来源各8个组件浏览器场景通过，修复草稿线宽/箭头头部未包含UserUnit的实际bug；73项定向、完整npm build/tsc和JS预算通过。见 [AP一致性验收末节](NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md)。页边长标签仍可能裁切，后续已补普通与样式混合测量的页框溢出风险提示，见 [风险提示专项](NATIVE_PDF_MEASURE_CROP_REVIEW_ACCEPTANCE.md)；自动重新排版仍未实现。


2026-11-12 PDF页边提示续批：实际输出CropBox∩MediaBox的保守风险诊断、普通绘图保存回执保留、诊断异常不阻断真实预览保存下载均已限定验收。引擎20项、HTTP新3项与相关3项、既有发布合同79项、宿主UI12项通过；不会把风险提示算作消除实际裁切。详见专项记录。


同批补齐预览后仅裁切诊断失败的非阻断边界：新诊断不使同内容确认失效，原字节SHA/操作/来源绑定不变。普通绘图保存现保留完整回执。最新PR219合入后的Word/PPTX包预算已通过纯helper静态拆包恢复到232.97/237.11KiB，不提高250KiB上限；相关103项窄测、实际Chrome模块导入与全部预算合同通过，详见 [裁切风险提示与构建验收](NATIVE_PDF_MEASURE_CROP_REVIEW_ACCEPTANCE.md)。


2026-11-12 浏览器续批：测量标签页边风险已补真实UI标定/UndoRedo/预览告警/保存/下载/新修订重开闭环，独立pypdf/ReportLab回读与48份实际JS/CSS身份核验通过。原件不变、保存告警不阻断下载；真实路由与引擎、隔离内存修订仓储，不冒称生产DB。见 [页边风险提示浏览器补证](NATIVE_PDF_MEASURE_CROP_REVIEW_ACCEPTANCE.md)。


2026-11-12 测量物理单位续批：修复跨UserUnit页面共享标定时长度翻倍/减半的问题。按PDF.js实际来源页单位归一化到物理pt，保持原始坐标/既有标签/默认Unit1行为；固定GenOffice源同样使用raw hypot，因此为本地一致性适配。24项定向、完整类型/构建/预算、双向重标定及实际保存下载重开通过，见 [跨页标定验收](NATIVE_PDF_MEASURE_USERUNIT_ACCEPTANCE.md)。制图比例不同仍需用户重新标定，不自动推断图纸比例。

2026-11-12 XLSX续批：已有图表格式/删除进入 AI 明确授权和显式采纳闭环，补冻结目标身份及严格运行时格式参数校验。45项图表专项、34项既有XLSX AI、旧报告AI两项与宿主7项通过；完整tsc/Vite45.17s和预算通过。真实浏览器手工草稿、UndoRedo、放弃删除、修订4→5→6、下载/重开及169份实际JS/CSS身份已核，独立openpyxl/lxml确认另一同名图表字节不变；ScriptedModel/内存仓储不算真实provider/生产DB链。原有bar画布渲染缺口明确保留，详见专项记录。

2026-11-12 画布续批：上述bar方向缺口已补，并修复bar/column负值、虚构零条及缺失分类错位。10项新实际扩展测试全部先RED后GREEN，与相关测试合计17项；完整tsc/Vite49.08s、预算通过。真实截图独立像素恢复5/5/0色块及共同零线，169份资源SHA核验；相同新构建下AI两次保存下载重开再通过。标题/网格文字可见性和复杂图表样式仍开放，详见 [画布增量验收](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md)。

2026-11-12 文字补证：空白浏览器原生Canvas已复现系统/别名字体宽度0与无墨迹，明确字体正对照正常；定位环境强别名指向系统WOFF2的解析路径。显式进程Fontconfig恢复同一构建的标题/网格文字，新增预检拒绝坏环境及独立截图文字像素检查；真实保存4→5→6/下载/重开再通过，各169份实际资源与字体配置SHA已核。产品字体/渲染器未改，复杂字体及图表样式不冒称通过。见 [文字环境根因与预检](NATIVE_XLSX_CANVAS_FONT_ENVIRONMENT.md)。

2026-11-12 图例续批：bar/column常见四侧/none图例接通读取与画布，可信名称引用使用当前网格、显式RGB系列色与色块一致。读取11项、画布等28项、实际桥接AI45项通过；最终tsc/Vite45.56s及预算通过。最终构建的五种图例独立像素、原几何、AI保存下载重开三链通过，各169份资源核SHA；复杂索引例外不猜映射，非bar/column和完整轴/标签样式仍开放。见 [图例画布验收](NATIVE_XLSX_LEGEND_CANVAS_ACCEPTANCE.md)。

2026-11-12 轴标题续批：bar/column主标题与轴标题分离、实际axId/crossAx唯一配对、隐藏轴与同表标题引用、角色方向及top/right标题带已补。读取19项分批、画布/文字28项与创建切换7项、真实桥接AI45项通过；完整tsc/Vite49.76s及预算通过。四场景独立像素、图例回归、AI带轴标题保存下载重开三链通过，各169份实际资源核SHA。完整刻度/数值范围、次轴/组合及标签仍开放，见 [轴标题专项](NATIVE_XLSX_AXIS_TITLE_CANVAS_ACCEPTANCE.md)。

2026-11-12 数值范围续批：bar/column手动min/max、反向、零点夹取及越界裁剪接通，null恢复本地自动范围；对数/无效或不可信轴配对不伪绘。读取29项、前端51项分批及真实桥接AI45项通过，完整tsc/Vite45.95s与预算通过。六范围像素、轴标题回归、真实候选设置5..25/恢复自动/撤销/保存下载重开三链通过，各169份资源核SHA；漂亮刻度/完整自动策略、对数计算与数据标签仍缺。见 [数值范围专项](NATIVE_XLSX_VALUE_RANGE_CANVAS_ACCEPTANCE.md)。

2026-11-12 数值轴续批：在合并PR220/221后的code上，bar/column接通源5%自动留白、主刻度单位/数字格式、独立刻度带、top/right及隐藏/反向，刻度/零线/条形共用有限域。原源函数直接执行750组差分，748一致、2组明确修正全负上界；57项前端、34项读取分批通过，完整tsc/Vite46.29s与全部预算通过。六场景独立像素、原几何回归及AI手动→自动→撤销→保存下载重开通过，各169份实际资源SHA已核。类别刻度、完整轴属性、源链接格式继承、对数/次轴及复杂图表仍开放，见 [数值轴验收](NATIVE_XLSX_VALUE_AXIS_CANVAS_ACCEPTANCE.md)。

2026-11-12 类别轴续批：补齐bar/column单层名称，并按固定源修复bar默认bottom-up和双类型maxMin组内系列顺序；保留实时空标签与缺失数值槽，外表引用用原索引缓存。41项读取、75项前端分批通过；原排序表达式292位置完全一致，完整tsc/Vite44.88s与预算通过。分类六场景、原几何/手动域/数值刻度/标题/图例及AI保存重开七条浏览器链已核实际像素与169份资源SHA；旧失败裁剪区不被覆盖。多级/日期比例/完整换行旋转与数据标签等仍缺，见 [类别轴验收](NATIVE_XLSX_CATEGORY_AXIS_CANVAS_ACCEPTANCE.md)。

2026-11-12 数值标签续批：普通bar/column显式value标签接通plot/series/point设置、删除、三种位置和格式；负值/反向/裁剪保留原值，零不制造色条，空格式分段保持隐藏。另修真实A/B短分类被省略号误判而隐藏。50项读取、87项前端分批通过，最终tsc/Vite48.04s与预算通过；八场景独立文字/色块/位置/关闭墨迹及AI带标签保存下载重开已核，字体/像素验收失败现场保留。完整标签样式/偏移/内容家族等仍开放，见 [标签验收](NATIVE_XLSX_DATA_LABEL_CANVAS_ACCEPTANCE.md)。

2026-11-12 标签样式续批：普通数值标签的字号/RGB/加粗与逐属性继承接通，字体指标参与放置；修复全局标签编辑丢失原txPr/point，以及detail误改嵌套点格式。SAX保留原子节点字节。76项引擎、90项前端及新bundle下45项AI专项通过；完整tsc/Vite49.56s与预算通过。六字体场景实际Canvas字体、独立RGB混合像素、带原样式AI保存重开及八标签回归三链已核，均169资源SHA/字体预检/errors=[]。未解析主题和过大字体不算支持；其他样式/家族仍开放，见 [字体样式验收](NATIVE_XLSX_DATA_LABEL_STYLE_ACCEPTANCE.md)。

2026-11-12 标签主题色续批：普通数值标签接通实际主题关系与完整配色的无变换 schemeClr，保留原引用并跟随真实主题切换；47项定向、构建/预算、真实撤销重做与保存下载重开通过。169实际资源身份及独立下载XML/颜色混合像素已核；明暗透明度变换、字体族及复杂标签仍缺，见 [主题色验收](NATIVE_XLSX_DATA_LABEL_THEME_ACCEPTANCE.md)。

2026-11-12 标签亮度续批：普通数值标签的RGB/已解析主题色接通常见lumMod→lumOff亮度组合，保存保留原变换。66项定向、1120组固定源实际执行对比、真实主题切换/撤销重做/下载重开与独立颜色像素通过；Python另6组浮点舍入差异已公开。透明度、其它变换链及完整标签家族仍缺，见 [亮度验收](NATIVE_XLSX_DATA_LABEL_LUMINANCE_ACCEPTANCE.md)。
