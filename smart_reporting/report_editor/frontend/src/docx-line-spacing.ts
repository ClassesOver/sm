import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { docxLineSpacingPatch } from '../../../reporting/doc_engine/bridge/docx-line-spacing'
import { docxOperations, type DocxAnchor } from './docx-operations'
import { createModal } from './modal'
import { buttonClasses } from './button'

function spacingTarget(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1 || $from.before(1) !== $to.before(1)) return null
  const node = $from.node(1), matches = anchors.filter(anchor => anchor.docxIndex === node.attrs.docxIndex)
  if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || matches.length !== 1
    || !matches[0]!.editable || matches[0]!.paragraphLayoutEditable === false) return null
  return { node, pos: $from.before(1) }
}

export function docxLineSpacingUnavailable(editor: Editor, anchors: DocxAnchor[]): string | null {
  return !editor.isEditable || !spacingTarget(editor, anchors) ? '请选择同一可编辑的原有正文段落；表格和跨段选区暂不支持行距选项' : null
}

/** 只开放源 ParagraphDialog 的行距选项，不扩张其他段落属性。 */
export function openDocxLineSpacingDialog(root: HTMLElement, editor: Editor, anchors: DocxAnchor[]) {
  const target = spacingTarget(editor, anchors)
  if (!target || !editor.isEditable) throw new Error(docxLineSpacingUnavailable(editor, anchors)!)
  const doc = editor.state.doc, selection = editor.state.selection
  const modal = createModal({ root, label: '段落行距', cardClass: 'docx-settings-dialog', closeLabel: '关闭段落行距', onRequestClose: () => modal.remove(), content: `
    <h2>段落行距</h2><form novalidate>
      <label>行距类型<select aria-label="行距类型"><option value="multiple">倍数</option><option value="atLeast">最小值</option><option value="exact">固定值</option></select></label>
      <label data-spacing-multiple>倍数<input aria-label="行距倍数" type="number" min="0.06" max="132" step="0.01"></label>
      <label data-spacing-points>行距值（pt）<input aria-label="行距值（pt）" type="number" min="1" max="1584" step="0.05"></label>
      <p>作用于当前正文段落。倍数支持 0.06–132，精度 0.01；固定值和最小值支持 1–1584 pt。</p><p role="alert"></p>
      <button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button>
    </form>` })
  const rule = modal.card.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!
  const multiple = modal.card.querySelector<HTMLInputElement>('[aria-label="行距倍数"]')!
  const points = modal.card.querySelector<HTMLInputElement>('[aria-label="行距值（pt）"]')!
  rule.value = ['exact', 'atLeast'].includes(target.node.attrs.lineRule) ? target.node.attrs.lineRule : 'multiple'
  const currentMultiple = Number(target.node.attrs.lineSpacing) || 1
  multiple.value = String(currentMultiple)
  points.value = String(target.node.attrs.lineRawTwips == null ? 12 : Number(target.node.attrs.lineRawTwips) / 20)
  const initialRule = rule.value
  const initialValue = initialRule === 'multiple' ? multiple.value : points.value
  const sync = () => {
    modal.card.querySelector<HTMLElement>('[data-spacing-multiple]')!.hidden = rule.value !== 'multiple'
    modal.card.querySelector<HTMLElement>('[data-spacing-points]')!.hidden = rule.value === 'multiple'
  }
  rule.addEventListener('change', sync); sync()
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (editor.isDestroyed || !editor.isEditable || editor.state.doc !== doc || !editor.state.selection.eq(selection)) throw new Error('文档或选区已变化，请重新打开行距选项')
      if (rule.value === initialRule && (rule.value === 'multiple' ? multiple.value : points.value) === initialValue) { modal.remove(); return }
      const pt = Number(points.value), twips = Math.round(pt * 20)
      if (rule.value !== 'multiple' && (!points.value.trim() || !Number.isFinite(pt) || pt < 1 || pt > 1584 || Math.abs(pt * 20 - twips) > 1e-7)) throw new Error('行距须为 1–1584 pt，最小单位为 0.05 pt')
      const values = rule.value === 'multiple' ? { lineSpacing: Number(multiple.value) } : { lineRule: rule.value, lineRawTwips: twips }
      const attrs = docxLineSpacingPatch(values)
      if (!attrs) throw new Error(rule.value === 'multiple' ? '行距倍数须为 0.06–132，精度为 0.01' : '请选择支持的行距类型和值')
      const tr = closeHistory(editor.state.tr).setNodeMarkup(target.pos, undefined, { ...target.node.attrs, ...attrs })
      docxOperations(doc.toJSON(), tr.doc.toJSON(), anchors)
      if (!tr.doc.eq(doc)) {
        editor.view.dispatch(tr)
        if (editor.state.doc === doc) throw new Error('此段落的现有修改暂不能与行距组合，请先保存再调整')
        editor.view.dispatch(closeHistory(editor.state.tr))
      }
      modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(rule)
  return modal.remove
}
