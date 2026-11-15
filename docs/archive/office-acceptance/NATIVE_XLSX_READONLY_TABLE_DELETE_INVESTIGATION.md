# XLSX 未投影／只读表格的来源名称与整页删除调查

2026-11-10。本轮只读调查生产和测试，仅新增本文；不改生产、不新增测试、不提交推送、不运行完整套件。共享脏树原样保留。下述修复是实施方案，尚未实现或进行浏览器验收。

## 结论

当前缺口成立：表格列、范围、样式等完整投影失败，会让 `readSheetTables` 返回 `tables: []` 和 `tablesReadOnlyReason`；前端 `assertTableSheetRemoval` 立即拒绝整页删除，即使表格所属关系、根名称均可核对、存续内容也没有依赖。文件侧已有独立于完整表格投影的删除保护，能允许无依赖删除并拒绝真实结构化引用。

最小完整修复应为表格增加独立、完整、可信的来源身份快照，把“不能编辑表格”与“不能核对删除身份”分开；前端依身份快照及 live 状态检查，文件侧复用同一名称提取规则。不能简单删掉前端 `readOnlyReason` 判断，不能把空投影当成没有表格，也不能只在保存后拒绝来代替 UI 删除前的原子预检。

## 固定上游证据

只读核对 `/home/junge/pros/genoffice-source-full` HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，该仓库 `git status --short` 无输出。

| 源文件 | 关键位置及行为 |
| --- | --- |
| `packages/xlsx-gateway/src/gateway/xlsx-sheets.ts` | 539–546 `tableDisplayName` 只从根 `<table>` 取 `displayName`，缺失才回退 `name`，XML 属性解码；不要求列、范围或样式可投影。549 起 `definedNamesUseToken` 忽略随删除页消失的 local 名称。 |
| `packages/xlsx-gateway/src/gateway/xlsx-gateway.ts` | 1962 起计算 owned 闭包，1992 起由存续 incoming 保留共享 part；2069–2091 只检查最终将删除的 `xl/tables/*.xml`，对存续 worksheet 和名称查大小写不敏感 `TableName[`。全部检查在 mutation 前完成。 |
| `packages/xlsx-gateway/src/gateway/xlsx-table-edit.ts` | 86 起 `tableNames` 可提取 `displayName` 和 `name` 两个别名；`sheetTableParts` 沿真实关系定位 part；104 起 `removeTable` 是“转换为范围”的单表删除链，不能直接用于整页删除。 |
| `apps/sheets/native/xlsx-engine/src/table_styles.rs` | 690 起 `read_sheet_tables` 的可视投影独立读取，736 注释说明结构化引用使用 `displayName`，`name` 为回退；不应以 native 视觉投影等同于完整删除身份。 |

前三文件 SHA256 依次为 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`、`748591515b74f2f5e8b25c40283b90b567640706eb97d2be015954717b390f6a`、`3d537c8661ae28fc6e9fea2a131fac1ec4907dfe727e442b261603a9a4aa43ea`。

上游正则属性/标签解析、缺失名称跳过、常规路径限定是来源事实，不代表已具备 namespace 与来源完整性校验。下面建议在本地保留现有安全边界，属于适配加强。上游 token 扫描仍可能命中字面量，不是语义公式解析器；本轮不承诺解决这类既有保守匹配。

## 当前本地链路与丢失点

所有下列路径相对 `smart_reporting/`：

1. `reporting/workbook_engine/packages/xlsx-engine/src/table-read.ts`：`readSheetTables` 120 起先用 `tableParts`、relationship Id/Type/TargetMode、路径解析确定 owner；但同一 try 内立刻 `parseTable`。列数量、列名重复、范围、行数、样式 namespace/flag 等任意异常，最终 catch 丢弃全部表格，包括此前已成功读取的表格。根名称不能单独保留下来。
2. `src/workbook-read.ts` 123–125 的 `SheetModel` 只有 `tables`、`tablesReadOnlyReason`；440 起传播该结果。`SheetTableModel` 同时含 name/displayName/path 和可编辑范围、列、样式，无法表示“身份完整、编辑投影失败”。
3. `report_editor/frontend/src/workbook-tables.ts` 18、73 起在只读时跳过表格编辑操作和 Univer 资源灌入。因此 `workbook.getTableList()` 没有这类表格是预期行为，不能据此授权删除。
4. `frontend/src/workbook-main.ts` 1849–1856 从当前结构来源模型取目标 `tables`、`tablesReadOnlyReason`；存续 `retainedTablePaths` 同样只用 `sheet.tables`。只读存续页的共享表格身份也会丢失，不能仅修目标页。
5. `frontend/src/workbook-table-sheet-removal.ts` 18 的 `source.readOnlyReason` 无条件 throw。之后已有 live 普通/共享公式、CF、DV、未投影原文、live 名称和部分未投影名称的检查；这些不应被新方案替换成旧 XML 全文扫描，否则用户清除 live 依赖后仍可能被旧普通公式误拒。
6. `reporting/workbook_engine/packages/xlsx-engine/src/sheet-ops.ts` 135–147 先得到最终 `removedParts`，再调用 `sheet-removal-parts.ts::assertRemovedTableDependencies`；该函数 127–133 从最终删除的 `xl/tables/*.xml` 根名称直接检查，完全不依赖 `readSheetTables` 的编辑投影。

文件侧后者当前只优先检查一个 `displayName`，没有名称则静默跳过，且限定常规路径。前端已有同时检查 name/displayName 的更保守语义。若新增独立身份快照，两个入口应统一提取、完整性失败及别名规则，不能新 UI 放行后留下保存侧另一个身份盲区。

## 本轮实际最小探针

未写入仓库 fixture 或测试。用项目 `.venv/bin/python` 的 openpyxl 创建真实 ZIP：`Source` 有 A1:A3 表格 `SalesData`，`Other!A1=42`。只在 ZIP 的 `xl/tables/table1.xml` 将 `tableColumns count="1"` 改成 `count="9"`，不改根名称、owner、关系或路径；另一个变体把 Other 单元格改成 `<f>SUM(SalesData[Amount])</f>`。这是故障注入的真实 XLSX 包，不宣称计数损坏后的表格符合 OOXML。

临时产物：

- `/tmp/readonly-table-identity-independent.xlsx`
- `/tmp/readonly-table-identity-dependent.xlsx`

在 `reporting/workbook_engine` 以现有 `node --import tsx --input-type=module` 直接调用 `readWorkbook` 和 `applySheetEdits`，计划为 `{renames:[],additions:[],removals:['Source'],order:['Other']}`。两条命令均 exit 0，输出为：

```text
independent {"tables":[],"reason":"表格容器数量或内容不一致"}
save allowed [ 'Other' ]
dependent {"tables":[],"reason":"表格容器数量或内容不一致"}
save rejected 存续工作表仍引用表格 "SalesData"，已拒绝删除。
```

前端在进入这些依赖检查前会按同一个 reason 拒绝，两变体都不能 UI 删除。这一前端结论来自直接代码路径，不冒充本轮浏览器运行结果。没有启动服务或后台进程，没有 provider 请求或 403。

后续最小可持久 fixture 可沿用上述 openpyxl + ZIP patch，而非 mock 表格对象。再增加同一页第二个表格，让第二个列计数失败，证明第一个有效表格也不能因 all-or-nothing 投影丢失删除身份。

## 可行的最小完整修复

### 1. 在源模型保留单独身份

在 `table-read.ts` 引入小型 `SheetTableSource`，仅保存 `{path, name, displayName}`，以及完整性状态，例如 `tableSources?: readonly SheetTableSource[]`、`tableSourcesReadOnlyReason?: string`。字段名可调整，但“未读取／完整空列表／完整非空列表／来源不完整”必须可区分；缺字段不能回退授权。`name` 可按现有规则回退 displayName；根 displayName 缺失时是否兼容 name-only 应明确统一，不能两端默默不同。

顺序必须是：完整发现并验证 owner → 完整验证所有 table part 的根身份 → 发布完整身份列表 → 尝试原有可编辑投影。完整投影失败仍保留 `tables: []`、`tablesReadOnlyReason`，同时保留可信 `tableSources`。不要让第一个 `parseTable` 失败提前中断后续身份收集。不要把部分身份列表标为完整。

身份验证只放宽列/范围/样式的可编辑要求；仍要求 XML 完整、单一正确 namespace 的根 table、可用且非空根名称、无重复身份歧义，以及完整可信 owner。可以复用既有 `saxes` 验证 XML/root/属性，避免以宽松正则在注释、外来 namespace 或嵌套扩展 table 中猜名称。`createBufferEntrySource` 已负责包读取限制、DOCTYPE/ENTITY 拒绝和前缀正规化，无需另造 ZIP 或 XML 基建。

继续复用 `tableRelationshipId`、`resolveTablePartPath` 的安全意图及 `tableParts` 完整性检查。若复用 `sheet-removal-parts.ts` 的 namespace-aware relationship/Target helper，按需小幅导出或提取，不能仅凭 regex 中 Type 字符串信任一个外来 relationship。明确拒绝重复 relationship Id、错误 Type/TargetMode、外部 target、越界、缺 part、重复 owner 引用。不能扫描 ZIP 猜 orphan table 属于目标页。

### 2. 前端删除使用来源身份，编辑仍使用原投影

`workbook-read.ts::SheetModel` 传播新字段；bridge 的现有模型 JSON 输出可自然携带，Python 是否有字段白名单需实施时窄查，不预先新增协议层。

`workbook-main.ts` 1849 起把目标和所有存续页的身份快照传给删除 helper；retained 必须以可信 part 路径计算，不能只用名称、更不能只用可编辑 `tables`。存续页身份不完整时不能把其空列表当作“该 part 不共享”；可保守拒绝或使用同一最终删除 planner 的结果，不能猜测。

`workbook-table-sheet-removal.ts` 将阻断条件从编辑投影 reason 改成来源身份完整性失败；来源完整时使用全部目标 name/displayName，排除由实际存续 incoming 保留的 part，再合并目标 live 表格名称。保留现有各依赖面和 live 清除语义。来源过期时沿用 `cfBaseline`/结构 signature 的同步保护，不拿初始文件覆盖改名、移位后的来源。

`workbook-tables.ts` 的只读编辑与资源跳过规则保持；新身份快照不能进入可编辑 Table Design 或公式解析资源，也不能触发“没有 live table，所以删除只读原表”的差分操作。

### 3. 文件侧复用身份规则，保持真实删除原子性

`sheet-removal-parts.ts::assertRemovedTableDependencies` 复用同一安全根身份读取，至少统一 name/displayName 的解码和歧义规则；名称不可核对时明确拒绝结构删除，不能 `continue` 当没有依赖。继续只检查最终 removed part，保留 local scope 跳过、大小写不敏感 token 和 mutation 前校验。

若支持非标准 table part 路径，候选身份必须来自已验证 table relationship 类型，不能把 `xl/tables/*.xml` 文件名当作所有权。最小实施可先保持现有常规路径支持并对超出范围明确拒绝，不得静默漏查；不能声称该限制是完整 OPC 支持。共享归属仍以 `planSheetRemovalParts` 的全部存续 incoming/保留子树为最终事实，单纯“其他页的 tableSources 中没出现”不足以替代它。

最低生产修改点为 `table-read.ts`、`workbook-read.ts`、`sheet-removal-parts.ts`、前端 `workbook-main.ts` 和 `workbook-table-sheet-removal.ts`；只在 namespace/path 复用需要时调整现有 helper。按仓库约定同步 SOURCE/指纹与实际 bundle 应在后续实施阶段完成，本轮未执行。

## 边界与验收门槛

| 情形 | 应有行为 |
| --- | --- |
| 列数量/样式投影失败，所有身份完整，无存续依赖 | 允许整页删除；编辑该表格仍只读。 |
| 同上，但 live 普通/共享公式、CF、DV、存续 global/local 名称或未投影内容引用目标表 | 删除前原子拒绝，给具体位置及表名，history/draft 不变化。 |
| 引用仅在被删页或其 local 名称内 | 不阻止整页删除。 |
| 两张表，任一投影失败 | 两张来源身份都保留，不能只保护成功投影那张。 |
| 存续页也只读但共享同一 table part | 按实际 incoming 保留 part 和依赖；不能误删共享表或只靠同名猜共享。 |
| 根缺失/外来 namespace/畸形 XML/名称缺失歧义、owner 缺失或不可信 | 明确报告身份无法核对并拒绝该结构修改，不凭局部名称放行。 |
| orphan table XML | 不凭 ZIP 扫描归属；保持现有原包保留策略。 |
| 用户先清除或改写已投影依赖，再删除 | 按 live 判断；不可用旧普通公式全文强行拒绝。未投影来源仍校验。 |
| 改名、行列移位后删除、undo/redo、草稿重载、修订重开 | 当前结构来源和身份一致，未投影表不被意外转换或丢弃。 |

实施后先运行新增窄 engine 测试：真实 XLSX 的独立/依赖双控制、两表 all-or-nothing、根身份失败、共享只读 part、大小写与别名；再运行对应 frontend helper 测试，并用一个真实 UI fixture 验证删除→undo/redo→草稿重载→Python 保存→修订重开及存续 ZIP 字节保真。只跑受影响测试，不重复完整测试。现有 `table-read.test.ts`、`owned-table-delete-dependencies.test.ts` 和 `workbook-table-sheet-removal.test.ts` 可作测试位置，本文未修改或运行这些文件。

本轮不涉及报告验收、发布门禁或下载签发；表格结构删除的依赖拒绝不得扩散成阻断现有报告产物下载的规则。


## 后续实施状态（2026-11-10）

上述方案已实施：engine独立身份与前端实际planner缓存完成；新增engine61项、前端6项定向通过，统一build/budget/contract通过。真实浏览器只读有引用拒绝、清引用后删除/undo/redo/draft/Python/revision2两模式通过，日志 /tmp/readonly-table-browser-{refusal,clear}.log。保存仅改目标表和所属sheet，Other数据与styles保持。具体闭环及边界见 NATIVE_WORD_XLSX_PARITY_AUDIT.md 本轮追加条目；本文早期“尚未实现”描述保留为调查历史。
