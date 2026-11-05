import { afterEach, expect, it, vi } from 'vitest'
const locationCalls = vi.hoisted(() => ({ select: vi.fn(), scroll: vi.fn() }))
vi.mock('@univerjs/core', () => ({ LocaleType: { ZH_CN: 'zh' }, mergeLocales: () => ({}) }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: vi.fn() }))
vi.mock('@univerjs/preset-sheets-core/locales/zh-CN', () => ({ default: {} }))
vi.mock('@sheets-web/xlsx-engine', () => ({ readWorkbook: async () => ({ sheets: [{ name: 'Sheet1' }] }) }))
vi.mock('../../../reporting/workbook_engine/bridge/operations', () => ({ applyWorkbookOperations: async (bytes: Uint8Array) => bytes }))
vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: () => ({ univerAPI: {
  onCommandExecuted: vi.fn(), executeCommand: vi.fn(), getActiveWorkbook: () => ({ getSnapshot: () => ({}),
    getActiveSheet: () => ({ getSheetName: () => 'Sheet1' }), getActiveRange: () => ({ getA1Notation: () => 'B5' }),
    getSheetByName: () => ({ getRange: () => ({ getRow: () => 4, getColumn: () => 1 }), scrollToCell: locationCalls.scroll }),
    setActiveSheet: vi.fn(), setActiveRange: locationCalls.select,
  }),
} }) }))
vi.mock('./workbook-vendor/grid/sync', () => ({ loadWorkbookData: vi.fn(), readBack: () => ({}) }))
vi.mock('./workbook-vendor/core/univer-data', () => ({ buildWorkbookData: () => ({}) }))
vi.mock('./workbook-vendor/core/session-core', () => ({ diffToEdits: () => [] }))
vi.mock('./workbook-vendor/core/data-tools', () => ({ geometryChanges: () => ({ columns: [], rows: [] }) }))
vi.mock('./workbook-grid-operations', () => ({ gridMergeChanges: () => [], structuralMutation: () => null,
  planGridSheets: () => ({ renames: [], additions: [], removals: [], order: ['Sheet1'] }),
}))
import { createEditorShell } from './shell'
import { createWorkbookEditorView } from './workbook-main'
afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren() })
it('routes workbook AI through the shared session, previews, applies and undoes before separate save', async () => {
  const root = document.createElement('main'); document.body.append(root)
  const shell = createEditorShell(root, 'full', 'xlsx')
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('xlsx', { headers: { 'X-Workbook-Sha256': 'a'.repeat(64) } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ taskId: 'workbook-task' })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ taskId: 'workbook-task', kind: 'workbook-edit', state: 'ready', proposal: { summary: '修改工作表', operations: [] } })))
    .mockResolvedValueOnce(new Response('{}'))
  vi.stubGlobal('fetch', fetcher)
  await createWorkbookEditorView(shell)
  root.querySelector<HTMLButtonElement>('[data-action="workbook-ai"]')!.click()
  document.querySelector<HTMLTextAreaElement>('.ask-ai-composers textarea')!.value = '整理工作表'
  document.querySelector('.ask-ai-composers form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(document.querySelector('.ai-task-preview')!.textContent).toContain('修改工作表'))
  expect(root.querySelector('.workbook-candidate')).toBeNull()
  document.querySelector<HTMLButtonElement>('[data-task-action="accept"]')!.click()
  await vi.waitFor(() => expect(document.querySelector('.ai-task-feedback')!.textContent).toContain('已采纳到草稿'))
  expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/save'))).toBe(false)
  document.querySelector<HTMLButtonElement>('[data-task-action="locate"]')!.click()
  await vi.waitFor(() => expect(locationCalls.scroll).toHaveBeenCalledWith(4, 1))
  root.querySelector<HTMLButtonElement>('[data-action="workbook-ai"]')!.click()
  document.querySelector<HTMLButtonElement>('[data-task-action="undo"]')!.click()
  await vi.waitFor(() => expect(document.querySelector('.ai-task-feedback')!.textContent).toContain('已撤销'))
  const start = fetcher.mock.calls.find(([path]) => String(path).endsWith('/ai/tasks'))!
  expect(JSON.parse(start[1]!.body as string)).toMatchObject({ kind: 'workbook-edit', snapshot: { expectedSha256: 'a'.repeat(64), operations: [] } })
})
