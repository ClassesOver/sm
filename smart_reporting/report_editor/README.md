# Report Editor

`report_editor` 是报告 Page 的 Markdown 编辑层。Markdown 是唯一权威内容；编辑器不会生成 HTML 报告产物，PDF/Word 由现有 reporting renderer 从保存后的 revision 生成。

## 能力

- Milkdown Crepe 即时编辑、官方目录、A4/宽屏和移动端布局。
- CAS 自动保存、离线草稿恢复、revision 历史与按需正文读取。
- 保存状态显示最近保存时间和待同步编辑次数，存在未保存内容时提供离开保护。
- 保存冲突提供基准/本地/远端差异，可保留本地、采用远端或编辑合并后重试。
- 导出设置支持封面、目录、页眉页脚和页码；每次导出创建新 revision。
- 导出支持版本备注、文件名/大小、请求编号、120 秒超时和失败重试。
- 内置医院整体运营报告模板与常用章节块。
- AI 改写进入 Diff Review，用户接受后才写回编辑器。
- 章节拖拽/键盘排序、搜索替换、图片预览、软告警和无障碍焦点管理。
- 首次载入提供明确加载态；网络故障、会话过期和未知错误显示可重试的可访问错误面板。

## 开发与验证

```bash
cd smart_reporting/report_editor/frontend
npm ci
npm test -- --run
npm run build
npm run check:budget
```

构建产物写入 `smart_reporting/report_editor/static`，运行镜像只复制该目录。生产请求由同源 FastAPI API、HttpOnly 会话 Cookie 和 CSRF 校验保护。

发布前按 [`frontend/smoke/README.md`](frontend/smoke/README.md) 使用真实编辑会话执行桌面端、移动端和导出冒烟；Vite fixture 不替代真实后端链路。

发布与恢复操作分别见 [`docs/runbooks/report-editor-release.md`](../../docs/runbooks/report-editor-release.md) 和 [`docs/runbooks/report-editor-recovery.md`](../../docs/runbooks/report-editor-recovery.md)。

## 限制

- 暂不支持 Plotly.js、任意 JavaScript 或编辑器内图片上传。
- 图片仅允许读取当前 job 登记且 SHA-256 未变化的 PNG/JPEG。
- 真实浏览器多尺寸截图、辅助技术验收和 PDF/Word 视觉验收需要在可用浏览器/渲染环境中执行。
