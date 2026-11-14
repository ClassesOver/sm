import type { Editor } from '@tiptap/core'
import type { Node } from '@tiptap/pm/model'
import type { DocxAnchor } from './docx-operations'
import type { StyleMap } from './docx-style-gallery'
import { applyStylesPaneAction } from './docx-styles-pane-operations'
import { applyDocxClearFormatting } from './docx-clear-formatting'

const contexts = new WeakMap<Editor, { anchors: DocxAnchor[]; source: StyleMap; onError: (error: unknown) => void }>()
export function registerStylesPaneContext(editor: Editor, context: NonNullable<ReturnType<typeof contexts.get>>) { contexts.set(editor, context); return () => contexts.delete(editor) }
export interface RibbonFormatState {
  doc: Node; sub: Editor | null; charStyleId: string | null; paraStyleId: string | null; headingLevel: number | null
  fontLatin: string | null; fontEastAsia: string | null; fontSizePt: number | null; textColor: string | null; bold: boolean; italic: boolean
}
export function activeParaAttrs(editor: Editor): Record<string, any> {
  return editor.getAttributes(editor.isActive('docHeading') ? 'docHeading' : editor.isActive('docListItem') ? 'docListItem' : 'docParagraph')
}
export function stylesPaneFormatState(editor: Editor, styles: StyleMap): RibbonFormatState {
  const p = activeParaAttrs(editor), mark = editor.getAttributes('docTextStyle')
  const para = styles.get(p.styleId ?? [...styles.values()].find(style => style.type === 'paragraph' && style.isDefault)?.styleId ?? ''), char = styles.get(mark.styleId ?? '')
  const pd = para?.display ?? {}, cd = char?.display ?? {}, value = (key: string) => mark[key] ?? (cd as Record<string, any>)[key] ?? (pd as Record<string, any>)[key] ?? null
  return { doc: editor.state.doc, sub: null, charStyleId: mark.styleId ?? null, paraStyleId: p.styleId ?? null, headingLevel: editor.isActive('docHeading') ? p.level ?? null : null,
    fontLatin: value('fontAscii') ?? value('font'), fontEastAsia: value('eastAsiaFont'), fontSizePt: value('sizeHalfPoints') === null ? null : value('sizeHalfPoints') / 2,
    textColor: value('color'), bold: editor.isActive('bold'), italic: editor.isActive('italic') }
}
export function applyParagraphStyleId(editor: Editor, styleId: string | null, _headingLevel: number | null) {
  const context = contexts.get(editor); if (!context || !styleId) return
  try { applyStylesPaneAction(editor, styleId, 'paragraph', context.anchors, context.source) } catch (error) { context.onError(error) }
}
export function applyGalleryStyle(editor: Editor, sub: Editor | null, info: { styleId: string; name: string; type: string }, _styles: StyleMap | undefined, activeCharStyleId: string | null) {
  const context = contexts.get(editor); if (!context || sub) return
  try { applyStylesPaneAction(editor, info.styleId, info.type === 'character' ? 'character' : 'paragraph', context.anchors, context.source, info.type === 'character' && activeCharStyleId === info.styleId) } catch (error) { context.onError(error) }
}
export function clearAllFormatting(editor: Editor, sub: Editor | null, _styles: StyleMap) {
  const context = contexts.get(editor); if (!context || sub) return
  try { applyDocxClearFormatting(editor, true, context.anchors) } catch (error) { context.onError(error) }
}
