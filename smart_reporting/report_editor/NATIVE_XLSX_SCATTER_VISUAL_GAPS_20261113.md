# XLSX 散点图视觉差异（2026-11-13）

本文对照固定 GenOffice 提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，保留初始只读调查，并跟踪后续实现与验收边界。

## 2026-11-14 后续：首系列标签回退

已补固定源 root none/absent → first-series mode 的读取／Canvas 投影，并在首系列 value 会使关闭失效时限制 none；value 与其它编辑保持可用。格式窗格／设计对话框均有解释和条件限制，writer 同语义保护预设及 AI。定向测试、真实组件浏览器及独立 XLSX 回读见[回退专项](NATIVE_XLSX_SCATTER_LABEL_FALLBACK_ACCEPTANCE_20261114.md)。仅关闭以下历史第1项的读取差异与无效关闭风险；完整轴样式、复杂来源与生产保存整链仍开放。下面的“当前状态”及候选未实施说明保留为本次之前的历史记录。

## 2026-11-14 当前状态

图表根级 `value/none` 已接入 reader、格式面板、writer 和 Canvas，注释边界的重复插入／漏删已修复。真实保存、HTTP 下载与原 r5 重开均已完成；此前丢失的原保存响应仍明确记为缺失，未补造。

本轮进一步按 Scatter plot 的 axId 与 reciprocal crossAx 定位 X/Y，补齐轴标题、独立网格、显示单位缩放、Y 单位标签及对应刻度格式。既有轴对话框已开放 Scatter；编辑保留另一轴及非目标 ZIP 部件。数据点 clamp 原先已有，并非本轮新增。标签顶部及左右宽度预留已补齐，长数值标签在实际图框内。

验证分层：engine 专项 36/36；相关 7 文件 110 过、1 个修改前 baseline 已复现的失败。冻结 v1 相关前端 4 文件 171 过；右端修正后 renderer 133/133，最终 reduce 形式仅跑 3 项 margin 定向检查。最终 TypeScript、Vite 和原体积预算通过。唯一真实保存 r4→r5 仅改变 chart1.xml，其他 13 parts 保持，两 chart XSD 通过。最终 v2 使用同一个原 r5 零保存续验，314 GET/0 POST，301 个资源与 320 个后端模块哈希独立核对，六标签的 advance/ink 四角均处于实际图框内。不能将 v1 保存场景冒称最终 v2 再次完整保存。

`validation.ok=false / native_source_review_pending` 原样保留且下载正常；技术检查不等于业务事实及完整版式验收通过。

当前仍需补齐：

1. 固定源 Rust reader 在没有根标签或根模式 none、首个 series 有标签时回退首 series，本地尚未实现。该差异不能只改 reader：本地已有 Scatter 标签编辑入口，选择 none 会删除根标签但保留 series；若引入回退，首 series 的 value 会使标签重新显示。须先设计并验证关闭契约，不能将当前专项视为待直接接线的小修复。
2. 更正：固定源 `ScatterChart` 不接收或消费 `dataLabelStyle`，数据标签仅使用 `data-label` class；本地默认 9px／#888 不应因此列作固定源 Scatter 颜色／字号继承缺口。通用 reader 中存在该字段、或其它图族消费该字段，不证明 Scatter 具有此能力。
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


## 2026-11-14 固定源复核与本轮结论

本次基于 `code` 分支 `b65c5e8`（#237）独立工作区，只读复核固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，修正上面两项来源事实。没有修改产品代码、安装依赖、运行测试、接入真实 Codex、推送、PR、合并或部署。

- [WorkbookVisuals.tsx:4726–4928](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/sheets/src/renderer/WorkbookVisuals.tsx#L4726-L4928)：`ScatterChart` 参数不含 `dataLabelStyle`，仅在全图 `dataLabels === 'value'` 时绘制标签，标签没有 `labelTextStyle`。原“颜色／字号继承尚缺”判断撤回，不能借对齐名义扩展非源能力。
- [Rust charts.rs:598–641](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/sheets/native/xlsx-engine/src/visuals/charts.rs#L598-L641)：根模式优先；根为 none 且第一 series 非 none 时回退第一 series；缺根标签也回退第一 series。`delete` 优先 none，percent 与组合模式优先 value。Scatter 只显示最终 value 模式，不能把任意“有标签”简化为 value。
- [chart-visual.ts](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/packages/xlsx-gateway/src/domain/chart-visual.ts)：固定源 `LABELABLE_PLOTS` 不含 Scatter。本地已有 value/none 编辑入口属于需要单独验证的宿主增量，不可用固定源的只读显示事实替代编辑正确性证明。
- 本地 `chart-edit.ts::setDataLabels` 对 Scatter 的 none 仅删除根 `dLbls`，保留 series。`workbook-chart-format-pane.tsx` 与 `workbook-chart-design-dialog.ts` 仍允许选 none；因此简单增加 reader 回退会导致部分来源“关闭后仍显示”。一刀切禁用所有带 series `dLbls` 的编辑同样不正确，会回退根 value、首 series none/percent、仅后续 series 或仅 point 标签等既有可用能力。

若后续继续，候选范围必须重新批准：按请求结果判定，value 保持可用，none 只在保留来源 series 后实际回退为第一 series value 的场景拒绝；UI 明确解释且 writer 同语义保护，其他编辑不降级，并覆盖批处理／预设／AI 入口与真实保存重开。该方案本轮未实施、未测试、未获完整验收，当前产品行为保持原样。
