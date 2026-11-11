# 四格式 AI 助手前端对齐记录

2026-11-11。用户明确要求 AI 助手前端与 GenOffice 和当前入口一起对齐；图标相同或后端有工具不等于助手界面已对齐。

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 格式 | 固定源界面 | 当前可复用部件 | 仍须验证的目标 |
| --- | --- | --- | --- |
| Word | apps/docs/src/renderer/ai/AiPanel.tsx | office-ai-entry、native-word-assistant、native-ai | 同一侧栏承接阅读/编辑/审阅，当前功能区入口和授权选区，输入/任务/候选/采纳 |
| XLSX | apps/sheets/src/renderer/ai/AiChatPanel.tsx | native-office-assistant、workbook-native-ai | 阅读/编辑同侧栏，选区和整表范围明确，真实工具进度和候选撤销/采纳 |
| PPTX | apps/slides/src/renderer/ai/AiPanel.tsx | native-office-assistant、slides-native-ai | 阅读/编辑同侧栏，多选对象/当前页/整稿范围，复杂对象差异与采纳 |
| PDF | apps/pdf/src/renderer/ai/AiPanel.tsx | native-pdf-assistant、native-pdf-review、native-pdf-form-ai | 阅读/审阅/填表与当前入口接入同侧栏，关闭取消与焦点恢复，画布不被挤出 |

共同验收：中文、真实 SVG 图标；保留现有入口；文档画布旁的可折叠助手；明确输入和授权范围；真实 SSE 工具状态与取消；结果/错误/读取边界；候选差异和显式采纳到草稿；迟到回执或输入/草稿变化不能覆盖新状态；窄屏可用。服务由 Agno 驱动，不引入固定源桌面 AgentLoop/provider 循环。不能用额外确认弹窗代替当前任务的完整候选预览。

本轮先落地 PDF dock，其余三格式保持开放；不将共享横向面板的样式统一当成四格式侧栏完成。各格式能力继续按真实工具注册与实际文件验证逐项补齐。

## PDF 首次右侧栏落地证据

PDF已将阅读/批注审阅/表单填写停靠到同一360px右侧助手，原功能区入口打开对应功能，切换和关闭使用原控制器取消，窄屏抽屉。最终build浏览器3链通过，画布旁布局/功能切换/close/780px窄屏均实际验证，详见 `NATIVE_PDF_AI_FORM_ACCEPTANCE.md`。这只证明PDF本轮范围，不证明Word/XLSX/PPTX侧栏、完整对话历史/附件/所有复杂工具已等价。固定源可调整宽度等完整交互仍需后续逐项验证补齐。

### 2026-11-11 浮动窗口与视觉细化

- Word/XLSX/PPTX 共用停靠栏与 PDF 停靠栏接入相同浮动交互：右上角切换浮动/停靠，标题栏拖动，拖动手柄支持方向键移动。切换只改变位置，保留原面板 DOM 与任务控制器。
- 浮窗使用视口边界约束；缩窄窗口后重新限制位置与尺寸，保持标题栏操作可达。默认仍为右侧停靠，本轮不增加位置持久化。
- 保留主题色，细化分段导航、标题层次、轻边框结果卡片、圆角底部输入框、焦点反馈与阴影；沿用原始来源图标。
- 针对性验证：floating / office-task-dock / pdf-ai-dock / office-assistant-panel 共 9 项通过；`tsc --noEmit` 通过。
- 浏览器共用外壳验证通过：桌面拖动、390px 窄屏边界、一键停靠，page errors 为空。证据 `/tmp/office-floating-browser.json`；截图 `/tmp/office-floating-desktop.png`、`/tmp/office-floating-narrow.png`。此为隔离外壳场景，不代表重跑四格式 AI 模型或文件编辑验收。
- 本轮未重新生成发布构建；历史冻结构建不包含这些新改动。

浮动增量实际构建补记：`/tmp/office-floating-final-build.log` Vite44.57秒通过。PDF实际built验收 `/tmp/office-floating-pdf-built-20261111/summary.json` ok=true，5场景、37实际JS SHA匹配，manifest `a2b17e0162159f0a31baaa3e8d102e1c185662a666f4a5f6f7ccd259793dfae8`。候选状态浮动、拖动、390px窄屏边界与停靠恢复均通过；指令/草稿保留，真实Agno ScriptedModel填写/预览/采纳及取消/切换仍通过，错误三数组为空。root独立重核manifest与全部37资源。此构建全局预算仅workbook-engine433.5>428KiB失败；不能把PDF局部成功表述为全局通过。后续透视功能分包将通用引擎压回预算，最终构建证据由备注增量记录。
