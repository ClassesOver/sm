# XLSX 图表命名空间编辑与删除验收（2026-11-13）

本专项是 Word/XLSX/PPTX/PDF 对齐 GenOffice 的一个增量，整体目标仍未完成。固定源为 `/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。应用分支 code 当前为 `6a713d05`，保留现有未提交工作；没有提交、推送或部署。

## 来源行为与当前差异

| 来源入口/行为 | 当前本地证据与状态 |
| --- | --- |
| `apps/sheets/src/renderer/ribbon-actions.ts:295–392`：图表设计命令定位选中浮动图表；删除交给 `shapeEditRef`。 | `frontend/src/workbook-main.ts:1644–1723` 的功能区操作仍限定当前工作表仅一个图表，多图选择未接通。Agno 候选可使用可信 `chartPath` 精确编辑/删除；不能将此替代为已完成源选中对象 UI。 |
| `ExcelShell.tsx:2185–2280`：快速布局、更改颜色、六种转换、分组、选择数据、切换行列、格式及删除。 | 本地已有六种转换、分组/网格线对话框、数据替换等子能力；并非图表设计全缺。`workbook-ribbon.ts` 没有源快速布局和颜色方案入口。本批不关闭完整源图表设计/格式面板。 |
| 图表编辑/删除必须作用于实际部件，保留另一张同名图表及无关内容。 | 本批修复默认/任意命名空间前缀下的删除，并接续验证既有编辑适配；完成真实浏览器、保存、点击下载和明确修订重开。 |

## 修改范围与安全边界

- 接续现有 `chart-edit.ts` 命名空间适配：以 URI 识别 Chart/DrawingML 元素、恢复局部有效前缀；保留外来命名空间、扩展、注释、CDATA 和处理指令。混合别名可以合并为来源主前缀，不承诺每个别名原样保留。
- `chart-delete.ts` 改用已有 SaxesParser 解析元素/属性 URI 与解码后的关系 ID，精确移除唯一的 anchor 和 Relationship 源字符串区间；支持 twoCellAnchor、oneCellAnchor、absoluteAnchor。
- 仅接受真实 `anchor → graphicFrame → DrawingML graphic → graphicData → Chart chart` 归属。目标多重引用、额外对象、伪造 chart/id 命名空间和共享部件继续拒绝；拒绝时不改输入。
- `zip.ts::EntrySource.readText` 新增可选 `preservePrefixes`；仅命名空间感知的删除写入路径选择原始 XML，其余调用维持原先读取归一行为。否则即便精确删除成功，读取层仍会改写 prefixed package relationships。
- 继续保留工作表/绘图关系、部件路径、全包 incoming 共享检查和批量删除累积行为。没有改动发布或验收门禁语义。

## 定向验证

证据根目录：`/tmp/office-xlsx-chart-namespace-20261113`。

| 检查 | 结果与证据 |
| --- | --- |
| 删除专项 RED | `delete-red.log`：15 项中 10 个合法前缀场景失败、5 个拒绝场景通过；失败定位旧固定前缀身份正则。 |
| 删除首轮修复 | `delete-green.log`：锚点删除已成功；9 项逐字节断言发现读取层改写关系前缀，保留失败证据并修复原始读取。 |
| 删除最终 GREEN | `delete-green2.log`：新专项 15 项与原删除 3 项全部通过。逐字节比对 drawing/rels/无关 ZIP 部件、检查内容类型和输入不变。 |
| 编辑与读取回归 | `chart-regression.log`：命名空间编辑、原编辑、命名空间读取共 36 项通过。命令中不存在的旧 data-labels 文件名未计入测试数。 |
| ZIP 与标签回归 | `zip-label-regression.log`：ZIP 文件夹、标签样式、数据标签读取、主题标签共 56 项通过。 |
| 类型检查 | `engine-typecheck.log` 两级 tsc 及 `frontend-typecheck.log` 前端 tsc 均退出 0。 |
| 隔离构建/预算 | `frontend-build.log`：47.24 秒完成；`budget.json`：394 JS，failures=[]。没有覆盖共享 static 或调整预算。初次命令因错误目录及无系统 python 未启动有效构建，原日志单独保留；改用项目解释器和本地工具后完成。 |

合计 110 个不同定向测试通过，未运行完整测试套件。测试、构建和类型检查分别陈述，不能相互替代。

## 真实浏览器与独立文件回读

`frontend/smoke/workbook-chart-namespace-fixture.py` 从真实双图工作簿生成来源：chart1 默认 Chart namespace、chart2 为 plot 别名、绘图默认 XDR namespace、DrawingML 为 ink、关系属性为 link、package relationships 为 pkg；实际目标 ID 为 `chart&one`。加入含假标记的注释、vendor 扩展及二进制哨兵。

`browser/summary.json` 为 ok:true，Chromium 140.0.7339.16；同一冻结构建 manifest SHA-256 为 `2c54ea70768964953067ff38276aae83038389282bd4c414fc7865c7431f5640`。171 个实际加载 JS/CSS 的响应字节与磁盘 SHA 一致，pageErrors/consoleErrors/httpErrors/assetErrors 均为空。

真实操作顺序：打开双图 → 人工 A1 加粗草稿 → Agno 工具提出精确 chart1 修改 → 明确采纳 → Undo/Redo → 刷新恢复草稿 → 保存修订 4→5 → 点击 XLSX 链接触发浏览器 download 事件并保存实际字节 → 重开修订 5 → 删除候选先拒绝再生成并采纳 → 保存 5→6 → 再次点击下载并重开修订 6。

Python openpyxl/lxml/ZIP 独立检查：图表数 2→2→1，标题 Updated、横向条形图、底部图例、数据 10/20、Q1/Q2、来源公式及人工加粗正确；chart2 原字节不变；chart1 的 vendor 扩展和默认 namespace/ink 文本保持；删除 drawing/rels 分别严格等于旧文移除目标 anchor/Relationship，其余包成员逐字节保持。截图及独立像素检查确认标题/表头有墨迹、两条蓝色数据条和底部图例；已人工查看重开截图。

- 来源 SHA-256：`1edc775057f95e4225bf2fe12eba0cd6fdb863849b62fd5e217062a9f92f0133`
- 编辑下载 SHA-256：`fa49fa69e2a3d280df46f3d3b2cc1ab45fb3283c51e023fd16c900e42a6c8bb7`
- 删除下载 SHA-256：`4092bd91926cd75ee6e9d2ac5355c23fabcd5fbc5f61367b188a8be59eeb3eb4`

宿主 UI、HTTP 授权/cookie/CSRF、Agno 工具、Node 写入、发布下载及新修订读取为真实执行；provider 为 ScriptedModel，修订仓库为限定内存夹具。这不是生产鉴权、真实模型、桌面 Excel 或完整 OOXML 互操作验收。三类 anchor 的矩阵证据来自引擎测试，浏览器本批仅使用 twoCellAnchor。

## 未关闭范围

多图浮动对象的选中/移动/尺寸/删除及相应上下文 UI；源快速布局/颜色方案与完整格式面板；复杂组合图、图表局部主题、任意变换、外链或嵌入工作簿等依赖部件的删除回收与互操作；生产权限/真实模型和桌面 Office。其余四格式源入口仍需继续穷尽盘点和逐项闭环，不能由本批通过推导整体完成。
