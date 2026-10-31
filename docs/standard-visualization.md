# 标准可视化能力契约

本文是标准可视化的**当前**能力、参数、限额与回退条件。各轮实现细节与验证数据见[验证记录](standard-visualization-history.md)；两者冲突时以本文和代码为准。

## 定位与原则

- 标准路线是确定性的 Matplotlib 静态模板（PNG/JPEG），用于把规划器声明的参数直接编译成作图脚本，减少自由 Coding。不新增 Plotly 或交互图能力。
- 只使用已授权、已物化的冻结 chart-input。编译与运行时都按登记的 SHA256 重新核验每份输入；不修改原文件、不补零、不聚合未声明的数据、不从标题或字段名猜单位与期间。
- 模型只能声明结构化参数（字段、标签、范围、样式等），不能提供数值、比例或任意文案；标注与摘要数字都由冻结值计算。
- 不支持的参数组合是**软失败**：该图携带结构化诊断转 Coding，其他图继续走标准路线；已生成的 PDF/Word 照常签发（见 `AGENTS.md` 非阻断契约）。
- 标准脚本与 Coding 脚本共用执行、看图、提交与当前回执门禁；布局自检不替代独立视觉审查。

## 路由与回退

1. 规划阶段：`standard_plan_diagnostics` 逐图预检，把机器契约问题反馈给规划器；显式 `standardForm=custom` 或输入不可用的图不触发重规划。
2. 执行阶段（`run_standard_chart_routes`）：整组都支持时执行一次标准脚本；混合计划或整组执行失败时逐图隔离，只把不支持或验收失败的图交给 Coding。组件脚本分别核验身份，最终组合脚本重新核验所有输入和组件 SHA256，在独立命名空间按项目主题执行，再走完整门禁。
3. 只有测量到 `standard_chart_layout_unresolved` 且 `sizeMode=auto` 时，最多扩大画布重试两次；不改固定画布、DPI 与像素预算，不吞掉身份或语义失败。
4. 标准渲染证明：只有最终图片与真实标准执行逐字节一致时才保留，用于追溯中的图表核验。核验时用**当前**模板按证明中的计划重新编译，并与归档脚本逐字节比对；模板没有版本兼容，因此任何改变生成源码的模板改动，都会使改动前签发的证明核验失败，相应图表在质量评估中降为“未核验”（软告警，不影响签发）。修改模板前应评估这一影响，并尽量把源码变化集中在同一次发布中。
5. 模板结构：各分支（图族、统计图、汇总箱线、堆叠双轴、纵/横向断轴、显示范围）固定写在模板源码中，按图形与参数在运行时选择；编译时只按需附加被调用的辅助函数段，不对模板文本做替换。

### 诊断

`standard_visualization_preflight` 返回 `source` 或 `diagnostic`。诊断含稳定的 `code`、`parameter`、`message`、`suggestion`，可选 `details`，例如：

| 类别 | 示例 code |
|---|---|
| 输入与身份 | `standard_input_missing`、`standard_input_identity_mismatch`、`standard_table_shape_invalid` |
| 标签与选列 | `standard_label_ambiguous`、`standard_labels_selection_invalid`、`standard_field_selection_invalid` |
| 数值与单位 | `standard_values_invalid`、`standard_series_empty`、`standard_axis_units_incompatible`、`standard_unit_conversion_invalid` |
| 长表与堆叠 | `standard_long_table_incomplete`、`standard_negative_stack_unsupported`、`standard_total_reconciliation_failed` |
| 轴与标注 | `standard_axes_mode_conflict`、`standard_zoom_range_invalid`、`standard_annotation_binding_invalid`、`standard_annotation_capacity_exceeded` |
| 来源与变换 | `standard_source_alignment_failed`（`details.reason`）、`standard_transformation_failed`（`standardSteps[index]`） |

`standard_series_empty`、`standard_source_alignment_failed`、`standard_period_alignment_invalid` 允许规划器修正绑定（`bindingCorrectionAllowed`）。日志：逐图路由 `report_visualization_chart_route`（含诊断码），整组异常回退 `report_standard_visualization_fallback`（含 code/parameter）。

## 图形类型

`standardForm` 是机器类型，`visualForm` 保留业务描述；旧计划仅兼容完整中文名称（如“堆叠柱合计折线图”），不解析自然语言。

| standardForm | 要点 |
|---|---|
| `line` `bar` `barh` | 宽表多系列，或 period×分类×value 长表；长表缺组合仅折线允许断点 |
| `stacked-bar` `stacked-area` `stacked-total` | 非负分项；`stacked-total` 画服务端求和折线，或用 `standardTotalField` 对账独立总额（相对1e-12、绝对1e-9） |
| `summary-bars` | 单行表中用 `standardValueFields` 选≥2个同元数据列，按列名转为类别 |
| `scatter` `bubble` `heatmap` | 需 `standardEncoding`，见“编码图” |
| `waterfall` `boxplot` | 需 `standardWaterfall` / `standardDistribution` / `standardBoxSummary`，见“统计图” |
| `pie` `donut` `radar` `funnel` `sankey` | 图族，见“图族” |
| `custom` | 显式交给 Coding，不计为标准命中失败 |

## 输入与数据准备

- **标签与度量**：`standardLabelField` 明确标签列；`standardValueFields` 选择度量（≤8），未选择时核验全部数值列，不静默丢弃。同轴系列须有明确且一致的单位与百分数尺度；`unit=%` 且 `isPercent=false` 的小数按百分数显示。
- **窗口**：`standardLabels` 逐字选择冻结标签窗口，按原输入顺序显示，不补齐缺失期间。
- **多来源**：`standardSources` 为每份输入声明 `sourceIndex/labelField/valueField/seriesName`，可用 `categoryField/categoryValue` 选长表分类、`labelMode=month|month_of_year` 规范月份、`excludedLabels` 排除合计。所有来源都须被使用；标签集合一致、无重复、单位明确才按第一来源行序对齐。`standardSourceLabels` 在对齐阶段选共同输入窗口（保留计算所需历史）。
- **变换流水线**：`standardSteps` 最多8步，每步为 `view` 或 `derivation`，不能与旧 `standardView/standardDerivations` 混用。
  - `view`：`group`（sum/mean/weighted_mean，按 `labelField` 加最多2个 `groupBy`）或 `pivot`（显式 `seriesValues`）。百分比不能求和；分组要求度量完整且有限。
  - `derivation`：`ratio_percent`、`difference`、`yoy_percent`、`mom_percent`、`cumulative_sum`（可 `reset=year`）、`rolling_sum/rolling_mean`（`window` 1—60，可 `minPeriods`）。缺失与非正基数保持 null，不填零；派生列不得复用已有列名。
- **单位**：`standardDisplayUnit` 及轴级 `leftDisplayUnit/rightDisplayUnit` 只用服务端单位表换算，拒绝不兼容换算（如金额转人次）和复合单位降维。

## 坐标轴

- **`standardAxes`**
  - `mode`：`single` / `dual`（`rightFields` 绑定右轴）/ `panels`（共享横轴的独立纵轴分面；横向柱图可配 `panelLimit` 与 `panelDescending` 做逐面板 TopN）/ `zoom`（`zoomStart/zoomEnd` 逐字绑定冻结标签，`zoomBounds` 设定子图位置）。
  - `scale`：`linear` / `log`（严格正数折线）/ `symlog`（需正数 `linearThreshold`）。
  - `allowNulls`：保留缺失空位并加说明；`zeroBaseline`：线性轴保留零基线。
  - 逐系列 `standardStyle.series[].geometry` 可组合同轴柱线图，也可与 panels/zoom 组合。
- **`standardDomains`**：`left/right/x/zoom/panels` 的 `min/max/ticks`（≤16，严格递增）、`tickFormat=auto|number|scientific`、`decimals`。数值按最终显示单位填写。默认 `outOfRange=reject`，须覆盖柱体零基线、真实累计端点、独立总额和范围带；显式 `annotate` 才允许仅显示裁切，并在图下说明。
- **`standardBreak`**（两段断轴）：
  - 纵向适用于 `line/bar/stacked-*`；`barh` 为横向左右两段。须给出两段完整的 `min/max`，且 `lower.max < upper.min`；每段可分别设置刻度与格式，另有 `gap`（0.03—0.3）、`lowerFraction`（0.25—0.75）、`markSize`。
  - 默认拒绝落在省略区间或超出整体范围的值，显式 `omittedValues/outOfRange=annotate` 才允许，并说明数量。
  - 不能与 `standardDomains` 同图使用，也不能用于 log/symlog 或多轴/分面/zoom。
  - 横向断轴在自动画布下按交界两侧刻度的实际宽度加宽段间留白。

## 堆叠双轴

`stacked-bar/stacked-total` 配合 `standardAxes.mode=dual`：左轴只堆叠未列入右轴的分项，正负分项分别从零累计（用 Fraction 计算，拒绝溢出）；右侧字段画独立单位的折线。`standardTotalField` 须与左侧有符号分项的净和对账，未提供时画服务端净和。左侧分项缺失、百分比堆叠、非线性轴、堆叠面积或与范围带组合时回退；`allowNulls` 只允许右轴缺失。

## 编码图

| 图形 | 参数与边界 |
|---|---|
| `scatter` | `xField/yField` 为数值，可选 `groupField`（≤8类）或 `colorField` 连续颜色（二者互斥）。最多480行；观测标注、排序与窗口需唯一冻结标签列。X/Y 可分别设显示单位、说明和 linear/log/symlog |
| `bubble` | 另需 `sizeField`，面积与非负原值成正比；`maxArea` 100—1600点²；不设虚假最小气泡 |
| `heatmap` | 两个文本维度加一个数值；≤480单元格、每轴≤60类；`xLabels/yLabels` 给完整顺序；缺失需 `allowNulls`，以灰色掩码显示，真实零值保持原色；`showValues` ≤60 |
| 折线范围带 | `standardBands` ≤8条，只用冻结上下界，上下界须包含中心值；支持 single/dual/panels/zoom；不自动估计置信区间 |

编码图只支持单图单坐标系，不与双轴、分面、局部放大组合。

## 统计图

- **瀑布** `standardWaterfall`：`absoluteLabels` 须含首项，区分起点、小计、终点；后续绝对值须与此前累计对账。用 Fraction 精确累计。仅支持可加度量与线性单轴，最多60项；可设角色颜色与连接线。
- **原始样本箱线** `standardDistribution`：每行是一个原始样本。最多480行、24组，`whiskerIqr` 默认1.5，标签显示样本量 n；`showFliers=false` 会在图下说明。缺失须 `allowNulls`。
- **登记分位数箱线** `standardBoxSummary`：直接用已登记的 Q1、中位数、Q3 和上下须，每组一行、最多24组，不重算分位数也不推断须的含义。可选 `countField`（正整数计数）和 `outlierSource`（第二份输入，异常点须严格位于须外）。未提供的信息在图下明确说明，例如“n未提供”“异常点未提供”。与 `standardDistribution` 互斥。

## 图族

| 图形 | 参数与边界 |
|---|---|
| `pie` `donut` | 单一冻结度量；`standardComposition.denominator` 冻结分母，分母须为正且不小于可见类别合计，不重新归一化 |
| `radar` | 显式保留3—8个轴，每轴须有登记单位；异量纲或含负值时须用 `standardRadar.scales` 为每个轴绑定冻结的 min/max；超出尺度不裁切 |
| `funnel` | 保持阶段原序或完整显式顺序，不排序、不做 TopN、不删阶段；`ratioBase=none\|first\|previous` |
| `sankey` | 用 `standardEncoding` 的 `xField/yField/valueField` 绑定原始的 source/target/weight；`standardSankey.nodes` 引用辅助节点表（ID 唯一且覆盖全部端点）；不造零流或平衡流 |

图族不支持笛卡尔多轴、断轴、范围、分页、范围带、辅助摘要和系列别名；标注只支持绑定原值，实体超出容量时不截断。

## 标注、展示与样式

- **`standardAnnotations`**（≤10条）：`values`、`peak/trough`（并列峰谷全部标出）、`point`、`reference`（以指定冻结点的值画参考线）、`range`（两个冻结标签之间的背景高亮）。可选 `color/highlight/position/caption`；热力图用 `rowLabel/endRowLabel` 定位单元格。可见标注总数≤60。
- **`standardLabelFields`**：最多3个同表辅助数值列（须有冻结单位），附加在标注文字上，不改变坐标轴。
- **`standardPresentation`**：`subtitle`、`sourceNote`、`order`（source/reverse/label/value/explicit/max_abs，可 `limit` 与 `excludeMissing`）、`labelFormats`（≤3，可由服务端计算同单位分子/分母比例）、`summaries`（≤4个图头徽章）。
- **`standardStyle`**
  - 主题与调色板：`theme=report|classic`；`palette=report|tab10|Set2|Dark2|Paired|viridis|cividis`。
  - 背景、网格与字号：背景、网格及透明度，标题/坐标轴/图例/标注字号，标签旋转，图例列数与位置，小数位，标注偏移，值轴留白，柱组宽度。
  - 逐系列 `series`（≤8）：颜色（六位 HEX）、线型、线宽、点型、点大小、透明度、纹理、柱/线几何、图例别名。
  - 逐点 `points`：按冻结标签设置颜色与点大小。
  - 引用未知系列会转 Coding，不会静默忽略。
- **`standardCanvas`**：`sizeMode=auto|fixed`（默认 auto、12×7英寸、150 DPI；尺寸范围4—20×3—24英寸，DPI 72—240，≤2400万像素）、`layout=tight|constrained|manual`、`crop=canvas|tight`、`labelWrap` 6—40（默认14）、`tickFontSize` 8—16、`legendPosition`、`maxCategoryTicks` 4—60（默认18，只稀疏显示刻度，数据点全部保留）。
- **换行**：类别标签、标题、副标题和来源注释按字符数均分换行；行尾不留开括号，行首不放闭合标点；不拆开连续字母数字和“数字+单位字”；原有换行保留。
- **布局自检**：标注文字重叠时最多移动16次；刻度、图例和断轴标记会检查重叠与越界，失败返回 `standard_chart_layout_unresolved`。只检查几何，不等同于视觉验收。

## 分页

`standardPagination={"pageSize":30,"maxPages":20}` 由宿主在规划器返回前原子展开：每页有独立的 chartId、PNG 和页号标题，全部页共用原事实绑定、完整行集和统一的数值范围、单位与颜色。仅支持单绑定宽表 `bar/barh`、单一线性轴、`values` 标注；最多480行、每页60类。页数受 `maxPages`、章节和用户图数预算共同限制，放不下时保留原图并回退，不只交付前几页。单图模板拒绝未展开的分页。

## 报告编辑器 AI 改图

“AI改图”→“标准图形与排版”提供12类预设（如双坐标轴、断轴、热力、瀑布、分页等），预设只填入改图要求，不保证任意数据都能画成该形状。

- 后端 `ChartEditPlan.standard` 直接派生生产 `ChartDraft` 的全部 standard 字段，不复制另一套参数定义。
- L1 使用当前已核验的完整作图数据；L2 只能换绑同一分析已签发的目录。
- 显式给出 standard 时走标准预检和执行，失败用同一数据交 Coding；只给自由描述时直接交 Coding。
- 上轮参数写入登记，后续按参数组继承；`inheritPreviousStandard=false` 可显式重置。
- 分页整组替换，一次可撤销；导出新版本时，只有整组身份匹配才迁移继续编辑记录。

## 容量速查

| 项 | 上限 |
|---|---|
| 系列 / 类别标签 / 行 | 8 / 60 / 480（散点、气泡可到480个观测） |
| 标注条目 / 可见标注 | 10 / 60 |
| 变换步骤 / 分组维度 | 8 / 主维度+2 |
| 范围带 / 辅助标注列 / 图头摘要 | 8 / 3 / 4 |
| 热力单元格 / 每轴类别 | 480 / 60 |
| 箱线分组 | 24 |
| 分页每页类别 / 最大页数 | 60 / `maxPages`（≤20）且受章节预算限制 |

## 未覆盖

- 三段及以上断轴、小提琴图（密度估计）、多坐标系统计图，以及编码图、图族与多轴的组合。
- 分页的变换、排序、TopN、统计图和跨页峰谷标注。
- 线上自动规划命中率、独立视觉模型审美验收、真实 PDF/Word 导出效果尚未在具备模型配置的环境中实测；现有证据来自离线回放加独立数值/几何审计。

## 验证与回放入口

| 用途 | 命令 |
|---|---|
| 换数据/压力场景 | `PYTHONPATH=. python scripts/replay_standard_visualization_variants.py BASELINE OUTPUT --suite all` |
| 冻结产物覆盖回放 | `PYTHONPATH=. python scripts/replay_standard_visualization.py ARCHIVE --output OUTPUT` |
| 原图/新版对照 | `PYTHONPATH=. python scripts/replay_standard_visualization_comparison.py ARCHIVE OUTPUT [PREVIOUS]` |
| OS 报告回放 | `PYTHONPATH=. python scripts/replay_os_standard_visualization.py REPORT.tar.xz OUTPUT` |
| 编辑器标准图 | `PYTHONPATH=. python scripts/replay_editor_standard_charts.py OUTPUT [--verify-only]` |
| 分页 | `PYTHONPATH=. python scripts/replay_standard_chart_pagination.py OUTPUT [--verify-only]` |
| 线上就绪检查 | `PYTHONPATH=. python scripts/replay_visualization_task.py --check-standard-readiness --output readiness.json` |
| 线上规划+标准路由 | `PYTHONPATH=. python scripts/replay_visualization_task.py --benchmark-bundle BUNDLE --variant candidate --standard-routes --output online.json` |

回放出现异常时以非零状态退出；文件存在不等于验收通过。
