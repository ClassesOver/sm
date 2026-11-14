import type { ParaFormat } from '../packages/docx-engine/src/types'
import { mergePPrFormat, xmlSegments } from '../packages/docx-engine/src/generate'
import { normalizeDocxDropCap } from './docx-drop-cap'

/** 复用固定源 framePr 生成与 schema 排序；其余属性和正文原字节保留。 */
export function patchDocxDropCapXml(xml: string, input: unknown): string {
  const cap = normalizeDocxDropCap(input)
  const segment = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
  const raw = segment ? xml.slice(segment.start, segment.end).replace(/\/>$/, '></w:pPr>') : '<w:pPr></w:pPr>'
  const ppr = mergePPrFormat(raw, { dropCap: cap } as unknown as ParaFormat, undefined, new Set(['w:framePr']))
  if (segment) return xml.slice(0, segment.start) + ppr + xml.slice(segment.end)
  if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return xml.replace(/\/>$/, `>${ppr}</w:p>`)
  return xml.replace(/^(<w:p\b[^>]*>)/, `$1${ppr}`)
}
