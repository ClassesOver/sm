# XLSX 候选助手 select_range 验收（2026-11-15）

PR #245 继续固定 GenOffice f8c17004 的 select_range 对齐，将已验证的实际网格导航接入原生候选编辑助手。

## 行为

客户端通过 navigationEnabled 显式声明导航能力，该标记绑定任务请求身份；旧请求默认不注册导航。Agno 工具验证冻结授权范围和目标地址，保存自己的可信 navigation。原生规划器使用独立内部类型返回可选修改候选及导航；模型最终正文或 JSON 无法生成导航目标，原有修改候选 schema 仍要求非空操作。

纯定位可以完成任务，不伪造空白修改操作。结果保存在现有候选回执 envelope 中，operations=[] 仅表示没有编辑，不提供采纳入口，服务端也拒绝采纳纯导航结果。混合请求在工具提交候选前请求定位；候选仍经过真实引擎预览，并等待用户显式采纳。

浏览器复用阅读助手的实际 Univer 选区和视口实现。提交时立即冻结选区，异步草稿采集、导航模块加载、视口显示前后均检查任务、草稿及视图身份。用户移动选区或修改草稿时不执行过期定位；关闭或取消使正在等待的导航失效。定位失败保留已有编辑候选并明确显示原因。

## 自动验证

101 个相关后端节点分批验证通过，包括真实 Agno 纯导航及混合工具调用、工具授权和深拷贝、旧客户端、能力标记请求冲突、整行视图及模型最终 JSON 伪造拒绝。初始回归中 6 项真实引擎测试使用了过期的本地 dist，重建工作簿桥接后全部通过；另 2 项阅读器初始化回归已修复并复测。

32 个相关前端节点分批通过，包括实际 Univer 选区和内容不变、异步上下文、候选采纳、导航失败与取消。独立复核发现提交前懒加载可能捕获后选中的范围；新增真实 workbook-main 与 Univer 集成测试先失败后通过，验证 A1 提交后立即移到 B2 不会调用模型。复核未报告其他 Critical 或 Important 问题。

浏览器脚本沿用 frontend/smoke/workbook-ai-navigation-smoke.mjs，增加 WORKBOOK_AI_NAVIGATION_CANDIDATE=1 模式，使用真实原生授权、HTTP、Agno 和网格；模型提供方为 ScriptedModel，修订仓储为内存实现。与生产数据库及真实外部模型验收分别计算。

## 保留差异

沿用异步 navigation_requested 回执，浏览器确认后才显示定位成功；未实现来源桌面立即执行并回复模型的 RPC。工作表身份仍采用本地名称，静态只读表格不广告网格导航。工具全量一对一对齐仍在继续。

## 构建与浏览器证据

最终 npm run build（TypeScript + Vite）和 check:budget 通过；Ruff、脚本语法、git diff --check 通过。真实浏览器证据：/workspace/scratch/pr245-candidate-navigation-browser/evidence.json 与 navigated.png。候选模式在 Target!A1 发出整簿授权请求，实际定位 K2000:L2001；截图人工确认第 2000 行 navigation-canary84 可见。采纳入口隐藏，原件 SHA 与草稿操作不变、保存次数为零、无采纳或保存 POST、无页面错误；310 个实际加载 JS/CSS 与磁盘构建 SHA 相符。

复跑：

```sh
WORKBOOK_AI_NAVIGATION_CANDIDATE=1 \
WORKBOOK_AI_NAVIGATION_DIRECTORY=/tmp/pr245-candidate-navigation \
WORKBOOK_AI_NAVIGATION_PORT=4368 \
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
node smart_reporting/report_editor/frontend/smoke/workbook-ai-navigation-smoke.mjs
```
