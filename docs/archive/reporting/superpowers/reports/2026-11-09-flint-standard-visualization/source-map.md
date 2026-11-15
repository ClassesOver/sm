# 源码与证据地图

## 冻结身份

- 本项目：`28649e9c56b1aa7e96f0c363e8eec8accd0175b7`，分支 `audit/flint-standard-visualization-research`。
- Flint：Microsoft `microsoft/flint-chart`，提交 `a794557384adcc3293a77043f6b9aff1c33d152c`；`packages/flint-js` 版本 `1.0.1`，MIT。
- Flint 根 `package-lock.json` SHA256：`64e380870e1e82aad1629d8a45a6b01cbfc5e9594c17c2043e1f547b2d239a0e`。
- 本机：Python 3.12.3，Matplotlib 3.11.1 / Agg，Pillow 12.3.0；Node v24.18.0；Noto Sans CJK 字体可用。
- 上游依赖锁定安装未完成：`npm ci --ignore-scripts --no-audit --no-fund` 被执行环境拒绝，错误为 `EALLOWREMOTE`，拒绝获取 lockfile 指向的 `vite@...tgz`。因此 Flint Vitest 均未运行，以下只区分源码存在与测试源码覆盖。

## Flint 编译链

入口 `packages/flint-js/src/vegalite/assemble.ts:931-935` 顺序调用 `prepareVegaLite`、`analyzeChart`、`planLayout`、`emitVegaLite`。这个路径能将输入落实到 Vega-Lite spec；Flint 仓库还有其他后端，但本研究不将其纳入对照。

| 阶段 | 源码 | 观察到的行为 | 证据等级 / 边界 |
|---|---|---|---|
| 输入、编码规范化 | `packages/flint-js/src/core/analyze.ts:53-143` | 读取 `data.values`、`semantic_types` 和 `chart_spec.encodings`；整理静态系列、修复排序、推断编码类型、应用 override、隐式聚合。 | `source_present`；字段语义并非完全由静态类型定义。 |
| 类型推断 | `packages/flint-js/src/core/resolve-semantics.ts:233-245, 428-440, 513-550, 574-607` | 显式 annotation 优先；也包含按字段名 token 和数据值推断 `Year` 的窄启发式；数值/日期解析由不同路径处理。 | `source_present`；`temporal-parse.test.ts:57-60` 明确测试未被 semantic type 指导时不自动转换。 |
| 正交语义 registry | `packages/flint-js/src/core/type-registry.ts:41-69, 75-81` | type 映射至 aggregation role、domain shape、diverging、format class、zero-baseline、zeroPad 等多个决策维度；未知类型注释规定落到 `Unknown`/nominal/plain。 | `source_present`；便于集中改规则，但 registry 属性本身仍是领域判断，不构成其正确性的独立证明。 |
| 字段语义 | `packages/flint-js/src/core/field-semantics.ts:1143-1180` | 从语义 annotation 和实际值计算 format、默认可视类型、aggregation、domain、ordering、cyclic、binning 等字段语义。 | `source_present`；调用者需把“金额/数量/比例”等标注正确传入。 |
| 通道语义 | `packages/flint-js/src/core/resolve-semantics.ts:612-671` | 对每个编码解析 field semantics，再结合 channel 决定可视类型、sort、ticks、颜色、temporal 等；部分 chart marks 的零基线在 `analyze.ts:154-168` 按 mark 决策。 | `source_present`；需要沿目标 chart template 继续核对，不能只看 registry 推出最终 spec。 |
| 显示单位 | `packages/flint-js/src/core/field-semantics.ts:377-490`；`tests/unit-display.test.ts:32-72` | 显示 unit 来自显式 annotation；测试源码断言不从 semantic type 猜可见单位、常规缩写、词性单位放标题及拒绝 prose 当单位。 | `source_present`（含测试源码审阅，未执行）。它是显示策略，不等于跨单位数值换算或单位兼容证明。 |
| 时间解析 | `packages/flint-js/src/core/temporal-parse.ts`；`tests/temporal-parse.test.ts:9-60` | typed parser 支持若干明确年月/日期文本形式，对非法月份和 impossible date 返回 null；没有被类型指示时不强制将整数变日期。 | `source_present`（含测试源码审阅，未执行）；仍需业务数据契约决定日期粒度与时区。 |
| 值域 | `packages/flint-js/src/core/measure-domain.ts:161-210` | 可读取 intrinsic domain；若声明特定语义可推固定范围；结合 mark、channel、数值计算 domain。 | `source_present`；须审查规则与业务语义匹配，不能推成通用金融轴政策。 |
| 布局 reserve | `packages/flint-js/src/core/furniture-reserve.ts:14-62, 68-96` | 把家具分解为轴标签、标题、图例等占用量；使用 text measurer、轴标签/值域计算宽度。 | `source_present`。 |
| 布局 fit | `packages/flint-js/src/core/canvas-fit.ts:17-30, 116-125` | 对 around、labels、stretch、scale、aspect、minSide 定量判断 canvas 是否拥挤；`plan.ts:157-186` 将语义和值域组合进入布局。 | `source_present`；规则使用估计与阈值，仍需具体 renderer 实测验证。 |
| 规范输出 | `packages/flint-js/src/vegalite/assemble.ts:931-935` | 输出为 assembled Vega-Lite spec；`emitVegaLite` 后还可用 `vegaLiteHonour` 对 plan 与实际 spec 的偏离作检查（1004-1030）。 | `source_present`；当前环境不能运行上游验证器。 |

## 上游测试材料

| 测试 | 具体断言 | 没有证明什么 |
|---|---|---|
| `packages/flint-js/tests/unit-display.test.ts:32-72` | 显式单位展示、不从 semantic type 推显示单位、`kg`/`USD` 显示归一、prose 不作为 unit。 | 不能证明数据的原始单位声明正确、换算正确、ratio 与百分点相互区分。 |
| `packages/flint-js/tests/temporal-parse.test.ts:9-60` | 多种 YearMonth/Date 输入、非法日期拒绝、解析依赖语义类型。 | 不能证明任意 locale、时区、财政期或本项目比较窗口口径。 |
| `packages/flint-js/tests/furniture-reserve.test.ts:17-51` | 图例和 y-label 预留空间、更多家具时 band step 变化、replan 保留空间。 | 不能证明中文字体、Matplotlib PNG 文本无重叠；Flint 的测试渲染布局与本项目 renderer 不同。 |
| `packages/flint-js/tests/canvas-fit.test.ts` | 文件存在，但本次未读取全文件或执行。 | 不把文件存在称作测试覆盖或通过。 |

## 原始修复记录与反例

已读取 [Flint PR #147](https://github.com/microsoft/flint-chart/pull/147) 的说明和文件差异，公开说明快照见 [`evidence/flint-pr147.json`](evidence/flint-pr147.json)，逐文件差异见 [`evidence/flint-pr147-files.json`](evidence/flint-pr147-files.json)。合并提交为 `3e99e1bfcfc5acbd4eebb37826ed28840fc6f505`。本地固定基线包含对应测试 `packages/flint-js/tests/year-band-dodge.test.ts`。

- **触发输入：** 12 个连续年份、每年只有四个系列中的两个，`x` 声明为 `Year`、数值为 `Quantity`，Grouped Bar 使用 `dodge: local`。时间语义不变，但模板将年份轴按类别 band 绘制。
- **修复前：** `templates/bar.ts` 按 x 的 nominal/ordinal 类型选择分组轴；Year 仍是 temporal，于是误选 y，形成 `groupby: ['y']`。PR 作者记录柱宽归零的 SVG 路径。
- **修复后：** instantiate 按 assembler 已选择的 `xOffset/yOffset` 定位轴；Grouped Bar 与 Boxplot 的选项检查改用布局同一个 `detectBandedAxisForceDiscrete` 决策，避免重复猜测。
- **回归断言：** 完整系列情形检查 `xOffset`；稀疏系列情形检查两条 lane transform 都按 `['x']` 分组；Boxplot 检查 local dodge 选项适用。测试没有独立检查中文字体、PNG 重叠或本项目业务绑定。
- **证据边界：** 差异和测试源码为 `source_present`。PR 作者陈述修复前失败、修复后通过及 2854 项测试通过，属于公开作者运行陈述；本机没有执行这些测试，不能记作本地通过。

这个反例支持的建议是：语义声明、布局计划和后端输出应共享可核验决策，不能由各层单独按类型猜测。它不证明本项目存在相同缺陷，也不支持新增图种或引入 Flint renderer。

历史检索限制：本地 checkout 是浅克隆，`git log` 只有冻结 HEAD。GitHub 路径提交查询在该冻结版本的 `furniture-reserve.ts` 下只返回发布 squash 提交 `60324d2fa31acd46bb2e79bc4503930da69f2619`（#146）；不能从聚合提交说明还原每项修复的独立前后状态，因此没有凑满 5 项案例。`CHANGELOG.md:203-215,251-275` 的显式单位、端点标签 packing 和 reserve 描述只作历史索引，不作效果证明。

README 链接论文 `arXiv:2607.20775`，本次只确认该索引，未审阅全文方法、附录或逐样本数据，也未复算论文结果。论文相关结论保持 `not_reviewed`。

## 本项目链路及对照边界

1. `ChartDraft` 中的字段绑定、来源选择、period/comparison、axes 和 derivation 定义见 `smart_reporting/reporting/workflow/runtime/phase_models.py:757-927`。
2. `chart_inputs.py:302-369` 将绑定列投影为冻结 chart-input，并记录列名、行数、可空列、columnMeta、size、SHA256；`437-465` 对读取原事实文件重验 SHA，再物化输入，宿主准备失败时回退 facts 路径。
3. `standard_chart_pagination.py:37-162` 要求显式且完整的类别/值列、一致登记单位/比例尺度、显式缺失策略，并用全表值范围锁定分页共用值域；`165-195` 展开失败时保留原图并附 warning。
4. `standard_chart_alignment.py:9-82` 依据显式 sourceIndex/field 绑定和文件 SHA 做多源对齐；`standard_chart_transform.py:235-318` 处理声明的 view/derivation。测试 `test_standard_chart_transform.py` 覆盖单位不兼容、月份连续、保留空值、多个 source 选择等路径。
5. `standard_visualization.py:80-101` 以结构化 preflight 生成标准绘图脚本或诊断；`146-169` 对比较期间施加显式条件；`195` 起组装 Matplotlib 脚本，custom 请求保留为 Coding 选择。
6. `standard_chart_routing.py:164-250` 逐图 preflight 并记录 standard/Coding 路由；初始合并绘制失败后可以运行回退逻辑（388 行起）。本次仅据源码和已通过现有定向测试，不统计线上命中率。
7. `standard_chart_presentation.py` 与 `standard_visualization.py:686-869` 管理格式化、标注、静态 canvas 与布局；缺少生产输入及 reviewer 回执时，不推导视觉正确。

### 证据类型不得互换

- Git SHA/文件 SHA 只核对文件身份，不证明内容正确。
- 独立 Decimal/Fraction oracle 只证明明确给定公式和样本值的数值结果。
- 几何文本边界只检查图元未越画布，不证明互不重叠或业务映射正确。
- PNG 人工自查不构成盲法独立视觉审查。
- pytest 通过证明列出的回归节点通过，不代表线上总体正确率或任何性能收益。

本次没有读取任何业务数据库、真实冻结任务或未脱敏业务素材。没有找到/取得独立领域审阅人和两名盲法视觉审阅人；这两类裁决保持 `not_reviewed`。
