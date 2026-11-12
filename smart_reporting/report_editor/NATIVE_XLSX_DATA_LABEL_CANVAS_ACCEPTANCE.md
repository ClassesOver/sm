# XLSX 显式数值数据标签验收

日期：2026-11-12。范围限于普通 bar/column 的显式 value 标签、常用位置/格式、系列与点级开关；不是完整数据标签或所有图表类型交付。

## 原始素材与实现

直接核对固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/src/renderer/WorkbookVisuals.tsx`（showsLabel/labelFor/formatLabelValue）、`chart-point-labels.test.ts` 和 `chart-label-style-format.test.ts`，并读取实际 XLSX 的图表/系列/单点 dLbls、showVal/delete、numFmt、dLblPos 及实时单元格。原本 writer 已能写标签，reader/画布未投影，保存字段变化不能证明屏幕已显示。

- 读取plot和series的显式设置，按实际点idx保留覆盖；显示/删除开关、ctr/inEnd/outEnd和XML解码格式进入模型。图表级查找排除series块，点级设置不串到默认开关。重复/未知位置、异常开关/点身份、非value模式、自定义文本或manualLayout标为未支持，不改成普通数字。
- 标签使用实时实际数值，按最终条形增长方向绘制；负数和反向数值轴同时成立。条形越界裁剪时仍显示原始12，不把它改成轴上界8；完全不可见值不伪绘。零值在空间允许时可显示0，仍没有虚构的色条。
- 所有条形先绘制，再绘标签；按实际测量宽度、完整包围框和碰撞检查裁剪到数据区。inside标签须完整容于条形，outside须完整容于绘图区，不截断数字以强行塞入。空间不足、碰撞或超过500个有限数值时可省略，不能算源布局全部保真。
- 显式数字格式复用Univer numfmt，General可回退到已保存的value-cache格式。空格式分段是有意隐藏：`0;-0;;`的零标签和`;;;`的全部标签保持为空。未解析完整实时单元格样式继承；格式库抛错或不返回字符串时回退实际值，不把合法空文本误当错误。
- 文件无标签时不自动开启；固定源对少量单系列图有产品性自动补标签，本地本批按文件显式设置，不能将两者说成相同。自定义文本/偏移、txPr字体样式、sourceLinked实时样式、非数值内容和非普通bar/column家族仍开放。
- 实际截图发现短分类A/B虽放得下，却因省略号更宽被旧fitted辅助函数判为空。修正为先接受放得下的完整文字，再检查省略号；增加真实短分类墨迹正对照。

## 定向验证

| 方法 | 结果 |
| --- | --- |
| RED | 新标签读取8项先失败；注册扩展新增8项失败、其余49项通过（含无空间时不绘的新增对照）；合法空格式2项先失败；短文字1项先失败。初始日志保留。 |
| 读取GREEN | 标签9项与原41项，**50项通过**；包含plot/series/point分界、解码/缓存格式、删除/关闭、重复/未知/非值/自定义边界。 |
| 前端GREEN | 注册扩展59、数值15、图例文字3、类别引用3、创建4、切换3，**87项分批通过**；最后短文字/注册扩展62项在实际修复后再通过，其余25项沿用同批未受影响结果。 |
| 构建 | 引擎两级tsc/bundle、最终完整前端tsc/Vite **48.04s**、所有JS预算通过，不改阈值；Ruff、JS语法、diff通过。因空格式和真实短标签缺陷的新增修复重建最终资产，未重复完整项目测试。 |

## 独立像素方法与失败现场

最终Canvas调用核实际数字内容，独立openpyxl/lxml核原件数值/标签开关/格式/位置，Pillow从最终截图直接恢复图框、完整条形和标签墨迹。inside标签白字的0/8/$可能把蓝色底分成内部小色岛，初版组件算法将其误数为额外条形。现在只有在显式标签专项中，才将完全被同色外组件包围的小组件归入原条形；原始小组件仍保存在 `enclosedColorComponents` 和AI的 `edited-label-color-components.json`，不按“小于某尺寸”删除真实短条。

小字号抗锯齿白字几乎没有纯255像素，初版纯白计数门槛不成立。修正后的已知蓝底标签检查只在色条内缩3px区域取白色混合墨迹（min RGB>180且B>220，蓝底68/114/196不可能通过），要求至少20个对比像素；再量其实际包围框，ctr的中心和inEnd的端点留白分别核对，文字像素位置容差3px。无标签与空格式两种控制条形还要求此检测严格为0。外侧黑字、单点关闭和格式隐藏零的空区仍用深色墨迹>=3/严格0，数据几何容差仍2px。不是通过放宽条形数量或删除原比例断言获得通过。

失败现场保留：`/tmp/workbook-chart-labels-browser-20261112-green`、`/tmp/workbook-ai-charts-browser-20261112-labels` 的初版色岛误计；`/tmp/workbook-chart-labels-browser-20261112-final`、`/tmp/workbook-ai-charts-browser-20261112-labels-final` 的纯白计数不成立。最终使用独立新目录完成全部回执；旧失败不算成功。

## 最终冻结浏览器

冻结目录 `/tmp/workbook-chart-labels-static-20261112-final`，manifest SHA=`1bbbcd8d42fbd94c026d5326239ea01d03dce7b2f02061ba5d1446184677fefb`，Chromium140.0.7339.16。每条最终链均字体预检通过、169份实际JS/CSS与磁盘SHA一致，pageErrors/consoleErrors/httpErrors/assetErrors为空、原件身份不变。

1. `/tmp/workbook-chart-labels-browser-20261112-final-green/summary.json`：八场景为外侧正负/零、居中货币、反向且裁剪的内端、单点删除/关闭/格式、系列关闭/百分比格式、未支持的percent模式、格式隐藏零、格式隐藏全部。条形数2/2/3/4/4/4/2/4，零和空值不制造条形；独立核真实文字位置和被隐藏标签的零墨迹，原12.0、-5.0、$12、200%/400%以及A/B/C/D由实际绘制调用核内容。
2. `/tmp/workbook-ai-charts-browser-20261112-labels-final-green/summary.json`：真实UI/HTTP/授权/Agno工具/Node writer/签发/下载/重开；人工加粗→AI显式value/center/0.0并带轴标题和5..25→UndoRedo→候选恢复自动→撤销→保存4→5/下载重开→放弃删除/再采纳→保存5→6/下载重开。独立OOXML确认showVal=1、ctr、0.0、原10/20与Q1/Q2、人工格式和另一图字节保持；从新修订截图确认居中标签墨迹和位置，手动/自动范围比例保持。provider为ScriptedModel、修订存储为作用域内存，不算真实provider/生产DB验收。
3. 相同最终资产的类别、标题和图例回归分别在 `/tmp/workbook-chart-category-browser-20261112-labels-final`、`/tmp/workbook-chart-axis-browser-20261112-labels-final`、`/tmp/workbook-chart-legend-browser-20261112-labels-final`，保留原单层分类/空槽/方向/数字刻度、隐藏与top/right标题、四侧图例/颜色的独立检查。

复现：图形smoke设置WORKBOOK_CHART_RENDER_CASE=labels；AI链在AXIS_TITLES=1和VALUE_RANGE=1之外添加WORKBOOK_AI_CHARTS_DATA_LABELS=1。每次新目录，沿用显式FONTCONFIG_FILE与冻结PDF_SMOKE_STATIC_DIRECTORY，不覆盖失败现场。

仍缺完整标签字体/填充/引导线、文本/分类/占比标签、手动偏移、完整实时格式继承、复杂继承边界、多级/日期比例分类、完整轴属性、对数/次轴/堆叠组合及跨表数值；本批仅验收普通线性bar/column。未改发布下载门禁，未部署或开启生产开关；既有PDF和数值轴WIP快照保持。

最终八图源SHA=`546e24f47927c98df2024afac2eee0d12403cf1b46ab310ae3d1ac8ffc275cea`；AI修订5下载SHA=`965b3c882fb41d4a4da9d1e43fe954c469649f5fdd95b9bd2bb9b31be4c944b2`，修订6=`6dc3fe9697c8464b8e4aadf9e04722d081e9f45e47c84f0a0215591b9062cc83`。根任务逐份复核全部已加载资源SHA并查看最终八图截图；inside抗锯齿对比像素分别为居中50/52、内端33/37/31，AI重开46/43，均另核实际包围框位置。
