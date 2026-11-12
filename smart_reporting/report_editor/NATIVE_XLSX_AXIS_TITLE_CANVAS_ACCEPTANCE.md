# XLSX 柱形与条形图轴标题验收

日期：2026-11-12。范围是单一、可信轴配对的bar/column标题读取及画布显示；不等于完整坐标轴、刻度、数值范围或数据标签对齐。

## 原始依据与实际缺口

固定GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/src/renderer/WorkbookVisuals.tsx`、BarChart/AxisTitleTexts：横向图以category为左侧标题、value为底部标题，纵向图相反。本地writer已有axisTitles写入，但chart-read未投影轴标题，画布因此无法显示。

另有独立读取bug：原titleOf搜索全图第一个c:title，没有图表主标题时会把坐标轴标题提升成主标题。本次通过真实writer生成OOXML后移除主标题，先复现再修复，未用截图文字缺失推测读取原因。

## 实现与保留边界

- 主标题查找限定在plotArea之前。轴文本限定在对应axis/title/tx，读取rich runs（含xml:space和转义）或strRef及其缓存，避免跨轴/主标题串读。
- 只为单一bar plot的两条实际axId投影轴：UInt32身份、唯一分类/日期轴与数值轴、互相crossAx均需匹配。更早的未引用轴不被误选；重复身份/不匹配交叉引用/多plot不猜配对，缺省省略该投影，原图和文件保持可读。
- 读取hidden和位置。c:delete存在但无val按true处理；隐藏轴不绘制/预留标题带，数据条形保留。轴标题不存在或明确移除时不臆造标题。
- 沿用源的分类/数值角色与图形方向；接受对应维度的top/right相反侧位置。旧writer为横向图仍写b/l时，按语义角色规范到左/底，而非把分类与数值维度互换；这不是任意手动轴布局支持。
- 标题使用24px独立带、旋转、测量截断与裁剪，图例先预留空间，再预留轴标题空间。使用当前可信同表单格标题引用；外表/不可读引用只回退原缓存。同表明确空单元格隐藏标题，不复活过期缓存，该修复也适用于共享的图例文字解析。
- 未改writer及发布签发链。已有axisTitles候选使用同一授权、引擎预览和显式采纳流程；此次只是让实际保存的常见轴标题能读回并正确显示。

## 测试与构建

| 范围 | 结果 |
| --- | --- |
| 读取RED | 新8项最初6 failed/2 passed，包括缺失主标题被提升的真实bug。 |
| 读取GREEN | 新轴8项+图例/既有读取11项共 **19项分批通过**。首次GREEN有1个fixture的JS替换字符串误把$D$1当成捕获组；改用函数替换后单独复验该项通过，未改产品迎合坏fixture。 |
| 画布/调用 | 新标题前3项先失败；最终渲染/文字 **28 passed**，加上未受影响的图表创建/切换 **7 passed**（同批分开运行，合计35）。含方向、隐藏、top/right、空引用、长标题裁剪与既有图例/正负/空值几何。 |
| 实际桥接AI | 最新Node bundle下test_workbook_ai_charts.py **45 passed**，完整草稿与明确采纳、身份/参数边界保持。 |
| 构建 | 引擎两级tsc和bundle通过；完整前端tsc+Vite **49.76s**（heap4GiB）、全部JS预算通过，阈值不变。新Python Ruff、JS语法与diff检查通过。未重复完整项目测试。 |

## 真实生产资产与独立像素

旧冻结资产RED：`/tmp/workbook-chart-axis-browser-20261112-red/failure.json`，缺少Quarter轴标题；保留现场，不反推旧版本显示通过。

最终构建三条浏览器链均通过显式Canvas字体预检，Chromium140.0.7339.16，各169份实际JS/CSS与冻结磁盘SHA一致，错误数组为空；根任务再次逐份核验并查看实际图像。

1. `/tmp/workbook-chart-axis-browser-20261112-green/summary.json`：独立openpyxl/ZIP/lxml核源数据、物理位置、隐藏标记和标题引用；捕获实际Canvas文字证明Group来自D1而非OLD GROUP缓存，DO NOT DRAW不绘制。Pillow从最终截图恢复图框/条形，分别检查旋转与水平标题带、主标题空白区；未采用renderer返回的文字坐标作像素结论。
2. `/tmp/workbook-chart-legend-browser-20261112-axis-regression/summary.json`：四侧/none图例回归通过，各图4条形、2/2/2/2/0图例色块，名称和系列色保持。
3. `/tmp/workbook-ai-charts-browser-20261112-axis09/summary.json`：ScriptedModel真实工具候选请求axisTitles，实际预览/明确采纳/UndoRedo/保存4→5→6/下载/重开通过。独立XML确认Quarter/Amount (USD)，实际修订5重开截图分类轴/数值轴墨迹69/96像素、底部图例1色块；原值/引用/人工加粗及另一图XML字节保持。真实路由/授权/Node/publication，修订仓储为有作用域内存，不能计真实provider或生产DB整链通过。

| 轴标题截图场景 | 旋转标题墨迹 | 水平标题墨迹 | 数据条形/图例 |
| --- | ---: | ---: | --- |
| column默认角色 | 116 | 61 | 2/0 |
| bar默认角色 | 69 | 96 | 2/0 |
| top/right、无主标题 | 43 | 93 | 2/0；主标题带无墨迹 |
| 隐藏数值轴、同表标题引用 | 35 | 0 | 2/1；隐藏标题无墨迹 |

上述为固定夹具的存在性及位置检查，结合实际绘制调用和源字节核验，不是OCR或任意文字逐像素排版证明。保存仍诚实返回业务/完整版式待复核并签发下载，不标记验收通过。

冻结资源 `/tmp/workbook-chart-axis-static-20261112`，manifest=`18e63f874929c62589a18ab87a021935ac2c84bfb119f92b653d2627bb49e3eb`；轴夹具源SHA=`cf7536864270896ebe709a8ff66404cdd3dcdb40134dcf22d3b4d979db7e2bf5`。修订5下载SHA=`a2bf8156eeed939b220e6184216eb1763cc6a54adea205ae0b5a06bd74e4ed0d`；修订6=`e5579f0d154b598a3f7e52d270858b8af87dd7ce29ea3a01882a7629c276ca15`。

复现：workbook-chart-render-smoke.mjs设置WORKBOOK_CHART_RENDER_CASE=axis、新目录和冻结资源；AI保存脚本另设WORKBOOK_AI_CHARTS_AXIS_TITLES=1。两者沿用显式FONTCONFIG_FILE，输出目录不覆盖历史结果。

仍缺轴线/刻度/数值及对数范围/显示单位、复杂样式/手动布局、次坐标轴/组合图、数据标签、跨表数值和完整字体度量。本次日期轴只有读取合同，不算日期刻度/布局通过；不把保守省略不可信配对算作支持。未合并部署或开启生产开关，原两个PDF WIP stash保持原样。
