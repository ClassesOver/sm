# 标准可视化

以下保留各轮验证记录；当前能力及限制以首节为准。

## 瀑布贡献链与原始样本箱线图（2026-10-28）

新增`visualForm=waterfall`与`standardWaterfall`，使用绑定长表的唯一冻结标签及有符号度量列。`absoluteLabels`必须包含首项，显式区分起点/小计/终点与其他增减项；后续绝对值须与此前累计按1e-12相对容差对账，不隐式重置累计。累计用标准库`Fraction`保留输入浮点数的精确贡献，最终转回坐标时拒绝溢出或非零增减完全不可见的情况。没有终点标签不会补造总额；小计不重复计入后续累计。支持零、负贡献和负数起点/终点。

`increaseColor/decreaseColor/absoluteColor`分别控制角色颜色，`connectors`控制连接线；按`standardStyle.points`的度量名+冻结标签覆盖某个贡献的颜色。标注显示原始增减值或绝对值，位置对应累计端点，避免把累计值误称为单项贡献；负数保留有符号柱高。瀑布仅支持明确可加度量与线性单轴，百分比、缺失贡献、排序/TopN/标签截取和逐系列几何替换回退Coding。最多60项。

```json
{
  "visualForm": "waterfall",
  "standardLabelField": "项目",
  "standardValueFields": ["金额"],
  "standardWaterfall": {
    "valueField": "金额",
    "absoluteLabels": ["期初", "小计", "期末"],
    "increaseColor": "#36856b", "decreaseColor": "#b55d68", "absoluteColor": "#3066a3",
    "connectors": true
  }
}
```

新增`visualForm=boxplot`与`standardDistribution`，`groupField`为冻结文本分组，`valueField`每行必须代表一个已绑定的原始样本，不能用汇总均值/总额冒充分布。最多480行、24组；`groupLabels`只调整所有当前分组的完整顺序，不删除样本。`orientation=vertical/horizontal`控制方向；支持登记单位换算、百分数尺度、log/symlog、按冻结组名设置系列颜色/线型及图例别名（用于分类标签）。

使用Matplotlib的`boxplot_stats`与`bxp`，线性插值四分位、默认`whiskerIqr=1.5`倍IQR须，拒绝不可表示的四分位/IQR溢出。每组分类标签显示有效样本数n；单样本、相同值样本保持退化箱体，不添加抖动或假观测。缺失须`allowNulls=true`，仅排除未知样本并注明，不补零；整组无样本则回退。`showFliers=false`才隐藏异常点，明确写入图下说明，统计仍使用全部有效样本；显示异常点时不能用marker=none静默隐藏。

```json
{
  "visualForm": "boxplot",
  "standardValueFields": ["收入"],
  "standardDistribution": {
    "groupField": "院区", "valueField": "收入", "groupLabels": ["东院", "西院"],
    "orientation": "horizontal", "whiskerIqr": 1.5, "showFliers": true
  },
  "standardAxes": {"allowNulls": true, "scale": "symlog", "linearThreshold": 1}
}
```

两类图复用标准画布/排版/来源说明与`values/peak/trough/point/range`标注，箱线标注明确称“中位数”；高亮仅加文本框，不制造额外样本点。暂不支持多轴、参考线、辅助字段或冻结行摘要。规划器及Coding指令要求绑定全部类别和度量字段，保留作用域及原输入SHA；标准统计脚本仅在出现这些图形时加入，旧图编译结果保持逐字节一致。

`--suite statistics`新增48场景，3个种子×3个量级×4类配置共36张成图，另12个预期回退。独立检查每根瀑布柱的起点/有符号高度/横坐标/颜色、连接线位置与端点，以及箱线四分位/中位数/须/异常点/样本数/颜色；横向分组轴也检查刻度重叠。独立四分位预期使用排序与插值，不调用Matplotlib统计函数。7个故意错误的几何/颜色预期被识别。

新增31项测试分批通过，并定向回归189项旧绘图、逐图路由、编码和计划模型测试，本轮220项通过；包含真实Pydantic计划序列化→授权字段物化→绘图、混合旧图/瀑布/箱线批量执行，以及正式源码门禁和输入篡改拒绝。3模块mypy、Ruff、diff检查通过。原384场景及OS报告16图重新编译与既有已执行脚本一致，不重复完整回归；新48场景使用最终统计渲染器及扩展独立审计回放。`--suite all`现有432场景：326成图、101预检回退、2身份拒绝、2布局修复、1schema拒绝。

仍未标准化：小提琴密度估计、预先汇总分位数输入、堆叠双轴、断轴/显式刻度范围、大数据分页，以及真实线上自动规划与审美验收。当前验证仍为离线人工参数回放，不能宣称线上模型命中率，尚未部署。其余能力与历史证据见下节。

## 数值坐标、热力矩阵与冻结范围带（2026-10-28）

新增`standardEncoding`和`standardBands`，与既有数据变换、SHA256身份核验、标准画布、独立图形校验及逐图Coding回退共用流程。规划器和Coding指令同步更新：编码使用的坐标、类别、面积、颜色、观测标签、范围上下界必须进入`dataBindings`，不能只绑定中心值。

| 图形 | 标准参数与边界 |
|---|---|
| `scatter` | `xField/yField`为登记单位的数值，使用真实数值X/Y；可选`groupField`（最多8类）或`colorField`连续颜色，两者互斥。最多480行；无标签列时仍可绘制，但指定观测标注、逐点样式、标签窗口及排序须有唯一冻结`standardLabelField`。 |
| `bubble` | 同散点，另须`sizeField`；面积与原非负数值成正比，`maxArea`仅调整最大面积（100—1600点²）。零面积保持零，不设虚假最小气泡；全零/非零面积小于1点²时回退其他视图。高亮和逐系列点型不能改变面积或连续颜色。 |
| `heatmap` | 长表的两个不同文本维度`xField/yField`与一个数值`valueField`；最大480网格单元、每轴60类。`xLabels/yLabels`可声明所有现存类别的完整顺序；重复单元须先显式分组，不能暗中求和。缺失组合/值须`allowNulls=true`，显示灰色掩码，真实零值保持原颜色。 |
| 折线范围带 | `standardBands:[{series,lowerField,upperField,label?,color?,alpha?}]`，最多8条；只使用冻结上下界，支持single/dual/panels/zoom，单位可换算、期间须相同，百分数/小数尺度自动归一，上下界须包含中心值。缺失上下界须同时为空且显式`allowNulls=true`，保持断带并在图下注明；全缺失时不显示虚假范围图例。不能自动估计置信区间。 |

散点分别用`xDisplayUnit/yDisplayUnit`设置可登记换算的轴单位，`xCaption/yCaption`设置说明；Y轴沿用`standardAxes.scale/linearThreshold`，X轴用`xScale/xLinearThreshold`，支持linear/log/symlog，普通对数拒绝零负值。连续颜色使用`colorDisplayUnit/colorCaption`及`colorMap`（viridis/cividis/Blues/RdBu_r/YlGnBu）、`colorScale`、`colorLinearThreshold`；线性`colorCenter`必须严格位于数据最小/最大值之间，适合围绕零的发散色标。`sizeCaption`设置面积含义说明。

热力`showValues`最多60个数值标签，最终布局检查每个标签是否容纳在单元内；密集矩阵应关闭逐值文字。point用`label+rowLabel`定位冻结单元，range再给`endLabel+endRowLabel`框选矩形；高亮描边保留数值颜色。散点标注定位真实数值坐标，高亮文本框保留气泡面积和颜色。缺失观测使用联合掩码，不补零；连续色标轴不参与类别刻度变换。散点/气泡/热力当前只支持单图单坐标系，不组合双轴/分面/局部放大。

```json
{
  "visualForm": "bubble",
  "standardLabelField": "科室",
  "standardValueFields": ["收入"],
  "standardEncoding": {
    "xField": "人次", "yField": "收入", "sizeField": "样本量", "groupField": "院区",
    "xDisplayUnit": "万人次", "yDisplayUnit": "万元",
    "xCaption": "就诊量", "yCaption": "医疗收入", "sizeCaption": "样本量", "maxArea": 600
  }
}
```

新增`--suite geometry`，包含3个随机种子×3个量级（1e-10/1/1e10）的散点/气泡、稀疏/稠密矩阵和四类轴范围带，以及12个异常案例：84场景中72张实际成图、12个预期回退。独立校验核对每个点的坐标/面积/连续色值及颜色、矩阵方向/掩码/零值/色标范围、范围带每个横坐标的上下界与断点，不只检查文件存在。故意篡改预期坐标、面积、矩阵方向、缺失掩码、上下界和调色板的6项负例均被识别。另验证480点及100点多来源输入通过正式源码门禁，不把全部观测数值内嵌到脚本。

`--suite all`现有384个换数据案例：290成图、89预检回退、2身份拒绝、2布局修复、1schema拒绝，均符合各自预期。最终编译结果与实际执行脚本逐字节一致或保持相同拒绝路线，缺失范围说明修改后只重放受影响源码的案例。原OS报告16图全部回归通过，59项登记资源身份核验、21份作图输入值不变，保留原图对比PDF。

新增47项测试与原329项相关测试合计376项通过；另外扩展到计划模型、输入投影和固定阶段工作流260项通过，共636项。修正旧计划模型快照遗漏标准参数字段的问题，保留原业务元数据断言；新增真实Pydantic计划序列化→授权字段物化→气泡绘图检查。本轮4模块mypy及Ruff检查通过。离线回放是人工参数+独立几何/数值核验，不能据此声称线上模型自动命中率或独立视觉模型验收已通过；尚未部署。

尚未标准化的主要缺口：箱线/小提琴等分布统计图、瀑布图、堆叠双轴、断轴/显式刻度范围、大数据分页，以及真实线上自动规划与审美验收。复杂参数不支持时只回退对应图，其他图继续使用标准路线；产物下载签发保持原非阻断契约。

## 多维变换与时间计算流水线（2026-10-28）

新增`standardSteps`，按声明顺序执行最多8步，每步只能包含`view`或`derivation`；不能与旧`standardView/standardDerivations`混用。每一步使用上一步的列及登记单位，保留服务端计算的转换记录和`bound_input_rows_only`范围。原输入SHA256仍在执行前重新核验，不覆盖原文件。派生列不得复用原始列名或前面步骤曾生成的列名，即使该列在中间视图被丢弃。步骤失败返回`standard_transformation_failed`与`standardSteps[index]`，方便定向修正。

分组`view.kind=group`以`labelField`为主维度、`groupBy`为最多两个附加维度，保留三个维度的原列，不拼接业务标签。`aggregation=sum`继续复用冻结事实的可加指标聚合；`mean`使用标准库`statistics.mean`；`weighted_mean`必须声明有登记单位的非负`weightField`，用标准库`Fraction`对输入浮点数精确计算乘积/和/比值后转回float，避免中间溢出、最小非零值提前归零或极小权重的有效贡献被丢弃。零总权重返回null。分组操作要求度量输入完整且有限；不能把缺失项默认为0。百分比只能求均值或加权平均，不允许求和；原百分数/小数尺度保持不变。均值或加权平均的业务标题应明确其含义，不能称为总额。

`derivation`以`numerator`指定冻结/前步度量，时间运算必须给`labelField`，可用`groupBy`隔离最多三个业务维度：

| kind | 行为与边界 |
|---|---|
| `yoy_percent` | 按同组去年同月匹配，支持不连续历史；没有去年同月或基数非正时为null，不拿相邻行替代。 |
| `mom_percent` | 同组连续月环比；首月或缺失/非正基数为null。 |
| `cumulative_sum` | 从绑定的首月累计，默认跨年连续；`reset=year`才按年重置。遇到未知值后保持未知，直到显式年度重置。不能把年中起始样本称为完整年初至今累计。 |
| `rolling_sum` / `rolling_mean` | 必须声明`window`（1—60月）；默认完整有效窗口，早期/缺失窗口为null。`minPeriods`可显式减少最低有效样本数，计算只使用该窗口内已知值，不填零。 |

除同比外，时间操作要求同组月份连续；所有时间操作拒绝同月重复观测和非有限值。累计/滚动求和不能用于百分比，百分比滚动均值保留原比例尺度。同行差额/比率也会传播缺失操作数。

多来源历史窗口与展示窗口分开：`standardSourceLabels`在`standardSources`对齐阶段选共同输入窗口，须使用来源归一化后的标签并保留计算所需历史；有数据变换时，`standardLabels`只在计算后选展示窗口，避免先裁掉同比/滚动基数。仍不自动外连接、补齐或猜测缺失的来源月份；未使用变换的旧参数保持原有共同窗口行为。

示例：按月与院区汇总→计算完成率→分院区滚动均值→透视成两条系列。

```json
{
  "standardLabelField": "月份",
  "standardValueFields": ["东院", "西院"],
  "standardAxes": {"allowNulls": true},
  "standardSteps": [
    {"view": {"kind": "group", "labelField": "月份", "groupBy": ["院区"], "valueFields": ["收入", "预算"]}},
    {"derivation": {"kind": "ratio_percent", "name": "完成率", "numerator": "收入", "denominator": "预算"}},
    {"derivation": {"kind": "rolling_mean", "name": "平滑完成率", "numerator": "完成率", "labelField": "月份", "groupBy": ["院区"], "window": 3}},
    {"view": {"kind": "pivot", "labelField": "月份", "seriesField": "院区", "seriesValues": ["东院", "西院"], "valueFields": ["平滑完成率"]}}
  ]
}
```

新增`--suite pipelines`，由`scripts/standard_visualization_pipeline_cases.py`提供独立预期：3个随机种子×3个量级×8类运算，另有6个异常回退案例。78场景中72个实际成图并逐值核对、6个预期回退；加权平均案例显式按月份排序后定向复验。原122基础及100扩展场景也重新运行，三组共300场景：218成图、77预检回退、2身份拒绝、2布局修复、1schema拒绝，全部符合各自预期。`--suite all`包含这300个场景，默认basic仍为原122个。

本轮50项新增测试覆盖多维键碰撞、百分比尺度、零/非法权重、极端量级和次正规数、稀疏同比、分组隔离、累计缺失传播/年度重置、完整/显式部分滚动窗口、乱序换数据、流水线命名保护、步骤诊断、来源历史窗口及原始身份篡改；分批合计329项相关测试通过，3模块mypy、Ruff及diff检查通过。生成参数指令与Coding回退指令同步支持这些操作。仍为离线验证，线上模型自动规划与独立视觉模型未实测，尚未部署。

剩余主要能力缺口：更多统计图形、堆叠双轴、断轴/显式刻度范围、大数据自动分页，以及真实线上自动命中与审美验收。流水线不提供任意表达式、隐式补值或未经声明的自动聚合。

## 逐图路由、诊断与复杂组合（2026-10-28）

生产章节工作流使用`run_standard_chart_routes`。全部支持时仍执行一次标准脚本；混合计划或批量标准执行失败时，按图隔离预检与执行，只把不支持/验收失败的图交给Coding。组件脚本分别校验身份，最终组合脚本重新核验所有chart-input和组件SHA256、在独立命名空间执行，并重新走执行、看图、提交及当前回执核验。单图组件的旧回执不能代替最终回执。最终视觉诊断明确指向某张图时，允许一次只修复该图的Coding重试；无法定位的整体错误仍由原工作流处理。旧交互计划保留原兼容路线，不把JSON companion送进图片审查；没有新增Plotly能力。

`standard_visualization_preflight`返回`source/diagnostic`，常见失败有稳定code、parameter、message与suggestion：图形不支持、输入缺失/身份变化、标签歧义、选列错误、非法数值/空系列、来源对齐、单位换算/同轴量纲、普通对数含零负数、重复标签、负堆叠及标签/标注容量等。标准预检失败属于首次Coding生成，诊断随`standardChartPreflight`传入并保留完整作用域计划；已有脚本执行/视觉失败才使用修复诊断，避免误读不存在的脚本。结果记录`standard_chart_routes`，组合脚本保留`CHART_ROUTES`，日志区分standard/coding数量。

柱线混合可与panels/zoom组合。新增`standardAxes.scale="symlog"`及正数`linearThreshold`，用于同时含零、负值和悬殊量级的数据，阈值以显示单位表达。局部图只绘制声明窗口，保留完整边缘柱体，逐点颜色按窗口内原标签绑定。数字轴不再应用类别标签换行，避免破坏对数数学刻度。

自动图例在候选位置按数据点、柱体及其他图例遮挡情况选择位置；标注避让图例和子图标题。只有明确测量到`standard_chart_layout_unresolved`，且`sizeMode=auto`时，最多扩大画布重试两次；保留DPI、裁切/布局策略及2400万像素预算，不改变固定画布、不吞掉身份或语义失败。图例避让是几何启发式，仍不能替代独立视觉审查或保证美观。

修复图表登记投影：按`ReportChartRegistration`字段白名单生成归档请求，避免标准参数被登记接口当作多余字段拒绝；完整作图参数仍保留在计划及签名脚本。

线上验证复用既有回放工具，不另建模型调用框架：

```bash
# 仅检查当前进程配置；缺少配置返回2，不调用模型、不打印凭据值。
PYTHONPATH=. python scripts/replay_visualization_task.py --check-standard-readiness --output readiness.json

# 实际自动规划→标准路线/逐图Coding→独立视觉与回执验收。
PYTHONPATH=. python scripts/replay_visualization_task.py --benchmark-bundle BUNDLE --variant candidate --standard-routes --output online.json
```

`--standard-routes`为明确的验证模式：candidate planner加入生产标准参数指令，执行复用生产路由，结果记录逐图路线与`routeCounts`；不与默认benchmark结果混计。缺少物化输入不能将普通Coding回放标为标准命中。当前环境未配置模型接口地址及凭据，readiness实际返回`blocked_missing_model_configuration`、模型请求0次，线上自动命中/Coding修复/独立视觉验收均未验证。

本轮22项新增测试覆盖混合计划、单图/最终视觉失败隔离、批量失败隔离、组件篡改、全部支持快路径、旧兼容路径、诊断、柱线分面/局部图、symlog、窗口颜色/边缘柱体、有限自动调参及线上入口；合计482项定向测试通过（分批运行，失败修复后定向复验），5模块mypy、Ruff与diff检查通过。原222场景保持146成图/71预检回退/2身份拒绝/2布局修复/1schema拒绝；后续刻度与局部图修复另定向回归32个高级轴场景，24成图、8预期回退。新增7个合成复杂组合场景均通过实际系列数值与几何审计；OS报告16张图再次全部通过原来源离线回放。以上回放不等同于线上自动命中或完整审美验收。

仍未标准化：多维/多步数据变换、加权平均/累计/同比/滚动窗口、更多统计图形、堆叠双轴、断轴与显式轴刻度范围、大数据自动分页等。身份、单位和来源核验边界继续保留。

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
