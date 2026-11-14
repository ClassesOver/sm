import { afterEach, expect, it } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { undoDepth } from '@tiptap/pm/history'
import { createDocxNavigation } from './docx-navigation'
import { NativeDraft } from './native-draft'
import { SearchHighlightExtension, searchPluginKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/decoration-extensions'
import { SCAN_THRESHOLD } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/find'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'inline*', renderHTML: () => ['p', 0] })
const Heading = Paragraph.extend({ name: 'docHeading', addAttributes: () => ({ level: { default: 1 } }), renderHTML: () => ['h1', 0] })
const Protected = Paragraph.extend({ name: 'docProtected', renderHTML: () => ['aside', 0] })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docTableRow+', renderHTML: () => ['table', ['tbody', 0]] })
const Row = Node.create({ name: 'docTableRow', content: 'docTableCell+', renderHTML: () => ['tr', 0] })
const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', renderHTML: () => ['td', 0] })
const Break = Node.create({ name: 'docHardBreak', inline: true, group: 'inline', renderHTML: () => ['br'] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Bold = Mark.create({ name: 'bold', renderHTML: () => ['b', 0] })
const block = (text: string, type = 'docParagraph') => ({ type, ...(text ? { content: [{ type: 'text', text }] } : {}) })
const cleanups: (() => void)[] = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.replaceChildren(); localStorage.clear() })
function setup(content: any[] = [block('标题', 'docHeading'), block('cat CAT ＣＡＴ'), block('cat')], onSearchNavigate?: () => void) {
  let updates = 0
  const draft = new NativeDraft({ documentId: 'navigation-search', revision: 1, sourceSha256: 'source', scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }, localStorage)
  const editor = new Editor({ element: document.body.appendChild(document.createElement('div')), extensions: [Doc, Paragraph, Heading, Protected, Table, Row, Cell, Text, Break, Bold, UndoRedo, SearchHighlightExtension], content: { type: 'doc', content }, editorProps: { handleScrollToSelection: () => true }, onUpdate: () => { updates++ } })
  const navigation = createDocxNavigation({ editor, container: document.body.appendChild(document.createElement('div')), onSearchNavigate })
  cleanups.push(() => { navigation.dispose(); editor.destroy() })
  navigation.open()
  const input = navigation.panel.querySelector<HTMLInputElement>('[data-navigation-query]')
  expect(input, '导航窗格必须提供正文搜索框').not.toBeNull()
  const query = (text: string) => { input!.value = text; input!.dispatchEvent(new Event('input', { bubbles: true })) }
  const action = (name: string) => navigation.panel.querySelector<HTMLButtonElement>('[data-navigation-search-action="' + name + '"]')!
  const results = () => [...navigation.panel.querySelectorAll<HTMLButtonElement>('[data-navigation-search-result]')]
  const count = () => navigation.panel.querySelector('[data-navigation-search-count]')!.textContent
  const status = () => navigation.panel.querySelector('[data-navigation-search-status]')!.textContent
  const selected = () => editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to)
  return { editor, navigation, draft, input: input!, query, action, results, count, status, selected, updates: () => updates }
}

it('搜索忽略大小写与全半角，结果点击和上下个循环精确选择且不写文档/草稿/历史', () => {
  const f = setup(); const before = f.editor.getJSON(), storage = JSON.stringify(localStorage), selection = f.editor.state.selection
  f.query('cat'); expect(f.results()).toHaveLength(4); expect(f.count()).toBe('0/4'); expect(f.editor.state.selection).toBe(selection)
  f.action('next').click(); expect(f.selected()).toBe('cat'); expect(f.count()).toBe('1/4')
  f.action('previous').click(); expect(f.count()).toBe('4/4')
  f.results()[2].focus(); f.results()[2].click(); expect(f.selected()).toBe('ＣＡＴ'); expect(f.count()).toBe('3/4')
  expect(document.activeElement).toBe(f.results()[2]); expect(f.results()[2].getAttribute('aria-current')).toBe('location')
  expect(f.editor.getJSON()).toEqual(before); expect(f.draft.dirty).toBe(false); expect(f.updates()).toBe(0)
  expect(undoDepth(f.editor.state)).toBe(0); expect(JSON.stringify(localStorage)).toBe(storage)
})

it('跨格式run和非BMP匹配使用真实偏移，并搜索表格但跳过受保护正文和段落边界', () => {
  const f = setup([{ type: 'docParagraph', content: [{ type: 'text', text: '前😀ca', marks: [{ type: 'bold' }] }, { type: 'text', text: 't尾' }] }, { type: 'docTable', content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [block('😀cat')] }] }] }, block('😀cat', 'docProtected'), block('前'), block('后')])
  f.query('😀cat'); expect(f.results()).toHaveLength(2); f.results()[0].click(); expect(f.selected()).toBe('😀cat')
  expect(f.editor.state.selection.from).toBe(2); expect(f.editor.state.selection.to).toBe(7)
  f.results()[1].click(); expect(f.selected()).toBe('😀cat'); expect(f.editor.state.selection.$from.depth).toBe(4)
  f.query('前后'); expect(f.results()).toHaveLength(0); expect(f.status()).toContain('未找到')
})

it.each(['^p', '^', '.*', '<img'])('以纯字面搜索 %s，结果上下文作为安全DOM文字输出', text => {
  const f = setup([block('a^p b^ c.* <img src=x onerror=alert(1)>')]); f.query(text)
  expect(f.results().length).toBe(text === '^' ? 2 : 1); f.results()[0].click(); expect(f.selected()).toBe(text)
  expect(f.navigation.panel.querySelector('img')).toBeNull(); expect(f.results()[0].querySelector('mark')?.textContent).toBe(text)
})

it('清空/无匹配/重新打开恢复标题树及折叠，Enter与Shift+Enter不修改正文', () => {
  const f = setup(); f.query('missing'); expect(f.count()).toBe('0/0'); expect(f.action('next').disabled).toBe(true)
  f.query('cat'); f.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); expect(f.count()).toBe('1/4')
  f.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true })); expect(f.count()).toBe('4/4')
  f.navigation.close(); f.navigation.open(); expect(f.results()).toHaveLength(4)
  f.action('clear').click(); expect(f.input.value).toBe(''); expect(f.results()).toHaveLength(0)
  expect(f.navigation.panel.querySelector<HTMLElement>('[role="tree"]')!.hidden).toBe(false); expect(f.status()).toContain('请输入')
})
it.each(['composition', 'legacy', 'handled'])('导航搜索保留受保护Enter的查询和当前选区：%s', protection => {
  const f = setup(); f.query('cat'); f.input.focus()
  const selection = f.editor.state.selection, before = f.editor.getJSON(), storage = JSON.stringify(localStorage)
  for (const shiftKey of [false, true]) {
    const event = new KeyboardEvent('keydown', { key: 'Enter', shiftKey, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
    if (protection === 'handled') event.preventDefault()
    f.input.dispatchEvent(event)
    expect(f.count()).toBe('0/4'); expect(f.input.value).toBe('cat'); expect(f.editor.state.selection).toBe(selection); expect(document.activeElement).toBe(f.input)
  }
  f.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); expect(f.count()).toBe('1/4')
  expect(f.editor.getJSON()).toEqual(before); expect(JSON.stringify(localStorage)).toBe(storage); expect(undoDepth(f.editor.state)).toBe(0)
})

it.each(['readonly', 'saving'])('%s 搜索与导航可用，不清除现有查找替换高亮', state => {
  const f = setup(); if (state === 'readonly') f.editor.setEditable(false); else f.draft.beginSave()
  f.editor.view.dispatch(f.editor.state.tr.setMeta(searchPluginKey, { ranges: [{ from: 1, to: 2 }], activeIndex: 0 }))
  const highlights = searchPluginKey.getState(f.editor.state), before = f.editor.getJSON(), updates = f.updates(), storage = JSON.stringify(localStorage)
  f.query('cat'); f.action('next').click(); expect(f.selected()).toBe('cat'); f.action('clear').click(); f.navigation.close()
  expect(searchPluginKey.getState(f.editor.state)).toBe(highlights); expect(f.editor.getJSON()).toEqual(before)
  expect(f.updates()).toBe(updates); expect(f.draft.dirty).toBe(false); expect(JSON.stringify(localStorage)).toBe(storage)
})

it('文档更新后结果和范围刷新，清空全部匹配后不可跳到旧位置', () => {
  const f = setup([block('cat')]); f.query('cat'); f.editor.commands.insertContentAt(1, 'new ')
  expect(f.results()).toHaveLength(1); f.results()[0].click(); expect(f.editor.state.selection.from).toBe(5); expect(f.selected()).toBe('cat')
  f.editor.commands.setContent({ type: 'doc', content: [block('没有结果')] }); expect(f.results()).toHaveLength(0); expect(f.action('next').disabled).toBe(true)
  f.editor.commands.setContent({ type: 'doc', content: [block('cat cat')] }); expect(f.results()).toHaveLength(2)
})

it('只列前500个结果，仍能跳转全部匹配', () => {
  const f = setup([block('cat '.repeat(503))]); f.query('cat'); expect(f.results()).toHaveLength(500); expect(f.count()).toBe('0/503')
  f.action('previous').click(); expect(f.count()).toBe('503/503'); expect(f.editor.state.selection.from).toBe(2009)
  expect(f.status()).toContain('前 500')
})

it('异步旧查询/销毁不会覆盖新结果，dispose解绑保留DOM的搜索和跳转事件', async () => {
  const original = SCAN_THRESHOLD.nodeSize; SCAN_THRESHOLD.nodeSize = 0
  cleanups.push(() => { SCAN_THRESHOLD.nodeSize = original })
  const f = setup(); f.query('cat'); f.query('标题'); await Promise.resolve(); await Promise.resolve()
  expect(f.results()).toHaveLength(1); expect(f.results()[0].textContent).toContain('标题')
  const oldInput = f.input, oldNext = f.action('next'); f.query('cat'); f.navigation.dispose(); await Promise.resolve(); await Promise.resolve()
  const before = f.editor.state.selection; oldInput.value = '不存在'; oldInput.dispatchEvent(new Event('input', { bubbles: true })); oldNext.click()
  expect(f.editor.state.selection).toBe(before); expect(f.navigation.panel.isConnected).toBe(false)
})

it('搜索结果跳转前才调用页面可见回调，metadata先于精确选区且不写正文', () => {
  let beforeNavigate = () => {}; const events: string[] = []
  const f = setup(undefined, () => beforeNavigate())
  beforeNavigate = () => { events.push('callback'); f.editor.commands.setMeta('navigation-test-page', true) }
  f.editor.on('transaction', ({ transaction }) => { if (transaction.getMeta('navigation-test-page')) events.push('page'); else if (transaction.selectionSet) events.push('selection') })
  const before = f.editor.getJSON(), storage = JSON.stringify(localStorage)
  f.query('cat'); f.navigation.refresh(); expect(events).toEqual([])
  f.results()[0].click(); expect(events).toEqual(['callback', 'page', 'selection']); expect(f.selected()).toBe('cat')
  expect(f.editor.getJSON()).toEqual(before); expect(f.updates()).toBe(0); expect(undoDepth(f.editor.state)).toBe(0); expect(JSON.stringify(localStorage)).toBe(storage)
})

it('回滚直接updateState后public refresh以当前文档重查，旧异步结果不能覆盖', async () => {
  const original = SCAN_THRESHOLD.nodeSize; SCAN_THRESHOLD.nodeSize = 0
  cleanups.push(() => { SCAN_THRESHOLD.nodeSize = original })
  const f = setup([block('cat')]), originalState = f.editor.state
  f.query('cat'); f.editor.commands.setContent({ type: 'doc', content: [block('已拒绝安装的正文')] })
  f.editor.view.updateState(originalState); f.navigation.refresh()
  await Promise.resolve(); await Promise.resolve()
  expect(f.results()).toHaveLength(1); f.results()[0].click(); expect(f.selected()).toBe('cat'); expect(f.editor.state.selection.from).toBe(1)
})

it('纯字面搜索不跨硬换行、段落边界，也不把^l当作换行代码', () => {
  const f = setup([{ type: 'docParagraph', content: [{ type: 'text', text: '前' }, { type: 'docHardBreak' }, { type: 'text', text: '后' }] }, block('前'), block('后')])
  f.query('前后'); expect(f.results()).toHaveLength(0)
  f.query('^l'); expect(f.results()).toHaveLength(0)
})
