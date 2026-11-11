// 固定GenOffice f8c17004 native/xlsx-engine/src/table_styles.rs 的已有样式读取。
// 仅显示投影，不重建styles.xml，不增加自定义样式创建协议。
import { parseColor } from './style-read'
import { resolveStyleColor } from './style-color'
import { decodeXmlText, extractElements, readCoreAttribute, sectionInner } from './xml'

export type CustomTablePalette = Partial<Record<
  'headerFill' | 'headerFontColor' | 'stripeFill' | 'secondRowStripeFill' | 'columnStripeFill' | 'secondColumnStripeFill' |
  'wholeTableFill' | 'firstColumnFill' | 'lastColumnFill' | 'totalRowFill' | 'totalRowFontColor' |
  'totalRowBorderColor' | 'totalRowBorderStyle' | 'firstHeaderCellFontColor' |
  'wholeTableBorderColor' | 'wholeTableBorderStyle' | 'innerHorizontalBorderColor' | 'innerHorizontalBorderStyle' |
  'innerVerticalBorderColor' | 'innerVerticalBorderStyle' | 'headerBottomBorderColor' | 'headerBottomBorderStyle', string>>
export interface CustomTableStyle { name: string; palette: CustomTablePalette }

// ECMA indexed颜色表；与固定源visuals/colors.rs相同，64/65为系统前景/背景。
const INDEXED = ('000000 FFFFFF FF0000 00FF00 0000FF FFFF00 FF00FF 00FFFF 000000 FFFFFF FF0000 00FF00 0000FF FFFF00 FF00FF 00FFFF 800000 008000 000080 808000 800080 008080 C0C0C0 808080 9999FF 993366 FFFFCC CCFFFF 660066 FF8080 0066CC CCCCFF 000080 FF00FF FFFF00 00FFFF 800080 800000 008080 0000FF 00CCFF CCFFFF CCFFCC FFFF99 99CCFF FF99CC CC99FF FFCC99 3366FF 33CCCC 99CC00 FFCC00 FF9900 FF6600 666699 969696 003366 339966 003300 333300 993300 993366 333399 333333 000000 FFFFFF').split(' ')
const tag = (xml: string, name: string) => xml.match(new RegExp(`<${name}\\b[^>]*>`))?.[0] ?? ''

export function createStylesheetColorResolver(xml: string, themePalette?: readonly string[]): (entry: string) => string | undefined {
  const indexed = extractElements(sectionInner(xml, 'indexedColors') ?? '', 'rgbColor').map(entry => parseColor(entry))
  return (entry: string): string | undefined => {
    const parsed = parseColor(entry) ?? parseColor(entry.replace(/\s+theme="[^"]*"/, ''))
    if (parsed !== undefined) return resolveStyleColor(parsed, themePalette)
    const index = readCoreAttribute(entry, 'indexed')
    if (index === undefined || !/^\d+$/.test(index)) return
    const value = Number(index), override = value < 64 ? indexed[value] : undefined
    return override !== undefined ? resolveStyleColor(override, themePalette) : INDEXED[value] ? '#' + INDEXED[value] : undefined
  }
}

export function readCustomTableStyles(xml: string, themePalette?: readonly string[]): Map<string, CustomTableStyle> {
  const color = createStylesheetColorResolver(xml, themePalette)
  const dxfs = extractElements(sectionInner(xml, 'dxfs') ?? '', 'dxf').map(dxf => {
    const fill = sectionInner(dxf, 'fill') ?? '', pattern = sectionInner(fill, 'patternFill')
    let fillColor = pattern === null ? undefined : color(tag(pattern, 'bgColor') || tag(pattern, 'fgColor'))
    if (pattern === null) {
      const stops = extractElements(sectionInner(fill, 'gradientFill') ?? '', 'stop').flatMap(stop => {
        const value = color(tag(stop, 'color')), position = Number(readCoreAttribute(stop, 'position'))
        return value && Number.isFinite(position) ? [{ value, position }] : []
      }).sort((a, b) => a.position - b.position)
      if (stops.length) {
        const first = stops[0]!.value, last = stops[stops.length - 1]!.value
        fillColor = '#' + [1, 3, 5].map(index => Math.floor((parseInt(first.slice(index, index + 2), 16) + parseInt(last.slice(index, index + 2), 16)) / 2).toString(16).padStart(2, '0')).join('').toUpperCase()
      }
    }
    const border = sectionInner(dxf, 'border') ?? ''
    const edge = (name: string) => {
      const entry = extractElements(border, name)[0]
      const style = entry ? readCoreAttribute(entry, 'style') : undefined
      return entry && style && style !== 'none' ? { color: color(tag(entry, 'color')), style } : undefined
    }
    return { fillColor, fontColor: color(tag(sectionInner(dxf, 'font') ?? '', 'color')), edge }
  })
  const styles = new Map<string, CustomTableStyle>()
  for (const entry of extractElements(sectionInner(xml, 'tableStyles') ?? '', 'tableStyle')) {
    const rawName = readCoreAttribute(tag(entry, 'tableStyle'), 'name')
    if (!rawName) continue
    const name = decodeXmlText(rawName), palette: CustomTablePalette = {}
    const put = (key: keyof CustomTablePalette, value: string | undefined) => { if (value !== undefined) palette[key] = value }
    const border = (prefix: 'wholeTableBorder' | 'innerHorizontalBorder' | 'innerVerticalBorder' | 'headerBottomBorder' | 'totalRowBorder', edge: ReturnType<typeof dxfs[number]['edge']>) => {
      put(`${prefix}Color`, edge?.color); put(`${prefix}Style`, edge?.style)
    }
    for (const element of extractElements(entry, 'tableStyleElement')) {
      const id = readCoreAttribute(element, 'dxfId')
      if (id === undefined || !/^\d+$/.test(id)) continue
      const dxf = dxfs[Number(id)]
      if (!dxf) continue
      switch (readCoreAttribute(element, 'type')) {
        case 'wholeTable': put('wholeTableFill', dxf.fillColor); border('wholeTableBorder', dxf.edge('left') ?? dxf.edge('top')); border('innerHorizontalBorder', dxf.edge('horizontal')); border('innerVerticalBorder', dxf.edge('vertical')); break
        case 'headerRow': put('headerFill', dxf.fillColor); put('headerFontColor', dxf.fontColor); border('headerBottomBorder', dxf.edge('bottom')); break
        case 'totalRow': put('totalRowFill', dxf.fillColor); put('totalRowFontColor', dxf.fontColor); border('totalRowBorder', dxf.edge('top')); break
        case 'firstColumn': put('firstColumnFill', dxf.fillColor); break
        case 'lastColumn': put('lastColumnFill', dxf.fillColor); break
        case 'firstRowStripe': put('stripeFill', dxf.fillColor); break
        case 'secondRowStripe': put('secondRowStripeFill', dxf.fillColor); break
        case 'firstColumnStripe': put('columnStripeFill', dxf.fillColor); break
        case 'secondColumnStripe': put('secondColumnStripeFill', dxf.fillColor); break
        case 'firstHeaderCell': put('firstHeaderCellFontColor', dxf.fontColor); break
      }
    }
    styles.set(name, { name, palette })
  }
  return styles
}
