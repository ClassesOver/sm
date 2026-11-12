# XLSX 常见图例读取与画布验收

日期：2026-11-12。范围为本表数值引用的 bar/column 自动图例：四侧位置、无图例、名称和显式RGB系列色。不是完整图表版式或所有图例结构验收。

## 原始依据与问题

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/tests/chart-legend-swatch.test.ts` 与 `WorkbookVisuals.tsx` 明确要求非折线图图例使用实际系列填色。源图表编辑协议及本地 writer 早已保存 legendPos，但本地 chart-read 没有投影图例，画布也不绘图例；系列名称可能直接读成单元格引用字符串，显式系列色同样未进入画布。

本轮从实际writer生成的OOXML、独立ZIP/lxml与openpyxl源值，以及最终浏览器像素入手，不以按钮存在或XML已写出认定显示闭环。

## 实现与边界

- `chart-read.ts` 投影图例位置、overlay与隐藏条目原始索引；保留源系列index、显式RGB fill、nameRef/nameCache。旧name字段语义保持，避免破坏已有切换行列等调用。名称查询限定在tx，颜色限定在系列自身spPr的填色，不能从点色或线色偷取。
- bar/column画布新增四侧图例与RGB系列色；色块和条形走同一颜色解析。非overlay预留绘图区，overlay在条形之后绘制。源文件无legend不凭多系列数量臆造图例；支持现有空legend默认右侧。
- 同表单格名称引用读取实际当前网格，可包含引号、撇号和叹号；字面名即使看起来像地址也不当成引用。外表/外部/不可解析引用只回退源缓存或明确的通用系列名，不读取当前表的同地址伪装成目标，不访问外部数据。
- 常见规范编号的隐藏项只隐藏图例，不删除数据条形。**非连续系列编号与图例例外同时出现时，不猜映射、不走本轮自动图例绘制**；原图表及源部件保持，完整排序/例外映射仍开放。[Microsoft公开ISO条目](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.charts.index?view=openxml-3.0.1)说明只能确认idx依赖父上下文，未据此宣称已经独立核实复杂映射。
- 长名称截断并显示省略号，过多条目显示“… +N”，绘制裁剪到图例边界。这里只实现有限自动布局，不声称与源或Excel逐像素一致；右上、overlay和隐藏项/溢出为组件合同证据，四侧/none另有实际浏览器证据。

## 定向验证

| 层次 | 结果 |
| --- | --- |
| OOXML读取 | 新chart-legend-read最初6 failed/1 passed；最终与既有chart-read共 **11 passed**。覆盖四侧/none、默认右侧、名称引用与缓存分离、转义、原始索引/隐藏项/overlay，以及点色/线色隔离。 |
| 画布/调用兼容 | chart-render、chart-legend、chart-add、chart-switch共 **28 passed**。真实注册扩展的四侧/右上、共同色块颜色、不与条形重叠、overlay顺序、空数据仍有源图例、名称解析、隐藏边界、溢出和原有正负/空值几何均覆盖。 |
| AI回归 | 新桥接bundle下test_workbook_ai_charts.py **45 passed**，真实Agno工具、Node预览、显式采纳与人工草稿保全通过。未重跑完整项目测试。 |
| 构建 | 引擎两级tsc、bundle:bridges通过；最终完整前端tsc/Vite **45.56s**（heap4GiB）、全部JS预算通过，阈值不变。为增加复杂索引保守边界做了最终重建，首轮54.56s不是最终冻结构建。新Python Ruff、JS语法和diff检查通过。 |

引擎dist为忽略产物，仅本地按当前源重建用于验收；发布仍需正常从新源码构建，不能沿用旧CLI bundle。

## 真实浏览器与独立像素

旧冻结资产RED：`/tmp/workbook-chart-legend-browser-20261112-red/failure.json`，实际没有应绘制的Live Revenue图例。已有font06下载/重开截图再经新底部图例检查，也因色块数量0失败，日志 `/tmp/xlsx-legend-reopen-red.log`；不把历史“XML有legend”算作历史画布通过。

最终冻结构建下三条浏览器链：

1. `/tmp/workbook-chart-legend-browser-20261112-final/summary.json`：独立源有右/下/左/上/none五图，源名称引用缓存故意为STALE，实际B1为Live Revenue。原生11px Canvas绘制调用确认使用Live Revenue与Costs & tax，不使用STALE。Pillow从最终截图恢复图框、绿色/红色色块与条形，ZIP/lxml核源位置、颜色、引用，openpyxl核源值；各图4根条形，四侧各2个匹配色块，none为0，图例文字有墨迹、位置与预留空间正确。
2. `/tmp/workbook-chart-geometry-browser-20261112-legend-final/summary.json`：原有混合正负/空值/零值3图继续为5/5/0色块，标题墨迹38/57/39、网格表头460。该几何夹具明确设置legend=none以隔离条形断言，不在产品中覆盖源图例。
3. `/tmp/workbook-ai-charts-browser-20261112-legend08-final/summary.json`：人工加粗、AI明确采纳、UndoRedo、放弃删除、再次采纳、修订4→5→6、实际下载与重开通过，标题/表头墨迹及原数值/引用/另一图XML字节保持。额外对实际下载和重开图做独立检查 `independent-legend-reopen.json`，修订5底部图例确实有1个色块，不能只靠保存XML中的legendPos=b。

第三条使用真实路由/授权/Agno工具/Node writer/publication，provider为ScriptedModel，仓储为有作用域内存夹具，不算真实provider/生产DB整链。两次保存仍返回业务/完整版式待复核并签发下载链接。

三条均Chromium140.0.7339.16、显式Canvas字体预检通过，各169份实际JS/CSS与冻结磁盘SHA一致，运行错误数组为空；根任务再次独立核对全部资产并查看实际截图。

| 身份 | SHA-256 |
| --- | --- |
| 最终manifest | `4245e3d96a36f6bc1ceefa9df5641f9950be0fe377797d8cb97de08ec50c58c4` |
| 五图源文件 | `dcfc04dc0dc032b956d91cdb53c16c87e94e28fe764a70d4c74b4f6ee46986a6` |
| 修订5下载 | `f9ebc5b16b6a56bc5231234ffdc18deaf512cfd3cea534b14f7e2f933b7ab385` |
| 修订6下载 | `3c7aa2aa9dd932698e45cfcc2ace984e8334a5f1d3a56287da74c1aa7a6fc745` |

复现：给workbook-chart-render-smoke.mjs设置WORKBOOK_CHART_RENDER_CASE=legend、新输出目录、冻结静态目录及显式FONTCONFIG_FILE；geometry模式保持原几何夹具。当前冻结资源为 `/tmp/workbook-chart-legend-static-20261112-final`。

仍缺饼图/折线/组合等图例、手动布局与复杂图例条目排序、主题/点色/noFill等完整颜色语义，以及轴/数据标签/堆叠/百分比/跨表数值和完整字体度量。未部署或开启生产开关，两个PDF WIP stash保持原样。

后续常见bar/column轴标题已限定补齐并通过保存重开像素检查，见 [轴标题专项](NATIVE_XLSX_AXIS_TITLE_CANVAS_ACCEPTANCE.md)；刻度/数值范围和其它轴能力仍未关闭。
