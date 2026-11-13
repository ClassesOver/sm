# XLSX 手动数值轴范围与裁剪验收

日期：2026-11-12。范围为可信单一轴配对的bar/column线性min/max、反向数值方向、边界裁剪及恢复本地自动范围；不关闭完整坐标轴或对数轴能力。

## 原始依据与实际问题

固定GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `packages/xlsx-gateway/src/domain/chart-visual.ts::valueAxisScale` 使用显式min/max，`WorkbookVisuals.tsx`及chart-negative-bars测试以真实零线绘制条形。本地已有valueAxis writer，但chart-read未保留scaling；画布无论源min/max是什么，都按本地数据极值与零点计算，保存成功不代表范围在画布生效。

本次从实际writer生成OOXML与独立openpyxl/lxml源值入手，先复现丢失范围和画布忽略范围，再补实际浏览器像素及保存下载重开。

## 实现与明确边界

- 仅从实际plot关联的value轴读取min/max、maxMin方向；数字须是有限十进制/科学计数值，不把NaN、Infinity、空属性、倒置范围或未知方向当成自动。类别轴不混入数值范围。
- 先把零点与各数值夹到可见域，再线性映射，得到裁剪后的可见条形；完全不可见或零长度的条形不虚构1px色条。反向轴改变增长方向，分类槽保留。
- 常规有限跨度使用差值比，溢出跨度再归一化，兼顾MAX_VALUE两端和相邻大数的有限几何；单边界保留另一自动端，必要时推导可表示的有限区间，不能生成有效区间则不伪画。
- null移除边界后回到**本地既有自动范围**。源valueAxisScale的5%裕量、漂亮刻度及完整自动策略仍未迁入，不把本批恢复自动当成源自动布局全部一致。
- 对数或无效范围、显式范围却无法确认轴配对时，保留原件/模型并显示“此数值轴暂不支持预览，请下载原件查看”，不按错误的普通线性比例绘数据。该提示限制在图框内，不引入发布/下载门禁；不能将此降级算作支持对数轴。
- 未改writer、发布签发链或AI权限。现有valueAxis候选仍需整簿授权、真实预览和明确采纳，原数值缓存/引用不被改造为屏幕数据。

## 定向验证

| 范围 | 结果 |
| --- | --- |
| RED | 新范围读取最初8 failed/1 passed；新双方向画布8项全部失败（原26项仍通过）。旧冻结浏览器因范围未投影而失败，现场 `/tmp/workbook-chart-scale-browser-20261112-red`。 |
| 读取GREEN | 范围新10项、先前轴/图例读取19项 **共29项分批通过**，覆盖null移除、单边界、科学计数、反向、无效/对数识别、歧义轴身份。 |
| 前端GREEN | 实际注册扩展、数值映射、文字、创建/切换 **共51项分批通过**：初始相关43项，增加歧义1项及数值helper7项后，受影响渲染/数值42项通过；其余9项沿用同批结果。检查可见长度、反向、范围两端、完全不可见值、全负域、单边界、自动恢复、极端数及信息提示。 |
| 真实桥接AI | 新CLI bundle下test_workbook_ai_charts.py **45 passed**。完整草稿/显式采纳/参数和身份边界保持。 |
| 构建 | 引擎两级tsc与bundle通过；完整前端tsc/Vite **45.95s**（heap4GiB）、全部JS预算通过，不改阈值。Python Ruff、JS语法与diff检查通过。未重复完整项目测试。 |

## 真实浏览器与独立像素

三条最终构建浏览器链均有显式Canvas字体预检，各169份实际JS/CSS与冻结磁盘SHA一致，pageErrors/consoleErrors/httpErrors/assetErrors为空；原件不变。根任务再次逐份核SHA并查看实际截图。

1. `/tmp/workbook-chart-scale-browser-20261112-green/summary.json`：ZIP/lxml核min/max、反向及logBase，openpyxl核真实单元格；Pillow直接从最终截图恢复图框和完整色块。六图条形数为 **2/2/2/1/2/0**：正域2..8、跨零-4..8、反向2..8、低值排除/高值裁剪、全负-8..-2、对数不伪绘。长度与零线位置按源数值独立计算，纯色边缘允许2px误差；被排除第一分类保持空槽，不把第二个值移位。
2. `/tmp/workbook-chart-axis-browser-20261112-scale-regression/summary.json`：柱形/横向角色、top/right、隐藏标题及底部图例像素回归保持，原标题墨迹和数据条形数量一致。
3. `/tmp/workbook-ai-charts-browser-20261112-scale10/summary.json`：真实HTTP/授权/Agno工具/Node writer/publication；手工加粗→AI设置valueAxis=5..25并带轴标题→UndoRedo→真实候选恢复自动null/null→截图→撤销恢复自动→保存4→5→下载/重开→放弃删除/再采纳删除→保存5→6。独立XML确认保存仍为5..25，截图量得10/20条形为绘图区的1/4、3/4；自动预览则为1/2、全部长度，证明不是仅回执字段变化。轴标题/图例、原数据/引用、人工格式及另一图XML字节保持。

第三条provider为ScriptedModel、修订仓储为有作用域内存，不能计真实provider/生产DB链；4次真实planner请求与2个保存修订均核对。两次保存仍诚实返回业务/完整版式待复核并提供下载与新修订。

冻结目录 `/tmp/workbook-chart-scale-static-20261112`，Chromium140.0.7339.16。manifest=`dd6542bc4ac797cae8e685ccb9bc2e3ebdf959f32d51fd2885362d5ae520ccad`；六图源SHA=`29cc503837d70fb4a3a7bab0ac0f6a91cb0c0b23cc0f0f78479a2a51d4493af5`。修订5下载SHA=`284fccb319f8d06a7e98fcf099c752a9fb6fcd49a651ebff1e4c664852ef422e`；修订6=`bd67ce5ce2f85486b060d81d1935caecaf2e8b8273425bb9a8f5f3ce53524f7f`。

复现：图形smoke设置WORKBOOK_CHART_RENDER_CASE=scale；保存链设置WORKBOOK_AI_CHARTS_VALUE_RANGE=1（可同时设AXIS_TITLES=1）。沿用显式FONTCONFIG_FILE和冻结目录，每次新建输出目录，不覆盖失败现场。

仍缺刻度/轴线/数值标签、源漂亮刻度与完整自动范围、对数计算、非零交点/次轴/组合/堆叠/百分比、跨表数值及完整字体度量。未部署或开启生产开关，两个既有PDF WIP stash保持原样。

后续普通bar/column的源自动留白与数值刻度已另批补齐，见 [数值轴续批验收](NATIVE_XLSX_VALUE_AXIS_CANVAS_ACCEPTANCE.md)。本文件保留当时本地自动范围的历史证据，不把旧冻结构建倒算为新算法已验收。
