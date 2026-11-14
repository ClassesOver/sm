import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { validDocxSpecialIndent } from '../../../reporting/doc_engine/bridge/docx-special-indent'
import { docxOperations, type DocxAnchor } from './docx-operations'
import { createModal } from './modal'
import { buttonClasses } from './button'

function targetParagraph(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1 || !$from.sameParent($to)) return null
  const node = $from.parent, matches = anchors.filter(anchor => anchor.docxIndex === node.attrs.docxIndex)
  if (!['docParagraph', 'docHeading'].includes(node.type.name) || matches.length !== 1
    || !matches[0]!.editable || matches[0]!.paragraphLayoutEditable === false) return null
  return { node, pos: $from.before(1) }
}

export function docxSpecialIndentUnavailable(editor: Editor, anchors: DocxAnchor[]): string | null {
  return !editor.isEditable || !targetParagraph(editor, anchors) ? '请选择同一可信原有正文段落或标题；列表、表格及跨段选区暂不支持特殊缩进' : null
}

/** 源 ParagraphDialog：绝对首行／悬挂，以及首行字符单位。 */
export function openDocxSpecialIndentDialog(root: HTMLElement, editor: Editor, anchors: DocxAnchor[]) {
  const target = targetParagraph(editor, anchors)
  if (!target || !editor.isEditable) throw new Error(docxSpecialIndentUnavailable(editor, anchors)!)
  const doc = editor.state.doc, selection = editor.state.selection
  const modal = createModal({ root, label: '特殊缩进', cardClass: 'docx-settings-dialog', closeLabel: '关闭特殊缩进', onRequestClose: () => modal.remove(), content: `
    <h2>特殊缩进</h2><form novalidate>
      <label>类型<select aria-label="特殊缩进类型"><option value="none">无</option><option value="firstLine">首行</option><option value="hanging">悬挂</option></select></label>
      <label>单位<select aria-label="特殊缩进单位"><option value="pt">pt</option><option value="chars">字符</option></select></label>
      <label><span data-value-label>值（pt）</span><input aria-label="缩进值（pt）" type="number" min="0.05" max="720" step="0.05"></label>
      <p>仅调整当前段落的特殊缩进，保留左右缩进。绝对值支持 0.05–720 pt；首行另支持 0.01–100 字符，换算值不超过 720 pt。</p>
      <p data-character-warning hidden>字符单位将保留为原生首行字符缩进，随字号变化；切换 pt 将转换为绝对缩进，取消保持来源原样。</p>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button>
    </form>` })
  const kind = modal.card.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  const unit = modal.card.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')!
  const points = modal.card.querySelector<HTMLInputElement>('[aria-label="缩进值（pt）"]')!
  const current = Number(target.node.attrs.indentFirstLine) || 0
  const chars = Number(target.node.attrs.indentFirstLineChars) || 0
  kind.value = chars > 0 || current > 0 ? 'firstLine' : current < 0 ? 'hanging' : 'none'
  unit.value = chars > 0 ? 'chars' : 'pt'
  points.value = String(chars > 0 ? chars / 100 : current ? Math.abs(current) / 20 : 36)
  // twips仅为绝对长度后备值；Word以firstLineChars为权威。使用段首run，避免光标后移改变后备值。
  const first = target.node.content.content.find(node => node.isText)
  const mark = first?.marks.find(mark => mark.type.name === 'docTextStyle')?.attrs
  const storage = editor.storage.listNumbering
  const styles = storage?.styles
  const defaultStyle = [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)
  const size = Number(mark?.sizeHalfPoints) || styles?.get(String(mark?.styleId ?? ''))?.display?.sizeHalfPoints
    || (!first ? Number(target.node.attrs.emptyRunSize) : 0)
    || (styles?.get(String(target.node.attrs.styleId ?? '')) ?? defaultStyle)?.display?.sizeHalfPoints
    || storage?.docDefaults?.sizeHalfPoints || 24
  const sync = () => {
    const characters = unit.value === 'chars'
    points.disabled = kind.value === 'none'; unit.disabled = kind.value !== 'firstLine'
    points.setAttribute('aria-label', characters ? '缩进值（字符）' : '缩进值（pt）')
    points.min = characters ? '0.01' : '0.05'; points.max = characters ? '100' : '720'; points.step = characters ? '0.01' : '0.05'
    modal.card.querySelector('[data-value-label]')!.textContent = characters ? '值（字符）' : '值（pt）'
    modal.card.querySelector<HTMLElement>('[data-character-warning]')!.hidden = !characters
  }
  kind.addEventListener('change', () => {
    if (kind.value !== 'firstLine' && unit.value === 'chars') { unit.value = 'pt'; points.value = '36' }
    sync()
  })
  unit.addEventListener('change', () => { points.value = unit.value === 'chars' ? '2' : '36'; sync() }); sync()
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (editor.isDestroyed || !editor.isEditable || editor.state.doc !== doc || !editor.state.selection.eq(selection)) throw new Error('文档或选区已变化，请重新打开特殊缩进')
      const characters = kind.value === 'firstLine' && unit.value === 'chars'
      const pt = Number(points.value), raw = characters ? Math.round(pt * 100) / 100 * size * 10 : pt * 20
      const firstLineChars = characters ? Math.round(pt * 100) : undefined
      const twips = kind.value === 'none' ? 0 : Math.round(raw) * (kind.value === 'hanging' ? -1 : 1)
      if (!['none', 'firstLine', 'hanging'].includes(kind.value) || !['pt', 'chars'].includes(unit.value)
        || !validDocxSpecialIndent(twips, firstLineChars) || kind.value !== 'none' && (!points.value.trim() || !Number.isFinite(pt)
          || (characters ? pt < 0.01 || pt > 100 || Math.abs(pt * 100 - firstLineChars!) > 1e-7
            : pt < 0.05 || pt > 720 || Math.abs(raw - Math.round(raw)) > 1e-7))) throw new Error('特殊缩进须为 0.05–720 pt，精度 0.05 pt；或首行 0.01–100 字符，精度 0.01 字符且换算不超过 720 pt；取消请选择“无”')
      const tr = closeHistory(editor.state.tr).setNodeMarkup(target.pos, undefined, { ...target.node.attrs, indentFirstLine: twips, indentFirstLineChars: firstLineChars ?? null })
      docxOperations(doc.toJSON(), tr.doc.toJSON(), anchors)
      if (!tr.doc.eq(doc)) {
        editor.view.dispatch(tr)
        if (editor.state.doc === doc) throw new Error('现有修改暂不能与特殊缩进组合，请先保存')
        editor.view.dispatch(closeHistory(editor.state.tr))
      }
      modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(kind)
  return modal.remove
}
