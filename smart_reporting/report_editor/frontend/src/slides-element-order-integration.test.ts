import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

const canvas = vi.hoisted(() => ({ state: undefined as any }))
const views:ReturnType<typeof createSlidesEditorView>[]=[]
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update(state: any) { canvas.state = state }, destroy() {} }) }))
afterEach(() => { for(const view of views.splice(0))view.dispose(); document.body.replaceChildren(); canvas.state = undefined })
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1].map(slideIndex => ({ slideIndex, elements: ['a','b','c'].map((id, index) => ({ id, type: 'shape', name: id, text: id, editable: true, deletable: true, orderEditable: true, arrangeEditable: true, geometry: { x: index * 100, y: 20, width: 80, height: 40 } })) })) }
async function open(operations: any[] = []) {
  const storage = new Map<string,string>()
  const draft = new NativeDraft({ documentId: 'layers', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: k => storage.get(k) ?? null, setItem: (k,v) => { storage.set(k,v) }, removeItem: k => { storage.delete(k) } })
  if (operations.length) draft.setOperations(operations)
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : path === 'render-tree' ? { slides: source.slides.map(s => ({ slideIndex: s.slideIndex, widthPx: 960, heightPx: 540, nodes: s.elements.map(e => ({ id: e.id, sourceId: e.id, type: 'shape', box: { x: e.geometry.x, y: 20, w: 80, h: 40 } })) })) } : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  views.push(view)
  let error:unknown
  try { await view.ready } catch (reason) { error=reason }
  if(!error)await vi.waitFor(()=>expect(canvas.state).toBeDefined())
  const command = (id: string) => shell.editor.querySelector<HTMLButtonElement>(`[data-command="${id}"]`)!
  return { shell, draft, view, request, command, error }
}

it('多选层级保持相对顺序、整批一次历史并保存，回到来源顺序移除草稿', async () => {
  const app = await open([{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'a', text: '保留文字' }], order: [0,1] }])
  app.shell.editor.querySelector<HTMLInputElement>('[data-arrange-object="b"]')!.click()
  expect(app.command('bringToFront')).not.toBeNull()
  app.command('bringToFront').click()
  expect(app.draft.operations[0]?.elementOrders).toEqual([{ slideIndex: 0, elementIds: ['c','a','b'] }])
  expect(canvas.state.slide.nodes.map((n: any) => n.sourceId)).toEqual(['c','a','b'])
  expect(app.draft.operations[0]?.edits).toEqual([{ slideIndex: 0, elementId: 'a', text: '保留文字' }])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(app.draft.operations[0]?.elementOrders).toBeUndefined()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  app.command('sendToBack').click()
  expect(app.draft.operations[0]?.elementOrders).toBeUndefined()
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  app.shell.save.click()
  await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const call = app.request.mock.calls.find(([path]) => path === 'save')!
  expect(JSON.parse(call[1]!.body as string).operations[0].elementOrders).toEqual([{ slideIndex: 0, elementIds: ['c','a','b'] }])
  app.view.dispose()
})

it('框选只改变当前页选择且拒绝旧页面回调，边界层级无新增历史', async () => {
  const app = await open()
  expect(canvas.state.onSelectMany).toBeTypeOf('function')
  canvas.state.onSelectMany(['a','b'])
  expect(app.shell.editor.querySelectorAll('[data-arrange-object]:checked')).toHaveLength(2)
  expect(app.draft.operations).toEqual([])
  app.command('sendToBack').click()
  expect(app.draft.operations).toEqual([])
  const stale = canvas.state.onSelectMany
  app.shell.editor.querySelector<HTMLButtonElement>('[data-slide-index="1"]')!.click()
  stale(['b','c'])
  expect(app.shell.editor.querySelectorAll('[data-arrange-object]:checked')).toHaveLength(1)
  canvas.state.onSelectMany([])
  expect(app.shell.editor.querySelectorAll('[data-arrange-object]:checked')).toHaveLength(0)
  expect(app.command('bringToFront').disabled).toBe(true)
  expect(app.draft.operations).toEqual([])
  app.view.dispose()
})

it('恢复来源对象完整顺序并投影，非法顺序拒绝且保留草稿', async () => {
  const operation = { kind: 'editSlides', order: [0,1], elementOrders: [{ slideIndex: 0, elementIds: ['b','c','a'] }] }
  const app = await open([operation])
  expect(canvas.state.slide.nodes.map((n: any) => n.sourceId)).toEqual(['b','c','a'])
  app.view.dispose()
  document.body.replaceChildren();canvas.state=undefined
  const invalid = { ...operation, elementOrders: [{ slideIndex: 0, elementIds: ['a','a','c'] }] }
  const bad = await open([invalid])
  expect(bad.draft.operations).toEqual([invalid])
  expect(String(bad.error)).toContain('草稿')
  bad.shell.save.click()
  expect(bad.request.mock.calls.some(([path])=>path==='save')).toBe(false)
  bad.view.dispose()
})
