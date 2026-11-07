# Word Layout 段落间距验收（2026-11-06）

## 已实现

- Layout「段前 / 段后」复用 Home 的 `spaceBefore` / `spaceAfter` attrs 和 `setParagraphSpacing` operation；来源 `blockId` / hash、可编辑性及范围验证保持在原链路。
- 输入单位为 pt；允许 0–720 pt，精度 0.05 pt（对应整数 0–14400 twips），不更改 Home 原有 12 pt toggle / 行距预设。
- 显示「继承 / 自动 / 混合」，显式 0 不被当成继承；自动状态显式输入同值仍清除自动间距。空、非有限、负数、超范围和非整数 twips 精度输入均不修改草稿。
- Enter / 失焦提交，Escape 取消。focus 时捕获段落集合及来源身份；仅 selection 变化仍绑定原目标，document 变化取消过期提交。字段间焦点切换不替换下一输入框。每次编辑独立 Undo，跨段一次提交保持原子性。
- 只读 / 保存锁禁用并在提交时复核；跨表格、无来源新段及重复 docxIndex 不启用。跨段选择结束于下一段文本 offset 0 时不包含下一段。
- 继续使用 NativeDraft 的持久化、Undo/Redo 和 `replayDocxOperations` 刷新恢复；回放增补 spacing 字段、来源 hash 及只读校验。

## 已执行的针对性验证

- `npm --prefix smart_reporting/report_editor/frontend test -- --run src/docx-spacing.test.ts src/docx-operations.test.ts src/docx-ribbon.test.ts src/workbook-ribbon.test.ts src/workbook-native.test.ts src/workbook-native-recovery.test.ts`
  - Word/Excel 前端合并选择 **111 passed**；Excel 后续独立选择三个测试文件 **31 passed**，中文 locale 注入单测 **1 passed，2 skipped**。
- `.venv/bin/pytest smart_reporting/reporting/tests/test_docx_engine_bridge.py -k spacing -q`
  - 24 passed，70 deselected，19.53 s。包含非预设整数 twips、显式零、上界、自动间距和未触及 XML 属性保留，以及非法值拒绝。
- `.venv/bin/pytest smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py -k 'docx or xlsx'`
  - **2 passed，2 deselected**。Word `12.55 pt / 0 pt` 与 Excel 操作走 HTTP 保存/下载/重开；发布验收仍为失败状态且产物链接保留。
- `.venv/bin/pytest smart_reporting/reporting/tests/test_workbook_engine_bridge.py::test_workbook_replacement_cell_edits_preserve_legacy_notes_and_untargeted_parts -q`
  - **1 passed**。独立 openpyxl 与 ZIP 检查保留公式、数值/布尔、批注作者/VML、非目标工作表与 ZIP 部件，源文件不变。
- Bridge spacing 测试前已用 esbuild 只重建 `smart_reporting/reporting/slides_engine/dist/edit-docx.mjs`；`run_bridge` 优先读取此 dist 文件，避免以旧 bundle 验证新源码。
- 真实 Chromium 浏览器操作已覆盖 Word 精确段间距输入及保存、Excel 官方 Find/Replace 面板、当前表两处替换、保存、下载文件及重开修订 2。用 python-docx / openpyxl 独立读取下载产物，确认 DOCX `251/0 twips`、XLSX 两处 `alpha → beta` 及未修改公式、格式、合并范围、定义名称和第二工作表。浏览器路由使用隔离合成授权宿主，**不是生产授权/数据库验收**。

## 构建与未覆盖范围

- 标准 `npm run build`、`npm run check:budget`（中文 locale 修复后重跑）和 `npm run test:budget` 通过；`npm run build:slides`、该包体检查也在 locale 修复前通过。保留既有 chunk/circular chunk 警告。
- 未部署；未构建完整新应用镜像；未做生产数据库、生产租户身份/权限、外部宿主或 Microsoft Office 桌面验收。
- 浏览器仍观察到 Excel 新修订载入后显示「有未保存修改」。本轮保留现有 mutation 捕获行为，未完成该状态来源调查，不能据本轮将整个编辑器标记验收通过。浏览器期间的定位超时、剪贴板焦点错误与一次导航中断均未计作成功；重新观察并执行后的文件结果才用于上述结论。
- Ruff：HTTP 与 XLSX 测试文件通过；DOCX bridge 测试文件检查仍返回 30 条既有 E702/I001，和 HEAD 基线数量/类别一致，未扩展为无关格式清理。HTTP 定向检查退出时出现 Agno tracing 的关闭日志流错误，pytest 本身为 2 passed、退出码 0。
- 未解决其他 Word/Excel 功能区缺口（Word 表格样式/合并/边框/复杂表格、批注/审阅/引用/邮件/完整上下文选项卡、Excel 批注读状态/编辑、保护状态回读、筛选/数据工具、Chart Design 上下文等）；仍须按源命令 inventory 逐项补齐。富文本替换明确拒绝，避免静默格式丢失。
- 不提供负间距、自动 / 继承模式切换、其他间距单位或非预设精确行距；空输入是取消修改，不是重置继承。
- 未修改开关或签发链；未提交 / push。
