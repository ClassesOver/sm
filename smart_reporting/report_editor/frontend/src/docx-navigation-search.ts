import type { Editor } from '@tiptap/core'
import type { Node as PmNode } from '@tiptap/pm/model'
import { TextSelection } from '@tiptap/pm/state'
import { compileFind, findInDoc, findInDocAsync, matchContext, RESULTS_LIST_CAP, SCAN_THRESHOLD, type FindMatch, type FindOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/find'

// 只复用固定源查找引擎；不写共享 searchPluginKey，避免覆盖已有查找替换面板高亮。
export function createDocxNavigationSearch(options: { editor: Editor; onQueryChange(active: boolean): void; onNavigate?(): void; onError?(error: unknown): void }) {
  const { editor } = options
  const element = document.createElement('section'); element.className = 'docx-navigation-search'
  element.innerHTML = '<div class="docx-navigation-query-row"><input type="search" data-navigation-query aria-label="搜索正文和表格" placeholder="搜索正文和表格"><button type="button" data-navigation-search-action="clear" aria-label="清除导航搜索">清除</button></div><div class="docx-navigation-search-summary" hidden><button type="button" data-navigation-search-action="previous" aria-label="上一个搜索结果">↑</button><button type="button" data-navigation-search-action="next" aria-label="下一个搜索结果">↓</button><output data-navigation-search-count aria-label="搜索结果计数"></output></div><p data-navigation-search-status role="status" aria-live="polite">请输入搜索文字</p><div class="docx-navigation-results" data-navigation-results hidden></div>'
  const input = element.querySelector<HTMLInputElement>('[data-navigation-query]')!
  const results = element.querySelector<HTMLElement>('[data-navigation-results]')!
  const status = element.querySelector<HTMLElement>('[data-navigation-search-status]')!
  const count = element.querySelector<HTMLOutputElement>('[data-navigation-search-count]')!
  const summary = element.querySelector<HTMLElement>('.docx-navigation-search-summary')!
  const previous = element.querySelector<HTMLButtonElement>('[data-navigation-search-action="previous"]')!
  const next = element.querySelector<HTMLButtonElement>('[data-navigation-search-action="next"]')!
  const settings: FindOptions = { mode: 'literal', matchCase: false, wholeWord: false, matchWidth: false }
  let disposed = false, visible = false, scanning = false, active = -1
  let matches: FindMatch[] = [], token: { aborted: boolean } | undefined, scannedDoc: PmNode | undefined
  const abort = () => { if (token) token.aborted = true; token = undefined; scanning = false }
  const updateActive = () => {
    count.textContent = String(active + 1) + '/' + matches.length
    for (const button of results.querySelectorAll<HTMLButtonElement>('[data-navigation-search-result]')) {
      const selected = Number(button.dataset.navigationSearchResult) === active
      button.classList.toggle('on', selected)
      if (selected) button.setAttribute('aria-current', 'location'); else button.removeAttribute('aria-current')
    }
  }
  const paint = () => {
    const focused = document.activeElement instanceof HTMLElement && results.contains(document.activeElement) ? document.activeElement.dataset.navigationSearchResult : undefined
    results.replaceChildren()
    matches.slice(0, RESULTS_LIST_CAP).forEach((match, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'docx-navigation-result'; button.dataset.navigationSearchResult = String(index)
      const context = matchContext(match), hit = document.createElement('mark'); hit.textContent = context.hit
      button.append(document.createTextNode(String(index + 1) + '. ' + context.before), hit, document.createTextNode(context.after)); results.append(button)
    })
    const hasQuery = input.value.length > 0
    summary.hidden = !hasQuery; results.hidden = !hasQuery
    previous.disabled = next.disabled = scanning || matches.length === 0
    status.textContent = !hasQuery ? '请输入搜索文字' : scanning ? '正在搜索…' : !matches.length ? '未找到匹配内容' : '找到 ' + matches.length + ' 处' + (matches.length > RESULTS_LIST_CAP ? '；仅列出前 ' + RESULTS_LIST_CAP + ' 条，上下个可导航全部匹配' : '')
    updateActive()
    if (focused !== undefined) results.querySelector<HTMLButtonElement>('[data-navigation-search-result="' + focused + '"]')?.focus({ preventScroll: true })
  }
  const refresh = (reset = false) => {
    abort()
    if (disposed || !visible || editor.isDestroyed) return
    const query = input.value, keep = reset ? -1 : active
    options.onQueryChange(query.length > 0)
    scannedDoc = editor.state.doc; matches = []; active = -1
    if (!query) { paint(); return }
    // 源 literal 模式仍解释 Word 的 ^ 代码；本框承诺纯字面，因此用源约定 ^^ 转义每个 ^。
    const compiled = compileFind(query.replaceAll('^', '^^'), settings)
    if (!compiled.ok) { paint(); return }
    const doc = scannedDoc
    const commit = (found: FindMatch[]) => { matches = found; active = found.length && keep >= 0 ? Math.min(keep, found.length - 1) : -1; paint() }
    if (doc.nodeSize <= SCAN_THRESHOLD.nodeSize) { commit(findInDoc(doc, compiled.query, settings)); return }
    scanning = true; paint()
    const current = { aborted: false }; token = current
    void findInDocAsync(doc, compiled.query, settings, current).then(found => {
      if (disposed || !visible || current.aborted || token !== current || editor.state.doc !== doc || input.value !== query) return
      token = undefined; scanning = false
      if (found) commit(found)
    }).catch(error => { if (!disposed && token === current) { token = undefined; scanning = false; paint(); options.onError?.(error) } })
  }
  const navigate = (index: number) => {
    if (disposed || !visible || editor.isDestroyed || scanning || !matches.length) return
    if (scannedDoc !== editor.state.doc) { refresh(); return }
    const target = (index + matches.length) % matches.length, match = matches[target]
    try {
      options.onNavigate?.()
      if (scannedDoc !== editor.state.doc) { refresh(); return }
      editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, match.from, match.to)).setMeta('addToHistory', false))
      active = target; updateActive()
      const { node } = editor.view.domAtPos(match.from)
      ;(node instanceof HTMLElement ? node : node.parentElement)?.scrollIntoView?.({ block: 'center', inline: 'nearest' })
    } catch (error) { options.onError?.(error) }
  }
  const step = (direction: 1 | -1) => navigate(active < 0 ? direction === 1 ? 0 : matches.length - 1 : active + direction)
  const onInput = () => refresh(true)
  const click = (event: MouseEvent) => {
    const button = (event.target as Element).closest<HTMLButtonElement>('button')
    if (!button || !element.contains(button)) return
    if (button.dataset.navigationSearchResult != null) navigate(Number(button.dataset.navigationSearchResult))
    else if (button.dataset.navigationSearchAction === 'next') step(1)
    else if (button.dataset.navigationSearchAction === 'previous') step(-1)
    else if (button.dataset.navigationSearchAction === 'clear') { input.value = ''; refresh(true); input.focus({ preventScroll: true }) }
  }
  const keydown = (event: KeyboardEvent) => { if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.target === input && event.key === 'Enter') { event.preventDefault(); step(event.shiftKey ? -1 : 1) } }
  input.addEventListener('input', onInput); element.addEventListener('click', click); element.addEventListener('keydown', keydown)
  return { element, refresh, setVisible(value: boolean) { if (disposed) return; visible = value; if (!visible) abort() }, dispose() {
    if (disposed) return
    disposed = true; abort(); input.removeEventListener('input', onInput); element.removeEventListener('click', click); element.removeEventListener('keydown', keydown); element.remove()
  } }
}
