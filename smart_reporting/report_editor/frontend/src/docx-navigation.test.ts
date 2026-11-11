import { outlineViewKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/outline-view'
import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { undoDepth } from '@tiptap/pm/history'
import { createDocxNavigation } from './docx-navigation'
import type { DocxNavigationPagesOptions } from './docx-navigation-pages'
import { NativeDraft } from './native-draft'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'inline*', addAttributes: () => ({ styleId: { default: null }, level: { default: 1 } }), renderHTML: () => ['p', 0] })
const Heading = Paragraph.extend({ name: 'docHeading', renderHTML: () => ['h1', 0] })
const ListItem = Paragraph.extend({ name: 'docListItem', renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const block = (text: string, level = 1, type = 'docHeading', styleId: string | null = null) => ({ type, attrs: { level, styleId }, ...(text ? { content: [{ type: 'text', text }] } : {}) })
const disposals: (() => void)[] = []
afterEach(() => { disposals.splice(0).forEach(dispose => dispose()); document.body.replaceChildren(); localStorage.clear() })
function setup(content = [block('章一'), block('子标题', 2), block('正文', 1, 'docParagraph'), block('章二')], pages?: Omit<DocxNavigationPagesOptions, 'editor' | 'onError'>) {
  const container = document.body.appendChild(document.createElement('div'))
  const draft = new NativeDraft({ documentId: 'navigation', revision: 1, sourceSha256: 'source', scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }, localStorage)
  let updates = 0, visibilityChanges = 0
  const editor = new Editor({ element: document.body.appendChild(document.createElement('div')), extensions: [Doc, Paragraph, Heading, ListItem, Text, UndoRedo], content: { type: 'doc', content }, editorProps: { handleScrollToSelection: () => true }, onUpdate: () => { updates++ } })
  const styles = new Map([['HeadingList', { headingLevel: 2 }], ['HeadingBody', { headingLevel: 3 }], ['OutlineOff', { headingLevel: 2, headingOutlineOff: true as const }]])
  const navigation = createDocxNavigation({ editor, container, styles, pages, onVisibilityChange: () => { visibilityChanges++ } })
  const buttons = () => [...navigation.panel.querySelectorAll<HTMLButtonElement>('[data-navigation-heading]')]
  const collapse = (index: number) => navigation.panel.querySelectorAll<HTMLButtonElement>('[data-navigation-collapse]')[index].click()
  disposals.push(() => { navigation.dispose(); editor.destroy() })
  return { editor, navigation, buttons, collapse, draft, updates: () => updates, visibilityChanges: () => visibilityChanges }
}

it('列出层级标题、空标题、继承标题样式的正文和列表，排除正文大纲关闭样式', () => {
  const f = setup([block('章一'), block('', 3), block('编号标题', 1, 'docListItem', 'HeadingList'), block('样式标题', 1, 'docParagraph', 'HeadingBody'), block('排除', 1, 'docParagraph', 'OutlineOff')])
  expect(f.navigation.visible).toBe(false); f.navigation.open()
  expect(f.buttons().map(button => button.textContent)).toEqual(['章一', '（空标题）', '编号标题', '样式标题'])
  expect([...f.navigation.panel.querySelectorAll('[role="treeitem"]')].map(row => row.getAttribute('aria-level'))).toEqual(['1', '2', '2', '3'])
})

it('点击标题只移动真实选区，不修改文档、草稿、存储或撤销栈', () => {
  const f = setup(); const before = f.editor.getJSON(); const storageBefore = JSON.stringify(localStorage); f.navigation.open()
  const target = f.buttons()[2]; target.focus(); target.click()
  expect(f.editor.state.selection.$from.parent.textContent).toBe('章二')
  expect(f.buttons()[2].getAttribute('aria-current')).toBe('location'); expect(document.activeElement).toBe(target)
  expect(f.editor.getJSON()).toEqual(before); expect(f.updates()).toBe(0)
  expect(undoDepth(f.editor.state)).toBe(0); expect(f.draft.dirty).toBe(false); expect(JSON.stringify(localStorage)).toBe(storageBefore)
})

it.each(['readonly', 'saving'])('%s 仍可打开折叠和跳转且不产生写入', state => {
  const f = setup(); if (state === 'readonly') f.editor.setEditable(false); else f.draft.beginSave()
  const before = f.editor.getJSON(), updatesBefore = f.updates(); f.navigation.toggle(); f.collapse(0)
  expect(f.buttons().map(button => button.textContent)).toEqual(['章一', '章二'])
  f.buttons()[1].click(); expect(f.editor.state.selection.$from.parent.textContent).toBe('章二')
  expect(f.editor.getJSON()).toEqual(before); expect(f.draft.dirty).toBe(false); expect(f.updates()).toBe(updatesBefore)
})

it('相同文字标题单独折叠，折叠父节点承接活动标题且可定位空标题', () => {
  const f = setup([block('重复'), block('', 2), block('重复'), block('第二子项', 2)])
  f.navigation.open(); f.buttons()[1].click(); f.collapse(0)
  expect(f.buttons().map(button => button.textContent)).toEqual(['重复', '重复', '第二子项'])
  expect(f.buttons()[0].getAttribute('aria-current')).toBe('location')
  f.buttons()[2].click(); expect(f.editor.state.selection.$from.parent.textContent).toBe('第二子项')
  f.collapse(0); f.buttons()[1].click(); expect(f.editor.state.selection.$from.parent.textContent).toBe('')
})

it('实时更新标题和定位位置，关闭重开保留折叠，外部选区更新活动项', () => {
  const f = setup(); f.navigation.open(); f.collapse(0); f.editor.commands.insertContentAt(1, '新')
  expect(f.buttons()[0].textContent).toBe('新章一'); f.navigation.close(); expect(f.navigation.visible).toBe(false)
  f.editor.commands.insertContentAt(f.editor.state.doc.content.size, block('章三'))
  f.navigation.toggle(); expect(f.buttons().map(button => button.textContent)).toEqual(['新章一', '章二', '章三'])
  f.buttons()[2].click(); expect(f.editor.state.selection.$from.parent.textContent).toBe('章三')
  f.editor.commands.setTextSelection(1); expect(f.buttons()[0].getAttribute('aria-current')).toBe('location')
})

it('无标题显示空状态，关闭按钮和 Escape 生效，dispose 解绑旧 DOM 与编辑器', () => {
  const f = setup([block('正文', 1, 'docParagraph')]); f.navigation.open(); f.navigation.open(); expect(f.visibilityChanges()).toBe(1)
  expect(f.navigation.panel.textContent).toContain('当前正文没有标题')
  f.navigation.panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); expect(f.navigation.visible).toBe(false)
  f.navigation.open(); f.navigation.panel.querySelector<HTMLButtonElement>('[data-navigation-action="close"]')!.click(); expect(f.navigation.visible).toBe(false)
  f.navigation.open(); const panel = f.navigation.panel; f.navigation.dispose()
  expect(panel.isConnected).toBe(false); f.editor.commands.setContent({ type: 'doc', content: [block('新章')] })
  f.navigation.open(); f.navigation.refresh(); expect(f.navigation.visible).toBe(false); expect(panel.textContent).not.toContain('新章')
})

it('页面标签先准备页面视图，切回标题与关闭后不接受旧测量', async () => {
  let prepared = false, resolve!: (value: never) => void, current!: () => boolean
  const f = setup(undefined, { getZoom: () => 1, prepare: () => { prepared = true }, getPagination(stillCurrent) { current = stillCurrent; return new Promise(done => { resolve = done }) } })
  f.navigation.open()
  const pages = f.navigation.panel.querySelector<HTMLButtonElement>('[data-navigation-tab="pages"]')!
  expect(pages).not.toBeNull(); pages.click(); await Promise.resolve()
  expect(prepared).toBe(true); expect(current()).toBe(true)
  expect(f.navigation.panel.querySelector<HTMLElement>('[role="tree"]')!.hidden).toBe(true)
  f.navigation.panel.querySelector<HTMLButtonElement>('[data-navigation-tab="headings"]')!.click()
  expect(current()).toBe(false); expect(f.buttons().map(button => button.textContent)).toEqual(['章一', '子标题', '章二'])
  pages.click(); await Promise.resolve(); f.navigation.close(); expect(current()).toBe(false)
  resolve({} as never); await Promise.resolve()
  expect(f.navigation.panel.querySelectorAll('[data-navigation-page]')).toHaveLength(0)
})

it('切入大纲立即失效页面请求并回到标题标签', async () => {
  let current!: () => boolean
  const f = setup(undefined, { getZoom: () => 1, getPagination(stillCurrent) { current = stillCurrent; return new Promise(() => {}) } })
  f.navigation.open()
  f.navigation.panel.querySelector<HTMLButtonElement>('[data-navigation-tab="pages"]')!.click()
  await Promise.resolve()
  expect(current()).toBe(true)
  f.editor.view.dispatch(f.editor.state.tr.setMeta(outlineViewKey, { active: true }))
  expect(current()).toBe(false)
  expect(f.navigation.panel.querySelector('[data-navigation-tab="headings"]')?.getAttribute('aria-selected')).toBe('true')
})
