# Office 原生编辑（report_editor）

`report_editor` 承载 Office 四格式原生编辑：DOCX、XLSX、PPTX、PDF 在浏览器中直接编辑原始文件，
保存为新修订并签发下载链接。报告工作流与旧 Markdown/幻灯片/工作簿编辑器已退役，旧编辑链接返回 `410`。

## 结构

- `native*.py`：原生文档会话、读取模型、预览、保存/导出（`native_publication`）、导入与各格式文件内 AI。
- `pptx_engine.py`、`slides_render.py`、`pptx_*.py`：PPTX 引擎桥接、结构编辑校验与渲染树。
- `slides_*` / `workbook_*`：PPTX、XLSX 文件内 AI 的方案模型、工具与服务。
- 中立能力位于 `smart_reporting/office`：编辑授权与会话、产物身份、结构化候选 Agent、Office 模型，
  以及复杂场景编码任务入口（`office/codex.py`，基于 Agno `CodexAgent`，默认关闭）。
- 前端位于 `frontend/`，入口 `src/unified-main.ts` 只进入 Office 编辑器；管理端为 `src/management`。

## 约束

- `.importlinter` 禁止 Office 模块（含间接依赖）引用已退役的报告工作流、旧编辑器与管理端报告功能。
- 验收或发布门禁失败不阻断已核验身份文件的下载签发，原因写入 `validation.issues`（见仓库根 `AGENTS.md`）。
- 文件内 AI 只提出可预览方案，经用户接受后进入草稿，可撤销；图表只产出 Matplotlib 静态图。

## 开发与验证

```bash
cd smart_reporting/report_editor/frontend
npm ci
npm test -- --run
npm run build
npm run build:management
npm run check:budget
```

构建产物写入 `smart_reporting/report_editor/static`，运行镜像只复制该目录。生产请求由同源 FastAPI API、
HttpOnly 会话 Cookie 和 CSRF 校验保护。原生 Word/PDF 编辑、四格式上传和灰度回滚见
[原生 Office 接入指南](../../docs/archive/office-acceptance/NATIVE_EDITING.md)；
各功能的历史验收与调查记录归档在 [`docs/archive/office-acceptance`](../../docs/archive/office-acceptance/)。

发布前按 [`frontend/smoke/README.md`](frontend/smoke/README.md) 使用真实编辑会话执行冒烟；Vite fixture 不替代真实后端链路。

## 限制

- 原生复杂对象及未适配母版对象只显示并保留，不承诺任意对象可编辑。
- 浏览器回放与引擎回读不等于 Microsoft Office 桌面验收；桌面兼容性需按部署环境执行。
- 真实浏览器多尺寸截图、辅助技术验收和 PDF/Word 视觉验收需要在可用浏览器/渲染环境中执行。
