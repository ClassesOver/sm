# XLSX 散点图视觉差异（2026-11-13）

本文对照固定 GenOffice 提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，保留初始只读调查，并跟踪后续实现与验收边界。

## 2026-11-14 当前状态

图表根级 `value/none` 已接入 reader、格式面板、writer 和 Canvas，注释边界的重复插入／漏删已修复。真实保存、HTTP 下载与原 r5 重开均已完成；此前丢失的原保存响应仍明确记为缺失，未补造。

本轮进一步按 Scatter plot 的 axId 与 reciprocal crossAx 定位 X/Y，补齐轴标题、独立网格、显示单位缩放、Y 单位标签及对应刻度格式。既有轴对话框已开放 Scatter；编辑保留另一轴及非目标 ZIP 部件。数据点 clamp 原先已有，并非本轮新增。标签顶部及左右宽度预留已补齐，长数值标签在实际图框内。

验证分层：engine 专项 36/36；相关 7 文件 110 过、1 个修改前 baseline 已复现的失败。冻结 v1 相关前端 4 文件 171 过；右端修正后 renderer 133/133，最终 reduce 形式仅跑 3 项 margin 定向检查。最终 TypeScript、Vite 和原体积预算通过。唯一真实保存 r4→r5 仅改变 chart1.xml，其他 13 parts 保持，两 chart XSD 通过。最终 v2 使用同一个原 r5 零保存续验，314 GET/0 POST，301 个资源与 320 个后端模块哈希独立核对，六标签的 advance/ink 四角均处于实际图框内。不能将 v1 保存场景冒称最终 v2 再次完整保存。

`validation.ok=false / native_source_review_pending` 原样保留且下载正常；技术检查不等于业务事实及完整版式验收通过。

当前仍需补齐：

1. 固定源 Rust reader 在没有根标签或根模式 none、首个 series 有标签时回退首 series，本地尚未实现。
2. 图表级 `dataLabelStyle` 的颜色／字号继承，目前仍使用默认 9px／#888。
3. 完整轴文字样式、富文本／主题，以及复杂多 plot／次轴来源仍需核验。固定源未应用的反向坐标、顶部／右侧布局或 X 单位标签不列为必须新增功能。
4. 四格式整体、完整 AI 工具、真实生产 provider 同链及持久恢复仍未验收完成。

完整证据保留于外部 `office-scatter-axes-20261114/RESULT.md`。以下为接线前历史调查，当前状态以上述内容为准。

## 当前链路

- `xlsx-engine/src/chart-read.ts::axesOf` 会按 Scatter plot 中两个 `<c:axId>` 的声明顺序，把对应 `valAx` 映射到 X、Y 轴记录；读取各轴标题、数字格式、最小/最大值、主刻度、隐藏状态、方向和位置。
- `designOf` 与图表级 `plot` 选择逻辑没有包含 `scatterChart`。因此 plot 级 `c:dLbls` 不会进入 `ChartReadSpec.dataLabels`，设计级网格线读取也没有 Scatter plot 上下文。`seriesOf` 会读取每个 series 的 `c:dLbls` 并写入 `series.dataLabels`。
- `grid/chart-render.ts` 使用两轴的范围、主刻度和数字格式绘制 Scatter 刻度，但没有为 Scatter 调用 `paintAxisTitles`、绘制任一坐标轴的网格线，或调用 `paintLineDataLabels` 绘制散点值标签。已读取的 series 级标签因此没有进入 Canvas。
- `chart-add.ts` 能生成 plot 级 Scatter 数据标签和数值轴主网格线。`chart-edit.ts` 的可编辑标签 plot 匹配器未包含 Scatter，因此不能编辑标签模式、位置或格式。坐标轴标题和网格线编辑使用首个 `catAx`/`valAx`；Scatter 使用两个 `valAx` 且没有 `catAx`，通用编辑不能正确定位语义上的 X、Y 轴。`setValueAxisBounds` 和 `setGridlines` 也只选择首个数值轴；本地 Scatter writer 输出中该轴是 X 轴。

## 固定源行为

`WorkbookVisuals.tsx::ScatterChart` 使用 plot 级 `dataLabels="value"`，并按各 series 数字格式绘制非空数据值；不处理 series 级 `dLbls` 或单点标签覆盖。Y 轴通过 `VerticalAxis` 绘制网格线，除非全局 `gridlines` 明确为 false；X 轴仅在 `xAxis.majorGridlines` 为 true 时绘制网格线。X、Y 刻度分别使用本轴数字格式和显示单位除数；Y 轴标题旁还会绘制显示单位标签。两个轴标题都会显示。数据点坐标会限制在绘图区边界内，不根据轴方向反转坐标。

全局 value 标签的具体位置为点位正上方 8px、水平居中，未设置 `dataLabels` 时不显示。Scatter renderer 不消费 `dataLabelPosition` 或 `dataLabelFormat`；源 Format Pane 的格式控件与 renderer 实际使用 series `numberFormat` 的行为并不完全一致，不能仅按控件存在扩展可见行为。本地 Format Pane 的 `canLabel` 也排除了 Scatter。最小下一子项可独立补 reader 的 Scatter plot 匹配、renderer 的固定上方标签、面板 value/none 入口与 edit writer 的 `LABELABLE_PLOT_PATTERN`，不扩展位置或 series/point 标签；需分别验证读取、绘制、控件和写回，本文仍无该子项实现或测试通过声明。

## 最小后续范围

在图表读取模型中按语义保留 X、Y 轴属性：各轴分别保存主网格线和显示单位除数/标签；已有设计级网格线字段应明确映射到 Y 轴/全局行为。读取 Scatter plot 级数据标签，再按 series 数字格式绘制全局数值标签，并根据对应字段绘制轴标题、X 轴和 Y 轴网格线。固定源 renderer 不处理 series/point 级 `dLbls`，本轮不扩展这部分。编辑坐标轴标题、网格线和值范围时，应依据 Scatter plot 声明的轴 ID 定位，不应默认使用 XML 中首个轴或 `catAx`/`valAx` 类型。

参考文件：`reporting/workbook_engine/packages/xlsx-engine/src/chart-read.ts`、`src/chart-add.ts`、`src/chart-edit.ts`、`report_editor/frontend/src/workbook-vendor/grid/chart-render.ts`、`grid/chart-data-labels.ts`，以及固定源 `apps/sheets/src/renderer/WorkbookVisuals.tsx` 的 `ScatterChart`。
