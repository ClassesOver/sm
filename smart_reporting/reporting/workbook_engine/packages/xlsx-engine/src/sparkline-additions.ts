/** 固定源 xlsx-sparkline.ts 的追加协议；原有组始终保留原文。 */
import { SaxesParser } from 'saxes'
import { z } from 'zod'
import { parseSparklineSourceReference } from './sparklines'
import { renameSheetInFormula } from './sheets-edit'
import { parseAddress } from './cell-address'
import { escapeXmlText } from './xml'
import { createBufferEntrySource, assemblePackage } from './zip'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'

const MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const X14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const XM = 'http://schemas.microsoft.com/office/excel/2006/main'
const URI = '{05C60535-1F16-4fd2-B633-F4F36F0B64E0}'
export const appendSheetSparklinesOperationSchema = z.object({
  kind: z.literal('appendSheetSparklines'), sheetName: z.string().min(1).max(31),
  groups: z.array(z.object({
    type: z.enum(['line', 'column', 'stacked']), color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
    cells: z.array(z.object({ cell: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/), sourceRef: z.string().max(150) }).strict()).min(1).max(200),
  }).strict()).min(1).max(200),
}).strict().refine(op => op.groups.reduce((sum, group) => sum + group.cells.length, 0) <= 200, '迷你图新增上限为200个宿主。')
export type SparklineGroupAddition = z.infer<typeof appendSheetSparklinesOperationSchema>['groups'][number]
export const removeSheetSparklinesOperationSchema = z.object({
  kind: z.literal('removeSheetSparklines'), sheetName: z.string().min(1).max(31),
  targets: z.array(z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/)).min(1).max(200),
}).strict()
export const editSheetSparklineGroupOperationSchema = z.object({
  kind: z.literal('editSheetSparklineGroup'), sheetName: z.string().min(1).max(31),
  target: z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,6}$/),
  type: z.enum(['line', 'column', 'stacked']).optional(),
  color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
  negativeColor: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
  markers: z.boolean().optional(), showAxis: z.boolean().optional(),
}).strict().refine(op => Object.keys(op).some(key => !['kind', 'sheetName', 'target'].includes(key)), '至少指定一个迷你图组属性。')

function validCell(cell: string): void {
  const point = parseAddress(cell)
  if (point.row >= 1048576 || point.column >= 16384) throw Error(`迷你图单元格越界：${cell}`)
}
function validateSource(sourceRef: string, sheetName: string): void {
  const match = sourceRef.match(/^(?:'((?:[^']|'')+)'|([A-Za-z_\u0080-\uFFFF][A-Za-z0-9_.\u0080-\uFFFF]*))!\$([A-Z]{1,3})\$([1-9][0-9]{0,6}):\$([A-Z]{1,3})\$([1-9][0-9]{0,6})$/)
  if (!match || (match[1]?.replaceAll("''", "'") ?? match[2]) !== sheetName) throw Error('迷你图来源必须是同表的规范绝对引用。')
  const first = `${match[3]}${match[4]}`, last = `${match[5]}${match[6]}`
  validCell(first); validCell(last)
  if (match[4] !== match[6] || parseAddress(first).column >= parseAddress(last).column) throw Error('迷你图来源必须为单行且至少两列。')
}
interface Element {
  name: string; local: string; uri: string; start: number; openEnd: number; closeStart: number; end: number
  empty: boolean; text: string; parent: Element | undefined; children: Element[]; extensionUri?: string
}
/** saxes 提供命名空间身份与 span；只修改插入点，绝不序列化已有 XML。 */
function scan(xml: string): Element[] {
  const parser = new SaxesParser({ xmlns: true }), stack: Element[] = [], nodes: Element[] = []
  let start = 0
  parser.on('doctype', () => { throw Error('迷你图 XML 不支持 DOCTYPE。') })
  parser.on('opentagstart', () => { start = xml.lastIndexOf('<', parser.position - 1) })
  parser.on('opentag', tag => {
    const parent = stack.at(-1)
    const node: Element = { name: tag.name, local: tag.local, uri: tag.uri, start, openEnd: parser.position, closeStart: parser.position, end: parser.position, empty: tag.isSelfClosing, text: '', parent, children: [] }
    const extensionUri = Object.values(tag.attributes).find(attr => !attr.uri && attr.local === 'uri')?.value
    if (extensionUri !== undefined) node.extensionUri = extensionUri
    parent?.children.push(node); nodes.push(node); stack.push(node)
  })
  parser.on('text', text => { const node = stack.at(-1); if (node) node.text += text })
  parser.on('cdata', text => { const node = stack.at(-1); if (node) node.text += text })
  parser.on('closetag', () => {
    const node = stack.pop()!
    node.closeStart = node.empty ? node.openEnd : xml.lastIndexOf('</', parser.position - 1)
    node.end = parser.position
  })
  parser.write(xml).close()
  return nodes
}
async function worksheet(bytes: Uint8Array, sheetName: string) {
  const source = await createBufferEntrySource(bytes)
  const sheet = parseSheetElements(await source.readText('xl/workbook.xml')).find(sheet => sheet.name === sheetName)
  if (!sheet?.relationshipId) throw Error(`找不到工作表：${sheetName}`)
  const path = await resolveWorksheetPath(source, sheet.relationshipId)
  return { path, xml: await source.readText(path) }
}
/** bridge 对非标准 prefix 的原有组也执行结构保护。 */
export async function assertSheetSparklinesShiftable(bytes: Uint8Array, sheetName: string, geometry: 'rows-columns' | 'cells' = 'rows-columns'): Promise<void> {
  const source = await createBufferEntrySource(bytes)
  const sheets = parseSheetElements(await source.readText('xl/workbook.xml'))
  if (!sheets.some(sheet => sheet.name === sheetName)) throw Error(`找不到工作表：${sheetName}`)
  for (const sheet of sheets) {
    if (!sheet.relationshipId) continue
    const path = await resolveWorksheetPath(source, sheet.relationshipId), nodes = scan(await source.readText(path))
    if (sheet.name === sheetName && nodes.some(node => node.uri === X14 && node.local === 'sparklineGroups' || node.extensionUri?.toUpperCase() === URI.toUpperCase())) throw Error('含迷你图的工作表不能移位，以免来源和宿主错位。')
    // 其他页的宿主也可读取本页来源。只有 canonical xm:f 的整行列移位
    // 已由 shiftQualifiedFormulas 可靠同步；单元格带状移位与别名前缀尚不能同步。
    for (const node of nodes.filter(node => node.uri === XM && node.local === 'f' && node.parent?.uri === X14 && node.parent.local === 'sparkline')) {
      const reference = node.children.length ? undefined : parseSparklineSourceReference(node.text)
      if (!reference) throw Error(`迷你图来源无法可靠解析，不能移位：${sheet.name}`)
      const origin = reference.sourceSheet ?? sheet.name
      if (origin.toLowerCase() === sheetName.toLowerCase() && (geometry === 'cells' || node.name !== 'xm:f')) throw Error(`迷你图仍读取工作表“${sheetName}”的来源，暂不支持此结构移位。`)
    }
  }
}

function insert(xml: string, node: Element, content: string): string {
  if (node.empty) return xml.slice(0, node.start) + xml.slice(node.start, node.openEnd).replace(/\/>$/, `>${content}</${node.name}>`) + xml.slice(node.end)
  return xml.slice(0, node.closeStart) + content + xml.slice(node.closeStart)
}
export async function appendSheetSparklines(bytes: Uint8Array, sheetName: string, groups: readonly SparklineGroupAddition[]): Promise<Uint8Array> {
  const parsed = appendSheetSparklinesOperationSchema.parse({ kind: 'appendSheetSparklines', sheetName, groups })
  const seen = new Set<string>()
  for (const group of parsed.groups) for (const entry of group.cells) {
    validCell(entry.cell); validateSource(entry.sourceRef, sheetName)
    if (seen.has(entry.cell)) throw Error(`迷你图宿主重复：${entry.cell}`)
    seen.add(entry.cell)
  }
  const { path, xml } = await worksheet(bytes, sheetName), nodes = scan(xml)
  const root = nodes[0]
  if (!root || root.local !== 'worksheet' || root.uri !== MAIN) throw Error('迷你图不支持此工作表命名空间结构。')
  const lists = nodes.filter(node => node.parent === root && node.uri === MAIN && node.local === 'extLst')
  const extensions = nodes.filter(node => node.extensionUri?.toUpperCase() === URI.toUpperCase())
  if (lists.length > 1 || extensions.length > 1) throw Error('迷你图扩展结构不明确。')
  const ext = extensions[0]
  if (ext && (ext.parent !== lists[0] || ext.uri !== MAIN || ext.local !== 'ext')) throw Error('迷你图扩展结构不支持。')
  const containers = nodes.filter(node => node.uri === X14 && node.local === 'sparklineGroups')
  if (containers.length > 1 || containers.some(node => node.parent !== ext) || ext && (ext.children.length !== 1 || !containers.length)) throw Error('迷你图组结构不支持。')
  const container = containers[0]
  if (container) {
    for (const group of container.children) {
      if (group.uri !== X14 || group.local !== 'sparklineGroup') throw Error('迷你图组结构不支持。')
      const knownChildren = new Set(['colorSeries', 'colorNegative', 'colorAxis', 'colorMarkers', 'colorFirst', 'colorLast', 'colorHigh', 'colorLow', 'sparklines'])
      if (group.children.some(node => !(node.uri === X14 && knownChildren.has(node.local)) && !(node.uri === XM && node.local === 'f'))) throw Error('迷你图组包含未知对象结构。')
      const entries = group.children.filter(node => node.uri === X14 && node.local === 'sparklines')
      if (entries.length !== 1) throw Error('迷你图宿主结构不支持。')
      for (const entry of entries[0]!.children) {
        const refs = entry.children.filter(node => node.uri === XM && node.local === 'sqref')
        if (entry.uri !== X14 || entry.local !== 'sparkline' || refs.length !== 1 || refs[0]!.children.length || entry.children.some(node => node.uri !== XM || !['f', 'sqref'].includes(node.local))) throw Error('迷你图宿主结构不支持。')
        const host = refs[0]!.text.trim().replaceAll('$', '')
        if (!/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(host)) throw Error('迷你图已有宿主结构不支持。')
        validCell(host)
        if (seen.has(host)) throw Error(`迷你图宿主重复：${host}`)
      }
    }
  }
  // 固定源 buildGroupXml 的类型、颜色与默认负色协议；局部声明避免污染旧前缀。
  const additions = parsed.groups.map(group => `<x14:sparklineGroup xmlns:x14="${X14}" xmlns:xm="${XM}" displayEmptyCellsAs="gap"${group.type === 'line' ? '' : ` type="${group.type}"`}>` +
    `<x14:colorSeries rgb="FF${(group.color ?? '#376092').slice(1).toUpperCase()}"/><x14:colorNegative rgb="FFD00000"/><x14:sparklines>` +
    group.cells.map(entry => `<x14:sparkline><xm:f>${escapeXmlText(entry.sourceRef)}</xm:f><xm:sqref>${entry.cell}</xm:sqref></x14:sparkline>`).join('') + '</x14:sparklines></x14:sparklineGroup>').join('')
  const wrapped = `<x14:sparklineGroups xmlns:x14="${X14}">${additions}</x14:sparklineGroups>`
  const extension = `<ext xmlns="${MAIN}" uri="${URI}">${wrapped}</ext>`
  const next = container ? insert(xml, container, additions) : lists[0] ? insert(xml, lists[0], extension) : insert(xml, root, `<extLst xmlns="${MAIN}">${extension}</extLst>`)
  // 解析最终产物，确保所有 namespace / span 组合在出包前仍合法。
  scan(next)
  return (await assemblePackage(bytes, { replaced: new Map([[path, next]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}

/** Remove selected hosts while preserving the remaining x14 XML verbatim. */
export async function removeSheetSparklines(bytes: Uint8Array, sheetName: string, targets: readonly string[]): Promise<Uint8Array> {
  const parsed = removeSheetSparklinesOperationSchema.parse({ kind: 'removeSheetSparklines', sheetName, targets })
  const wanted = new Set(parsed.targets.map(target => target.toUpperCase()))
  if (wanted.size !== parsed.targets.length) throw Error('迷你图删除目标重复。')
  const { path, xml } = await worksheet(bytes, sheetName), nodes = scan(xml), root = nodes[0]
  if (!root || root.local !== 'worksheet' || root.uri !== MAIN) throw Error('迷你图不支持此工作表命名空间结构。')
  const entries = nodes.filter(node => node.uri === X14 && node.local === 'sparkline')
  const removals: Element[] = []
  const found = new Set<string>()
  for (const entry of entries) {
    const ref = entry.children.find(node => node.uri === XM && node.local === 'sqref')
    if (!ref || ref.children.length || entry.children.some(node => node.uri !== XM || !['f', 'sqref'].includes(node.local))) continue
    const host = ref.text.trim().replaceAll('$', '').toUpperCase()
    if (wanted.has(host)) { removals.push(entry); found.add(host) }
  }
  if (found.size !== wanted.size) throw Error(`找不到迷你图宿主：${[...wanted].filter(target => !found.has(target)).join(', ')}`)
  let next = xml
  for (const node of removals.sort((a, b) => b.start - a.start)) next = next.slice(0, node.start) + next.slice(node.end)
  const emptyGroups = scan(next).filter(node => node.uri === X14 && node.local === 'sparklineGroup' && !node.children.some(child => child.uri === X14 && child.local === 'sparklines' && child.children.some(entry => entry.uri === X14 && entry.local === 'sparkline')))
  for (const node of emptyGroups.sort((a, b) => b.start - a.start)) next = next.slice(0, node.start) + next.slice(node.end)
  const afterGroups = scan(next)
  const emptyContainers = afterGroups.filter(node => node.uri === X14 && node.local === 'sparklineGroups' && !node.children.some(child => child.uri === X14 && child.local === 'sparklineGroup'))
  for (const node of emptyContainers.sort((a, b) => b.start - a.start)) next = next.slice(0, node.start) + next.slice(node.end)
  const emptyExtensions = scan(next).filter(node => node.uri === MAIN && node.local === 'ext' && node.extensionUri?.toUpperCase() === URI.toUpperCase() && !node.children.length)
  for (const node of emptyExtensions.sort((a, b) => b.start - a.start)) next = next.slice(0, node.start) + next.slice(node.end)
  const emptyLists = scan(next).filter(node => node.uri === MAIN && node.local === 'extLst' && node.parent === root && !node.children.length)
  for (const node of emptyLists.sort((a, b) => b.start - a.start)) next = next.slice(0, node.start) + next.slice(node.end)
  scan(next)
  return (await assemblePackage(bytes, { replaced: new Map([[path, next]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}

function setAttribute(tag: string, name: string, value: string | undefined): string {
  const pattern = new RegExp(`\\s${name}=(['\"])[^'\"]*\\1`)
  if (pattern.test(tag)) return value === undefined ? tag.replace(pattern, '') : tag.replace(pattern, ` ${name}="${value}"`)
  return value === undefined ? tag : tag.replace(/\s*(\/?>)$/, ` ${name}="${value}"$1`)
}

export async function editSheetSparklineGroup(bytes: Uint8Array, sheetName: string, target: string, updates: {
  type?: 'line' | 'column' | 'stacked' | undefined; color?: string | undefined; negativeColor?: string | undefined; markers?: boolean | undefined; showAxis?: boolean | undefined
}): Promise<Uint8Array> {
  const parsed = editSheetSparklineGroupOperationSchema.parse({ kind: 'editSheetSparklineGroup', sheetName, target, ...updates })
  validCell(parsed.target)
  const { path, xml } = await worksheet(bytes, sheetName), nodes = scan(xml), entries = nodes.filter(node => node.uri === X14 && node.local === 'sparkline')
  const matches = entries.filter(entry => {
    const ref = entry.children.find(node => node.uri === XM && node.local === 'sqref')
    return ref && !ref.children.length && ref.text.trim().replaceAll('$', '').toUpperCase() === parsed.target
  })
  if (matches.length !== 1) throw Error(matches.length ? `迷你图宿主重复：${parsed.target}` : `找不到迷你图宿主：${parsed.target}`)
  const group = matches[0]!.parent?.parent
  if (!group || group.uri !== X14 || group.local !== 'sparklineGroup') throw Error('迷你图宿主组结构不支持。')
  const knownChildren = new Set(['colorSeries', 'colorNegative', 'colorAxis', 'colorMarkers', 'colorFirst', 'colorLast', 'colorHigh', 'colorLow', 'sparklines'])
  if (group.children.some(node => !(node.uri === X14 && knownChildren.has(node.local)) && !(node.uri === XM && node.local === 'f'))) throw Error('迷你图组包含未知对象结构。')
  const groupTag = xml.slice(group.start, group.openEnd)
  let nextGroupTag = groupTag
  if (parsed.type !== undefined) nextGroupTag = setAttribute(nextGroupTag, 'type', parsed.type)
  if (parsed.markers !== undefined) nextGroupTag = setAttribute(nextGroupTag, 'markers', parsed.markers ? '1' : undefined)
  if (parsed.showAxis !== undefined) nextGroupTag = setAttribute(nextGroupTag, 'displayAxis', parsed.showAxis ? '1' : undefined)
  const edits: { start: number; end: number; text: string }[] = []
  if (nextGroupTag !== groupTag) edits.push({ start: group.start, end: group.openEnd, text: nextGroupTag })
  const colorUpdates = [['colorSeries', parsed.color], ['colorNegative', parsed.negativeColor]] as const
  for (const [local, color] of colorUpdates) {
    if (color === undefined) continue
    const node = group.children.find(child => child.uri === X14 && child.local === local)
    const rgb = `FF${color.slice(1).toUpperCase()}`
    if (node) {
      const tag = xml.slice(node.start, node.openEnd), updated = setAttribute(tag, 'rgb', rgb)
      if (tag !== updated) edits.push({ start: node.start, end: node.openEnd, text: updated })
    } else {
      const list = group.children.find(child => child.uri === X14 && child.local === 'sparklines')
      if (!list) throw Error('迷你图宿主组结构不支持。')
      const prefix = group.name.includes(':') ? `${group.name.split(':')[0]}:` : ''
      edits.push({ start: list.start, end: list.start, text: `<${prefix}${local} rgb="${rgb}"/>` })
    }
  }
  let next = xml
  for (const edit of edits.sort((a, b) => b.start - a.start)) next = next.slice(0, edit.start) + edit.text + next.slice(edit.end)
  scan(next)
  return (await assemblePackage(bytes, { replaced: new Map([[path, next]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}

/** 现有 worksheet 改名器仅识别 xm:f；这里按 namespace 补齐原生别名前缀。 */
export async function renameSparklineSheetReferences(bytes: Uint8Array, renames: readonly { sheetName: string; newName: string }[]): Promise<Uint8Array> {
  if (!renames.length) return bytes
  const source = await createBufferEntrySource(bytes), replaced = new Map<string, string>()
  for (const sheet of parseSheetElements(await source.readText('xl/workbook.xml'))) {
    if (!sheet.relationshipId) continue
    const path = await resolveWorksheetPath(source, sheet.relationshipId)
    const xml = await source.readText(path)
    const changes = scan(xml).filter(node => node.uri === XM && node.local === 'f' && node.name !== 'xm:f' && node.parent?.uri === X14 && node.parent.local === 'sparkline')
    let next = xml
    for (const node of changes.reverse()) {
      if (node.empty || node.children.length) throw Error('迷你图来源公式结构不支持改名。')
      const value = renames.reduce((formula, rename) => renameSheetInFormula(formula, rename.sheetName, rename.newName), node.text)
      if (value !== node.text) next = next.slice(0, node.openEnd) + escapeXmlText(value) + next.slice(node.closeStart)
    }
    if (next !== xml) replaced.set(path, next)
  }
  if (!replaced.size) return bytes
  return (await assemblePackage(bytes, { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [...replaced.keys()] })).buffer
}
