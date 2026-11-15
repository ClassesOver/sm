# 2026-09-26 编辑器导出链路修复报告

## 结论

编辑器全链路打通：**导出 200，revision-3 产出（12 页 PDF + DOCX，8 图全嵌入，citation 标记 0 泄漏）**。
本报告覆盖用户报告的 4 个问题（引用显示/导出报错/搜索高亮/签发时效）与导出链路上逐个击破的 5 个
隐藏缺陷。全程真实链路验证（AgentOS 服务 + 编辑器 API + runtime 渲染）。

## 用户报告问题 → 修复

| 问题 | 根因 | 修复（commit） |
|---|---|---|
| 引用不需要显示 | `.report-citation-marker` 渲染"引用"胶囊；PDF 侧本就剥离标记 | CSS display:none（与 section 一致）+ 打印样式清理（`e50d69d`） |
| 导出 Word/PDF 报错 | 5 个串联缺陷（见下） | 5 个修复 |
| 搜索没有文本高亮 | 高亮直接改 ProseMirror DOM，被 MutationObserver 回滚 | 新增 `search-highlight-plugin.ts`（decoration 方式），search.ts 增加 `applyHighlight` 回退（`e50d69d`） |
| 签发时间默认永久 | `EDITOR_GRANT_TTL = 10min` | 改 10 年（存储列禁 NULL，远端日期表达永久）（`e50d69d`） |

## 导出链路 5 个串联缺陷（逐个被真实 run 暴露）

1. **Milkdown 序列化转义协议标记**（`450acdb` 前已提交 `e50d69d`）：
   序列化器把 `[[section:section_001]]` 写成 `\[\[section:section\_001]]`，导出渲染报
   "章节标识与提纲不一致"。修复：前端 `restoreProtocolMarkers()` 存储前还原；存量 draft 已用脚本还原（22 个标记）。
2. **草稿目录图片相对解析失败**（`cf5028e`）：draft 在 `revision-N/draft/`，图片在报告根目录。
   修复：`_images` 按 job render.images 清单后缀回退。
3. **HTML 内联图片同样按清单回退**（`8a0c0b7`）：`_inline_images` 的 `<img>` 解析也认 source_parent。
4. **Word 封面/目录校验不尊重导出设置**（`7b73833`）：`_editorExportSettings` 允许关封面/目录，但
   `_postprocess_docx` 无条件硬校验封面标题与目录标题。修复：按 include_cover/include_toc 跳过。
   另：前端导出设置默认勾选封面（对齐经过完整验收的形态）。
5. **data URI 被自定义 fetcher 拒绝**（`6636a05` + `1f53af7`）：`_inline_images` 产物（html_body）
   原是死值，改喂给 PDF/Word 两路后，PDF 的自定义 url_fetcher 拒绝非 file: URL，data URI 被静默
   丢弃 → PDF 无图 → 验收失败。修复：data URI 交 weasyprint 默认抓取器。附带：验收失败现在
   WARNING 输出完整 validation 明细（原报错吞掉一切细节）。

## 验证

- 前端：178 项单测全绿（新增 `restoreProtocolMarkers` 回归测试）；`npm run build` 产物已上线
- 后端：`test_report_runtime.py` 42 passed、`test_report_editor.py` 26 passed；
  `test_reporting_code_agent_trajectories.py` 1 失败为 HEAD 存量（stash 对照确认）
- 端到端：`POST /api/export` → 200；revision-3 PDF 12 页、poppler 确认 8 图嵌入、
  citation 标记 0 泄漏；DOCX 双产物齐备

## 已知遗留

1. **cover=false 的 LibreOffice 空白页验收**：无封面导出模板仍保留封面分节标记，LibreOffice
   转换出现空白首页判定。封面勾选为默认（已对齐验收完整形态），无封面支持留作后续模板级改造
2. 编辑器会话 TTL 仍 8 小时（设计内）
3. 前一报告的观察项不变（coverage 语义硬门、edit_invalid 偶发等）

## 提交链

`e50d69d`（引用/标记还原/搜索高亮/永久 grant）→ `cf5028e` → `8a0c0b7` → `7b73833` →
`6636a05` → `1f53af7`（均含根因说明）

## 原始数据

- 导出验证脚本：`/tmp/verify_editor_export.py`（grant 兑换→CSRF→export 全链路）
- 渲染复现：`/tmp/repro_render_cli.py`（直接调 runtime CLI，隔离服务层）
- 导出产物：`…/report-run-64879d…/revision-3/`（PDF 3.18MB + DOCX）
