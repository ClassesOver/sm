export type MasterRichRun = {
  text: string; srcRun?: number; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean
  fontSize?: number; fontFamily?: string; color?: string
}
export type MasterRichParagraph = { runs: MasterRichRun[]; srcPara?: number; align?: 'left' | 'center' | 'right' | 'justify' }

export function masterRichTextHtml(paragraphs: readonly MasterRichParagraph[]): string {
  return paragraphs.map((paragraph, pi) => {
    const runs = paragraph.runs.map(run => {
      const decorations = [run.underline ? 'underline' : '', run.strike ? 'line-through' : ''].filter(Boolean).join(' ')
      const styles = [run.bold ? 'font-weight:700' : '', run.italic ? 'font-style:italic' : '', decorations ? `text-decoration:${decorations}` : '', run.fontSize ? `font-size:${run.fontSize}pt` : '', run.fontFamily ? `font-family:${safeCss(run.fontFamily)}` : '', run.color && /^#[0-9a-f]{6}$/i.test(run.color) ? `color:${run.color}` : ''].filter(Boolean).join(';')
      const attrs = [Number.isInteger(run.srcRun) ? `data-src-run="${run.srcRun}"` : '', run.fontSize ? `data-font-size="${run.fontSize}"` : '', run.fontFamily ? `data-font-family="${escapeAttr(run.fontFamily)}"` : '', run.color && /^#[0-9a-f]{6}$/i.test(run.color) ? `data-color="${run.color}"` : ''].filter(Boolean).join(' ')
      return `<span ${attrs} style="${styles}">${escapeHtml(run.text)}</span>`
    }).join('')
    return `<div data-src-para="${Number.isInteger(paragraph.srcPara) ? paragraph.srcPara : pi}" style="text-align:${paragraph.align ?? ''}">${runs || '<br>'}</div>`
  }).join('')
}

export function extractMasterRichText(root: HTMLElement): MasterRichParagraph[] {
  const paras = Array.from(root.children).filter((node): node is HTMLElement => node instanceof HTMLElement)
  const source = paras.length ? paras : [root]
  return source.map((para, pi) => {
    const runs: MasterRichRun[] = []
    const walk = (node: Node, inherited: Omit<MasterRichRun, 'text' | 'srcRun'>, srcRun?: number) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const text = node.textContent ?? ''
        if (text) runs.push({ text, ...inherited, ...(srcRun === undefined ? {} : { srcRun }) })
        return
      }
      if (!(node instanceof HTMLElement)) return
      const style = node.style
      const tag = node.tagName.toLowerCase()
      const weight = Number(style.fontWeight)
      const decorations = `${style.textDecorationLine} ${style.textDecoration}`
      const marks = {
        bold: inherited.bold || tag === 'b' || tag === 'strong' || style.fontWeight === 'bold' || weight >= 600,
        italic: inherited.italic || tag === 'i' || tag === 'em' || style.fontStyle === 'italic',
        underline: inherited.underline || tag === 'u' || decorations.includes('underline'),
        strike: inherited.strike || tag === 's' || tag === 'strike' || decorations.includes('line-through'),
        ...(node.dataset.fontSize ? { fontSize: Number(node.dataset.fontSize) } : inherited.fontSize !== undefined ? { fontSize: inherited.fontSize } : {}),
        ...(node.dataset.fontFamily ? { fontFamily: node.dataset.fontFamily } : inherited.fontFamily ? { fontFamily: inherited.fontFamily } : {}),
        ...(node.dataset.color ? { color: node.dataset.color } : inherited.color ? { color: inherited.color } : {}),
      }
      const ownSrc = node.dataset.srcRun === undefined ? srcRun : Number(node.dataset.srcRun)
      node.childNodes.forEach(child => walk(child, marks, ownSrc))
    }
    para.childNodes.forEach(node => walk(node, { bold: false, italic: false, underline: false, strike: false }))
    const alignment = align(para.style.textAlign)
    return { runs: coalesce(runs), ...(para.dataset.srcPara !== undefined && /^\d+$/.test(para.dataset.srcPara) ? { srcPara: Number(para.dataset.srcPara) } : { srcPara: pi }), ...(alignment ? { align: alignment } : {}) }
  })
}

function coalesce(runs: MasterRichRun[]): MasterRichRun[] {
  return runs.reduce<MasterRichRun[]>((out, run) => {
    const previous = out.at(-1)
    if (previous && previous.srcRun === run.srcRun && previous.bold === run.bold && previous.italic === run.italic && previous.underline === run.underline && previous.strike === run.strike && previous.fontSize === run.fontSize && previous.fontFamily === run.fontFamily && previous.color === run.color) previous.text += run.text
    else out.push(run)
    return out
  }, [])
}

function escapeHtml(value: string) { return value.replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]!) }
function escapeAttr(value: string) { return escapeHtml(value) }
function safeCss(value: string) { return value.replace(/[;{}<>"']/g, '') }
function align(value: string): MasterRichParagraph['align'] { return value === 'left' || value === 'center' || value === 'right' || value === 'justify' ? value : undefined }
