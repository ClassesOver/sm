import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { buildContinuousPageSnapshot, createDocxNavigationPages, type DocxNavigationPagination } from './docx-navigation-pages'
const Doc = Node.create({ name: 'doc', topNode: true, content: 'paragraph+' })
const Paragraph = Node.create({ name: 'paragraph', group: 'block', content: 'text*', renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const disposals: (() => void)[] = []
afterEach(() => { disposals.splice(0).forEach(fn => fn()); document.body.replaceChildren() })
function fixture() {
  const editor = new Editor({ element: document.body.appendChild(document.createElement('div')), extensions: [Doc, Paragraph, Text], content: '<p>第一页</p><p>第二页</p>', editorProps: { handleScrollToSelection: () => true } })
  disposals.push(() => editor.destroy())
  const pm = editor.view.dom, children = [...pm.children] as HTMLElement[]
  const rect = (top: number, height: number) => ({ top, bottom: top + height, left: 100, right: 300, width: 200, height, x: 100, y: top, toJSON() {} })
  pm.getBoundingClientRect = () => rect(0, 160)
  children.forEach((el, i) => { el.getBoundingClientRect = () => rect(i * 80, 80) })
  const cuts = [0, 80].map((start, i) => ({ start, end: start + 80, section: 0, lead: { kind: 'block', block: i }, blank: false, floats: [], gap: { heightPx: 0 } }))
  const pagination = { cuts, geoms: [{ contentHeight: 100, topPx: 10 }], blocks: children.map((el, i) => ({ el, top: i * 80, height: 80, domHeight: 80 })), section: { pageWidth: 3000, pageHeight: 4500, marginTop: 150, marginBottom: 150, marginLeft: 150, marginRight: 150 }, sections: [] } as unknown as DocxNavigationPagination
  return { editor, pm, children, pagination }
}
it('零高度 gaps 仍按真实 cuts 生成两页', () => {
  const f = fixture(), result = buildContinuousPageSnapshot(f.pm, 1, f.pagination)
  expect(result.reason).toBeUndefined(); expect(result.pages).toHaveLength(2)
  expect(result.pages?.map(page => page.blocks.map(block => block.el.textContent))).toEqual([['第一页'], ['第二页']])
  expect(result.pages?.[1].blocks[0].top).toBe(10)
})
it.each(['line', 'row', 'cell'])('拒绝 %s 切分而不伪造页面缩略图', kind => {
  const f = fixture(); f.pagination.cuts[1].lead.kind = kind as 'line'
  const result = buildContinuousPageSnapshot(f.pm, 1, f.pagination)
  expect(result.pages).toBeUndefined(); expect(result.reason).toMatch(/段内|表格/)
})
it('拒绝混合尺寸、镜像页边距和分栏', () => {
  const f = fixture(); f.pagination.mirrorMargins = true
  expect(buildContinuousPageSnapshot(f.pm, 1, f.pagination).reason).toMatch(/镜像/)
  f.pagination.mirrorMargins = false; f.pagination.geoms[0].cols = 2
  expect(buildContinuousPageSnapshot(f.pm, 1, f.pagination).reason).toMatch(/分栏/)
  f.pagination.geoms[0].cols = 1; f.pagination.sections = [{ settings: { ...f.pagination.section, pageHeight: 9000 } }] as DocxNavigationPagination['sections']
  expect(buildContinuousPageSnapshot(f.pm, 1, f.pagination).reason).toMatch(/尺寸/)
})
it('只读页面点击定位真实正文；克隆清除重复身份和可执行资源', async () => {
  const f = fixture(); f.editor.setEditable(false)
  f.children[0].id = 'live-paragraph'; f.children[0].setAttribute('contenteditable', 'true'); f.children[0].setAttribute('autofocus', '')
  f.children[0].insertAdjacentHTML('beforeend', '<script>window.bad=1</script><iframe src="https://invalid.test"></iframe><span id="inner" onclick="bad()">文字</span>')
  const pages = createDocxNavigationPages({ editor: f.editor, getPagination: async () => f.pagination, getZoom: () => 1 })
  disposals.push(pages.dispose); document.body.append(pages.element); pages.setVisible(true)
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(pages.element.querySelectorAll('[data-navigation-page]')).toHaveLength(2)
  expect(pages.element.querySelectorAll('script,iframe,[id],[contenteditable],[autofocus],[onclick],.ProseMirror,.doc-page')).toHaveLength(0)
  const before = f.editor.getJSON(); (pages.element.querySelector('[data-navigation-page="1"]') as HTMLButtonElement).click()
  expect(f.editor.state.selection.$from.parent.textContent).toBe('第二页'); expect(f.editor.getJSON()).toEqual(before)
})
it.each(['hide', 'dispose', 'document', 'zoom', 'request'])('等待期间 %s 身份失效后拒绝旧分页结果', async cause => {
  const f = fixture(); let resolve!: (value: DocxNavigationPagination) => void, zoom = 1
  const pages = createDocxNavigationPages({ editor: f.editor, getPagination: () => new Promise(done => { resolve = done }), getZoom: () => zoom })
  disposals.push(pages.dispose); document.body.append(pages.element); pages.setVisible(true)
  await Promise.resolve()
  if (cause === 'hide') pages.setVisible(false)
  if (cause === 'dispose') pages.dispose()
  if (cause === 'document') f.editor.commands.insertContent('新')
  if (cause === 'zoom') zoom = 2
  if (cause === 'request') { const old = resolve; pages.refresh(); old(f.pagination) }
  else resolve(f.pagination)
  await new Promise(done => setTimeout(done, 0))
  expect(pages.element.querySelectorAll('[data-navigation-page]')).toHaveLength(0)
})
it('缩放后仍保留真实块宽与页首段前距，不把屏幕坐标当纸张坐标', () => {
  const f = fixture()
  f.children.forEach((el, i) => { el.getBoundingClientRect = () => ({ top: i * 160, bottom: i * 160 + 160, left: 100, right: 500, width: 400, height: 160, x: 100, y: i * 160, toJSON() {} }) })
  f.pagination.blocks[1].leadFoldPx = 6; f.pagination.cuts[1].leadDropsSpaceBefore = false
  const result = buildContinuousPageSnapshot(f.pm, 2, f.pagination)
  expect(result.pages?.[1].blocks[0].width).toBe(200)
  expect(result.pages?.[1].blocks[0].top).toBe(16)
})
it('正文块跨越真实 cut 末尾时明确拒绝，不能静默截掉段落', () => {
  const f = fixture(); f.pagination.blocks[0].domHeight = 90
  const result = buildContinuousPageSnapshot(f.pm, 1, f.pagination)
  expect(result.pages).toBeUndefined(); expect(result.reason).toMatch(/段内/)
})
it('空白页保留真实页数，正文页定位不复用虚构 paperY', () => {
  const f = fixture(); f.pagination.cuts.splice(1, 0, { ...f.pagination.cuts[0], start: 80, end: 80, blank: true, lead: { block: -1, kind: 'tail' } })
  const result = buildContinuousPageSnapshot(f.pm, 1, f.pagination)
  expect(result.pages).toHaveLength(3); expect(result.pages?.[1].blocks).toEqual([])
  expect(result.pages?.[2].target).toBe(f.children[1])
})
it('页面首块缩进不改变其他块的纸张左边距', () => {
  const f = fixture(); f.pagination.cuts = [{ ...f.pagination.cuts[0], end: 160 }]
  f.children[0].getBoundingClientRect = () => ({ top: 0, bottom: 80, left: 140, right: 300, width: 160, height: 80, x: 140, y: 0, toJSON() {} })
  const result = buildContinuousPageSnapshot(f.pm, 1, f.pagination)
  expect(result.pages?.[0].blocks.map(block => block.left)).toEqual([50, 10])
})
it('缩略图鼠标按下保留真实选区并阻止克隆链接默认行为', async () => {
  const f = fixture(); f.editor.setEditable(false); f.children[0].insertAdjacentHTML('beforeend', '<a href="#external">链接</a><form action="/bad"><input autofocus><button>提交</button></form>')
  const pages = createDocxNavigationPages({ editor: f.editor, getPagination: async () => f.pagination, getZoom: () => 1 })
  disposals.push(pages.dispose); document.body.append(pages.element); pages.setVisible(true)
  await new Promise(resolve => setTimeout(resolve, 0))
  const before = f.editor.state.selection
  const paper = pages.element.querySelector<HTMLElement>('.docx-navigation-page-paper')!
  expect(paper.inert).toBe(true)
  const button = pages.element.querySelector<HTMLButtonElement>('[data-navigation-page]')!
  const mouse = new MouseEvent('mousedown', { bubbles: true, cancelable: true }); button.dispatchEvent(mouse)
  expect(mouse.defaultPrevented).toBe(true); expect(f.editor.state.selection.eq(before)).toBe(true)
  const click = new MouseEvent('click', { bubbles: true, cancelable: true }); paper.querySelector('a')!.dispatchEvent(click)
  expect(click.defaultPrevented).toBe(true)
})
it('纵向居中和多节不同正文宽度明确显示支持边界', () => {
  const f = fixture(); f.pagination.section.vAlign = 'center'
  expect(buildContinuousPageSnapshot(f.pm, 1, f.pagination).reason).toMatch(/纵向对齐/)
  f.pagination.section.vAlign = undefined
  f.pagination.sections = [{ settings: { ...f.pagination.section, marginLeft: 300 } }] as DocxNavigationPagination['sections']
  expect(buildContinuousPageSnapshot(f.pm, 1, f.pagination).reason).toMatch(/页边距/)
})
