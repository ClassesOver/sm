import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { docxOperations, type DocxAnchor } from './docx-operations'
import { projectDocxParagraphProperties } from './docx-paragraph-properties'
import { projectDocxTableCellParagraphProperties } from './docx-table-cell-paragraph-properties'
import { DOCX_PARAGRAPH_FLAGS, type DocxParagraphProperties } from '../../../reporting/doc_engine/bridge/docx-paragraph-properties'
import { createModal } from './modal'
import { buttonClasses } from './button'
import './docx-paragraph-dialog.css'

function targets(editor: Editor, anchors: DocxAnchor[]) {
  const { $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1) {
    if ($from.depth !== $to.depth) return []
    const paragraphDepth = $from.depth
    if (!['docParagraph', 'docHeading', 'docListItem'].includes($from.parent.type.name)) return []
    let tableDepth = -1, cellDepth = -1
    for (let depth = paragraphDepth - 1; depth > 0; depth--) {
      if (cellDepth < 0 && ['docTableCell', 'docTableHeader'].includes($from.node(depth).type.name)) cellDepth = depth
      if ($from.node(depth).type.name === 'docTable') { tableDepth = depth; break }
    }
    if (tableDepth < 0 || cellDepth < 0 || $from.node(cellDepth) !== $to.node(cellDepth) || $from.node(tableDepth) !== $to.node(tableDepth)) return []
    const tablePos = $from.before(tableDepth), row = $from.index(tableDepth), column = $from.index(tableDepth + 1), paragraphIndex = $from.index(cellDepth)
    const tableNode = editor.state.doc.nodeAt(tablePos), matches = anchors.filter(anchor => anchor.docxIndex === tableNode?.attrs.docxIndex)
    const anchor = matches[0], cell = anchor?.cells?.[row]?.[column], paragraph = cell?.paragraphs?.find(item => item.index === paragraphIndex)
    if (!tableNode || tableNode.type.name !== 'docTable' || matches.length !== 1 || !anchor?.editable || !cell?.editable || !paragraph?.editable) return []
    const result = []
    const cellNode = $from.node(cellDepth), cellStart = $from.start(cellDepth)
    for (let index = paragraphIndex, offset = 0; index <= $to.index(cellDepth); index++) {
      const node = cellNode.child(index)
      const identity = cell.paragraphs?.find(item => item.index === index)
      if (!identity?.editable || !['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name)) return []
      if (index === paragraphIndex) for (let before = 0; before < index; before++) offset += cellNode.child(before).nodeSize
      result.push({ node, pos: cellStart + offset, anchor, tablePos, tableNode, row, column, paragraphIndex: index })
      offset += node.nodeSize
    }
    return result
  }
  const result: { node: typeof $from.parent; pos: number; anchor: DocxAnchor; tablePos?: number; tableNode?: typeof $from.parent; row?: number; column?: number; paragraphIndex?: number }[] = []
  editor.state.doc.forEach((node, pos, index) => {
    if (index < $from.index(0) || index > $to.index(0)) return
    const matches = anchors.filter(a => a.docxIndex === node.attrs.docxIndex)
    if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || matches.length !== 1 || !matches[0]!.editable || matches[0]!.paragraphPropertiesEditable === false || matches[0]!.paragraphLayoutEditable === false) return
    result.push({ node, pos, anchor: matches[0]! })
  })
  return result.length === $to.index(0) - $from.index(0) + 1 ? result : []
}
export function docxParagraphDialogUnavailable(editor: Editor, anchors: DocxAnchor[]) {
  return !editor.isEditable || !targets(editor, anchors).length ? '请选择连续的可信原有正文、标题或列表段落' : null
}
const flagLabels = ['孤行控制', '与下段同页', '段中不分页', '取消行号', '段前分页', '同样式段落间不添加间距']
let paragraphDialogCount = 0
/** 固定源 ParagraphDialog 的双页签字段；只将明确改变的值提交原生段落意图。 */
export function openDocxParagraphDialog(root: HTMLElement, editor: Editor, anchors: DocxAnchor[]) {
  const selected = targets(editor, anchors)
  if (!selected.length || !editor.isEditable) throw new Error(docxParagraphDialogUnavailable(editor, anchors)!)
  const doc = editor.state.doc, selection = editor.state.selection
  const sourceIdentity = JSON.stringify(anchors)
  const tabId = `docx-paragraph-settings-${++paragraphDialogCount}`
  const modal = createModal({ root, label: '段落设置', cardClass: 'docx-settings-dialog docx-paragraph-dialog', closeLabel: '关闭段落设置', onRequestClose: () => modal.remove(), content: `
    <h2>段落</h2><div role="tablist" aria-label="段落设置页签"><button type="button" role="tab" id="${tabId}-indents-tab" aria-controls="${tabId}-indents-panel" data-tab="indents" aria-selected="true" tabindex="0">缩进和间距</button><button type="button" role="tab" id="${tabId}-pagination-tab" aria-controls="${tabId}-pagination-panel" data-tab="pagination" aria-selected="false" tabindex="-1">换行和分页</button></div>
    <form novalidate><div role="tabpanel" id="${tabId}-indents-panel" aria-labelledby="${tabId}-indents-tab" data-panel="indents">
    <label>对齐方式<select aria-label="段落对齐"><option value="">混合（保持原样）</option><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option><option value="justify">两端对齐</option></select></label>
    <label>大纲级别<select aria-label="大纲级别"><option value="">混合（保持原样）</option><option value="0">正文文本</option>${Array.from({ length: 9 }, (_, i) => `<option value="${i + 1}">${i + 1} 级</option>`).join('')}</select></label>
    ${[['indentLeft','左缩进'],['indentRight','右缩进'],['spaceBefore','段前间距'],['spaceAfter','段后间距']].map(([key,label]) => `<label>${label}（pt）<input type="number" step="0.05" data-field="${key}" aria-label="${label}（pt）"></label>`).join('')}
    <label>特殊缩进<select aria-label="特殊缩进类型"><option value="">混合（保持原样）</option><option value="none">无</option><option value="firstLine">首行</option><option value="hanging">悬挂</option></select></label>
    <label>单位<select aria-label="特殊缩进单位"><option value="">混合（保持原样）</option><option value="pt">pt</option><option value="chars">字符</option></select></label><label>缩进值<input type="number" step="0.05" aria-label="特殊缩进值"></label>
    <label>行距<select aria-label="段落行距类型"><option value="">混合（保持原样）</option><option value="single">单倍</option><option value="oneHalf">1.5 倍</option><option value="double">双倍</option><option value="atLeast">最小值</option><option value="exact">固定值</option><option value="multiple">多倍</option></select></label><label>设置值<input type="number" step="0.01" aria-label="段落行距倍数"></label>
    </div><div role="tabpanel" id="${tabId}-pagination-panel" aria-labelledby="${tabId}-pagination-tab" data-panel="pagination" hidden>${DOCX_PARAGRAPH_FLAGS.map((key,i) => `<label><input type="checkbox" data-paragraph-flag="${key}" aria-label="${flagLabels[i]}">${flagLabels[i]}</label>`).join('')}</div>
    <p>空白或混合字段保持各段原样。缩进精度 0.05 pt；段前后间距不超过 1584 pt。</p><p role="alert"></p><button type="button" data-paragraph-cancel class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const field = (name: string) => modal.card.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${name}"]`)!
  const common = (read: (item: typeof selected[number]) => unknown) => { const values = selected.map(read); return values.every(v => v === values[0]) ? values[0] : undefined }
  field('段落对齐').value = String(common(({ node }) => node.attrs.align ?? (node.attrs.bidi === true ? 'right' : 'left')) ?? '')
  const outline = field('大纲级别'); outline.value = String(common(({ node }) => node.type.name === 'docHeading' ? node.attrs.level : 0) ?? '')
  outline.disabled = selected.some(({ node }) => node.type.name === 'docListItem' || node.type.name === 'docHeading' && node.attrs.outlineOnly !== true)
  if (outline.disabled) outline.title = '列表或样式标题的大纲级别由来源定义'
  for (const input of modal.card.querySelectorAll<HTMLInputElement>('[data-field]')) { const v = common(({ node }) => Number(node.attrs[input.dataset.field!] ?? 0)); input.value = v === undefined ? '' : String(Number(v) / 20) }
  const kind = field('特殊缩进类型'), unit = field('特殊缩进单位'), by = field('特殊缩进值')
  kind.value = String(common(({ node }) => Number(node.attrs.indentFirstLineChars) > 0 || Number(node.attrs.indentFirstLine) > 0 ? 'firstLine' : Number(node.attrs.indentFirstLine) < 0 ? 'hanging' : 'none') ?? '')
  const characterUnit = common(({ node }) => Number(node.attrs.indentFirstLineChars) > 0)
  unit.value = characterUnit === undefined ? '' : characterUnit ? 'chars' : 'pt'
  const special = !unit.value ? undefined : common(({ node }) => unit.value === 'chars' ? Number(node.attrs.indentFirstLineChars) / 100 : Math.abs(Number(node.attrs.indentFirstLine) || 0) / 20)
  by.value = special === undefined ? '' : String(special)
  const lineKind = field('段落行距类型'), lineBy = field('段落行距倍数')
  lineKind.value = String(common(({ node }) => ['exact','atLeast'].includes(node.attrs.lineRule) ? node.attrs.lineRule : Number(node.attrs.lineSpacing ?? 1) === 1 ? 'single' : Number(node.attrs.lineSpacing) === 1.5 ? 'oneHalf' : Number(node.attrs.lineSpacing) === 2 ? 'double' : 'multiple') ?? '')
  const line = common(({ node }) => ['exact','atLeast'].includes(node.attrs.lineRule) ? Number(node.attrs.lineRawTwips) / 20 : Number(node.attrs.lineSpacing ?? 1)); lineBy.value = line === undefined ? '' : String(line)
  const syncLine = () => { lineBy.disabled = !['multiple','exact','atLeast'].includes(lineKind.value); lineBy.setAttribute('aria-label', ['exact','atLeast'].includes(lineKind.value) ? '段落行距（pt）' : '段落行距倍数') }
  lineKind.addEventListener('change', () => { lineBy.value = lineKind.value === 'multiple' ? '1' : ['exact','atLeast'].includes(lineKind.value) ? '12' : ''; syncLine() }); syncLine()
  const syncSpecial = () => { by.disabled = !kind.value || kind.value === 'none'; unit.disabled = kind.value !== 'firstLine' }
  kind.addEventListener('change', () => { if (kind.value !== 'firstLine') unit.value = 'pt'; syncSpecial() }); syncSpecial()
  const storage = editor.storage.listNumbering
  for (const flag of modal.card.querySelectorAll<HTMLInputElement>('[data-paragraph-flag]')) {
    const key = flag.dataset.paragraphFlag! as typeof DOCX_PARAGRAPH_FLAGS[number], value = common(({ node }) => {
      if (typeof node.attrs[key] === 'boolean' && (key !== 'pageBreakBefore' || node.attrs[key])) return node.attrs[key]
      const styles = storage?.styles, style = styles?.get(String(node.attrs.styleId ?? '')) ?? [...(styles?.values() ?? [])].find(s => s.type === 'paragraph' && s.isDefault)
      return style?.display?.[key] ?? key === 'widowControl'
    })
    flag.checked = value === true; flag.indeterminate = value === undefined
    flag.addEventListener('change', () => { flag.indeterminate = false; flag.dataset.touched = 'true' })
  }
  const controls = [...modal.card.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input,select')]
  const initial = new Map(controls.map(input => [input, input.type === 'checkbox' ? String((input as HTMLInputElement).checked) : input.value]))
  const changed = (input: HTMLInputElement | HTMLSelectElement) => initial.get(input) !== (input.type === 'checkbox' ? String((input as HTMLInputElement).checked) : input.value) || input.dataset.touched === 'true'
  const tabs = [...modal.card.querySelectorAll<HTMLButtonElement>('[data-tab]')]
  const selectTab = (tab: HTMLButtonElement) => {
    for (const item of tabs) { item.setAttribute('aria-selected', String(item === tab)); item.tabIndex = item === tab ? 0 : -1 }
    for (const panel of modal.card.querySelectorAll<HTMLElement>('[data-panel]')) panel.hidden = panel.dataset.panel !== tab.dataset.tab
  }
  for (const tab of tabs) {
    tab.addEventListener('click', () => selectTab(tab))
    tab.addEventListener('keydown', event => {
      if (event.isComposing || event.keyCode === 229 || event.defaultPrevented || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const index = tabs.indexOf(tab), next = event.key === 'Home' ? tabs[0]! : event.key === 'End' ? tabs.at(-1)!
        : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]!
      selectTab(next); next.focus()
    })
  }
  modal.card.querySelector('[data-paragraph-cancel]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (JSON.stringify(anchors) !== sourceIdentity || editor.isDestroyed || !editor.isEditable || editor.state.doc !== doc || !editor.state.selection.eq(selection)) throw new Error('文档或选区已变化，请重新打开段落设置')
      const values: DocxParagraphProperties = {}
      const twips = (input: HTMLInputElement | HTMLSelectElement) => { const n = Number(input.value) * 20; if (!input.value.trim() || !Number.isFinite(n) || Math.abs(n - Math.round(n)) > 1e-7) throw new Error('长度须为有效数值，精度 0.05 pt'); return Math.round(n) }
      if (changed(field('段落对齐')) && field('段落对齐').value) values.align = field('段落对齐').value
      if (!outline.disabled && changed(outline) && outline.value) values.outlineLevel = Number(outline.value)
      for (const input of modal.card.querySelectorAll<HTMLInputElement>('[data-field]')) if (changed(input) && input.value.trim()) values[input.dataset.field!] = twips(input)
      for (const flag of modal.card.querySelectorAll<HTMLInputElement>('[data-paragraph-flag]')) if (changed(flag) && !flag.indeterminate) values[flag.dataset.paragraphFlag!] = flag.checked
      if ([kind,unit,by].some(changed) && kind.value) {
        if (!['none','firstLine','hanging'].includes(kind.value) || !['pt','chars'].includes(unit.value)) throw new Error('特殊缩进类型或单位无效')
        const number = Number(by.value)
        if (kind.value === 'none') values.indentFirstLine = 0
        else if (!by.value.trim() || number <= 0) throw new Error('特殊缩进须为正数')
        else if (unit.value === 'chars' && kind.value === 'firstLine') {
          const chars = number * 100
          if (!Number.isSafeInteger(chars)) throw new Error('字符缩进精度为 0.01 字符')
          values.indentFirstLineChars = chars
          const node = selected[0]!.node, first = node.content.content.find(n => n.isText), mark = first?.marks.find(m => m.type.name === 'docTextStyle')?.attrs
          const size = Number(mark?.sizeHalfPoints) || storage?.styles?.get(String(node.attrs.styleId ?? ''))?.display?.sizeHalfPoints || storage?.docDefaults?.sizeHalfPoints || 24
          values.indentFirstLine = Math.round(number * size * 10)
        } else values.indentFirstLine = twips(by) * (kind.value === 'hanging' ? -1 : 1)
      }
      if ([lineKind,lineBy].some(changed) && lineKind.value) {
        if (['exact','atLeast'].includes(lineKind.value)) { values.lineRule = lineKind.value; values.lineRawTwips = twips(lineBy) }
        else if (['single','oneHalf','double','multiple'].includes(lineKind.value)) values.lineSpacing = lineKind.value === 'single' ? 1 : lineKind.value === 'oneHalf' ? 1.5 : lineKind.value === 'double' ? 2 : Number(lineBy.value)
        else throw new Error('行距类型无效')
      }
      if (!Object.keys(values).length) { modal.remove(); return }
      const tr = closeHistory(editor.state.tr)
      for (const target of selected) {
        if (target.tableNode && target.tablePos !== undefined && target.row !== undefined && target.column !== undefined && target.paragraphIndex !== undefined) {
          const table = tr.doc.nodeAt(target.tablePos)!.toJSON()
          const projectedTable = projectDocxTableCellParagraphProperties(table, target.anchor, target.row, target.column, target.paragraphIndex, values, editor.schema)
          const paragraph = projectedTable.content![target.row]!.content![target.column]!.content![target.paragraphIndex]!
          tr.setNodeMarkup(target.pos, editor.schema.nodes[paragraph.type], paragraph.attrs)
          tr.setNodeMarkup(target.tablePos, editor.schema.nodes[projectedTable.type], projectedTable.attrs)
        } else {
          const projected = projectDocxParagraphProperties(target.node.toJSON(), target.anchor, values, editor.schema)
          tr.setNodeMarkup(target.pos, editor.schema.nodes[projected.type], projected.attrs)
        }
      }
      docxOperations(doc.toJSON(), tr.doc.toJSON(), anchors, undefined, editor.schema)
      editor.view.dispatch(tr)
      if (editor.state.doc === doc) throw new Error('现有修改不能与段落设置组合，请先保存后重新打开')
      editor.view.dispatch(closeHistory(editor.state.tr)); modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(field('段落对齐'))
  return modal.remove
}
