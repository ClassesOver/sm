import { readFile, writeFile } from 'node:fs/promises'
import JSZip from 'jszip'
import { z } from 'zod'
import {
  createBlankWorkbook, applySheetEdits, applyCellEdits, applyColumnWidths, applyPageSetups,
  readWorkbook, validateSheetName, workbookStyleEditSchema,
  formatAddress, escapeXmlText, type CellEdit,
} from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from './operations'

const scalar = z.union([z.string(), z.number().finite(), z.boolean(), z.null()])
const rowCell = z.union([scalar, z.object({
  value: scalar, formula: z.string().optional(), style: workbookStyleEditSchema.optional(),
}).strict()])
const sheetSchema = z.object({
  name: z.string().min(1).max(31), rows: z.array(z.array(rowCell).max(16384)).max(1048576),
  headerRow: z.number().int().min(0).optional(), sectionId: z.string().optional(),
  analysisIds: z.array(z.string()).optional(),
}).passthrough()

async function create(request: any): Promise<void> {
  const sheets = z.array(sheetSchema).min(1).max(256).parse(request.sheets)
  for (const sheet of sheets) validateSheetName(sheet.name)
  if (new Set(sheets.map(sheet => sheet.name.toLocaleLowerCase())).size !== sheets.length) {
    throw new Error('workbook_sheet_name_duplicate')
  }
  let bytes = await createBlankWorkbook(sheets[0]!.name)
  if (sheets.length > 1) bytes = await applySheetEdits(bytes, {
    renames: [], removals: [], additions: sheets.slice(1).map(sheet => ({ name: sheet.name })),
    order: sheets.map(sheet => sheet.name),
  })
  const edits: CellEdit[] = []
  for (const sheet of sheets) {
    for (let row = 0; row < sheet.rows.length; row += 1) {
      for (let column = 0; column < sheet.rows[row]!.length; column += 1) {
        const raw = sheet.rows[row]![column]!
        const content = raw !== null && typeof raw === 'object' ? raw : { value: raw }
        const header = row === (sheet.headerRow ?? 0)
        const style = {
          ...(header ? { bold: true, fillColor: '#17365D', fontColor: '#FFFFFF', wrapText: true } : { wrapText: true }),
          ...content.style,
        }
        edits.push({ sheetName: sheet.name, row, column, writeValue: true,
          cell: content.formula === undefined ? { value: content.value } : { value: content.value, formula: content.formula },
          style,
        })
      }
    }
  }
  bytes = await applyCellEdits(bytes, edits)
  for (const sheet of sheets) {
    const columns = sheet.rows.reduce((width, row) => Math.max(width, row.length), 1)
    bytes = await applyColumnWidths(bytes, sheet.name, Array.from({ length: columns }, (_, index) => ({
      index, widthChars: index === 0 ? 28 : 20,
    })))
  }
  bytes = await applyPageSetups(bytes, sheets.map(sheet => ({
    sheetName: sheet.name, orientation: 'landscape', paperSize: 9,
    fitToPage: true, fitToWidth: 1, fitToHeight: 0,
    frozenRows: (sheet.headerRow ?? 0) + 1,
    printTitles: `${(sheet.headerRow ?? 0) + 1}:${(sheet.headerRow ?? 0) + 1}`,
  })))
  const zip = await JSZip.loadAsync(bytes)
  // The engine intentionally clears caches on edits. Creation has frozen source
  // values for these formulas, so retain that known result for download/reopen.
  const createdModel = await readWorkbook(bytes)
  for (const sheet of sheets) {
    const path = createdModel.sheets.find(model => model.name === sheet.name)!.path
    let xml = await zip.file(path)!.async('string')
    for (let row = 0; row < sheet.rows.length; row += 1) {
      for (let column = 0; column < sheet.rows[row]!.length; column += 1) {
        const raw = sheet.rows[row]![column]
        if (raw === null || typeof raw !== 'object' || !raw.formula || raw.value === null) continue
        const address = formatAddress(row, column)
        const value = typeof raw.value === 'boolean' ? (raw.value ? '1' : '0') : escapeXmlText(String(raw.value))
        const type = typeof raw.value === 'string' ? ' t="str"' : typeof raw.value === 'boolean' ? ' t="b"' : ''
        const pattern = new RegExp(`<c r="${address}"([^>]*)>([\\s\\S]*?)</c>`)
        xml = xml.replace(pattern, (_match, attributes, body) => `<c r="${address}"${attributes}${type}>${body}<v>${value}</v></c>`)
      }
    }
    zip.file(path, xml)
  }
  zip.file('smart-reporting/source-mapping.json', JSON.stringify({
    version: 1, title: request.title, period: request.period,
    sources: request.sourceMapping ?? {},
    sheets: sheets.map(sheet => ({ name: sheet.name, sectionId: sheet.sectionId, analysisIds: sheet.analysisIds })),
  }))
  const contentTypes = await zip.file('[Content_Types].xml')!.async('string')
  zip.file('[Content_Types].xml', contentTypes.replace('</Types>', '<Override PartName="/smart-reporting/source-mapping.json" ContentType="application/json"/></Types>'))
  bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
  const model = await readWorkbook(bytes)
  await writeFile(request.output, bytes)
  console.log(JSON.stringify({ sheetCount: model.sheets.length, issues: [] }))
}

async function main() {
  const request = JSON.parse(await readFile(process.argv[2]!, 'utf-8'))
  if (request.kind === 'create') return create(request)
  const bytes = new Uint8Array(await readFile(request.input))
  if (request.kind === 'inspect') console.log(JSON.stringify(await readWorkbook(bytes)))
  else if (request.kind === 'patch') {
    const output = await applyWorkbookOperations(bytes, request.operations)
    await readWorkbook(output)
    await writeFile(request.output, output)
    console.log(JSON.stringify({ ok: true }))
  } else throw new Error('workbook_request_invalid')
}
main().catch(error => { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1 })
