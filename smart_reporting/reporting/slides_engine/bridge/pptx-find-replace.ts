import type { TextElement } from '@genoffice/pptx-engine'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'

function unsafe(): never { throw new Error('pptx_find_replace_source_unsupported') }
function sourceChildren(xml: string, tag: string) {
  if (/<!--|<!\[CDATA\[|<\?/.test(xml)) unsafe()
  const open = new RegExp(`^<${tag}\\b(?:"[^"]*"|'[^']*'|[^'">])*>`).exec(xml)?.[0]
  if (!open) unsafe()
  const selfClosing = open.endsWith('/>')
  if (selfClosing ? open !== xml : !xml.endsWith(`</${tag}>`)) unsafe()
  const inner = selfClosing ? '' : xml.slice(open.length, -`</${tag}>`.length)
  const children = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== children.map(child => child.xml).join('').replace(/\s/g, '')) unsafe()
  return children
}

/** Only text bodies whose simple run structure the editor can round-trip without dropping
 * source semantics are searchable. Any unrecognized XML stays outside the replace surface. */
export function findReplaceEditable(element: TextElement | { type: string; anchor?: { originalXml: string }; text?: unknown }): boolean {
  try {
    if ((element.type !== 'text' && element.type !== 'shape') || !element.anchor?.originalXml || !element.text
      || typeof element.text !== 'object' || !('paragraphs' in element.text)) return false
    const paragraphs = (element.text as { paragraphs?: unknown }).paragraphs
    if (!Array.isArray(paragraphs) || !paragraphs.length) return false
    const xml = element.anchor.originalXml
    // Engine-generated shapes carry the standard creation identity extension in cNvPr;
    // it does not touch text and the element patcher preserves it verbatim.
    const withoutCreationId = xml.replace(/<a:extLst>\s*<a:ext uri="\{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236\}">\s*<a16:creationId\b[^>]*\/>\s*<\/a:ext>\s*<\/a:extLst>/g, '')
    if (/<(?:\w+:)?(?:extLst|AlternateContent|br|fld|hlinkClick|hlinkHover)\b/.test(withoutCreationId)) return false
    const shape = sourceChildren(xml, 'p:sp')
    for (const child of shape) {
      if (child.name === 'p:nvSpPr' || child.name === 'p:spPr') continue
      if (child.name !== 'p:txBody') return false
      const body = sourceChildren(child.xml, 'p:txBody')
      for (const bodyChild of body) {
        if (bodyChild.name === 'a:bodyPr' || bodyChild.name === 'a:lstStyle') continue
        if (bodyChild.name !== 'a:p') return false
        const paragraph = sourceChildren(bodyChild.xml, 'a:p')
        let runs = 0
        for (const item of paragraph) {
          if (item.name === 'a:pPr' || item.name === 'a:endParaRPr') continue
          if (item.name !== 'a:r') return false
          const run = sourceChildren(item.xml, 'a:r')
          if (run.some(part => part.name !== 'a:rPr' && part.name !== 'a:t')) return false
          if (run.filter(part => part.name === 'a:t').length !== 1 || run.filter(part => part.name === 'a:rPr').length > 1) return false
          const props = run.find(part => part.name === 'a:rPr')
          if (props && sourceChildren(props.xml, 'a:rPr').some(part => !['a:ln', 'a:solidFill', 'a:latin', 'a:ea', 'a:cs', 'a:sym', 'a:highlight', 'a:uFillTx', 'a:uLnTx'].includes(part.name))) return false
          runs++
        }
        if (runs !== 1) return false
      }
    }
    return shape.some(child => child.name === 'p:txBody')
  } catch { return false }
}
