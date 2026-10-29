# PR #147 登记单位回归核验（2026-10-29）

## 结论与版本

`code` 当前为 `0cfbd25a5ffe5a14afa3e47242b044d3ce8f616a`，尚无标准可视化模块。
首轮 PR #147 为 open，核验头部为 `8ccb485538c92f316148cc03aa7d7eedc72f672d`，
仍以 PR #146 的 `fix/supplemental-period-comparison-table-lineage` 为目标。

审查针对的 `c713499f6fdf174930f6f06c407cf22dbd3c05a2` 确实丢弃单位。
后续提交 `1a970e868cc4f09f20d128713dcf3098c3459dec` 已实施所需修复：
从冻结 `columnMeta` 读取度量单位，加入模板配置，并在纵向图的 Y 轴、横向图的 X 轴显示。
当前头部保留该实现。本轮不重复改写运行时，补齐直接检出原缺陷的回归测试。

## 复现与修复证据

历史复现输入为 `columns=[period,value]` 或 `columns=[label,value]`、
`rows=[[2025-01,10],[2025-02,20]]`、`columnMeta.value.unit=万元`、标题“收入趋势”。
执行从 Git 读取的历史编译函数及其生成的 Matplotlib 脚本，沿用内容 SHA256 核验。
两种输入分别配 line/bar/barh 共 6 次成图，数值轴标签均为空。

把本轮单位回归测试指向同一历史编译函数后，period/value 折线的元、万元、
标题已重复万元三个用例均在轴单位断言失败，实际值为空字符串。
测试因此能够检出原审查问题，而非仅检查脚本中出现单位字符串。

当前实现的 30 个参数化用例覆盖：

- period/value 与 label/value；line、bar、barh。
- 登记元、登记万元但标题未提及，以及标题已重复万元。
- 缺少 columnMeta 时继续保持既有单系列行为，轴不猜测单位；标题写有万元也不作为登记来源。
- 原值 `[0, -12500.5, 27000.25]` 与实际折线 Y 值、柱高或横向柱宽逐项完全相等；输入文件字节不变。
- 轴标签严格等于登记单位；标题保留，生成真实 PNG。

扩展逐图路由测试，实际检查最终保存的图，而非仅检查预检结果。
不支持的相邻图、单图视觉审查失败、最终视觉审查定位单图，以及组件篡改分别沿用原有隔离/拒绝断言。
成功保留的横向标准图在最终组合执行后仍具有 X 轴“元”和柱宽 `[10,20]`；
无需 Coding 修复的折线仍具有 Y 轴“元”和原始 Y 值。组件篡改继续拒绝执行。

## 验证

Python 3.12.14，Matplotlib 3.11.1，NumPy 2.3.5，Pandas 2.3.3，SciPy 1.16.3，Agno 3.1.2。
渲染环境安装 Noto Sans CJK SC。没有运行完整仓库测试或完整历史回放。

在 `91b5bf70397204f235a8b2da6fc26762b7489e25` 上，以下四个文件合计 **135 项通过**：

```bash
.venv/bin/python -m pytest \
  smart_reporting/reporting/tests/test_standard_visualization.py \
  smart_reporting/reporting/tests/test_standard_chart_routing.py \
  smart_reporting/reporting/tests/test_report_vision.py \
  smart_reporting/reporting/tests/test_chart_input_projection.py -q
```

工作期间上游新增横向断轴提交；本地快进到 `8ccb485538` 后，针对发生变化的运行时复核以下 **61 项通过**：

```bash
.venv/bin/python -m pytest \
  smart_reporting/reporting/tests/test_standard_visualization.py::test_registered_unit_reaches_value_axis_without_changing_values \
  smart_reporting/reporting/tests/test_standard_chart_routing.py \
  smart_reporting/reporting/tests/test_standard_chart_horizontal_breaks.py -q
```

更新 PR 前，上游推进到 `59b0d30f3dca1165d24e26630c1ec0306c70749e`。
以该版本为基线同步测试提交后，重跑上述四个测试文件与横向断轴测试文件，合计 **155 项通过**。

Ruff 检查两个改动测试文件以及 standard_visualization、standard_chart_routing、
standard_chart_horizontal_breaks、vision 模块通过；`git diff --check` 通过。

## Readiness 与 PR 后续

`vision.py` 的 `missing_units` 仍为 warning；现有视觉审查测试确认不会因此要求修复。
这与语义问题非阻断契约一致，不能用它代替标准模板正确传递登记单位。
本轮未修改视觉审查、发布或下载签发策略。

以上为离线确定性渲染和带测试替身的路由验证。生产模型地址/凭据、自动规划命中、
真实 Coding 修复和独立视觉模型尚未验证，也未部署。
线上验收仍须以实际配置跑通计划、物化、标准执行、强制逐图回退、独立看图、提交及当前回执核验。

建议把本轮测试与证据提交补入 PR #147，并在复审确认后处理仍未解决的过时 P2 线程；
无需再添加相同运行时修复。PR #146 合并后再将 #147 的目标改为 code。
本次提交无冲突地同步到 `59b0d30f3dca1165d24e26630c1ec0306c70749e`。
本次更新范围为测试和核验记录；不改变目标分支，不代替复审解决线程，也不合并 PR。
