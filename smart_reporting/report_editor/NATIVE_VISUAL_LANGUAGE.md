# 原生 Office 编辑器统一视觉语言

2026-11-09。Word / Excel / PowerPoint / PDF 四种原生编辑器共用一套视觉语言，**以 Markdown 报告编辑器为基准**。

## 规则

- 唯一 token 源：`frontend/src/office-theme.css` 的 `--office-*`，全部派生自 `style.css` 的 md 设计 token（`--color-*`、`--radius-*`、`--font-size-*`、`--motion-*`）。
- 格式样式（`docx.css`、`workbook.css`、`pdf.css`、`pdf-ribbon.css`、`slides.css`）只描述结构差异；外壳颜色、控件尺寸、交互状态一律引用 `--office-*`。
  不得再引入格式专属强调色（旧 PDF/PPTX 青绿色已移除）。
- 文档内容颜色不受影响：Word 文档内 `--surface/--text`、PDF 高亮/便签/搜索命中/夜间模式、表格单元格格式等保持原样。
- 四个入口在各自格式样式之后导入 `office-theme.css`（`docx-main.tsx`、`workbook-main.ts`、`pdf-main.ts`、`slides-native-ribbon.ts`）。

## md 基准映射

| md 来源（style.css） | Office token | 用途 |
| --- | --- | --- |
| `--color-primary` / `--color-primary-soft` | `--office-accent` / `--office-accent-soft` | 选中标签、导航悬停、主操作、PPTX 选择框 |
| `.report-actions button:not(.is-primary):hover`：`#f2f6f9` + `border-strong` | `--office-hover-bg` / `--office-hover-border` | Ribbon 按钮悬停 |
| `.report-actions button[aria-pressed=true]`：`primary-soft` + `border-strong` + `ink-2` | `--office-pressed-*` | 按下/开启状态 |
| `.report-actions button:disabled`：`opacity .55` | `--office-disabled-opacity` | 禁用 |
| `.report-actions button:focus-visible`：`2px #8fc9df` | `--office-focus-ring` | 焦点环 |
| `.toolbar-group + .toolbar-group::before`：`#dfe8ef` | `--office-separator` | Ribbon 分组分隔 |
| 页面底色 `--color-bg`、`.editor-surface` 边框与阴影 | `--office-canvas` / `--office-page-border` / `--office-page-shadow` | 文档画布与纸面 |
| `.report-actions button[data-action=save]` | `--office-accent` / `--office-accent-hover` | 主操作按钮 |

外壳：四种格式都嵌入同一 md 纸面卡片（PPTX 不再全宽贴边）；顶部栏中的文件链接（下载原件/XLSX）与 md 工具栏按钮同形；状态栏、侧栏、提示条共用同一底色与字号。

## 守卫

`frontend/src/office-visual-language.test.ts`：token 必须派生自 md 值；四个 Ribbon 的选中/悬停/按下/禁用/焦点/分隔引用同一组 token；PDF/PPTX 不含旧青绿色或内联主题；画布、纸面阴影、状态栏共用；文档内容颜色不被改写；PPTX 画布选择框读取 `--office-accent`。
