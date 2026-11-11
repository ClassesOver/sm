/** 来源表格合并/拆分：共享固定源 PM 语义，只在服务端保留并拼装原段落 XML。 */
import type { Block, TableModel } from '@genoffice/docx-engine'
import { decodeEntities, generateTableModelXml } from '@genoffice/docx-engine'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { applyTableCellShapeSteps, Schema, TableMap, type TableCellShapeStep } from '../../../report_editor/frontend/src/docx-table-cell-shape-core.ts'

export interface CellShapeRect { top: number; left: number; bottom: number; right: number }
export interface CellShapeCell extends CellShapeRect { physicalRow: number; physicalColumn: number }
interface SourceCell extends CellShapeCell { xml: string; paragraphs: string[]; model: TableModel['rows'][number][number] }
function fail(code: string): never { throw new Error(`docx_table_cell_shape_${code}`) }
const attr = (xml: string, key: string) => new RegExp(`(?:^|\\s)${key}=(?:"([^"]*)"|'([^']*)')`).exec(xml)?.slice(1).find(value => value !== undefined)
function children(xml: string, tag: string) {
  if (!new RegExp(`^<${tag}\\s*>[\\s\\S]*</${tag}>$`).test(xml)) fail('shell_unsupported')
  const inner = xml.slice(xml.indexOf('>') + 1, xml.lastIndexOf('</'))
  const parts = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== parts.map(part => part.xml).join('').replace(/\s/g, '')) fail('xml_unsupported')
  return parts
}
function allowed(parts: ReturnType<typeof splitXmlChildren>, names: string[], repeating: string[] = []) {
  if (parts.some(part => !names.includes(part.name)) || names.some(name => !repeating.includes(name) && parts.filter(part => part.name === name).length > 1)) fail('properties_unsupported')
}
const one = (parts: ReturnType<typeof splitXmlChildren>, tag: string) => parts.find(part => part.name === tag)?.xml
function width(xml: string | undefined) {
  const w = xml && attr(xml, 'w:w')
  if (!w || !/^\d+$/.test(w) || Number(w) < 1 || Number(w) > 31680) fail('width_unsupported')
  return Number(w)
}
function paragraphText(xml: string) {
  return [...xml.matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>|<w:(tab|br|cr)\b[^>]*\/>/g)].map(match => match[1] !== undefined ? decodeEntities(match[1]) : match[2] === 'tab' ? '\t' : '\n').join('')
}
function sourceOf(block: Block) {
  if (block.type !== 'table' || !block.table || !block.originalXml) fail('unsupported')
  const xml = block.originalXml, model = block.table
  if (xml.length > 1024 * 1024 || /<!--|<!\[CDATA\[|<\?/.test(xml)) fail('xml_unsupported')
  if (/<w:(?:ins|del|moveFrom|moveTo|sdt|hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|pPrChange|rPrChange|tblPrExChange|cellIns|cellDel|cellMerge|hyperlink|fldSimple|fldChar|instrText|drawing|pict|object|bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|commentReference|sectPr|numPr|tblpPr|bidiVisual)\b/.test(xml)) fail('content_unsupported')
  const parts = children(xml, 'w:tbl'); allowed(parts, ['w:tblPr', 'w:tblGrid', 'w:tr'], ['w:tr'])
  const tblPr = one(parts, 'w:tblPr'), grid = one(parts, 'w:tblGrid')
  if (!tblPr || !grid) fail('width_unsupported')
  const props = children(tblPr, 'w:tblPr')
  allowed(props, ['w:tblW', 'w:tblLayout', 'w:tblBorders', 'w:tblCellMar', 'w:tblStyle', 'w:tblLook', 'w:jc', 'w:tblInd', 'w:shd'])
  if (attr(one(props, 'w:tblLayout') ?? '', 'w:type') !== 'fixed' || attr(one(props, 'w:tblW') ?? '', 'w:type') !== 'dxa') fail('width_unsupported')
  const columns = children(grid, 'w:tblGrid'); allowed(columns, ['w:gridCol'], ['w:gridCol'])
  const widths = columns.map(column => width(column.xml))
  if (!widths.length || widths.length > 30 || width(one(props, 'w:tblW')) !== widths.reduce((a, b) => a + b, 0)) fail('width_unsupported')
  const rows = parts.filter(part => part.name === 'w:tr')
  if (!rows.length || rows.length > 100 || rows.length * widths.length > 1000 || model.rows.length !== rows.length) fail('size_unsupported')
  const cells: SourceCell[] = [], headers: boolean[] = []
  let active = new Map<number, SourceCell>()
  rows.forEach((row, r) => {
    const rowParts = children(row.xml, 'w:tr'); allowed(rowParts, ['w:trPr', 'w:tc'], ['w:tc'])
    const trPr = one(rowParts, 'w:trPr')
    if (trPr) allowed(children(trPr, 'w:trPr'), ['w:trHeight', 'w:tblHeader', 'w:cantSplit'])
    const header = trPr && one(children(trPr, 'w:trPr'), 'w:tblHeader')
    headers.push(!!header && !['0', 'off', 'false'].includes(attr(header, 'w:val') ?? ''))
    const rowCells = rowParts.filter(part => part.name === 'w:tc')
    if (rowCells.length !== model.rows[r].length) fail('model_mismatch')
    let col = 0
    const next = new Map<number, SourceCell>()
    rowCells.forEach((item, c) => {
      const content = children(item.xml, 'w:tc'); allowed(content, ['w:tcPr', 'w:p'], ['w:p'])
      const tcPr = one(content, 'w:tcPr')
      if (!tcPr) fail('properties_unsupported')
      const tcProps = children(tcPr, 'w:tcPr')
      allowed(tcProps, ['w:tcW', 'w:gridSpan', 'w:vMerge', 'w:tcBorders', 'w:shd', 'w:vAlign', 'w:textDirection', 'w:tcMar', 'w:noWrap'])
      const spanXml = one(tcProps, 'w:gridSpan'), spanValue = spanXml ? attr(spanXml, 'w:val') : '1'
      if (!spanValue || !/^\d+$/.test(spanValue)) fail('grid_unsupported')
      const span = Number(spanValue), mergeXml = one(tcProps, 'w:vMerge'), merge = mergeXml ? attr(mergeXml, 'w:val') ?? 'continue' : undefined
      if (!Number.isSafeInteger(span) || span < 1 || col + span > widths.length || merge && !['restart', 'continue'].includes(merge)) fail('grid_unsupported')
      const tcW = one(tcProps, 'w:tcW')
      if (attr(tcW ?? '', 'w:type') !== 'dxa' || width(tcW) !== widths.slice(col, col + span).reduce((a, b) => a + b, 0)) fail('width_unsupported')
      const paragraphs = content.filter(part => part.name === 'w:p').map(part => part.xml)
      if (!paragraphs.length) fail('content_unsupported')
      for (const paragraph of paragraphs) {
        const body = paragraph.replace(/^<w:p\b[^>]*>/, '').replace(/<\/w:p>$/, '')
        if (paragraph === '<w:p/>') continue
        const pParts = splitXmlChildren(body); allowed(pParts, ['w:pPr', 'w:r'], ['w:r'])
        for (const run of pParts.filter(part => part.name === 'w:r')) {
          const runParts = splitXmlChildren(run.xml.replace(/^<w:r\b[^>]*>/, '').replace(/<\/w:r>$/, ''))
          allowed(runParts, ['w:rPr', 'w:t', 'w:tab', 'w:br', 'w:cr'], ['w:t', 'w:tab', 'w:br', 'w:cr'])
          if (runParts.some(part => part.name === 'w:br' && attr(part.xml, 'w:type') && attr(part.xml, 'w:type') !== 'textWrapping')) fail('content_unsupported')
        }
      }
      const m = model.rows[r][c]
      if ((m.colSpan ?? 1) !== span || m.vMerge !== merge || m.gridGap || m.nestedTables?.length || JSON.stringify(m.paras) !== JSON.stringify(paragraphs.map(paragraphText))) fail('model_mismatch')
      const record: SourceCell = { top: r, left: col, bottom: r + 1, right: col + span, physicalRow: r, physicalColumn: c, xml: item.xml, paragraphs, model: m }
      if (merge === 'continue') {
        const owner = active.get(col)
        if (!owner || owner.right !== col + span) fail('grid_unsupported')
        // 结构变化不能丢掉continue自己的隐藏内容/特殊格式。
        if (paragraphs.length !== 1 || !/^<w:p\s*\/>$|^<w:p\s*>\s*<\/w:p>$/.test(paragraphs[0]) || tcProps.some(part => !['w:tcW', 'w:gridSpan', 'w:vMerge'].includes(part.name))) fail('continuation_unsupported')
        owner.bottom = r + 1; next.set(col, owner)
      } else {
        cells.push(record)
        if (merge === 'restart') next.set(col, record)
      }
      col += span
    })
    if (col !== widths.length) fail('grid_unsupported')
    active = next
  })
  const firstNonHeader = headers.indexOf(false)
  if (firstNonHeader >= 0 && headers.slice(firstNonHeader).some(Boolean)) fail('header_unsupported')
  return { model, xml, widths, cells, tblPr }
}
/** 仅借用引擎结构字段，其他原属性（主题/边框space等）不经模型重建。 */
function structuralTcPr(original: string, generated: string) {
  const source = children(original, 'w:tcPr'), shell = children(generated, 'w:tcPr')
  const before = JSON.stringify(source)
  const order = ['w:cnfStyle', 'w:tcW', 'w:gridSpan', 'w:hMerge', 'w:vMerge', 'w:tcBorders', 'w:shd', 'w:noWrap', 'w:tcMar', 'w:textDirection', 'w:tcFitText', 'w:vAlign', 'w:hideMark']
  for (const name of ['w:tcW', 'w:gridSpan', 'w:vMerge']) {
    const index = source.findIndex(part => part.name === name), next = shell.find(part => part.name === name)
    if (!next) { if (index >= 0) source.splice(index, 1); continue }
    if (index >= 0) {
      const before = source[index].xml
      const same = name === 'w:tcW' ? attr(before, 'w:w') === attr(next.xml, 'w:w') && attr(before, 'w:type') === 'dxa'
        : (attr(before, 'w:val') ?? (name === 'w:vMerge' ? 'continue' : '1')) === (attr(next.xml, 'w:val') ?? (name === 'w:vMerge' ? 'continue' : '1'))
      if (!same) source[index] = next
    } else {
      const at = source.findIndex(part => order.indexOf(part.name) > order.indexOf(name))
      source.splice(at < 0 ? source.length : at, 0, next)
    }
  }
  if (before === JSON.stringify(source)) return original
  return '<w:tcPr>' + source.map(part => part.xml).join('') + '</w:tcPr>'
}
export function tableCellShapeAvailability(block: Block) {
  try {
    const source = sourceOf(block)
    return { cellShapeEditable: true, cellShapeReadOnlyReason: null, cellShapeWidthsTwips: source.widths,
      cellShapeCells: source.cells.map(({ top, left, bottom, right, physicalRow, physicalColumn }) => ({ top, left, bottom, right, physicalRow, physicalColumn })) }
  } catch (error) {
    return { cellShapeEditable: false, cellShapeReadOnlyReason: error instanceof Error ? error.message : 'docx_table_cell_shape_unsupported', cellShapeWidthsTwips: [] as number[], cellShapeCells: [] as CellShapeCell[] }
  }
}

export function editTableCellShape(block: Block, steps: readonly TableCellShapeStep[]) {
  const source = sourceOf(block)
  const schema = new Schema({ nodes: {
    doc: { content: 'docTable+' }, text: { group: 'inline' },
    docParagraph: { content: 'text*', attrs: { docxIndex: { default: null }, shapePPr: { default: null } } },
    docTable: { content: 'docTableRow+', tableRole: 'table', attrs: { colWidthsPct: { default: null } } },
    docTableRow: { content: 'docTableCell*', tableRole: 'row', attrs: { rawTrPr: { default: null }, heightTwips: { default: null }, heightRule: { default: null }, repeatHeader: { default: false }, repeatHeaderEdited: { default: false }, cantSplit: { default: false }, cantSplitEdited: { default: false }, rowRevision: { default: null } } },
    docTableCell: { content: 'docParagraph+', tableRole: 'cell', attrs: { colspan: { default: 1 }, rowspan: { default: 1 }, colwidth: { default: null }, modelCell: { default: null }, sourceXml: { default: null } } },
  } })
  const originals = new Map<string, string>()
  const table = schema.node('docTable', { colWidthsPct: source.widths.map(w => w / source.widths.reduce((a, b) => a + b, 0) * 100) }, source.model.rows.map((_, r) => schema.node('docTableRow', {
    rawTrPr: source.model.rawTrPrs?.[r] ?? null, heightTwips: source.model.rowHeightsTwips?.[r] ?? null, heightRule: source.model.rowHeightRules?.[r] ?? null,
    repeatHeader: !!source.model.repeatHeaderRows?.[r], cantSplit: !!source.model.rowCantSplit?.[r],
  }, source.cells.filter(cell => cell.top === r).map(cell => schema.node('docTableCell', {
    colspan: cell.right - cell.left, rowspan: cell.bottom - cell.top, colwidth: source.widths.slice(cell.left, cell.right).map(w => w / 15), modelCell: cell.model, sourceXml: cell.xml,
  }, cell.paragraphs.map((xml, p) => {
    const token = `${r}:${cell.physicalColumn}:${p}`; originals.set(token, xml)
    const text = paragraphText(xml)
    return schema.node('docParagraph', { docxIndex: token, shapePPr: /<w:pPr(?:\s[^>]*)?>[\s\S]*?<\/w:pPr>/.exec(xml)?.[0] ?? null }, text ? [schema.text(text)] : [])
  }))))))
  let projection: ReturnType<typeof applyTableCellShapeSteps>
  try { projection = applyTableCellShapeSteps(table, source.widths, steps) } catch (error) { fail(error instanceof Error ? error.message.replace(/^docx_table_cell_shape_/, '') : 'steps_invalid') }
  const result = projection.table, map = TableMap.get(result), widths = projection.widthsTwips
  const cells: (CellShapeCell & { paras: string[] })[] = [], bodies = new Map<string, string>(), rawCellProperties = new Map<string, string>(), rawCells = new Map<string, string>()
  const model: TableModel = { ...structuredClone(source.model), rows: [], colWidthsTwips: widths, colWidthsPct: widths.map(w => w / widths.reduce((a, b) => a + b, 0) * 100), rawTrPrs: [], rowHeightsTwips: [], rowHeightRules: [], repeatHeaderRows: [], rowCantSplit: [] }
  const seen = new Set<number>()
  for (let r = 0; r < map.height; r++) {
    const row = result.child(r)
    model.rawTrPrs!.push(row.attrs.rawTrPr); model.rowHeightsTwips!.push(row.attrs.heightTwips); model.rowHeightRules!.push(row.attrs.heightRule)
    model.repeatHeaderRows!.push(!!row.attrs.repeatHeader); model.rowCantSplit!.push(!!row.attrs.cantSplit)
    const entries: TableModel['rows'][number] = []
    for (let col = 0; col < map.width;) {
      const position = map.map[r * map.width + col], node = result.nodeAt(position)!, rect = map.findCell(position), colspan = rect.right - rect.left
      if (rect.left !== col) fail('projection_invalid')
      if (seen.has(position)) {
        entries.push({ paras: [''], colSpan: colspan > 1 ? colspan : undefined, vMerge: 'continue' })
        bodies.set(`${r}:${entries.length - 1}`, '<w:p/>')
      } else {
        seen.add(position)
        const paragraphs: string[] = [], texts: string[] = []
        node.forEach(paragraph => {
          const token = paragraph.attrs.docxIndex
          if (token !== null && !originals.has(token)) fail('origin_invalid')
          const original = token === null ? undefined : originals.get(token)
          // 新空段只继承首段pPr，不复制段落身份或run内容。
          const pPr = paragraph.attrs.shapePPr as string | null
          const blank = pPr ? `<w:p>${pPr}</w:p>` : '<w:p/>'
          paragraphs.push(original ?? blank); texts.push(paragraph.textContent)
        })
        const sourceCell = node.attrs.modelCell as TableModel['rows'][number][number]
        if (node.attrs.sourceXml) rawCells.set(`${r}:${entries.length}`, node.attrs.sourceXml)
        if (sourceCell.rawTcPr) rawCellProperties.set(`${r}:${entries.length}`, sourceCell.rawTcPr)
        entries.push({ ...structuredClone(sourceCell), paras: texts, richParas: undefined, colSpan: colspan > 1 ? colspan : undefined, vMerge: rect.bottom > r + 1 ? 'restart' : undefined })
        bodies.set(`${r}:${entries.length - 1}`, paragraphs.join(''))
        cells.push({ ...rect, physicalRow: r, physicalColumn: entries.length - 1, paras: texts })
      }
      col += colspan
    }
    model.rows.push(entries)
  }
  const generated = children(generateTableModelXml(model, source.xml), 'w:tbl')
  let r = 0
  const xml = '<w:tbl>' + generated.map(part => {
    if (part.name === 'w:tblPr') return source.tblPr
    if (part.name !== 'w:tr') return part.xml
    let c = 0
    const row = r++
    return '<w:tr>' + children(part.xml, 'w:tr').map(item => {
      if (item.name === 'w:trPr' && result.child(row).attrs.rawTrPr) return result.child(row).attrs.rawTrPr as string
      if (item.name !== 'w:tc') return item.xml
      const tcPr = one(children(item.xml, 'w:tc'), 'w:tcPr')!
      const key = `${row}:${c++}`, original = rawCellProperties.get(key)
      const patchedTcPr = original ? structuralTcPr(original, tcPr) : tcPr, originalCell = rawCells.get(key)
      if (originalCell) {
        const originalParagraphs = children(originalCell, 'w:tc').filter(part => part.name === 'w:p').map(part => part.xml).join('')
        if (originalParagraphs === bodies.get(key)) return originalCell.replace(original!, () => patchedTcPr)
      }
      return `<w:tc>${patchedTcPr}${bodies.get(key)!}</w:tc>`
    }).join('') + '</w:tr>'
  }).join('') + '</w:tbl>'
  // 同步验证实际XML逻辑网格/文字；实际ZIP parseDocx由调用者回读。
  const actual = sourceOf({ ...block, originalXml: xml, table: model })
  if (JSON.stringify(actual.cells.map(cell => ({ top: cell.top, left: cell.left, bottom: cell.bottom, right: cell.right, paras: cell.paragraphs.map(paragraphText) }))) !== JSON.stringify(cells.map(({ top, left, bottom, right, paras }) => ({ top, left, bottom, right, paras })))) fail('write_not_applied')
  return { xml, widthsTwips: widths, cells }
}

/** 调用方在产物parseDocx后核验实际逻辑网格、段落与宽度。 */
export function verifyTableCellShapeResult(block: Block, expected: ReturnType<typeof editTableCellShape>): void {
  if (block.originalXml !== expected.xml) fail('write_not_applied')
  const actual = sourceOf(block)
  const shape = actual.cells.map(({ top, left, bottom, right, paragraphs }) => ({ top, left, bottom, right, paras: paragraphs.map(paragraphText) }))
  if (JSON.stringify(actual.widths) !== JSON.stringify(expected.widthsTwips) || JSON.stringify(shape) !== JSON.stringify(expected.cells.map(({ top, left, bottom, right, paras }) => ({ top, left, bottom, right, paras })))) fail('write_not_applied')
}
