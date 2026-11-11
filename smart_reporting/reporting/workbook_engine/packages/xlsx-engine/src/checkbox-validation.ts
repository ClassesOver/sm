/** 本地持久化适配：Univer checkbox 的 Excel list fallback 之外，显式保存编辑器类型。
 * 不把普通 1,0 列表猜成 checkbox，也不声称这是 Excel 新式 boolean cell control。 */
import type { DvWireRule, DvCellArea } from './data-validation'
import { decodeXmlText, escapeXmlText } from './xml'

const URI = 'urn:smart-reporting:xlsx:checkbox:1'
const NS = 'https://smart-reporting.local/ns/xlsx/checkbox/1'
const EXT = /<ext\b[^>]*>[\s\S]*?<\/ext>|<ext\b[^>]*\/>/g
interface StoredCheckbox { original: DvWireRule; fallback: string }

export function checkboxFallback(item: DvWireRule): DvWireRule {
  const rule = item.rule
  const checked = rule.formula1 === undefined || rule.formula1 === '' ? '1' : String(rule.formula1)
  const unchecked = rule.formula2 === undefined || rule.formula2 === '' ? '0' : String(rule.formula2)
  return { ranges: item.ranges, rule: { ...rule, type: 'list', operator: undefined,
    formula1: `${checked},${unchecked}`, formula2: undefined } }
}

function stored(xml: string): StoredCheckbox[] {
  const extensions = [...xml.matchAll(EXT)].filter(match => match[0].match(/^<ext\b[^>]*\buri="([^"]*)"/)?.[1] === URI)
  if (extensions.length !== 1) return []
  const body = extensions[0]![0].match(/^<ext\b[^>]*><sr:checkboxes xmlns:sr="([^"]*)" version="1">([^<]*)<\/sr:checkboxes><\/ext>$/)
  if (!body || body[1] !== NS) return []
  try {
    const items: unknown = JSON.parse(decodeXmlText(body[2]!))
    if (!Array.isArray(items) || items.length > 10000) return []
    return items.filter((item): item is StoredCheckbox => !!item && typeof item === 'object' &&
      typeof item.fallback === 'string' && item.original?.rule?.type === 'checkbox' && Array.isArray(item.original?.ranges) &&
      [item.original.rule.formula1, item.original.rule.formula2].every(value => value === undefined || ['string', 'number', 'boolean'].includes(typeof value)))
  } catch { return [] }
}

export function restoreCheckboxValidations(xml: string, rules: DvWireRule[], serialize: (rule: DvWireRule) => string): void {
  const items = stored(xml)
  const actualIdentities = rules.map(rule => serialize(rule))
  for (let index = 0; index < rules.length; index++) {
    try {
      const actual = actualIdentities[index]!
      if (actualIdentities.filter(identity => identity === actual).length !== 1) continue
      const matching = items.filter(item => item.fallback === actual && serialize(checkboxFallback(item.original)) === actual)
      if (matching.length === 1) {
        const original = matching[0]!.original.rule
        rules[index] = { ranges: rules[index]!.ranges, rule: { ...rules[index]!.rule,
          type: 'checkbox', formula1: original.formula1, formula2: original.formula2 } }
      }
    } catch { /* 不可信扩展只失去 checkbox 投影，已完整读取的普通 DV 保留。 */ }
  }
}

export function writeCheckboxValidations(xml: string, rules: readonly DvWireRule[], serialize: (rule: DvWireRule) => string, append = false, remove: readonly DvCellArea[] = [], previousRules: readonly DvWireRule[] = []): string {
  const areaKey = (area: DvCellArea) => JSON.stringify([area.startRow, area.endRow, area.startColumn, area.endColumn])
  const replaced = new Set([...rules.flatMap(rule => rule.ranges), ...remove].map(areaKey))
  const items: StoredCheckbox[] = []
  const previousIdentities = previousRules.map(item => serialize(item.rule.type === 'checkbox' ? checkboxFallback(item) : item))
  const previous = stored(xml)
  if (append) for (const item of previous) {
    try {
      if (item.fallback !== serialize(checkboxFallback(item.original)) ||
          previousIdentities.filter(identity => identity === item.fallback).length !== 1 ||
          previous.filter(other => other.fallback === item.fallback).length !== 1) continue
      const original = { ...item.original, ranges: item.original.ranges.filter(area => !replaced.has(areaKey(area))) }
      if (original.ranges.length) items.push({ original, fallback: serialize(checkboxFallback(original)) })
    } catch { /* 破损 metadata 不参与新保存。 */ }
  }
  items.push(...rules.filter(item => item.rule.type === 'checkbox').map(original => ({ original, fallback: serialize(checkboxFallback(original)) })))
  xml = xml.replace(EXT, ext => ext.match(/^<ext\b[^>]*\buri="([^"]*)"/)?.[1] === URI ? '' : ext)
  // 删除本适配独占的空容器；其他扩展逐字保留。
  xml = xml.replace(/<extLst\b[^>]*>\s*<\/extLst>/g, '')
  if (!items.length) return xml
  const ext = `<ext uri="${URI}"><sr:checkboxes xmlns:sr="${NS}" version="1">${escapeXmlText(JSON.stringify(items))}</sr:checkboxes></ext>`
  const close = xml.lastIndexOf('</extLst>')
  if (close > xml.lastIndexOf('</sheetData>')) return xml.slice(0, close) + ext + xml.slice(close)
  const end = xml.lastIndexOf('</worksheet>')
  return xml.slice(0, end) + `<extLst>${ext}</extLst>` + xml.slice(end)
}
