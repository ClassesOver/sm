# 原生 AI 任务生命周期增量验收

日期：2026-11-13。完整目标继续开放，见 [源工具接线矩阵](NATIVE_AI_SOURCE_TOOL_COVERAGE_20261113.md) 和 [实施计划](../../docs/superpowers/plans/2026-11-13-native-ai-complete-lifecycle.md)。本轮只登记已实际实现和验证的生命周期增量，不替代复杂对象、完整源工具或长任务恢复。

## 复现、根因与改动

1. 事件日志原来没有终态封口，重复 finish 和迟到工具／内容回调继续增加序号。现在序号、追加和封口在同一个 condition 锁内完成，既有排队 Agno 回调先排空，首次终态后不再追加。
2. 已消费终态后的 SSE 重连原来继续等待／心跳。现在直接结束响应；回放过程中才到达的终态仍会发送，不因旧快照提前关流。
3. 大于当前序号的游标原来永久等不到新事件。现在服务端发 reset 并重放现存历史；前端允许明确 reset 回退至非负游标，普通倒序、重复、非法帧仍被拒绝。
4. 阅读任务及 XLSX／PPTX 取消先于启动时只写状态，没有 SSE 终态。现在取消墓碑也发布终态；任务刚创建尚未执行就关闭服务时，由宿主补终态，不依赖协程一定执行 finally。
5. 基础阅读／候选服务关闭后原来还能创建任务。现在新增关闭守卫，保留取消及状态读取；候选采纳在预览前后均拒绝已关闭服务。
6. Word／PDF 选区编辑原来没有请求 ID，启动回执丢失后前端无法取消。现在复用现有原生会话增加可选 `clientRequestId`、请求摘要幂等和 `/api/ai/cancel-request`。预览前及任务创建前两次检查请求登记，启动期间取消不再进入模型。取消回执保留一小时，新请求不能通过淘汰未过期墓碑重启同一请求。
7. 前端取消、换选区、改要求、关闭／卸载时，未拿到 editId 也按请求 ID 取消；启动网络失败且没有编辑 ID 时同样清理请求。拿到编辑 ID 后继续使用原取消接口。采纳仍只进入草稿，不自动保存。

本轮保留原生 Agno 工具事件及最终结构化输出，不解析 assistant 正文执行操作；SSE 不包含推理、工具参数或原始工具结果。没有修改业务事实、文件权限或发布签发链。

## 定向验证

新增用例先观察失败再修复：日志／重连／提前取消五项失败、立即关闭三项失败、请求协议三项失败、前端提前取消三场景失败、启动网络失败一项失败。PDF 初次沙箱夹具挂在异步 worker 唤醒，faulthandler 指向 fixture 等待；中止后在获准的沙箱外运行真实文件夹具，不把挂起计为通过。

| 范围 | 命令／结果 |
| --- | --- |
| 最终后端请求协议与基础候选 | `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_native_ai_requests.py smart_reporting/reporting/tests/test_native_ai_event_lifecycle.py smart_reporting/reporting/tests/test_native_ai.py --tb=short`：45 passed。含真实 Word／PDF 夹具、真实授权 HTTP、CSRF／Origin／版本作用域、提前取消、幂等及原有缓存／预览／采纳。 |
| 事件与相邻取消／关闭 | `test_native_ai_event_lifecycle.py`、`test_agent_events.py`、`test_native_ai_shutdown_terminal.py`、`test_native_ai_cancel_terminal.py`、`test_native_slides_ai_cancel_terminal.py`：该批 28 passed。后续基础任务新增字段后另跑下行兼容回归，不累加为独立用例数。 |
| 阅读／审阅／表单共用基类 | `test_native_pdf_ai_tasks.py`、`test_native_pdf_review_ai_tasks.py`、`test_native_pdf_form_ai_tasks.py`、`test_native_word_read_tasks.py`、`test_native_office_read_tasks.py`：50 passed。 |
| XLSX／PPTX 候选兼容 | `test_workbook_native_ai.py`、`test_slides_native_ai.py`、`test_native_ai_shutdown_terminal.py`：25 passed。 |
| 前端最终用例 | `npx vitest run src/native-ai.test.ts src/native-api.test.ts src/native-ai-progress.test.ts src/native-ai-progress-panels.test.ts`：62 passed，包含启动网络失败清理、三种提前取消、重连和 API CSRF 请求。 |

所有 Python 批次仅有既有 imghdr 弃用告警，没有重复完整项目测试。目标 ruff、JS smoke 语法检查及局部 `git diff --check` 通过。

## 真实浏览器证据与构建边界

`frontend/smoke/word-ai-lifecycle-smoke.mjs` 复用真实 Word fixture 服务、FastAPI 路由、grant／cookie／CSRF 和工作区。仅对测试服务挂起启动回执，再用真实 UI 执行取消、改要求、关闭助手。三场景均确认取消请求先落地、迟到 start 返回 cancelled、模型调用为零、没有候选／采纳／保存／导出、草稿及原件不变；浏览器真实 fetch 验证未来游标 reset／回放和消费终态后空响应结束。

第一冻结构建三场景通过，158 个实际 JS／CSS 逐资源 SHA 与磁盘匹配，pageErrors 为空；证据 `/tmp/native-ai-lifecycle-browser-20261113/summary.json`。这组是取消场景，**没有调用模型**，不是 provider 成功证据。内存修订仓储也不是生产数据库验收。

第一构建 `npm run build` 通过（Vite 44.05 秒），日志 `/tmp/native-ai-lifecycle-build-20261113.log`；预算检查实际失败，PDF 主块 255.7 KiB 超出 250 KiB，保留日志 `/tmp/native-ai-lifecycle-budget-20261113.log`。没有提高预算；把本轮涉及的共用 `native-ai.ts` 独立为 `native-selection-ai` 构建块。中间构建因继续补启动网络失败用例而主动中止，最终源码需重建、预算检查及浏览器补验，不能沿用第一构建冒称最终整包通过。

第二构建补齐网络失败清理，tsc／Vite 通过，日志 `/tmp/native-ai-lifecycle-final2-build-20261113.log`；取消三场景再次通过，161 份资源身份核验，证据 `/tmp/native-ai-lifecycle-browser-20261113-final2/summary.json`。预算仍实际失败（PDF 主块 259.6 KiB），没有隐去。继续按现有模块边界把选区、PDF 阅读／批注／表单 AI 面板归为 `native-ai-controls`，第三构建与最终浏览器验证进行中。

第二构建的既有 `word-ai-review-smoke.mjs` 在 AI 操作前因通用 `[role=tablist]` 断言失败，现场 `/tmp/native-ai-word-review-20261113-final2/failure.html` 及 PNG 保留。独立 lxml 回读确认工作区内命中的是 `docx-navigation-tabs`（导航内容），真正 `.docx-ribbon` 在工作区内为0、整页为1；截图也显示功能区在正文／助手之上。修正 smoke 仅检查实际 `.docx-ribbon`，没有改产品布局或删除布局验收。

### final7 收尾（上述进行中为历史状态）

后续 final4／final5 暴露 slides-show 测试夹具的 scale 缺失／背景 RenderFill 的 type 与 kind 混淆；final6 构建完成但 Word 主块 260.2 KiB 超限。按真实 chunk 模块清单定位 docx-ribbon 的约 59.9 KB 渲染体积，把现有功能区模块按原边界拆分，没有提高预算。失败和诊断日志保留。

final7 `/tmp/native-ai-lifecycle-final7-build-20261113.log` 构建退出 0（Vite 43.80 秒），预算 `/tmp/native-ai-lifecycle-final7-budget-20261113.log` 退出 0；Word 119.2 KiB、PDF 238.9 KiB、workbook-main 223.0 KiB、workbook-engine 344.1 KiB。冻结 manifest 为 `720c30172b543ca6c625a99395afd8c78eabda2e037f97c612228c6f0f59b2fe`。

同冻结构建 `/tmp/native-ai-lifecycle-browser-20261113-final7/summary.json`：三项提前取消通过，163 份资源身份匹配、errors 为空，模型调用为零。`/tmp/native-ai-word-review-20261113-final7/summary.json`：Word 普通回复显式采纳与独立 DOCX 回读通过，163 份资源匹配；该用例为真实 Agno＋ScriptedModel，不是外部 provider。原通用 tablist 误报已按真实 ribbon 断言纠正。后续 final8 仅图表来源与相关构建证据见[来源图表专项](NATIVE_XLSX_AI_CHART_SOURCES_ACCEPTANCE_20261113.md)，不冒充在 final8 重复整套生命周期验收。

## 明确保留的缺口

- 源完整工具及 DSL、复杂对象尚未完成；源声明矩阵是接线调查，不是功能验收。
- 原生 AI job、请求回执及进度历史仍保存在进程内；断线重连可重放现有任务，不代表服务重启可恢复。长任务尚须复用现有 task_execution 仓储、租约、预算、取消和回执，并绑定原生上下文。
- 依赖吞掉取消后继续长时间阻塞的取消确认上界、跨进程接管／租约隔离、可恢复澄清等待仍需后续完整生命周期工作。
- 本轮未新增真实 provider 调用，也未完成生产数据库／浏览器真实模型／显式采纳／新修订／下载重开的同一条验收链。原有 [provider 证据](NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md) 保持其原始范围。
- 没有提交、推送、部署、开启生产功能开关或恢复 DockerSandbox。
