# PDF 源页范围参数与共用输入框 UI（2026-11-15）

来源为固定 GenOffice f8c17004。本轮同时推进工具和 UI，用户端不提供模型选择。

## 工具接线

PDF read_pages 接受源 start/end（从 1 开始、包含端点，end 省略时等于 start）。每次最多读取 10 页及 24000 字符；超过页数或字符预算都会返回可直接执行的 next，保留请求的 end，续读不会扩张范围。end 超出文件时截到文件末页。

read_annotations 接受源 start/end，省略时覆盖全文，可只给其中一个端点。分页 offset/limit/text_offset 在所选页范围内计算，next 保留页范围。完整批注读取状态及后续批注处理仍使用原始全局序号，不能把筛选列表的第 0 项误认成文档第 0 项。正文和批注的源参数同时接到原生批注处理 wrapper。

通过 StrictInt 保证实际 Agno 工具调用拒绝布尔、字符串及浮点页号。原生 start_page/page_count 兼容保留，无参调用仍读前 10 页；源范围不能与原生页范围混用。原生字符分页、结构化回执、授权选区和投影 effective 页号继续使用，属于明确的网页适配，不声称与桌面文本输出完全相同。读取指南或改变参数不能增加未读取批注的编辑权限。

## 输入框 UI

共用助手输入框采用来源 slides AiPanel.tsx:1431–1446 的自动伸缩算法：先测量内容，再限制在 168px；清空后交回 CSS 默认高度。用户输入、新对话、任务开始、忙碌时排队清空和侧栏重新展开均同步尺寸；隐藏展开沿用下一布局帧，卸载清理监听器。保留现有输入法、队列、聊天跟随及授权范围控件，不搬入来源模型选择器。

## 验证

后端 71 项相关节点分批通过。新增范围测试先失败后通过，包含真实 Agno 两个工具的严格类型、正文单页与包含范围、10 页截断、字符截断、端点上限、混用拒绝、授权选区、批注全局读取身份与原生处理 wrapper；既有阅读、批注和草稿真实投影回归通过。独立复核发现 10 页截断缺少带 end 的 next，已用 20 页文件读取 1–15 页的回归先失败后修复，续读在第 15 页停止。

前端 42 项相关节点通过，覆盖输入框、输入法、队列、重新展开、阅读控制器和无模型选择。独立复核无其它具体问题。TypeScript 检查和生产打包通过；初次预算发现共享 PDF 控件块 254.6 KiB 超出 250 KiB，保留原预算并拆出打印／保护对话框，最终打包与预算另列。

脚本 frontend/smoke/pdf-ai-navigation-smoke.mjs 使用 PDF_AI_SOURCE_RANGES_SMOKE=1，可在真实原生 HTTP、授权、Agno 和 PDF.js 中调用 start/end 源参数，并检查输入框达到 168px 后清空复位、真实跳页、隐藏完成后展开及未写入。模型是 ScriptedModel、修订查询是限定内存实现，不计为真实外部模型／生产数据库验收。

全部来源工具和全部 UI 对齐仍在继续，本轮不代表所有能力完成。

最终构建验证：首轮 npm run build 的 TypeScript 与 Vite 通过；仅调整打包边界后，最终 Vite 打包（1 分 13 秒）及 check:budget 通过，未提高预算。Ruff、脚本语法及 git diff --check 通过。

真实浏览器证据位于 /workspace/scratch/pr245-source-ranges-browser/evidence.json、navigated.png、reopened.png；截图已人工检查。源 start/end 实际执行后正文覆盖 1、2 页，1/1 批注完整读完；输入框自动增长到 168px、清空复位及重新展开跟随均通过。169 个实际加载 JS/CSS 与磁盘构建 SHA 相符，无页面错误，无编辑 preview/采纳/保存 POST，原件和草稿未变，无用户模型选择。

复跑：

```sh
PDF_AI_SOURCE_RANGES_SMOKE=1 \
PDF_AI_NAVIGATION_DIRECTORY=/tmp/pr245-source-ranges \
PDF_AI_NAVIGATION_PORT=4369 \
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
node smart_reporting/report_editor/frontend/smoke/pdf-ai-navigation-smoke.mjs
```
