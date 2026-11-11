# XLSX / PPTX Agno 阅读验收

日期：2026-11-11。固定对齐源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。此增量补充独立问答、总结与关键要点，不代表完整四格式工具和复杂操作已对齐。

## 功能与边界

- XLSX/PPTX 提供中文 Lucide SVG 阅读入口，复用已有任务状态、SSE 工具进度和取消。阅读回答独立于非空编辑候选，无采纳、保存或导出动作。
- `NativeOfficeReadService` 复用现有有界任务生命周期，绑定来源、要求、动作、选区和操作快照。读取原件，或经真实 `patch_office` 生成草稿后 `inspect_office`；不通过手动拼接模拟草稿。编辑关闭仍能读取原件，有操作时仍检查编辑权限。
- XLSX 七个只读工具包含上下文、区域/离散格读取、搜索、统计、依赖与从属追踪，复用既有查询实现。冻结范围只保留授权单元格值与公式；稀疏格按 JSON 字符分页，搜索/统计/追踪不代表完整读完。不读取图片、图表视觉、批注；公式缓存不保证重新计算。
- PPTX 上下文与读页工具读取引擎真实 `text`，不以 `editable` 限制阅读；仅授权对象进入工具快照。备注、图片视觉及无 text 的表格/图表不在本次范围；界面展示服务端 `limitations`，完整覆盖仅指已提取文字，不表示完整 PPTX 全内容已读。
- `AgnoNativeWorkbookReadPlanner` / `AgnoNativeSlidesReadPlanner` 使用当前 reporting 模型的副本、既有能力策略及原生 Agno 事件执行，不自造 provider 循环，不注册写/候选工具。
- 引用只接受实际授权且完整读过的身份，服务端重建可读标签；无依据、未完整覆盖、无效引用均返回软告警。空选区不能转换为整份，整份使用显式 `null`。
- 前端采集当前真实操作与选区。XLSX 等待持久化及完整操作采集，异步期间变更拒绝；正在编辑的单元格要求先按 Enter 确认。PPTX 使用真实多选对象集合，草稿结构不明时选区拒绝。编辑关闭时提供独立原件阅读面板和下载，不加载或伪造编辑画布，不混入本地草稿。

## PPTX 解析身份缺陷与修复

真实引擎探针确认对象 `sp_*` ID 随解析顺序改变。原第一页 15 个文本框，另一页 1 个；重排 `[1,0]` 后，旧 `sp_9` 可指向原页对象 0，而非授权对象 9。仅重绑页索引会读取邻对象。

新增回归先红后绿。服务端现先检查原文件，再按核验过的原页内对象序与实际草稿页序重绑，同时校验数量、类型和名称。只允许已确认不改拓扑的操作；插入/删除、组合、图层顺序、版式、页脚等结构变化选区拒绝，仍可整稿读取真实草稿。页脚操作另有同名对象换位窄回归，避免误把数量/类型/名称相等当作身份充分证据。

## 定向验证

- PPTX 工具 12 项通过；XLSX 工具先 9 项、追加空表/标签/元数据边界 2 项通过。
- 真实引擎任务原 8 项分批通过（首轮 7 项通过、XLSX 草稿测试修正为真实 row/column 操作协议后 1 项通过）；追加 PPTX 重排 1 项与页脚身份 1 项通过。含关闭编辑可读、真实草稿选区隔离、请求快照、提前取消和吞取消后的迟到结果抑制。
- HTTP 6 项通过，含两格式关闭编辑阅读、SSE、取消、cookie/CSRF/origin/文档/修订/作用域检查及严格输入结构。
- 追加只读任务不能返回写提案、模型返回后来源变化不得发布回答两格式 2 项通过。受影响 Word 原阅读 HTTP 链 1 项通过。
- 前端面板/API/入口共 18 项分批通过；追加阅读边界展示及中文查询工具名窄回归通过；动态采集模块另 6 项通过，覆盖真实范围/操作、整篇 null、未确认输入和异步期间范围/草稿/编辑状态变化。相关 Python ruff 和目标 diff 检查通过。未跑完整项目测试。

## 真实 provider

`/tmp/office-ai-read-real-provider-20261111.json`：当前 reporting 模型工厂构建 `deepseek-v4.1-flash` / `ReportingPhaseOpenAIChat`，经真实 Agno 与任务服务执行 XLSX/PPTX 各一次选区问答及整篇摘要，四项均 completed、严格检查通过、`issues=[]`，总耗时 14.16 秒。

两格式选区回答收入 42，授权快照及引用不含秘密格/对象；整篇摘要实际完整读取并正确包含收入 42、成本 17；真实上下文和读取事件存在，源 SHA 不变，无编辑提案。此为合成文件、非生产数据库。最初 XLSX 整篇检查的手写地址顺序与引擎行序不一致，探针改用真实检查顺序后核验原回执，未重复 provider 调用。

## 浏览器

Vite 41.88 秒打包通过，日志 `/tmp/office-read-vite-build.log`。Chromium `140.0.7339.16` 两格式在关闭编辑模式完成原件总结：XLSX 2/2 格、PPTX 1/1 实际文本页；中文 SVG、引用、SSE 工具进度与 PPTX 边界提示通过。真实 HTTP/会话/来源/Agno 使用 ScriptedModel，不冒称真实 provider。

`/tmp/office-ai-read-20261111/summary.json`：`ok=true`，9 个实际加载 JS 的 HTTP 200 与磁盘 SHA 一致，manifest 在运行中不变；源 SHA、localStorage 草稿不变，无 preview/save/export POST，page/console/HTTP errors 为空。root 独立读取 summary 并目视 PPTX 截图。编辑开启的真实选区/未保存草稿尚未做浏览器专项，已有前端采集及后端真实文件定向证据，不能替代完整浏览器链。

## 构建与剩余范围

完整 `npm run build` 的类型阶段被共享工作区新交叉引用测试引入的 `doc_engine/bridge` TS 扩展导入与严格类型错误阻挡（`/tmp/office-read-build.log`），不是完整类型通过。首次预算检查 workbook-main 253.0 KiB 超过 253 KiB 上限；现将本轮阅读采集逻辑动态加载，主包 252.5 KiB、新模块 0.9 KiB，不提高上限。最终 Vite 43.61 秒与预算通过（`/tmp/office-read-budget-final-build.log`、`/tmp/office-read-budget-final.log`），预算契约已通过。

最终拆包改变三个实际加载入口 chunk 的路径，因此没有直接复用先前浏览器结果。独立 `/tmp/office-ai-read-20261111-final` 复验两链通过，9 个实际加载 JS 全部 SHA 匹配最终磁盘，manifest 为 `d12da77b2e20337ba1a6a38da53ddf2e811f950b1d1fe61d1b63830353af188b`。page/console/HTTP errors 为空，源/草稿不变，无 preview/save/export POST。root 重新核对全部加载资源和 manifest 并目视最终 XLSX 截图。旧证据保留，未重复完整测试。

完整审阅工具族、PPTX 复杂原生操作、PDF 页与表单 AI 工具，以及四格式所有工具的复杂多步任务仍开放。无发布签发链变更，未提交、推送或部署。
