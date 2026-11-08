import type { Editor } from '@tiptap/core'
import type { Schema } from '@tiptap/pm/model'
import { TextSelection } from '@tiptap/pm/state'
import { COVER_END_MARK, COVER_PRESETS, COVER_START_MARK, buildCoverNodes, coverPageRange, type CoverPara } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/cover-pages'
import type { DocxPmNode } from './docx-operations'

/**
 * Insert ▸ Cover Page, following GenOffice f8c17004 editor/cover-pages.ts
 * (vendored unmodified): a preset gallery built only from paragraph
 * primitives (alignment, spacing, shading, single-line borders, indents,
 * bold/italic/colour/size), placed at the document start with a trailing
 * page-break paragraph; hidden _GenOfficeCoverPage bookmarks let "Remove
 * Current Cover Page" find it again after save/reopen. Inserting replaces an
 * existing gallery cover.
 *
 * Local save boundary: the first cover paragraph carries the resolved preset
 * paragraph specs as `nativeCoverPage`; the diff re-projects those specs with
 * the texts read back from the paragraphs (so editing the placeholder texts
 * before saving is kept) and the group must match exactly — any other
 * formatting or structural change is refused until the cover is saved. The
 * bridge validates the same bounded spec (COVER_PARA_KEYS) and writes the
 * paragraphs itself; it never receives arbitrary formatting.
 */
export const COVER_PARA_KEYS = ['text', 'bold', 'italic', 'color', 'sizeHalfPoints', 'align', 'spaceBefore', 'spaceAfter', 'shadingFill', 'borders', 'indentLeft', 'indentRight'] as const
export const COVER_PARA_LIMIT = 20
const HEX = /^[0-9A-Fa-f]{6}$/
const int = (value: unknown, min: number, max: number) => Number.isInteger(value) && (value as number) >= min && (value as number) <= max

/** Strict cover paragraph spec shared with the bridge's validation. */
export function coverParaSpecs(value: unknown): CoverPara[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > COVER_PARA_LIMIT) throw new Error('封面段落数量无效')
  return value.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(key => !(COVER_PARA_KEYS as readonly string[]).includes(key))) throw new Error('封面段落字段无效')
    const para = item as Record<string, unknown>
    const ok = (para.text === undefined || (typeof para.text === 'string' && para.text.length <= 2000 && !/[\x00-\x08\x0b-\x1f]/.test(para.text)))
      && (para.bold === undefined || typeof para.bold === 'boolean') && (para.italic === undefined || typeof para.italic === 'boolean')
      && (para.color === undefined || (typeof para.color === 'string' && HEX.test(para.color)))
      && (para.shadingFill === undefined || (typeof para.shadingFill === 'string' && HEX.test(para.shadingFill)))
      && (para.sizeHalfPoints === undefined || int(para.sizeHalfPoints, 2, 400))
      && (para.align === undefined || ['left', 'center', 'right'].includes(para.align as string))
      && (para.spaceBefore === undefined || int(para.spaceBefore, 0, 14400)) && (para.spaceAfter === undefined || int(para.spaceAfter, 0, 14400))
      && (para.indentLeft === undefined || int(para.indentLeft, -31680, 31680)) && (para.indentRight === undefined || int(para.indentRight, -31680, 31680))
      && (para.borders === undefined || (typeof para.borders === 'string' && /^(?!.*(.).*\1)[tblr]{1,4}$/.test(para.borders)))
    if (!ok) throw new Error('封面段落格式无效')
    // 规范键序（COVER_PARA_KEYS），使读回的规格与投影时的规格逐字节一致。
    return Object.fromEntries(COVER_PARA_KEYS.filter(key => para[key] !== undefined).map(key => [key, para[key]])) as CoverPara
  })
}

/** Resolved preset paragraphs (placeholder texts and today's date evaluated now). */
export function coverPresetParas(presetId: string): CoverPara[] {
  const preset = COVER_PRESETS.find(item => item.id === presetId)
  if (!preset) throw new Error('未知的封面样式')
  return coverParaSpecs(preset.paras.map(para => Object.fromEntries(Object.entries(para).filter(([, value]) => value !== undefined))))
}

/** Deterministic editor projection of a cover (fixed-source buildCoverNodes). */
export function projectCoverNodes(paras: CoverPara[], schema: Schema): DocxPmNode[] {
  const specs = coverParaSpecs(paras)
  const nodes = buildCoverNodes({ id: 'native', name: '', paras: specs }).map(node => schema.nodeFromJSON(node).toJSON() as DocxPmNode)
  nodes[0]!.attrs = { ...nodes[0]!.attrs, nativeCoverPage: { paras: specs } }
  return nodes.map(node => schema.nodeFromJSON(node).toJSON() as DocxPmNode)
}

const nodeText = (node: DocxPmNode): string => (node.content ?? []).map(child => child.type === 'text' ? child.text ?? '' : '￼').join('')

/** Read a new cover group back: specs with each paragraph's current text. */
export function coverGroupParas(group: DocxPmNode[]): CoverPara[] {
  const intent = (group[0]?.attrs?.nativeCoverPage as { paras?: unknown } | undefined)?.paras
  const specs = coverParaSpecs(intent)
  if (group.length !== specs.length + 1) throw new Error('封面段落结构已改变')
  return specs.map((spec, index) => {
    const text = nodeText(group[index]!)
    const { text: _placeholder, ...rest } = spec
    return text ? { ...rest, text } : rest
  })
}

/** The first node's `nativeCoverPage` intent only supplies the formatting spec
 *  (it keeps the original placeholder texts); the paragraphs themselves —
 *  content, marks and every other attribute — must equal the projection. */
export function coverGroupMatchesProjection(group: DocxPmNode[], expected: DocxPmNode[]): boolean {
  const strip = (nodes: DocxPmNode[]) => JSON.stringify(nodes.map((node, index) => index === 0 ? { ...node, attrs: { ...node.attrs, nativeCoverPage: null } } : node))
  return group.length === expected.length && strip(group) === strip(expected)
}

export function isCoverEndNode(node: DocxPmNode | undefined): boolean {
  return !!(node?.attrs?.hiddenBookmarks as string[] | null | undefined)?.includes(COVER_END_MARK)
}
export function isCoverStartNode(node: DocxPmNode | undefined): boolean {
  return !!(node?.attrs?.hiddenBookmarks as string[] | null | undefined)?.includes(COVER_START_MARK)
}

export function docxCoverUnavailable(editor: Editor, editable: boolean): string | undefined {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  if (!editor.schema.nodes.docParagraph) return '当前文档结构不支持封面'
  return undefined
}

function dispatchChecked(editor: Editor, tr: import('@tiptap/pm/state').Transaction, failure: string): void {
  const previous = editor.state.doc
  editor.view.dispatch(tr.scrollIntoView())
  if (editor.state.doc === previous) throw new Error(failure)
  editor.view.focus()
}

/** Fixed-source insertCoverPage: replace an existing gallery cover, insert at the document start. */
export function insertDocxCoverPage(editor: Editor, presetId: string): boolean {
  const reason = docxCoverUnavailable(editor, true)
  if (reason) throw new Error(reason)
  const schema = editor.state.schema
  const nodes = projectCoverNodes(coverPresetParas(presetId), schema).map(node => schema.nodeFromJSON(node))
  const tr = editor.state.tr
  const existing = coverPageRange(tr.doc)
  if (existing) tr.delete(existing.from, existing.to)
  tr.insert(0, nodes)
  tr.setSelection(TextSelection.near(tr.doc.resolve(1)))
  dispatchChecked(editor, tr, '封面未插入：原封面含暂不支持删除的内容，请先保存后再替换')
  return true
}

/** Fixed-source removeCoverPage. */
export function removeDocxCoverPage(editor: Editor): boolean {
  const range = coverPageRange(editor.state.doc)
  if (!range) throw new Error('文档中没有可删除的封面')
  const tr = editor.state.tr.delete(range.from, range.to)
  dispatchChecked(editor, tr, '封面未删除：封面中有暂不支持删除的内容')
  return true
}

export const docxHasCoverPage = (editor: Editor): boolean => coverPageRange(editor.state.doc) !== null
export { COVER_PRESETS }
