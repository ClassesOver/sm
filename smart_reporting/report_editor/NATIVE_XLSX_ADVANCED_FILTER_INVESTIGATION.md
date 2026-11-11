# XLSX 高级筛选：固定源语义与最小复用调查

日期：2026-11-11。固定源 `/home/junge/pros/genoffice-source-full`，只读核对 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只读源码并新增本文，没有改生产代码、测试或构建，没有执行筛选运行探针、实际 ZIP 保存或浏览器验收。以下“现有能力”是源码证据，不能记作高级筛选功能交付。

## 结论

固定源 Ribbon 名为“高级筛选”的功能，实际是 **已有自动筛选范围内，单列、最多两个自定义条件，以 AND/OR 连接**。它不是 Excel 的完整 Advanced Filter：没有条件单元格区域、多行条件矩阵、复制到其它位置或唯一记录开关。数据保持原位，通过原生筛选模型控制可见性；不复制、删除、排序或去重数据。

本地已具备普通筛选 UI、Univer 筛选插件、customFilters 投影、声明式 `applySheetFilter` 协议、OOXML 条件及隐藏行回写。主要差距是受控对话框与确认执行入口。无需新建筛选算法、服务器 op 或 OOXML writer。源和本地表格筛选路由存在差异，首版必须按本地既有边界处理，不能从源支持情况外推。

## 固定源：入口到回调的真实行为

下列路径相对于固定源根目录。

| 层次 | 文件 / 符号 | 行为 |
| --- | --- | --- |
| Ribbon | `apps/sheets/src/renderer/ExcelShell.tsx`，`filter-advanced` | 点击进入 command；提示文字是“对某列套用自定义筛选条件”。 |
| 调度 | `ribbon-actions.ts` `case 'filter-advanced'` | 有 filter 时直接打开；无 filter 时先异步执行 `sheet.command.smart-toggle-filter`，再打开。创建范围委托官方 smart-selection，不由 dialog 接收范围字符串。 |
| 打开 | `data-tools-actions.ts` `openAdvancedFilterDialog` | 重新取当前活动表与 `getFilter()`；没有 filter 则反馈不打开。字段来自该 filter 的首行。 |
| 字段 | `univer-sync.ts` `advancedFilterColumnOptions` | `colId` 为范围首列起的零基偏移；空表头退回列字母；仅显示范围前 **26** 列。不是从当前选择独立推导数据源。 |
| 对话框 | `AdvancedFilterDialog.tsx` | 一列、第一条件必填、第二条件可空、AND 默认选中。六运算符：equal/notEqual/greaterThan/greaterThanOrEqual/lessThan/lessThanOrEqual。条件值保持字符串，不 trim；第一值严格 `=== ''` 才拒绝，第二值 `=== ''` 则省略。 |
| 确认 | `data-tools-actions.ts` `handleApplyAdvancedFilter` | **确认时再次读取实时活动表/filter**，将 `filter.startColumn + colId` 转列名后交 `applyFilterCriteria`。错误返回字符串，成功返回 null 关闭。源未冻结原 workbook/sheet core、范围或 generation。 |
| 写入 | `univer-sync.ts` `applyFilterCriteria` | 同 AI `set_filter_criteria` 落地路径。验证绝对列位于 filter 范围后，调用 `filter.setColumnFilterCriteria(absoluteColumn, {colId,customFilters})`。只替换该列，保留其它列条件；跨列组合交原生自动筛选模型。 |

`buildCustomFilters` 的兼容细节不可省略：只有两个条件且 AND=true 才写 `and: BooleanNumber.TRUE`；单条件忽略连接符；equal **省略 operator**。源注释说明 Univer 显式 equal 会走数值比较，缺省才符合文本相等路径。OOXML writer 同样将显式/缺省 equal 都写为无 operator 的 `<customFilter val="…"/>`。不能只测试数字相等后认定文本路径正确。

语义范围明确如下：

- 条件内 AND/OR 只连接同一列的两个条件；UI 没有跨列 OR 表达式、任意数量条件或条件区域引用。已有其它列筛选继续参与原生组合。
- 首行作为筛选表头，不当作数据条件行。`colId` 是协议相对列号；Univer 查询和命令使用绝对列坐标，两者不可混用，尤其 C5 等偏移范围。
- 值列表不是“唯一记录”。共享 `applyFilterCriteria` 还接受 `{values:string[]}` 或 null 清除列条件，但本对话框只提交 customs；它不实现去重。
- 通配符、大小写、数值文本/日期/公式结果/空白的具体匹配由 pinned Univer 的比较函数决定。读取 `@univerjs/sheets-filter` 0.25.1 可见双条件 AND/OR 和数值转换分支；本轮未运行这些向量，不额外宣称与 Excel 全语义一致。
- 取消/遮罩关闭本身不写条件；但源无 filter 时，**打开动作已先创建 filter**，因此此路径取消不是工作簿零变化，且创建和设条件可能分成两条历史。这是应明确处理的迁移行为，而非隐藏为“取消无写入”。

## 固定源的持久化路径

1. `App.tsx` 捕获 `FILTER_MUTATIONS`，调用 `recordFilterChange`；`edit-journal.ts` 的 `filterDirty: Set<sheetId>` 标记需要收集。不是把整行数据复制进 cell journal。
2. `save-actions.ts` 调用 `collectFilterStates(runtime,state)`。它收集完整范围、所有列的 values/blank/customs、`getFilteredOutRows()`，以及当前与来源范围并集 `visibilityRange`。删除 filter 时也声明来源范围重新显示。
3. 保存请求携带 `filterStates`，进入 `packages/xlsx-gateway/src/gateway/xlsx-gateway.ts` 的 `applyRoutedFilterState`。普通范围写 worksheet `<autoFilter>`；范围落在一张 Excel Table 内则写 `xl/tables/table*.xml` 的 `<autoFilter>`，worksheet 只写行可见性；跨表格边界拒绝。
4. `xlsx-filter.ts` 序列化 `<filterColumn colId="…"><customFilters and="1"><customFilter …/></customFilters></filterColumn>`；行状态在 visibilityRange 内按声明隐藏/取消隐藏，标题行不作为数据隐藏。`and=false` 省略属性，equal 省略 operator。
5. 这是一条真实 ZIP 编辑实现路径，不是会话内临时谓词。但本轮只追源码，**未实际调用固定源保存或独立回读文件**，也未验证保存后的 Excel 显示状态。

## 本地可以复用的现成实现

以下路径相对于 `smart_reporting/report_editor/frontend/`，引擎相对于仓库根目录。

| 模块 | 已有能力 / 限制 |
| --- | --- |
| `src/workbook-ribbon.ts` | 已有“高级筛选”条目 `filter-advanced`，目前无 command 且 disabled reason 为“尚无高级筛选条件对话框与文件回写”。“文件回写缺失”这一原因过宽，已有通用 customs 写回能力；完成入口后再按事实更新。 |
| `src/workbook-main.ts` | 已装 `UniverSheetsFilterPreset`；filter-toggle/clear/reapply 走官方命令。before guard 对只读/保存/关闭、源 readOnlyReason、dateGroups 等拒绝；`currentOperations()` 已追加 `workbookFilterOperations`。新入口应复用这些边界。 |
| `src/workbook-filters.ts` | `withWorkbookFilters` 导入 `SHEET_FILTER_PLUGIN`，把协议相对 colId 转为原生绝对列；`criteriaOf`/`workbookFilterOperations` 转回相对列并支持 customs 1–2 条。按完整实时筛选差分保存，不需第二份高级筛选 journal。 |
| 同模块可见性 | 将原生 `getFilteredOutRows()` 与 snapshot rowData 手动隐藏并集，声明 `hiddenRows`。来源/实时状态相同则无新 op。日期分组或无法承载的源条件不投影，防静默丢失。 |
| `smart_reporting/reporting/workbook_engine/bridge/operations.ts` | `applySheetFilter` 已在协议内；schema 接受六种运算符、1–2 条 customs、and 布尔、范围、hiddenRows/visibilityRange。不是增加一个 advancedFilter op。 |
| `…/packages/xlsx-engine/src/filters.ts` | `applySheetFilter` 写 worksheet `<autoFilter>` 和 row visibility，校验范围/相对列/重复列/条件与预算；equal XML 兼容已实现。已有 table-overlap 检查会拒绝 sheet filter 写到 Table 上，不能直接套用源 gateway 的 table 路由承诺。 |
| `src/workbook-filters.test.ts` | 已有 customs 差分、隐藏行与手动隐藏、移除恢复、dateGroups 边界、openpyxl 可见性回读测试；它们不是新 dialog 的端到端证明。 |
| 草稿 / 服务器保存 | 当前主链从 `currentOperations()` 取得同一个声明式 op，沿现有 NativeDraft / 保存修订协议。应复用原请求幂等与下载新修订路径；不附加自建缓存或对同一次操作重复 staged+live 差分。 |

建议提交形状示意（现有协议，非新增协议）：

```ts
{
  kind: 'applySheetFilter', sheetName: 'Data',
  filter: {
    range: { startRow: 4, endRow: 9, startColumn: 2, endColumn: 4 },
    columns: [{ colId: 1, customs: { and: true,
      filters: [{ operator: 'greaterThanOrEqual', val: '10' },
                { operator: 'lessThan', val: '30' }] } }]
  },
  hiddenRows: [5, 8]
}
```

此例 protocol colId=1 指 D 列，原生命令参数 col 应为 3；hiddenRows 为绝对零基。真实 columns 必须来自全部实时列条件，不能只把当前列作为全表覆盖快照。引擎只持久化声明，不代替 Univer 重算符合条件的行，不能省略行可见性验收。

## 原子执行、撤销与草稿要求

pinned `SetSheetsFilterCriteriaCommand`（`@univerjs/sheets-filter` 0.25.1）读取旧列条件构造 undo mutation，执行 `sheet.mutation.set-filter-criteria`，成功后 push 官方 UndoRedo item，再发 dirty mutation。已有 filter 上的单次条件替换通常就是一条原生历史；无需照搬 subtotal 多步事务。

仍必须处理下列边界：

- 不通过 facade 的链式返回值判成功；使用 `ICommandService.syncExecuteCommand` 检查 false/throw。源确认路径未检查底层 false，有“被 guard 拒绝仍返回成功”的风险，不能照抄。
- 如果没有 filter，建议最小首版仅提示先开启筛选，以保持打开/取消零写入。若要求完全复刻源的一键创建，应在确认时将 create-range + set-criteria 合为一件事务，并在首 mutation 前完成预检；不要在打开 dialog 时偷偷创建。此选择需产品明确，不把两种行为混写。
- 目标捕获用 workbook/sheet **core identity**、filter range、完整列条件/可见性版本和选区/会话 generation。确认时拒绝切表、同 ID 重建、范围改动、条件变动等 stale；源的实时重新取表缺陷不迁移。
- 失败发生在原生 mutation 后、history push 前或 push 后时，都应恢复原列条件、筛选缓存/可见性、dirty 状态与本 unit 历史。Undo/Redo 也要同步保存差分，不留下失败候选草稿。
- 如确需临时收集 history，应沿已验证 subtotal 的固定版本适配经验，**只收集目标 unit**，其它文档编辑 unit 历史透传官方服务；保持 mutation 参数对象 identity，避免 WeakSet ownership 拒绝。不要为单命令操作无端复制整个复杂事务实现。
- 受保护/只读/不可写源条件与 table 边界在提交前拒绝；本地 protection guard 是否覆盖新命令应专项确认，不能仅凭普通 filter guard 推断。修改失败属于本次编辑失败，不触碰报告 PDF/Word 非阻断签发规则。

## 最小迁移范围

1. 新增轻量 `workbook-advanced-filter-dialog.ts`：单列、六运算符、1–2 值、AND/OR；明确这是自定义列筛选。Cancel/Escape/backdrop 不写入；中文提示第一值必填。保留源 equal 缺省转换，不自行重写比较算法。
2. 新增小型 runtime helper：捕获已有 filter 的稳定目标和范围，提供字段（是否保留源前26列限制须明确），校验 colId/运算符/长度/条件数，提交一条官方 set-filter-criteria 并检查结果。目标不存在或改变时错误留在 dialog。
3. main 只接入口、readOnly/protection/preflight、反馈与 dispose；ribbon 给已有条目绑定 command，完成后移除失真的 disabled reason。
4. 保存复用 `workbookFilterOperations` → `applySheetFilter`，首版不改 OOXML writer/bridge。Table 内过滤若本地没有既有可复用路由，明确拒绝并解释，另开 table filter 专项，不将 source route 整包搬入本任务。
5. 不附带条件区域、复制结果、唯一记录、跨列 OR、更多条件、颜色/图标/Top10/dynamic/dateGroups UI，也不新增 AI 接口。它们不是这条源功能已有范围。

## 最小验收向量

| 向量 | 必须观察的结果 |
| --- | --- |
| AND / OR | 数值区间 `>=10 AND <30`、`<10 OR >30`，一条条件时连接符无影响；真实原生隐藏行和下载文件一致。 |
| 文本相等 | equal 省略 operator；文本、数值文本、布尔/空值、公式结果及通配符分别观察，不把未验证行为写成承诺。notEqual 文本单独覆盖。 |
| 非原点 | filter 从 C5 开始，选 D 列；协议 colId=1、原生 col=3，前后列条件不串位；多列已有条件保留。 |
| 范围 | 首行不隐藏、尾行不越界、范围外不动、手动隐藏保留；移除/清除后可见性正确。 |
| 取消 / stale | Cancel/Escape/backdrop 零 mutation/历史/草稿；切表/同ID重建/filter改范围/条件变化拒绝。无 filter 路径按最终选择明确验收。 |
| 输入拒绝 | 空第一值、非法列/运算符、3条件、过长值、源readOnlyReason/dateGroups、保护/只读、Table重叠，首 mutation 前拒绝。 |
| 原子故障 | 命令 false/throw、mutation已执行后监听器throw、history push前后故障；条件/缓存/可见性/草稿/旧undo+redo全部恢复，foreign docs-unit历史不吞。 |
| Undo / Redo | 一次撤销恢复原列条件与全部可见性，一次重做完整复现；保存差分也随之恢复。 |
| 真实持久化 | 下载实际XLSX，ZIP CRC+lxml+openpyxl独立核对 autoFilter ref、colId/customFilters/and/operator/转义、row.hidden、数据不变；同时验证普通范围与Table拒绝边界。 |
| 草稿 / 新修订 | 生成草稿、离开重开、相同请求重试、一次保存新修订后明确重开；不重复应用 op、不重新提交已完成checkpoint。 |

本轮没有执行上述新向量。实施时仅运行相关 dialog/runtime/filter/保存专项与唯一产品构建，不重复全量测试；验收不能只凭 XML 条件存在或 manifest/hash 通过。
