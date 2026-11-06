/** Local acceptance probe only; this does not expose native structural operations. */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { parseDocx, saveDocx, generateTableModelXml, type TableModel, type SaveBlock } from '@genoffice/docx-engine'

const [source, destination] = process.argv.slice(2)
if (!source || !destination) throw new Error('Usage: tsx probes/docx-table-structure.ts SOURCE.docx NEW_OUTPUT_DIRECTORY')
const output = resolve(destination)
await mkdir(output) // Refuse an existing directory; never overwrite previous evidence.
const parsed = await parseDocx(await readFile(source))
const blocks = parsed.blocks.filter(block => !block.hidden)
const target = blocks.find(block => block.table)
if (!target?.table || !target.originalXml) throw new Error('Probe requires a source table with original XML')
if (target.table.rows.length !== 3 || target.table.rows.some(row => row.length !== 3 || row.some(cell => cell.colSpan || cell.vMerge || cell.gridGap || cell.nestedTables?.length))) throw new Error('Probe fixture must be a simple 3x3 rectangle')
const rowArrays = ['rowHeightsTwips', 'rowHeightRules', 'repeatHeaderRows', 'rowCantSplit', 'rawTrPrs', 'rowRevisions', 'rowPrChanges', 'rawTblPrExs', 'rowTblPrExChanges'] as const
const blankCell = () => ({ paras: [''], richParas: [{ runs: [] }] })
const cases: Record<string, unknown>[] = []
for (const operation of ['original', 'regenerate', 'insertRow', 'deleteRow', 'insertColumn', 'deleteColumn']) {
  const positions = ['original', 'regenerate'].includes(operation) ? [0] : operation.startsWith('insert') ? [0, 1, 3] : [0, 1, 2]
  for (const index of positions) {
    const model: TableModel = structuredClone(target.table)
    if (operation === 'insertRow' || operation === 'deleteRow') {
      if (operation === 'insertRow') model.rows.splice(index, 0, Array.from({ length: 3 }, blankCell))
      else model.rows.splice(index, 1)
      for (const key of rowArrays) {
        const values = model[key] as unknown[] | undefined
        if (values) {
          if (operation === 'insertRow') values.splice(index, 0, null)
          else values.splice(index, 1)
        }
      }
    }
    if (operation === 'insertColumn' || operation === 'deleteColumn') {
      const widths = [...model.colWidthsTwips!]
      if (operation === 'insertColumn') {
        const neighbor = Math.min(index, widths.length - 1)
        const width = widths[neighbor]!
        if (width < 2) throw new Error('Cannot split width')
        if (index === widths.length) widths.splice(neighbor, 1, Math.floor(width / 2), width - Math.floor(width / 2))
        else widths.splice(index, 1, Math.floor(width / 2), width - Math.floor(width / 2))
        for (const row of model.rows) row.splice(index, 0, blankCell())
      } else {
        const [removed] = widths.splice(index, 1)
        widths[Math.min(index, widths.length - 1)]! += removed!
        for (const row of model.rows) row.splice(index, 1)
      }
      model.colWidthsTwips = widths
      const total = widths.reduce((a, b) => a + b, 0)
      model.colWidthsPct = widths.map(width => width / total * 100)
    }
    const finalBlocks: SaveBlock[] = blocks.map(block => block === target && operation !== 'original'
      ? { kind: 'xml', docxIndex: block.docxIndex, xml: generateTableModelXml(model, target.originalXml) }
      : { kind: 'original', docxIndex: block.docxIndex })
    const bytes = await saveDocx(parsed, finalBlocks)
    const name = `${operation}-${index}.docx`
    await writeFile(resolve(output, name), bytes)
    const reopened = await parseDocx(bytes)
    cases.push({ operation, index, file: name, engineMatrix: reopened.blocks.find(block => block.table)?.table?.rows.map(row => row.map(cell => cell.paras.join('\n'))) })
  }
}
await writeFile(resolve(output, 'engine-cases.json'), JSON.stringify(cases, null, 2))
