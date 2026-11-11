# XLSX 透视缓存来源工作表重命名浏览器验收

在 `smart_reporting/report_editor/frontend` 目录、最新生产资源已由主任务构建后运行。本脚本不执行构建，使用端口 `4238` 启动 Vite preview，并通过 Playwright Chromium 加载实际构建资源。

```bash
node smoke/workbook-pivot-sheet-rename-built-smoke.mjs
PIVOT_RENAME_NAMESPACE=alias node smoke/workbook-pivot-sheet-rename-built-smoke.mjs
```

- openpyxl 创建真实 Pivot Table、Cache Definition 与关系；默认模式使用默认 SpreadsheetML 命名空间，`alias` 模式把缓存定义改为 `q:` 前缀。
- 通过真实页签 UI 将 `Source` 改为 `财务 O'Brien & 数据`，覆盖中文、单引号与 XML 实体；检查撤销、重做和本地草稿刷新恢复。
- 保存路由调用真实 Python `patch_office`。独立 openpyxl 回读确认源值、透视表及缓存来源新名称；ElementTree 直接读取缓存 XML 的 `worksheetSource@sheet`。默认命名空间下缓存 XML 仅该属性发生变化；别名模式精确允许既有读取层（`workbook_engine/packages/xlsx-engine/src/zip.ts` 的 `normalizeOoxmlPartPrefix`，实现位于 `src/xml.ts`）将 `q:` 元素改为默认命名空间并补上 `xmlns:r` 声明，其他 XML 文本必须完全一致。ZIP 部件集合不变，除 workbook/cache definition 外所有部件保留原字节，包括 pivot table、关系、源工作表、透视工作表和样式。
- 明确导航到修订 2 并读取实际保存字节，再尝试删除重命名后的来源页。删除须被拒绝，撤销/重做后页签、草稿、保存状态保持不变，保存请求总数仍为 1。
- context/file/save HTTP 响应由脚本路由提供；页面、交互、草稿、Python patch 与 XLSX 回读均执行真实逻辑。本脚本不等价于数据库修订注册或鉴权服务集成测试。
- 所有加载的编辑器 JavaScript 必须返回 200，SHA-256 与磁盘构建资源一致，且无页面异常。

浏览器运行使用主任务确认后的生产构建；输出记录两种命名空间的具体检查结果。
