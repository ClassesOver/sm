import { LocaleType, mergeLocales } from '@univerjs/core'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import { UniverSheetsFindReplacePreset } from '@univerjs/preset-sheets-find-replace'
import { UniverSheetsDrawingPreset } from '@univerjs/preset-sheets-drawing'
import { UniverSheetsTablePreset } from '@univerjs/preset-sheets-table'
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
import { stepSelectionDecimals } from './workbook-vendor/grid/decimal-step'
import {
  applyWorkbookRibbonCommand,
  mountWorkbookRibbon,
  type RibbonWorkbook,
} from './workbook-ribbon'
import { requestJson } from './api-request'
import type { NativeDraft, NativeOperation } from './native-draft'
import './workbook.css'

type AIStatus = { editId: string; status: string; snapshotSha256: string; proposal?: WorkbookProposal; error?: { message: string } }

export interface WorkbookEditorOptions {
  request?: <T>(path: string, payload?: unknown) => Promise<T>
  file?: () => Promise<{ bytes: ArrayBuffer; sha256: string }>
  native?: boolean
  draft?: NativeDraft
}

export async function createWorkbookEditorView(shell: EditorShell, options: WorkbookEditorOptions = {}) {
  const base = location.pathname.replace(/\/$/, '')
  const draft = new WorkbookDraft()
  const nativeDraft = options.native ? options.draft : undefined
  const request = options.request ?? (<T>(path: string, payload?: unknown): Promise<T> => requestJson(
    `${base}/api/${path}`,
    payload === undefined ? {} : { method: 'POST', body: JSON.stringify(payload) },
    'report_workbook_csrf',
  ))
  shell.editor.innerHTML = `
    <section class="workbook-ai" aria-label="工作簿 AI 编辑"><form><label for="workbook-instruction">Ask AI</label><textarea id="workbook-instruction" maxlength="2000" rows="2" placeholder="描述要调整的单元格、公式或样式"></textarea><button type="submit">生成候选</button><button type="button" class="workbook-undo" disabled>撤销 AI 采纳</button></form><div class="workbook-feedback" role="status" aria-live="polite"></div><div class="workbook-candidate" hidden><strong></strong><pre></pre><button type="button" class="workbook-accept">采纳到草稿</button><button type="button" class="workbook-reject">拒绝</button></div></section>
    <div class="workbook-ribbon-host"></div>
    <div id="workbook-grid" class="workbook-grid" aria-label="报告工作簿"></div>`
  const feedback = shell.editor.querySelector<HTMLElement>('.workbook-feedback')!
  const form = shell.editor.querySelector<HTMLFormElement>('form')!
  const instruction = shell.editor.querySelector<HTMLTextAreaElement>('textarea')!
  const submit = form.querySelector<HTMLButtonElement>('[type="submit"]')!
  const candidate = shell.editor.querySelector<HTMLElement>('.workbook-candidate')!
  const accept = candidate.querySelector<HTMLButtonElement>('.workbook-accept')!
  const reject = candidate.querySelector<HTMLButtonElement>('.workbook-reject')!
  const undo = form.querySelector<HTMLButtonElement>('.workbook-undo')!
  if (options.native) { form.hidden = true; form.inert = true; submit.disabled = true }
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
  let saving = false
  let disposed = false
  let gridChanged = false
  let captureGeneration = 0
  let persistence = Promise.resolve()
  let structural: NonNullable<ReturnType<typeof structuralMutation>>[] = []
  let acceptedSnapshot = ''
  const runtime = createUniver({
    locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN) },
    presets: [
      UniverSheetsCorePreset({ container: 'workbook-grid', header: false, toolbar: true, contextMenu: true, formulaBar: true, footer: { sheetBar: true, statisticBar: true } }),
      UniverSheetsFindReplacePreset(),
      UniverSheetsDrawingPreset(),
      UniverSheetsTablePreset(),
    ],
  })
  const markDirty = () => {
    if (loading || saving || saved || disposed) return
    dirty = true
    gridChanged = true
    shell.statusLabel.textContent = '有未保存修改'
    if (!candidate.hidden) feedback.textContent = '内容已变化时需重新生成 AI 候选。'
    if (nativeDraft) {
      // 连续 mutation 只采集最新网格；异步结构操作不得让旧快照覆盖新草稿。
      const generation = ++captureGeneration
      persistence = persistence.then(async () => {
        if (generation !== captureGeneration || disposed) return
        const operations = await currentOperations()
        if (generation !== captureGeneration || disposed) return
        nativeDraft.setOperations(operations as NativeOperation[])
        if (nativeDraft.persistenceError) feedback.textContent = nativeDraft.persistenceError
      }).catch(error => { feedback.textContent = `本地草稿暂未更新：${(error as Error).message}` })
    }
  }
  const ribbon = mountWorkbookRibbon(
    shell.editor.querySelector<HTMLElement>('.workbook-ribbon-host')!,
    command => {
      if (loading || saving || saved || disposed) return
      const workbook = runtime.univerAPI.getActiveWorkbook()
      if (!workbook) return
      try {
        const applied = applyWorkbookRibbonCommand(
          command,
          workbook as unknown as RibbonWorkbook,
          step => stepSelectionDecimals(runtime, step),
        )
        if (!applied) {
          feedback.textContent = 'Select a cell or range first.'
          return
        }
        markDirty()
        feedback.textContent = command === 'insert-sheet'
          ? 'New worksheet added; changes are not saved.'
          : 'Selection updated; changes are not saved.'
      } catch (error) { feedback.textContent = (error as Error).message }
    },
  )
  runtime.univerAPI.onCommandExecuted(command => {
    if (!loading && !saving && !saved && command.id.startsWith('sheet.mutation.')) {
      const mutation = structuralMutation(command.id, command.params)
      if (mutation) {
        const trigger = (command.params as { trigger?: string }).trigger
        const inverse = mutation.op.kind.startsWith('insert-')
          ? mutation.op.kind.replace('insert-', 'remove-') : mutation.op.kind.replace('remove-', 'insert-')
        const undone = trigger === 'univer.command.undo' ? structural.findLastIndex(item =>
          item.sheetId === mutation.sheetId && item.op.kind === inverse &&
          item.op.index === mutation.op.index && item.op.count === mutation.op.count) : -1
        // 仅真实 Univer Undo 撤回对应结构日志；手动删后插仍须保留破坏性引用语义。
        if (undone >= 0) structural.splice(undone, 1)
        else structural.push(mutation)
      }
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
    // 公式缓存由 Univer 自动重算，不属于编辑；恢复后不得因此追加重复操作并更换重试身份。
    for (const sheet of readback.sheets) {
      const before = baseline.sheets.find(item => item.name === sheet.name)
      for (const [address, cell] of Object.entries(sheet.cells)) {
        const originalCell = before?.cells[address]
        if (cell.formula && cell.formula === originalCell?.formula) cell.value = originalCell.value
      }
    }
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
    if (options.file) {
      const file = await options.file()
      expectedSha256 = file.sha256
      original = new Uint8Array(file.bytes)
    } else {
      const response = await fetch(`${base}/api/file`, { credentials: 'same-origin' })
      if (!response.ok) throw new Error('工作簿载入失败，请刷新重试。')
      expectedSha256 = response.headers.get('X-Workbook-Sha256') ?? ''
      original = new Uint8Array(await response.arrayBuffer())
    }
    if (nativeDraft && nativeDraft.identity.sourceSha256 !== expectedSha256) throw new Error('工作簿来源已变化，草稿已保留，请重新打开。')
    await loadOperations(nativeDraft?.operations ?? [])
    dirty = nativeDraft?.dirty ?? false
    shell.editor.setAttribute('aria-busy', 'false')
    shell.status.setAttribute('aria-busy', 'false')
    shell.statusLabel.textContent = dirty ? '有未保存修改 · 已恢复本地草稿' : '已保存'
    if (nativeDraft?.persistenceError) feedback.textContent = nativeDraft.persistenceError
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
    if (options.native) { runtime.univer.dispose(); throw error }
    return
  }
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (options.native) return
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
    if (options.native) return
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
  const save = async () => {
    if (saved || saving) return
    saving = true
    shell.save.disabled = true
    shell.editor.inert = true
    shell.statusLabel.textContent = '正在保存'
    try {
      await persistence
      // 未继续编辑的恢复草稿原样重试，保留服务端幂等请求身份。
      const operations = nativeDraft && !gridChanged ? nativeDraft.operations : await currentOperations()
      nativeDraft?.setOperations(operations as NativeOperation[])
      const result = await request<WorkbookSaveResult & { xlsx: { downloadUrl?: string }; validation: { ok: boolean; issues: { message: string }[] } }>('save', { expectedSha256, operations })
      const outcome = workbookSaveOutcome(result)
      dirty = outcome.kind === 'retry'
      saved = outcome.kind !== 'retry'
      shell.statusLabel.textContent = outcome.status
      if (result.xlsx.downloadUrl) { shell.exportXlsx.href = result.xlsx.downloadUrl; shell.exportXlsx.hidden = false }
      feedback.textContent = result.validation.issues.map(issue => issue.message).join('；') || '新修订已保存。'
      if (outcome.kind === 'reopen') {
        if (!options.native) location.assign(outcome.url)
        else {
          const reopen = document.createElement('a'); reopen.className = 'native-next-revision'; reopen.href = outcome.url; reopen.textContent = '打开新修订继续编辑'
          feedback.append(' · ', reopen)
        }
      }
    } catch (error) { shell.statusLabel.textContent = '保存失败，草稿已保留'; feedback.textContent = (error as Error).message }
    finally {
      saving = false
      shell.save.disabled = saved
      shell.editor.inert = saved && !options.native
      if (options.native && saved) shell.editor.querySelector<HTMLElement>('.workbook-grid')!.inert = true
    }
  }
  shell.save.addEventListener('click', save)
  const beforeLeave = (event: BeforeUnloadEvent) => {
    if (dirty) { event.preventDefault(); event.returnValue = '' }
  }
  window.addEventListener('beforeunload', beforeLeave)
  return { dispose() { disposed = true; ribbon.dispose(); shell.save.removeEventListener('click', save); window.removeEventListener('beforeunload', beforeLeave); runtime.univer.dispose() } }
}
