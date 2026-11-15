import {z} from 'zod'
import {formatAddress, parseRange} from '../packages/xlsx-engine/src/cell-address'
import {isValidDefinedName} from '../packages/xlsx-engine/src/defined-names'
import {applyTableAdditions, collectExistingTableNames} from '../packages/xlsx-engine/src/table-add'
import {readWorkbook} from '../packages/xlsx-engine/src/workbook-read'
import {applyCellEdits, type CellEdit} from '../packages/xlsx-engine/src/workbook-write'
import {createBufferEntrySource} from '../packages/xlsx-engine/src/zip'

const schema = z.object({
  kind: z.literal('applyTableSource'),
  sheetName: z.string().min(1).max(31),
  range: z.string().max(32),
  name: z.string().refine(isValidDefinedName).optional(),
  style: z.string().regex(/^TableStyle(?:Light|Medium|Dark)[1-9][0-9]?$/).optional(),
  bandedRows: z.boolean().default(true),
}).strict()

export async function applyTableSource(bytes: Uint8Array, raw: unknown): Promise<Uint8Array> {
  const operation = schema.parse(raw)
  const area = parseRange(operation.range)
  const width = area.endColumn - area.startColumn + 1
  if (area.endRow <= area.startRow || area.endRow >= 1048576 || area.endColumn >= 16384 || width > 1000) {
    throw new Error('workbook_ai_table_range_invalid')
  }
  const workbook = await readWorkbook(bytes)
  const sheet = workbook.sheets.find(item => item.name === operation.sheetName)
  if (!sheet) throw new Error('workbook_ai_table_sheet_invalid')

  let name = operation.name
  if (!name) {
    const names = await collectExistingTableNames(await createBufferEntrySource(bytes))
    for (const entry of workbook.definedNames ?? []) names.add(entry.name.toLowerCase())
    let index = 1
    while (names.has(`table${index}`)) index++
    name = `Table${index}`
  }
  const used = new Set<string>()
  const edits: CellEdit[] = []
  const columnNames = Array.from({length: width}, (_, index) => {
    const column = area.startColumn + index
    const header = sheet.cells[formatAddress(area.startRow, column)]
    if (header?.formula) throw new Error('workbook_ai_table_formula_header_unsupported')
    const base = String(header?.value ?? '').trim().slice(0, 255) || `Column${index + 1}`
    let label = base
    for (let suffix = 2; used.has(label.toLowerCase()); suffix++) {
      const tail = String(suffix)
      label = base.slice(0, 255 - tail.length) + tail
    }
    used.add(label.toLowerCase())
    if (header?.value !== label) {
      edits.push({sheetName: sheet.name, row: area.startRow, column, writeValue: true, cell: {value: label}})
    }
    return label
  })
  const table = await applyTableAdditions(bytes, [{
    worksheetSheetName: sheet.name, area, name, columnNames,
    style: operation.style, bandedRows: operation.bandedRows,
  }])
  return applyCellEdits(table, edits)
}
