import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { highlightTarget } from './docx-highlight'

// GenOffice f8c17004 ribbon-color-palette.tsx THEME_COLORS + STANDARD_COLORS;
// the paragraph shading split button opens this shared picker with a no-color entry.
export const DOCX_SHADING_COLORS = [
  'FFFFFF', '000000', 'E7E6E6', '0E2841', '156082', 'E97132', '196B24', '0F9ED5', 'A02B93', '4EA72E',
  'C00000', 'FF0000', 'FFC000', 'FFFF00', '92D050', '00B050', '00B0F0', '0070C0', '002060', '7030A0',
] as const

/** fill: 6-hex direct shading; clear: explicit auto cancels inherited style shading; null fill removes the direct shd. */
export function safeDocxShading(value: unknown): { fill: string | null; clear: boolean } {
  if (typeof value !== 'string') throw new Error('段落底纹颜色无效；仅支持六位十六进制 RGB、auto 或 none')
  const normalized = value.toLowerCase()
  if (normalized === 'auto') return { fill: null, clear: true }
  if (normalized === 'none') return { fill: null, clear: false }
  if (!/^[0-9a-f]{6}$/.test(normalized)) throw new Error('段落底纹颜色无效；仅支持六位十六进制 RGB、auto 或 none')
  return { fill: normalized, clear: false }
}

export function paragraphShading(node: { attrs?: Record<string, unknown> | null }): string | null | undefined {
  const fill = node.attrs?.shadingFill
  if (typeof fill === 'string') return fill
  if (node.attrs?.shadingClear === true) return 'auto'
  if (fill === null) return node.attrs?.shadingClear === false || node.attrs?.shadingClear === null || node.attrs?.shadingClear === undefined ? 'none' : undefined
  return undefined
}

/** 来源独立能力可允许notes引用；不提升普通正文editable，重复锚点和未知inline仍由target拒绝。 */
export function paragraphShadingTarget(editor: Editor, anchors: Parameters<typeof highlightTarget>[1]) {
  return highlightTarget(editor, anchors.map(anchor => ({ ...anchor, editable: anchor.paragraphShadingEditable ?? anchor.editable })), true)
}
export function applyParagraphShading(editor: Editor, anchors: Parameters<typeof highlightTarget>[1], value: unknown) {
  const shading = safeDocxShading(value)
  const target = paragraphShadingTarget(editor, anchors)
  if (!editor.isEditable || !target) return false
  const attrs = target.node.attrs
  const next = { ...attrs, shadingFill: shading.fill, shadingClear: shading.clear ? true : null }
  editor.view.dispatch(closeHistory(editor.state.tr.setNodeMarkup(target.from - 1, undefined, next)))
  editor.commands.focus()
  return true
}
