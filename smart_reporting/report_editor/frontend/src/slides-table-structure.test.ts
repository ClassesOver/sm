import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createNativeOfficeView } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity } from './native-draft'
import type { NativeContextResponse } from './native-api'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const identity: NativeDraftIdentity = { documentId: 'table-structure', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const context = { context: { ...identity, format: 'pptx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true } as unknown as NativeContextResponse
const store = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
function model(rows = 2, cols = 3, safe = true) {
  return { revision: 1, sha256: identity.sourceSha256, size: { cx: 9144000, cy: 5143500 }, layouts: [{ path: 'ppt/slideLayouts/slideLayout1.xml', name: 'Blank', layoutType: 'blank', placeholders: [] }], slides: [{ slideIndex: 0, animations: [], transitionApplyAllSafe: true, elements: [
    { id: 'tbl_1', type: 'table', name: 'Table', text: '', editable: false, tableStructureEditable: safe, tableCells: Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => `${r}:${c}`)) },
    { id: 'text_0', type: 'text', name: 'Text', text: 'outside table', editable: true },
  ] }] }
}
async function open(draft = new NativeDraft(identity, store()), source = model(), extra = {}) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })), ...extra }
  const view = await createNativeOfficeView(shell, { api: api as never, context, draft })
  if (!view) throw new Error('no slides view')
  return { shell, view, draft, api }
}
const button = (root: ParentNode, command: string) => root.querySelector<HTMLButtonElement>(`[data-command="${command}"]`)!
const selectTable = (root: ParentNode) => {
  const select = root.querySelector<HTMLSelectElement>('#object-select')!
  select.value = 'tbl_1'; select.dispatchEvent(new Event('change')); return select
}
const openDialog = (root: ParentNode) => { button(root, 'tableStructure').click(); return root.querySelector<HTMLDialogElement>('[aria-label="调整表格行列"]')! }
const action = (dialog: HTMLDialogElement, text: string) => [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === text)!

it('focuses a visibly labelled reference row and groups row and column operations', async () => {
  const { shell, view } = await open(); selectTable(shell.editor)
  const dialog = openDialog(shell.editor)
  const row = dialog.querySelector<HTMLSelectElement>('[aria-label="参考行"]')!
  expect(document.activeElement).toBe(row)
  expect(row.closest('label')?.textContent).toContain('参考行')
  expect(dialog.querySelector('[aria-label="参考列"]')!.closest('label')?.textContent).toContain('参考列')
  const groups = [...dialog.querySelectorAll('fieldset')]
  expect(groups.map(group => group.querySelector('legend')?.textContent)).toEqual(['行', '列'])
  expect(groups.map(group => group.querySelectorAll('button').length)).toEqual([3, 3])
  view.dispose()
})

it.each(['取消', 'Escape', '标题关闭'])('restores the structure entry and discards reference choices on %s', async method => {
  const { shell, view, draft } = await open(); selectTable(shell.editor)
  const opener = button(shell.editor, 'tableStructure'); opener.focus()
  const dialog = openDialog(shell.editor)
  dialog.querySelector<HTMLSelectElement>('[aria-label="参考行"]')!.value = '1'
  if (method === 'Escape') dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
  else if (method === '标题关闭') {
    const close = dialog.querySelector<HTMLButtonElement>('[aria-label="关闭调整表格行列"]')
    expect(close).not.toBeNull(); close!.click()
  } else action(dialog, '取消').click()
  expect(dialog.isConnected).toBe(false)
  expect(document.activeElement).toBe(opener)
  expect(draft.operations).toEqual([])
  const reopened = openDialog(shell.editor)
  expect(reopened.querySelector<HTMLSelectElement>('[aria-label="参考行"]')!.value).toBe('0')
  view.dispose()
})

it.each([
  ['在上方插入行', 'insert-row', 1, true], ['在下方插入行', 'insert-row', 1, false], ['删除行', 'delete-row', 1, undefined],
  ['在左侧插入列', 'insert-col', 2, true], ['在右侧插入列', 'insert-col', 2, false], ['删除列', 'delete-col', 2, undefined],
])('stages %s with immutable source coordinates and reversible locks', async (label, kind, index, before) => {
  const { shell, view, draft, api } = await open()
  selectTable(shell.editor)
  const dialog = openDialog(shell.editor)
  expect(dialog.open).toBe(true)
  dialog.querySelector<HTMLSelectElement>('[aria-label="参考行"]')!.value = '1'
  dialog.querySelector<HTMLSelectElement>('[aria-label="参考列"]')!.value = '2'
  action(dialog, String(label)).click()
  const expected = { slideIndex: 0, elementId: 'tbl_1', kind, index, ...(before !== undefined ? { before } : {}) }
  expect(draft.operations[0]).toMatchObject({ tableStructures: [expected] })
  expect(dialog.isConnected).toBe(false)
  expect(button(shell.editor, 'tableStructure').disabled).toBe(true)
  expect(button(shell.editor, 'tableAllBorders').disabled).toBe(true)
  expect(shell.editor.querySelector<HTMLSelectElement>('#layout-select')!.disabled).toBe(true)
  expect([...shell.editor.querySelectorAll<HTMLTextAreaElement>('[data-table-cell]')].every(field => field.disabled)).toBe(true)
  expect(shell.editor.querySelectorAll('[data-table-cell]')).toHaveLength(6)
  expect(shell.editor.querySelector('.canvas-status')!.textContent).toMatch(/保存.*打开新修订.*显示新结构/)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
  expect(draft.operations).toEqual([]); expect(button(shell.editor, 'tableStructure').disabled).toBe(false)
  shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click()
  expect(draft.operations[0]).toMatchObject({ tableStructures: [expected] })
  expect(api.renderTree.mock.calls.every(call => !JSON.stringify(call).includes('tableStructures'))).toBe(true)
  view.dispose()
})

it('recovers a valid source structure draft while retaining outside-object edits', async () => {
  const storage = store(), draft = new NativeDraft(identity, storage)
  const expected = [{ kind: 'editSlides', tableStructures: [{ slideIndex: 0, elementId: 'tbl_1', kind: 'insert-col', index: 1, before: false }], edits: [{ slideIndex: 0, elementId: 'text_0', text: 'outside edit' }] }]
  draft.setOperations(expected)
  const recovered = new NativeDraft(identity, storage)
  const { shell, view } = await open(recovered)
  selectTable(shell.editor)
  expect(recovered.operations).toEqual(expected)
  expect(button(shell.editor, 'tableStructure').disabled).toBe(true)
  const select = shell.editor.querySelector<HTMLSelectElement>('#object-select')!; select.value = 'text_0'; select.dispatchEvent(new Event('change'))
  expect(shell.editor.querySelector<HTMLTextAreaElement>('#object-text')!.value).toBe('outside edit')
  view.dispose()
})

it.each([
  [1, 1, ['删除行', '删除列']], [75, 2, ['在上方插入行', '在下方插入行']], [2, 75, ['在左侧插入列', '在右侧插入列']],
])('enforces row/column bounds for a %s by %s table even for dispatched events', async (rows, cols, labels) => {
  const { shell, view, draft } = await open(undefined, model(Number(rows), Number(cols)))
  selectTable(shell.editor); const dialog = openDialog(shell.editor)
  for (const label of labels as string[]) { const target = action(dialog, label); expect(target.disabled).toBe(true); target.dispatchEvent(new Event('click')); expect(draft.operations).toEqual([]) }
  view.dispose()
})

it('blocks unsupported and mixed-source table operations before persistence', async () => {
  const { shell, view, draft } = await open(undefined, model(2, 3, false))
  selectTable(shell.editor); expect(button(shell.editor, 'tableStructure').disabled).toBe(true)
  button(shell.editor, 'tableStructure').dispatchEvent(new Event('click')); expect(shell.editor.querySelector('dialog[open]')).toBeNull(); expect(draft.operations).toEqual([]); view.dispose()
  const editable = await open(); selectTable(editable.shell.editor)
  const cell = editable.shell.editor.querySelector<HTMLTextAreaElement>('[data-table-cell="0:0"]')!; cell.value = 'changed'; cell.dispatchEvent(new Event('change'))
  selectTable(editable.shell.editor); expect(button(editable.shell.editor, 'tableStructure').disabled).toBe(true)
  expect(editable.draft.operations[0]).not.toHaveProperty('tableStructures'); editable.view.dispose()
})

it('drops cancel/Escape/disposed dialogs and refuses stale selection, draft and tampered indices', async () => {
  const { shell, view, draft } = await open(); selectTable(shell.editor)
  let dialog = openDialog(shell.editor); action(dialog, '取消').click(); expect(draft.operations).toEqual([])
  dialog = openDialog(shell.editor); dialog.dispatchEvent(new Event('cancel', { cancelable: true })); expect(dialog.isConnected).toBe(false); expect(draft.operations).toEqual([])
  dialog = openDialog(shell.editor); dialog.querySelector<HTMLSelectElement>('[aria-label="参考行"]')!.value = ''; action(dialog, '删除行').click(); expect(draft.operations).toEqual([])
  const select = shell.editor.querySelector<HTMLSelectElement>('#object-select')!; select.value = 'text_0'; select.dispatchEvent(new Event('change')); action(dialog, '删除行').click(); expect(draft.operations).toEqual([])
  action(dialog, '取消').click(); selectTable(shell.editor); dialog = openDialog(shell.editor)
  const changed = [{ kind: 'editSlides', edits: [{ slideIndex: 0, elementId: 'text_0', text: 'external history' }] }]; draft.setOperations(changed)
  action(dialog, '删除行').click(); expect(draft.operations).toEqual(changed)
  const late = action(dialog, '在下方插入行'); view.dispose(); expect(dialog.isConnected).toBe(false)
  late.dispatchEvent(new Event('click')); expect(draft.operations).toEqual(changed)
})

it('refuses old modal callbacks while saving and after the source revision is closed', async () => {
  const { shell, view, draft } = await open(); selectTable(shell.editor)
  const dialog = openDialog(shell.editor), remove = action(dialog, '删除行')
  draft.beginSave(); remove.dispatchEvent(new Event('click'))
  expect(draft.operations).toEqual([])
  draft.saveFailed(); draft.saveCompleted({ revision: 2, revisionRegistered: true })
  remove.dispatchEvent(new Event('click')); expect(draft.operations).toEqual([])
  view.dispose(); expect(dialog.isConnected).toBe(false)
})

it('blocks stale custom-size submission after staging a structure operation', async () => {
  const { shell, view, draft } = await open()
  button(shell.editor, 'customSlideSize').click()
  const sizeDialog = shell.editor.querySelector<HTMLDialogElement>('dialog')!
  selectTable(shell.editor); action(openDialog(shell.editor), '删除行').click()
  sizeDialog.querySelector<HTMLInputElement>('[aria-label="幻灯片宽度"]')!.value = '30'
  button(sizeDialog, 'applyCustomSlideSize').dispatchEvent(new Event('click'))
  expect(draft.operations[0]).toHaveProperty('tableStructures')
  expect(draft.operations[0]).not.toHaveProperty('slideSize')
  view.dispose()
})

it.each([
  null,
  [{ slideIndex: 0, elementId: 'tbl_1', kind: 'insert-row', index: 0 }],
  [{ slideIndex: 0, elementId: 'tbl_1', kind: 'delete-row', index: 0, before: false }],
  [{ slideIndex: 0, elementId: 'foreign', kind: 'delete-row', index: 0 }],
  [{ slideIndex: 0, elementId: 'tbl_1', kind: 'delete-row', index: true }],
  [{ slideIndex: 0, elementId: 'tbl_1', kind: 'delete-row', index: 0, extra: 1 }],
  [{ slideIndex: 0, elementId: 'tbl_1', kind: 'delete-row', index: 0 }, { slideIndex: 0, elementId: 'tbl_1', kind: 'delete-col', index: 0 }],
])('preserves rejected recovered structure draft %j', async tableStructures => {
  const storage = store(), draft = new NativeDraft(identity, storage), operations = [{ kind: 'editSlides', tableStructures }]
  draft.setOperations(operations)
  await expect(open(draft)).rejects.toThrow(/原草稿已保留/)
  expect(new NativeDraft(identity, storage).operations).toEqual(operations)
})

it.each([
  { tableCells: [{ slideIndex: 0, elementId: 'tbl_1', row: 0, col: 0, text: 'changed' }] },
  { tableStyles: [{ slideIndex: 0, elementId: 'tbl_1', shadingColor: '#FFF2CC' }] },
  { slideSize: { cx: 9144000, cy: 5143500 } },
  { resetLayouts: [0] },
  { slideLayouts: [{ slideIndex: 0, layoutPath: 'ppt/slideLayouts/slideLayout1.xml' }] },
])('preserves conflicting recovered structure state %j', async conflict => {
  const storage = store(), draft = new NativeDraft(identity, storage)
  const operations = [{ kind: 'editSlides', tableStructures: [{ slideIndex: 0, elementId: 'tbl_1', kind: 'delete-row', index: 0 }], ...conflict }]
  draft.setOperations(operations); await expect(open(draft)).rejects.toThrow(/原草稿已保留/)
  expect(new NativeDraft(identity, storage).operations).toEqual(operations)
})
