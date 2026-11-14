import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft, type NativeOperation } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
const views: ReturnType<typeof createSlidesEditorView>[] = []
beforeEach(() => {
  document.documentElement.lang = 'zh-CN'
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); document.documentElement.lang = ''; Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal'); Reflect.deleteProperty(HTMLDialogElement.prototype, 'close'); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function storage() {
  const items = new Map<string, string>()
  return { getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => { items.set(key, value) }, removeItem: (key: string) => { items.delete(key) } }
}
async function fixture(store = storage()) {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [0, 1].map(slideIndex => ({ slideIndex, elements: [{ id: 'title', name: '标题', type: 'text', text: '来源' + slideIndex, editable: true, geometry: { x: 10, y: 10, width: 300, height: 50 } }], animations: [] })) }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const draft = new NativeDraft({ documentId: 'equation', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, store)
  const request = vi.fn(async (path: string, _init?: RequestInit) => path === 'deck' ? source : path === 'render-tree' ? { slides: [] } : { revision: 2, revisionRegistered: true, validation: { issues: [] } })
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx })
  views.push(view); await view.ready
  const control = <T extends HTMLElement>(selector: string) => shell.editor.querySelector<T>(selector)!
  const open = () => {
    const button = control<HTMLButtonElement>('[data-command=insertEquation]')
    expect(button.disabled).toBe(false); button.focus(); button.click()
    const dialog = control<HTMLDialogElement>('.slides-equation-dialog'); expect(dialog).not.toBeNull()
    return dialog
  }
  const insert = (text: string) => { const dialog = open(); const input = dialog.querySelector<HTMLInputElement>('input')!; input.value = text; input.dispatchEvent(new Event('input')); dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!.click() }
  return { shell, view, draft, request, control, open, insert, store }
}

it('插入公式提供固定源12模板，打开和取消不写草稿并恢复入口焦点', async () => {
  const app = await fixture(); const dialog = app.open()
  expect([...dialog.querySelectorAll('[data-equation-template]')].map(button => button.textContent)).toEqual([
    'x = (−b ± √(b² − 4ac)) / 2a二次求根公式', 'a² + b² = c²勾股定理', 'e^(iπ) + 1 = 0欧拉恒等式', 'E = mc²质能方程', 'A = πr²圆面积', '∑ₖ₌₁ⁿ k = n(n+1)/2等差求和', '∫₋∞^∞ e^(−x²) dx = √π高斯积分', 'lim(x→∞) (1 + 1/x)ˣ = e自然对数极限', 'x̄ = (1/n) ∑ᵢ xᵢ均值', 'σ = √( ∑(xᵢ − μ)² / n )标准差', 'F(ω) = ∫₋∞^∞ f(t) e^(−iωt) dt傅里叶变换', 'f(x) = (1/(σ√(2π))) e^(−(x−μ)²/2σ²)正态分布',
  ])
  expect(dialog.textContent).toContain('数学字体文本框'); expect(app.draft.operations).toEqual([])
  dialog.querySelector<HTMLButtonElement>('[data-equation-cancel]')!.click()
  expect(app.control('.slides-equation-dialog')).toBeNull(); expect(app.draft.operations).toEqual([])
  expect(document.activeElement).toBe(app.control('[data-command=insertEquation]'))
})

it('模板仅填入输入框，明确插入后使用来源居中1英寸框和Cambria Math斜体', async () => {
  const app = await fixture(); const dialog = app.open()
  dialog.querySelectorAll<HTMLButtonElement>('[data-equation-template]')[3]!.click()
  expect(dialog.querySelector<HTMLInputElement>('input')!.value).toBe('E = mc²'); expect(app.draft.operations).toEqual([])
  dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!.click()
  expect(app.draft.operations).toMatchObject([{ kind: 'editSlides', textBoxes: [{ slideIndex: 0, text: 'E = mc²', fontSize: 18, fontFamily: 'Cambria Math', italic: true, equation: true, geometry: { x: 432, y: 222, width: 96, height: 96 } }] }])
  expect(app.control('.structure-pending').textContent).toContain('公式文本')
})

it('自定义Unicode文本进入同一草稿，撤销重做和刷新恢复保持公式标识', async () => {
  const app = await fixture(); app.insert('  α² + β² = γ² <&> 😀  ')
  const after = structuredClone(app.draft.operations)
  expect(after).toMatchObject([{ textBoxes: [{ text: 'α² + β² = γ² <&> 😀', equation: true }] }])
  app.control<HTMLButtonElement>('[data-source-action=onUndo]').click(); expect(app.draft.operations).toEqual([])
  app.control<HTMLButtonElement>('[data-source-action=onRedo]').click(); expect(app.draft.operations).toEqual(after)
  app.view.dispose(); views.splice(views.indexOf(app.view), 1)
  document.body.replaceChildren()
  const restored = await fixture(app.store)
  expect(restored.draft.operations).toEqual(after); expect(restored.control<HTMLInputElement>('[aria-label="新增公式文本"]').value).toBe('α² + β² = γ² <&> 😀')
})

it('空白禁用提交，Enter仅提交一次；待保存公式未失焦修改随原source身份保存', async () => {
  const app = await fixture(); const dialog = app.open(), input = dialog.querySelector<HTMLInputElement>('input')!, submit = dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!
  input.value = '   '; input.dispatchEvent(new Event('input')); expect(submit.disabled).toBe(true)
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); expect(app.draft.operations).toEqual([])
  input.value = '∑ xᵢ'; input.dispatchEvent(new Event('input')); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
  expect(app.control('.slides-equation-dialog')).toBeNull()
  const pending = app.control<HTMLInputElement>('[aria-label="新增公式文本"]'); pending.value = '未失焦 α = 42'; pending.dispatchEvent(new Event('input')); pending.focus()
  app.shell.save.click(); await vi.waitFor(() => expect(app.request.mock.calls.some(([path]) => path === 'save')).toBe(true))
  const saved = JSON.parse(app.request.mock.calls.find(([path]) => path === 'save')![1]!.body as string)
  expect(saved).toMatchObject({ expectedSha256: 'a'.repeat(64), operations: [{ textBoxes: [{ text: '未失焦 α = 42', equation: true }] }] })
  expect(saved.operations[0].textBoxes).toHaveLength(1)
})

it('页面重排仍把公式映射到原来源页，关闭视图销毁尚未提交的对话框', async () => {
  const app = await fixture(); app.control<HTMLButtonElement>('.slide-open[data-slide-index="1"]').click()
  app.control<HTMLButtonElement>('[data-command=movePrevious]').click(); app.insert('E = mc²')
  expect(app.draft.operations).toMatchObject([{ order: [1, 0], textBoxes: [{ slideIndex: 1 }] }])
  app.open(); const before: NativeOperation[] = structuredClone(app.draft.operations); app.view.dispose(); views.splice(views.indexOf(app.view), 1)
  expect(app.control('.slides-equation-dialog')).toBeNull(); expect(app.draft.operations).toEqual(before)
})

it('IME确认和超限输入不提交，保存锁定期间不产生新公式操作', async () => {
  const app = await fixture(); const dialog = app.open(), input = dialog.querySelector<HTMLInputElement>('input')!
  input.value = 'α = 42'; input.dispatchEvent(new Event('input'))
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }))
  expect(app.draft.operations).toEqual([]); expect(dialog.isConnected).toBe(true)
  input.value = 'x'.repeat(20001); input.dispatchEvent(new Event('input')); dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!.click()
  expect(app.draft.operations).toEqual([])
  input.value = 'α = 42'; input.dispatchEvent(new Event('input')); app.draft.beginSave()
  dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!.click()
  expect(app.draft.operations).toEqual([]); app.draft.saveFailed()
})

it('对话框打开后来源页变化则不把公式错误写入另一页', async () => {
  const app = await fixture(); const dialog = app.open(), input = dialog.querySelector<HTMLInputElement>('input')!
  input.value = 'E = mc²'; input.dispatchEvent(new Event('input'))
  app.control<HTMLButtonElement>('.slide-open[data-slide-index="1"]').click()
  dialog.querySelector<HTMLButtonElement>('[data-equation-insert]')!.click()
  expect(app.draft.operations).toEqual([])
})
