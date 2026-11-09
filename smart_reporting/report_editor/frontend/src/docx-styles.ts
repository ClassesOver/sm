import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import type { DocxAnchor } from './docx-operations'

export interface DocxStyleInfo {
  styleId: string; name: string; type: string; basedOn?: string; numPr?: unknown; headingLevel?: number
  headingLevelInherited?: true; headingOutlineOff?: true; isDefault?: boolean; display?: object
}
export function safeParagraphStyle(styles: Map<string, DocxStyleInfo> | Record<string, DocxStyleInfo> | undefined, styleId: unknown): DocxStyleInfo {
  if (typeof styleId !== 'string' || !styleId || styleId.length > 255 || /[\u0000-\u001f\u007f]/.test(styleId)) throw new Error('段落样式标识无效')
  const get = (id: string) => styles instanceof Map ? styles.get(id) : styles?.[id]
  const root = get(styleId)
  if (!root || root.styleId !== styleId || root.type !== 'paragraph') throw new Error('来源文档中不存在此段落样式')
  const seen = new Set<string>()
  let current: DocxStyleInfo | undefined = root
  while (current) {
    if (seen.has(current.styleId)) throw new Error('段落样式继承存在循环')
    seen.add(current.styleId)
    if (current.type !== 'paragraph') throw new Error('段落样式继承类型无效')
    if (current.numPr != null || current.headingLevel != null || current.headingLevelInherited === true || current.headingOutlineOff === true) throw new Error('含编号或大纲语义的段落样式暂不支持')
    // These inherited properties are materialized in PM attributes on import. A pStyle-only
    // change cannot refresh them; ordinary run fonts/colors/size and CSS paragraph props remain usable.
    const display = current.display as Record<string, unknown> | undefined
    if (['bidi', 'rtl', 'tabStops', 'indentChars', 'autoSpaceDE', 'autoSpaceDN', 'wordWrap', 'overflowPunct', 'eastAsiaLang', 'frame', 'dropCap'].some(key => display?.[key] != null)) throw new Error('此段落样式含尚未同步的复杂显示属性')
    if (current.basedOn === undefined) break
    if (!current.basedOn || seen.has(current.basedOn) || !get(current.basedOn)) throw new Error('段落样式继承链不完整')
    current = get(current.basedOn)
  }
  return root
}

export function paragraphStyleTargets(editor: Editor, anchors: DocxAnchor[]) {
  const { from, to, $from } = editor.state.selection
  const targets: { pos: number; node: typeof $from.parent; anchor: DocxAnchor }[] = []
  let unsupported = false
  editor.state.doc.nodesBetween(from, to, (node, pos, parent) => {
    if (parent !== editor.state.doc) return false
    if (from < to && pos + 1 === to && from < pos) return false
    const anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex)
    const count = editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length
    if (node.type.name !== 'docParagraph' || !anchor || !(anchor.paragraphStyleEditable ?? anchor.editable) || count !== 1 || !anchor.blockId || !anchor.expectedObjectSha256) unsupported = true
    else targets.push({ pos, node, anchor })
    return false
  })
  return unsupported ? [] : targets
}

export function createParagraphStyleControl(editor: Editor, editable: boolean, anchors: DocxAnchor[]) {
  const select = document.createElement('select')
  select.className = 'rb-select docx-style-select'
  select.dataset.action = 'paragraph-style'
  select.dataset.editableAction = 'true'
  select.setAttribute('aria-label', '来源段落样式')
  const styles = () => (editor.storage as any).listNumbering?.styles as Map<string, DocxStyleInfo> | undefined
  let captured: { doc: typeof editor.state.doc; targets: ReturnType<typeof paragraphStyleTargets> } | undefined
  const sync = () => {
    const catalog = styles(), targets = paragraphStyleTargets(editor, anchors)
    const ids = targets.map(({ node }) => node.attrs.styleId ?? '')
    const mixed = ids.some(id => id !== ids[0])
    const value = mixed ? '__mixed__' : ids[0] ?? ''
    const state = mixed ? '混合样式' : value === '' ? '继承默认段落样式（未指定）' : undefined
    select.replaceChildren()
    if (state || !catalog?.has(value)) {
      const option = new Option(state ?? `当前：${value}`, value); option.disabled = true; select.add(option)
    }
    for (const style of catalog?.values() ?? []) {
      if (style.type !== 'paragraph') continue
      const option = new Option(`${style.name} (${style.styleId})`, style.styleId)
      try { safeParagraphStyle(catalog, style.styleId) } catch (error) { option.disabled = true; option.text += ` — ${String((error as Error).message)}` }
      select.add(option)
    }
    select.value = value
    select.dataset.styleState = mixed ? 'mixed' : value ? 'explicit' : 'inherited'
    let reason = targets.length ? '' : '请选择已有可编辑的普通正文段落'
    for (const { node } of targets) {
      const sourceId = node.attrs.styleId ?? [...(catalog?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      try { if (sourceId != null) safeParagraphStyle(catalog, sourceId) } catch (error) { reason = (error as Error).message }
    }
    select.disabled = !editable || !editor.isEditable || !!reason || !catalog?.size
    select.title = reason || '应用来源文档已有样式；保留直接格式。修改样式后请先保存，再修改同段文字或其他格式。'
  }
  select.addEventListener('focus', () => { captured = { doc: editor.state.doc, targets: paragraphStyleTargets(editor, anchors).map(target => ({ ...target, anchor: { ...target.anchor } })) } })
  select.addEventListener('change', () => {
    const saved = captured ?? { doc: editor.state.doc, targets: paragraphStyleTargets(editor, anchors) }
    const styleId = select.value
    try {
      safeParagraphStyle(styles(), styleId)
      if (!editable || !editor.isEditable || select.disabled || !saved.targets.length || saved.doc !== editor.state.doc) return
      if (!saved.targets.every(({ pos, node, anchor }) => {
        const current = anchors.find(item => item.docxIndex === anchor.docxIndex)
        return editor.state.doc.nodeAt(pos) === node && (current?.paragraphStyleEditable ?? current?.editable)
          && current?.blockId === anchor.blockId && current.expectedObjectSha256 === anchor.expectedObjectSha256
      })) return
      const tr = closeHistory(editor.state.tr)
      for (const { pos, node } of saved.targets) if (node.attrs.styleId !== styleId) tr.setNodeMarkup(pos, undefined, { ...node.attrs, styleId })
      if (tr.docChanged) editor.view.dispatch(tr)
    } catch {
      // A stale/forged option cannot become a draft operation.
    } finally {
      sync()
      captured = document.activeElement === select ? { doc: editor.state.doc, targets: paragraphStyleTargets(editor, anchors).map(target => ({ ...target, anchor: { ...target.anchor } })) } : undefined
    }
  })
  select.addEventListener('blur', () => { captured = undefined; sync() })
  select.addEventListener('keydown', event => { if (event.key === 'Escape') { captured = undefined; select.blur(); editor.commands.focus() } })
  editor.on('transaction', sync); editor.on('selectionUpdate', sync)
  editor.on('destroy', () => { editor.off('transaction', sync); editor.off('selectionUpdate', sync) })
  sync()
  return select
}
