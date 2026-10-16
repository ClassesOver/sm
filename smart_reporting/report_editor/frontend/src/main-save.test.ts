import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { ReportEditorApiError } from './api'

// 执行 main 的实际保存函数，隔离 Milkdown 启动与网络，控制保存途中输入的时序。
const source = ts.createSourceFile('main.ts', readFileSync('src/main.ts', 'utf8'), ts.ScriptTarget.Latest, true)
let saveFunction = ''
function findSave(node: ts.Node): void {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'saveNow') saveFunction = node.getText(source)
  ts.forEachChild(node, findSave)
}
findSave(source)
if (!saveFunction) throw new Error('saveNow not found')
const code = ts.transpileModule(`${saveFunction}\nglobalThis.run = saveNow`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText

function setup() {
  const requests: Array<{ resolve: (value: { sha256: string }) => void; reject: (error: Error) => void }> = []
  let tick = 0
  const context = {
    window: { clearTimeout: vi.fn(), setTimeout }, saveTimer: 0,
    editReviewMode: () => 'idle', evidenceView: { state: { doc: {} } },
    pendingConflict: null, savePromise: null,
    currentMarkdown: 'B', lastSavedMarkdown: 'A', sha256: 'hash-A',
    status: vi.fn(), saveState: null, draftController: null,
    conflictPanel: { show: vi.fn() }, showConflictStatus: vi.fn(), recoverFromConflict: vi.fn(),
    performance: { now: () => (tick += 1000) }, savedEditorDoc: {},
    historyController: { record: vi.fn() }, telemetry: { record: vi.fn() },
    reviewMode: 'idle', savedLabel: () => 'saved',
    getEditorMarkdown: () => context.currentMarkdown,
    errorLabel: () => 'save failed', saveInBackground: vi.fn(), ReportEditorApiError,
    client: { load: vi.fn(async () => ({ markdown: 'remote', sha256: 'hash-remote' })),
      save: vi.fn((_markdown: string, _sha: string) => new Promise<{ sha256: string }>((resolve, reject) => {
      requests.push({ resolve, reject })
    })) },
  }
  const sandbox = vm.createContext(context)
  vm.runInContext(code, sandbox)
  return { context, requests, save: sandbox.run as () => Promise<void> }
}

describe('saveNow before export', () => {
  it('offers the latest edits for merging after a save conflict and remote reload', async () => {
    const { context, requests, save } = setup()
    let resolveRemote!: (value: { markdown: string; sha256: string }) => void
    context.client.load.mockImplementation(() => new Promise((resolve) => { resolveRemote = resolve }))
    const conflict = new ReportEditorApiError(409, 'report_editor_conflict')
    const failed = expect(save()).rejects.toBe(conflict)
    context.currentMarkdown = 'C'
    requests[0]!.reject(conflict)
    await vi.waitFor(() => expect(context.client.load).toHaveBeenCalledOnce())
    context.currentMarkdown = 'D'
    resolveRemote({ markdown: 'remote', sha256: 'hash-remote' })
    await failed
    expect(context.conflictPanel.show).toHaveBeenCalledWith('A', 'D', 'remote')
    expect(context.currentMarkdown).toBe('D')
    expect(context.lastSavedMarkdown).toBe('A')
    expect(context.sha256).toBe('hash-A')
    expect(context.client.save).toHaveBeenCalledTimes(1)
  })

  it('retries a failed conflict lookup without choosing the remote version', async () => {
    const { context, requests, save } = setup()
    const conflict = new ReportEditorApiError(409, 'report_editor_conflict')
    context.client.load.mockRejectedValueOnce(new Error('offline'))
    const failed = expect(save()).rejects.toBe(conflict)
    context.currentMarkdown = 'C'
    requests[0]!.reject(conflict)
    await failed
    const retry = context.status.mock.calls.at(-1)![2] as () => void
    let retried!: Promise<void>
    context.saveInBackground.mockImplementation(() => {
      retried = save().catch(() => undefined)
    })
    retry()
    expect(context.recoverFromConflict).not.toHaveBeenCalled()
    expect(context.client.save).toHaveBeenLastCalledWith('C', 'hash-A')
    requests[1]!.reject(conflict)
    await retried
    expect(context.client.load).toHaveBeenCalledTimes(2)
    expect(context.conflictPanel.show).toHaveBeenCalledWith('A', 'C', 'remote')
    expect(context.currentMarkdown).toBe('C')
    expect(context.sha256).toBe('hash-A')
  })

  it.each([false, true])('waits for edits during a save (another waiting caller: %s)', async (anotherCaller) => {
    const { context, requests, save } = setup()
    let finished = false
    const first = save()
    const waiting = anotherCaller ? save() : first
    const exported = waiting.then(() => { finished = true; return context.sha256 })
    context.currentMarkdown = 'C'
    requests[0]!.resolve({ sha256: 'hash-B' })
    await vi.waitFor(() => expect(context.client.save).toHaveBeenCalledTimes(2))
    expect(context.client.save).toHaveBeenLastCalledWith('C', 'hash-B')
    expect(finished).toBe(false)
    requests[1]!.resolve({ sha256: 'hash-C' })
    await first
    expect(await exported).toBe('hash-C')
    expect(context.lastSavedMarkdown).toBe('C')
    expect(context.client.save).toHaveBeenCalledTimes(2)
  })

  it('rejects export when saving the newer edits fails', async () => {
    const { context, requests, save } = setup()
    const failed = expect(save()).rejects.toThrow('offline')
    context.currentMarkdown = 'C'
    requests[0]!.resolve({ sha256: 'hash-B' })
    await vi.waitFor(() => expect(context.client.save).toHaveBeenCalledTimes(2))
    requests[1]!.reject(new Error('offline'))
    await failed
    expect(context.lastSavedMarkdown).toBe('B')
    expect(context.currentMarkdown).toBe('C')
  })
})
