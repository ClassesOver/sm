import { SaxesParser } from 'saxes'
import { readTableSource } from './table-source'
import type { EntrySource } from './zip'
import { decodeXmlText, readXmlAttribute } from './xml'

const packageNamespaces = new Set(['http://schemas.openxmlformats.org/package/2006/relationships', 'http://purl.oclc.org/ooxml/package/relationships'])
const contentNamespaces = new Set(['http://schemas.openxmlformats.org/package/2006/content-types', 'http://purl.oclc.org/ooxml/package/content-types'])
const officeType = /^(?:http:\/\/schemas\.openxmlformats\.org\/officeDocument\/2006\/relationships\/|http:\/\/purl\.oclc\.org\/ooxml\/officeDocument\/relationships\/)([^/]+)$/
const ownedKinds = new Set(['drawing', 'vmlDrawing', 'comments', 'threadedComment', 'ctrlProp', 'table', 'image'])
const ignoredKinds = new Set(['hyperlink', 'printerSettings'])
const relsPath = (part: string) => part ? part.replace(/([^/]+)$/, '_rels/$1.rels') : '_rels/.rels'
const ownerPath = (rels: string) => rels.replace(/(^|\/)_rels\/([^/]*)\.rels$/, '$1$2')
interface Relationship { id: string; type: string; target: string; external: boolean }

export function relationships(xml: string, path: string): Relationship[] {
  const parser = new SaxesParser({ xmlns: true }), result: Relationship[] = [], ids = new Set<string>()
  let depth = 0
  parser.on('doctype', () => { throw new Error(`关系来源 ${path} 不支持DOCTYPE`) })
  parser.on('opentag', tag => {
    depth++
    if (!packageNamespaces.has(tag.uri) || (depth === 1 ? tag.local !== 'Relationships' : depth !== 2 || tag.local !== 'Relationship')) throw new Error(`关系来源 ${path} 的命名空间或结构无效`)
    if (depth === 1) return
    const attr = (name: string) => Object.values(tag.attributes).find(value => !value.uri && value.local === name)?.value
    const id = attr('Id'), type = attr('Type'), target = attr('Target'), mode = attr('TargetMode')
    if (!id || ids.has(id) || !type || !target || mode !== undefined && mode !== 'Internal' && mode !== 'External') throw new Error(`关系来源 ${path} 的身份、Target或TargetMode无效`)
    ids.add(id);result.push({ id, type, target, external: mode === 'External' })
  })
  parser.on('closetag', () => { depth-- })
  parser.write(xml).close()
  return result
}

function resolveTarget(owner: string, target: string): string {
  let decoded: string
  try { decoded = decodeURIComponent(target.split('#', 1)[0]!.trim()) } catch { throw new Error('级联删除关系Target编码无效') }
  if (!decoded || /[\x00-\x1f\\?#]/.test(decoded) || decoded.startsWith('//') || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(decoded)) throw new Error('级联删除关系Target路径不安全')
  const segments = decoded.startsWith('/') ? [] : owner.split('/').slice(0, -1)
  for (const part of decoded.split('/')) {
    if (part === '..') { if (!segments.length) throw new Error('级联删除关系Target越出包根');segments.pop() }
    else if (part && part !== '.') segments.push(part)
  }
  const path = segments.join('/')
  if (!path || path === '[Content_Types].xml' || path.endsWith('.rels')) throw new Error('级联删除关系Target不是有效内容part')
  return path
}

/** 先求owned内部闭包，再由全部存续incoming关系保留共享目标及其子树；不改包。 */
export async function planSheetRemovalParts(source: EntrySource, removedSheetPaths: readonly string[]): Promise<{ removedParts: ReadonlySet<string> }> {
  const removedSheets = new Set(removedSheetPaths), candidates = new Set<string>(), paths = await source.paths()
  const cache = new Map<string, Relationship[]>()
  const readRels = async (path: string) => {
    if (!cache.has(path)) cache.set(path, relationships(await source.readText(path), path))
    return cache.get(path)!
  }
  const queue: string[] = []
  for (const sheet of removedSheets) {
    const path = relsPath(sheet)
    if (!await source.has(path)) continue
    for (const entry of await readRels(path)) {
      if (entry.external) continue
      const kind = officeType.exec(entry.type)?.[1]
      if (kind && ignoredKinds.has(kind)) continue
      if (!kind || !ownedKinds.has(kind)) throw new Error(`工作表关系 ${entry.type} 尚不支持安全级联删除`)
      queue.push(resolveTarget(sheet, entry.target))
    }
  }
  while (queue.length) {
    const part = queue.pop()!
    if (candidates.has(part)) continue
    if (!await source.has(part)) throw new Error(`级联删除来源缺少 ${part}`)
    candidates.add(part)
    const path = relsPath(part)
    if (!await source.has(path)) continue
    candidates.add(path)
    for (const entry of await readRels(path)) if (!entry.external) queue.push(resolveTarget(part, entry.target))
  }
  const dyingRels = new Set([...removedSheets].map(relsPath).concat([...candidates].filter(path => path.endsWith('.rels')))), keep: string[] = []
  for (const path of paths) {
    if (!path.endsWith('.rels') || dyingRels.has(path)) continue
    const owner = ownerPath(path)
    if (removedSheets.has(owner)) continue
    for (const entry of await readRels(path)) {
      if (entry.external) continue
      const target = resolveTarget(owner, entry.target)
      if (candidates.has(target)) keep.push(target)
    }
  }
  while (keep.length) {
    const part = keep.pop()!
    if (!candidates.delete(part)) continue
    const path = relsPath(part)
    if (candidates.delete(path)) for (const entry of await readRels(path)) if (!entry.external) keep.push(resolveTarget(part, entry.target))
  }
  // worksheet根及其关系由调用方统一删除，不能因子树循环重复授权。
  for (const sheet of removedSheets) { candidates.delete(sheet);candidates.delete(relsPath(sheet)) }
  return { removedParts: candidates }
}

/** 只移除精确part的Override，Default及其余内容保持原字节；支持sheet和satellite。 */
export function removePartOverrides(xml: string, removedParts: ReadonlySet<string>): string {
  const parser = new SaxesParser({ xmlns: true }), spans: { start: number; end: number }[] = []
  let depth = 0, start = 0, removing = false
  parser.on('doctype', () => { throw new Error('ContentTypes不支持DOCTYPE') })
  parser.on('opentag', tag => {
    depth++
    if (!contentNamespaces.has(tag.uri) || (depth === 1 ? tag.local !== 'Types' : depth !== 2 || !['Default', 'Override'].includes(tag.local))) throw new Error('ContentTypes命名空间或结构无效')
    if (depth !== 2 || tag.local !== 'Override') return
    const part = Object.values(tag.attributes).find(value => !value.uri && value.local === 'PartName')?.value
    if (!part) throw new Error('ContentTypes Override缺少PartName')
    start = xml.lastIndexOf('<', parser.position - 1);removing = part.startsWith('/') && removedParts.has(part.slice(1))
  })
  parser.on('closetag', () => { if (depth === 2 && removing) { spans.push({ start, end: parser.position });removing = false }depth-- })
  parser.write(xml).close()
  for (const span of spans.reverse()) xml = xml.slice(0, span.start) + xml.slice(span.end)
  return xml
}


/** 与固定源一致按大小写不敏感的TableName[ token保护存续公式/名称。 */
export async function assertRemovedTableDependencies(
  source: EntrySource,
  removedParts: ReadonlySet<string>,
  survivingWorksheetPaths: readonly string[],
  workbookXml: string,
  removedLocalIds: ReadonlySet<number>,
): Promise<void> {
  // 真实table关系识别非标准路径；最终removedParts仍决定是否实际删除。
  const tablePaths = new Set<string>()
  for (const path of await source.paths()) {
    if (!path.endsWith('.rels')) continue
    for (const rel of relationships(await source.readText(path), path)) {
      if (!rel.external && officeType.exec(rel.type)?.[1] === 'table') tablePaths.add(resolveTarget(ownerPath(path), rel.target))
    }
  }
  for (const path of removedParts) {
    if (!tablePaths.has(path) && !/^xl\/tables\/[^/]+\.xml$/.test(path)) continue
    const identity = readTableSource(await source.readText(path), path)
    for (const name of new Set([identity.name, identity.displayName])) {
      const needle = `${name}[`.toLowerCase()
      for (const worksheet of survivingWorksheetPaths) {
        if ((await source.readText(worksheet)).toLowerCase().includes(needle)) throw new Error(`存续工作表仍引用表格 "${name}"，已拒绝删除。`)
      }
      for (const match of workbookXml.matchAll(/<definedName\b([^>]*)>([\s\S]*?)<\/definedName>/g)) {
        const localId = readXmlAttribute(match[1] ?? '', 'localSheetId')
        if (localId !== undefined && removedLocalIds.has(Number(localId))) continue
        if (decodeXmlText(match[2] ?? '').toLowerCase().includes(needle)) throw new Error(`存续定义名称仍引用表格 "${name}"，已拒绝删除。`)
      }
    }
  }
}
