# XLSX 条形方向、零线与空值画布验收

日期：2026-11-12。承接 [已有图表 AI 验收](NATIVE_XLSX_AI_EXISTING_CHART_ACCEPTANCE.md) 中“保存为 bar，画布仍是竖柱”的已确认缺口。范围为当前本表数值引用、默认自动线性轴下的簇状 bar/column 几何，不关闭完整图表视觉对齐。

## 从原始材料确认问题

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/tests/chart-negative-bars.test.ts` 直接测试 WorkbookVisuals.BarChart：横向负值向零线左侧生长、纵向负值向下生长，缺失值不能成为全深负柱。通过 git show 读取实际测试；不拿整理后的能力矩阵作为行为依据。

本地 `frontend/src/workbook-vendor/grid/chart-render.ts` 原来计算 `barDirection` 后直接丢弃，bar/column 共用竖柱路径；两者 min 固定为0，负值及零值以 Math.max(1, …) 画成1px色条；numbersOf 又移除空值，使后面的值挤到前一个分类。后续系列更长时，分类数仍只取首系列，可能画出图框。

本轮修复实际注册的画布扩展：bar 沿X、column 沿Y，正负值共用真实零线；保留缺失分类槽，零/缺失/非有限数不绘制假条形；分类数取各系列最大长度，系列带宽不强行放大到2px。数值先按最大绝对值归一化，避免两个有限端点相减溢出产生无穷几何。其他图形仍沿用原有数值压缩和绘制行为，未借此宣称已修复它们的负值/空值语义。

## 先失败后通过的定向验证

`frontend/src/workbook-vendor/grid/chart-render.test.ts` 通过注册表取得**实际扩展类**，使用真实 parseRange、受控 worksheet/skeleton 和绘图上下文记录，不复制绘制算法。新增10项全部在修复前失败，修复后通过：两方向分别覆盖混合正负、零/缺失/文本/非有限数、缺失分类与较长后续系列、全负数、MAX_VALUE 到 -MAX_VALUE 的有限几何。按零线连接、长度比、分类间距与图框范围断言。

与 workbook-chart-add.test.ts、workbook-chart-switch.test.ts 合计 **17 passed**。完整 npm run build（tsc + Vite，Node heap4GiB）通过，Vite **49.08s**；全部JS预算通过，未改阈值。新Python脚本Ruff、JS语法及git diff --check通过。未重复完整项目测试，也未重跑不受影响的发布/AI Python全组。

## 真实生产构建与独立截图像素

`frontend/smoke/workbook-chart-render-smoke.mjs` 使用真实源文件、HTTP/授权和当前生产构建打开网格，不注入模型或草稿。fixture通过openpyxl生成表格，既有writer建立图表部件，再用独立ZIP/lxml将空值点缓存与真实空单元格对齐；输入同一组两系列数据：First=[3,-5,0,缺失]，Second=[1,缺失,-2,6]，另有全零系列。

Pillow直接分析最终截图：从图框边线和两种完整纯色连通区域恢复几何，不使用浏览器/renderer返回的条形坐标。openpyxl独立读取输入值。结果为：

| 图形 | 实际非零色块 | 独立检查 |
| --- | --- | --- |
| bar | 5 | 正值向右、负值向左共用零线；各色块长度与3/5/1/2/6成比例；空分类未压缩 |
| column | 5 | 正值向上、负值向下共用零线；数值比例与分类间距保持 |
| 全零bar | 0 | 图框保留，没有虚构1px条形 |

纯色区域不包含抗锯齿边缘，因此长度比较采用相对最大条形的**绝对2px容差**，而不是用16px最短条形作分母放大舍入误差。组件上下文的几何断言仍使用精确比例。此容差仅用于本次100%缩放、固定夹具的像素检查，不代表任意工作簿的像素保真。

- RED：`/tmp/workbook-chart-render-browser-20261112-red03/failure.json`。旧冻结资产得到第一图6块、第三零图仍有细色条；第一项即失败，截图可复核。
- GREEN：`/tmp/workbook-chart-render-browser-20261112-green03/summary.json`。三个图依次5/5/0，pageErrors/consoleErrors/httpErrors/assetErrors均为空，原件不变，无AI请求或保存。
- 失败现场保留：首次fixture缺PYTHONPATH；初版试图捕获附着Canvas而漏掉离屏绘制，之后改用最终截图；green02最初以最短条形计算比例放大边缘舍入，改为上述有物理依据的2px检查后最终green03通过。未为错误测试改产品。

Chromium `140.0.7339.16`，固定资源 `/tmp/workbook-chart-render-static-20261112`。169份实际加载JS/CSS与冻结磁盘逐份SHA匹配；manifest=`530d7dde396bfbbcc223084a782c7f27d94245bb8985ed6ff6b884856d54fa69`。输入SHA=`3e5636dcb52a04888e7c50d621344ea901239442a0ebfb828dfe1d3d0caab81d`。根任务随后再次独立核验169份资源，并查看实际截图。

## 新构建上的保存闭环

`/tmp/workbook-ai-charts-browser-20261112-render05/summary.json`：既有完整AI浏览器脚本在相同manifest的新构建再次通过，实际工具预览、手工草稿、显式采纳、UndoRedo、放弃删除、保存4→5→6、下载与重开保持。独立openpyxl/lxml确认原引用/数值/手工加粗和另一同名图表字节保全；图表数2→2→1。169份实际JS/CSS核验，运行错误数组为空。provider为ScriptedModel，仓储为有作用域内存夹具，不是生产DB/真实provider证据。

编辑下载SHA=`934968017001206ca8f18d5e67bd3a139d6d87c029fafe1eeba44cc589d2af37`；删除下载SHA=`320acece0ba0c69c1a1d77994f15f53d9ece498ddc67ed3a8b9f7fee1cf4f246`。两次保存仍返回业务/完整版式待复核并正常签发链接。

## 未关闭的范围

本轮只关闭上述方向、零线和分类槽问题。图表标题及网格文字的可见性仍需核查（本环境截图中未见对应文字），图例/轴/标签/颜色样式、堆叠与百分比、组合/对数/手动轴范围、跨工作表引用解析等仍需独立专项；不能把这一限定截图算作复杂图表完整视觉对齐。未改writer、发布签发链或源文件；未合并部署或启用生产开关。两个PDF WIP stash保持原样。
