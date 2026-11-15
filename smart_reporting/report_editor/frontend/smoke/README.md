# Office 编辑器冒烟

本目录只保留 Office 原生编辑器（DOCX、XLSX、PPTX、PDF）与管理后台的浏览器冒烟。旧 Markdown
报告编辑器、证据浏览器 fixture 和旧幻灯片编辑器冒烟已随报告工作流退役；历史记录见
`docs/archive/reporting/`。

## 通用约定

- 在 frontend 目录运行：先 `npm run build`；用到桥接引擎的脚本需先 `npm run bundle:bridges`
  （workbook_engine、slides_engine）。
- 命名约定：
  - `*-smoke.mjs`：完整操作链路。
  - `*-layout.mjs`：视口与布局检查。
  - `*-probe.mjs`：定向诊断。
  - `*-server.py` / `*-fixture.*`：本地数据或服务替身。
  - `*-verify.py`：用 python-docx、openpyxl、python-pptx 或 pypdf 回读保存结果。
- 大部分脚本使用 Vite 前端加 Playwright 替身 context/file 路由，保存经真实 `patch_*` 引擎。
  它们不替代权限、会话与签发链路的真实后端验收。
- 如果 Playwright 版本与预装浏览器不一致，用 `REPORT_EDITOR_CHROMIUM_EXECUTABLE` 指向本机 Chromium。
- 截图与回读结果写入项目 `output/`，不提交到 Git。

## 分组

- `docx-*`、`word-*`、`office-docx-*`、`native-word-*`：Word 编辑、审阅、页面布局与 AI。
- `workbook-*`、`office-xlsx-*`、`office-workbook-*`：Excel 单元格、图表、数据透视、打印与 AI。
- `pptx-*`、`slides-*`、`office-pptx-*`、`office-slides-*`：PowerPoint 画布、对象、放映与 AI。
- `pdf-*`、`office-pdf-*`：PDF 阅读、注释、表单、签名、页面与转换。
- `office-*`（其余）：跨格式外壳、对话框、助手窗口与导航。
- `management-*`：管理后台。`*-postgres-smoke.mjs` 需要真实 PostgreSQL。

## 2026-11-09 对齐批次真实浏览器验收

- `workbook-ribbon-gui-smoke.mjs`：XLSX 缩进、格式刷（单次）、行高/列宽对话框、自动调整行高、复制→粘贴；
  保存经真实 `patch_office`，用 openpyxl 回读。`WORKBOOK_RIBBON_CASE` 可选：
  - `cells`：插入单元格（下移）与删除单元格（左移）。
  - `protect`：保护工作表、保护工作簿，以及保护后编辑被拒绝。
  - `sort`：自定义排序。
  - `fill`：填充与定位。
  - `numfmt`：设置单元格格式（数字）。
  - `formulas`：显示公式、计算选项与开始计算。可设 `WORKBOOK_SMOKE_SCREENSHOT` 保存网格截图。
- `docx-insert-gui-smoke.mjs`：Word 封面、分页符、空白页、插入表格并输入；保存经真实 `patch_docx`，
  用 python-docx 与 XML 回读。`DOCX_INSERT_CASE` 可选：
  - `sections`：分节符与多节页面设置。
  - `format`：选中文字局部格式。
  - `followup`：多修订续验收。替换封面并改占位文字、插入表格；重开后编辑并保存表格空单元格，再删除封面。
