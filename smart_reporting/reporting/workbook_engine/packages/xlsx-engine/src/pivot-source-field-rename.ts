import { SaxesParser } from 'saxes'
import { createBufferEntrySource, type EntrySource } from './zip'
import { readPivotState, resolvePivotTarget, type PivotAddition } from './pivot-add'
import { formatPivotFormula, parsePivotFormula, type PivotFormulaAst } from './pivot-formula'
import { isPivotCacheDefinitionPath, pivotCacheReadsFromTable, renameTableInPivotCacheSource } from './pivot-cache-source'
import { decodeXmlText, escapeXmlAttribute, extractElements, readXmlAttribute } from './xml'
import { readPivotControls, planPivotControlFieldRenames, pivotControlPartPath } from './pivot-controls'

const MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition'
const fail = (reason: string): never => { throw new Error('透视字段更名：' + reason) }
const attr = (tag: string, name: string) => decodeXmlText(readXmlAttribute(tag, name) ?? '')
const relsPath = (path: string) => path.replace(/([^/]+)$/, '_rels/$1.rels')

export interface PivotFieldRenameSupport { fieldNames: readonly string[]; calculatedNames: readonly string[] }
export interface PivotFieldRenameRequest {
  aliases: readonly string[]; sheetName: string; startColumn: number
  beforeNames: readonly string[]; afterNames: readonly string[]
}

export function pivotFieldRenameReason(support: PivotFieldRenameSupport, afterNames: readonly string[]): string | undefined {
  if (afterNames.length !== support.fieldNames.length) return '透视字段更名暂不支持同时增删列'
  const names = afterNames.map(name => name.trim().toLowerCase())
  if (afterNames.some(name => !name.trim() || name.length > 255 || /[\u0000-\u001f\ufffe\uffff]/.test(name)) || new Set(names).size !== names.length) return '透视字段名称为空、重复或含不支持的控制字符'
  if (support.calculatedNames.some(name => names.includes(name.trim().toLowerCase()))) return '来源字段名称与透视计算字段冲突'
}

function renamedFormula(formula: string, before: readonly string[], after: readonly string[]): string {
  const rename = (ast: PivotFormulaAst): PivotFormulaAst => {
    if (ast.t === 'field') return { ...ast, name: after[before.indexOf(ast.name)]! }
    if (ast.t === 'neg') return { ...ast, operand: rename(ast.operand) }
    if (ast.t === 'bin') return { ...ast, left: rename(ast.left), right: rename(ast.right) }
    return ast
  }
  const ast = parsePivotFormula(formula, before), updated = formatPivotFormula(rename(ast))
  return updated === formatPivotFormula(ast) ? formula : updated
}

function replaceAttributes(opening: string, values: Record<string, string>): string {
  return opening.replace(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g, (match, name, quote) => {
    if (!Object.hasOwn(values, name)) return match
    return match.slice(0, match.indexOf(quote) + 1) + escapeXmlAttribute(values[name]!) + quote
  })
}

function cacheFields(xml: string, timeline = false) {
  const fields: { opening: string; start: number; end: number; name: string; formula?: string }[] = []
  const parser = new SaxesParser({ xmlns: true }), stack: { local: string; uri: string }[] = []
  let start = 0, containers = 0
  parser.on('doctype', () => fail('不支持缓存DOCTYPE'))
  parser.on('opentagstart', () => { start = xml.lastIndexOf('<', parser.position - 1) })
  parser.on('opentag', tag => {
    const parent = stack.at(-1)
    if (!stack.length && (tag.local !== 'pivotCacheDefinition' || tag.uri !== MAIN)) fail('缓存根结构不支持')
    if (tag.local === 'cacheFields' && tag.uri === MAIN && stack.length === 1) containers++
    if (tag.local === 'cacheField' && tag.uri === MAIN && parent?.local === 'cacheFields' && parent.uri === MAIN && stack.length === 2) {
      const attrs = Object.values(tag.attributes), name = attrs.find(attribute => !attribute.uri && attribute.local === 'name')?.value
      if (name === undefined) fail('缓存字段缺少名称')
      const formula = attrs.find(attribute => !attribute.uri && attribute.local === 'formula')?.value
      fields.push({ opening: xml.slice(start, parser.position), start, end: parser.position, name: name!, ...(formula !== undefined ? { formula } : {}) })
    }
    if (tag.uri === MAIN && tag.local === 'extLst' && !(timeline && stack.length === 1 && xml.startsWith('<extLst><ext uri="{5DA0FC9A-693D-419c-AD59-312A39285967}"><x15:timelinePivotCacheDefinition xmlns:x15="http://schemas.microsoft.com/office/spreadsheetml/2010/11/main" timelineData="1"/></ext></extLst>', start))) fail('缓存包含未支持的扩展或计算项')
    if (tag.uri === MAIN && tag.local === 'calculatedItems') fail('缓存包含未支持的扩展或计算项')
    stack.push({ local: tag.local, uri: tag.uri })
  })
  parser.on('closetag', () => { stack.pop() })
  parser.write(xml).close()
  if (containers !== 1) fail('缓存字段容器不唯一')
  return fields
}

/** 完整规划后由调用方一次写入 overlay；此函数也供前端载入时预检能力。 */
export async function planPivotTableFieldRename(input: EntrySource | Uint8Array, request: PivotFieldRenameRequest): Promise<{ replacements: Map<string, string>; support: PivotFieldRenameSupport }> {
  const source = input instanceof Uint8Array ? await createBufferEntrySource(input) : input
  const paths = await source.paths(), caches = new Map<string, string>(), owners = new Map<string, { path: string; xml: string; state: PivotAddition }[]>()
  const names = new Set(request.aliases.map(name => name.toLowerCase()))
  for (const path of paths.filter(isPivotCacheDefinitionPath)) {
    const xml = await source.readText(path), alias = request.aliases.find(name => pivotCacheReadsFromTable(xml, name))
    if (!alias) continue
    renameTableInPivotCacheSource(xml, alias, alias, request.sheetName) // 验证内部来源及工作表，丢弃无变化的预览结果。
    caches.set(path, xml)
  }
  for (const path of paths.filter(path => /^xl\/pivotTables\/[^/]+\.xml$/.test(path))) {
    const xml = await source.readText(path), state = readPivotState(xml), relPath = relsPath(path)
    const relationships = await source.has(relPath) ? extractElements(await source.readText(relPath), 'Relationship').filter(tag => attr(tag, 'Type') === REL) : []
    const rel = relationships[0], cachePath = rel && resolvePivotTarget(path, attr(rel, 'Target'))
    const referenced = state?.sourceTableName && names.has(state.sourceTableName.toLowerCase())
    const linked = relationships.some(relationship => caches.has(resolvePivotTarget(path, attr(relationship, 'Target'))))
    if (!referenced && !linked) continue
    if (!state || !referenced || !cachePath || !caches.has(cachePath) || relationships.length !== 1 || ![undefined, 'Internal'].includes(readXmlAttribute(rel!, 'TargetMode')) || state.sourceSheetName.toLowerCase() !== request.sheetName.toLowerCase()) fail('来源或共享缓存缺少完整自有状态，不能安全迁移')
    if (state!.sourceArea.startColumn !== request.startColumn || JSON.stringify(state!.fieldNames) !== JSON.stringify(request.beforeNames)) fail('来源列结构已变化，请先刷新透视表再更名')
    const list = owners.get(cachePath!) ?? []; list.push({ path, xml, state: state! }); owners.set(cachePath!, list)
  }
  const nativePaths = caches.size ? paths.filter(path => pivotControlPartPath.test(path)) : []
  if (nativePaths.length && !(input instanceof Uint8Array)) fail('原生控件迁移需要完整工作簿快照')
  const controls = nativePaths.length ? await readPivotControls(input as Uint8Array) : []
  if (nativePaths.length !== controls.length * 2) fail('存在未知原生控件部件，不能安全迁移')
  const support = { fieldNames: [...request.beforeNames], calculatedNames: [...new Set([...owners.values()].flatMap(list => list.flatMap(owner => owner.state.values.filter(value => value.formula !== undefined).map(value => value.calcName!))))] }
  const reason = pivotFieldRenameReason(support, request.afterNames)
  if (reason) fail(reason)
  const replacements = new Map<string, string>()
  const workbookRels = extractElements(await source.readText('xl/_rels/workbook.xml.rels'), 'Relationship')
  const registered = extractElements(await source.readText('xl/workbook.xml'), 'pivotCache')
  for (const [cachePath, cacheXml] of caches) {
    const list = owners.get(cachePath)
    if (!list?.length) fail('缓存没有完整自有透视表归属')
    const timeline = controls.some(control => control.kind === 'timeline' && list!.some(owner => owner.path === control.tablePath))
    const fields = cacheFields(cacheXml, timeline)
    for (const owner of list!) {
      const cacheId = attr(owner.xml.match(/<pivotTableDefinition\b[^>]*>/)?.[0] ?? '', 'cacheId')
      const registrations = registered.filter(tag => attr(tag, 'cacheId') === cacheId)
      const relationships = workbookRels.filter(rel => attr(rel, 'Id') === attr(registrations[0] ?? '', 'r:id'))
      const rel = relationships[0]
      if (!/^\d+$/.test(cacheId) || registrations.length !== 1 || relationships.length !== 1 || !rel || attr(rel, 'Type') !== REL || ![undefined, 'Internal'].includes(readXmlAttribute(rel, 'TargetMode')) || resolvePivotTarget('xl/workbook.xml', attr(rel, 'Target')) !== cachePath) fail('工作簿缓存登记与透视关系不一致')
      const calc = owner.state.values.filter(value => value.formula !== undefined)
      const expectedNames = [...request.beforeNames, ...calc.map(value => value.calcName!)]
      if (JSON.stringify(fields.map(field => field.name)) !== JSON.stringify(expectedNames)) fail('缓存字段与自有状态不一致')
      for (let index = 0; index < fields.length; index++) {
        const expected = calc[index - request.beforeNames.length]?.formula, actual = fields[index]!.formula
        if (expected === undefined ? actual !== undefined : actual === undefined || formatPivotFormula(parsePivotFormula(actual, request.beforeNames)) !== formatPivotFormula(parsePivotFormula(expected, request.beforeNames))) fail('缓存计算公式与自有状态不一致')
      }
      const tag = owner.xml.match(/<aio:aioPivotState\b[^>]*\/>/)![0], metadata = JSON.parse(attr(tag, 'v'))
      metadata.fieldNames = [...request.afterNames]
      metadata.values = metadata.values.map((value: { formula?: string }) => value.formula === undefined ? value : { ...value, formula: renamedFormula(value.formula, request.beforeNames, request.afterNames) })
      const updated = owner.xml.replace(tag, () => tag.replace(/(\sv=")[^"]*(")/, (_match, prefix, suffix) => prefix + escapeXmlAttribute(JSON.stringify(metadata)) + suffix))
      readPivotState(updated) // 复用完整索引、计算字段冲突和公式校验。
      replacements.set(owner.path, updated)
    }
    let updated = cacheXml
    for (let index = fields.length - 1; index >= 0; index--) {
      const field = fields[index]!
      let opening = field.opening
      const values: Record<string, string> = {}
      if (index < request.beforeNames.length && request.beforeNames[index] !== request.afterNames[index]) values.name = request.afterNames[index]!
      if (field.formula !== undefined) {
        const formula = renamedFormula(field.formula, request.beforeNames, request.afterNames)
        if (formula !== field.formula) values.formula = formula
      }
      opening = replaceAttributes(opening, values)
      updated = updated.slice(0, field.start) + opening + updated.slice(field.end)
    }
    const result = cacheFields(updated, timeline)
    const expectedNames = [...request.afterNames, ...list![0]!.state.values.filter(value => value.formula !== undefined).map(value => value.calcName!)]
    if (JSON.stringify(result.map(field => field.name)) !== JSON.stringify(expectedNames)) fail('更名后的标准缓存字段校验失败')
    result.forEach((field, index) => {
      const original = fields[index]!.formula
      if (original === undefined ? field.formula !== undefined : field.formula === undefined || formatPivotFormula(parsePivotFormula(field.formula, request.afterNames)) !== formatPivotFormula(parsePivotFormula(renamedFormula(original, request.beforeNames, request.afterNames), request.afterNames))) fail('更名后的标准缓存计算公式校验失败')
    })
    replacements.set(cachePath, updated)
  }
  const renames = new Map([...owners.values()].flatMap(list => list.map(owner => [owner.path, new Map(request.beforeNames.map((name, index) => [name, request.afterNames[index]!]))] as const)))
  return { replacements: controls.length ? await planPivotControlFieldRenames(input as Uint8Array, replacements, renames) : replacements, support }
}
