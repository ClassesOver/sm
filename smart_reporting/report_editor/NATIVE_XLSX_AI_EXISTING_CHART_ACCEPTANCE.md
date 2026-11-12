# XLSX AI 已有图表候选验收

日期：2026-11-12。承接 PR #218/#220；范围是已有图表的格式编辑与删除，不关闭完整 XLSX 图表 AI 或画布保真目标。

## 原始依据与实际问题

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`：`apps/sheets/src/renderer/ai/tools.ts` 的 chart context 输出真实 path/title/type/sheetId；`ai/prompts/guides/charts.md` 描述已有图表编辑。通过 `git show` 读取实际固定源，不依赖工作区稀疏检出的文件是否存在。

本地 `workbook_engine/bridge/operations.ts` 已有 applyChartEdits/applyChartDeletions，但 WorkbookAIProposal 不允许这两类候选，工具指南没有 charts，整簿提示及 UI 明确禁止图表。因此有真实 writer 不等于 AI 已接入。

更深一层的问题是 TS 接口不能校验模型传来的 JSON。实际绕过 AI 直接调用 writer 的探针确认：`legend="diagonal"` 会写出 `legendPos val="undefined"`。本轮在 AI 边界使用 Pydantic 严格运行时类型、枚举、有限数和范围约束，避免把这类参数交给 writer；未修改 vendored writer 或扩大手动入口。

## 实现与授权边界

- 两类原生操作进入候选 schema，复用既有真实引擎预览、显式采纳、UndoRedo、完整草稿身份及保存协议。
- `workbook_ai_charts.validate_chart_candidates` 从**包含人工草稿的冻结模型**建立真实 chartPath→所属表索引。路径不存在、共享/重复身份、删除表名不符、删除后再次操作、空候选或未知字段均拒绝。没有按标题或数组位置自动选择图表的代码。多图目标的语义消歧由模型指令要求；这不等于任意真实模型都不会误选。
- Toolkit 与 NativeWorkbookAIService 都校验；不使用 Toolkit 的 planner 不能绕过。报告工作簿 ReportWorkbookAIService 也使用同一契约，避免共享 schema 扩大旧入口权限。
- 原有单元格选区模式仍只允许选区内 applyCellEdits，不读取图表特性、不允许图表候选。只有用户明确选择整簿范围才开放本轮能力。
- 格式包括标题、六类可转换类型、图例、系列/点颜色、数据标签、轴标题、分组、网格、轴范围、间隙、圆环内径和饼图分离。JSON 布尔不接受字符串/数字替代；非有限数、非法枚举/颜色/索引、越界百分比、非法 XML 控制字符均拒绝。轴标题/上下界允许明确 null 表示移除/自动。实际图表是否支持某格式仍由真实 OOXML writer 预览判断。
- 不开放新增图表、series/seriesSet 数据替换、图片、保护或主题；图表源数据授权/缓存一致性需另行闭环，不把任意模型数值作为缓存落盘。

## 分层验证

| 范围 | 结果 |
| --- | --- |
| 初始 RED | 新专项最初 11 failed / 5 passed，已有图表的协议和工具指南缺失；日志 `/tmp/workbook-ai-charts-red.log`。不把每个失败都算成独立产品 bug。 |
| 最终图表专项 | `test_workbook_ai_charts.py` **45 passed**。包括真实 Agno ScriptedModel/工具/Node writer，双同名图表精确目标、原件保留、人工草稿、显式采纳、过期草稿拒绝、另一图 XML 字节保全、删除、两种服务的非工具 planner 边界，以及 24 组运行时非法值。 |
| 既有 XLSX AI | `test_workbook_ai_tools.py`、`test_workbook_native_ai.py`、`test_workbook_native_ai_registration.py` **34 passed**；旧报告工作簿两项 AI 合同另外通过。未重复完整项目测试。 |
| 前端宿主 | `workbook-native-ai.test.ts` **7 passed**；更新帮助文字，明确整簿已有图表格式/删除与仍未支持范围。 |
| 构建 | 完整 `npm run build`（tsc + Vite，Node heap 4GiB）通过，Vite **45.17s**；全部 JS 预算通过，阈值不变。新 Python Ruff、JS 语法和 diff whitespace 检查通过。 |

## 真实浏览器保存、下载与重开

最终证据：`/tmp/workbook-ai-charts-browser-20261112-04/summary.json`，Chromium `140.0.7339.16`。实际生产构建、真实 session/grant/cookie/CSRF/HTTP、Agno 工具、Node writer、publication 和下载服务；provider 为 ScriptedModel，修订仓储是有作用域的内存夹具，**不是生产数据库或真实 provider 验收**。

1. 两张同名柱形图、真实引用和数值 10/20；界面在 A1 手工加粗。
2. 整簿 AI 只修改 chart1：标题 Updated、bar 类型、bottom 图例。候选未采纳时草稿保持；显式采纳进入同一草稿，Undo→Redo 原样恢复。
3. 保存修订 4→5，实际界面 XLSX 链接与响应一致，HTTP 下载，再打开新修订并读取其实际文件；SHA 一致。
4. 新修订生成删除 chart1 候选，先放弃，确认没有删除草稿；再次生成并显式采纳，保存 5→6、下载与重开。
5. 独立 openpyxl/lxml/ZIP 从实际下载回读：图表数 **2→2→1**；标题 Updated、`barDir=bar`、`legendPos=b`；数值缓存及 A/B 原始引用保持；A1 手工加粗在两份下载中保留，chart2 XML 与原件字节一致。
6. 两次保存都诚实返回 `validation.ok=false / native_source_review_pending`，仍提供真实下载与新修订，不冒称业务或完整版式验收通过。

冻结资源 `/tmp/workbook-ai-charts-static-20261112`；169 个实际加载的 JS/CSS 响应与磁盘逐个核 SHA，随后根任务再次独立核对。禁用浏览器缓存以取得每次重开时的实际响应字节；manifest 始终不变，pageErrors/consoleErrors/httpErrors/assetErrors 均为空。

| 身份 | SHA-256 |
| --- | --- |
| manifest | `a8e490e93b2733ca9d76f14ff8a3a7a847444b58eeefbbf459164e3956f5d71b` |
| 原件 | `f629e607bb7328f8ff595ce074d36fe1d2491c5f732a90f9153e20966b84f6ea` |
| 编辑下载／修订5 | `d46d5ea3e11858e6d51408f84ff14ccd9443bcc942b6066de4c86cdbc90cda58` |
| 删除下载／修订6 | `413a09465828237ac0482def4d6e1236f6a9f0f4ca14953264d069f39e921395` |

浏览器脚本 `frontend/smoke/workbook-ai-charts-smoke.mjs` 会新建唯一目录，调用同名 server.py/verify.py，不覆盖先前失败。首次失败是脚本用了 PDF 下载区选择器；第二次完成全部产品步骤和独立文件验证，但把合法缓存 304 当作错误；03 通过后增加严格运行时边界，04 再次通过。失败现场均保留，不改产品满足错误断言。

## 仍开放的缺口

- **画布显示不等于文件格式保真**：本专项最初确认 v1 renderer 将 bar 与 column 同样画成竖柱（barDirection 未使用）。后续已修方向、正负零线、零值及缺失分类，17项定向与真实截图像素通过，见 [画布增量验收](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md)；标题/网格文字可见性、图例/轴样式等仍需独立补证，不能认定任意图表视觉通过。
- 可编辑目标限当前解析模型返回的图表；未投影的复杂/特殊锚点不靠猜测路径开放。共享部件、复杂组合图的写入继续受真实 writer 边界约束。
- AI 新建图表与替换数据、同名多图语义消歧的真实 provider 表现，以及真实 provider→生产仓储→浏览器采纳保存下载的同一链路仍开放。
- 未合并、部署或启用生产功能开关；两份原有 PDF WIP stash 未动。
