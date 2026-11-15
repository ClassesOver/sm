# XLSX 表格所属工作表删除：前端原子性

固定来源：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。后端已有 TableName[ 依赖检查；前端原生删除必须在修改快照和草稿前拒绝，不能依赖保存失败兜底。

## 本轮实现

`frontend/src/workbook-table-sheet-removal.ts` 从可信源模型取得目标表格名称，并结合当前实时表格名、存活工作表的稀疏公式、CF/DV 和定义名称预检。未投影的共享/特殊公式和不完整 CF/DV 使用可信原 XML；已经清除的普通实时公式不会被旧 XML 误拒绝。删除页本地名称跳过，存活页共享同一表格 part 时保留其名称依赖。与固定源一致使用大小写不敏感的 TableName[ 检查，可能保守拒绝同形字符串，未声称完整结构化引用语义解析。

`workbook-main.ts` 只向预检传入与基线身份匹配的源模型及原 XML。`workbook-data-validation-structure.ts` 为原生工作表删除产生的 TABLE/CF/DV 内部 mutation 登记实际 params 对象身份，并在撤销恢复时保留表格元数据；没有用命令名称字符串绕过写入保护。

## 证据

- RED `/tmp/workbook-table-sheet-removal-main-red3.log`：命令返回 false，但工作簿已经改变。
- 定向 GREEN `/tmp/workbook-table-sheet-removal-directed-final.log`：8 passed / 50 skipped，含稀疏引用拒绝快照/草稿一致、清引用后删除、完整表格元数据撤销恢复、redo 和实际引擎保存。
- 生产构建 `/tmp/office-cjk-expanded-build.log` 与 budget/contract exit0；workbook-main DNXdHCvd 244.4 KiB、engine B1-xJNXH 372.2 KiB。
- `/tmp/workbook-table-removal-built-refusal-final.log` exit0：真实 Chromium，删除拒绝时页签、撤销重做、草稿、保存状态不变；114 次 JS 200+SHA，无页面错误。
- `/tmp/workbook-table-removal-built-clear-final.log` exit0：纯界面将 Other!C1 的结构化引用改为数值1，再删除 Source，undo/redo、草稿恢复、保存和明确 revision2 重开成功；真实 Python ZIP 回读只剩 Other，表格 part 与引用均删除，B1:B5 和 styles 保留。操作顺序 applyCellEdits → applySheetEdits；342 次 JS 200+SHA，无页面错误。

HTTP revision/context/save 由探针替身路由提供，浏览器与 Python 文件操作真实执行，未声称生产 HTTP 全链路测试。

## 仍有缺口

目标表格来源无法完整投影时仍保守拒绝删除，尚未补齐只读/未投影表格名称身份提取。透视缓存来源工作表删除依赖另有缺口，不属于本轮完成范围。
