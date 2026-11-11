import { createHash } from 'node:crypto'
import type JSZip from 'jszip'
import { XMLValidator } from 'fast-xml-parser'
import { parseRels, resolveRelationshipTargetPath } from '../packages/docx-engine/src/parse-package.ts'
import { attrsOf, childrenOf, nameOf, xmlParser, type XNode } from '../packages/docx-engine/src/xml-utils.ts'

const sha = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex')
export const hfRelsPath = (path: string) => path.replace(/([^/]+)$/, '_rels/$1.rels')
export interface HfRelationshipGraph { sha256: string | null; reason?: string }
const relationshipNamespace = 'http://schemas.openxmlformats.org/package/2006/relationships'
const officeRelationshipNamespace = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const supportedTypes = new Set([
  ...['image', 'hyperlink', 'chart', 'chartUserShapes', 'package', 'oleObject'].map(type => `${officeRelationshipNamespace}/${type}`),
  'http://schemas.microsoft.com/office/2011/relationships/chartStyle',
  'http://schemas.microsoft.com/office/2011/relationships/chartColorStyle',
])

/** 新HF与原HF同目录：复制companion rels后可共享原有不可变依赖，无需重写rId或图片字节。
 *  复制前递归核验整个可达图。未知关系、循环或缺失身份只影响对应slot，inspect保留原产物。 */
export function createHfRelationshipInspector(zip: JSZip) {
  const memo = new Map<string, Promise<HfRelationshipGraph>>()
  let typesPromise: Promise<{ defaults: Map<string, string>; overrides: Map<string, string> }> | undefined
  const contentTypes = () => typesPromise ??= (async () => {
    const xml = await zip.file('[Content_Types].xml')?.async('string')
    if (!xml || XMLValidator.validate(xml) !== true) throw new Error('包内容类型无法核验')
    const root = (xmlParser.parse(xml) as XNode[]).find(node => nameOf(node) === 'Types')
    if (!root || attrsOf(root)['xmlns'] !== 'http://schemas.openxmlformats.org/package/2006/content-types') throw new Error('包内容类型命名空间无法核验')
    const defaults = new Map<string, string>(), overrides = new Map<string, string>()
    for (const node of childrenOf(root)) {
      const name = nameOf(node), attrs = attrsOf(node)
      if (name === '#text') continue
      if (!attrs.ContentType) throw new Error('包内容类型声明不完整')
      if (name === 'Default') {
        const extension = attrs.Extension?.toLowerCase()
        if (!extension || defaults.has(extension)) throw new Error('包扩展名内容类型重复或缺失')
        defaults.set(extension, attrs.ContentType)
      } else if (name === 'Override') {
        const path = resolveRelationshipTargetPath('', attrs.PartName ?? '')
        if (!path || overrides.has(path)) throw new Error('包部件内容类型重复或路径无效')
        overrides.set(path, attrs.ContentType)
      } else throw new Error('包内容类型包含未知声明')
    }
    return { defaults, overrides }
  })()
  const inspect = async (rootPath: string): Promise<HfRelationshipGraph> => {
    try {
      const types = await contentTypes(), identities: Array<[string, string, string]> = []
      const visited = new Set<string>(), active = new Set<string>()
      const visit = async (path: string): Promise<void> => {
        if (active.has(path)) throw new Error('页眉页脚依赖关系包含循环，当前无法安全复制')
        if (visited.has(path)) return
        active.add(path)
        const file = zip.file(path), contentType = types.overrides.get(path) ?? types.defaults.get(path.split('.').at(-1)?.toLowerCase() ?? '')
        if (!file || !contentType) throw new Error('页眉页脚依赖部件缺失或内容类型无法核验')
        const bytes = await file.async('uint8array')
        identities.push([path, sha(bytes), contentType])
        const relPath = hfRelsPath(path), relFile = zip.file(relPath)
        const relations = await parseRels(zip, relPath)
        if (relFile) {
          const xml = await relFile.async('string')
          if (XMLValidator.validate(xml) !== true) throw new Error('页眉页脚关系XML无效')
          const root = (xmlParser.parse(xml) as XNode[]).find(node => nameOf(node) === 'Relationships')
          if (!root || attrsOf(root).xmlns !== relationshipNamespace) throw new Error('页眉页脚关系命名空间无法核验')
          const nodes = childrenOf(root).filter(node => nameOf(node) !== '#text')
          if (nodes.length !== relations.size || nodes.some(node => nameOf(node) !== 'Relationship'
            || Object.keys(attrsOf(node)).some(key => !['Id', 'Type', 'Target', 'TargetMode'].includes(key)))) throw new Error('页眉页脚关系包含重复或未知标记')
          if ((types.overrides.get(relPath) ?? types.defaults.get('rels')) !== 'application/vnd.openxmlformats-package.relationships+xml') throw new Error('页眉页脚关系内容类型无法核验')
          identities.push([relPath, sha(xml), 'application/vnd.openxmlformats-package.relationships+xml'])
        }
        if (contentType.endsWith('xml') || contentType.endsWith('+xml')) {
          const xml = await file.async('string')
          if (XMLValidator.validate(xml) !== true) throw new Error('页眉页脚依赖XML无效')
          const walk = (nodes: XNode[], inherited = new Map([['xml', 'http://www.w3.org/XML/1998/namespace']])) => {
            for (const node of nodes) {
              const attributes = attrsOf(node), namespaces = new Map(inherited)
              for (const [key, value] of Object.entries(attributes)) if (key.startsWith('xmlns:')) namespaces.set(key.slice(6), value)
              const element = nameOf(node) ?? '', elementPrefix = element.includes(':') ? element.split(':')[0]! : undefined
              if (elementPrefix && !namespaces.has(elementPrefix)) throw new Error('页眉页脚XML包含未声明的命名空间')
              for (const [key, value] of Object.entries(attributes)) {
                const [prefix, local] = key.split(':')
                if (!local || prefix === 'xmlns') continue
                if (!namespaces.has(prefix!)) throw new Error('页眉页脚XML属性包含未声明的命名空间')
                if (namespaces.get(prefix!) === officeRelationshipNamespace && ['id', 'embed', 'link'].includes(local) && !relations.has(value)) throw new Error('页眉页脚XML引用了缺失的关系身份')
              }
              walk(childrenOf(node), namespaces)
            }
          }
          walk(xmlParser.parse(xml) as XNode[])
        }
        for (const relation of relations.values()) {
          if (!relation.target || !supportedTypes.has(relation.type)) throw new Error('页眉页脚包含当前未支持核验的关系类型')
          if (relation.targetMode === 'External') continue
          if (relation.targetMode !== undefined && relation.targetMode !== 'Internal') throw new Error('页眉页脚关系TargetMode无法核验')
          const target = resolveRelationshipTargetPath(path, relation.target)
          if (!target) throw new Error('页眉页脚内部关系路径无法核验')
          await visit(target)
        }
        active.delete(path); visited.add(path)
      }
      await visit(rootPath)
      identities.sort((a, b) => a[0].localeCompare(b[0]))
      return { sha256: sha(JSON.stringify(identities)) }
    } catch (error) { return { sha256: null, reason: error instanceof Error ? error.message : '页眉页脚依赖身份无法核验' } }
  }
  return (path: string | null): Promise<HfRelationshipGraph> => {
    if (!path) return Promise.resolve({ sha256: sha('[]') })
    let result = memo.get(path)
    if (!result) { result = inspect(path); memo.set(path, result) }
    return result
  }
}
