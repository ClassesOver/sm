import { docxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import type { DocxNotesModel } from './docx-notes'

export const NOTE_PARAGRAPH_LAYOUT_KINDS = new Set(['setParagraphAlignment', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphSpacing'])

/** 无正文投影复用属性校验；notes段落的两项装饰能力来自已核验的独立来源。 */
export function noteParagraphLayout(source: DocxPmNode, current: DocxPmNode, anchor: DocxAnchor, model: DocxNotesModel) {
  const eligible = model.referenceBlocks?.find(block => block.blockId === anchor.blockId && block.expectedObjectSha256 === anchor.expectedObjectSha256)
  if (!(eligible?.editable ?? anchor.editable) || source.type !== current.type || source.attrs?.docxIndex !== anchor.docxIndex || current.attrs?.docxIndex !== anchor.docxIndex) throw new Error('注释段落布局来源身份无效')
  const projection = (node: DocxPmNode): DocxPmNode => ({ type: 'doc', content: [{ ...structuredClone(node), content: [] }] })
  const operations = docxOperations(projection(source), projection(current), [{ ...anchor, editable: true }])
  if (operations.some(op => NOTE_PARAGRAPH_LAYOUT_KINDS.has(op.kind)) && anchor.paragraphLayoutEditable === false) throw new Error('此注释来源段落布局只读')
  if (operations.some(op => !NOTE_PARAGRAPH_LAYOUT_KINDS.has(op.kind)
    && !(op.kind === 'setParagraphShading' && (anchor.paragraphShadingEditable ?? anchor.editable))
    && !(op.kind === 'setParagraphBorders' && (anchor.paragraphBordersEditable ?? anchor.editable)))) throw new Error('注释混编仅支持已核验的段落布局、底纹和边框')
  if (operations.some(op => ['setParagraphShading', 'setParagraphBorders'].includes(op.kind))) {
    let referenceIndex = 0
    for (const child of source.content ?? []) if (child.type === 'docNoteRef') {
      const kind = child.attrs?.kind, id = String(child.attrs?.id)
      const note = kind === 'footnote' || kind === 'endnote' ? model[`${kind}s`].find(note => note.id === id) : undefined
      const index = referenceIndex++
      if (!note?.references.some(ref => ref.blockId === anchor.blockId && ref.expectedObjectSha256 === anchor.expectedObjectSha256 && ref.referenceIndex === index)) throw new Error('段落装饰的注释来源身份无效')
    }
  }
  return { operations, paragraph: { ...structuredClone(current), attrs: structuredClone(source.attrs) } }
}
