import { restoreCheckboxValidations } from './checkbox-validation'
/// Local browser-safe adapter for the upstream Univer wire model. A partial
/// projection must never authorize replacing the full file rule set.
import { parseRange, columnIndex } from './cell-address'
import { applyDvRules, type DvWireRule, type DvCellArea } from './data-validation'
import { decodeXmlText, readXmlAttribute } from './xml'

export interface SheetDataValidationModel {
  rules: DvWireRule[]
  readOnlyReason?: string
}

const TYPES = new Set(['none', 'whole', 'decimal', 'list', 'date', 'time', 'textLength', 'custom'])
const ERROR_STYLES: Record<string, number> = { information: 0, stop: 1, warning: 2 }
const ATTRIBUTES = new Set(['type', 'sqref', 'operator', 'allowBlank', 'showDropDown',
  'showInputMessage', 'showErrorMessage', 'errorStyle', 'errorTitle', 'error', 'promptTitle', 'prompt'])

function areaOf(ref: string): DvCellArea {
  const clean = ref.replaceAll('$', '')
  const columns = clean.match(/^([A-Z]+):([A-Z]+)$/)
  const rows = clean.match(/^([1-9][0-9]*):([1-9][0-9]*)$/)
  const range = columns
    ? { startRow: 0, endRow: 1048575, startColumn: columnIndex(columns[1]!), endColumn: columnIndex(columns[2]!) }
    : rows
      ? { startRow: Number(rows[1]) - 1, endRow: Number(rows[2]) - 1, startColumn: 0, endColumn: 16383 }
      : parseRange(ref)
  if (range.startRow > range.endRow || range.startColumn > range.endColumn ||
      range.endRow >= 1048576 || range.endColumn >= 16384) throw new Error('数据验证范围超出工作表')
  return range
}

function readEntry(entry: string, x14: boolean): DvWireRule {
  const opening = entry.match(/^<[^>]+>/)?.[0] ?? ''
  for (const attr of opening.matchAll(/([\w:.-]+)\s*=/g)) {
    if (!ATTRIBUTES.has(attr[1]!) && !attr[1]!.startsWith('xmlns')) {
      throw new Error(`数据验证属性 ${attr[1]} 尚未建模`)
    }
  }
  const attribute = (key: string) => {
    const value = readXmlAttribute(opening, key)
    return value === undefined ? undefined : decodeXmlText(value)
  }
  const bool = (key: string) => {
    const value = attribute(key)
    if (value !== undefined && !['0', '1', 'false', 'true'].includes(value)) throw new Error('数据验证布尔属性无效')
    return value === '1' || value === 'true'
  }
  const type = attribute('type') ?? 'none'
  if (!TYPES.has(type)) throw new Error(`数据验证类型 ${type} 尚未支持`)
  const sqref = x14 ? entry.match(/<xm:sqref\b[^>]*>([\s\S]*?)<\/xm:sqref>/)?.[1] : attribute('sqref')
  if (!sqref?.trim()) throw new Error('数据验证缺少范围')
  const rule: Record<string, unknown> = {
    type: type === 'none' ? 'any' : type, allowBlank: bool('allowBlank'),
    ...(type === 'list' ? { showDropDown: !bool('showDropDown') } : {}),
    showInputMessage: bool('showInputMessage'), showErrorMessage: bool('showErrorMessage'),
  }
  for (const key of ['operator', 'errorTitle', 'error', 'promptTitle', 'prompt']) {
    const value = attribute(key)
    if (value !== undefined) rule[key] = value
  }
  if (['whole', 'decimal', 'date', 'time', 'textLength'].includes(type) && rule.operator === undefined) rule.operator = 'between'
  const errorStyle = attribute('errorStyle')
  if (errorStyle !== undefined) {
    if (!(errorStyle in ERROR_STYLES)) throw new Error('数据验证错误样式无效')
    rule.errorStyle = ERROR_STYLES[errorStyle]
  }
  let rest = entry.slice(opening.length).replace(/<\/(?:x14:)?dataValidation>$/, '')
  for (const key of ['formula1', 'formula2']) {
    const pattern = x14
      ? new RegExp(String.raw`<x14:${key}\b[^>]*>\s*<xm:f\b[^>]*>([\s\S]*?)<\/xm:f>\s*<\/x14:${key}>`)
      : new RegExp(String.raw`<${key}\b[^>]*>([\s\S]*?)<\/${key}>`)
    const match = rest.match(pattern)
    if (!match) continue
    let formula = decodeXmlText(match[1]!)
    if (type === 'list') {
      const literal = formula.startsWith('"') && formula.endsWith('"')
      formula = literal
        ? formula.slice(1, -1).replaceAll('""', '"')
        : `=${formula.replace(/^=/, '')}`
      if (literal && formula.startsWith('=')) throw new Error('以等号开头的列表常量尚不能无损编辑')
    } else if (type === 'custom') formula = `=${formula.replace(/^=/, '')}`
    else if (formula.trim() && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$/.test(formula.trim())) {
      // OOXML omits the formula prefix; Univer requires it for references and expressions.
      formula = `=${formula.replace(/^=/, '')}`
    }
    rule[key] = formula
    rest = rest.replace(match[0], '')
  }
  if (x14) rest = rest.replace(/<xm:sqref\b[^>]*>[\s\S]*?<\/xm:sqref>/, '')
  if (rest.trim()) throw new Error('数据验证含未建模的子元素')
  const result = { ranges: decodeXmlText(sqref).trim().split(/\s+/).map(areaOf), rule }
  // Share serializer validation rather than maintain a second operator schema.
  applyDvRules('<worksheet><sheetData/></worksheet>', [result])
  return result
}

export function readDataValidations(xml: string): SheetDataValidationModel {
  const model: SheetDataValidationModel = { rules: [] }
  try {
    const sections = [...xml.matchAll(/<(x14:)?dataValidations\b[^>]*\/>|<(x14:)?dataValidations\b[^>]*>[\s\S]*?<\/(?:x14:)?dataValidations>/g)]
    for (const section of sections) {
      const raw = section[0]
      const x14 = raw.startsWith('<x14:')
      const opening = raw.match(/^<[^>]+>/)![0]
      for (const attr of opening.matchAll(/([\w:.-]+)\s*=/g)) {
        if (attr[1] !== 'count' && !attr[1]!.startsWith('xmlns')) throw new Error(`数据验证容器属性 ${attr[1]} 尚未建模`)
      }
      const entries = [...raw.matchAll(/<(?:x14:)?dataValidation\b[^>]*\/>|<(?:x14:)?dataValidation\b[^>]*>[\s\S]*?<\/(?:x14:)?dataValidation>/g)]
      const count = readXmlAttribute(opening, 'count')
      if (count !== undefined && Number(count) !== entries.length) throw new Error('数据验证规则数量不一致')
      let rest = raw.slice(opening.length).replace(/<\/(?:x14:)?dataValidations>$/, '')
      for (const entry of entries) {
        model.rules.push(readEntry(entry[0], x14))
        rest = rest.replace(entry[0], '')
      }
      if (rest.trim()) throw new Error('数据验证包含未识别规则')
    }
    const remaining = sections.reduce((rest, section) => rest.replace(section[0], ''), xml)
    if (/<(?:[\w.-]+:)?dataValidations?\b/.test(remaining)) throw new Error('数据验证使用未支持的命名空间或结构')
  } catch (error) {
    model.readOnlyReason = error instanceof Error ? error.message : '数据验证无法完整读取'
  }
  if (!model.readOnlyReason) restoreCheckboxValidations(xml, model.rules, rule => applyDvRules('<worksheet><sheetData/></worksheet>', [rule]))
  return model
}
