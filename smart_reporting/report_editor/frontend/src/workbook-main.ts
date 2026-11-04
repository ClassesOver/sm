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

type AIStatus = { editId: string; status: string; snapshotSha256: string; proposal?: WorkbookProposal; error?: { message: string } }

export async function createWorkbookEditorView(shell: EditorShell) {
  const base = location.pathname.replace(/\/$/, '')
  const draft = new WorkbookDraft()
  const request = <T>(path: string, payload?: unknown): Promise<T> => requestJson(
    `${base}/api/${path}`,
    payload === undefined ? {} : { method: 'POST', body: JSON.stringify(payload) },
    'report_workbook_csrf',
  )
  shell.editor.innerHTML = `
    <section class="workbook-ai" aria-label="工作簿 AI 编辑"><form><label for="workbook-instruction">Ask AI</label><textarea id="workbook-instruction" maxlength="2000" rows="2" placeholder="描述要调整的单元格、公式或样式"></textarea><button type="submit">生成候选</button><button type="button" class="workbook-undo" disabled>撤销 AI 采纳</button></form><div class="workbook-feedback" role="status" aria-live="polite"></div><div class="workbook-candidate" hidden><strong></strong><pre></pre><button type="button" class="workbook-accept">采纳到草稿</button><button type="button" class="workbook-reject">拒绝</button></div><div class="workbook-actions" role="toolbar" aria-label="单元格布局"><button type="button" data-workbook-command="sheet.command.add-worksheet-merge-all">合并单元格</button><button type="button" data-workbook-command="sheet.command.remove-worksheet-merge">取消合并</button></div></section>
    <div id="workbook-grid" class="workbook-grid" aria-label="报告工作簿"></div>`
  const feedback = shell.editor.querySelector<HTMLElement>('.workbook-feedback')!
  const form = shell.editor.querySelector<HTMLFormElement>('form')!
  const instruction = shell.editor.querySelector<HTMLTextAreaElement>('textarea')!
  const submit = form.querySelector<HTMLButtonElement>('[type="submit"]')!
  const candidate = shell.editor.querySelector<HTMLElement>('.workbook-candidate')!
  const accept = candidate.querySelector<HTMLButtonElement>('.workbook-accept')!
  const reject = candidate.querySelector<HTMLButtonElement>('.workbook-reject')!
  const undo = form.querySelector<HTMLButtonElement>('.workbook-undo')!
  let original: Uint8Array
  let currentModel!: WorkbookModel
  let expectedSha256 = ''
  let staged: WorkbookOperation[] = []
  let aiId = ''
  let candidateOperations = ''
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
    if (!candidate.hidden) feedback.textContent = '内容已变化时需重新生成 AI 候选。'
  }
  for (const button of shell.editor.querySelectorAll<HTMLButtonElement>('[data-workbook-command]')) {
    button.addEventListener('click', async () => {
      button.disabled = true
      try {
        const applied = await runtime.univerAPI.executeCommand(button.dataset.workbookCommand!)
        feedback.textContent = applied ? '合并布局已更新，尚未保存。' : '请选择要合并或取消合并的单元格区域。'
      } catch (error) { feedback.textContent = (error as Error).message }
      finally { button.disabled = false }
    })
  }
  runtime.univerAPI.onCommandExecuted(command => {
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
  const hideCandidate = () => { candidate.hidden = true; draft.reject(); aiId = '' }
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
    submit.disabled = true
    return
  }
  form.addEventListener('submit', async event => {
    event.preventDefault()
    submit.disabled = true
    hideCandidate()
    feedback.textContent = '正在生成候选；包含当前未保存修改。'
    try {
      const ops = await currentOperations()
      draft.setOperations(ops)
      candidateOperations = JSON.stringify(ops)
      let status = await request<AIStatus>('ai/start', { instruction: instruction.value, operations: ops })
      aiId = status.editId
      while (status.status === 'running') status = await request<AIStatus>(`ai/${aiId}?wait_ms=20000`)
      if (status.status !== 'succeeded' || !status.proposal) throw new Error(status.error?.message ?? 'AI 候选未生成。')
      draft.preview(status.proposal)
      candidate.querySelector('strong')!.textContent = status.proposal.summary
      candidate.querySelector('pre')!.textContent = JSON.stringify(status.proposal.operations, null, 2)
      candidate.hidden = false
      feedback.textContent = '候选尚未改变草稿，采纳后可撤销。'
    } catch (error) { feedback.textContent = (error as Error).message }
    finally { submit.disabled = false }
  })
  reject.addEventListener('click', () => {
    if (aiId) void request(`ai/${aiId}/cancel`, {}).catch(() => {})
    hideCandidate()
    feedback.textContent = '已拒绝候选，草稿保持原样。'
  })
  accept.addEventListener('click', async () => {
    accept.disabled = true
    shell.save.disabled = true
    try {
      await withWorkbookLocked(shell.editor, async () => {
        const ops = await currentOperations()
        draft.setOperations(ops)
        if (JSON.stringify(ops) !== candidateOperations) throw new Error('工作簿内容已变化，请重新生成候选。')
        await request(`ai/${aiId}/accept`, { operations: ops })
        draft.accept()
        await loadOperations(draft.operations)
        candidate.hidden = true
        undo.disabled = false
        acceptedSnapshot = JSON.stringify(await currentOperations())
        markDirty()
        feedback.textContent = '候选已进入草稿，尚未保存。'
      })
    } catch (error) { feedback.textContent = (error as Error).message }
    finally { accept.disabled = false; shell.save.disabled = saved }
  })
  undo.addEventListener('click', async () => {
    if (JSON.stringify(await currentOperations()) !== acceptedSnapshot) {
      feedback.textContent = '采纳后又有手动修改，请使用网格撤销，或保存当前草稿后重新编辑。'
      return
    }
    draft.undo()
    await loadOperations(draft.operations)
    undo.disabled = true
    markDirty()
    feedback.textContent = '已撤销 AI 采纳，恢复采纳前草稿。'
  })
  shell.save.addEventListener('click', async () => {
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
  })
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = '' }
  })
}
