# XLSX 透视缓存来源工作表删除浏览器验收

在 `smart_reporting/report_editor/frontend` 目录、最新生产资源已经构建后运行。本脚本不执行构建，使用端口 `4236` 启动 Vite preview，并用 Playwright Chromium 加载实际构建资源。

```bash
node smoke/workbook-pivot-sheet-removal-built-smoke.mjs
PIVOT_REMOVAL_ALLOW=1 node smoke/workbook-pivot-sheet-removal-built-smoke.mjs
```

- 默认模式：openpyxl 创建真实 Pivot Table、Cache Definition 与关系，存活的 `Pivot` 引用 `Source`。右键删除 `Source` 必须被拒绝；撤销/重做后来源表仍在、本地草稿及保存状态不变、不触发保存请求。
- 允许模式：右键删除无引用的 `Unused`，检查撤销/重做、草稿刷新恢复、保存和修订 2 重开。保存路由调用真实 Python `patch_office`，用 openpyxl 和 ZIP 独立回读，确认 Source/Pivot 保留、源值保留、透视表仍指向 Source，以及全部 pivot/cache 部件集合和原始字节、Pivot 工作表和样式字节不变。
- context/file/save HTTP 响应由脚本路由提供；实际页面、交互、草稿机制、Python patch 和 XLSX 回读均执行真实逻辑。本脚本不等价于数据库修订注册或鉴权服务集成测试。
- 验收要求所有加载的编辑器 JavaScript 返回 200，其 SHA-256 与磁盘构建资源一致，且无页面异常。
