import type { EntrySource } from './zip'
import { readPivotState, resolvePivotTarget } from './pivot-add'
import { isPivotCacheDefinitionPath, pivotCacheReadsFromTable, renameTableInPivotCacheSource } from './pivot-cache-source'
import { decodeXmlText, escapeXmlAttribute, extractElements, readXmlAttribute } from './xml'

/** 不支持迁移的结构变化仍拒绝丢失缓存字段，允许撤回未进入缓存的新列。 */
export async function assertPivotTableSourceColumns(pkg: EntrySource, aliases: readonly string[], removedNames: readonly string[]): Promise<void> {
  if (await pivotTableSourceUsesColumns(pkg, aliases, removedNames)) throw new Error('透视缓存仍引用此表格字段，不能移除或更名；请先调整或删除依赖透视表')
}

export async function pivotTableSourceUsesColumns(pkg: EntrySource, aliases: readonly string[], removedNames: readonly string[]): Promise<boolean> {
  if (!removedNames.length) return false
  const paths = await pkg.paths(), names = new Set(aliases.map(name => name.toLowerCase()))
  for (const path of paths.filter(isPivotCacheDefinitionPath)) {
    const xml = await pkg.readText(path)
    if (aliases.some(name => pivotCacheReadsFromTable(xml, name, removedNames))) return true
  }
  for (const path of paths.filter(path => /^xl\/pivotTables\/[^/]+\.xml$/.test(path))) {
    const state = readPivotState(await pkg.readText(path))
    if (state?.sourceTableName && names.has(state.sourceTableName.toLowerCase()) && state.fieldNames.some(name => removedNames.some(removed => removed.toLowerCase() === name.toLowerCase()))) {
      return true
    }
  }
  return false
}

/** 仅迁移来源身份，不重算缓存、输出、筛选或控件。ZIP overlay 保证整批失败不写出。 */
export async function updatePivotTableSourceNames(
  pkg: EntrySource & { write(path: string, xml: string): void },
  aliases: readonly string[], sheetName: string, newName: string | undefined, touched: Set<string>,
  dependencyReason = '表格仍被透视表作为动态来源引用，不能转换为普通区域',
): Promise<void> {
  const paths = await pkg.paths(), names = new Set(aliases.map(name => name.toLowerCase())), caches = new Set<string>()
  for (const path of paths.filter(isPivotCacheDefinitionPath)) {
    let xml = await pkg.readText(path)
    const matching = aliases.filter(name => pivotCacheReadsFromTable(xml, name))
    if (!matching.length) continue
    if (newName === undefined) throw new Error(dependencyReason)
    for (const name of matching) xml = renameTableInPivotCacheSource(xml, name, newName, sheetName)
    pkg.write(path, xml); touched.add(path); caches.add(path)
  }
  for (const path of paths.filter(path => /^xl\/pivotTables\/[^/]+\.xml$/.test(path))) {
    const xml = await pkg.readText(path), state = readPivotState(xml)
    if (!state) continue
    const referenced = state.sourceTableName !== undefined && names.has(state.sourceTableName.toLowerCase())
    const relsPath = path.replace('/pivotTables/', '/pivotTables/_rels/') + '.rels'
    const rels = await pkg.has(relsPath) ? extractElements(await pkg.readText(relsPath), 'Relationship') : []
    const cacheRel = rels.find(rel => (readXmlAttribute(rel, 'Type') ?? '').endsWith('/pivotCacheDefinition'))
    const target = cacheRel && readXmlAttribute(cacheRel, 'Target')
    const linked = target !== undefined && caches.has(resolvePivotTarget(path, decodeXmlText(target)))
    if (!referenced && !linked) continue
    if (newName === undefined) throw new Error(dependencyReason)
    if (!referenced || !linked || state.sourceSheetName.toLowerCase() !== sheetName.toLowerCase() ||
        ![undefined, 'Internal'].includes(cacheRel && readXmlAttribute(cacheRel, 'TargetMode'))) {
      throw new Error('透视表动态来源与缓存归属不一致，不能安全迁移表名')
    }
    const tag = xml.match(/<aio:aioPivotState\b[^>]*\/>/)![0], value = readXmlAttribute(tag, 'v')!
    // 保留完整原始 JSON 的其他属性，避免重建透视状态改变派生隐藏成员。
    const metadata = JSON.parse(decodeXmlText(value)); metadata.sourceTableName = newName
    const updated = tag.replace(/(\sv=")[^"]*(")/, (_match, prefix, suffix) => prefix + escapeXmlAttribute(JSON.stringify(metadata)) + suffix)
    pkg.write(path, xml.replace(tag, () => updated)); touched.add(path)
  }
}
