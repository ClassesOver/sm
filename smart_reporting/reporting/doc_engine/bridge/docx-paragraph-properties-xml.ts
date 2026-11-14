import type { Block, ParaFormat } from '../packages/docx-engine/src/types'
import { mergePPrFormat, PPR_CHILD_ORDER, splitXmlChildren } from '../packages/docx-engine/src/generate'
import { normalizeDocxParagraphProperties } from './docx-paragraph-properties'
import { docxLineSpacingPatch } from './docx-line-spacing'

/** 使用源引擎生成属性值，仅替换用户触及的属性族；保留未建模的 OOXML 属性。 */
export function patchDocxParagraphProperties(block: Block, input: unknown): string {
  const values = normalizeDocxParagraphProperties(input), xml = block.originalXml!
  if ('outlineLevel' in values && (block.type === 'listItem' || block.type === 'heading' && !block.outlineOnly)) throw new Error('docx_paragraph_outline_unsupported')
  const raw = /<w:pPr\b[^>]*>[\s\S]*?<\/w:pPr>|<w:pPr\b[^>]*\/>/.exec(xml)?.[0] ?? ''
  const inner = (ppr: string) => ppr.replace(/^<w:pPr\b[^>]*\/?>([\s\S]*?)(?:<\/w:pPr>)?$/, '$1')
  const children = splitXmlChildren(inner(raw)), format = { ...values, ...docxLineSpacingPatch(values) } as ParaFormat
  if ('indentFirstLineChars' in values) format.charIndents = { firstLine: Number(values.indentFirstLineChars) }
  const generated = splitXmlChildren(inner(mergePPrFormat('', format)))
  const touched = new Map<string, Set<string>>()
  const touch = (tag: string, ...attrs: string[]) => touched.set(tag, new Set([...(touched.get(tag) ?? []), ...attrs]))
  for (const key of Object.keys(values)) {
    if (key === 'align') touch('w:jc')
    else if (key === 'outlineLevel') touch('w:outlineLvl')
    else if (key === 'spaceBefore') touch('w:spacing', 'before', 'beforeLines', 'beforeAutospacing')
    else if (key === 'spaceAfter') touch('w:spacing', 'after', 'afterLines', 'afterAutospacing')
    else if (key.startsWith('line')) touch('w:spacing', 'line', 'lineRule')
    else if (key === 'indentLeft') touch('w:ind', 'left', 'start', 'leftChars', 'startChars')
    else if (key === 'indentRight') touch('w:ind', 'right', 'end', 'rightChars', 'endChars')
    else if (key.startsWith('indentFirstLine')) touch('w:ind', 'firstLine', 'hanging', 'firstLineChars', 'hangingChars')
    else touch(`w:${key}`)
  }
  for (const [tag, attrs] of touched) {
    const index = children.findIndex(child => child.name === tag), old = index < 0 ? '' : children[index]!.xml
    let fresh = generated.find(child => child.name === tag)?.xml ?? ''
    if (tag === 'w:outlineLvl') fresh = `<w:outlineLvl w:val="${Number(values.outlineLevel) === 0 ? 9 : Number(values.outlineLevel) - 1}"/>`
    if (tag === 'w:pageBreakBefore' && values.pageBreakBefore === false) fresh = '<w:pageBreakBefore w:val="0"/>'
    if (attrs.size) {
      const getAttrs = (element: string) => [...element.matchAll(/\s(w:[\w]+)="([^"]*)"/g)].map(m => [m[1]!, m[2]!] as const)
      const kept = getAttrs(old).filter(([name]) => !attrs.has(name.slice(2)))
      const changed = getAttrs(fresh).filter(([name]) => attrs.has(name.slice(2)))
      if (tag === 'w:spacing') for (const [key, name] of [['spaceBefore', 'before'], ['spaceAfter', 'after']] as const) if (key in values) {
        if (!changed.some(([a]) => a === `w:${name}`)) changed.push([`w:${name}`, String(values[key])])
        changed.push([`w:${name}Autospacing`, '0'])
      }
      // 绝对缩进必须显式取消来源/样式字符单位，否则 Word 仍优先使用字符值。
      if (tag === 'w:ind') for (const [key, names] of [['indentLeft', ['leftChars', 'startChars']], ['indentRight', ['rightChars', 'endChars']], ['indentFirstLine', ['firstLineChars', 'hangingChars']]] as const) if (key in values) {
        for (const name of names) if (!changed.some(([a]) => a === `w:${name}`)) changed.push([`w:${name}`, '0'])
      }
      fresh = `<${tag}${[...kept, ...changed].map(([name, value]) => ` ${name}="${value}"`).join('')}/>`
    }
    if (index >= 0) children.splice(index, 1)
    if (fresh) children.push({ name: tag, xml: fresh })
  }
  const rank = (name: string) => { const n = PPR_CHILD_ORDER.indexOf(name); return n < 0 ? PPR_CHILD_ORDER.length : n }
  children.sort((a, b) => rank(a.name) - rank(b.name))
  const open = /^<w:pPr\b[^>]*>/.exec(raw)?.[0].replace(/\/>$/, '>') ?? '<w:pPr>'
  const ppr = `${open}${children.map(child => child.xml).join('')}</w:pPr>`
  return raw ? xml.replace(raw, ppr) : xml.replace(/^(<w:p\b[^>]*>)/, `$1${ppr}`)
}
