# Word AI 只读问答与摘要验收

日期：2026-11-11。固定对齐源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本增量属于四格式 AI 共性优先项，不代表完整工具面或复杂操作已经对齐。

## 已实现范围

- 独立阅读入口提供问答、正文/选区总结、关键要点；使用真实 Lucide SVG 与中文界面。阅读不生成编辑候选，不写入 NativeDraft，也没有采纳操作。
- `AgnoNativeWordReadPlanner` 使用当前 reporting 模型和 Agno 原生工具循环，注册 `get_document_context`、`read_blocks`、`search_text`。工具调用通过现有事件桥接进入 SSE，并复用共享中文进度、取消和任务状态。
- 服务端读取实际 DOCX；有未保存操作时先用既有引擎生成真实草稿，再检查并读取该草稿。回答标明原件/草稿版本及实际覆盖范围，不手工拼接模拟正文。
- 授权范围为正文段落和表格文字。选区按整段/整格读取；不含页眉、脚注、图片。搜索片段不计完整覆盖；分页必须从开头连续覆盖全部内容，才可标记块已读。引用由服务端从已授权且完整读取的身份重建，覆盖不足返回软告警。
- 阅读开关独立于编辑开关；禁止编辑时仍可阅读原件，有草稿则仍须通过编辑权限检查。任务绑定来源、操作、选区、动作和要求；取消、超时或过期回答不能发布迟到结果。

## 选区修复与限制

阅读改用独立 `getReadSelection()`，不再复用编辑器可能回退整表的选区回调。布局属性变更保留单格身份；跨段、多格和跨表逐项计算授权，只有显式整表 NodeSelection 才读取整表。

结构变更、缺失/重复来源锚或新插入无来源内容会使选区失效。提交先同步待完成编辑，再重新核验选区；失效时不发请求，不回退全文。整篇模式可读取含新插入段落的真实草稿；结构变化后的选区需保存重开。

## 定向验证

- 阅读工具：10 项；真实引擎草稿、任务身份、取消、Agno/SSE 和结构变更任务：7 项；HTTP/权限/API：15 项；相关 PDF HTTP 兼容：2 项，分批通过。
- 前端选区 helper 8 项、面板 7 项、接线 1 项通过；另有阅读 API 1 项及原 main/API 10 项通过。未重复完整项目测试。
- 同轮修复旧 Word 编辑工具的分页覆盖绕过：只读长块尾页不再标记完整。复现及受影响工具定向 4 项通过、9 项未选择。
- 本轮 Python 阅读模块、API、受影响编辑工具及相应测试 ruff 通过，相关文件 `git diff --check` 通过。`app.py` 仍存在既有导入排序问题，不计为全应用 lint 通过。
- 最终前端 TypeScript + Vite 构建通过（43.87 秒），预算和预算契约通过；未提高预算上限。构建日志 `/tmp/word-ai-read-build.log`。

### 真实 provider 探针

当前 reporting 模型工厂构建 `deepseek-v4.1-flash` / `ReportingPhaseOpenAIChat`，经真实 Agno 和阅读服务执行两项合成 DOCX 探针，总耗时 13.9 秒。证据 `/tmp/word-ai-read-real-provider-20261111.json`。

- 单格问答通过：正确回答 731 元，完整读取所选格，只引用所选 cellId；相邻秘密格的文字和身份均不在授权快照或结果中，原件不变。
- 全文摘要任务完成，真实读取 3/3 块，42/17/25 金额正确，原件不变。但模型返回一个无效引用，被服务端丢弃并给出 `native_word_ai_unread_citation` 软告警；回答还把资料中的“未授权”措辞当作范围说明，声称没有读取实际已读的格。因此严格探针 `ok=false`，不能计全文摘要质量通过。实际覆盖以服务端证据为准，不以回答正文的声明为准。

### 浏览器首轮发现

首次生产构建 smoke 在编辑关闭模式失败：画布初始化调用既有 `preview([])`，被编辑门禁拒绝，阅读入口未显示。失败证据保留于 `/tmp/word-ai-read-20261111-disabled-editor-failure`，日志 `/tmp/word-ai-read-smoke.log`。此轮无阅读任务完成、不计通过。

修复增加独立 GET `read-model`，复用原件会话与来源身份授权，只返回真实 DOCX 检查模型，不接受操作或写入。画布仅在关闭编辑且开启 Word 阅读时使用该接口，其余保留原预览链。新增后端 2 项及前端 API 2 项定向通过，含关闭编辑可读、原 preview 仍拒绝、缺会话/跨文档/跨修订/跨作用域拒绝及非 DOCX 拒绝。

重新完整构建期间，共享工作区新增文件引入了两组 TypeScript 问题：先是 `slides-show.test.tsx` 的不完整 mock 强制转换，已用显式 `unknown` 桥接且该文件 5 项测试通过；随后是尚未接主入口的 `docx-cross-reference.ts` 与其测试的 unknown/可选值/NativeOperation 类型错误。仅给操作接口补 Record 类型并将 never 断言函数改为显式声明，保持运行逻辑，该文件 4 项定向测试通过。浏览器包使用单独 Vite 构建，类型检查结果另列。

### 最终浏览器复验

Vite 构建 44.98 秒通过、预算通过；日志 `/tmp/word-ai-read-model-vite-build.log`、`/tmp/word-ai-read-model-budget.log`。Chromium `140.0.7339.16` 在编辑关闭模式真实打开 Word，完成整篇 3/3 块及点击第二段后的选区 1/1 块摘要，真实 HTTP/授权/源文件/Agno 工具和 SSE，中文 SVG 入口、引用、覆盖与进度均有断言。ScriptedModel 仅负责模型回合，不冒称真实 provider。

`/tmp/word-ai-read-20261111-final/summary.json` 的 `ok=true`，122 个实际加载 JS 资源均 HTTP 200 且与磁盘 SHA 匹配，manifest 在验收期间未变；page/console/HTTP errors 均为空。原件 SHA 和本地草稿不变，无 preview/save/export POST。root 独立读取结果并目视 `selection-summary.png`。此链使用 scoped in-memory revision lookup 和本地 fixture 身份，非生产数据库/桌面 Word 验收。

复验前一次启动复用旧目录，workspace 按预期拒绝覆盖既有源文件，未进入浏览器；最终改用独立 `-final` 目录，未放宽文件覆盖规则。

最终单独 `tsc --noEmit` 仍失败：共享工作区 `workbook-ribbon.ts` 及其测试的 `superscript/subscript` 尚未加入 `RibbonCommand` 类型（日志 `/tmp/word-ai-read-model-final-types.log`）。本轮未修改该工作簿功能，不声称当前全前端类型检查通过。该结果与上述 Vite/browser 验收分别保留。

ScriptedModel 经真实 Agno 的浏览器验证不能替代真实 provider 验收。

## 仍开放

完整 GenOffice AI 工具面、Word 页眉/脚注/图片阅读及复杂结构编辑、四格式通用多步复杂操作仍未完成。此次不改变发布签发链，也未提交、推送或部署。
