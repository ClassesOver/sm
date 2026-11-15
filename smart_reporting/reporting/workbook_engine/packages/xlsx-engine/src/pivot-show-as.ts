import { SaxesParser } from 'saxes'
import { PIVOT_X14_SHOW_DATA_AS } from './pivot-value-modes'

// MS-XLSX 2.2.4.5 (Pivot Table) and Office2010 CT_DataField. Parent ratios
// are x14:pivotShowAs values, not standard ST_ShowDataAs enumerations.
export const PIVOT_DATA_FIELD_EXT_URI = '{E15A36E0-9728-4E99-A89B-3F7291B0FE68}'
export const PIVOT_X14_NS = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

/// In core dataField order. Unknown x14 modes/ambiguous extensions stay explicit
/// so the host can refuse destructive edits instead of treating them as normal.
export function readPivotShowAs(xml: string): string[] {
  const result: string[] = []
  const stack: { local: string; uri: string; extUri: string }[] = []
  let field: { depth: number; mode: string; extended: boolean } | undefined
  const parser = new SaxesParser({ xmlns: true })
  parser.on('opentag', tag => {
    const attr = (name: string) => Object.values(tag.attributes).find(a => a.uri === '' && a.local === name)?.value ?? ''
    const parent = stack.at(-1), grandparent = stack.at(-2)
    if ((tag.uri === MAIN_NS || tag.uri === '') && tag.local === 'dataField' && parent?.local === 'dataFields' && (parent.uri === MAIN_NS || parent.uri === '')) {
      const mode = attr('showDataAs')
      field = { depth: stack.length + 1, mode: mode === 'percent' ? 'percentOf' : mode, extended: false }
    } else if (field && tag.uri === PIVOT_X14_NS && tag.local === 'dataField') {
      const valid = parent?.local === 'ext' && (parent.uri === MAIN_NS || parent.uri === '') && parent.extUri.toUpperCase() === PIVOT_DATA_FIELD_EXT_URI && grandparent?.local === 'extLst' && (grandparent.uri === MAIN_NS || grandparent.uri === '') && stack.length === field.depth + 2
      const mode = attr('pivotShowAs')
      const olap = Object.values(tag.attributes).some(a => a.uri === '' && ['sourceField','uniqueName'].includes(a.local))
      field.mode = valid && !field.extended ? olap ? 'unsupported:x14-olap' : (PIVOT_X14_SHOW_DATA_AS as readonly string[]).includes(mode) ? mode : 'unsupported:x14-mode' : 'unsupported:x14-extension'
      field.extended = true
    }
    stack.push({ local: tag.local, uri: tag.uri, extUri: attr('uri') })
  })
  parser.on('closetag', () => {
    if (field && field.depth === stack.length) { result.push(field.mode); field = undefined }
    stack.pop()
  })
  parser.on('error', error => { throw error })
  parser.write(xml).close()
  return result
}
