// 调色规则适配自固定 GenOffice f8c17004 的 renderer/table-styles.ts。
// 使用官方 RangeThemeStyle 叠加显示，不把表格主题烘焙进单元格格式或文件差分。
import type { CustomTablePalette } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/table-style-read'
import { univerBorderStyleId } from './workbook-vendor/core/style-map'
import type { BorderStyleTypes, IStyleData } from '@univerjs/core'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import type { IRangeThemeStyleJSON, IRangeThemeStyleItem } from '@univerjs/sheets'
import type { IUniverSheetsTableConfig } from '@univerjs/sheets-table'
import { TableManager } from '@univerjs/sheets-table'
import { InterceptorEffectEnum, IUniverInstanceService, UniverInstanceType, type Injector, type Workbook } from '@univerjs/core'
import { INTERCEPTOR_POINT, SheetInterceptorService, SheetRangeThemeModel } from '@univerjs/sheets'

type TableStyleFamily = 'Light' | 'Medium' | 'Dark'
const TABLE_STYLE_COUNTS = { Light: 21, Medium: 28, Dark: 11 }
export interface TableStylePalette extends CustomTablePalette {
  headerFill?: string
  headerFontColor?: string
  stripeFill?: string
  secondRowStripeFill?: string
  columnStripeFill?: string
  wholeTableFill?: string
  totalRowFill?: string
  totalRowFontColor?: string
  totalRowBorderColor?: string
  totalRowBorderStyle?: string
  bodyFontColor?: string
  borderColor?: string
  wholeTableBorderColor?: string
  wholeTableBorderStyle?: string
  innerHorizontalBorderColor?: string
  innerHorizontalBorderStyle?: string
  innerVerticalBorderColor?: string
  innerVerticalBorderStyle?: string
}
const DEFAULT_ACCENTS = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
const WHITE = '#FFFFFF'

type Rgb = readonly [number, number, number]

function parseHex(hex: string): Rgb | null {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return null
  const value = Number.parseInt(match[1]!, 16)
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff]
}

function toHex([red, green, blue]: Rgb): string {
  return `#${[red, green, blue].map((part) => part.toString(16).padStart(2, '0').toUpperCase()).join('')}`
}

function rgbToHsl([red, green, blue]: Rgb): [number, number, number] {
  const r = red / 255
  const g = green / 255
  const b = blue / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h: number
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0)
  else if (max === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return [h / 6, s, l]
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  if (s === 0) {
    const gray = Math.round(l * 255)
    return [gray, gray, gray]
  }
  const hue2rgb = (p: number, q: number, t: number): number => {
    let tt = t
    if (tt < 0) tt += 1
    if (tt > 1) tt -= 1
    if (tt < 1 / 6) return p + (q - p) * 6 * tt
    if (tt < 1 / 2) return q
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6
    return p
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  return [
    Math.round(hue2rgb(p, q, h + 1 / 3) * 255),
    Math.round(hue2rgb(p, q, h) * 255),
    Math.round(hue2rgb(p, q, h - 1 / 3) * 255),
  ]
}

/// Excel's tint: luminance toward white (tint > 0) or black (tint < 0).
export function applyTint(hex: string, tint: number): string {
  const rgb = parseHex(hex)
  if (!rgb) return hex
  if (tint === 0) return toHex(rgb)
  const [h, s, l] = rgbToHsl(rgb)
  const lum = tint < 0 ? l * (1 + tint) : l * (1 - tint) + tint
  return toHex(hslToRgb(h, s, Math.min(1, Math.max(0, lum))))
}

interface ThemeBase {
  readonly dark1: string
  readonly accent: (index: number) => string
}

function themeBase(themeColors: readonly string[] | undefined): ThemeBase {
  const slot = (index: number): string | undefined => {
    const value = themeColors?.[index]
    return value && parseHex(value) ? value : undefined
  }
  return {
    dark1: slot(1) ?? '#000000',
    accent: (index) => {
      const wrapped = ((index - 1) % 6) + 1
      return slot(3 + wrapped) ?? DEFAULT_ACCENTS[wrapped - 1]!
    },
  }
}

export function builtinTablePalette(
  styleName: string | undefined,
  themeColors: readonly string[] | undefined,
): TableStylePalette {
  if (!styleName) return {}
  const match = /^TableStyle(Light|Medium|Dark)(\d+)$/.exec(styleName)
  const family = (match?.[1] ?? 'Medium') as TableStyleFamily
  const number = Number(match?.[2] ?? (family === 'Medium' ? 2 : 1))
  const theme = themeBase(themeColors)
  const accentIndex = Math.max(0, number - 1) % 7
  const neutral = accentIndex === 0
  const base = neutral ? theme.dark1 : theme.accent(accentIndex)
  const band = (color: string, fromDark1: boolean, tint: number): string =>
    applyTint(color, fromDark1 ? tint + 0.05 : tint)
  const variant = Math.floor(Math.max(0, number - 1) / 7)
  const palette: TableStylePalette = {}
  if (family === 'Light') {
    if (variant === 0) {
      palette.headerFontColor = applyTint(base, -0.25)
      palette.stripeFill = band(base, neutral, 0.8)
      palette.totalRowFontColor = applyTint(base, -0.25)
      palette.totalRowBorderColor = base
      palette.totalRowBorderStyle = 'thin'
      palette.borderColor = base
    } else if (variant === 1) {
      palette.headerFill = base
      palette.headerFontColor = WHITE
      palette.totalRowBorderColor = base
      palette.totalRowBorderStyle = 'double'
    } else {
      palette.headerFontColor = theme.dark1
      palette.stripeFill = band(base, neutral, 0.8)
      palette.totalRowBorderColor = base
      palette.totalRowBorderStyle = 'double'
      palette.wholeTableBorderColor = base
      palette.wholeTableBorderStyle = 'thin'
      palette.innerHorizontalBorderColor = base
      palette.innerHorizontalBorderStyle = 'thin'
      palette.innerVerticalBorderColor = base
      palette.innerVerticalBorderStyle = 'thin'
    }
  } else if (family === 'Medium') {
    if (variant === 1) {
      palette.headerFill = base
      palette.headerFontColor = WHITE
      palette.stripeFill = band(base, neutral, 0.6)
      palette.secondRowStripeFill = band(base, neutral, 0.8)
      palette.wholeTableFill = band(base, neutral, 0.8)
      palette.totalRowFill = base
      palette.totalRowFontColor = WHITE
    } else if (variant === 2) {
      palette.headerFill = base
      palette.headerFontColor = WHITE
      palette.stripeFill = applyTint(theme.dark1, 0.85)
      palette.totalRowBorderColor = theme.dark1
      palette.totalRowBorderStyle = 'double'
    } else if (variant === 3) {
      palette.headerFill = band(base, neutral, 0.8)
      palette.headerFontColor = theme.dark1
      palette.stripeFill = band(base, neutral, 0.6)
      palette.wholeTableFill = band(base, neutral, 0.8)
      palette.totalRowFill = band(base, neutral, 0.8)
      palette.totalRowBorderColor = base
      palette.totalRowBorderStyle = 'medium'
    } else {
      palette.headerFill = base
      palette.headerFontColor = WHITE
      palette.stripeFill = band(base, neutral, 0.8)
      palette.totalRowBorderColor = base
      palette.totalRowBorderStyle = 'double'
    }
  } else if (variant === 1) {
    const bandBase = neutral ? theme.dark1 : theme.accent(2 * (number - 8) - 1)
    const headerBase = neutral ? theme.dark1 : theme.accent(2 * (number - 8))
    palette.headerFill = headerBase
    palette.headerFontColor = WHITE
    palette.stripeFill = band(bandBase, neutral, 0.6)
    palette.secondRowStripeFill = band(bandBase, neutral, 0.8)
    palette.wholeTableFill = band(bandBase, neutral, 0.8)
    palette.totalRowFill = band(bandBase, neutral, 0.8)
    palette.totalRowBorderColor = theme.dark1
    palette.totalRowBorderStyle = 'double'
  } else {
    palette.headerFill = theme.dark1
    palette.headerFontColor = WHITE
    if (neutral) {
      palette.wholeTableFill = applyTint(theme.dark1, 0.45)
      palette.stripeFill = applyTint(theme.dark1, 0.25)
      palette.totalRowFill = applyTint(theme.dark1, 0.15)
    } else {
      palette.wholeTableFill = base
      palette.stripeFill = applyTint(base, -0.25)
      palette.totalRowFill = applyTint(base, -0.5)
    }
    palette.bodyFontColor = WHITE
    palette.totalRowFontColor = WHITE
  }
  if (palette.stripeFill) palette.columnStripeFill = palette.stripeFill
  return palette
}

type NativeTable = NonNullable<WorkbookModel['sheets'][number]['tables']>[number]

export function nativeTableThemeId(sheetId: string, tableId: string): string {
  return `native-file-table:${JSON.stringify([sheetId, tableId])}`
}

// 不把未知自定义样式误当 Medium2；None 与未知样式继续使用空主题。
export function nativeTableTheme(table: Pick<NativeTable, 'style' | 'headerRowCount' | 'totalsRowCount'> & { customStyle?: NativeTable['customStyle'] | undefined },
  themePalette: readonly string[] | undefined, name: string): IRangeThemeStyleJSON | undefined {
  const match = /^TableStyle(Light|Medium|Dark)([1-9][0-9]?)$/.exec(table.style?.name ?? '')
  const custom = table.customStyle?.name === table.style?.name ? table.customStyle : undefined
  if (!custom && (!match || Number(match[2]) > TABLE_STYLE_COUNTS[match[1] as TableStyleFamily])) return
  const palette: TableStylePalette = custom?.palette ?? builtinTablePalette(table.style!.name, themePalette)
  const fill = (rgb?: string): IRangeThemeStyleItem => rgb ? { bg: { rgb } } : {}
  const whole: IRangeThemeStyleItem = { ...fill(palette.wholeTableFill), ...(palette.bodyFontColor ? { cl: { rgb: palette.bodyFontColor } } : {}) }
  const theme: IRangeThemeStyleJSON = { name, wholeStyle: whole }
  if (!custom && (palette.innerHorizontalBorderColor || palette.innerVerticalBorderColor)) {
    const edge = (color: string) => ({ s: 1, cl: { rgb: color } })
    whole.bd = {
      ...(palette.innerHorizontalBorderColor ? { t: edge(palette.innerHorizontalBorderColor), b: edge(palette.innerHorizontalBorderColor) } : {}),
      ...(palette.innerVerticalBorderColor ? { l: edge(palette.innerVerticalBorderColor), r: edge(palette.innerVerticalBorderColor) } : {}),
    }
  }
  if (table.headerRowCount > 0) {
    theme.headerRowStyle = { bg: { rgb: palette.headerFill ?? '' }, bl: 1,
      ...(palette.headerFontColor || custom ? { cl: { rgb: palette.headerFontColor ?? (palette.headerFill ? '#FFFFFF' : '#333333') } } : {}) }
    if (custom && palette.headerBottomBorderColor) theme.headerRowStyle.bd = { b: tableBorder(palette.headerBottomBorderColor, palette.headerBottomBorderStyle) }
    if (palette.borderColor) theme.headerRowStyle.bd = {
      t: { s: 8, cl: { rgb: palette.borderColor } }, b: { s: 1, cl: { rgb: palette.borderColor } },
    }
  } else if (palette.borderColor) {
    // 固定源顶部框线与是否显示表头无关；首个数据行仍保留条纹且不加粗。
    theme.headerRowStyle = { bd: { t: { s: 8, cl: { rgb: palette.borderColor } } } }
  }
  if (table.style?.showRowStripes) {
    const first = fill(palette.stripeFill), second = fill(palette.secondRowStripeFill)
    // 官方模型 offset=1 使用 firstRowStyle；无表头时首个数据格 offset=0。
    theme.firstRowStyle = table.headerRowCount > 0 ? first : second
    theme.secondRowStyle = table.headerRowCount > 0 ? second : first
  }
  if (table.style?.showColumnStripes) {
    // 官方模型的 firstColumnStyle 对应奇数偏移；Excel firstColumnStripe 从0开始。
    theme.secondColumnStyle = fill(palette.columnStripeFill)
    theme.firstColumnStyle = fill(custom ? palette.secondColumnStripeFill : palette.wholeTableFill)
  }
  if (table.style?.showFirstColumn) theme.headerColumnStyle = { bl: 1, ...fill(palette.firstColumnFill) }
  if (table.style?.showLastColumn) theme.lastColumnStyle = { bl: 1, ...fill(palette.lastColumnFill) }
  if (table.totalsRowCount > 0) {
    theme.lastRowStyle = { bg: { rgb: palette.totalRowFill ?? '' }, bl: 1,
      ...(palette.totalRowFontColor ? { cl: { rgb: palette.totalRowFontColor } } : {}) }
    if (palette.totalRowBorderColor) theme.lastRowStyle.bd = {
      t: tableBorder(palette.totalRowBorderColor, palette.totalRowBorderStyle),
    }
  }
  if (palette.borderColor) theme.lastRowStyle = { ...theme.lastRowStyle, bd: {
    ...theme.lastRowStyle?.bd, b: { s: 8, cl: { rgb: palette.borderColor } },
  } }
  return theme
}

export function nativeTableThemes(model: WorkbookModel, sheets: Record<string, { id: string; name: string }>): NonNullable<IUniverSheetsTableConfig['userThemes']> {
  const themes: NonNullable<IUniverSheetsTableConfig['userThemes']> = []
  for (const sheet of Object.values(sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)
    if (!source || source.tablesReadOnlyReason) continue
    for (const table of source.tables ?? []) {
      const theme = nativeTableTheme(table, model.themePalette, nativeTableThemeId(sheet.id, table.id))
      if (theme) { const { name, ...style } = theme; themes.push({ name, style }) }
    }
  }
  return themes
}

// 工作簿读取晚于插件创建；使用官方资源注册本工作簿主题，避免跨修订全局残留。
export function nativeTableThemeResource(model: WorkbookModel, sheets: Record<string, { id: string; name: string }>) {
  const themes = nativeTableThemes(model, sheets)
  return { name: 'SHEET_RANGE_THEME_MODEL_PLUGIN', data: JSON.stringify({
    rangeThemeStyleMapJson: Object.fromEntries(themes.map(({ name, style }) => [name, { name, ...style }])),
  }) }
}

export function withNativeTableThemes<T extends { sheets: Record<string, { id: string; name: string }>; resources?: { name: string; data: string }[] }>(data: T, model: WorkbookModel): T & { resources: { name: string; data: string }[] } {
  const theme = nativeTableThemeResource(model, data.sheets)
  const resources = (data.resources ?? []).filter(resource => resource.name !== theme.name).map(resource => {
    if (resource.name !== 'SHEET_TABLE_PLUGIN') return resource
    const tables = JSON.parse(resource.data)
    for (const sheet of Object.values(data.sheets)) {
      const source = model.sheets.find(item => item.name === sheet.name)
      for (const table of source?.tables ?? []) {
        const id = nativeTableThemeId(sheet.id, table.id)
        if (!nativeTableTheme(table, model.themePalette, id)) continue
        const registered = tables[sheet.id]?.tables?.find((entry: { id: string }) => entry.id === `file-table-${sheet.id}-${table.id}`)
        if (registered) registered.meta = { ...registered.meta, nativeTableThemeId: id }
      }
    }
    return { ...resource, data: JSON.stringify(tables) }
  })
  return Object.assign(data, { resources: [theme, ...resources] })
}

const tableBorder = (rgb: string, style?: string) => ({ s: (univerBorderStyleId(style ?? 'thin') ?? 1) as BorderStyleTypes, cl: { rgb } })

// 官方RangeThemeStyle不能区分四角/外边界；在现有只读渲染副本中补这些边。
function customTableCellEdges(palette: CustomTablePalette, table: any, row: number, column: number): IRangeThemeStyleItem {
  const range = table.getRange(), header = table.isShowHeader() && row === range.startRow
  const totals = table.getTableMeta().nativeTotalsRowCount ?? (table.isShowFooter() ? 1 : 0)
  const border: NonNullable<IRangeThemeStyleItem['bd']> = {}
  if (palette.innerHorizontalBorderColor && row < range.endRow) border.b = tableBorder(palette.innerHorizontalBorderColor, palette.innerHorizontalBorderStyle)
  if (palette.innerVerticalBorderColor && column < range.endColumn) border.r = tableBorder(palette.innerVerticalBorderColor, palette.innerVerticalBorderStyle)
  if (palette.headerBottomBorderColor && header) border.b = tableBorder(palette.headerBottomBorderColor, palette.headerBottomBorderStyle)
  if (palette.wholeTableBorderColor) {
    const edge = tableBorder(palette.wholeTableBorderColor, palette.wholeTableBorderStyle)
    if (row === range.startRow) border.t = edge
    if (row === range.endRow) border.b = edge
    if (column === range.startColumn) border.l = edge
    if (column === range.endColumn) border.r = edge
  }
  if (totals && row === range.endRow && palette.totalRowBorderColor) border.t = tableBorder(palette.totalRowBorderColor, palette.totalRowBorderStyle)
  const firstHeader = header && column === range.startColumn && table.getTableMeta().nativeTableStyle?.showFirstColumn && palette.firstHeaderCellFontColor
  return { bd: border, ...(firstHeader ? { cl: { rgb: firstHeader } } : {}) }
}

// 固定源 applyTableBanding：自动黑字体让位于表格文字色，空填充不是显式填充。
// 只调整 CELL_CONTENT 的返回副本，保存/撤销继续使用原始样式，用户实色保持优先。
export function installNativeTableStyleRendering(injector: Injector) {
  const tables = injector.get(TableManager), themes = injector.get(SheetRangeThemeModel)
  const instances = injector.get(IUniverInstanceService)
  const refresh = () => {
    for (const workbook of instances.getAllUnitsForType<Workbook>(UniverInstanceType.UNIVER_SHEET)) {
      const unitId = workbook.getUnitId()
      for (const info of tables.getTableList(unitId)) {
        const table = tables.getTable(unitId, info.id)!, name = table.getTableMeta().nativeTableThemeId
        if (typeof name !== 'string' || !name.startsWith('native-file-table:') || name === table.getTableStyleId()) continue
        const rangeInfo = { unitId, subUnitId: info.subUnitId, range: table.getRange() }
        themes.removeRangeThemeRule(table.getTableStyleId(), rangeInfo)
        table.setTableStyleId(name)
        themes.registerRangeThemeRule(name, rangeInfo)
      }
    }
  }
  refresh()
  const initialized = tables.tableInitStatus$.subscribe(ready => { if (ready) refresh() })
  const renderer = injector.get(SheetInterceptorService).intercept(INTERCEPTOR_POINT.CELL_CONTENT, {
    id: 'native-file-table-style', effect: InterceptorEffectEnum.Style,
    handler: (cell, context, next) => {
      const rendered = next(cell)
      if (!rendered) return rendered
      const { unitId, subUnitId, row, col, workbook } = context
      const native = tables.getTablesBySubunitId(unitId, subUnitId).find(table => {
        const range = table.getRange()
        return table.getTableStyleId().startsWith('native-file-table:') && row >= range.startRow && row <= range.endRow && col >= range.startColumn && col <= range.endColumn
      })
      if (!native) return rendered
      let theme = themes.getCellStyle(unitId, subUnitId, row, col)
      const style = workbook.getStyles().getStyleByCell(rendered)
      if (!theme) return rendered
      const customStyle = native.getTableMeta().nativeCustomTableStyle
      const custom: CustomTablePalette | undefined = customStyle?.name === native.getTableMeta().nativeTableStyle?.name ? customStyle?.palette : undefined
      if (custom) theme = { ...theme, ...customTableCellEdges(custom, native, row, col) }
      const inherited: IStyleData = { ...style }
      if (custom && theme.bd) {
        inherited.bd = { ...inherited.bd, ...theme.bd }
      }
      const isHeader = native.isShowHeader() && row === native.getRange().startRow
      const hasFill = !!inherited.bg?.rgb
      const automaticFont = !inherited.cl?.rgb || inherited.cl.rgb.toUpperCase() === '#000000'
      const header = themes.getRangeThemeStyle(unitId, native.getTableStyleId()).getHeaderRowStyle()
      // 固定源：无显式填充的表头必定加粗；实色填充只在自动字体采用主题表头填充时加粗。
      const forceHeader = isHeader && (!hasFill || !!header?.bg?.rgb && automaticFont)
      let themeStyle = custom ? { ...rendered.themeStyle, ...theme } : rendered.themeStyle
      if (forceHeader) inherited.bl = 1
      else if (isHeader && hasFill) {
        themeStyle = { ...themeStyle }
        delete themeStyle.bl
        delete themeStyle.cl
      }
      if (theme.cl && automaticFont && (!hasFill || forceHeader)) delete inherited.cl
      if (theme.bg && inherited.bg?.rgb === '') delete inherited.bg
      return { ...rendered, s: inherited, themeStyle }
    },
  })
  return { refresh, dispose() { initialized.unsubscribe(); renderer.dispose() } }
}
