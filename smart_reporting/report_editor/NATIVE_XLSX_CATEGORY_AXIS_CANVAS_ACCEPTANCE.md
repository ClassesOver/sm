# XLSX 类别刻度、空槽与源分类顺序验收

日期：2026-11-12。PR #222 数值轴后的续批，只覆盖可信配对普通 bar/column 的单层分类名称、方向和组内系列顺序，不关闭完整图表布局能力。

## 原始依据和问题

直接读取固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/src/renderer/WorkbookVisuals.tsx`。其 rowSlot/seriesSlot 在水平 bar 默认 minMax 时均为倒序（分类从下往上），maxMin 时恢复正序；column 的 maxMin 则同时镜像分类和组内系列。此前本地始终按从上往下绘制 bar，且没有分类名称，不能仅补文字而留下顺序错位。

另直接读取实际 XLSX 的 cat/cache/单元格/轴方向，未从旧验收文档推导期望。源分类缓存中的 pt idx 和实时空单元格都必须保留位置；过滤空名字后再按数组下标绘制会将后续名称配给错误条形。

## 实现边界

- 读取单层 strCache/numCache/strLit/numLit，保留实际点索引、空槽及 numeric category format；只读取可信轴配对中类别轴的 maxMin。上限10000点；重复/越界索引、无效或过大计数、多层块不扁平化为假分类。无分类块才使用序号；已有但不可读的分类块保留空投影。
- 可信同表一维引用使用实时单元格，包括空值，不用旧缓存复活已清空名称。支持行/列向量、绝对地址、带撇号或感叹号的带引号表名；外表或不可读引用使用原索引缓存，不误读当前表同地址。二维引用不平铺。
- 默认/反向分类和组内系列按源表达式绘制；隐藏类别轴只隐藏名称与空带，不改变数据顺序。缺失数值仍保留分类槽，零值不制造色条。
- 分类带先预留，再绘制数值轴，最后按共同最终绘图区绘分类标签和数据。bar支持left/right，column支持top/bottom，兼容旧writer轴位置与角色。标题、图例和两类刻度各自保留空间。
- 显式类别数字格式复用已有格式化库，验证百分比；长名称带省略符并裁剪，密集类别可抽样显示。只处理单层、均匀分类槽；不声称源换行/旋转/日期比例轴/多级分类/源链接单元格格式继承全部保真。已有虚构的序号不会替代不可读的源分类。

## 定向与独立证明

| 验证 | 结果 |
| --- | --- |
| 有效fixture下先RED | 7项新增分类读取全部失败；实际注册扩展新增8项失败，原40项仍通过。初始fixture漏title造成的测试构造错误已纠正，不把该异常当成功能缺陷证据；有效RED见 `/tmp/xlsx-category-read-red2.log`。 |
| 读取GREEN | 新分类7与原读取34，**41项通过**。覆盖缓存/引用、稀疏乱序、实体解码、数值字面格式、无效/重复/多层边界和真正类别轴方向。 |
| 前端GREEN | 实际注册扩展48、数值15、图例文字2、分类引用3，加创建4/切换3，**75项分批通过**。包含实时空槽、外表缓存、双方向/双类型组序、百分比、隐藏和top/right、特殊表名与二维拒绝。 |
| 原源表达式执行 | `smoke/workbook-chart-category-source-oracle.mjs` git show 固定版本后，在VM执行原 rowSlot/catSlot/seriesSlot 表达式，与本地实际函数比较。两种图、两种方向、1/2/3/4/48分类及3系列，**292/292位置一致**。版本不符或找不到原表达式即失败，不以复制的期望函数替代。原始证据 `/tmp/xlsx-category-source-oracle-20261112.json`。 |
| 构建 | 引擎两级tsc/bundle、完整前端tsc/Vite **44.88s**、所有JS预算通过，不改阈值；Ruff、JS语法和diff通过。未重复完整项目测试。 |

原源排序复现：frontend下执行 `GENOFFICE_SOURCE_DIRECTORY=/path/to/genoffice WORKBOOK_CHART_CATEGORY_ORACLE_OUTPUT=/tmp/category-oracle.json node smoke/workbook-chart-category-source-oracle.mjs`。

## 冻结浏览器与最终像素

冻结目录 `/tmp/workbook-chart-category-static-20261112`，manifest SHA=`94df87912fd1478140d031713a215f05fa642ed6d3ce8570a6bcc6ae14a8a7f2`。Chromium140.0.7339.16；所有成功链均显式字体预检、169份实际JS/CSS与磁盘SHA一致、四种浏览器错误数组为空、原件身份不变。

- `/tmp/workbook-chart-category-browser-20261112-green/summary.json`：六场景为实时bar/实时column/反向bar/顶部反向百分比column/右侧外表缓存及长名称/隐藏类别轴。独立openpyxl/lxml回读源空名称、两系列数值、反向与百分比格式；Pillow恢复最终图框与完整色块，按源分类索引、源组内顺序及数值比例计算起点/厚度/长度，容差2px。色块数 **6/6/6/3/3/3**，分类墨迹 **116/113/116/79/446/0**；实时空分类位置墨迹严格为0，仍有该槽实际第二系列条形。实际Canvas调用核Alpha/Gamma/Fourth、10%/25%/50%/75%、External A和省略符，不出现STALE；根任务已查看整张截图。
- `/tmp/workbook-ai-charts-browser-20261112-category/summary.json`：真实UI/HTTP/授权/Agno工具/Node writer/签发下载，人工加粗→候选改图带标题与5..25→UndoRedo→候选恢复自动→撤销→保存4→5/下载重开→放弃删除/再采纳→保存5→6/下载重开。独立OOXML确认另一图字节、原值10/20、分类引用Q1/Q2和人工格式保留；像素按源bottom-up顺序逐值核手动1/4、3/4及自动10/25、20/25，分类带包含在绘图区计算中。provider为ScriptedModel、修订存储为作用域内存，不能算真实provider或生产DB验收。
- 同一构建的原几何、手动值域、数值刻度、轴标题、图例回归目录依次为 `/tmp/workbook-chart-geometry-browser-20261112-category`、`/tmp/workbook-chart-scale-browser-20261112-category`、`/tmp/workbook-chart-ticks-browser-20261112-category`、`/tmp/workbook-chart-axis-browser-20261112-category-green`、`/tmp/workbook-chart-legend-browser-20261112-category`。原缺失/零值、反向/裁剪/不支持对数、标题隐藏及图例独立检查继续成立。

轴标题初次回归目录 `/tmp/workbook-chart-axis-browser-20261112-category` 的“隐藏数值标题空区”捕获了新增真实Q1标签边缘的1个像素；脚本现按独立恢复的数据左边界分开分类带与空标题区，仍要求空区墨迹严格0，不放宽阈值。失败现场保留，新目录完整重跑。其他回归脚本按本次明确的bar bottom-up顺序与分类带更新期望，未删除源值/比例/共同零线断言。

六分类图源SHA=`9519cdd23d392a450190cf52fa6ad187741ec05e7beef86cdcdf5a4536b6979f`；AI修订5下载SHA=`287edf3dd8ef377db573d6ac4099b01a47fefb8392d0004cff4dd8c40f793d91`，修订6=`99e2b76bd5bdd1eb2206ec4d9e3912b53c757ed73e0514bff5d7fd11a264be72`。实际截图、模型、独立JSON、文件、HTTP与planner证据在各目录。

复现使用 WORKBOOK_CHART_RENDER_CASE=category；其他专项case保留。每次新目录，沿用显式FONTCONFIG_FILE和PDF_SMOKE_STATIC_DIRECTORY；AI链设置AXIS_TITLES=1及VALUE_RANGE=1。

仍缺多级/日期比例分类、完整换行/旋转/交点/轴属性、数据标签、对数/次轴/组合堆叠、跨表数值及完整字体度量；未改发布下载门禁，未部署或开启生产开关。旧PDF暂存和初始数值轴WIP快照保持。

后续普通bar/column显式数值标签及真实短分类A/B的拟合修复见 [数值标签续批](NATIVE_XLSX_DATA_LABEL_CANVAS_ACCEPTANCE.md)。本文件保留当时分类构建的历史证据，不将其倒算为已验收数据标签或短字形拟合的后续修正。
