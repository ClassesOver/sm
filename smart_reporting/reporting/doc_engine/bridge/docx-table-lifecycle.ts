/** Source-preserving lifecycle for ordinary rectangular body tables.
 * Mirrors pinned GenOffice splitTableAtSelection: upper, blank paragraph, lower;
 * lower identity and alternative text are reset. The caller owns body scope and
 * the exactly-one-operation transaction boundary (including empty-body filler).
 */
import { createHash } from 'node:crypto'
import { XMLValidator } from 'fast-xml-parser'
import type { Block } from '@genoffice/docx-engine'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { attrsOf, childrenOf, xmlParser } from '../packages/docx-engine/src/xml-utils.ts'
import { tableStructureAvailability } from './docx-table-structure.ts'
import { tableAltTextAvailability } from './docx-table-alt-text.ts'

export type TableLifecycleOperation =
  | { kind: 'deleteTable'; blockId: string; expectedObjectSha256: string }
  | { kind: 'splitTable'; blockId: string; expectedObjectSha256: string; row: number }
export interface TableLifecycleContext { blockId: string; expectedObjectSha256: string; protectedDocument: boolean }
const fail = (code: string): never => { throw new Error(`docx_table_lifecycle_${code}`) }
const hash = (xml: string) => createHash('sha256').update(xml).digest('hex')
const sha = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const opening = (xml: string) => /^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/.exec(xml)?.[0] ?? fail('source_unsupported')
type Child = { name: string; xml: string; start: number; end: number }
function children(xml: string): Child[] {
  const open = opening(xml)
  if (open.endsWith('/>')) return []
  const end = xml.lastIndexOf('</'), inner = xml.slice(open.length, end)
  let cursor = 0
  const parts = splitXmlChildren(inner).map(child => {
    cursor += /^\s*/.exec(inner.slice(cursor))![0].length
    if (!inner.startsWith(child.xml, cursor)) fail('source_unsupported')
    const start = open.length + cursor
    cursor += child.xml.length
    return { ...child, start, end: open.length + cursor }
  })
  if (inner.slice(cursor).trim()) fail('source_unsupported')
  return parts
}
function remove(xml: string, parts: Child[]) {
  for (const part of [...parts].sort((a, b) => b.start - a.start)) xml = xml.slice(0, part.start) + xml.slice(part.end)
  return xml
}
/** Lifecycle never resizes: normalize only validated width/layout metadata for
 * the structure guard, whose fixed-width contract is needed by row/column edits.
 * These bytes are never used in either lifecycle output table. */
function structurePropsProjection(props: string, grid: Child) {
  const items = children(props)
  const widths = items.filter(part => part.name === 'w:tblW')
  const layouts = items.filter(part => part.name === 'w:tblLayout')
  if (widths.length > 1 || layouts.length > 1) fail('width_unsupported')
  const gridColumns = children(grid.xml)
  const total = gridColumns.reduce((sum, col) => {
    const attrs = attrsOf(xmlParser.parse(col.xml)[0])
    if (col.name !== 'w:gridCol' || children(col.xml).length || Object.keys(attrs).length !== 1
      || !/^\d+$/.test(attrs['w:w'] ?? '') || Number(attrs['w:w']) < 1 || Number(attrs['w:w']) > 31680) fail('width_unsupported')
    return sum + Number(attrs['w:w'])
  }, 0)
  if (!total || total > 31680) fail('width_unsupported')
  if (widths[0]) {
    const attrs = attrsOf(xmlParser.parse(widths[0].xml)[0]), value = attrs['w:w'], kind = attrs['w:type']
    if (children(widths[0].xml).length || Object.keys(attrs).length !== 2 || value === undefined || !/^\d+$/.test(value)
      || !['auto', 'dxa', 'pct'].includes(kind)
      || (kind === 'auto' && Number(value) !== 0)
      || (kind === 'dxa' && Number(value) !== total)
      || (kind === 'pct' && (Number(value) < 1 || Number(value) > 5000))) fail('width_unsupported')
  }
  if (layouts[0]) {
    const attrs = attrsOf(xmlParser.parse(layouts[0].xml)[0])
    if (children(layouts[0].xml).length || Object.keys(attrs).length !== 1 || !['fixed', 'autofit'].includes(attrs['w:type'])) fail('width_unsupported')
  }
  const retained = remove(props, [...widths, ...layouts])
  const at = opening(retained).length
  return retained.slice(0, at) + `<w:tblW w:w="${total}" w:type="dxa"/><w:tblLayout w:type="fixed"/>` + retained.slice(at)
}
function sourceOf(block: Block) {
  const xml = block.originalXml
  if (block.type !== 'table' || !block.table || !xml || xml.length > 1024 * 1024
    || block.sdtShell || block.sdtShells?.length || block.blockRevision || block.hidden
    || XMLValidator.validate(xml) !== true || !/^<w:tbl(?:\s|>)/.test(xml)) fail('source_unsupported')
  const nodes = xmlParser.parse(xml)
  if (nodes.length !== 1) fail('source_unsupported')
  // Namespaces are inherited from document.xml. Reject local rebinding anywhere
  // rather than interpreting an element with a familiar spelling under a new URI.
  const pending = [...nodes]
  while (pending.length) {
    const node = pending.pop()!
    if (Object.keys(attrsOf(node)).some(name => name === 'xmlns' || name.startsWith('xmlns:'))) fail('namespace_unsupported')
    pending.push(...childrenOf(node))
  }
  const identity = Object.keys(attrsOf(nodes[0]))
  if (identity.some(name => !['w:rsidR', 'w:rsidRPr', 'w:rsidDel'].includes(name))) fail('identity_unsupported')
  if (identity.some(name => !/^[a-fA-F0-9]{8}$/.test(attrsOf(nodes[0])[name]))) fail('identity_unsupported')
  const parts = children(xml), props = parts.filter(part => part.name === 'w:tblPr')
  if (props.length !== 1) fail('source_unsupported')
  const alt = children(props[0].xml).filter(part => part.name === 'w:tblCaption' || part.name === 'w:tblDescription')
  // Reuse the independent alt-text source/model guard before allowing these two
  // known fields through the strict structure validator's narrower projection.
  const altState = tableAltTextAvailability(block)
  if (!altState.tableAltTextEditable) fail('alt_text_unsupported')
  const strippedProps = remove(props[0].xml, alt)
  const grids = parts.filter(part => part.name === 'w:tblGrid')
  if (grids.length !== 1) fail('source_unsupported')
  const guardProps = structurePropsProjection(strippedProps, grids[0])
  const projected = '<w:tbl>' + xml.slice(opening(xml).length, props[0].start) + guardProps + xml.slice(props[0].end)
  const safe = tableStructureAvailability({ ...block, originalXml: projected })
  if (!safe.structureEditable) fail('source_unsupported')
  const rows = parts.filter(part => part.name === 'w:tr')
  // Metadata must precede a contiguous row run; disallow ambiguous ordering that
  // the structure guard otherwise accepts because it only needs a grid.
  if (parts[0]?.name !== 'w:tblPr' || parts[1]?.name !== 'w:tblGrid' || parts.slice(2).some(part => part.name !== 'w:tr')) fail('source_unsupported')
  return { xml, rows, props: props[0], strippedProps }
}

export function tableLifecycleAvailability(block: Block, protectionLocked: boolean): { tableLifecycleEditable: boolean; tableLifecycleReadOnlyReason: string | null } {
  try {
    if (typeof protectionLocked !== 'boolean' || protectionLocked) fail('protected')
    sourceOf(block)
    return { tableLifecycleEditable: true, tableLifecycleReadOnlyReason: null }
  } catch (error) {
    return { tableLifecycleEditable: false, tableLifecycleReadOnlyReason: error instanceof Error ? error.message : 'docx_table_lifecycle_unsupported' }
  }
}

export function editDocxTableLifecycle(block: Block, operation: unknown, context: TableLifecycleContext): { kind: TableLifecycleOperation['kind']; sourceXml: string; replacementXml: string } {
  if (!operation || typeof operation !== 'object' || Array.isArray(operation)) fail('operation_invalid')
  const op = operation as Record<string, unknown>, fields = ['kind', 'blockId', 'expectedObjectSha256', ...(op.kind === 'splitTable' ? ['row'] : [])]
  if (!['splitTable', 'deleteTable'].includes(op.kind as string) || Object.keys(op).length !== fields.length || Object.keys(op).some(key => !fields.includes(key))) fail('operation_invalid')
  if (!context || context.protectedDocument !== false) fail('protected')
  if (typeof context.blockId !== 'string' || !context.blockId || op.blockId !== context.blockId
    || !sha(op.expectedObjectSha256) || !sha(context.expectedObjectSha256) || op.expectedObjectSha256 !== context.expectedObjectSha256) fail('anchor_invalid')
  // Never trust client capability flags, row counts, or the caller's hash alone.
  const source = sourceOf(block)
  if (hash(source.xml) !== context.expectedObjectSha256) fail('anchor_invalid')
  if (op.kind === 'deleteTable') return { kind: 'deleteTable', sourceXml: source.xml, replacementXml: '' }
  if (typeof op.row !== 'number' || !Number.isInteger(op.row) || op.row < 1 || op.row >= source.rows.length) fail('row_invalid')
  const cut = source.rows[op.row].start, firstRow = source.rows[0].start
  const upper = source.xml.slice(0, cut) + '</w:tbl>'
  const prefix = source.xml.slice(0, firstRow)
  const lowerPrefix = '<w:tbl>' + prefix.slice(opening(prefix).length, source.props.start) + source.strippedProps + prefix.slice(source.props.end)
  const lower = lowerPrefix + source.xml.slice(cut)
  return { kind: 'splitTable', sourceXml: source.xml, replacementXml: upper + '<w:p/>' + lower }
}
