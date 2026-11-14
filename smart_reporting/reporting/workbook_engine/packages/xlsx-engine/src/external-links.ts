import { SaxesParser } from 'saxes'
// 外链声明只读包内关系；绝不根据 Target 探测文件系统或网络。
import { z } from 'zod'
import { createBufferEntrySource, assemblePackage, assertOnlyTouchedEntriesChanged, type EntrySource } from './zip'
import { decodeXmlText, readXmlAttribute } from './xml'
import { relationships } from './sheet-removal-parts'
import { resolvePivotTarget } from './pivot-add'
import { planExternalLinkBreak, retargetExternalLinkRels } from './external-links-break'

export interface ExternalWorkbookLink {
 readonly index: number
 readonly rawTarget: string
 readonly source: string | null
 readonly sheetNames: readonly string[]
 readonly part: string
 readonly relsPart: string
}
function assertSpreadsheetPart(xml: string, root: string) {
 const namespaces = new Set(['http://schemas.openxmlformats.org/spreadsheetml/2006/main', 'http://purl.oclc.org/ooxml/spreadsheetml/main'])
 const parser = new SaxesParser({ xmlns: true }); let depth = 0
 parser.on('opentag', tag => { depth++; if (depth === 1 && (tag.local !== root || !namespaces.has(tag.uri)) || ['externalReference', 'externalBook', 'sheetName'].includes(tag.local) && !namespaces.has(tag.uri)) throw new Error('外链部件命名空间身份无效') })
 parser.on('closetag', () => { depth-- }); parser.write(xml).close()
}
const attr = (tag: string, name: string) => decodeXmlText(readXmlAttribute(tag, name) ?? '')
export async function readExternalLinks(source: EntrySource): Promise<ExternalWorkbookLink[]> {
 const book = await source.readText('xl/workbook.xml'), rels = relationships(await source.readText('xl/_rels/workbook.xml.rels'), 'xl/_rels/workbook.xml.rels')
 assertSpreadsheetPart(book, 'workbook')
 const result: ExternalWorkbookLink[] = []
 for (const [position, match] of [...book.matchAll(/<externalReference\b[^>]*>/g)].entries()) {
  const id = attr(match[0], 'r:id'), rel = rels.find(item => item.id === id)
  if (!rel || rel.external || !rel.type.endsWith('/externalLink')) throw new Error('外链关系身份无效')
  const part = resolvePivotTarget('xl/workbook.xml', rel.target)
  if (!part.startsWith('xl/externalLinks/') || !(await source.has(part))) throw new Error('外链部件来源无效')
  const link = await source.readText(part), relsPart = part.replace(/([^/]+)$/, '_rels/$1.rels')
  assertSpreadsheetPart(link, 'externalLink')
  const sourceRels = relationships(await source.readText(relsPart), relsPart), sourceId = attr(link.match(/<externalBook\b[^>]*>/)?.[0] ?? '', 'r:id')
  const path = sourceRels.find(item => item.id === sourceId && item.type.endsWith('/externalLinkPath') && item.external)
  if (!path) throw new Error('外链来源关系无效')
  if (result.some(item => item.part === part)) throw new Error('外链部件身份重复共享')
  result.push({ index: position + 1, rawTarget: path.target, source: /^(?:https?|ftp|data|javascript):/i.test(path.target) ? null : path.target,
   sheetNames: [...link.matchAll(/<sheetName\b[^>]*>/g)].map(item => attr(item[0], 'val')), part, relsPart })
 }
 return result
}

export const externalLinkOperationSchema = z.discriminatedUnion('kind', [
 z.object({ kind: z.literal('retargetExternalLink'), index: z.number().int().positive().max(64), expectedTarget: z.string().max(2048), target: z.string().min(1).max(2048).refine(value => [...value].every(char => char.charCodeAt(0) >= 32)) }).strict(),
 z.object({ kind: z.literal('breakExternalLink'), index: z.number().int().positive().max(64), expectedTarget: z.string().max(2048) }).strict(),
])
export async function applyExternalLinkOperation(bytes: Uint8Array, raw: unknown): Promise<Uint8Array> {
 const operation = externalLinkOperationSchema.parse(raw), source = await createBufferEntrySource(bytes)
 const link = (await readExternalLinks(source)).find(item => item.index === operation.index)
 if (!link || link.rawTarget !== operation.expectedTarget) throw new Error('外链来源已变化，请重新打开外部链接')
 const plan = operation.kind === 'breakExternalLink' ? await planExternalLinkBreak(source, [operation.index]) : {
  replaced: new Map([[link.relsPart, retargetExternalLinkRels(await source.readText(link.relsPart), operation.target)]]),
  added: new Map<string, string>(), addedBinary: new Map<string, Uint8Array>(), removedEntries: [], addedEntries: [], touchedEntries: [link.relsPart],
 }
 if (operation.kind === 'breakExternalLink') for (const path of plan.touchedEntries) {
  if (path.startsWith('xl/worksheets/') && /<sheetProtection(?:[ >])/.test(await source.readText(path))) throw new Error('外链公式所在工作表受保护，不能断开链接')
 }
 const mutation = await assemblePackage(bytes, plan)
 assertOnlyTouchedEntriesChanged(mutation)
 return mutation.buffer
}
