import type { Editor } from '@tiptap/core'
import type { Node as PmNode, Schema } from '@tiptap/pm/model'
import { TextSelection } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode, type DocxSectionAnchor } from './docx-operations'
import type { NativeOperation } from './native-draft'
import type { DocxStyleInfo } from './docx-styles'
import { compileFind, expandReplacement, findInDoc, matchContext, HIGHLIGHT_CAP, RESULTS_LIST_CAP, type FindMatch, type FindOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/find'
import { searchPluginKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/decoration-extensions'

// Matching/expansion and highlight metadata are reused from pinned GenOffice
// f8c17004fb730df11f0f743164ffd8b4281bb38c. Writes still use the native guard.
export function validateDocxReplacement(baseline: DocxPmNode, candidate: DocxPmNode, anchors: DocxAnchor[], schema: Schema, styles: Map<string, DocxStyleInfo>, section?: DocxSectionAnchor | readonly DocxSectionAnchor[], sectionOperation?: NativeOperation | NativeOperation[]) {
  const operations = docxOperations(baseline, candidate, anchors, sectionOperation, schema, styles)
  for (const operation of operations) if (typeof operation.text === 'string' && (operation.text.length > 20000 || /[\x00-\x08\x0b-\x1f]/.test(operation.text))) throw new Error('替换后文字超出保存协议限制（每对象最多 20000 字符且不含控制字符）')
  const projected = replayDocxOperations(baseline, operations, anchors, section, schema, styles)
  if (!schema.nodeFromJSON(projected).eq(schema.nodeFromJSON(candidate))) throw new Error('替换会改变原有分段或文字格式边界；当前保存协议无法准确保留，请分段或等长替换')
}

export function assertReplaceTarget(doc: PmNode, match: FindMatch, anchors: DocxAnchor[], baseline: DocxPmNode) {
  const from = doc.resolve(match.from), to = doc.resolve(match.to)
  if (from.parent !== to.parent || !from.parent.isTextblock) throw new Error('不支持跨段落替换')
  const top = from.node(1), index = top.attrs.docxIndex
  const anchor = anchors.filter(item => item.docxIndex === index)
  let count = 0
  doc.forEach(node => { if (node.attrs.docxIndex === index) count++ })
  if (index == null || anchor.length !== 1 || count !== 1 || !anchor[0].blockId || !anchor[0].expectedObjectSha256
    || baseline.content?.filter(node => node.attrs?.docxIndex === index).length !== 1) throw new Error('替换需要唯一且有效的来源锚点；新增段落请先保存')
  const source = anchor[0]
  if (top.attrs.nativeTableStructure) throw new Error('表格结构修改后请先保存，再替换文字')
  if (top.type.name === 'docTable') {
    let cellDepth = -1
    for (let depth = from.depth; depth > 1; depth--) if (['docTableCell', 'docTableHeader'].includes(from.node(depth).type.name)) { cellDepth = depth; break }
    if (cellDepth < 0) throw new Error('不支持此表格结构的替换')
    const cell = source.cells?.[from.index(cellDepth - 2)]?.[from.index(cellDepth - 1)]
    if (!cell?.editable || !cell.cellId || !cell.expectedObjectSha256) throw new Error('只读或缺少来源身份的单元格不能替换')
    const cellNode = from.node(cellDepth)
    if (cellNode.childCount !== 1) throw new Error('多段落单元格替换会改变原有分段，暂不支持')
    const runs = cellNode.firstChild?.content.content ?? []
    if (runs.some(run => !run.isText) || runs.some(run => !run.sameMarkup(runs[0]))) throw new Error('含混合文字格式或复杂对象的单元格暂不支持替换')
  } else if (!source.editable || !['docParagraph', 'docHeading', 'docListItem'].includes(top.type.name)) throw new Error('只读或不支持的正文对象不能替换')
  let complex = false, linked = false
  from.parent.forEach(node => { if (!node.isText) complex = true; if (node.marks.some(mark => mark.type.name === 'link')) linked = true })
  if (complex) throw new Error('含换行、域或复杂内联对象的段落暂不支持替换')
  if (linked) throw new Error('含已有链接的段落暂不支持文字替换；请先单独处理链接')
  const boundary = (at: number) => !(at > 0 && at < from.parent.textContent.length && /[\uD800-\uDBFF]/.test(from.parent.textContent[at - 1]) && /[\uDC00-\uDFFF]/.test(from.parent.textContent[at]))
  if (!boundary(from.parentOffset) || !boundary(to.parentOffset)) throw new Error('替换范围不能拆开 Unicode 字符')
}

export function createDocxFindReplace(options: { editor: Editor; root: HTMLElement; anchors: DocxAnchor[]; getBaseline: () => DocxPmNode; getSection: () => DocxSectionAnchor | readonly DocxSectionAnchor[] | undefined; getSectionOperation: () => NativeOperation | NativeOperation[] | undefined; styles: Map<string, DocxStyleInfo>; isLocked: () => boolean }) {
  const { editor, root, anchors, getBaseline, isLocked } = options
  const panel = document.createElement('section')
  panel.className = 'find-panel docx-find-replace'; panel.hidden = true
  panel.setAttribute('role', 'region'); panel.setAttribute('aria-label', '查找和替换')
  panel.innerHTML = '<div class="find-tabs"><button type="button" data-find-tab="find" class="find-tab">查找</button><button type="button" data-find-tab="replace" class="find-tab">替换</button><button type="button" data-find-action="close" aria-label="关闭查找">关闭</button></div><div class="find-row"><input class="find-input" data-find-query aria-label="查找内容"><button type="button" data-find-action="previous" aria-label="上一个匹配">↑</button><button type="button" data-find-action="next" aria-label="下一个匹配">↓</button><span class="find-count" data-find-count></span></div><div class="find-row" data-replace-row><input class="find-input" data-find-replacement aria-label="替换为"><button type="button" data-find-action="replace">替换当前</button><button type="button" data-find-action="replace-all">全部替换</button></div><div class="find-options"><label><input type="checkbox" data-find-option="matchCase">区分大小写</label><label><input type="checkbox" data-find-option="wholeWord">全字匹配</label><label><input type="checkbox" data-find-option="matchWidth">区分全半角</label><select data-find-mode aria-label="查找模式"><option value="literal">普通文字</option><option value="wildcard">Word 通配符</option><option value="regex">正则表达式</option></select></div><p role="status" data-find-status></p><div class="find-results" data-find-results></div><p class="find-results-note">搜索当前正文和表格；受保护对象、页眉页脚不在此搜索范围。段落拆分及复杂结构替换尚未支持。</p>'
  root.append(panel)
  const query = panel.querySelector<HTMLInputElement>('[data-find-query]')!
  const replacement = panel.querySelector<HTMLInputElement>('[data-find-replacement]')!
  const status = panel.querySelector<HTMLElement>('[data-find-status]')!
  const count = panel.querySelector<HTMLElement>('[data-find-count]')!
  const results = panel.querySelector<HTMLElement>('[data-find-results]')!
  let matches: FindMatch[] = [], active = 0, disposed = false, applying = false
  const settings = (): FindOptions => ({ matchCase: panel.querySelector<HTMLInputElement>('[data-find-option="matchCase"]')!.checked,
    wholeWord: panel.querySelector<HTMLInputElement>('[data-find-option="wholeWord"]')!.checked, matchWidth: panel.querySelector<HTMLInputElement>('[data-find-option="matchWidth"]')!.checked,
    mode: panel.querySelector<HTMLSelectElement>('[data-find-mode]')!.value as FindOptions['mode'] })
  const highlight = () => {
    const ranges = matches.length > HIGHLIGHT_CAP ? matches.slice(active, active + 1) : matches
    editor.view.dispatch(editor.state.tr.setMeta(searchPluginKey, { ranges, activeIndex: matches.length > HIGHLIGHT_CAP ? 0 : active }))
  }
  const refreshLock = () => {
    const locked = isLocked() || !editor.isEditable
    for (const button of panel.querySelectorAll<HTMLButtonElement>('[data-find-action="replace"], [data-find-action="replace-all"]')) {
      button.disabled = locked; button.title = locked ? '当前修订只读、已关闭或正在保存，仍可查找和导航' : '替换前检查全部目标；不支持的目标会给出原因'
    }
    replacement.disabled = locked
  }
  const paint = () => {
    count.textContent = matches.length ? `${active + 1}/${matches.length}` : '0/0'
    results.replaceChildren()
    matches.slice(0, RESULTS_LIST_CAP).forEach((match, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = `find-result${index === active ? ' on' : ''}`
      const context = matchContext(match); button.textContent = `${index + 1}. ${context.before}${context.hit}${context.after}`
      button.addEventListener('click', () => navigate(index)); results.append(button)
    })
    if (matches.length > RESULTS_LIST_CAP) { const note = document.createElement('p'); note.textContent = `仅列出前 ${RESULTS_LIST_CAP} 条；可用上一个/下一个导航全部结果`; results.append(note) }
    highlight(); refreshLock()
  }
  const scan = (reset = false) => {
    if (disposed) return
    const opts = settings(), compiled = compileFind(query.value, opts)
    matches = compiled.ok ? findInDoc(editor.state.doc, compiled.query, opts) : []
    if (reset) active = 0
    active = Math.max(0, Math.min(active, matches.length - 1))
    status.textContent = !query.value ? '请输入查找内容' : !compiled.ok ? `查找表达式无效：${compiled.error}` : matches.length ? `找到 ${matches.length} 处` : '未找到匹配内容'
    paint()
  }
  const navigate = (index: number) => {
    if (!matches.length) return
    active = (index + matches.length) % matches.length
    const match = matches[active]
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, match.from, match.to)))
    const { node } = editor.view.domAtPos(match.from)
    ;(node instanceof HTMLElement ? node : node.parentElement)?.scrollIntoView?.({ block: 'center' })
    paint()
  }
  const replace = (all: boolean) => {
    if (isLocked() || !editor.isEditable) { status.textContent = '当前修订只读、已关闭或正在保存，不能替换'; return false }
    scan()
    const selected = all ? matches : matches.slice(active, active + 1)
    if (!selected.length) return false
    try {
      const tr = closeHistory(editor.state.tr)
      for (const match of [...selected].reverse()) {
        assertReplaceTarget(editor.state.doc, match, anchors, getBaseline())
        const segments = expandReplacement(replacement.value, match, settings().mode ?? 'literal')
        if (segments.length !== 1 || /[\r\n\x00-\x08\x0b-\x1f]/.test(segments[0])) throw new Error('段落拆分、换行或控制字符替换尚未接入保存协议')
        tr.insertText(segments[0], match.from, match.to)
      }
      // Validate the entire candidate before the guarded atomic dispatch. Do
      // not applyTransaction twice: append-transaction plugins may have effects.
      if (tr.doc.eq(editor.state.doc)) throw new Error('替换文字与原文字相同，未产生修改')
      validateDocxReplacement(getBaseline(), tr.doc.toJSON(), anchors, editor.schema, options.styles, options.getSection(), options.getSectionOperation())
      const expected = tr.doc
      applying = true
      try { editor.view.dispatch(tr) } finally { applying = false }
      if (!editor.state.doc.eq(expected)) throw new Error('替换被文档写入守卫拒绝，请检查正文提示')
      editor.view.dispatch(closeHistory(editor.state.tr))
      scan(); status.textContent = `已替换 ${selected.length} 处；已写入当前草稿，可撤销`
      return true
    } catch (error) {
      status.textContent = `替换失败：${error instanceof Error ? error.message : String(error)}；本次未替换`
      return false
    }
  }
  const close = () => { panel.hidden = true; editor.view.dispatch(editor.state.tr.setMeta(searchPluginKey, { ranges: [], activeIndex: 0 })); editor.view.focus() }
  const open = (mode: 'find' | 'replace') => {
    panel.hidden = false
    panel.querySelector<HTMLElement>('[data-replace-row]')!.hidden = mode !== 'replace'
    for (const tab of panel.querySelectorAll<HTMLButtonElement>('[data-find-tab]')) tab.classList.toggle('on', tab.dataset.findTab === mode)
    scan(); query.focus(); query.select()
  }
  panel.addEventListener('input', event => { if (event.target !== replacement) scan(true) })
  panel.addEventListener('change', () => scan(true))
  panel.addEventListener('click', event => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button')
    if (!button) return
    if (button.dataset.findTab) open(button.dataset.findTab as 'find' | 'replace')
    switch (button.dataset.findAction) {
      case 'close': close(); break
      case 'next': navigate(active + 1); break
      case 'previous': navigate(active - 1); break
      case 'replace': replace(false); break
      case 'replace-all': replace(true); break
    }
  })
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close() }
    if (event.key === 'Enter' && event.target === query) { event.preventDefault(); navigate(active + (event.shiftKey ? -1 : 1)) }
  })
  const shortcut = (event: KeyboardEvent) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || !['f', 'h'].includes(event.key.toLowerCase())) return
    event.preventDefault(); event.stopPropagation(); open(event.key.toLowerCase() === 'h' ? 'replace' : 'find')
  }
  root.addEventListener('keydown', shortcut, true)
  const onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }) => { if (!panel.hidden && transaction.docChanged && !applying) scan(); else refreshLock() }
  editor.on('transaction', onTransaction)
  return { open, replace, panel, refreshLock, dispose() { disposed = true; root.removeEventListener('keydown', shortcut, true); editor.off('transaction', onTransaction); panel.remove() } }
}
