# Report Editor

`report_editor` 为 document 和 PPTX 复用同一主界面，按产物类型加载编辑区域和工具栏。document 以 Markdown 为唯一权威内容，PDF/Word 由现有 reporting renderer 从保存后的 revision 生成；PPTX 基于已核验身份的原始文件编辑并保存为新修订。

PPTX 在同一 shell 内按需加载 React/Konva 画布，支持对象选择、拖动、角点缩放、文字临时预览、页面排序、商务主题、母版/版式读取与版式切换，以及动画效果、触发方式、持续时间和延迟调整。画布复用固定版本 GenOffice 的静态渲染模块及 Apache-2.0 声明，PDF 作为画布加载失败时的兼容预览。

Ask AI 候选经预览、采纳后进入待保存修改，可撤销；已登记数据图表复用 Matplotlib 改图服务，按图片内容身份与冻结 manifest/trace 唯一匹配，生成的 PNG/JPEG 经采纳后替换原图片对象。AI 配图独立生成并确认加入，不作为数据图表来源。保存请求期间锁定编辑；保存成功后通过“打开新修订”继续编辑，避免旧文件身份覆盖。未修改对象在文件往返中保留，验收和追溯告警不阻止已核验身份的产物签发。

报告工作流在复用需求澄清、取数和冻结分析证据后，按持久化的 `deliveryFormat` 路由到文档步骤或 PPT 步骤。PPT 从发现图谱规划页面，复用静态图表任务及 manifest/trace 归档，不经过文档章节成稿；默认仍是 document，恢复和重试沿用首次冻结的格式。
历史暂停的文档任务在末端恢复时迁移已存格式，缺少格式字段时沿用 document。幻灯片图表优先采用冻结分析的明确归属；同数据集、同指标的多个分析无法消歧时保留文字证据，不猜测配图。发布清单重新编号后，图表改图仍通过图片身份关联原始 trace 编号。

生成与编辑桥接均先写出 PPTX，再执行版式审查；审查异常作为 `validation.issues` 返回，保留可核验文件的下载。图表页采用左右双栏，过量正文保留并返回版式告警。AI 配图沿用 DashScope 凭据，模型通过 `AGENT_REPORT_SLIDES_IMAGE_MODEL` 独立配置（默认 `qwen-image-plus`）。DashScope 与 Token Plan 使用同源原生多模态生成接口，自定义其他服务仍使用 OpenAI images 兼容接口；提供方拒绝或超时时返回可公开的状态与原因，保留原页面，不自动换模型。当前账户可用模型须以实际配置和模型清单为准。

## 能力

- Milkdown Crepe 即时编辑、官方目录、A4/宽屏和移动端布局。
- CAS 自动保存、离线草稿恢复、revision 历史与按需正文读取。
- 保存状态显示最近保存时间和待同步编辑次数，存在未保存内容时提供离开保护。
- 保存冲突提供基准/本地/远端差异，可保留本地、采用远端或编辑合并后重试。
- 导出设置支持封面、目录、页眉页脚和页码；每次导出创建新 revision。
- 导出支持版本备注、文件名/大小、请求编号、120 秒超时和失败重试。
- 内置医院整体运营报告模板与常用章节块。
- AI 改写进入 Diff Review，用户接受后才写回编辑器。
- AI 改图（`AGENT_REPORT_EDITOR_CHART_AI_ENABLED`，默认开启）：对登记图表用自然语言做呈现类调整（仅 Matplotlib 静态图），前后对比接受才替换，导出新版本后与原图同样可追溯；超出已登记作图数据的要求逐条说明后跳过。
- AI 改表（`AGENT_REPORT_EDITOR_TABLE_AI_ENABLED`，默认开启）：支持已有确定性事实绑定的登记表格，输入要求或套用模板，逐格审阅后接受替换。仅有原始补证单元格绑定的表格暂不支持。
- 图表入口：鼠标移到图片/登记表格上（会出现描边），或点击、键盘聚焦后，使用图/表右上角的“AI 改图 / AI 改表”按钮；面板首屏“从推荐开始”区分「一键」（立即出预览，不经过 AI）与「AI」（先填入要求，可补充后发送）；图片预览内的改图按钮和双击表格入口仍保留。服务端默认开启对应开关；部署或重启加载新配置后，刷新编辑页即可显示入口；显式设为 `false` 可关闭对应入口。
- Ask AI 使用情况埋点：通过 `/api/events` 上报 `ai_suggestion_used`、`ai_edit_started`、`ai_edit_finished`、`ai_edit_adopted`，只含面板类型（chart/table）、来源（start/dialog/refine/free）、类型（oneclick/ai）、固定推荐标识、结果与耗时，不含用户输入或建议原文；服务端写入 `report_editor_event` 日志，可据此统计各推荐的使用率、成功率与采用率。
- 章节拖拽/键盘排序、搜索替换、图片预览、软告警和无障碍焦点管理。
- 首次载入提供明确加载态；网络故障、会话过期和未知错误显示可重试的可访问错误面板。
- 编辑页可签发并复制绑定当前修订版的分享编辑链接，有效期 30 天；获得链接的人可编辑该修订版。

## 开发与验证

```bash
cd smart_reporting/report_editor/frontend
npm ci
npm test -- --run
npm run build
npm run build:slides
npm run check:budget
```

构建产物写入 `smart_reporting/report_editor/static`，运行镜像只复制该目录。生产请求由同源 FastAPI API、HttpOnly 会话 Cookie 和 CSRF 校验保护。

发布前按 [`frontend/smoke/README.md`](frontend/smoke/README.md) 使用真实编辑会话执行桌面端、移动端和导出冒烟；Vite fixture 不替代真实后端链路。

发布与恢复操作分别见 [`docs/runbooks/report-editor-release.md`](../../docs/runbooks/report-editor-release.md) 和 [`docs/runbooks/report-editor-recovery.md`](../../docs/runbooks/report-editor-recovery.md)。

## 限制

- 不支持任意 JavaScript 或编辑器内图片上传。
- 图片仅允许读取当前 job 登记且 SHA-256 未变化的 PNG/JPEG，以及同一修订版改图登记（`draft/.chart-edits.json`）中身份一致的改图图片。
- PPTX 未登记、身份匹配不唯一或追溯已失效的图片保持只读；原生复杂对象及未适配母版对象只显示并保留，不承诺任意对象可编辑。图表候选需先在候选面板核对，采纳后保存才替换画布中的图片。
- 商务主题和版式切换保存后在新修订中更新；浏览器字体与桌面 PowerPoint 字体环境可能不同。
- PPTX 浏览器回放与引擎回读不等于 Microsoft PowerPoint 桌面验收；真实模型报告端到端及桌面兼容性仍需按部署环境执行。
- 真实浏览器多尺寸截图、辅助技术验收和 PDF/Word 视觉验收需要在可用浏览器/渲染环境中执行。
