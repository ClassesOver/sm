# XLSX 数值轴刻度与自动范围验收

日期：2026-11-12。基于 `code` 的 PR #220/#221 合并结果，范围限于单一可信轴配对的普通 bar/column 线性数值轴。不把本批算作完整图表或完整坐标轴能力。

## 原始依据与实现

原始依据为固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `packages/xlsx-gateway/src/domain/chart-visual.ts::valueAxisScale` 和 `apps/sheets/src/renderer/WorkbookVisuals.tsx` 的轴角色/完整数字策略，另直接读取实际 XLSX ZIP 中的 valAx、单元格值、min/max/orientation/majorUnit/numFmt。不是从既有验收说明推导图形应有比例。

- 自动范围采用源 5% 留白、1/2/5 主刻度单位及负值下界的 1/2/2.5/5 取整。10/20 的自动范围由旧 0..20 改为 0..25；3/6 为 0..7；300/-500 为 -600..400。
- 读取实际关联数值轴的 majorUnit 和解码后的 numFmt。无效、非正或非有限主刻度不静默转为自动；既有对数/无效范围和不可信轴归属继续显示不支持提示。
- 画布数字刻度、轴线、跨零零线和条形共用同一个有限、夹取映射；显式 min/max、反向和边界裁剪保持。隐藏数值轴不保留空刻度带，数据仍绘制。bar 支持 top/bottom、column 支持 left/right；兼容旧 writer 的轴位置与语义角色。
- 刻度带位于标题/图例带内侧；测量文字后布局，跳过碰撞标签，不截断数字来强行塞入。密集保存单位按其整数倍抽样，限制到至多 12 个候选，覆盖完整域，不以固定前十个刻度截掉后段；不改源文件单位或数据。
- 显式数字格式复用现有 Univer numfmt，百分比保留实际格式精度；General 使用完整整数与可读小数，不缩写为 K，也不把极小非零值画成 0。格式库抛错或未返回非空文本时回落到实际数值，不能据此声称全格式保真。
- 原源算法对部分全负域会把自动 max 从 0 再向上取整成正数；本地遵循其零基线意图，将全负自动上界保持为 0。浮点跨度溢出时保留有限边界并归一化；窄大数显式端点不做破坏性精度取整。上述是明确的本地适配，不声称逐字复制。

## 外部对照与定向验证

| 方法 | 结果 |
| --- | --- |
| 原源算法独立执行 | `smoke/workbook-chart-scale-source-oracle.mjs` 直接 git show 固定版本，TypeScript transpile 后在 VM 执行原函数，与本地函数比较。固定 seed=190、250 组跨量级正负数据，各测自动/显式范围/主单位，共 **750 组**：748 组域一致，2 组仅为上述全负上界修正。原始结果 `/tmp/xlsx-axis-source-oracle-final-20261112.json` 包含两组具体输入与源/本地边界。 |
| RED | 新元数据读取先 **5 failed / 10 passed**；实际注册画布扩展新刻度先 **4 failed / 36 passed**；自动范围新 helper 初始 7 项失败。失败日志保留，不算验收通过。 |
| 读取 GREEN | 值域/单位/格式 15 项与已有读取 19 项 **共 34 项分批通过**。 |
| 前端 GREEN | 注册扩展 40、数值范围 15、既有图例文字 2，**共 57 项分批通过**；包含全负零点、完整数字/百分比、top/right、反向、隐藏/不可信轴、密集单位、溢出和 subnormal 几何。 |
| 构建 | 引擎两级 tsc/bundle、完整前端 tsc/Vite **46.29s**、全部 JS 预算通过；不修改阈值。Ruff、JS 语法与 diff 检查通过。未重复完整项目测试。 |

源算法差分复现：在 frontend 执行 `GENOFFICE_SOURCE_DIRECTORY=/path/to/genoffice WORKBOOK_CHART_SCALE_ORACLE_OUTPUT=/tmp/oracle.json node smoke/workbook-chart-scale-source-oracle.mjs`，脚本会核对原始仓库 HEAD 必须等于固定版本；找不到或版本不符即失败，不替换成复制的期望实现。

## 浏览器、独立像素与保存重开

使用冻结生产构建 `/tmp/workbook-chart-ticks-static-20261112`，manifest SHA256=`c602c2f616e35143ad4cb4bf4216154342dcf00d754e49045ab7f13fcf79258b`，Chromium140.0.7339.16。每条链都先显式 Fontconfig/Canvas 字体预检，实际加载 169 份 JS/CSS 与磁盘 SHA 一致，pageErrors/consoleErrors/httpErrors/assetErrors 为空，源文件身份不变。

1. `/tmp/workbook-chart-ticks-browser-20261112-green/summary.json`：六个真实 XLSX 图表，独立 openpyxl/lxml 回读实际源值、手动域、反向、0.1 单位、0% 格式与隐藏标记；Pillow 从最终截图恢复图框/完整数据色块，按真实数值独立计算长度与零点，容许纯色边缘 2px。每图 2 条数据；刻度区域深色墨迹 **148/52/56/42/0/56**，隐藏轴确实无刻度墨迹。实际 Canvas 文本调用另核 -600、400、-22.5、0%/10%/50%，不以仅有模型字段或宽度大于零算可见。根任务已查看完整截图。
2. `/tmp/workbook-chart-geometry-browser-20261112-ticks/summary.json`：原正负/缺失分类/零值回归，色块数 **5/5/0**，比例、共同零线与空分类槽保持，标题和网格有实际墨迹。
3. `/tmp/workbook-ai-charts-browser-20261112-ticks/summary.json`：真实 UI/HTTP/授权/Agno 工具/Node writer/签发/下载/重开，人工加粗→AI 范围 5..25 带轴标题→UndoRedo→真实候选恢复自动→撤销恢复自动→保存4→5/下载重开→放弃删除→重新采纳删除→保存5→6/下载重开。独立 XML 仍确认手动 5..25、原值10/20及引用、另一图字节不变；像素为手动1/4、3/4，恢复自动后为10/25、20/25。轴标题/图例与人工格式保持。provider 为 ScriptedModel、修订存储为作用域内存，不能算真实 provider 或生产 DB 验收。

4. `/tmp/workbook-chart-axis-browser-20261112-ticks/summary.json`：四种角色/方向/隐藏标题与底部图例回归通过，原标题墨迹和两条数据保持。
5. `/tmp/workbook-chart-scale-browser-20261112-ticks-green/summary.json`：原六种手动域/反向/跨零/裁剪/全负/对数降级回归通过，条形数2/2/2/1/2/0。初次 `/tmp/workbook-chart-scale-browser-20261112-ticks` 在旧“第二分类大于原绘图区中点”断言失败；独立图像确认数据槽正确，脚本改按新增20px刻度带后的分类起点和厚度分别核对，两处均保持2px容差，不放宽条形范围/比例条件。失败现场保留，最终新目录重跑通过。

六图源 SHA=`f05007a76af112e5ff0e8ccea3d9f8255518034d65fab22e7e6ffd3e98e687d5`；AI 修订5下载 SHA=`bd71437e642add00c873665d3878fb1f56a50bde47e331eab6b4ec8a5a017af7`，修订6=`08ab398f106a4fe5ac8868bb484f40b922b4bf50b67121d764518c192d3473c2`。截图、独立 JSON、下载文件、HTTP 与 planner 证据在各目录内。

浏览器复现使用 WORKBOOK_CHART_RENDER_CASE=ticks 与新的 WORKBOOK_CHART_RENDER_DIRECTORY；AI 链同时设置 WORKBOOK_AI_CHARTS_VALUE_RANGE=1、WORKBOOK_AI_CHARTS_AXIS_TITLES=1。均沿用显式 FONTCONFIG_FILE、PDF_SMOKE_STATIC_DIRECTORY 冻结目录，不能覆盖旧失败目录。

## 尚未关闭

类别刻度/多级分类、完整网格线与轴线样式、tickLblPos/交点/源链接格式继承、显示单位、数据标签、对数/次轴/组合/堆叠/百分比图计算、跨表数值及完整字体度量仍缺。小图或过宽数字可省略刻度，不能算布局保真。已有 AI 新建/替换数据和真实 provider 生产链仍未完成。不改发布门禁、下载权限或业务验收结果，不部署或开生产开关。旧 PDF 暂存与本次开始前的数值轴 WIP 快照均保留。
