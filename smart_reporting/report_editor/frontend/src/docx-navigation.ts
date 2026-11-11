import type { Editor } from '@tiptap/core'
import { TextSelection, type Transaction } from '@tiptap/pm/state'
import { collectHeadings, type HeadingRef, type HeadingStyles } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/headings'
import { buildHeadingTree, headingAtPos, headingKey, MAX_HEADING_LEVEL, visibleRows, type NavRow } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/nav-outline'
import { createDocxNavigationSearch } from './docx-navigation-search'
import { createDocxNavigationPages, type DocxNavigationPagesOptions } from './docx-navigation-pages'
import { outlineViewKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/outline-view'
import './docx-navigation.css'

// 复用固定来源 GenOffice f8c17004 的标题识别和树模型；本适配层仅导航，不执行标题编辑。
export function createDocxNavigation(options: {
  editor: Editor
  container: HTMLElement
  styles?: HeadingStyles
  pages?: Omit<DocxNavigationPagesOptions, 'editor' | 'onError'>
  onError?: (error: unknown) => void
  onVisibilityChange?: () => void
  onSearchNavigate?: () => void
}) {
  const { editor, container } = options
  const panel = document.createElement('section')
  panel.className = 'docx-navigation'; panel.dataset.docxNavigation = ''; panel.hidden = true
  panel.setAttribute('aria-label', '文档导航')
  panel.innerHTML = '<div class="docx-navigation-head"><strong>导航</strong><button type="button" data-navigation-action="close" aria-label="关闭导航窗格">关闭</button></div><h2 class="docx-navigation-title">标题</h2><div class="docx-navigation-tree" role="tree" aria-label="正文标题"></div><p class="docx-navigation-empty" hidden>当前正文没有标题</p><p class="docx-navigation-note">搜索当前正文和表格，忽略大小写及全半角；仅选择匹配文字，不添加全文高亮。页面仅呈现正文；暂不支持页眉页脚搜索、替换或修改标题。</p>'
  container.append(panel)
  const treeElement = panel.querySelector<HTMLElement>('[role="tree"]')!
  const empty = panel.querySelector<HTMLElement>('.docx-navigation-empty')!
  let disposed = false, headings: HeadingRef[] = [], rows: NavRow[] = [], allRows: NavRow[] = []
  let collapsed = new Set<number>(), searching = false, tab: 'headings' | 'pages' = 'headings'
  const pages = options.pages ? createDocxNavigationPages({ ...options.pages, editor, onError: options.onError }) : undefined
  if (pages) {
    const tabs = document.createElement('div'); tabs.className = 'docx-navigation-tabs'; tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '导航内容')
    tabs.innerHTML = '<button type="button" role="tab" data-navigation-tab="headings" aria-selected="true">标题</button><button type="button" role="tab" data-navigation-tab="pages" aria-selected="false">页面</button>'
    panel.querySelector('.docx-navigation-head')!.after(tabs); panel.querySelector('.docx-navigation-note')!.before(pages.element)
  }
  const title = panel.querySelector<HTMLElement>('.docx-navigation-title')!
  const search = createDocxNavigationSearch({ editor, onError: options.onError, onNavigate: options.onSearchNavigate, onQueryChange(active) {
    searching = active; title.hidden = active || tab === 'pages'; treeElement.hidden = active || tab === 'pages'; empty.hidden = active || tab === 'pages' || headings.length > 0
  } })
  ;(panel.querySelector('.docx-navigation-tabs') ?? panel.querySelector('.docx-navigation-head'))!.after(search.element)

  const updateActive = () => {
    pages?.updateActive()
    let index = headingAtPos(headings, editor.state.selection.from)
    const visible = new Set(rows.map(row => row.node.index))
    while (index >= 0 && !visible.has(index)) index = allRows[index].node.parent
    for (const button of treeElement.querySelectorAll<HTMLButtonElement>('[data-navigation-heading]')) {
      const active = Number(button.dataset.navigationIndex) === index
      button.classList.toggle('on', active)
      if (active) button.setAttribute('aria-current', 'location'); else button.removeAttribute('aria-current')
      button.closest('[role="treeitem"]')!.setAttribute('aria-selected', String(active))
    }
  }
  const refresh = () => {
    if (disposed || editor.isDestroyed) return
    headings = collectHeadings(editor.state.doc, options.styles ?? (editor.storage as { listNumbering?: { styles?: HeadingStyles } }).listNumbering?.styles, true)
    // 原模型按文字折叠：在树模型中用位置替代文字作键，避免同名/空标题互相折叠。展示始终使用原始标题。
    const tree = buildHeadingTree(headings.map(ref => ({ ...ref, text: String(ref.pos) })))
    allRows = visibleRows(tree, new Set(), MAX_HEADING_LEVEL)
    const keys = new Set(headings.filter(ref => collapsed.has(ref.pos)).map(ref => headingKey({ ...ref, text: String(ref.pos) })))
    rows = visibleRows(tree, keys, MAX_HEADING_LEVEL)
    const focused = document.activeElement instanceof HTMLElement && panel.contains(document.activeElement) ? document.activeElement : null
    const focusKind = focused?.hasAttribute('data-navigation-collapse') ? 'data-navigation-collapse' : 'data-navigation-heading'
    const focusPosition = focused?.getAttribute(focusKind)
    treeElement.replaceChildren()
    for (const row of rows) {
      const ref = headings[row.node.index]
      const item = document.createElement('div'); item.className = 'docx-navigation-row'
      item.setAttribute('role', 'treeitem'); item.setAttribute('aria-level', String(row.depth + 1))
      item.style.paddingInlineStart = String(row.depth * 14) + 'px'
      if (row.hasChildren) {
        item.setAttribute('aria-expanded', String(!row.collapsed))
        const fold = document.createElement('button'); fold.type = 'button'; fold.className = 'docx-navigation-fold'
        fold.dataset.navigationCollapse = String(ref.pos); fold.textContent = row.collapsed ? '▸' : '▾'
        fold.setAttribute('aria-label', (row.collapsed ? '展开：' : '折叠：') + (ref.text.trim() || '空标题'))
        fold.setAttribute('aria-expanded', String(!row.collapsed)); item.append(fold)
      } else { const spacer = document.createElement('span'); spacer.className = 'docx-navigation-spacer'; item.append(spacer) }
      const button = document.createElement('button'); button.type = 'button'; button.className = 'docx-navigation-heading'
      button.dataset.navigationHeading = String(ref.pos); button.dataset.navigationIndex = String(row.node.index)
      button.textContent = ref.text.trim() || '（空标题）'; button.title = button.textContent
      item.append(button); treeElement.append(item)
    }
    empty.hidden = searching || tab === 'pages' || headings.length > 0
    search.refresh()
    if (tab === 'pages') pages?.refresh()
    updateActive()
    if (focusPosition != null) treeElement.querySelector<HTMLButtonElement>('[' + focusKind + '="' + focusPosition + '"]')?.focus({ preventScroll: true })
  }
  const setVisible = (visible: boolean) => {
    if (disposed || visible === !panel.hidden) return
    panel.hidden = !visible
    search.setVisible(visible && tab === 'headings')
    pages?.setVisible(visible && tab === 'pages')
    if (visible) refresh()
    options.onVisibilityChange?.()
  }
  const selectTab = (next: 'headings' | 'pages') => {
    if (next === tab) return
    tab = next
    panel.querySelectorAll<HTMLButtonElement>('[data-navigation-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.navigationTab === tab)))
    search.element.hidden = tab === 'pages'; search.setVisible(!panel.hidden && tab === 'headings')
    title.hidden = tab === 'pages' || searching; treeElement.hidden = tab === 'pages' || searching; empty.hidden = tab === 'pages' || searching || headings.length > 0
    pages?.setVisible(!panel.hidden && tab === 'pages')
    if (tab === 'headings') refresh()
  }
  const navigate = (position: number) => {
    try {
      const ref = headings.find(heading => heading.pos === position)
      if (!ref) return
      // 选区事务不入撤销历史，也不会触发文档更新/草稿持久化；只读与保存中同样可用。
      editor.view.dispatch(editor.state.tr.setSelection(TextSelection.near(editor.state.doc.resolve(ref.pos + 1))).setMeta('addToHistory', false))
      const target = editor.view.nodeDOM(ref.pos)
      ;(target instanceof HTMLElement ? target : target?.parentElement)?.scrollIntoView?.({ block: 'center', inline: 'nearest' })
    } catch (error) { options.onError?.(error) }
  }
  const fold = (position: number) => {
    if (collapsed.has(position)) collapsed.delete(position); else collapsed.add(position)
    refresh()
  }
  const click = (event: MouseEvent) => {
    if (disposed) return
    const button = (event.target as Element).closest<HTMLButtonElement>('button')
    if (!button || !panel.contains(button)) return
    if (button.dataset.navigationTab === 'headings' || button.dataset.navigationTab === 'pages') selectTab(button.dataset.navigationTab)
    else if (button.dataset.navigationAction === 'close') setVisible(false)
    else if (button.dataset.navigationCollapse != null) fold(Number(button.dataset.navigationCollapse))
    else if (button.dataset.navigationHeading != null) navigate(Number(button.dataset.navigationHeading))
  }
  const keydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); setVisible(false); return }
    const tabButton = (event.target as Element).closest<HTMLButtonElement>('[data-navigation-tab]')
    if (tabButton && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault(); const next = event.key === 'Home' || event.key === 'ArrowLeft' ? 'headings' : 'pages'; selectTab(next); panel.querySelector<HTMLButtonElement>('[data-navigation-tab="' + next + '"]')?.focus({ preventScroll: true }); return
    }
    const button = (event.target as Element).closest<HTMLButtonElement>('[data-navigation-heading]')
    if (!button) return
    const index = rows.findIndex(row => row.node.index === Number(button.dataset.navigationIndex))
    const row = rows[index]
    if (!row) return
    let target = index
    if (event.key === 'ArrowDown') target = Math.min(index + 1, rows.length - 1)
    else if (event.key === 'ArrowUp') target = Math.max(index - 1, 0)
    else if (event.key === 'Home') target = 0
    else if (event.key === 'End') target = rows.length - 1
    else if (event.key === 'ArrowRight') { if (row.collapsed) fold(row.node.ref.pos); else if (row.hasChildren) target = index + 1 }
    else if (event.key === 'ArrowLeft') {
      if (row.hasChildren && !row.collapsed) fold(row.node.ref.pos)
      else { const parent = rows.findIndex(item => item.node.index === row.node.parent); if (parent >= 0) target = parent }
    } else return
    event.preventDefault()
    treeElement.querySelectorAll<HTMLButtonElement>('[data-navigation-heading]')[target]?.focus({ preventScroll: true })
  }
  const transaction = ({ transaction: tr }: { transaction: Transaction }) => {
    if (disposed) return
    if (tab === 'pages' && tr.getMeta(outlineViewKey)?.active === true) selectTab('headings')
    if (tr.docChanged) {
      collapsed = new Set([...collapsed].flatMap(pos => { const result = tr.mapping.mapResult(pos, 1); return result.deleted ? [] : [result.pos] }))
      if (!panel.hidden) refresh()
    } else if (!panel.hidden) updateActive()
  }
  panel.addEventListener('click', click); panel.addEventListener('keydown', keydown)
  editor.on('transaction', transaction)
  return { panel, open: () => setVisible(true), close: () => setVisible(false), toggle: () => setVisible(panel.hidden), refresh,
    get visible() { return !disposed && !panel.hidden },
    dispose() {
      if (disposed) return
      disposed = true; search.dispose(); pages?.dispose(); editor.off('transaction', transaction)
      panel.removeEventListener('click', click); panel.removeEventListener('keydown', keydown); panel.remove()
    },
  }
}
