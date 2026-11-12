# XLSX 数值标签字号、RGB、加粗与写回保留验收

日期：2026-11-12。范围限于普通bar/column显式value标签的常见txPr属性和非none全局标签编辑的保留行为；不关闭完整标签样式或复杂图表。

## 原始依据和实际缺陷

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `WorkbookVisuals.tsx::labelTextStyle` 与 `chart-label-style-format.test.ts` 明确使用color/size/bold；`chart-text-scale.ts` 的 PT_TO_PX 为4/3，SVG逆缩放保持实际点字号。本地此前统一11px/默认颜色，布局高度也固定12px，无法呈现源字号或正确判断大字能否放下。

另从实际writer输出发现：setDataLabels重建整段plot dLbls会丢掉txPr和点级覆盖；setDataLabelDetail的首次numFmt/dLblPos查找也可能误改嵌套点属性。只读对齐还不足以保证下一次改图/保存后字体不丢失。

## 本批实现与范围

- reader保留显式字号（sz的百分之一pt）、b和纯RGB文本色；单一defRPr优先，没有时可用单一endParaRPr后备。缺失字段与b=0/false分开，空样式不清空父级属性。无效数值、权重、未解析的主题色和颜色变换标为不支持，不用默认RGB冒充已解析。
- 画布逐属性合并plot/series/point样式；12pt对应16 CSS px，显式取消加粗有效。用选中的真实Canvas字体测量宽度和actualBoundingBoxAscent/Descent，再计算包围框、居中/端点位置及碰撞；指标缺失时才使用字号相关的后备高度。放不下的72pt不裁出一部分数字。
- writer复用现有SaxesParser定位标签的直属子节点，按schema顺序只替换请求属性，保留其它节点原始字节。全局showVal/模式/格式/位置编辑不再删除根字体、点级格式/位置/字体或扩展。保留现有mode=none显式移除plot标签块的行为，不声称关掉再开启还原全部旧属性；Undo仍基于原件重放。
- 字体族、斜体/下划线/描边、复杂富文本/多段、主题/变换色、完整sourceLinked实时单元格样式与任意字体度量仍开放。本批主要是单层常规文本的三个显式属性；不能把部分字体属性看作完整排版保真。实际浏览器为100%缩放，其他缩放未在本批重新验收。

## 定向验证

| 范围 | 证据 |
| --- | --- |
| RED | 字体读取/写回最初8项失败；实际注册画布的3项字体测试先失败，原59项仍通过。 |
| 引擎GREEN | 字体/字节保留10、既有读取50、改图写入16，**76项分批通过**。含显式false、后备样式、非法字号/权重、空配对RGB、主题/alpha边界；原字体/point字节、带原生>条件的点格式、自定义Unicode文字与扩展保持。 |
| 前端GREEN | 实际扩展62、数值15、类别引用3、图例文字3、创建4、切换3，**90项通过**。验证12pt→16px、RGB、逐属性继承、b=false和过大字体不绘。 |
| 真实CLI桥接AI | 修改writer并重建bundle后 `test_workbook_ai_charts.py` **45 passed / 40.97s**，未重复完整项目测试。 |
| 构建 | 引擎两级tsc/bundle、完整前端tsc/Vite **49.56s**、全部JS预算通过，不改阈值；Ruff、JS语法、diff检查通过。 |

## 真实浏览器与独立检查

最终冻结目录 `/tmp/workbook-chart-label-style-static-20261112`，manifest SHA=`dbaf313203f133f0f3172f27db1c50ea3181d39c8f00fd093aaceccd3b382954`，Chromium140.0.7339.16。三条实际链都字体预检通过，各169份实际JS/CSS与磁盘SHA一致、四类浏览器错误数组为空、原件身份不变。

1. `/tmp/workbook-chart-label-style-browser-20261112-green/summary.json`：默认11px、plot12pt加粗、series/point颜色与取消加粗、未解析主题色、过大72pt、endParaRPr后备9pt红字共六场景。实际Canvas调用被动记录字体和颜色，12pt字体确为bold 16px，系列取消加粗为16px，点9pt为12px，颜色为源90EE90/FFD700/A02040；不注入图表模型或操作。独立openpyxl/lxml核原件数值及真实sz/b/RGB/theme属性，Pillow测量源前景/背景的抗锯齿混合线（alpha>=0.6、RGB残差<=2），恢复字形包围框并核中心/端点。字号增大时像素高度至少增加2px，墨迹增加；相同16px下加粗与取消加粗另比较墨迹。默认11px两标签44/42像素，12pt加粗160/168，系列/点颜色84/52，红字后备82/99；未解析主题和过大字体均为严格0，不算支持这些样式。源RGB/大小/权重和额外墨迹比较补验存 `additional-source-style-verification.json`，根任务已查看整张截图。
2. `/tmp/workbook-ai-charts-browser-20261112-label-style/summary.json`：源文件自带plot12pt白色加粗、单点b=0与0.00格式；真实UI/HTTP/授权/Agno工具/Node writer/签发/下载链执行人工加粗→AI重新设置value、center、0.0及5..25→UndoRedo→候选恢复自动→撤销→保存4→5/下载重开→放弃删除/再采纳→保存5→6/下载重开。独立XML canonical比较确认原plot txPr与整个point块保留，根格式为新0.0、点仍为原0.00；另一图字节、原值/分类/引用与人工格式保持。新修订实际Canvas记录10.0为bold16px、20.00为非加粗16px，另有独立字形中心和140/150对比像素，证明不只是模型回执字段。原范围比例/标题/图例继续成立。provider为ScriptedModel、修订存储为作用域内存，不能算真实provider或生产DB验收。
3. `/tmp/workbook-chart-labels-browser-20261112-style-regression/summary.json`：同一最终构建对原八种标签场景的正负/零、中心货币、反向裁剪原值、点级删除、系列开关、百分比格式、未支持模式和合法空格式分段再验收。原条形数2/2/3/4/4/4/2/4、内容与显式关闭的零墨迹保持；实际字体指标修正后的字形位置也通过独立检查。

字体链原件样式由fixture先写入真实XLSX，AI只改变已有公开标签字段，没有新增虚构的字体写入工具。字体模式/格式编辑保留原节点的单元测试按实际字节比较；浏览器保存则由独立lxml核真实下载，不以截图颜色或DOM样式代替文件写回证明。

复现：图形使用WORKBOOK_CHART_RENDER_CASE=label-style；带源字体AI在AXIS_TITLES=1、VALUE_RANGE=1、DATA_LABELS=1之外设置WORKBOOK_AI_CHARTS_SOURCE_LABEL_STYLE=1。使用新的输出目录、显式FONTCONFIG_FILE及冻结PDF_SMOKE_STATIC_DIRECTORY；保留先前批次现场。

未新增发布/下载门禁或签发后步骤；不部署或开启生产开关。既有PDF与数值轴WIP快照保持。完整标签内容/偏移、复杂继承、字体族和非普通图表等缺口仍未关闭。

六字体图源SHA=`2ec063d1d7ed0d818837a6371719983d4e3d6585d7d1041cefa75c94e804268b`；AI修订5下载SHA=`e25358fd91452ead9a5a1dde6885553ee7b2244aa2da1afaf477a6635d6b3d46`，修订6=`203c0c692cbe3d649f8dd452f2e625717ed5529d0b3d864127dadb3231379b23`。根任务逐份复核实际加载资源与冻结manifest的SHA，原始字体/颜色绘制记录见各model.json及edited-label-font-paints.json。

2026-11-12 标签主题色续批：普通数值标签接通实际主题关系与完整配色的无变换 schemeClr，保留原引用并跟随真实主题切换；47项定向、构建/预算、真实撤销重做与保存下载重开通过。169实际资源身份及独立下载XML/颜色混合像素已核；明暗透明度变换、字体族及复杂标签仍缺，见 [主题色验收](NATIVE_XLSX_DATA_LABEL_THEME_ACCEPTANCE.md)。
