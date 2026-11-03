import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import fixture from './fixtures/report-design.json'
import { ReportEditorApiError } from './api'

// 执行实际导出入口，验证正文与设计同步完毕之后发送同一设计版本。
const source = ts.createSourceFile('main.ts', readFileSync('src/main.ts', 'utf8'), ts.ScriptTarget.Latest, true)
let exportFunction = ''
function findExport(node: ts.Node): void {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'exportFormat') exportFunction = node.getText(source)
  ts.forEachChild(node, findExport)
}
findExport(source)
const code = ts.transpileModule(`${exportFunction}\nglobalThis.run = exportFormat`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
function setup(designEnabled = true) {
  const events: string[] = []
  let designHash = 'old-design'
  const context = {
    performance: { now: () => 0 }, root: {}, shell: { editor: {} }, initialFormalHeadings: [],
    setActionsDisabled: vi.fn(), status: vi.fn(), reportPreflight: () => [], getEditorMarkdown: () => '# 报告',
    saveNow: async () => { events.push('save-markdown') }, sha256: 'body-sha',
    designPanel: designEnabled ? {
      flush: async () => { events.push('save-design'); designHash = 'saved-design' },
      read: () => ({ design: fixture, designSha256: designHash, note: '设计版' }),
    } : null,
    designState: null, blockUI: vi.fn(), unblockUI: vi.fn(),
    pendingExportSettings: null, exportSettingsPanel: { read: () => ({ cover: false, sources: false, note: '旧版' }) },
    client: { export: vi.fn(async () => { events.push('export'); return { revision: 2 } }) },
    telemetry: { record: vi.fn() }, exportPanel: { show: vi.fn() }, ReportEditorApiError,
    errorStatusLabel: () => '保存冲突',
  }
  const sandbox = vm.createContext(context)
  vm.runInContext(code, sandbox)
  return { context, events, run: sandbox.run as (format: string) => Promise<void> }
}
describe('report design export integration', () => {
  it('flushes both drafts and exports the saved design options with its matching hash', async () => {
    const { context, events, run } = setup()
    await run('word')
    expect(events).toEqual(['save-markdown', 'save-design', 'export'])
    expect(context.client.export).toHaveBeenCalledWith('body-sha', fixture.options, '设计版', 'saved-design')
  })
  it('preserves legacy exports for documents without server design', async () => {
    const { context, events, run } = setup(false)
    await run('pdf')
    expect(events).toEqual(['save-markdown', 'export'])
    expect(context.client.export).toHaveBeenCalledWith('body-sha', { cover: false, sources: false }, '旧版', undefined)
  })
  it('blocks new editing before saving drafts so the design save cannot leave newer text behind', async () => {
    const { context, run } = setup()
    context.saveNow = async () => {
      if (!context.blockUI.mock.calls.length) throw new Error('editing remained enabled during save')
    }
    await run('pdf')
    expect(context.client.export).toHaveBeenCalledOnce()
  })
  it('keeps the draft available and avoids exporting a silently overwritten design after conflict', async () => {
    const { context, run } = setup()
    context.designPanel!.flush = async () => { throw new ReportEditorApiError(409, 'report_editor_design_conflict') }
    await run('pdf')
    expect(context.client.export).not.toHaveBeenCalled()
    expect(context.status).toHaveBeenLastCalledWith('PDF 导出失败：保存冲突', 'error', expect.any(Function))
    expect(context.setActionsDisabled).toHaveBeenLastCalledWith(false)
  })
})
