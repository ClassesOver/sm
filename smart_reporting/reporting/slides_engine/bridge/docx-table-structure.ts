/** Native adapter: generate structure with the pinned engine; keep surviving XML. */
import { generateTableModelXml, type Block, type TableModel } from '@genoffice/docx-engine'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'

export const TABLE_STRUCTURE_KINDS = ['insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn'] as const
export type TableStructureKind = typeof TABLE_STRUCTURE_KINDS[number]
const ROW_ARRAYS = ['rowHeightsTwips', 'rowHeightRules', 'repeatHeaderRows', 'rowCantSplit', 'rawTrPrs', 'rowRevisions', 'rowPrChanges', 'rawTblPrExs', 'rowTblPrExChanges'] as const
const MAX_ROWS = 100, MAX_COLUMNS = 30, MAX_CELLS = 1000
function fail(code: string): never { throw new Error(`docx_table_structure_${code}`) }
const attr = (xml: string, name: string) => new RegExp(`(?:^|\\s)${name}=(?:"([^"]*)"|'([^']*)')`).exec(xml)?.slice(1).find(value => value !== undefined)

function children(xml: string, tag: string) {
  // Shell attributes may carry unmodeled structural semantics; do not discard them.
  if (!new RegExp(`^<${tag}\\s*>[\\s\\S]*</${tag}>$`).test(xml)) fail('shell_unsupported')
  const inner = xml.slice(xml.indexOf('>') + 1, xml.lastIndexOf('</'))
  const parts = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== parts.map(part => part.xml).join('').replace(/\s/g, '')) fail('xml_unsupported')
  return parts
}
function allowed(parts: ReturnType<typeof splitXmlChildren>, names: string[]) {
  if (parts.some(part => !names.includes(part.name)) || names.some(name => parts.filter(part => part.name === name).length > 1 && !['w:tr', 'w:tc', 'w:p', 'w:r', 'w:gridCol'].includes(name))) fail('properties_unsupported')
}
function one(parts: ReturnType<typeof splitXmlChildren>, name: string) {
  return parts.find(part => part.name === name)?.xml
}
function positiveWidth(xml: string | undefined) {
  if (!xml || !/^<w:(?:tcW|tblW|gridCol)\s[^>]*\/>$/.test(xml)) fail('width_unsupported')
  const value = attr(xml, 'w:w')
  if (!value || !/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 31680) fail('width_unsupported')
  return Number(value)
}
function withWidth(cell: string, width: number) {
  const tcPr = one(children(cell, 'w:tc'), 'w:tcPr')!
  const tcW = one(children(tcPr, 'w:tcPr'), 'w:tcW')!
  const updatedWidth = tcW.replace(/(\sw:w=)(["'])\d+\2/, (_, prefix, quote) => `${prefix}${quote}${width}${quote}`)
  // Original XML is data: replacement strings would interpret $&, $` and $'.
  return cell.replace(tcPr, () => tcPr.replace(tcW, () => updatedWidth))
}

function sourceOf(block: Block) {
  if (block.type !== 'table' || !block.table || !block.originalXml) fail('unsupported')
  const xml = block.originalXml, model = block.table
  if (xml.length > 1024 * 1024 || /<!--|<!\[CDATA\[|<\?/.test(xml)) fail('xml_unsupported')
  // These objects need identity/layout rules beyond a rectangular structure edit.
  if (/<w:(?:ins|del|moveFrom|moveTo|sdt|vMerge|hMerge|gridSpan|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|pPrChange|rPrChange|tblPrExChange|cellIns|cellDel|cellMerge|hyperlink|fldSimple|fldChar|instrText|drawing|pict|object|bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|commentReference|sectPr|numPr|tblpPr|bidiVisual)\b/.test(xml)) fail('content_unsupported')
  const parts = children(xml, 'w:tbl')
  allowed(parts, ['w:tblPr', 'w:tblGrid', 'w:tr'])
  const tblPr = one(parts, 'w:tblPr')
  const grid = one(parts, 'w:tblGrid')
  if (!tblPr || !grid) fail('width_unsupported')
  const props = children(tblPr, 'w:tblPr')
  allowed(props, ['w:tblW', 'w:tblLayout', 'w:tblBorders', 'w:tblCellMar', 'w:tblStyle', 'w:tblLook', 'w:jc', 'w:tblInd', 'w:shd'])
  if (attr(one(props, 'w:tblLayout') ?? '', 'w:type') !== 'fixed' || attr(one(props, 'w:tblW') ?? '', 'w:type') !== 'dxa') fail('width_unsupported')
  const gridColumns = children(grid, 'w:tblGrid')
  allowed(gridColumns, ['w:gridCol'])
  const widths = gridColumns.map(part => positiveWidth(part.xml))
  if (positiveWidth(one(props, 'w:tblW')) !== widths.reduce((a, b) => a + b, 0)) fail('width_unsupported')
  const rows = parts.filter(part => part.name === 'w:tr').map(part => {
    const content = children(part.xml, 'w:tr')
    allowed(content, ['w:trPr', 'w:tc'])
    const trPr = one(content, 'w:trPr')
    if (trPr) allowed(children(trPr, 'w:trPr'), ['w:trHeight', 'w:tblHeader', 'w:cantSplit'])
    const cells = content.filter(child => child.name === 'w:tc').map((cell, ci) => {
      const content = children(cell.xml, 'w:tc')
      allowed(content, ['w:tcPr', 'w:p'])
      const tcPr = one(content, 'w:tcPr')
      if (!tcPr || !content.some(child => child.name === 'w:p')) fail('content_unsupported')
      const props = children(tcPr, 'w:tcPr')
      allowed(props, ['w:tcW', 'w:tcBorders', 'w:shd', 'w:vAlign', 'w:textDirection', 'w:tcMar', 'w:noWrap'])
      const tcW = one(props, 'w:tcW')
      if (attr(tcW ?? '', 'w:type') !== 'dxa' || positiveWidth(tcW) !== widths[ci]) fail('width_unsupported')
      // Preserve complete original paragraphs, including unmodeled pPr/attributes.
      for (const paragraph of content.filter(child => child.name === 'w:p')) {
        const body = paragraph.xml.replace(/^<w:p\b[^>]*>/, '').replace(/<\/w:p>$/, '')
        const elements = splitXmlChildren(body)
        allowed(elements, ['w:pPr', 'w:r'])
        // Repeated runs are legitimate; the duplicate check below is only for pPr.
        if (elements.filter(child => child.name === 'w:pPr').length > 1) fail('content_unsupported')
        for (const run of elements.filter(child => child.name === 'w:r')) {
          const runBody = run.xml.replace(/^<w:r\b[^>]*>/, '').replace(/<\/w:r>$/, '')
          if (splitXmlChildren(runBody).some(child => !['w:rPr', 'w:t', 'w:tab', 'w:br', 'w:cr'].includes(child.name))) fail('content_unsupported')
        }
      }
      return cell.xml
    })
    return { trPr: trPr ?? '', cells }
  })
  if (!rows.length || !widths.length || rows.length > MAX_ROWS || widths.length > MAX_COLUMNS || rows.length * widths.length > MAX_CELLS || rows.some(row => row.cells.length !== widths.length)) fail('size_unsupported')
  if (model.rows.length !== rows.length || model.rows.some(row => row.length !== widths.length || row.some(cell => (cell.colSpan ?? 1) !== 1 || cell.vMerge || cell.gridGap || cell.nestedTables?.length))) fail('model_mismatch')
  const headers = rows.map(row => {
    const tag = row.trPr ? one(children(row.trPr, 'w:trPr'), 'w:tblHeader') : undefined
    return !!tag && !['0', 'false', 'off'].includes(attr(tag, 'w:val') ?? '')
  })
  const headerCount = headers.findIndex(header => !header) < 0 ? headers.length : headers.findIndex(header => !header)
  if (headers.slice(headerCount).some(Boolean)) fail('header_unsupported')
  return { model, originalXml: xml, tblPr, rows, widths, headerCount }
}

export function tableStructureAvailability(block: Block): { structureEditable: boolean; structureReadOnlyReason: string | null } {
  try { sourceOf(block); return { structureEditable: true, structureReadOnlyReason: null } }
  catch (error) { return { structureEditable: false, structureReadOnlyReason: error instanceof Error ? error.message : 'docx_table_structure_unsupported' } }
}

export function editTableStructure(block: Block, kind: TableStructureKind, index: number) {
  const source = sourceOf(block)
  const inserting = kind.startsWith('insert'), rowOperation = kind.endsWith('Row')
  if (!TABLE_STRUCTURE_KINDS.includes(kind)) fail('operation_invalid')
  const count = rowOperation ? source.rows.length : source.widths.length
  if (!Number.isInteger(index) || index < 0 || index >= count + Number(inserting)) fail('index_invalid')
  if (!inserting && count === 1) fail('last_dimension')
  const nextRows = source.rows.length + (rowOperation ? inserting ? 1 : -1 : 0)
  const nextColumns = source.widths.length + (!rowOperation ? inserting ? 1 : -1 : 0)
  if (nextRows > MAX_ROWS || nextColumns > MAX_COLUMNS || nextRows * nextColumns > MAX_CELLS) fail('size_unsupported')
  const model: TableModel = structuredClone(source.model)
  const rowIds: (number | null)[] = source.rows.map((_, i) => i)
  const columnIds: (number | null)[] = source.widths.map((_, i) => i)
  const widths = [...source.widths]
  // Inserting inside the repeating prefix must keep it contiguous for Word.
  const newHeader = inserting && rowOperation && index < source.headerCount
  const blankCell = () => ({ paras: [''], richParas: [{ runs: [] }] })
  if (rowOperation) {
    if (inserting) { model.rows.splice(index, 0, widths.map(blankCell)); rowIds.splice(index, 0, null) }
    else { model.rows.splice(index, 1); rowIds.splice(index, 1) }
    for (const key of ROW_ARRAYS) {
      const values = model[key] as unknown[] | undefined
      if (values) inserting ? values.splice(index, 0, key === 'repeatHeaderRows' && newHeader ? true : null) : values.splice(index, 1)
    }
  } else {
    if (inserting) {
      const neighbor = Math.min(index, count - 1), width = widths[neighbor]!
      if (width < 2) fail('width_too_small')
      widths.splice(neighbor, 1, Math.floor(width / 2), width - Math.floor(width / 2))
      columnIds.splice(index, 0, null)
      for (const row of model.rows) row.splice(index, 0, blankCell())
    } else {
      const [removed] = widths.splice(index, 1)
      widths[Math.min(index, widths.length - 1)]! += removed!
      columnIds.splice(index, 1)
      for (const row of model.rows) row.splice(index, 1)
    }
  }
  model.colWidthsTwips = widths
  model.colWidthsPct = widths.map(width => width / widths.reduce((a, b) => a + b, 0) * 100)
  const generated = children(generateTableModelXml(model, source.originalXml), 'w:tbl')
  let ri = 0
  const xml = '<w:tbl>' + generated.map(part => {
    if (part.name === 'w:tblPr') return source.tblPr
    if (part.name !== 'w:tr') return part.xml
    const sourceRow = rowIds[ri++]
    let ci = 0
    const content = children(part.xml, 'w:tr').filter(child => child.name !== 'w:trPr').map(child => {
      if (child.name !== 'w:tc') return child.xml
      const column = columnIds[ci]!, width = widths[ci++]!
      return sourceRow === null || column === null ? child.xml : withWidth(source.rows[sourceRow!]!.cells[column]!, width)
    }).join('')
    return `<w:tr>${sourceRow === null ? newHeader ? '<w:trPr><w:tblHeader/></w:trPr>' : '' : source.rows[sourceRow!]!.trPr}${content}</w:tr>`
  }).join('') + '</w:tbl>'
  const matrix = rowIds.map(row => columnIds.map(column => row === null || column === null ? '' : source.model.rows[row]![column]!.paras.join('\n')))
  return { xml, matrix, widths }
}
