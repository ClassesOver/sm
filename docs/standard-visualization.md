# 标准可视化

## OS报告缺口标准化（2026-10-28）

新增参数覆盖本报告此前需要改绑、裁月、拆图或替代图形的情况：

- `standardLabelField`：明确标签列，多文本辅助列不会被误判成长表分类。
- `standardView`：`group`按`labelField`对`valueFields`求和，复用冻结事实的`additive_group_totals`；只汇总绑定行，拒绝缺失/非有限数和百分比求和。`pivot`用`seriesField`及显式`seriesValues`将一个度量透视成多个系列；重复或缺失单元不合并、不填零。
- `standardDerivations`：新列名`name`与`numerator/denominator`声明同单位`ratio_percent`或`difference`；`mom_percent`指定`numerator/labelField`，验证连续ISO月份后计算环比。衍生列不得覆盖原字段，首月和非正基数保留缺失。不会为原未登记比例猜单位。
- `standardPresentation.order={mode:"max_abs",fields:[...],descending:true}`：按多列最大绝对值排序，支持正负变化额；要求度量单位/比例尺度一致。
- `standardSources[].labelMode="month"`显式将ISO日/月标签规范为年月，`excludedLabels`明确排除合计，`standardLabels`选择共同窗口；重复月份、缺月和未使用绑定来源仍拒绝。
- `standardAxes.allowNulls=true`允许折线/普通柱图保留缺失空位和说明；不会补零，不应用于堆叠。`leftDisplayUnit/rightDisplayUnit`分别使用登记换算，不能提交自由倍率。
- `standardStyle.series[].geometry="bar"|"line"`组合共享轴柱线图；`label`仅替换图例显示名称，冻结系列身份和数值审计不变。
- 横向柱图配合`standardAxes={mode:"panels",panelLimit:10,panelDescending:true}`，一张图各指标独立排序TopN，逐柱颜色仍绑定冻结标签；标注预算按实际可见行计数。可见峰谷标注以该面板实际展示范围为准。

所有派生视图登记转换参数和`bound_input_rows_only`范围，运行前仍核验每份原始输入SHA256；保留原数据，不覆盖原文件。模型指令与结构化schema同步开放这些参数，标准路线继续保留Coding修复及独立视觉检查。

可复现回放：

```bash
PYTHONPATH=. python scripts/replay_os_standard_visualization.py REPORT.tar.xz OUTPUT
```

回放校验原包59项登记资源的size/SHA256、21份图表输入；缺失单位仅由对应登记事实重新物化，逐项确认columns/rows不变。16张图全部在原来源绑定上生成一张标准图，通过独立数值/颜色、可见文本边界及类别标签碰撞检查：包括11类×两期间透视、原3来源月度对齐、12个月缺失值双轴、项目明细分组和汇总比率、同图双面板独立Top10，以及同轴柱线组合。不再用裁月、改绑、拆图或替代图形计作覆盖。保留原图/标准图对照PDF、逐图PNG、参数、独立预期与审计。回放失败返回非零状态。

原有222场景重新执行后仍全部符合各自预期：146成图、71预检回退、2身份拒绝、2布局修复、1schema拒绝。新增22项转换/复杂图契约测试，包括换业务标签、乱序数据及1e-12至1e20量级，累计本轮268项相关测试通过；5模块mypy、Ruff及diff检查通过。以上是离线人工选参回放，不代表线上模型自动命中或独立视觉验收通过，也不承诺任意新数据自动可用。

## 扩大覆盖至222场景（2026-10-28）

回放CLI增加 `--suite basic|extended|all`（默认basic）。extended在独立的 `scripts/standard_visualization_stress_cases.py` 中声明100个新场景及预期：2/3/8来源各自随机打乱后按原标签对齐；缺标签、重复、空元数据、布尔数值、未使用来源、重复系列名、期间/百分比尺度不一致；主/次来源执行前被改动；百分比小数与百分数、元/万元/亿元换算、复合单位不能错误降维；闰日/跨年/重复月份/非法日期/Unicode非逐字一致标签；2/4系列×双轴/分面/对数/局部放大×正数/零/负数/混合单位；排序后的逐柱颜色、执行率、冻结摘要；长表缺口；布局/图例组合；20/30/60个平坦值标注及标注超预算、过小画布。

审计不再只检查图片存在：扩展场景提供独立预期数组，读取真实Matplotlib系列/柱高逐值比较，并验证配置颜色与实际绘制文字。另用故意错误的数值、颜色及摘要三个负控制，确认审计确实报错。回退、身份拒绝、schema拒绝和布局修复各有独立预期；出现不符时CLI返回非零状态。

本轮修复两项：manual布局外置图例可能超出固定画布，现由模板测量图例边界并要求修复；isPercent误传0/1或字符串时不能当成另一种百分比尺度，选定系列、多来源和辅助/摘要均检查元数据类型。保留旧记录未登记单位的兼容行为，不凭图名猜单位。

修复后原有122场景再次执行，新增100场景全部符合预期。合计222场景：146个成图并通过几何检查（扩展成图另核对声明的数值/颜色/摘要），71个预检回退，2个执行阶段拦截输入身份变化，2个布局要求修复，1个schema拒绝。图表9个基线仍全部成图。合计457项相关作图、投影、工作流及扩展契约测试通过，mypy、Ruff、diff检查通过。结果仍是离线模板/输入契约验证，未运行生产模型重新规划和Coding修复的线上闭环，不等同于完整业务语义或独立视觉验收。

## 换数据完整回放（2026-10-28）

新增 `scripts/replay_standard_visualization_variants.py BASELINE OUTPUT`，从已保存参数和重新物化的输入载入全部9张报告图。每张覆盖原值、极小金额、极大金额、全零、负金额、悬殊量级、倒置行序、缺失单位和字段改名；另补1/12/60/61标签、六种图形、双轴/分面/对数/局部放大、空值/NaN/Inf/重复标签/溢出/损坏结构、长表8×60容量等边界。

共122个场景：84个真实生成PNG并通过可见文字越界、分类标签碰撞及小数误显示为零的几何检查；38个在标准预检要求Coding回退。原报告9个基线均重新生成。合成变更数据不是新增业务事实；检查不等同于独立视觉审查、业务语义验收或新数据经过模型重新规划的线上端到端运行。38个回退只验证标准路线退出，未调用模型验证Coding一定修复成功。

本轮修复极小非零值在默认精度下变成0.00的问题：主标注、参考线、辅助字段和摘要统一按需要显示科学计数；极大数同样采用紧凑科学计数。堆叠合计预检捕获浮点溢出，损坏的JSON/表格结构不会在标准预检抛出而绕过Coding。`standardCanvas.maxCategoryTicks` 默认18（范围4—60），纵向图横轴过密时仅稀疏显示标签，所有数据点保留；类别文字仍重叠或标注超出固定画布时返回可修复错误，不提交不合格图。

换数据的边界：字段名称或期间改变应重新绑定和规划；单位须从对应已核验事实继承；双轴分别检查单位和尺度；对数必须严格正数；分组柱/堆叠不填补缺失单元；负堆叠、零分母、重复标签及超出60标签/8系列/480行的视图走Coding或由计划改用其他视图。不能承诺任意数据与任意旧参数组合自动合格。预检、原始文件SHA256与独立视觉审查/Coding回退共同约束实际交付。

回放目录保留每个场景的输入、参数、执行脚本、PNG和几何审计，汇总为variants.json、README和可筛选的index.html；异常或几何问题使CLI以非零状态退出，明确要求处理，不将文件存在视为验收通过。

本轮347项定向回归验证通过，含三组固定随机种子下陌生字段/业务标签的折线、横向柱与堆叠合计逐值核对，以及1e-14至1e16量级、非法JSON、损坏元数据和密集标签场景。相关4模块mypy、Ruff与diff检查通过。

## 报告主题与真实报告缺口补齐（2026-10-28）

标准图默认使用 `standardStyle.theme=report` 与 `palette=report`：深色标题、柔和蓝/橙/绿系列色、淡网格、细边框、白边数据点和无箭头数值标注。`classic` 可保留传统文字样式，其他Matplotlib调色板仍可选。`barGroupWidth` 控制柱组宽度（0.3—0.9，默认0.64），模型可显式调颜色、密度、线条和画布。

逐系列颜色按完整冻结名称绑定，支持含 `（非病区）`、` · ` 的业务名称；不会再用字符串切割猜测系列。`standardStyle.points` 按 `{series,label,color,markerSize}` 指定单柱/单点颜色，排序后仍绑定原标签。预算/实际单行对比可分别为蓝/橙；`standardAnnotations` 支持 `color`、`highlight`、`position`、`caption`，可做峰值绿、谷值红、指定参考线配色。峰谷/重点已有专用标注时，values不再重复输出同一点。

`standardPresentation` 标准化副标题、来源脚注、月份标签、排序、辅助标注与摘要徽章。标题/副标题/脚注会按画布宽度换行，tight和constrained布局为文本保留空间。参考线说明沿参考线定位到图边，避免覆盖柱体。

```json
{
  "standardPresentation": {
    "subtitle":"2025年1—9月累计｜单位：亿元、%",
    "sourceNote":"数据来源：收入预算执行汇总。",
    "order":{"mode":"value","field":"完成率(%)","limit":10,"excludeMissing":true},
    "labelFormats":[
      {"field":"预算合计","caption":"预算","displayUnit":"亿元"},
      {"field":"实际合计","caption":"实际","displayUnit":"亿元"}
    ]
  },
  "standardStyle": {
    "theme":"report","palette":"report","annotationLeader":false,
    "series":[{"series":"完成率(%)","color":"#4d9a69"}]
  }
}
```

order支持source/reverse/label/value/explicit；数值排序必须指定现有列，`excludeMissing` 仅显式排除排序字段为null的行，其他非有限值拒绝，不填零。`limit` 是明确的视图子集，不改变原文件；计划与图注仍应说明子集范围。`labelMode=month` 仅用于同一年、每月唯一的ISO期间；跨年或重复月份拒绝。`standardAxes.zeroBaseline` 显式保留线性轴零基线，对数轴不接受。

`labelFormats` 最多3项，可指定已有字段、简称、显示单位、精度、正号及限定系列。也可指定同单位冻结 `numerator/denominator`，由服务端计算百分比；分母必须大于0，缺失单位、混合单位、零分母均回退，不接受模型提供比例数值。`summaries` 最多4项，复用字段/显示格式并增加 `label` 唯一行选择和 `color`，在图头显示预算差额、完成率等徽章。单行转置图的摘要读取转置前冻结行；辅助预算/实际金额能独立换算亿元，不再沿用百分比轴单位。

单位缺口在数据投影层修复：`metrics[n].periodValues.value` 只继承该已核验指标自身的unit/isPercent，不从标题、字段名、邻近指标或模型推断。历史chart-input本身不修改；离线对比工具保留原字节，并从同包已登记size/SHA256的对应事实重新物化新输入，逐项断言columns/rows不变，记录新增元数据来源。

复现入口：`PYTHONPATH=. python scripts/replay_standard_visualization_comparison.py ARCHIVE OUTPUT [PREVIOUS_COMPARISON_FOLDER]`。生成9页原图/新版对照PDF、逐图PNG、概览、参数、执行脚本与replay.json；传入上一版目录时另生成优化前后PDF/PNG。该工具针对上传的revision-2报告选择参数，未保存原始计划，因此是人工选参离线回放，不能当作线上命中率。修复后的元数据投影下9/9实际生成PNG；旧输入原样仍有2张因缺少单位拒绝。已有独立视觉审查和Coding回退保持不变，尚未部署。

## 标准画布参数

所有标准图统一使用ChartDraft.standardCanvas，配置随计划保存并写入执行脚本，最终由既有脚本身份回执绑定；不另造未验证的画布验收回执。示例：

```json
{"sizeMode":"fixed","width":12,"height":7,"dpi":150,"layout":"tight","crop":"canvas","padding":0.25,"labelWrap":14,"tickFontSize":9,"legendPosition":"auto"}
```

- sizeMode：auto根据标签/分面数扩展画布；fixed严格采用width/height（英寸）。默认auto、12×7、150DPI。
- layout：tight、constrained、manual；manual使用left/right/bottom/top归一化留白，默认0.12/0.94/0.16/0.90。
- crop：canvas保留完整画布（默认）；tight显式紧裁切，导出像素不保证等于width×DPI。padding控制tight裁切导出留白（英寸）。
- labelWrap：6—40字符，默认14；tickFontSize：8—16点，默认9；legendPosition：auto/inside/outside。
- 尺寸范围4—20×3—24英寸，DPI72—240；声明尺寸及自动扩展后的画布均限制2400万像素。自动扩展超预算会转Coding，不静默降低DPI。

279项作图/投影/工作流回归通过；单轴、双轴、分面固定8×5英寸100DPI实际PNG均为800×500像素，手动留白和字号有断言。mypy、Ruff通过，尚未部署。

## 视觉质量修复闭环

标准路线失败后优先将原始visual_repair_diagnostic传入Coding回退；没有视觉诊断时使用现有受限执行故障摘要，保留脚本路径、错误和可用stderr。修复不重新进入相同标准模板，沿用原工作流的生成/修复次数限制和独立视觉审查，不因图表不合格阻止已有PDF/Word链接签发。

标准模板根据标签数调整画布；长标签按14字符换行，图例超过3项时外置，输出保留紧边界和留白。标注在绘制后使用Matplotlib真实文字包围盒检测重叠，每个标注最多移动16次；无法解除时产生standard_chart_layout_unresolved错误并转Coding，不删除标注或静默接受。该检测只覆盖标注文字间重叠，不等价于完整视觉验收，箭头、图例、标题和密集刻度仍需独立看图复核。

本轮60项作图测试、297项投影/工作流/发布非阻断回归通过；已断言文字包围盒不重叠、换行不改变数值、审查意见保留。mypy、Ruff和diff检查通过，尚未部署或运行新的生产模型验收。

## 独立总额、单行总览与窗口补齐

多来源standardSources可用categoryField/categoryValue显式选择长表内的一个分类，再按唯一冻结标签对齐。stacked-total可指定standardTotalField，独立总额逐标签与其余分项求和核验（相对1e-12、绝对1e-9容差），不闭合时回退；总额只画折线，不重复计入堆叠。图例明确区分独立冻结总额与服务端求和。

summary-bars/单行指标对比图支持从一行冻结表中用standardValueFields明确选择至少两个相同元数据的数值列，按列名转为类别显示；例如预算与实际两柱，不把差额默认加入比较。standardLabels显式选择冻结标签窗口，全部标签必须存在且唯一，按原输入顺序显示，不从标题推断或补齐缺失月份。

同一用户产物包新一轮离线候选回放覆盖7/9图，新增单行预算/实际总览；多来源旧输入缺单位时仍拒绝，不伪造元数据。回放不是原始在线路线命中率。59项作图测试通过，包含独立总额不重复堆叠、对账失败回退、单行指标和窗口实际数值验证。

## 多来源、组合图与联合标注增强

`standardSources` 显式选择本图各chart-input的sourceIndex、labelField、valueField和唯一seriesName。所有来源均须被选择，分别校验SHA256；标签集合完全一致、各来源无重复标签、数值有限且单位元数据明确时，按第一来源行序对齐。不同顺序允许，缺少标签或缺少单位拒绝；脚本运行再次核验每个原文件。当前不从旧产物缺失的单位元数据反推授权，因此不能宣称历史门诊双来源图已自动完整命中。

`visualForm=stacked-total`（或堆叠柱合计折线图）输出非负分项堆叠及服务端逐点求和折线，图例明确标识求和；它不冒充独立总额来源，尚不能完整复现原报告的“分项＋独立总额”双来源图。

`standardLabelFields` 最多3个同表辅助数值列，附加到values/point/peak/trough标注，例如金额柱旁显示占比；各字段需有冻结单位和有限值，按同一行/分类唯一定位，不改变坐标轴。高级轴与辅助列联合标注暂不组合。`standardDisplayUnit` 可显式选择单轴显示单位，换算倍率来自服务端单位表，拒绝金额转人次等不兼容转换。

本轮56项作图测试及211项投影/工作流回归通过；多来源重排、次来源篡改拒绝、求和曲线、联合百分比标签、元转亿元都有数值断言。用户报告院区成本图已以冻结输入实际重画联合标注PNG；未重新统计整报告覆盖率，未部署。

章节作图在授权 chart-input 物化后优先预检标准静态模板；整组均支持才进入标准路径，任一图不支持则整组走原 Coding 路线。失败日志为 `report_standard_visualization_fallback`，成功日志为 `report_standard_visualization_completed`。

支持 visualForm 为 line/折线图/多系列折线图、bar/柱状图/分组柱状图、barh/横向条形图、stacked-bar/堆叠柱状图、stacked-area/堆叠面积图。每图绑定一个已校验来源，最多60个标签、8个系列、480行。

输入支持 period 或 label 标签列加一个或多个数值列，以及 period×分类×value 长表。宽表多系列要求各列显式登记相同单位和比例尺度；趋势和堆叠图还要求列期间元数据一致。分组对比允许本期/基期分别保留各列冻结期间。长表重复期间/分类组合拒绝；缺少组合仅折线允许并展示断点，其余图不填零。堆叠图拒绝负值。非有限值、混合单位、复杂双轴、多来源拼接及其他数据形状继续走 Coding。benchmark 路径保持原配置。

模板读入时再次核验 chart-input SHA256，沿用原始行序和数值，不聚合、不裁剪、不填零。仅输出 Matplotlib PNG/JPEG。模板执行复用 ReportingCodeModeToolkit 的写入、执行、独立视觉审查、提交与当前回执重验；看图仍可能调用视觉模型，不能宣称零模型或线上提速已验证。

显示层从冻结 columnMeta 读取坐标单位；unit=% 且 isPercent=false 时将小数按百分数显示。最新增强的作图、投影与工作流242项回归通过，实际断点及百分比柱高有数值断言。新增复杂模板真实执行覆盖宽表/长表的五类图形。

## 冻结产物覆盖回放

## 结构化复杂标注

## 双轴与量级悬殊

`standardAxes` 显式声明轴策略：`{"mode":"dual","rightFields":["完成率"]}` 将选定系列绑定右轴，其他系列绑定左轴；每侧单位和比例尺度须一致且明确，两侧各自显示单位和图例轴归属。柱图双轴使用左柱右线，折线双轴使用双折线。标注与参考线跟随系列所属轴，百分比按冻结尺度显示。

`{"scale":"log"}` 只接纳全部严格正数的折线，坐标注明对数刻度；零值和负值不平移、不截断，回退Coding。`{"mode":"panels"}` 将系列放在共享横轴的独立纵轴分面，保留各自单位。`{"mode":"zoom","zoomStart":"2025-01","zoomEnd":"2025-03"}` 在完整主图上增加明确标识的局部放大，范围只能逐字绑定冻结标签。缩放由选择区间真实数值决定，不接受模型提供纵轴上下限。

高级轴当前限单来源宽表折线或柱状图，长表、多来源和堆叠双轴继续回退。1与1e12的量级差异、双轴百分比数据及参考线归属已有数值断言，53项作图和211项投影/工作流回归通过。尚未部署。

## 结构化复杂标注契约

ChartDraft.standardAnnotations 最多10条，支持 values（系列数值）、peak/trough（全部并列峰谷）、point（重点点位）、reference（以指定冻结点值画参考线）和 range（两个冻结标签之间的背景高亮）。series 必须引用已选择数值列或长表分类，label/endLabel 必须逐字引用冻结标签；不接受模型提供value或任意数字文案。无法绑定、区间倒序、缺失点位或总标注预算超过60时回退Coding。趋势断点不会被标成零。

例如 `{"kind":"peak","series":"actual"}`、`{"kind":"reference","series":"actual","label":"2025-01"}`、`{"kind":"range","label":"2025-01","endLabel":"2025-03"}`。标注数字由冻结值按同一百分数显示尺度生成；参考线是“指定点值参考”，不声称目标值或业务阈值。堆叠标注坐标使用累计高度，文案保留系列自身数值。仍经现有独立视觉审查；不保证密集标签完全无重叠，超过预算或视觉验收失败转Coding。

本轮43项作图及标注测试、211项投影/工作流测试通过；五类图形实际生成包含峰谷、重点、参考线、区间的PNG并校验标注坐标与文案。mypy、Ruff通过。

## 冻结产物覆盖回放结果

2026-10-28 使用用户上传 revision-2 产物包的9张图、11份chart-input离线回放。图表身份按trace-index登记的size/SHA256核验，不修改原始文件。新增唯一文本标签识别及 `standardValueFields` 显式数值列选择；选择必须是绑定表内现有数值列，未选择时仍核验全部数值列，不静默丢弃混合单位辅助列。

同一输入、相同回放候选枚举下，优化前1/9图可覆盖，优化后6/9可覆盖；命中候选均实际生成PNG。剩余两张为多来源绑定、一张为无标签单行预算总览。该包未保存原可视化计划，因此这是离线模板候选覆盖率，不能当作原始在线路由命中率、整体报告数值正确率或模型性能结论。245项作图/投影/工作流回归通过。

可复现入口：`PYTHONPATH=. python scripts/replay_standard_visualization.py ARCHIVE --output OUTPUT`。Python 3.14以下读取zstd ZIP需要zstandard。报告保存在OUTPUT/replay.json，包含逐图覆盖、明确列选择、输入摘要与实际PNG路径；不向线上发送请求。

PR146 审查定向回归168项通过；标准出图及工作流218项通过，另补5项执行门禁测试；发布非阻断契约86项通过。实际模板执行验证三种PNG输出及输入篡改拒绝。三个运行时模块mypy、Ruff和diff检查通过。尚未进行生产模型端到端报告验收。
# 模型可组合的标准表现参数

`ChartDraft.standardStyle` 已加入模型输出 schema，并在可视化规划指令中要求根据阅读目标主动调参。参数可与 `standardCanvas`、`standardAxes`、多来源和冻结标注组合；不更改输入字节、数据数值、单位或期间。

```json
{
  "standardCanvas": {"sizeMode":"fixed","width":12,"height":7,"dpi":150,"legendPosition":"outside"},
  "standardStyle": {
    "palette":"Dark2","background":"#ffffff","grid":"y","gridAlpha":0.2,
    "titleFontSize":16,"axisFontSize":11,"labelRotation":0,
    "legendColumns":2,"legendFontSize":10,"legendLocation":"upper left",
    "decimals":1,"annotationFontSize":10,"annotationOffsetX":8,"annotationOffsetY":16,
    "valueMargin":0.15,
    "series":[{"series":"actual","color":"#0072b2","lineStyle":"--","lineWidth":3,"marker":"s","markerSize":6,"alpha":0.9,"hatch":"//"}]
  },
  "standardAxes":{"mode":"zoom","zoomStart":"2025-01","zoomEnd":"2025-03","zoomBounds":[0.08,0.5,0.4,0.35]}
}
```

示例中的系列名、期间必须替换为真实绑定列及冻结标签。`series` 最多8项且名称唯一；未知系列回退Coding，避免模型以为样式已应用。颜色限六位HEX；线型、点型、纹理、调色板为枚举，数值参数有范围且不能为NaN/Inf。`zoomBounds` 是主图相对坐标 `[left,bottom,width,height]`，必须完整处于主图内。主图和局部图复用系列颜色/线型，双轴默认左右图例；外置图例由画布参数控制。柱纹理仅作用于柱、线型点型仅作用于线，精度仅控制标注文案。值轴留白不改变局部放大的冻结范围。

复杂需求通过组合参数表达，标准路线仍不覆盖任意图形。标注避让目前检查文字之间的碰撞，不能保证避开局部图、曲线或所有其他元素；模型可调整局部图位置、画布、标注偏移和密度，并继续经独立视觉检查。无法表达或视觉检查失败时沿用Coding修复。
