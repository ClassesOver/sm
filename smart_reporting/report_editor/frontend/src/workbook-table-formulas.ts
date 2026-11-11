import { ICommandService, IUniverInstanceService, UniverInstanceType, type Workbook } from '@univerjs/core'
import { ErrorType, ErrorValueObject, IFormulaCurrentConfigService, ReferenceNodeFactory, SetSuperTableMutation, splitTableStructuredRef } from '@univerjs/engine-formula'
import { TableManager } from '@univerjs/sheets-table'

// 固定源dataRange：表模型保留完整范围，结构化公式的数据区域排除汇总行。
// 官方TableController不了解来源totals元数据，统一规范其加载/更名/范围变更注册。
export function installTableFormulaReferences(runtime: any) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService)
  const tables = injector.get(TableManager), instances = injector.get(IUniverInstanceService)
  const config = injector.get(IFormulaCurrentConfigService), factory = injector.get(ReferenceNodeFactory)
  const originalCreate = factory.checkAndCreateNodeType
  // Univer 0.25.1 的表引用对象固定假定首行为表头，registry也没有header/totals字段。
  // 仅适配来源/新建表的官方节点：复用其列名与分段解析，不改公式、表范围或持久化语义。
  const createNode = function (this: ReferenceNodeFactory, ...args: Parameters<typeof originalCreate>) {
    const node = originalCreate.apply(this, args)
    const reference = (node as any)?._tableReferenceObject
    if (!reference) return node
    const { tableName, columnStruct } = splitTableStructuredRef(node!.getToken())
    const table = tables.getTableList(config.getExecuteUnitId()).find((item: any) => item.name === tableName)
    if (!table?.meta || !Object.hasOwn(table.meta, 'nativeTotalsRowCount')) return node
    const { type } = reference._parseStructuredRef(columnStruct, reference._tableData.titleMap)
    const header = table.showHeader ? 1 : 0, totals = table.meta.nativeTotalsRowCount
    const area = table.range
    if (type === '#Headers' && !header || type === '#Totals' && !totals) {
      node!.execute = () => node!.setValue(ErrorValueObject.create(ErrorType.REF))
      return node
    }
    const first = type === '#Headers' || type === '#All' ? area.startRow
      : type === '#Totals' ? area.endRow : area.startRow + header
    const last = type === '#Headers' || type === '#This Row' ? first
      : type === '#All' || type === '#Totals' ? area.endRow : area.endRow - totals
    // #This Row 的 getRangeData 仍由官方按运行时 currentRow 动态覆盖；这里只补无上下文默认行。
    reference.setRangeData({ ...reference.getRangeData(), startRow: first, endRow: last })
    return node
  }
  factory.checkAndCreateNodeType = createNode
  const before = commands.beforeCommandExecuted((command: any) => {
    if (command.id !== SetSuperTableMutation.id) return
    const params = command.params
    const table = tables.getTableList(params.unitId).find((table: any) => table.name.toLowerCase() === params.tableName.toLowerCase())
    if (!table?.meta || !Object.hasOwn(table.meta, 'nativeTotalsRowCount') || !params.reference) return
    params.reference = { ...params.reference, range: { ...table.range, endRow: table.range.endRow - table.meta.nativeTotalsRowCount } }
  })
  const loaded = tables.tableInitStatus$.subscribe((ready: boolean) => {
    if (!ready) return
    for (const workbook of instances.getAllUnitsForType(UniverInstanceType.UNIVER_SHEET) as Workbook[]) {
      const unitId = workbook.getUnitId()
      for (const table of tables.getTableList(unitId)) {
        if (!table.meta || !Object.hasOwn(table.meta, 'nativeTotalsRowCount')) continue
        commands.syncExecuteCommand(SetSuperTableMutation.id, { unitId, tableName: table.name,
          reference: { range: table.range, sheetId: table.subUnitId,
            titleMap: new Map(table.columns.map((column: any, index: number) => [column.displayName, index])) } })
      }
    }
  })
  return { dispose() { before.dispose(); loaded.unsubscribe(); if (factory.checkAndCreateNodeType === createNode) factory.checkAndCreateNodeType = originalCreate } }
}
