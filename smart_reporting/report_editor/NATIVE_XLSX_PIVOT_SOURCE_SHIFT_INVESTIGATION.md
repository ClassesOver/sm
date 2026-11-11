# XLSX 透视缓存来源行列移位调查与最小保护

固定来源 `/home/junge/pros/genoffice-source-full`，HEAD 已核对为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。调查与窄范围引擎保护于 2026-11-10 完成；未执行完整测试、完整 build 或提交。本页不宣称实现 `worksheetSource.ref` 坐标同步，也不作为前端/浏览器验收记录。

## 结论与真实 ZIP 证据

本地原 `applyRowColumnOps` 会移动工作表数据，却保留缓存旧 `worksheetSource.ref`。固定源**没有实现**透视来源范围同步；它在保存阶段拒绝所有来源页行列移位。本地缺失的是该来源依赖保护，不是遗漏一个已有可迁移的 ref 同步算法。

`/tmp/pivot-source-shift-fixture.py` 用 openpyxl 创建实际 XLSX：Source 页含前置行、表头 Category/Amount、A/10、B/20 及后置行；Pivot 页带实际 TableDefinition/CacheDefinition、关系，缓存来源 `Source!A2:B4`；另有 Unused 页。`/tmp/pivot-source-shift-probe.ts` 同时调用本地 `applyRowColumnOps` 和固定源 `planCellEditsToXlsx`。实际入口已打包到 `/tmp/pivot-source-shift-probe.mjs`，输出 `/tmp/pivot-source-shift-results.jsonl`，各产物 `/tmp/pivot-source-shift-*.xlsx`。

| 操作（零基 index） | 原本地结果 | 固定源结果 |
| --- | --- | --- |
| Source insert-rows 0 / 2 | 数据下移，cache 仍 A2:B4 | 明确拒绝保存 |
| Source remove-rows 0 / 2 | 数据上移/被删，cache 仍 A2:B4 | 明确拒绝保存 |
| Source insert-cols 0 | 数据右移，cache 仍 A2:B4 | 明确拒绝保存 |
| Source remove-cols 0 | 第一列删除，cache 仍 A2:B4 | 明确拒绝保存 |
| Unused insert-rows 0 | 来源与 cache 不变，允许 | 允许 |

对实际 ZIP 再用 openpyxl 回读：前插一行后旧 A2:B4 读成 `[before/unused, Category/Amount, A/10]`；删除前置行后读成 `[A/10, B/20, after/99]`；前插一列后读成 `[空/Category, 空/A, 空/B]`；删来源首列后读成 `[Amount/空, 10/空, 20/空]`。因此“XLSX 可打开、透视缓存尚可显示旧值”不能证明保存正确。缓存刷新也不能修复这个问题：本地 `pivot-refresh.ts:165` 从旧 ref 读取区域，且校验缓存字段数，既不推断几何迁移也不扩展来源范围。

## 链路与源码触点

- 固定源 `packages/xlsx-gateway/src/gateway/xlsx-gateway.ts:1262–1279` 仅在 `isShiftingOp` 时收集缓存定义，逐来源页调用 `pivotCacheReadsFromSheet` 并抛 `StructuralShiftError`。来源页宽高/显隐/outline 等不移位操作允许；本地 `applyRowColumnOps` 的 StructuralOp union 只有四种行列插删，均属移位。固定源 `xlsx-sheets.ts:574` 是工作表名依赖判断，没有 ref shift helper。
- 本地 `reporting/workbook_engine/packages/xlsx-engine/src/sheet-ops.ts:337` 是行列变更文件入口；按 op 顺序应用工作表几何、图表/定义名称/表格/CF 等迁移，原先从未读取来源页之外的 pivotCacheDefinition。`structural.ts:435` 的 `assertShiftable` 只看目标 worksheet marker，无法发现 Pivot 页读取 Source 页。
- `reporting/workbook_engine/bridge/operations.ts:63` 顺序执行 `applyRowColumnOps`，前端预演和保存复用同一引擎入口。不存在由客户端传入可信缓存 XML 的必要，也不需要增加 operation 字段。
- 前端 `workbook-grid-operations.ts:28` 将原生 insert/remove row/col mutations 转成 StructuralOp；`workbook-main.ts` 的 onCommandExecuted 记录结构日志，`currentOperations` 生成 `applyRowColumnOps` 并按当前页名保存。已缓存 `pivotCacheSources` 与 `cfBaseline` 主要用于 sheet removal，原先未用于 row/col 来源检查。
- `workbook-data-validation-structure.ts` 已包装 `SheetInterceptorService.onCommandExecute` 进行原生结构预检；来源保护应在该服务真正执行前拒绝，而不能只取消一个后续 follower 或依靠保存失败撤销。还需覆盖直接调用原始 row/col mutation 的绕过路径。前端实现/浏览器证据由 root 集成任务单独完成。

## 已实施的最小来源对齐保护

`applyRowColumnOps` 在解析目标页之后、读取/迁移目标 XML 之前扫描固定范围 `isPivotCacheDefinitionPath`。对当前 ZIP 的每个缓存调用既有 namespace-aware `pivotCacheReadsFromSheet`，命中时抛 `StructuralShiftError`：`仍有透视表读取工作表 "…" 的来源数据，已拒绝插入/删除行列。` 没有改写来源 ref，也没有扩大到无关单元格、格式或发布验收流程。

既有 helper 接口不变：`isPivotCacheDefinitionPath(path)` 和 `pivotCacheReadsFromSheet(xml, sheetName)`。沿用 transitional/strict、别名前缀、单引号、实体单次解码、大小写忽略及完整 XML 验证；损坏 XML 不应被当作“无依赖”。前端可直接复用同一纯 helper，以可信当前模型的缓存快照验证原生动作。

顺序协议按当前 bytes 重新检查：先改名则后续新名称仍命中；若先通过真实受控操作消除了依赖，后续原页可继续编辑。固定源也是按保存当前读取到的 cache 检查；**不**提供“同一动作先改数据再宣称缓存已消除”的旁路。没有公开新增缓存换绑 API；测试只在可信 ZIP fixture 层构造已改变来源的当前包，验证引擎不会把初始快照旧名称永久冻结。

## 验证与后续范围同步边界

新增窄测试 `packages/xlsx-engine/tests/pivot-source-row-column-guard.test.ts`：6 种来源行列变更、无关页不影响 pivot/cache/source XML、alias/strict/实体来源、先改名再变更、依赖已真实迁出后的原页允许。先 RED 10 失败/2 通过 `/tmp/pivot-source-row-column-red.log`，补保护后 GREEN 12/12 `/tmp/pivot-source-row-column-green.log`；严格引擎类型检查通过 `/tmp/pivot-source-row-column-types.log`。未重复既有已绿完整套件。生产变更仅行列入口保护，未修改已绿的改名 helper 或改名逻辑。

若将来明确要求**支持**来源范围同步，应作为新增能力而非本次来源对齐，先确定以下协议并补真实 Excel 对照：

1. 普通矩形 ref 的前插/内部插入/边界插入、部分/全部删除、header 删除和工作表最大边界语义；只移动端点的公式 helper 不能直接处理所有删除交叠。无法保留合法来源时明确拒绝整次编辑。
2. 行变动与列变动分开设计：仅调整 ref 不足以支持列插删，cacheFields、共享项、pivotFields、row/column/dataFields 与刷新记录身份也可能改变。删除指标列或插入新表头不能简单扩大 ref 然后标记支持。
3. name/table 外部来源、缓存共享多个透视表、外部连接、输出页移动及缓存记录失效策略必须明确；不能把 worksheetSource@name 当作 ref，也不能仅因没有可解析 ref 就放行。现有源保护保守拒绝全部匹配来源页，可保留为未支持分支。
4. 如新增纯 planner，应由引擎从可信 XML 生成 `{changedCacheXML / refusalReason}`，namespace、完整解析、属性跨度及单次解码继续复用；前端原生 mutation前与服务端保存采用同一 planner，坐标逐步推进，禁止客户端自报 XML。无关属性/缓存/透视表 parts 字节保留，拒绝时不发生部分 ZIP 或网格变更。
5. 验证向量包含：前/内/后/边界行列插删、全删/header删、混合多步、重命名组合、同缓存多消费者、不同页同名大小写、alias/strict/实体/单引号/malformed/DTD、旧 name/table 来源、刷新后实际结果；原生 Ribbon/右键/直接 mutation、Undo/Redo、保存重开和实际 ZIP 回读均需覆盖。全程不将文件编辑校验混同报告发布门禁；发布验收告警不得阻断已有真实产物下载。


## 前端原子保护增量（2026-11-10）

`installDataValidationStructure` 增加独立结构预检回调，在命令服务 before listener 和结构拦截器调用原实现前执行；直接 row/col mutation 也检查。拒绝时只清理当前执行栈调用身份，不留下官方 before listener 异常残留；不改快照、历史或草稿。`workbook-main.ts` 从可信当前模型的 pivotCacheSources 读取缓存声明。工作表计划未变时，行列几何不改变来源名称，不要求几何缓存同步；工作表计划变化时仍检查 cfBaseline.source 绑定与完整有序工作表名称身份。没有跳过 Undo/Redo。

原始 RED 为来源插行错误返回 true；保护首轮使无关页 Undo 被几何同步判定拒绝，另新增改名+无关页组合也先复现 RED，再将来源身份检查与行列几何分离。最终 `/tmp/pivot-row-column-main-green.log` 4项通过：原名/改名来源各12命令及底层mutation拒绝时完整getSnapshot、undo/redo栈顶身份、草稿、保存态和save调用保持；无关页普通/改名两组合均插行列、Undo/Redo、草稿与真实ZIP保存通过。`/tmp/pivot-row-column-structure-compat.log` 16项通过；最终 `/tmp/pivot-row-column-frontend-tsc.log` exit0。没有重复完整main套件。

浏览器生产静态资源验收等待root统一构建，不以单测代替。

最终built新增Ribbon失败回归已修复：facade吞原生命令false导致外层误报dirty，四action调用前复用同源guard。最终/tmp/pivot-source-structure-built-smoke-http.log exit0，全部四来源拒绝/无关结构编辑UndoRedo/draft/Python/download/rev2通过，342JS身份匹配，errors=[]；仅sheet3.xml变化，其余ZIP字节保留。最终build/budget/contract同prefix /tmp/office-pivot-source-structure-ribbon-* exit0，详细操作与下载fixture说明见frontend/smoke/workbook-pivot-source-structure-built-smoke.md。
