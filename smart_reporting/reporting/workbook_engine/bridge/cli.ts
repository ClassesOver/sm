import { readFile, writeFile } from 'node:fs/promises'
import JSZip from 'jszip'
import { z } from 'zod'
import {
  createBlankWorkbook, applySheetEdits, applyCellEdits, applyColumnWidths, applyPageSetups,
  readWorkbook, validateSheetName, workbookStyleEditSchema, applyRowHeights, applySheetFilter,
  formatAddress, parseRange, escapeXmlText, type CellEdit,
} from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from './operations'
import { applyStaticImages, workbookSourceMapping } from './images'

const scalar = z.union([z.string(), z.number().finite(), z.boolean(), z.null()])
const rowCell = z.union([scalar, z.object({
  value: scalar, formula: z.string().optional(), style: workbookStyleEditSchema.optional(),
  valueType: z.enum(['percentPoints', 'date']).optional(),
}).strict()])
const sheetSchema = z.object({
  name: z.string().min(1).max(31), rows: z.array(z.array(rowCell).max(16384)).max(1048576),
  headerRow: z.number().int().min(0).optional(), sectionId: z.string().optional(),
  analysisIds: z.array(z.string()).optional(),
  cellTypes: z.record(z.string(), z.literal('percentPoints')).optional(),
  signatureSheet: z.boolean().optional(),
  signatureFontSizes: z.array(z.number().min(6).max(72)).optional(),
  signatureRowHeights: z.array(z.number().min(8).max(409)).optional(),
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
  const prefs = request.preferences
  const edits: CellEdit[] = []
  for (const sheet of sheets) {
    for (let row = 0; row < sheet.rows.length; row += 1) {
      for (let column = 0; column < sheet.rows[row]!.length; column += 1) {
        const raw = sheet.rows[row]![column]!
        const content = raw !== null && typeof raw === 'object' ? raw : { value: raw }
        const header = row === (sheet.headerRow ?? 0)
        const style = {
          ...(header ? { bold: true, fillColor: '#17365D', fontColor: '#FFFFFF', wrapText: true } : { wrapText: true }),
          ...(prefs ? (() => {
            const value = sheet.signatureSheet && row > 0 ? prefs.signature : header ? prefs.header : prefs.body
            const border = { style: 'thin' as const, color: '#D8E3ED' }
            const rgb = prefs.common.accentColor.slice(1).match(/../g).map((value: string) => parseInt(value, 16) / 255)
            const luminance = rgb.map((value: number) => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
              .reduce((sum: number, value: number, index: number) => sum + value * [.2126, .7152, .0722][index]!, 0)
            return { fontFamily: prefs.fontNames[value.font], fontSize: value.size, fontColor: value.color, bold: value.bold,
              ...(header ? { fillColor: prefs.common.accentColor, fontColor: luminance > .179 ? '#000000' : '#FFFFFF' } : {}),
              horizontalAlignment: sheet.signatureSheet ? prefs.signature.align : prefs.alignment, wrapText: sheet.signatureSheet || prefs.wrapText,
              ...(sheet.signatureSheet ? { fontSize: sheet.signatureFontSizes![row] } : {}),
              ...(prefs.borders === 'all' ? { borderTop: border, borderBottom: border, borderLeft: border, borderRight: border } : prefs.borders === 'light' && header ? { borderBottom: border } : {}),
              ...(prefs.striped && !header && row % 2 === 0 ? { fillColor: '#F4F7FA' } : {}),
              ...(typeof content.value === 'number' ? { numberFormat: (content.valueType ?? sheet.cellTypes?.[formatAddress(row, column)]) === 'percentPoints' ? prefs.percentPointsFormat : prefs.numberFormat } : {}) }
          })() : {}),
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
      index, widthChars: sheet.signatureSheet ? 60 : prefs?.columnWidth ?? (index === 0 ? 28 : 20),
    })))
  }
  if (prefs) for (const sheet of sheets) {
    if (sheet.signatureSheet || prefs.rowHeight != null) bytes = await applyRowHeights(bytes, sheet.name, sheet.rows.map((_, index) => ({ index, heightPoints: sheet.signatureSheet ? sheet.signatureRowHeights![index]! : prefs.rowHeight })))
    if (prefs.autoFilter && !sheet.signatureSheet && sheet.rows.length > 1) {
      const width = Math.max(...sheet.rows.map(row => row.length))
      bytes = await applySheetFilter(bytes, sheet.name, { filter: { range: { startRow: sheet.headerRow ?? 0, endRow: sheet.rows.length - 1, startColumn: 0, endColumn: width - 1 }, columns: [] }, hiddenRows: [] })
    }
  }
  bytes = await applyPageSetups(bytes, sheets.map(sheet => prefs ? ({
    sheetName: sheet.name, orientation: prefs.print.page.orientation, paperSize: ({ A4: 9, A3: 8, Letter: 1 } as Record<string, number>)[prefs.print.page.paper],
    fitToPage: sheet.signatureSheet || prefs.print.scalePercent == null, fitToWidth: sheet.signatureSheet ? 1 : prefs.print.fitToWidth ?? 0, fitToHeight: sheet.signatureSheet ? 0 : prefs.print.fitToHeight ?? 0,
    ...(sheet.signatureSheet || prefs.print.scalePercent == null ? {} : { scale: prefs.print.scalePercent }),
    frozenRows: prefs.freezeHeader && !sheet.signatureSheet ? (sheet.headerRow ?? 0) + 1 : 0,
    printTitles: prefs.print.repeatTitleRows && !sheet.signatureSheet ? '1:' + prefs.print.repeatTitleRows : null,
    printArea: 'A1:' + formatAddress(sheet.rows.length - 1, Math.max(...sheet.rows.map(row => row.length)) - 1),
    header: prefs.print.header, footer: prefs.print.footer,
  }) : ({
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
    if (prefs) {
      const margins = prefs.print.page.margins
      const hf = prefs.print.headerFooter
      const marginXml = '<pageMargins left="' + margins.left / 25.4 + '" right="' + margins.right / 25.4 + '" top="' + margins.top / 25.4 + '" bottom="' + margins.bottom / 25.4 + '" header="' + hf.headerDistance / 25.4 + '" footer="' + hf.footerDistance / 25.4 + '"/>'
      xml = /<pageMargins\b[^>]*\/>/.test(xml) ? xml.replace(/<pageMargins\b[^>]*\/>/, marginXml) : xml.replace(/<pageSetup\b/, marginXml + '<pageSetup')
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
  const images = await applyStaticImages(bytes, request.images ?? [])
  bytes = images.bytes
  if (prefs) {
    // 新建报表的自动打印范围覆盖实际嵌入的图表；拒用图片不扩大范围。
    const accepted: { sheetName: string; range: string }[] = (await workbookSourceMapping(bytes)).images ?? []
    bytes = await applyPageSetups(bytes, sheets.flatMap(sheet => {
      const ranges = accepted.filter(image => image.sheetName === sheet.name).map(image => parseRange(image.range))
      if (!ranges.length) return []
      const lastRow = Math.max(sheet.rows.length - 1, ...ranges.map(range => range.endRow))
      const lastColumn = Math.max(...sheet.rows.map(row => row.length - 1),
        ...ranges.map(range => range.endColumn))
      return [{ sheetName: sheet.name, printArea: 'A1:' + formatAddress(lastRow, lastColumn) }]
    }))
  }
  const model = await readWorkbook(bytes)
  await writeFile(request.output, bytes)
  console.log(JSON.stringify({ sheetCount: model.sheets.length, issues: [...images.issues, ...(prefs?.layoutIssues ?? [])] }))
}

async function main() {
  const request = JSON.parse(await readFile(process.argv[2]!, 'utf-8'))
  if (request.kind === 'create') return create(request)
  const bytes = new Uint8Array(await readFile(request.input))
  if (request.kind === 'inspect') {
    const mapping = await workbookSourceMapping(bytes)
    console.log(JSON.stringify({ ...await readWorkbook(bytes), sourceMapping: mapping, images: mapping.images ?? [] }))
  }
  else if (request.kind === 'patch') {
    let output: Uint8Array = bytes
    for (const operation of request.operations) {
      output = operation.kind === 'applyStaticImages'
        ? (await applyStaticImages(output, operation.images, operation.sourceMapping, operation.imageIssues)).bytes
        : await applyWorkbookOperations(output, [operation])
    }
    await readWorkbook(output)
    await writeFile(request.output, output)
    console.log(JSON.stringify({ ok: true }))
  } else throw new Error('workbook_request_invalid')
}
main().catch(error => { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1 })
