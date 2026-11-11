import { createBufferEntrySource, assemblePackage } from './zip'
import { readXmlAttribute } from './xml'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
export interface OutlineLineEdit {
  index: number
  level: number
  collapsed: boolean
  hidden?: boolean
}
export interface SheetOutlineEdit {
  summaryBelow?: boolean
  summaryRight?: boolean
  rows?: readonly OutlineLineEdit[]
  columns?: readonly OutlineLineEdit[]
}
function attributes(tag: string, entry: OutlineLineEdit): string {
  const set = (name: string, value: string | null) => {
    tag = tag.replace(new RegExp(`\\s+${name}="[^"]*"`, 'g'), '')
    if (value !== null) tag = tag.replace(/\s*\/?>$/, (ending) => ` ${name}="${value}"${ending}`)
  }
  set('outlineLevel', entry.level ? String(entry.level) : null)
  set('collapsed', entry.collapsed ? '1' : null)
  if (entry.hidden !== undefined) set('hidden', entry.hidden ? '1' : null)
  return tag
}
export function setSheetOutlineXml(xml: string, edits: SheetOutlineEdit): string {
  if (edits.summaryBelow !== undefined || edits.summaryRight !== undefined) {
    for (const value of [edits.summaryBelow, edits.summaryRight])
      if (value !== undefined && typeof value !== 'boolean') throw new Error('分组汇总方向无效')
    const patch = (original: string) => {
      let tag = original.replace(/>\s*<\/outlinePr>$/, '/>')
      for (const name of ['summaryBelow', 'summaryRight'] as const) {
        if (edits[name] === undefined) continue
        tag = tag.replace(new RegExp(`\\s+${name}="[^"]*"`, 'g'), '')
        tag = tag.replace(/\s*\/?>$/, (ending) => ` ${name}="${edits[name] ? '1' : '0'}"${ending}`)
      }
      return tag
    }
    const outline = xml.match(/<outlinePr\b[^>]*(?:\/>|>\s*<\/outlinePr>)/)
    if (outline) xml = xml.replace(outline[0], patch(outline[0]))
    else {
      const added = patch('<outlinePr/>')
      const properties = xml.match(/<sheetPr\b[^>]*(?:\/>|>[\s\S]*?<\/sheetPr>)/)
      if (properties) {
        const section = properties[0].endsWith('/>')
          ? properties[0].slice(0, -2) + '>' + added + '</sheetPr>'
          : properties[0].replace(/<(?:pageSetUpPr)\b|<\/sheetPr>/, (match) => added + match)
        xml = xml.replace(properties[0], section)
      } else xml = xml.replace(/<worksheet\b[^>]*>/, (tag) => tag + `<sheetPr>${added}</sheetPr>`)
    }
  }
  for (const [axis, entries, limit] of [
    ['rows', edits.rows ?? [], 1048576],
    ['columns', edits.columns ?? [], 16384]
  ] as const) {
    for (const entry of entries) {
      if (
        !Number.isInteger(entry.index) ||
        entry.index < 0 ||
        entry.index >= limit ||
        !Number.isInteger(entry.level) ||
        entry.level < 0 ||
        entry.level > 7 ||
        typeof entry.collapsed !== 'boolean' ||
        (entry.hidden !== undefined && typeof entry.hidden !== 'boolean')
      )
        throw new Error('分组层级或行列边界无效')
      const index = entry.index + 1
      if (axis === 'rows') continue
      {
        let found = false
        const current = xml.match(/<cols\b[^>]*>([\s\S]*?)<\/cols>/)
        let inner = (current?.[1] ?? '').replace(/<col\b[^>]*(?:\/>|>\s*<\/col>)/g, (original) => {
          const tag = original.replace(/>\s*<\/col>$/, '/>')
          const min = Number(readXmlAttribute(tag, 'min')),
            max = Number(readXmlAttribute(tag, 'max'))
          if (index < min || index > max) return tag
          found = true
          const span = (a: number, b: number) =>
            tag.replace(/\bmin="[^"]*"/, `min="${a}"`).replace(/\bmax="[^"]*"/, `max="${b}"`)
          return (
            (min < index ? span(min, index - 1) : '') +
            attributes(span(index, index), entry) +
            (index < max ? span(index + 1, max) : '')
          )
        })
        if (!found) {
          const added = attributes(`<col min="${index}" max="${index}"/>`, entry)
          let inserted = false
          inner = inner.replace(/<col\b[^>]*>/g, (tag) => {
            if (!inserted && Number(readXmlAttribute(tag, 'min')) > index) {
              inserted = true
              return added + tag
            }
            return tag
          })
          if (!inserted) inner += added
        }
        const cols = inner
        if (current) xml = xml.replace(current[0], `<cols>${cols}</cols>`)
        else xml = xml.replace(/<sheetData\b/, `<cols>${cols}</cols><sheetData`)
      }
    }
  }
  if (edits.rows?.length) {
    if (/<sheetData\b[^>]*\/>/.test(xml)) xml = xml.replace(/<sheetData\b[^>]*\/>/, '<sheetData></sheetData>')
    const requested = new Map(edits.rows.map((entry) => [entry.index + 1, entry]))
    const section = xml.match(/<sheetData\b[^>]*>([\s\S]*?)<\/sheetData>/)
    if (!section) throw new Error('工作表缺少sheetData')
    const existing = new Set([...section[1]!.matchAll(/<row\b[^>]*\br="([0-9]+)"/g)].map((match) => Number(match[1])))
    const missing = [...requested.keys()].filter((index) => !existing.has(index)).sort((a, b) => a - b)
    let cursor = 0
    let inner = section[1]!.replace(/<row\b[^>]*\br="([0-9]+)"[^>]*>/g, (tag, row) => {
      let prefix = ''
      while (cursor < missing.length && missing[cursor]! < Number(row)) {
        const index = missing[cursor++]!
        prefix += attributes(`<row r="${index}"/>`, requested.get(index)!)
      }
      const update = requested.get(Number(row))
      return prefix + (update ? attributes(tag, update) : tag)
    })
    while (cursor < missing.length) {
      const index = missing[cursor++]!
      inner += attributes(`<row r="${index}"/>`, requested.get(index)!)
    }
    xml = xml.replace(section[0], section[0].slice(0, section[0].indexOf('>') + 1) + inner + '</sheetData>')
  }
  const max = (tag: 'row' | 'col') => {
    let level = 0
    for (const match of xml.matchAll(new RegExp(`<${tag}\\b[^>]*>`, 'g')))
      level = Math.max(level, Number(readXmlAttribute(match[0], 'outlineLevel') ?? 0))
    return level
  }
  const rowMax = max('row'),
    colMax = max('col')
  const format = xml.match(/<sheetFormatPr\b[^>]*(?:\/>|>\s*<\/sheetFormatPr>)/)
  let replacement = format ? format[0].replace(/>\s*<\/sheetFormatPr>$/, '/>') : '<sheetFormatPr defaultRowHeight="15"/>'
  replacement = replacement
    .replace(/\s+outlineLevel(?:Row|Col)="[^"]*"/g, '')
    .replace('/>', `${rowMax ? ` outlineLevelRow="${rowMax}"` : ''}${colMax ? ` outlineLevelCol="${colMax}"` : ''}/>`)
  if (format) xml = xml.replace(format[0], replacement)
  else xml = xml.replace(/<(?:cols|sheetData)\b/, (match) => replacement + match)
  return xml
}
export async function applySheetOutline(
  bytes: Uint8Array,
  sheetName: string,
  edits: SheetOutlineEdit
): Promise<Uint8Array> {
  const source = await createBufferEntrySource(bytes),
    workbook = await source.readText('xl/workbook.xml')
  const sheet = parseSheetElements(workbook).find((item) => item.name === sheetName)
  if (!sheet?.relationshipId) throw new Error('找不到分组目标工作表')
  const path = await resolveWorksheetPath(source, sheet.relationshipId),
    xml = setSheetOutlineXml(await source.readText(path), edits)
  return (
    await assemblePackage(bytes, {
      replaced: new Map([[path, xml]]),
      added: new Map(),
      addedBinary: new Map(),
      removedEntries: [],
      addedEntries: [],
      touchedEntries: [path]
    })
  ).buffer
}
