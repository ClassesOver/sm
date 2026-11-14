# XLSX 图表系列、坐标轴与交互命令增量盘点

日期：2026-11-13。固定源：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。范围为固定源 Ribbon / 图表面板中与系列、坐标轴及画布元素操作相关的命令；不代表完整 Excel 图表、格式或渲染对齐。

续批已补 Scatter 的 `scatterStyle`、系列线色/宽度、`noFill` 与 marker `none` 的读取和 Canvas 绘制。真实 XLSX 导入四张图，红色 4px 折线、无连线、绿线无 marker 及 marker-only 均有实际 Canvas 与点击命中证据；marker 首击 series、次击 point，marker:none 的线点击保持 chart，与固定源无折线 onClick 一致。301 个实载 JS/CSS 响应 SHA 匹配同一冻结目录，草稿前后为空、0 保存、0 planner，见[修订视图／图像／散点图续批](NATIVE_REVIEW_IMAGES_SCATTER_ACCEPTANCE_20261113.md)。单点配色能力保留；smooth/dash、两轴网格线、显示单位、轴标题和全局标签没有因此全部关闭，详见[下一批视觉缺口](NATIVE_XLSX_SCATTER_VISUAL_GAPS_20261113.md)。

## 固定源入口

- `apps/sheets/src/renderer/ExcelShell.tsx:135–200,2064–2284`：选中图表时显示 Chart Design；包含 Add Chart Element、Quick Layout、Change Colors、图表类型、分组、Select Data、Switch Row/Column、Format Pane、Delete。
- `apps/sheets/src/renderer/ribbon-actions.ts:281–388`：命令以所选图表的 `chartPath`（临时对象用 id）为目标；分发类型、图例、标签、分组、配色、布局、标题、轴标题、行列切换。
- `apps/sheets/src/renderer/ChartPanels.tsx:148–364`：Format Pane 的系列/点颜色、单点分离、标题、图例、标签、标签格式/位置、主网格线、值轴最小/最大、分类间距、饼图分离和圆环内径。
- `apps/sheets/src/renderer/ChartPanels.tsx:366–600`：Select Data 的系列名、数值/分类引用、添加/删除/排序、Switch Row/Column；bar+line 组合图还逐系列选择 plot 与 secondary axis。
- `apps/sheets/src/renderer/WorkbookVisuals.tsx:750–782,1879–1891,2143–2360`：chart/title/legend/axis/series/point 身份、系列到点的连续点击选择、画布右键菜单及上下文命令。

## 本地差异

路径均相对仓库根 `smart_reporting/`。

| 命令族 | 本地落点与限制 | 现有证据 | 盘点结论 |
| --- | --- | --- | --- |
| 插入、类型、标题/轴标题、图例/标签 | `report_editor/frontend/src/workbook-ribbon.ts` 暴露上下文命令；`workbook-main.ts` 将目标绑定到当前 worksheet 与 chartPath，走 `applyChartEdits` 和 NativeDraft。图表类型入口限 column/bar/line/area/pie/doughnut；创建入口另支持 scatter/radar/combo。 | [图表插入验收](NATIVE_XLSX_CHART_INSERT_ACCEPTANCE.md) 覆盖创建和写回回读；[图表选择/预设验收](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md) 覆盖所选图表身份、绘制、撤销、真实保存/下载/重开。 | 已有实际链路；不把初始单图/静态面板测试当成闭环依据。桌面 Excel 未验。 |
| Select Data：普通系列 | `workbook-chart-data-dialog.ts` 与 `workbook-main.ts`；可编辑名称、数值/分类向量引用，添加、删除、重排并切换行列。读取限定同工作簿的一维范围、每向量最多 1000 格；新增行最多 24 条。 | [Select Data 验收](NATIVE_XLSX_SELECT_DATA_ACCEPTANCE.md) 有 4→5 一次保存、下载、重开、173 个资源及零保存重开续验。 | 已验证范围内通过；非向量、外部工作簿和超限范围明确拒绝。 |
| Select Data：组合系列与次轴 | `workbook-chart-data-dialog.ts`、`workbook-chart-switch.ts`、`xlsx-engine/src/chart-edit.ts` / `chart-read.ts` 支持逐系列 bar/line 与主/次轴选择、重排、转置、回读及 writer 分组；当前只重建 bar+line 组合。 | [组合图 Select Data 验收](NATIVE_XLSX_COMBO_SELECT_DATA_ACCEPTANCE.md) 有一次真实 HTTP 保存下载重开和独立 openpyxl/lxml/ZIP 回读。 | bar+line 子集已有闭环。三种以上 plot、3D、scatter 混合及其它复杂组合不支持重建，失败关闭。 |
| Format Pane 与轴参数 | `workbook-chart-format-pane.tsx` 按图表身份写入 `applyChartEdits`；已接源面板的系列/点颜色、标题、图例/标签、标签位置/格式、网格线、主值轴界限、间距、饼/圆环参数。Chart Design 另有标题和分类/数值轴标题命令。界限控件编辑主值轴；没有独立次值轴控件。 | [格式控件验收](NATIVE_XLSX_CHART_FORMAT_SOURCE_ACCEPTANCE_20261113.md) 有真实下载文件独立回读、Undo/Redo、浏览器图表选择及定向 reader/pane/host 验证；[轴专项索引](NATIVE_WORD_XLSX_CURRENT_GAPS.md) 另列已做的数值/类别轴视觉验收。 | 固定源面板的控件子集已接；不等于全量轴对象格式。散点/雷达轴标题的本地操作入口会拒绝。 |
| Quick Layout、Change Colors、分组 | `workbook-chart-presets.ts` 与 `workbook-ribbon.ts` 在所选图表上下文提供四套布局、五套颜色；`workbook-main.ts` 将其作为 chart edit 写入。分组目前由格式面板选择。配色限制为最多 24 系列/64 饼环分类。 | [选择/预设验收](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md) 有真实浏览器配色、布局、撤销、保存下载重开及独立 XLSX 回读。 | 已验证所列预设；不外推全部源图表布局、图表样式库或无限系列配色。 |
| 画布内元素点选 | `workbook-chart-selection.ts` / `workbook-chart-element-hit.ts` / `workbook-chart-object-interaction.ts` 将选中图表绑定到身份并将坐标交给 `chart-render.ts` hit regions；Scatter 可见 x/y 刻度点选、Radar 可见外围分类标签点选；Line marker/线段和 Area 填充区系列命中、系列到数据点缩窄及 Format Pane 目标下拉均已接。 | [选择/预设验收](NATIVE_XLSX_CHART_SELECTION_PRESETS_ACCEPTANCE.md) 真实双击选择图表及上下文操作；本轮 Scatter/Radar 鼠标结果见 `/tmp/workbook-axis-hit-browser-source-scale-20261113/evidence.json` 及 `/tmp/workbook-radar-browser-20261113-run7/evidence.json`。Line/area 独立真实单击：line segment 中点→series、marker 首击→series/再击→point、area fill 内部→series；Radar 新冻结验证 primary 13 类别截断为 12、第二系列 15 槽不绕圈、四圈可见、polygon 内点击选中 series、外围值环区域保持 chart，草稿前后均为空，未保存。Chromium 157.0.8103.38，Radar 299 个 JS/CSS 响应逐个与隔离构建磁盘 SHA 一致，零 HTTP/page/console 错误。原始证据：`/tmp/workbook-line-area-hit-20261113c/evidence.json`、`server.log`、`http-evidence.json`、`line-segment-selected.png`、`line-marker-point-selected.png`、`area-fill-selected.png`、`/tmp/workbook-radar-browser-20261113-run7/radar-12-axis-rings.png`。 | 本轮关闭 Radar 类别上限、系列槽对齐/clamp、四圈静态绘制及 polygon/外围值环命中证据；不代表完整 Radar 视觉/格式对齐：固定源值环没有 onClick，本地也不将其伪装成值轴；run7外围点仅为无遮挡区域；后续root的run11已直接点击捕获的可见环顶点，精确范围见下方续验。Scatter 的 clamp/reversed 差异及实际导入漏读两条数值轴已由[续批记录](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)的源码修复、OOXML 和严格浏览器验收关闭；displayUnit/gridlines/lineStyles 等仍未覆盖。完整图表视觉/格式对齐仍未验。 |

## 真实缺口与证据边界

scatter/radar 可见轴直接点选及 line/area 线段、填充命中已由真实 Chromium 单击坐标、目标身份及草稿不变验收关闭；marker 首击系列、再击数据点的优先级也已实测。本次未执行保存回读，因为选择轴/图元不应产生草稿。轴的完整格式/比例等效和其它保留视觉差异不随点击验收关闭。

以下内容保留为范围限制或证据空白，不计作已关闭：固定源 UI 可见命令的每个选项未全部逐项做最终浏览器验收；复杂组合图不在当前 writer 形状；图表格式样式和 OOXML 手工/复杂扩展并未穷举；桌面 Excel 的布局与无损往返未验。既有专项中未跑的失败尝试不作为产品行为证据，本盘点也未重跑测试或构建。

## root精确环线鼠标续验

`/tmp/workbook-radar-browser-20261113-run11` 使用相同Radar冻结manifest `441a2552065922f7cd0236fd31315721c9b2e9ac5a5e0a33c7855f9ee1ac959a`。探针捕获真实Canvas环线顶点及离屏画布到可见画布的drawImage变换，不凭截图估计坐标：四层半径为37、74、111、148px；直接点击外环顶点 `(574,309)` 后Format Pane目标为chart。系列内部点 `(537,417)` 命中series:1，距中心54.49px、距最近marker20.77px，排除了中心小圈或marker命中造成的假通过。两张截图分别保留系列和chart目标，root目视核对；299资源SHA匹配、草稿前后空、保存/planner为0，page/console/HTTP错误为空。

run8–10保留探针失败，原因是离屏Canvas没有DOM尺寸、随后原始画布坐标没有换算到可见画布；这些不是产品命中失败。run7原始JSON不追溯修改。最终smoke已清除错误的冗余标签hook，JS语法检查通过。新续验关闭直接无遮挡环线鼠标证据，不外推环线上覆盖系列时的优先级、样式修改、保存回读或全部Radar视觉。
