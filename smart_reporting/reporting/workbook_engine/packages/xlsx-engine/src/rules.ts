/// Data-validation and conditional-format rule writing (lean port of the
/// genoffice xlsx-dv / xlsx-cf write paths): appends rules to the worksheet's
/// dataValidations / conditionalFormatting sections, with CF highlight styles
/// interned copy-on-write into styles.xml dxfs.

import {
  cfCellIsRuleSchema,
  cfColorScaleEngineSchema,
  cfDataBarSchema,
  cfIconSetSchema,
  isValidRuleSqref,
  OOXML_ICON_SETS,
  type CfAnyRule,
  type CfRule,
  type Cfvo,
} from './cf-schemas'
import { readXmlAttribute } from './xml'
import { StylesheetEditor } from './styles-write'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { assemblePackage, assertOnlyTouchedEntriesChanged, createBufferEntrySource, type MutationPlan } from './zip'

export type DvType = 'whole' | 'decimal' | 'list' | 'date' | 'textLength'
export type DvOperator =
  | 'between'
  | 'notBetween'
  | 'equal'
  | 'notEqual'
  | 'greaterThan'
  | 'lessThan'
  | 'greaterThanOrEqual'
  | 'lessThanOrEqual'

export interface DvRule {
  readonly sheet: string
  /// target range, e.g. "A2:A100" or multi "A2:A5 B2:B5"
  readonly sqref: string
  readonly type: DvType
  readonly operator?: DvOperator | undefined
  /// first operand: literal, list ("a,b,c" → quoted inline), or =FORMULA
  readonly formula1?: string | undefined
  readonly formula2?: string | undefined
  readonly allowBlank?: boolean | undefined
  readonly promptTitle?: string | undefined
  readonly prompt?: string | undefined
  readonly errorTitle?: string | undefined
  readonly error?: string | undefined
}

export type CfOperator =
  | 'greaterThan'
  | 'lessThan'
  | 'equal'
  | 'notEqual'
  | 'greaterThanOrEqual'
  | 'lessThanOrEqual'
  | 'between'
  | 'notBetween'

export type { CfAnyRule, CfColorScaleRule, CfDataBarRule, CfIconSetRule, CfRule, Cfvo } from './cf-schemas'


function assertSqref(sqref: string): void {
  if (!isValidRuleSqref(sqref)) {
    throw new Error(`非法区域 "${sqref}"：需要有效的 A1 地址/范围（多区域以空格分隔）。`)
  }
}

function escapeXmlAttributeXml(input: string): string {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function escapeXmlText(input: string): string {
  return input.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function dvFormulaXml(formula: string | undefined): string {
  if (formula === undefined || formula === '') return ''
  return `<formula1>${escapeXmlText(formula)}</formula1>`
}

function dvFormula2Xml(rule: DvRule): string {
  if (rule.formula2 === undefined || rule.formula2 === '') return ''
  return `<formula2>${escapeXmlText(rule.formula2)}</formula2>`
}

function serializeDvRule(rule: DvRule): string {
  assertSqref(rule.sqref)
  const attributes = [
    `sqref="${rule.sqref}"`,
    `type="${rule.type}"`,
    ...(rule.operator !== undefined ? [`operator="${rule.operator}"`] : []),
    'allowBlank="1"',
    ...(rule.promptTitle !== undefined || rule.prompt !== undefined
      ? ['showInputMessage="1"']
      : []),
    ...(rule.errorTitle !== undefined || rule.error !== undefined
      ? ['showErrorMessage="1"']
      : []),
  ]
  const body = `${dvFormulaXml(rule.formula1)}${dvFormula2Xml(rule)}`
  const attributesText = attributes.join(' ')
  return body === ''
    ? `<dataValidation ${attributesText}/>`
    : `<dataValidation ${attributesText}>${body}</dataValidation>`
}

/// Appends dataValidation rules onto the worksheet's dataValidations section,
/// creating the section when absent (schema position: after sheetData).
export function appendDataValidations(worksheetXml: string, rules: readonly DvRule[]): string {
  const serialized = rules.map(serializeDvRule).join('')
  const existing = worksheetXml.match(/<dataValidations\b([^>]*)>([\s\S]*?)<\/dataValidations>/)
  if (existing) {
    const count = Number(existing[1]?.match(/\bcount="([0-9]+)"/)?.[1] ?? '0') + rules.length
    const inner = `${existing[2] ?? ''}${serialized}`
    return worksheetXml.replace(
      existing[0],
      () => `<dataValidations count="${count}">${inner}</dataValidations>`,
    )
  }
  const section = `<dataValidations count="${rules.length}">${serialized}</dataValidations>`
  if (worksheetXml.includes('</sheetData>')) {
    return worksheetXml.replace('</sheetData>', () => `</sheetData>${section}`)
  }
  return worksheetXml.replace(/<sheetData\s*\/>/, () => `<sheetData/>${section}`)
}

function toArgb(hex: string): string {
  return `FF${hex.slice(1).toUpperCase()}`
}

function cfDxfXml(rule: CfRule): string {
  const font =
    rule.fontColor !== undefined || rule.bold === true || rule.italic === true || rule.strike === true || rule.underline === true
      ? `<font>${rule.bold === true ? '<b/>' : ''}${rule.italic === true ? '<i/>' : ''}${rule.strike === true ? '<strike/>' : ''}${rule.underline === true ? '<u/>' : ''}${
          rule.fontColor !== undefined ? `<color rgb="${toArgb(rule.fontColor)}"/>` : ''
        }</font>`
      : ''
  const fill =
    rule.fillColor !== undefined
      ? `<fill><patternFill patternType="solid"><fgColor rgb="${toArgb(rule.fillColor)}"/><bgColor indexed="64"/></patternFill></fill>`
      : ''
  const inner = `${font}${fill}`
  return inner === '' ? '<dxf/>' : `<dxf>${inner}</dxf>`
}

function cfFormula1(rule: CfRule): string {
  const text = rule.formula1.startsWith('=') ? rule.formula1.slice(1) : rule.formula1
  return `<formula>${escapeXmlText(text)}</formula>`
}

function cfFormula2(rule: CfRule): string {
  if (rule.formula2 === undefined || rule.formula2 === '') return ''
  const text = rule.formula2.startsWith('=') ? rule.formula2.slice(1) : rule.formula2
  return `<formula>${escapeXmlText(text)}</formula>`
}

function requireHexColor(color: string, what: string): string {
  if (!/^#[0-9A-Fa-f]{6}$/.test(color)) {
    throw new Error(`The ${what} color "${color}" is not a valid #RRGGBB value.`)
  }
  return color
}

function serializeCfvo(cfvo: Cfvo, extra = ''): string {
  if (cfvo.type === 'min' || cfvo.type === 'max') {
    return `<cfvo type="${cfvo.type}"${extra}/>`
  }
  if (cfvo.type === 'formula') {
    const value = String(cfvo.value ?? '')
    if (value === '') throw new Error('A formula threshold needs a formula value.')
    return `<cfvo type="formula" val="${escapeXmlAttributeXml(value)}"${extra}/>`
  }
  const numeric = Number(cfvo.value ?? 0)
  if (!Number.isFinite(numeric)) throw new Error(`Invalid numeric conditional-format threshold "${String(cfvo.value)}".`)
  return `<cfvo type="${cfvo.type}" val="${numeric}"${extra}/>`
}

/// Serialized <cfRule> for any CF variant; cellIs keeps the dxf highlight
/// path, the visual variants (colorScale/dataBar/iconSet) carry no dxf.
function serializeCfAnyRule(
  rule: CfAnyRule,
  dxfIdFor: (cellIs: CfRule) => number | undefined,
  priority: number,
): string {
  const stopIfTrue = 'stopIfTrue' in rule && rule.stopIfTrue === true ? ' stopIfTrue="1"' : ''
  if (!('kind' in rule)) {
    const dxfId = dxfIdFor(rule)
    return (
      `<cfRule type="cellIs"${dxfId === undefined ? '' : ` dxfId="${dxfId}"`} priority="${priority}"${stopIfTrue} operator="${rule.operator}">` +
      `${cfFormula1(rule)}${cfFormula2(rule)}</cfRule>`
    )
  }
  if (rule.kind === 'colorScale') {
    if (rule.stops.length < 2 || rule.stops.length > 3) {
      throw new Error('A color scale needs two or three stops.')
    }
    const cfvos = rule.stops.map((stop) => serializeCfvo(stop.cfvo)).join('')
    const colors = rule.stops
      .map((stop) => `<color rgb="${toArgb(requireHexColor(stop.color, 'color scale'))}"/>`)
      .join('')
    return (
      `<cfRule type="colorScale" priority="${priority}"${stopIfTrue}>` +
      `<colorScale>${cfvos}${colors}</colorScale></cfRule>`
    )
  }
  if (rule.kind === 'dataBar') {
    const showValue = rule.showValue === false ? ' showValue="0"' : ''
    return (
      `<cfRule type="dataBar" priority="${priority}"${stopIfTrue}>` +
      `<dataBar${showValue}>${serializeCfvo(rule.min)}${serializeCfvo(rule.max)}` +
      `<color rgb="${toArgb(requireHexColor(rule.color, 'data bar'))}"/></dataBar></cfRule>`
    )
  }
  // iconSet
  if (!OOXML_ICON_SETS.includes(rule.iconSet)) {
    throw new Error(`The "${rule.iconSet}" icon set cannot be saved to xlsx.`)
  }
  const iconCount = Number(rule.iconSet.slice(0, 1))
  if (rule.thresholds.length !== iconCount) {
    throw new Error(
      `The "${rule.iconSet}" icon set needs exactly ${iconCount} thresholds.`,
    )
  }
  const cfvos = rule.thresholds
    .map((cfvo, index) => {
      // The first threshold is the catch-all minimum.
      if (index === 0) return '<cfvo type="percent" val="0"/>'
      return serializeCfvo(cfvo, cfvo.greaterThan === true ? ' gte="0"' : '')
    })
    .join('')
  const showValue = rule.showValue === false ? ' showValue="0"' : ''
  const reverse = rule.reverse === true ? ' reverse="1"' : ''
  return (
    `<cfRule type="iconSet" priority="${priority}"${stopIfTrue}>` +
    `<iconSet iconSet="${escapeXmlAttributeXml(rule.iconSet)}"${showValue}${reverse}>${cfvos}</iconSet></cfRule>`
  )
}

function nextCfPriority(worksheetXml: string): () => number {
  const used = new Set<number>()
  for (const match of worksheetXml.matchAll(/<(?:[A-Za-z_][\w.-]*:)?cfRule\b[^>]*?\bpriority="([0-9]+)"/g)) {
    used.add(Number(match[1]))
  }
  let candidate = 1
  return () => {
    while (used.has(candidate)) candidate += 1
    used.add(candidate)
    return candidate++
  }
}

const CF_BLOCK_PATTERN =
  /<conditionalFormatting\b[^>]*\/>|<conditionalFormatting\b[^>]*>[\s\S]*?<\/conditionalFormatting>/g

const AFTER_CF_PATTERN =
  /<dataValidations\b|<hyperlinks\b|<printOptions\b|<pageMargins\b|<pageSetup\b|<headerFooter\b|<rowBreaks\b|<colBreaks\b|<customProperties\b|<cellWatches\b|<ignoredErrors\b|<smartTags\b|<drawing\b|<legacyDrawing\b|<legacyDrawingHF\b|<picture\b|<oleObjects\b|<controls\b|<webPublishItems\b|<tableParts\b|<extLst\b/

function appendConditionalFormats(worksheetXml: string, blocks: readonly string[]): string {
  if (blocks.length === 0) return worksheetXml
  const body = blocks.join('')
  let lastEnd = -1
  for (const match of worksheetXml.matchAll(CF_BLOCK_PATTERN)) {
    if (match.index !== undefined) lastEnd = match.index + match[0].length
  }
  if (lastEnd >= 0) return worksheetXml.slice(0, lastEnd) + body + worksheetXml.slice(lastEnd)
  const afterSheetData = worksheetXml.match(/<sheetData\b[^>]*\/>|<\/sheetData>/)
  const searchStart = afterSheetData?.index === undefined
    ? 0
    : afterSheetData.index + afterSheetData[0].length
  const tail = worksheetXml.slice(searchStart)
  const anchor = tail.match(AFTER_CF_PATTERN)
  if (anchor?.index !== undefined) {
    const at = searchStart + anchor.index
    return worksheetXml.slice(0, at) + body + worksheetXml.slice(at)
  }
  const end = worksheetXml.lastIndexOf('</worksheet>')
  if (end < 0) throw new Error('Worksheet has no closing element.')
  return worksheetXml.slice(0, end) + body + worksheetXml.slice(end)
}


function appendRootChild(xml: string, rootName: string, child: string): string {
  const empty = xml.match(new RegExp(String.raw`<${rootName}\b([^>]*?)/>`))
  if (empty?.index !== undefined) {
    return xml.slice(0, empty.index) + `<${rootName}${empty[1]}>${child}</${rootName}>` +
      xml.slice(empty.index + empty[0].length)
  }
  const close = `</${rootName}>`
  const at = xml.lastIndexOf(close)
  if (at < 0) throw new Error(`OOXML part has no closing ${close}.`)
  return xml.slice(0, at) + child + xml.slice(at)
}

function nextRelationshipIdForRules(relsXml: string): string {
  let max = 0
  for (const match of relsXml.matchAll(/\bId="rId([0-9]+)"/g)) max = Math.max(max, Number(match[1]))
  return `rId${max + 1}`
}


export async function applyDvRules(
  sourceBytes: Uint8Array,
  rules: readonly DvRule[],
): Promise<Uint8Array> {
  if (rules.length === 0) return sourceBytes
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const bySheet = new Map<string, DvRule[]>()
  for (const rule of rules) {
    const list = bySheet.get(rule.sheet) ?? []
    list.push(rule)
    bySheet.set(rule.sheet, list)
  }
  const replaced = new Map<string, string>()
  const touched: string[] = []
  for (const [sheetName, sheetRules] of bySheet) {
    const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
    if (!element?.relationshipId) {
      throw new Error(`工作表 "${sheetName}" 不存在。`)
    }
    const path = await resolveWorksheetPath(source, element.relationshipId)
    replaced.set(path, appendDataValidations(await source.readText(path), sheetRules))
    touched.push(path)
  }
  const plan: MutationPlan = {
    replaced,
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: touched,
  }
  return (await assemblePackage(sourceBytes, plan)).buffer
}

/// Applies CF rules (cellIs highlight styles interned into styles.xml dxfs;
/// colorScale/dataBar/iconSet rules carry their own visuals and no dxf).
export async function applyCfRules(
  sourceBytes: Uint8Array,
  rules: readonly CfAnyRule[],
): Promise<Uint8Array> {
  if (rules.length === 0) return sourceBytes
  const validated = rules.map((rule) => {
    assertSqref(rule.sqref)
    const schema = !('kind' in rule)
      ? cfCellIsRuleSchema
      : rule.kind === 'colorScale' ? cfColorScaleEngineSchema
        : rule.kind === 'dataBar' ? cfDataBarSchema : cfIconSetSchema
    const result = schema.safeParse(rule)
    if (!result.success) {
      const detail = result.error.issues.map((issue) => issue.message).join('; ')
      throw new Error(`Invalid conditional-format rule: ${detail}`)
    }
    return result.data
  })
  const source = await createBufferEntrySource(sourceBytes)
  for (const path of await source.paths()) {
    if (/\.xml$|\.rels$/i.test(path)) await source.readText(path)
  }
  const workbookXml = await source.readText('xl/workbook.xml')
  const hasStyles = await source.has('xl/styles.xml')
  const stylesheet = new StylesheetEditor(
    hasStyles ? await source.readText('xl/styles.xml') : await createBlankStyles(),
  )
  const replaced = new Map<string, string>()
  const added = new Map<string, string>()
  const bySheet = new Map<string, CfAnyRule[]>()
  for (const rule of validated) {
    const list = bySheet.get(rule.sheet) ?? []
    list.push(rule)
    bySheet.set(rule.sheet, list)
  }
  for (const [sheetName, sheetRules] of bySheet) {
    const element = parseSheetElements(workbookXml).find((entry) => entry.name === sheetName)
    if (!element?.relationshipId) throw new Error(`工作表 "${sheetName}" 不存在。`)
    const path = await resolveWorksheetPath(source, element.relationshipId)
    const xml = await source.readText(path)
    const nextPriority = nextCfPriority(xml)
    const blocks = sheetRules.map((rule) => {
      const ruleXml = serializeCfAnyRule(rule, (cellIs) => {
        const needsDxf = cellIs.fontColor !== undefined || cellIs.fillColor !== undefined ||
          cellIs.bold === true || cellIs.italic === true || cellIs.strike === true || cellIs.underline === true
        return needsDxf ? stylesheet.internDxf(cfDxfXml(cellIs)) : undefined
      }, nextPriority())
      return `<conditionalFormatting sqref="${escapeXmlAttributeXml(rule.sqref)}">${ruleXml}</conditionalFormatting>`
    })
    replaced.set(path, appendConditionalFormats(xml, blocks))
  }
  if (stylesheet.changed) {
    if (hasStyles) {
      replaced.set('xl/styles.xml', stylesheet.serialize())
    } else {
      added.set('xl/styles.xml', stylesheet.serialize())
      const contentTypes = await source.readText('[Content_Types].xml')
      const overrides = [...contentTypes.matchAll(/<Override\b[^>]*\/>/g)]
      if (!overrides.some((entry) => readXmlAttribute(entry[0], 'PartName') === '/xl/styles.xml')) {
        replaced.set('[Content_Types].xml', appendRootChild(contentTypes, 'Types',
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'))
      }
      const relsPath = 'xl/_rels/workbook.xml.rels'
      const rels = await source.readText(relsPath)
      const relType = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles'
      const styleRel = [...rels.matchAll(/<Relationship\b[^>]*\/>/g)]
        .find((entry) => readXmlAttribute(entry[0], 'Type') === relType)
      if (styleRel) {
        const target = readXmlAttribute(styleRel[0], 'Target') ?? ''
        if (!['styles.xml', './styles.xml', '/xl/styles.xml'].includes(target)) {
          throw new Error('A nonstandard styles relationship cannot be replaced implicitly.')
        }
      } else {
        replaced.set(relsPath, appendRootChild(rels, 'Relationships',
          `<Relationship Id="${nextRelationshipIdForRules(rels)}" Type="${relType}" Target="styles.xml"/>`))
      }
    }
  }
  const mutation = await assemblePackage(sourceBytes, {
    replaced,
    added,
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [...added.keys()],
    touchedEntries: [...replaced.keys(), ...added.keys()],
  })
  assertOnlyTouchedEntriesChanged(mutation)
  return mutation.buffer
}

async function createBlankStyles(): Promise<string> {
  const { createBlankWorkbook } = await import('./blank')
  const bytes = await createBlankWorkbook()
  const source = await createBufferEntrySource(bytes)
  return source.readText('xl/styles.xml')
}

// ── chart edits (title / type conversion / series colors) ────────────────

import { applyChartEdit, type ChartEditLean } from './chart-edit'

export type { ChartEditLean } from './chart-edit'

/// Lists chart parts (path order = xl/charts/chartN.xml sorted).
export async function listChartParts(sourceBytes: Uint8Array): Promise<string[]> {
  const source = await createBufferEntrySource(sourceBytes)
  const charts: string[] = []
  for (const path of await source.paths()) {
    if (/^xl\/charts\/chart[0-9]+\.xml$/.test(path)) charts.push(path)
  }
  return charts.sort()
}

/// Applies lean chart edits to specific chart parts (fail closed per chart).
export async function applyChartEdits(
  sourceBytes: Uint8Array,
  edits: ReadonlyArray<{ chartPath: string } & ChartEditLean>,
): Promise<Uint8Array> {
  if (edits.length === 0) return sourceBytes
  const source = await createBufferEntrySource(sourceBytes)
  const replaced = new Map<string, string>()
  const touched: string[] = []
  for (const edit of edits) {
    if (!/^xl\/charts\/[A-Za-z0-9._-]+\.xml$/.test(edit.chartPath)) {
      throw new Error(`非法图表路径 "${edit.chartPath}"。`)
    }
    if (!(await source.has(edit.chartPath))) {
      throw new Error(`图表 "${edit.chartPath}" 不存在（可用 listChartParts 查询）。`)
    }
    const base = replaced.get(edit.chartPath) ?? (await source.readText(edit.chartPath))
    replaced.set(edit.chartPath, applyChartEdit(base, edit))
    if (!touched.includes(edit.chartPath)) touched.push(edit.chartPath)
  }
  const plan: MutationPlan = {
    replaced,
    added: new Map(),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: [],
    touchedEntries: touched,
  }
  return (await assemblePackage(sourceBytes, plan)).buffer
}

export { escapeXmlAttributeXml }
