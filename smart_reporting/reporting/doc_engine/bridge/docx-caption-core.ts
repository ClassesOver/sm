import { generateCaptionXml } from '../packages/docx-engine/src/generate'
import { decodeXmlText } from '../packages/docx-engine/src/zotero-doc-props'
import { attrsOf, xmlParser, type XNode } from '../packages/docx-engine/src/xml-utils'
import { docxTocSource } from './docx-toc-core'
import type { parseDocx } from '../packages/docx-engine/src/parse'

export type CaptionLabel = '图' | '表' | '公式'
export type CaptionOperation = { kind: 'insertCaption'; blockId: string; expectedObjectSha256: string; position: 'before' | 'after'; label: CaptionLabel; text: string }
export const isDocxCaptionOperation = (value: { kind?: unknown }) => value.kind === 'insertCaption'
export function readDocxCaptionOperation(value: unknown): CaptionOperation {
  const op = value as Partial<CaptionOperation> | null
  if (!op || typeof op !== 'object' || !isDocxCaptionOperation(op)
    || !/^[a-f0-9]{64}$/.test(op.blockId ?? '') || !/^[a-f0-9]{64}$/.test(op.expectedObjectSha256 ?? '')
    || !['before', 'after'].includes(op.position ?? '') || !['图', '表', '公式'].includes(op.label ?? '')
    || typeof op.text !== 'string' || op.text.length > 1000 || op.text !== op.text.trim()
    || /[\x00-\x1f\x7f-\x9f\uFFFE\uFFFF]/u.test(op.text)
    || [...op.text].some(char => { const code = char.codePointAt(0)!; return code >= 0xd800 && code <= 0xdfff })
    || Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'label', 'text'].includes(key))) throw new Error('docx_caption_operation')
  return op as CaptionOperation
}

type Field = { start: number; end?: number; instruction: string; result: string; separated: boolean; invalid: boolean; nested: boolean }
/** Read complete real fields, including split instructions. Unsupported fields affect only their own label. */
export function docxCaptionNumber(xml: string, label: CaptionLabel, insertion: number): number {
  const fields: Field[] = [], stack: Field[] = []
  let simpleDepth = 0, unsafeDepth = 0
  // Opaque comments and declarations are never interpreted as executable Word fields.
  const events = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<\/?w:(?:del|ins|moveFrom|moveTo|txbxContent)\b(?:[^>"']|"[^"]*"|'[^']*')*>|<\/?w:fldSimple\b(?:[^>"']|"[^"]*"|'[^']*')*>|<w:fldChar\b(?:[^>"']|"[^"]*"|'[^']*')*>|<w:(instrText|delInstrText|t)\b(?:[^>"']|"[^"]*"|'[^']*')*>((?:<!\[CDATA\[[\s\S]*?\]\]>|<!--[\s\S]*?-->|[^<])*)<\/w:\1\s*>/g
  for (const event of xml.matchAll(events)) {
    const token = event[0], start = event.index!
    if (token.startsWith('<!') || token.startsWith('<?')) continue
    if (/^<\/?w:(?:del|ins|moveFrom|moveTo|txbxContent)\b/.test(token)) {
      if (!token.endsWith('/>')) unsafeDepth += token.startsWith('</') ? -1 : 1
      for (const field of stack) field.invalid = true
      continue
    }
    if (/^<w:fldSimple\b/.test(token)) {
      const attrs = attrsOf((xmlParser.parse(token.endsWith('/>') ? token : token.slice(0, -1) + '/>') as XNode[])[0]!)
      const field = { start, end: start + token.length, instruction: decodeXmlText(attrs['w:instr'] ?? ''), result: '', separated: false, invalid: true, nested: true }
      fields.push(field); if (!token.endsWith('/>')) simpleDepth++
      continue
    }
    if (/^<\/w:fldSimple/.test(token)) { simpleDepth--; continue }
    if (/^<w:fldChar\b/.test(token)) {
      const attrs = attrsOf((xmlParser.parse(token.endsWith('/>') ? token : token.slice(0, -1) + '/>') as XNode[])[0]!)
      const type = decodeXmlText(attrs['w:fldCharType'] ?? '')
      if (type === 'begin') {
        const field: Field = { start, instruction: '', result: '', separated: false, invalid: simpleDepth > 0 || unsafeDepth > 0 || attrs['w:fldLock'] !== undefined, nested: stack.length > 0 }
        for (const parent of stack) parent.nested = true
        fields.push(field); stack.push(field)
      } else if (type === 'separate') {
        const field = stack.at(-1)
        if (field) { if (field.separated) field.invalid = true; field.separated = true }
      } else if (type === 'end') {
        const field = stack.pop()
        if (field) field.end = start + token.length
      } else if (stack.length) stack.at(-1)!.invalid = true
      continue
    }
    const field = stack.at(-1)
    // CDATA text is literal; ordinary XML text decodes entities. Comments carry no field text.
    const opening = /^<w:[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/.exec(token)![0]
    const content = token.slice(opening.length, token.lastIndexOf('</'))
      .split(/(<!\[CDATA\[[\s\S]*?\]\]>)/g)
      .map(part => part.startsWith('<![CDATA[') ? part.slice(9, -3) : decodeXmlText(part.replace(/<!--[\s\S]*?-->/g, ''))).join('')
    if (!field) {
      if (event[1] === 'instrText' || event[1] === 'delInstrText') fields.push({ start, instruction: content, result: '', separated: false, invalid: true, nested: false })
      continue
    }
    if (event[1] === 'instrText') {
      if (field.separated) field.invalid = true
      field.instruction += content
    } else if (event[1] === 'delInstrText') field.invalid = true
    else if (field.separated) field.result += content
  }
  let count = 0
  const labelPattern = new RegExp('^\\s*SEQ\\s+(?:"' + label + '"|' + label + ')(?=\\s|\\\\|$)', 'i')
  for (const field of fields) {
    const match = labelPattern.exec(field.instruction)
    if (!match) continue
    const tail = field.instruction.slice(match[0].length).trim()
    if (!field.end || field.invalid || field.nested || !field.separated || !/^(?:\\\*\s+ARABIC)?$/i.test(tail)
      || field.result !== String(count + 1)) throw new Error('docx_caption_sequence_unsupported')
    if (field.end > insertion) throw new Error('docx_caption_sequence_position')
    count++
  }
  return count + 1
}

export function docxCaptionPlan(parsed: Awaited<ReturnType<typeof parseDocx>>, _op: CaptionOperation) {
  const source = docxTocSource(parsed)
  if (!source.safe) throw new Error('docx_caption_source_unsupported')
  // Alternate Word namespace prefixes can hide fields from the byte scanner.
  if (/\bxmlns:(?!w[=\s])[^=\s]+\s*=\s*["']http:\/\/schemas\.openxmlformats\.org\/wordprocessingml\/2006\/main["']/.test(source.xml)) throw new Error('docx_caption_source_unsupported')
  return source
}
export function docxCaptionXml(label: CaptionLabel, number: number, text: string) { return generateCaptionXml(label, number, text) }
