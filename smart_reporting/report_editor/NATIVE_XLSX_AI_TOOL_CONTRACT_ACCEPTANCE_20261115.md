# XLSX AI 工具契约对齐增量（2026-11-15）

本批属于 PR #245 的四格式工具一对一对齐计划，只关闭下面的 XLSX 契约差异。
固定 GenOffice 源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，实际重新读取：

- `apps/sheets/src/renderer/ai/tools.ts`：工具声明、read_range/read_cells/read_formats/find_cells 输入处理。
- `apps/sheets/src/renderer/ai/workbook-search.ts`：buildMatcher、cellValueText、ERROR_VALUE_RE、匹配后上限截断。
- 本地同版本 vendored `workbook_engine/packages/xlsx-engine/src/cell-address.ts`：parseAddress/parseRange。

## 已实现

1. 共享范围解析接受小写、合法绝对引用、首尾和端点空白、倒序矩形；保留 Excel 行列边界及原有选区授权。离散读取规范化到实际存储地址。只读分页使用同一规范化，规范化后的重复地址仍拒绝。
2. 省略 sheetId 优先使用冻结选区的 sheetName，无选区时沿用首表；显式未知工作表拒绝。工作表身份仍是本地表名，尚未实现源端稳定 sheet ID 与所有 activeSheet 上下文字段。
3. set_cell/set_formula/clear_cell 规范化地址后，前置条件和同批中间状态使用同一实际地址；不能用 `$a$1` 别名把实际非空格误判为空白。
4. find_cells 对候选 Toolkit 与只读 Agent 都暴露 regex。通过 Node 原生 RegExp 保留大小写不敏感和 JS 命名组等语义，不用 Python 正则冒充源语义。Node 同时执行源端字面量小写匹配、布尔值 1/0、值与公式分别匹配、空值排除，以及全部源端现代错误类型；errors_only 按源端忽略 query/regex。
5. 结果上限整数 <=0 使用默认50，超过200收敛至200。额外匹配确实存在才标 truncated。正则无效、运行超时、运行时不可用返回明确失败，不伪造无匹配。Node 用 JSON stdin，无 shell；仅传授权冻结值/公式，5秒进程超时会结束子进程。

## 验证证据

六个测试文件共98项通过（23.82s）：test_workbook_search.py、test_workbook_tool_contracts.py、test_native_workbook_read_ai.py、test_workbook_ai_tools.py、test_workbook_ai_preconditions.py、test_workbook_ai_tool_boundaries.py。
包含源码参数差异的先红后绿、实际 Agno 工具 schema/regex调用及回执、授权范围/读取覆盖、真实 XLSX 引擎读取和预览、JavaScript命名组、现代错误、上限和实际病态正则超时。ScriptedModel 不算真实 provider 验收。
目标 Ruff 与 git diff --check 通过。未改前端，不声明浏览器验收或四格式全部完成。
环境最初没有 workbook node_modules/tsx/dist，真实引擎用例因此失败；按 lockfile npm ci 后重建 bundle，再通过上面的测试，没有为环境缺失放松产品校验。

## 剩余范围

- XLSX select_range/create_document、完整源指南与 DSL、稳定表身份、activeSheet 输出和源端完整回执格式仍需后续批次。
- trace_precedents/trace_dependents 的直接地址参数仍保留严格格式，未把共享范围解析的改善误记为这两个入口完成。
- 当前搜索针对冻结内存模型；源端 lazy/indexing/incompleteSheets 机制未实现。整数 schema 外的 JS Number 强制转换不对齐；查询空白仍使用 Python strip，特殊 Unicode 空白与源 trim 的差异仍开放。
- Word、PPTX、PDF 工具清单保持开放；未把通用提案工具计作全部源写工具完成。

## 独立复核

独立 reviewer 未发现 Critical/Important 问题。记录一个 Minor：sort_range/merge_cells 虽经过新的范围验证，仍将小写范围原文交给严格大写的实际引擎，预览会明确失败，不会产生虚假成功；完整结构 DSL 参数对齐留给后续批次。镜像会复制新增 .mjs 且已有 Node 运行时。

同步远端 `bf555ffe`（保留源工具迷你图新增适配）后，六组原有受影响测试加 test_workbook_ai_charts.py 共147项通过（33.33s）。该复跑针对共享工具/图表源码变化；未执行重复完整项目测试。Node语法、目标Ruff、diff空白检查通过。唯一警告来自既有第三方 visions 的 imghdr 弃用，不影响本批断言。
