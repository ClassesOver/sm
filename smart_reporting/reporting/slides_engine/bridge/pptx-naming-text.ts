import { placeholderSource } from '@genoffice/agent-core/redact-core'
import type { GlyphRun, RenderNode, RenderSlide, ShapeRenderNode, TextLine } from '@genoffice/pptx-render'

// GenOffice slides renderer: ai/redact-view.ts and file-naming.ts.
/** A run as the model may see it. */
function runTextForModel(run: GlyphRun, forDisplay = false): string {
  if (!forDisplay && run.redact) return placeholderSource(run.redact)
  return run.text
}

/** One laid-out line, joined. */
function lineTextForModel(line: TextLine, forDisplay = false): string {
  return line.runs.map((r) => runTextForModel(r, forDisplay)).join('')
}

const isTextNode = (n: RenderNode): n is ShapeRenderNode => n.type === 'shape' || n.type === 'text'

/** The `lines` of a shape, or of one table cell. */
function linesOf(node: { text?: { lines?: TextLine[] } }): TextLine[] {
  return node.text?.lines ?? []
}

/**
 * A shape's text, tab-separated cells for a table — the same shape the existing
 * `nodeText` produced, with withheld runs swapped for their markers.
 */
function textForModel(node: RenderNode, forDisplay = false): string {
  if (node.type === 'picture') {
    // a withheld picture reads as its marker so the model can see something is
    // there and write around it. The reader's own view stays empty: a picture
    // has no text, and inventing one for their card would be a lie.
    return !forDisplay && node.redact ? placeholderSource(node.redact) : ''
  }
  if (isTextNode(node)) {
    return linesOf(node)
      .map((line) => lineTextForModel(line, forDisplay))
      .join('\n')
  }
  if (node.type === 'table') {
    // row by row so the model can read table content; a cell's runs get the
    // same treatment as a shape's
    const byRow = new Map<number, string[]>()
    for (const cell of node.cells) {
      const text = linesOf(cell)
        .map((line) => lineTextForModel(line, forDisplay))
        .join(' ')
      const row = byRow.get(cell.y) ?? []
      row.push(text)
      byRow.set(cell.y, row)
    }
    return [...byRow.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([, r]) => r.join('\t'))
      .join('\n')
  }
  return ''
}

export function modelTextOfDeck(slides: readonly RenderSlide[]): string {
  const blocks: string[] = []
  let hasText = false
  for (const [index, slide] of slides.entries()) {
    const text = slide.nodes
      .map((node) => textForModel(node))
      .filter((line) => line.trim())
      .join('\n')
    hasText ||= Boolean(text)
    blocks.push(`## Slide ${index + 1}\n${text}`)
  }
  return hasText ? blocks.join('\n\n') : ''
}

export function excerptForNaming(content: string, limit = 4000): string {
  const collapsed = content.replace(/\n{3,}/g, '\n\n').trim()
  if (collapsed.length <= limit) return collapsed
  return `${collapsed.slice(0, limit)}\n…`
}
