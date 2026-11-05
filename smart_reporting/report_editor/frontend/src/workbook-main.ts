import { askAIPanel } from './ask-ai-panel'
import { createAITaskAdapter } from './ai-task'
import { renderWorkbookProposal } from './workbook-ai-preview'
import { LocaleType, mergeLocales } from '@univerjs/core'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import CoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN'
import '@univerjs/preset-sheets-core/lib/index.css'
import { readWorkbook, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createUniver } from './workbook-vendor/grid/create-univer'
import { loadWorkbookData, readBack } from './workbook-vendor/grid/sync'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { geometryChanges } from './workbook-vendor/core/data-tools'
import { WorkbookDraft, workbookSaveOutcome, type WorkbookOperation, type WorkbookProposal, type WorkbookSaveResult } from './workbook-draft'
import type { EditorShell } from './shell'
import { gridMergeChanges, planGridSheets, structuralMutation, type GridSnapshot } from './workbook-grid-operations'
import { withWorkbookLocked } from './workbook-grid-guards'
import { requestJson } from './api-request'
import './workbook.css'


export async function createWorkbookEditorView(shell: EditorShell) {
  const base = location.pathname.replace(/\/$/, '')
  const draft = new WorkbookDraft()
  const request = <T>(path: string, payload?: unknown): Promise<T> => requestJson(
    `${base}/api/${path}`,
    payload === undefined ? {} : { method: 'POST', body: JSON.stringify(payload) },
    'report_workbook_csrf',
  )
  shell.editor.innerHTML = `
    <div class="workbook-feedback" role="status" aria-live="polite"></div>
    <div id="workbook-grid" class="workbook-grid" aria-label="报告工作簿"></div>`
  const feedback = shell.editor.querySelector<HTMLElement>('.workbook-feedback')!
  let original: Uint8Array
  let currentModel!: WorkbookModel
  let expectedSha256 = ''
  let staged: WorkbookOperation[] = []
  let dirty = false
  // 新修订已登记后不再从当前底稿保存，避免重复生成修订。
  let saved = false
  let loading = true
  let structural: NonNullable<ReturnType<typeof structuralMutation>>[] = []
  let acceptedSnapshot = ''
  const runtime = createUniver({
    locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN) },
    presets: [UniverSheetsCorePreset({ container: 'workbook-grid', header: false, toolbar: true, contextMenu: true, formulaBar: true, footer: { sheetBar: true, statisticBar: true } })],
  })
  const markDirty = () => {
    dirty = true
    shell.statusLabel.textContent = '有未保存修改'
    shell.refreshToolbar()
  }
  for (const [id, label, command] of [
    ['workbook-merge', '合并单元格', 'sheet.command.add-worksheet-merge-all'],
    ['workbook-unmerge', '取消合并', 'sheet.command.remove-worksheet-merge'],
  ]) shell.registerToolbarAction({ id, label, bar: 'format', disabled: () => loading || saved || shell.editor.inert,
    run: async () => {
      const applied = await runtime.univerAPI.executeCommand(command)
      feedback.textContent = applied ? '布局已更新，尚未保存。' : '请选择单元格区域。'
    },
  })
  runtime.univerAPI.onCommandExecuted(command => {
    if (!loading) {
      const workbook = runtime.univerAPI.getActiveWorkbook()
      const sheet = workbook?.getActiveSheet?.()
      const range = workbook?.getActiveRange?.()
      if (sheet) shell.setContextTarget({ kind: 'cells', label: `${sheet.getSheetName()} · ${range?.getA1Notation() ?? 'A1'}` })
    }
    if (!loading && command.id.startsWith('sheet.mutation.')) {
      const mutation = structuralMutation(command.id, command.params)
      if (mutation) structural.push(mutation)
      markDirty()
    }
  })
  const currentOperations = async (): Promise<WorkbookOperation[]> => {
    const readback = readBack(runtime)
    const workbook = runtime.univerAPI.getActiveWorkbook()
    const snapshot = workbook!.getSnapshot() as unknown as GridSnapshot
    const plan = planGridSheets(currentModel.sheets.map(sheet => sheet.name), snapshot)
    const ops: WorkbookOperation[] = [...staged]
    const sheetChanged = plan.renames.length || plan.additions.length || plan.removals.length ||
      plan.order.some((name, index) => name !== currentModel.sheets[index]?.name)
    if (sheetChanged) ops.push({ kind: 'applySheetEdits', plan })
    for (const mutation of structural) {
      const name = snapshot.sheets[mutation.sheetId]?.name
      if (name) ops.push({ kind: 'applyRowColumnOps', sheetName: name, ops: [mutation.op] })
    }
    const baseline = sheetChanged || structural.length
      ? await readWorkbook(await applyWorkbookOperations(original, ops)) : currentModel
    const edits = diffToEdits(baseline, readback)
    const geometry = geometryChanges(baseline, readback)
    if (edits.length) ops.push({ kind: 'applyCellEdits', edits })
    for (const change of gridMergeChanges(baseline, readback)) ops.push({ kind: 'applySheetMerges', ...change })
    for (const change of geometry.columns) ops.push({ kind: 'applyColumnWidths', sheetName: change.sheet, entries: [{ index: change.index, widthChars: change.widthChars }] })
    for (const change of geometry.rows) ops.push({ kind: 'applyRowHeights', sheetName: change.sheet, entries: [{ index: change.index, heightPoints: change.heightPoints }] })
    return ops
  }
  const loadOperations = async (ops: WorkbookOperation[]) => {
    loading = true
    const bytes = ops.length ? await applyWorkbookOperations(original, ops) : original
    currentModel = await readWorkbook(bytes)
    loadWorkbookData(runtime, buildWorkbookData(currentModel, 'report-workbook', '报告工作簿'))
    staged = structuredClone(ops)
    structural = []
    loading = false
  }
  try {
    const response = await fetch(`${base}/api/file`, { credentials: 'same-origin' })
    if (!response.ok) throw new Error('工作簿载入失败，请刷新重试。')
    expectedSha256 = response.headers.get('X-Workbook-Sha256') ?? ''
    original = new Uint8Array(await response.arrayBuffer())
    await loadOperations([])
    shell.editor.setAttribute('aria-busy', 'false')
    shell.status.setAttribute('aria-busy', 'false')
    shell.statusLabel.textContent = '已保存'
    const revision = base.split('/').at(-1)
    document.querySelector<HTMLElement>('.revision-label')!.textContent = `工作簿 · 修订 ${revision}`
    document.querySelector<HTMLElement>('.structure-status')!.textContent = `${currentModel.sheets.length} 个工作表`
    shell.exportXlsx.href = `${base}/api/file`
    shell.exportXlsx.download = 'report.xlsx'
    shell.exportXlsx.hidden = false
  } catch (error) {
    feedback.textContent = (error as Error).message
    shell.statusLabel.textContent = '载入失败'
    shell.save.disabled = true
    return
  }
  let aiTarget: { sheet: string; range: string } | undefined
  const aiSession = askAIPanel().createTaskSession({
    kind: 'workbook', label: '工作簿',
    context: '候选包含当前未保存修改。检查工作表、单元格和公式变更后采纳，保存需单独操作。',
    suggestions: [
      { label: '统一数字格式', instruction: '统一金额列的数字格式，使用千分位并保留两位小数，不修改原始数值。' },
      { label: '突出表头与合计', instruction: '突出显示表头与合计行，保留原始数据和公式。' },
      { label: '调整列宽', instruction: '调整列宽，使表头和主要数值完整可读。' },
    ],
    refinements: ['保留所有原始数值和公式', '数值统一保留两位小数', '突出显示合计行'],
    captureInput: async () => ({ snapshot: { expectedSha256, operations: await currentOperations() } }),
    adapter: createAITaskAdapter<WorkbookProposal>({
      kind: 'workbook-edit',
      request: (path, init) => requestJson(`${base}/api/${path}`, init, 'report_workbook_csrf'),
      validateTarget: () => { if (saved || loading) throw new Error('请在当前可编辑修订中重试。') },
      renderProposal: renderWorkbookProposal,
      withDraftLock: async action => {
        if (shell.editor.inert) throw new Error('工作簿正在处理其他操作。')
        shell.save.disabled = true
        try { return await withWorkbookLocked(shell.editor, action) }
        finally { shell.save.disabled = saved; shell.refreshToolbar() }
      },
      locateTarget: () => {
        const workbook = runtime.univerAPI.getActiveWorkbook()
        const sheet = aiTarget && workbook?.getSheetByName(aiTarget.sheet)
        if (!sheet || !aiTarget) return false
        workbook!.setActiveSheet(sheet); workbook!.setActiveRange(sheet.getRange(aiTarget.range))
        sheet.scrollToCell?.(sheet.getRange(aiTarget.range).getRow(), sheet.getRange(aiTarget.range).getColumn())
        return true
      },
      applyProposal: async proposal => {
        const workbook = runtime.univerAPI.getActiveWorkbook()
        const sheet = workbook?.getActiveSheet?.()
        const range = workbook?.getActiveRange?.()
        aiTarget = sheet ? { sheet: sheet.getSheetName(), range: range?.getA1Notation() ?? 'A1' } : undefined
        const before = await currentOperations()
        const next = [...before, ...proposal.operations]
        await loadOperations(next)
        draft.setOperations(before); draft.preview(proposal); draft.accept()
        acceptedSnapshot = JSON.stringify(await currentOperations())
        markDirty()
      },
      undo: async () => {
        await withWorkbookLocked(shell.editor, async () => {
          if (saved || JSON.stringify(await currentOperations()) !== acceptedSnapshot) throw new Error('采纳后已有其他修改，请先用网格撤销这些修改。')
          draft.undo(); await loadOperations(draft.operations); markDirty()
        })
      },
    }),
  })
  shell.setContextTarget({ kind: 'cells', label: '工作簿单元格' })
  shell.registerToolbarAction({ id: 'workbook-ai', bar: 'context', label: 'Ask AI', disabled: () => saved || loading,
    run: () => aiSession.open(),
  })
  shell.registerToolbarAction({ id: 'save', bar: 'public', label: '保存', disabled: () => saved || loading || shell.editor.inert, run: async () => {
    if (saved) return
    shell.save.disabled = true
    shell.editor.inert = true
    shell.statusLabel.textContent = '正在保存'
    try {
      const result = await request<WorkbookSaveResult & { xlsx: { downloadUrl?: string }; validation: { ok: boolean; issues: { message: string }[] } }>('save', { expectedSha256, operations: await currentOperations() })
      const outcome = workbookSaveOutcome(result)
      dirty = outcome.kind === 'retry'
      saved = outcome.kind !== 'retry'
      shell.statusLabel.textContent = outcome.status
      if (result.xlsx.downloadUrl) { shell.exportXlsx.href = result.xlsx.downloadUrl; shell.exportXlsx.hidden = false }
      feedback.textContent = result.validation.issues.map(issue => issue.message).join('；') || '新修订已保存。'
      if (outcome.kind === 'reopen') location.assign(outcome.url)
    } catch (error) { shell.statusLabel.textContent = '保存失败，草稿已保留'; feedback.textContent = (error as Error).message }
    finally { shell.save.disabled = saved; shell.editor.inert = saved }
  } })
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = '' }
  })
}
