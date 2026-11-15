# XLSX 阅读助手 select_range 验收（2026-11-15）

来源：固定 GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c 的 select_range。PR #245 本增量将工具接入 Agno 阅读任务及真实 Univer 编辑器。

## 行为与边界

浏览器独立捕获 viewSelection；整簿阅读的授权 selection 仍为 null。服务端验证目标、授权范围及地址规范化，使用阅读器自身状态返回 navigation；模型最终 JSON 不能伪造目标。省略 sheetId 时使用捕获的当前工作表，后续工具采用最后请求的工作表。导航不增加阅读覆盖或引文。

现有异步任务返回 navigation_requested；浏览器验证原件、草稿、当前视图和任务生命周期，再调用真实选区及视口 API。确认目标实际可见后才显示“已定位”。导航失败保留答案并显示失败，不修改文档、草稿或保存。修复了待打开阅读面板在挂入侧栏前聚焦导致焦点丢失的问题。

本轮仅覆盖支持网格导航的 XLSX 阅读助手。候选编辑规划器、静态只读表格、来源立即执行并回复模型的桌面 RPC、稳定 sheet ID 仍待后续对齐；不据此声称工具全量一对一完成。

## 验证

- 后端：42 个相关节点通过（41 个分组节点及 1 个有效 API viewSelection 节点；分组另有 2 个集成节点未选中）。覆盖严格坐标、默认工作表、冻结授权、覆盖统计、可信回执、Agno 工具注册、旧客户端、任务传输及请求身份。
- 前端：72 个相关节点分批通过。实际 Univer 用例验证工作表切换、选区、视口失败、过期任务以及工作簿内容不变；面板入口焦点问题先失败再通过。
- 最终 npm run build（TypeScript + Vite）、资源预算检查、Ruff、脚本语法及 git diff --check 通过。
- 独立代码复核未发现具体 Critical、Important 或 Minor 问题。

可复跑浏览器脚本：frontend/smoke/workbook-ai-navigation-smoke.mjs；配套服务器：frontend/smoke/workbook-ai-navigation-server.py。使用真实授权跳转、原生 HTTP 读取任务、Agno 及 Univer；模型提供方替换为脚本模型，修订仓储为内存实现，不代表生产数据库或外部模型验收。

最终实际浏览器结果位于 /workspace/scratch/pr245-navigation-final：evidence.json、navigated.png。从 Target!A1 发起整簿阅读，工具将反向地址 l2001:k2000 规范化为 K2000:L2001。截图人工检查确认 Target 工作表、目标选区及第 2000 行 navigation-canary84 同时可见。请求 selection=null、viewSelection=Target!A1；原件 SHA 不变、草稿操作不变、保存次数为零，无采纳或保存 POST、无页面错误；307 个加载的 JS/CSS 资源与本地构建 SHA 相符，包含导航懒加载模块。

浏览器复跑示例：

```sh
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
WORKBOOK_AI_NAVIGATION_DIRECTORY=/tmp/pr245-navigation \
WORKBOOK_AI_NAVIGATION_PORT=4368 \
node smart_reporting/report_editor/frontend/smoke/workbook-ai-navigation-smoke.mjs
```
