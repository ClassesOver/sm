# XLSX AI 结构 DSL 与输入对齐增量（2026-11-15）

本批继续 PR #245 已确认的四格式工具一对一方案，不声明全量完成。
固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，重新读取 `packages/xlsx-gateway/src/domain/workbook-dsl.ts` 的四个行列 schema、workbookCommandBatchSchema，以及 `apps/sheets/src/renderer/ai/tools.ts::parseAuditAddress`。搜索空白直接使用 Node 的 String.trim。

## 接线与行为

| 源入口 | Agno 入口与实际执行 | 本批边界 |
| --- | --- | --- |
| insert_rows / delete_rows | propose_operations → workbook_ai_structure.translate_row_column_operation → applyRowColumnOps → 原生共享引擎 | 行号从1开始，count必填1–500；整簿授权。 |
| insert_cols / delete_cols | 同上 | 列名A–XFD，count必填1–100；整簿授权。 |
| sort_range / merge_cells | 原提案链，向引擎发送规范化后的矩形 | 保留非目标内容与既有合并；小写/绝对引用/倒序输入兼容是本地适配，不能声称源DSL schema也接受所有这些写法。 |
| trace_precedents / trace_dependents | 原注册工具 → 共享单格规范化 → 原授权追踪 | 小写、合法绝对地址和首尾空白进入真实规范地址；仍拒绝范围、越界和未授权依赖。 |
| find_cells | 原注册工具 → Node原生query.trim() → 原生匹配 | BOM会去除，NEL不会；空白查询返回invalid，errors_only保留源行为。 |

源workbookCommandBatchSchema明确不允许结构操作与内容/布局同批。新增四个源结构DSL遵循该规则；也拒绝与原生kind混批，避免未经分类的原生操作使冻结坐标变化。已有全原生操作兼容路径不变。原始人工草稿作为候选base保留，由实际引擎在base之后顺序执行结构操作。

## 引擎修复

实际末行/末列插入探针发现：旧引擎会把已存储单元格移到A1048577/XFE1且预览返回成功。补共享StructuralShiftError检查，拒绝移出Excel网格的存储行、单元格和合并端点；合法移动到最后一行/列以及边缘删除仍可执行。没有在Python另写一套文件修改器。

引擎旧sheet-ops用例把插入后的dimension断言为A1，但实际值为A1:B4；使用原始未修改引擎重跑同节点仍失败。已修正过时预期为包含实际数据/公式的A1:B4，没有更改产品dimension代码。新合并测试最初使用既有parser不支持的自闭合sheetData夹具，改为配对空sheetData后在原始引擎复现真正的缺少越界检查；失败日志保留在工作区scratch。

## 验证

- 新结构输入/实际预览初始27失败、3通过，修复后30通过；随后新增末行/列实际引擎探针2项先失败后修复。
- 追踪/特殊空白专项14项先失败，修复后两份完整输入/搜索文件42项通过。
- 最终8份受影响Python文件158项通过，38.62秒；含真实Agno ScriptedModel → 结构指南 → propose_operations → 实际引擎预览 → 显式accept → 独立openpyxl回读，确认人工草稿、跨表公式、合并和原件保留。该证据不等同真实provider、生产DB或浏览器端到端。
- 4份定向引擎测试39项通过；引擎typecheck和生产bridge bundle通过。目标Ruff、Node语法、diff空白检查通过。未重复完整项目测试。

select_range/create_document、其余结构/格式DSL、稳定sheet身份、完整指南/返回格式和其他三格式继续开放。前一批列出的trace直接地址、查询Unicode trim、排序/合并小写范围转发缺口由本批覆盖；其余历史边界不变。

独立复核未发现Critical/Important问题；根据复核建议补强四个真实引擎用例的同表公式断言并单独复跑。复核另确认既有局限：没有边缘存储格时，公式=A1048576在插入行后仍可能变为=A1048577。本批存储格/合并边界检查不等同完整公式、整行整列引用或其他元数据边界安全，相关能力继续按缺口记录。结构源与修正上游测试的本地哈希已更新，新边界测试登记至本地适配清单。
