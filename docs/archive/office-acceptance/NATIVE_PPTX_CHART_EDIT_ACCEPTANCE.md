# 原生 PPTX 图表数据与类型编辑

交付范围对齐固定 GenOffice `f8c17004…` 的 `ChartDataDialog` / `ChartTypeDialog`。图表数据编辑支持类别名、系列名、数值以及新增/删除类别和系列；空白或无效数值沿源行为保存为 0。类型切换沿源图表库的 13 项图库。散点图只接受数值 X 类别，组合图至少两个系列。

编辑只接受 GenOffice 创建并携带 `aislides-chart` 标记的标准内嵌工作簿图表。外部图表、扩展/特殊类别、共享图表部件或共享工作簿，以及无法确认图表数据映射的对象返回 `chartEditSafe=false` 和 `pptx_chart_source_unsupported`，宿主应禁用编辑入口并提示来源不支持。类别名、系列名上限为 100 个 Unicode 字符，禁止控制字符；超限的来源图表只读。类别与系列数据应同一事务提交，每批最多 50 项；重复图表目标拒绝，防止旧数据覆盖新修改。编辑更新原图表部件及其嵌入工作簿，保留页面上其他部件。

专项验证：`node --import tsx bridge/tests/pptx-chart-edit.test.ts`；`npm test -- src/slides-native-chart-edit.test.ts`。浏览器 smoke：启动前端 Vite 后运行 `node smoke/pptx-native-chart-edit-smoke.mjs`，可通过 `SMART_REPORTING_URL` 指定地址。

本次验证：bridge 4 项、前端 5 项通过；Chromium 独立对话框 smoke 已通过。该 smoke 验证 Vite 模块的真实浏览器交互，不替代完整应用的保存与重开验收。

2026-11-11 增量：已接入图表标题、双轴标题、图例、数据标签和网格线，继续沿用上述
安全来源、草稿及保存链路。新增真实构建浏览器验收覆盖数据/类型/元素合并、刷新、
实际下载和修订2重开；范围、证据和尚未接入的 Chart Design 能力详见
[图表元素专项验收](NATIVE_PPTX_CHART_STYLE_ACCEPTANCE.md)。
