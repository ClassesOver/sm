import { CommandType, ICommandService, IUndoRedoService } from '@univerjs/core'
import { RangeThemeStyle, SheetRangeThemeModel, SetWorksheetRangeThemeStyleMutation } from '@univerjs/sheets'
import { TableManager } from '@univerjs/sheets-table'
import { nativeTableTheme } from './workbook-table-styles'

export type TableStyleOption = 'showFirstColumn' | 'showLastColumn' | 'showRowStripes' | 'showColumnStripes'
const STYLE_OPTIONS: readonly TableStyleOption[] = ['showFirstColumn', 'showLastColumn', 'showRowStripes', 'showColumnStripes']

const STYLE_MUTATION = 'sheet.mutation.native-table-style'
const COUNTS = { Light: 21, Medium: 28, Dark: 11 }

// 固定源内置图库边界；空字符串是OOXML无样式，不回退为默认Medium。
function validStyle(name: string): boolean {
  const match = /^TableStyle(Light|Medium|Dark)([1-9][0-9]?)$/.exec(name)
  return name === '' || !!match && Number(match[2]) <= COUNTS[match[1] as keyof typeof COUNTS]
}

export function installTableStyleEdit(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector()
  const commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const tables = injector.get(TableManager), themes = injector.get(SheetRangeThemeModel)
  const owned = new WeakSet<object>()
  let disposed = false
  const capture = (unitId: string, table: any) => {
    const themeId = table.getTableStyleId()
    return { themeId, theme: structuredClone(themes.getRangeThemeStyle(unitId, themeId)?.toJson() ?? { name: themeId }),
      meta: structuredClone(table.getTableMeta()) }
  }
  const apply = (unitId: string, table: any, state: ReturnType<typeof capture>) => {
    const rangeInfo = { unitId, subUnitId: table.getSubunitId(), range: { ...table.getRange() } }
    themes.removeRangeThemeRule(table.getTableStyleId(), rangeInfo)
    themes.registerRangeThemeStyle(unitId, new RangeThemeStyle(state.themeId, state.theme))
    table.setTableStyleId(state.themeId)
    table.setTableMeta(structuredClone(state.meta))
    if (!commands.syncExecuteCommand(SetWorksheetRangeThemeStyleMutation.id, { ...rangeInfo, themeName: state.themeId })) throw new Error('表格样式刷新未执行')
  }
  const mutation = commands.registerCommand({ id: STYLE_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = tables.getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      const before = capture(params.unitId, table)
      try { apply(params.unitId, table, params.state) }
      catch (error) { apply(params.unitId, table, before); throw error }
      return true
    },
  })
  const update = (tableId: string, patch: { name?: string } & Partial<Record<TableStyleOption, boolean>>): boolean => {
    if (disposed) throw new Error('表格样式编辑已关闭')
    const workbook = runtime.univerAPI.getActiveWorkbook(), unitId = workbook?.getId()
    const table = unitId && tables.getTable(unitId, tableId)
    if (!table) throw new Error('当前表格不存在，请重新选择')
    if (protectedSheet(table.getSubunitId())) throw new Error('表格所在工作表受保护，请先撤销保护')
    const before = capture(unitId, table)
    const current = { name: '', showFirstColumn: false, showLastColumn: false, showRowStripes: false, showColumnStripes: false,
      ...before.meta.nativeTableStyle }
    if (Object.entries(patch).every(([key, value]) => current[key] === value)) return true
    const style = { ...current, ...patch }, styleName = style.name
    const themeId = `${styleName ? 'native-file-table' : 'native-table-none'}:${JSON.stringify([table.getSubunitId(), tableId])}:edit`
    const theme = nativeTableTheme({ customStyle: before.meta.nativeCustomTableStyle, style, headerRowCount: table.isShowHeader() ? 1 : 0,
      totalsRowCount: before.meta.nativeTotalsRowCount ?? (table.isShowFooter() ? 1 : 0) }, before.meta.nativeThemePalette, themeId) ?? { name: themeId }
    const after = { themeId, theme, meta: { ...before.meta, nativeTableStyle: style,
      nativeTableStyleName: styleName, nativeTableThemeId: themeId } }
    const params = (state: typeof before) => {
      const params = { unitId, subUnitId: table.getSubunitId(), tableId, state }
      owned.add(params)
      return params
    }
    const redo = { id: STYLE_MUTATION, params: params(after) }, undo = { id: STYLE_MUTATION, params: params(before) }
    if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('表格样式未应用')
    history.pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
    return true
  }
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; mutation.dispose() },
    setStyle(tableId: string, styleName: string): boolean {
      if (disposed) throw new Error('表格样式编辑已关闭')
      if (!validStyle(styleName)) throw new Error('表格样式无效，请选择内置浅色、中等、深色样式或无样式')
      return update(tableId, { name: styleName })
    },
    setOption(tableId: string, option: TableStyleOption, enabled: boolean): boolean {
      if (disposed) throw new Error('表格样式编辑已关闭')
      if (!STYLE_OPTIONS.includes(option) || typeof enabled !== 'boolean') throw new Error('表格样式选项无效')
      return update(tableId, { [option]: enabled })
    },
  }
}
