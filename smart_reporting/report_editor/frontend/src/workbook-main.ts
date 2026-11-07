import { UniverSheetsNotePreset } from '@univerjs/preset-sheets-note'
import NoteZhCN from '@univerjs/preset-sheets-note/locales/zh-CN'
import '@univerjs/preset-sheets-note/lib/index.css'
import { adjacentNote, validateNoteCommand, captureNoteTarget, validateNoteTarget, noteSource, noteStructureReason, withWorkbookNotes, workbookNoteOperations, validateNoteBudget, createNoteDialog, type NoteWorkbook } from './workbook-notes'
import { workbookFilterOperations, type FilterWorkbook } from './workbook-filters'
import { LocaleType, mergeLocales } from '@univerjs/core'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import { UniverSheetsFindReplacePreset } from '@univerjs/preset-sheets-find-replace'
import { UniverSheetsDrawingPreset } from '@univerjs/preset-sheets-drawing'
import { UniverSheetsTablePreset } from '@univerjs/preset-sheets-table'
import { UniverSheetsSortPreset } from '@univerjs/preset-sheets-sort'
import '@univerjs/preset-sheets-sort/lib/index.css'
import { UniverSheetsFilterPreset } from '@univerjs/preset-sheets-filter'
import '@univerjs/preset-sheets-filter/lib/index.css'
import FilterUiZhCN from '@univerjs/sheets-filter-ui/locale/zh-CN'
import CoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN'
import FindReplaceZhCN from '@univerjs/preset-sheets-find-replace/locales/zh-CN'
import SortZhCN from '@univerjs/preset-sheets-sort/locales/zh-CN'
import '@univerjs/preset-sheets-core/lib/index.css'
import { matchMarginPreset, readWorkbook, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createUniver } from './workbook-vendor/grid/create-univer'
import { loadWorkbookData, readBack, openFindReplace } from './workbook-vendor/grid/sync'
import { validateWorkbookReplacement, workbookReplacementCommand } from './workbook-find-replace'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { geometryChanges } from './workbook-vendor/core/data-tools'
import { WorkbookDraft, workbookSaveOutcome, type WorkbookOperation, type WorkbookProposal, type WorkbookSaveResult } from './workbook-draft'
import type { EditorShell } from './shell'
import { gridMergeChanges, planGridSheets, structuralMutation, type GridSnapshot } from './workbook-grid-operations'
import { withWorkbookLocked } from './workbook-grid-guards'
import { stepSelectionDecimals } from './workbook-vendor/grid/decimal-step'
import {
  applyWorkbookRibbonCommand, selectedWorkbookRotation,
  mountWorkbookRibbon,
  type RibbonWorkbook,
  type WorkbookPageSetupState,
} from './workbook-ribbon'
import { selectedWorkbookFormat, captureNumberFormatTarget, applyCapturedNumberFormat, validateNumberFormatBudget, createNumberFormatDialog, omitCalculatedNumberFormats, type FormatWorkbook, type NumberFormatTarget } from './workbook-format'
import {
  absoluteRangeRef, applyDefinedNameAction, createNameManagerDialog, definedNamesPlanOperation,
  liveDefinedNames, type DefinedNameWorkbook,
} from './workbook-defined-names'
import { requestJson } from './api-request'
import type { NativeDraft, NativeOperation } from './native-draft'
import { buildSheetPrintHtml, printDocument, PRINT_MARGIN_PRESETS, printSourceFromSnapshotSheet, type SheetPrintSetup, type SheetPrintSource } from './workbook-print'
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
    locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, FindReplaceZhCN, SortZhCN, NoteZhCN, FilterUiZhCN) },
    presets: [
      UniverSheetsCorePreset({ container: 'workbook-grid', header: false, toolbar: true, contextMenu: true, formulaBar: true, footer: { sheetBar: true, statisticBar: true } }),
      UniverSheetsFindReplacePreset(),
      UniverSheetsDrawingPreset(),
      UniverSheetsTablePreset(),
      UniverSheetsSortPreset(),
      UniverSheetsFilterPreset(),
      UniverSheetsNotePreset(),
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
  const rotationUnavailable = () => {
    const name = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetName()
    return currentModel?.sheets.find(sheet => sheet.name === name)?.rotationReadOnlyReason ? '此工作表包含尚不能完整回读的继承格式，暂不支持旋转编辑' : undefined
  }
  const editable = () => !loading && !saving && !saved && !disposed && !shell.editor.inert && !shell.editor.closest('[inert]')
  const formatWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as FormatWorkbook | null
  const formatState = () => selectedWorkbookFormat(formatWorkbook(), currentModel)
  const numberFormatDialog = createNumberFormatDialog(shell.editor, {
    initial: () => formatState().numberFormat,
    apply: (target, pattern) => {
      if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
      if (!target) throw new Error('请先选择单元格或区域')
      if (formatState().numberFormat.kind === 'unavailable') throw new Error('来源格式未完整投影，暂不能安全编辑数字格式')
      validateNumberFormatBudget(runtime.univerAPI.getActiveWorkbook()!.getSnapshot(), currentModel, staged, structural.length, target, pattern)
      applyCapturedNumberFormat(target, formatWorkbook(), pattern, editable())
      markDirty(); ribbon.refreshState?.()
      feedback.textContent = '数字格式已更新，值和公式保持不变；修改尚未保存。'
    },
  })
  const noteWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as NoteWorkbook | null
  const filterWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as FilterWorkbook | null
  const noteDialog = createNoteDialog(shell.editor, (target, text) => {
    const workbook = noteWorkbook(), sheet = validateNoteTarget(target, workbook, editable())
    noteSource(currentModel, sheet.getSheetName())
    const old = sheet.getRange(target.row, target.column).getNote()
    if (!runtime.univerAPI.syncExecuteCommand('sheet.command.update-note', { unitId: workbook!.getId(), subUnitId: target.sheetId,
      row: target.row, col: target.column, note: { ...old, note: text, width: old?.width ?? 240, height: old?.height ?? 140 } })) throw new Error('批注未应用')
    feedback.textContent = '批注已更新，修改尚未保存。'
  })
  // 名称管理器（Formulas ▸ 定义的名称）：实时读 FWorkbook.getDefinedNames()
  // 的全局名；动作走 Univer defined-name 命令，落盘差分由 currentOperations
  // 经既有 applyDefinedNames 协议收集（工作簿 scope，引擎限制见模块注释）。
  const definedNameWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as DefinedNameWorkbook | null
  // facade 缺少 getDefinedNames（版本方差）时返回 undefined，对话框按空列表
  // 展示，保存差分跳过 defined names（绝不能把"读不到"当成"已全部删除"）。
  const definedNameRows = () => liveDefinedNames(definedNameWorkbook()) ?? []
  const nameManagerDialog = createNameManagerDialog(shell.editor, {
    rows: definedNameRows,
    apply: action => {
      if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
      const failure = applyDefinedNameAction(definedNameWorkbook(), action, definedNameRows())
      if (failure === null) {
        markDirty()
        ribbon.refreshState?.()
        feedback.textContent = '定义名称已更新，修改尚未保存。'
      }
      return failure
    },
  })
  // 页面设置日志（Page Layout 族）：Univer 没有页面设置 facade（网格从不渲染
  // 打印设置），与固定源一致按 sheetId 记录补丁，保存差分经 applyPageSetups
  // 落盘；currentModel（引擎读模型）+ 日志补丁即当前生效状态。
  const pageSetupJournal = new Map<string, Record<string, unknown>>()
  const mergedPageSetup = (sheetName: string, patch: Record<string, unknown>): WorkbookPageSetupState => {
    const before = currentModel.sheets.find(item => item.name === sheetName)
    const setup = before?.pageSetup
    const fitToPage = (patch.fitToPage as boolean | undefined) ?? setup?.fitToPage ?? false
    return {
      margins: (patch.margins as WorkbookPageSetupState['margins'] | undefined) ?? matchMarginPreset(before?.margins),
      orientation: (patch.orientation as 'portrait' | 'landscape' | undefined) ?? setup?.orientation,
      paperSize: (patch.paperSize as number | undefined) ?? setup?.paperSize,
      fitToWidth: (patch.fitToWidth as number | undefined) ?? (fitToPage ? setup?.fitToWidth ?? 1 : undefined),
      fitToHeight: (patch.fitToHeight as number | undefined) ?? (fitToPage ? setup?.fitToHeight ?? 1 : undefined),
      printGridlines: (patch.printGridlines as boolean | undefined) ?? before?.printGridlines ?? false,
      printHeadings: (patch.printHeadings as boolean | undefined) ?? before?.printHeadings ?? false,
      printArea: (patch.printArea as string | null | undefined) === undefined ? before?.printArea : (patch.printArea as string | null) ?? undefined,
    }
  }
  const activePageSetupContext = () => {
    const liveWorkbook = runtime.univerAPI.getActiveWorkbook()
    const sheet = liveWorkbook?.getActiveSheet()
    if (!liveWorkbook || !sheet) return undefined
    return { liveWorkbook, sheet, before: currentModel.sheets.find(item => item.name === sheet.getSheetName()) }
  }
  const ribbon = mountWorkbookRibbon(
    shell.editor.querySelector<HTMLElement>('.workbook-ribbon-host')!,
    (command, capturedTarget) => {
      if (command === 'print' || command === 'undo' || command === 'redo') {
        // 固定源 File/Edit 菜单语义：打印为只读操作（与查找一致，保存后仍可
        // 用）；撤销/恢复重放 Univer 历史（与网格快捷键同一命令栈），需可编辑态。
        const blocked = loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')
        if (command === 'print' ? loading || disposed : blocked) return
        try {
          const workbook = runtime.univerAPI.getActiveWorkbook()
          const sheet = workbook?.getActiveSheet()
          if (!workbook || !sheet) throw new Error('工作簿尚未就绪')
          if (command === 'undo' || command === 'redo') {
            void (command === 'undo' ? runtime.univerAPI.undo() : runtime.univerAPI.redo()).then(applied => {
              feedback.textContent = applied
                ? command === 'undo' ? '已撤销上一步修改，修改尚未保存。' : '已恢复上一步修改，修改尚未保存。'
                : command === 'undo' ? '没有可撤销的修改。' : '没有可恢复的修改。'
            }, (error: unknown) => { feedback.textContent = (error as Error).message })
            return
          }
          // File ▸ 打印（web 等效子集）：按当前生效页面设置（文件值 + 会话
          // 页面设置日志）构建打印文档并经隐藏 iframe 提交浏览器打印。浏览器
          // 打印对话框仍掌管打印机/份数/页码范围；页眉页脚、单元格边框与数字
          // 格式显示值不在本子集内（如实反馈，不静默）。
          const sheetId = typeof (sheet as { getSheetId?: () => string }).getSheetId === 'function'
            ? (sheet as { getSheetId: () => string }).getSheetId() : undefined
          const before = currentModel.sheets.find(item => item.name === sheet.getSheetName())
          const patch = sheetId === undefined ? {} : pageSetupJournal.get(sheetId) ?? {}
          const marginsPreset = patch.margins as keyof typeof PRINT_MARGIN_PRESETS | undefined
          const fileMargins = before?.margins
          const setup: SheetPrintSetup = {
            orientation: (patch.orientation as SheetPrintSetup['orientation'] | undefined) ?? before?.pageSetup?.orientation ?? 'portrait',
            paperSize: (patch.paperSize as number | undefined) ?? before?.pageSetup?.paperSize ?? 9,
            scale: before?.pageSetup?.scale ?? 100,
            fitToPage: (patch.fitToPage as boolean | undefined) ?? before?.pageSetup?.fitToPage ?? false,
            fitToWidth: (patch.fitToWidth as number | undefined) ?? (before?.pageSetup?.fitToPage ? before?.pageSetup?.fitToWidth ?? 1 : 0),
            fitToHeight: (patch.fitToHeight as number | undefined) ?? (before?.pageSetup?.fitToPage ? before?.pageSetup?.fitToHeight ?? 1 : 0),
            margins: marginsPreset && marginsPreset in PRINT_MARGIN_PRESETS
              ? PRINT_MARGIN_PRESETS[marginsPreset]
              : fileMargins
                ? { left: fileMargins.left, right: fileMargins.right, top: fileMargins.top, bottom: fileMargins.bottom }
                : PRINT_MARGIN_PRESETS.normal,
            printGridlines: (patch.printGridlines as boolean | undefined) ?? before?.printGridlines ?? false,
            printHeadings: (patch.printHeadings as boolean | undefined) ?? before?.printHeadings ?? false,
            printArea: (patch.printArea as string | null | undefined) === undefined
              ? before?.printArea ?? null
              : (patch.printArea as string | null) ?? null,
            printTitles: (patch.printTitles as string | null | undefined) === undefined
              ? before?.printTitles ?? null
              : (patch.printTitles as string | null) ?? null,
            rowBreaks: (patch.rowBreaks as readonly number[] | undefined) ?? before?.rowBreaks ?? [],
            colBreaks: (patch.colBreaks as readonly number[] | undefined) ?? before?.colBreaks ?? [],
          }
          const snapshotSheets = (workbook.getSnapshot() as { sheets?: Record<string, unknown> }).sheets ?? {}
          const snapshotSheet = (sheetId !== undefined ? snapshotSheets[sheetId] : undefined)
            ?? Object.values(snapshotSheets).find(entry => (entry as { name?: string }).name === sheet.getSheetName())
          const source: SheetPrintSource = printSourceFromSnapshotSheet(snapshotSheet, (workbook.getSnapshot() as { styles?: Record<string, import('./workbook-vendor/core/style-map').UniverStyleData> }).styles)
          const html = buildSheetPrintHtml(source, setup)
          if (!html) throw new Error('没有可打印的内容。')
          const printed = printDocument(html)
          feedback.textContent = printed
            ? '已提交浏览器打印：纸张、方向、页边距、打印区域、标题行、分页符与缩放已按页面设置生效；打印机、份数与页码范围由浏览器打印对话框掌管，页眉页脚与单元格边框不在本次打印内。'
            : '当前浏览器不支持框架内打印，未发送打印任务；请改用浏览器菜单的打印功能。'
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'zoom-in' || command === 'zoom-out' || command === 'zoom-reset') {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        try {
          const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
          if (!active) throw new Error('工作簿尚未就绪')
          const current = typeof active.getZoom === 'function' ? active.getZoom() : 1
          const next = command === 'zoom-reset' ? 1 : Math.min(Math.max(current + (command === 'zoom-in' ? 0.1 : -0.1), 0.1), 4)
          const rounded = Math.round(next * 100) / 100
          // SetZoomRatioCommand 的嵌套 handler 异步返回，CommandService 记录
          // 警告但操作已生效——按观察到的缩放状态判定，不信同步返回值。
          let cause: unknown
          try { runtime.univerAPI.syncExecuteCommand('sheet.command.set-zoom-ratio', {
            unitId: runtime.univerAPI.getActiveWorkbook()!.getId(), subUnitId: active.getSheetId(), zoomRatio: rounded,
          }) } catch (caught) { cause = caught }
          const observed = typeof active.getZoom === 'function' ? active.getZoom() : 1
          if (Math.round(observed * 100) !== Math.round(rounded * 100)) {
            if (cause) throw cause
            throw new Error('缩放未应用')
          }
          // 固定源缩放为视图状态且随保存落盘（applyPageSetups zoomScale）。
          markDirty()
          ribbon.refreshState?.()
          feedback.textContent = `缩放已调整为 ${Math.round(rounded * 100)}%，修改尚未保存。`
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'freeze-panes') {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        try {
          const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
          if (!active) throw new Error('工作簿尚未就绪')
          const anchor = active.getSelection()?.getActiveRange()
          if (!anchor) throw new Error('请先选择单元格或区域')
          // Excel 语义：冻结选区左上角的上侧与左侧；再次冻结同点=取消冻结。
          const frozenRows = anchor.getRow(), frozenColumns = anchor.getColumn()
          const current = active.getFreeze?.()
          const same = current && current.ySplit === frozenRows && current.xSplit === frozenColumns
          const targetRows = same ? 0 : frozenRows, targetColumns = same ? 0 : frozenColumns
          if (!runtime.univerAPI.syncExecuteCommand('sheet.command.set-frozen', {
            unitId: runtime.univerAPI.getActiveWorkbook()!.getId(), subUnitId: active.getSheetId(),
            startRow: targetRows, startColumn: targetColumns, ySplit: targetRows, xSplit: targetColumns,
          })) throw new Error('冻结未应用')
          markDirty()
          ribbon.refreshState?.()
          feedback.textContent = same ? '冻结已取消，修改尚未保存。' : '冻结窗格已更新，修改尚未保存。'
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'print-gridlines' || command === 'print-headings' ||
        /^(page-margins|page-orientation|page-paper|print-area|page-breaks|print-titles|page-fit):/.test(command)) {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        try {
          const context = activePageSetupContext()
          if (!context) throw new Error('工作簿尚未就绪')
          const { sheet, before } = context
          const sheetId = sheet.getSheetId()
          const patch = { ...(pageSetupJournal.get(sheetId) ?? {}) }
          const state = mergedPageSetup(sheet.getSheetName(), patch)
          const note = (message: string) => {
            pageSetupJournal.set(sheetId, patch)
            markDirty()
            ribbon.refreshState?.()
            feedback.textContent = `${message}，修改尚未保存。`
          }
          if (command === 'print-gridlines' || command === 'print-headings') {
            const key = command === 'print-gridlines' ? 'printGridlines' : 'printHeadings'
            patch[key] = !state[key]
            note(`${key === 'printGridlines' ? '打印网格线' : '打印标题（行号列标）'}已${state[key] ? '关闭' : '开启'}`)
            return
          }
          const [pageKey, pageValue] = command.split(/:(.*)/s).slice(0, 2)
          if (pageKey === 'page-margins') {
            const preset = pageValue as 'normal' | 'wide' | 'narrow'
            if (!['normal', 'wide', 'narrow'].includes(preset)) throw new Error('未知页边距预设')
            patch.margins = preset
            note(`页边距已设为${preset === 'normal' ? '常规' : preset === 'wide' ? '宽' : '窄'}`)
            return
          }
          if (pageKey === 'page-orientation') {
            if (pageValue !== 'portrait' && pageValue !== 'landscape') throw new Error('未知纸张方向')
            patch.orientation = pageValue
            note(`纸张方向已设为${pageValue === 'portrait' ? '纵向' : '横向'}`)
            return
          }
          if (pageKey === 'page-paper') {
            const code = Number(pageValue)
            if (!Number.isInteger(code) || code < 1 || code > 118) throw new Error('未知纸张大小')
            patch.paperSize = code
            const PAPER_NAMES: Record<number, string> = { 1: 'Letter', 3: 'Tabloid', 5: 'Legal', 7: 'Executive', 8: 'A3', 9: 'A4', 11: 'A5' }
            note(`纸张大小已设为 ${PAPER_NAMES[code] ?? `代码 ${code}`}`)
            return
          }
          if (pageKey === 'print-area') {
            if (pageValue === 'clear') {
              patch.printArea = null
              note('打印区域已清除')
              return
            }
            const range = sheet.getSelection()?.getActiveRange()
            if (!range) throw new Error('请先选择单元格或区域')
            const columnLabel = (index: number) => {
              let label = ''
              for (let value = index; value >= 0; value = Math.floor(value / 26) - 1) {
                label = String.fromCharCode(65 + (value % 26)) + label
              }
              return label
            }
            const area = `${columnLabel(range.getColumn())}${range.getRow() + 1}:${columnLabel(range.getColumn() + range.getWidth() - 1)}${range.getRow() + range.getHeight()}`
            patch.printArea = area
            note(`打印区域已设为 ${area}`)
            return
          }
          if (pageKey === 'page-breaks') {
            const rowBreaks = [...((patch.rowBreaks as number[] | undefined) ?? before?.rowBreaks ?? [])]
            const colBreaks = [...((patch.colBreaks as number[] | undefined) ?? before?.colBreaks ?? [])]
            if (pageValue === 'reset') {
              patch.rowBreaks = []; patch.colBreaks = []
              note('手动分页符已全部重置')
              return
            }
            const range = sheet.getSelection()?.getActiveRange()
            if (!range) throw new Error('请先选择单元格或区域')
            // Excel 语义：整行选区只插横向分页符，整列选区只插纵向分页符；
            // 单元格两者都插；首行/首列之前无可插位置。
            const fullRow = range.getWidth() >= sheet.getMaxColumns()
            const fullColumn = range.getHeight() >= sheet.getMaxRows()
            const wantRow = !fullColumn && range.getRow() > 0
            const wantColumn = !fullRow && range.getColumn() > 0
            if (pageValue === 'insert') {
              if (!wantRow && !wantColumn) throw new Error('请在首行/首列之外的单元格或区域插入分页符')
              if (wantRow && !rowBreaks.includes(range.getRow())) rowBreaks.push(range.getRow())
              if (wantColumn && !colBreaks.includes(range.getColumn())) colBreaks.push(range.getColumn())
              patch.rowBreaks = rowBreaks.sort((a, b) => a - b)
              patch.colBreaks = colBreaks.sort((a, b) => a - b)
              note('分页符已插入')
              return
            }
            const nextRows = rowBreaks.filter(id => !(wantRow && id === range.getRow()))
            const nextColumns = colBreaks.filter(id => !(wantColumn && id === range.getColumn()))
            if (nextRows.length === rowBreaks.length && nextColumns.length === colBreaks.length) {
              feedback.textContent = '当前位置没有可移除的分页符。'
              return
            }
            patch.rowBreaks = nextRows; patch.colBreaks = nextColumns
            note('分页符已移除')
            return
          }
          if (pageKey === 'print-titles') {
            if (pageValue === 'clear') {
              patch.printTitles = null
              note('打印标题已清除')
              return
            }
            if (pageValue === 'first-row') {
              patch.printTitles = '1:1'
              note('打印标题已设为第 1 行')
              return
            }
            const range = sheet.getSelection()?.getActiveRange()
            if (!range) throw new Error('请先选择单元格或区域')
            // 固定源 clampTitleRows：过长选区保留顶部 21 行标题而非整体丢弃。
            const start = range.getRow() + 1
            const rows = `${start}:${Math.min(range.getRow() + range.getHeight(), start + 20)}`
            patch.printTitles = rows
            note(`打印标题已设为 ${rows}`)
            return
          }
          if (pageKey === 'page-fit') {
            const [axis, rawPages] = (pageValue ?? '').split(':')
            const pages = Number(rawPages)
            if ((axis !== 'width' && axis !== 'height') || !Number.isInteger(pages) || pages < 0 || pages > 1000) {
              throw new Error('未知调整为合适大小设置')
            }
            // Excel 语义：进入 fit-to-page 后另一轴按自动（0）处理。
            patch.fitToWidth = axis === 'width' ? pages : state.fitToWidth ?? 0
            patch.fitToHeight = axis === 'height' ? pages : state.fitToHeight ?? 0
            patch.fitToPage = (patch.fitToWidth as number) > 0 || (patch.fitToHeight as number) > 0
            note(`调整为${axis === 'width' ? '宽度' : '高度'} ${pages === 0 ? '自动' : `${pages} 页`}`)
            return
          }
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'filter-toggle' || command === 'filter-clear' || command === 'filter-reapply') {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        const official = command === 'filter-toggle' ? 'sheet.command.smart-toggle-filter'
          : command === 'filter-clear' ? 'sheet.command.clear-filter-criteria' : 'sheet.command.re-calc-filter'
        try {
          // The pinned smart-toggle chain completes synchronously but a nested
          // handler resolves a promise, so CommandService logs after applying;
          // the observed filter state decides the feedback, not the throw.
          let cause: unknown
          try { runtime.univerAPI.syncExecuteCommand(official) } catch (caught) { cause = caught }
          const installed = !!runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getFilter?.()
          if (command === 'filter-reapply') {
            feedback.textContent = '已重新应用筛选（行显示按条件重算，保存时行隐藏状态一并写回文件）。'
            return
          }
          if (command === 'filter-toggle' && !installed) {
            if (cause) throw cause
            throw new Error('当前工作表未安装筛选')
          }
          markDirty()
          ribbon.refreshState?.()
          feedback.textContent = command === 'filter-toggle' ? '筛选已切换，修改尚未保存。' : '筛选条件已清除，修改尚未保存。'
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'name-manager-open' || command === 'define-name') {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        try {
          const workbook = runtime.univerAPI.getActiveWorkbook()
          if (!workbook) throw new Error('工作簿尚未就绪')
          // 固定源语义：define-name 携带当前选区的绝对地址快速定义；
          // name-manager-open 打开空表单。
          let initialRef: string | undefined
          if (command === 'define-name') {
            const active = workbook.getActiveSheet()
            const range = active?.getSelection()?.getActiveRange()
            if (!active || !range) throw new Error('请先选择单元格或区域')
            initialRef = absoluteRangeRef(active.getSheetName(), range.getRow(), range.getColumn(),
              range.getRow() + range.getHeight() - 1, range.getColumn() + range.getWidth() - 1)
          }
          nameManagerDialog.open({ ref: initialRef })
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command.startsWith('use-in-formula:')) {
        // 固定源语义：把名称作为公式插入活动单元格，仅当单元格为空时；
        // 拒绝静默覆盖已有值或公式。
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        try {
          const workbook = runtime.univerAPI.getActiveWorkbook()
          const active = workbook?.getActiveSheet()
          const range = active?.getSelection()?.getActiveRange()
          if (!active || !range) throw new Error('请先选择单元格或区域')
          const name = command.slice('use-in-formula:'.length)
          const cell = active.getRange(range.getRow(), range.getColumn()) as unknown as {
            getValue?(): unknown
            getFormula?(): string | null
            setFormula(formula: string): unknown
          }
          const value = typeof cell.getValue === 'function' ? cell.getValue() : undefined
          const formula = typeof cell.getFormula === 'function' ? cell.getFormula() : null
          if (formula || (value !== null && value !== undefined && value !== '')) {
            throw new Error('用于公式需要一个空单元格，已有内容不能被静默覆盖')
          }
          cell.setFormula(`=${name}`)
          markDirty()
          ribbon.refreshState?.()
          feedback.textContent = `已在活动单元格插入 =${name}，修改尚未保存。`
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'find' || command === 'replace') {
        if (loading || disposed || command === 'replace' && (saving || saved || shell.editor.inert || shell.editor.closest('[inert]'))) return
        void openFindReplace(runtime, command === 'replace').catch(error => { feedback.textContent = (error as Error).message })
        return
      }
      const readingNote = ['note-open', 'note-prev', 'note-next', 'note-show-toggle'].includes(command)
      if (readingNote ? loading || saving || disposed : !editable()) return
      const workbook = runtime.univerAPI.getActiveWorkbook()
      if (!workbook) return
      try {
        if (command.startsWith('note-')) {
          const target = captureNoteTarget(noteWorkbook())
          if (!target) throw new Error('请先选择单个单元格')
          const sheet = validateNoteTarget(target, noteWorkbook(), readingNote || editable())
          const source = noteSource(currentModel, sheet.getSheetName())
          if (command === 'note-open') noteDialog.open(target, source, editable())
          else if (command === 'note-prev' || command === 'note-next') {
            const next = adjacentNote(sheet.getNotes(), target.row, target.column, command === 'note-next')
            if (!next) throw new Error('当前工作表没有批注')
            sheet.setActiveSelection(sheet.getRange(next.row, next.col))
            const captured = captureNoteTarget(noteWorkbook())
            if (captured) noteDialog.open(captured, source, editable())
          } else if (command === 'note-show-toggle') {
            if (!runtime.univerAPI.syncExecuteCommand('sheet.command.toggle-note-popup')) throw new Error('当前单元格没有可显示的批注')
            feedback.textContent = '批注显示已切换（仅当前视图，不修改文件的 VML 显示状态）。'
          } else if (command === 'note-delete') {
            if (!sheet.getRange(target.row, target.column).getNote()) throw new Error('当前单元格没有批注')
            if (!runtime.univerAPI.syncExecuteCommand('sheet.command.delete-note')) throw new Error('批注未删除')
            feedback.textContent = '批注已删除，修改尚未保存。'
          }
          return
        }
        if (command === 'format:custom-open') {
          const target = capturedTarget ?? captureNumberFormatTarget(formatWorkbook())
          if (!target) throw new Error('请先选择单元格或区域')
          numberFormatDialog.open(target)
          return
        }
        if (command === 'sort:asc' || command === 'sort:desc') {
          // The official sort migrates notes in-grid; readOnlyReason notes stay
          // blocked through the same structural reason.
          const reason = noteStructureReason(currentModel, noteWorkbook(), { id: 'sheet.command.sort-range' })
          if (reason) throw new Error(reason)
        }
        if (command.startsWith('rotate:') && rotationUnavailable()) throw new Error(rotationUnavailable())
        const applied = applyWorkbookRibbonCommand(
          command,
          workbook as unknown as RibbonWorkbook,
          step => stepSelectionDecimals(runtime, step),
          value => { if (!runtime.univerAPI.syncExecuteCommand('sheet.command.set-text-rotation', { value })) throw new Error('文字旋转未应用') },
          (bounds, ascending) => runtime.univerAPI.syncExecuteCommand('sheet.command.sort-range', {
            range: { startRow: bounds.startRow, endRow: bounds.endRow, startColumn: bounds.startColumn, endColumn: bounds.endColumn },
            orderRules: [{ colIndex: bounds.colIndex, type: ascending ? 'asc' : 'desc' }],
            unitId: workbook.getId(), subUnitId: workbook.getActiveSheet().getSheetId(), hasTitle: false,
          }),
          // 官方清除命令（formats/all）；保存差分把清除后的样式缺席捕获为 styleReset。
          kind => !!runtime.univerAPI.syncExecuteCommand(kind === 'all'
            ? 'sheet.command.clear-selection-all'
            : 'sheet.command.clear-selection-format'),
        )
        if (!applied) {
          feedback.textContent = '请先选择单元格或区域'
          return
        }
        markDirty()
        ribbon.refreshState?.()
        feedback.textContent = command === 'insert-sheet'
          ? '已添加工作表，修改尚未保存。'
          : '选区已更新，修改尚未保存。'
      } catch (error) { feedback.textContent = (error as Error).message }
    },
    {
      rotation: () => selectedWorkbookRotation(runtime.univerAPI.getActiveWorkbook() as unknown as RibbonWorkbook | null),
      editable, unavailableReason: rotationUnavailable, format: formatState,
      hasSelection: () => !!runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSelection()?.getActiveRange(),
      captureTarget: () => captureNumberFormatTarget(formatWorkbook()),
      pageSetup: () => {
        const context = activePageSetupContext()
        return context ? mergedPageSetup(context.sheet.getSheetName(), pageSetupJournal.get(context.sheet.getSheetId()) ?? {}) : undefined
      },
      definedNames: () => definedNameRows().map(row => row.name),
      noteReason: command => {
        try {
          const target = captureNoteTarget(noteWorkbook())
          if (!target) return '请先选择单个单元格'
          const sheet = noteWorkbook()!.getActiveSheet()!
          noteSource(currentModel, sheet.getSheetName())
          if (command === 'note-delete' || command === 'note-show-toggle') return sheet.getRange(target.row, target.column).getNote() ? undefined : '当前单元格没有批注'
          if (command === 'note-prev' || command === 'note-next') return sheet.getNotes().length ? undefined : '当前工作表没有批注'
        } catch (error) { return (error as Error).message }
      },
    },
  )
  let selectionListener: { dispose(): void } | undefined
  let replacing = false
  runtime.univerAPI.addEvent(runtime.univerAPI.Event.BeforeCommandExecute, command => {
    if (omitCalculatedNumberFormats(command, runtime.univerAPI.getActiveWorkbook()?.getSnapshot())) return
    if (!loading) {
      const reason = noteStructureReason(currentModel, noteWorkbook(), command)
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
    }
    if (/^sheet\.(?:command|mutation)\.(?:update-note|remove-note|delete-note|toggle-note-popup|update-note-position)$/.test(command.id)) {
      if (loading) return
      try {
        if (command.id.endsWith('update-note-position')) {
          // Official semantics: this mutation re-anchors a note to another cell
          // (model row/col change), not popup layout. Structure followers emit
          // it during sorts and row/column changes; the save pairs the
          // relocation and the engine keeps the original author, so the move
          // round-trips without identity loss and stays permitted here.
          validateNoteCommand(noteWorkbook(), command)
          return
        }
        const viewOnly = command.id.endsWith('toggle-note-popup')
        if (viewOnly ? saving || disposed : !editable()) throw new Error('当前工作簿不可编辑或正在保存')
        const workbook = noteWorkbook()
        const { sheet, notes } = validateNoteCommand(workbook, command)
        if (!viewOnly) {
          noteSource(currentModel, sheet.getSheetName())
          const proposed = { getSheets: () => workbook!.getSheets().map(item => item.getSheetId() === sheet.getSheetId()
            ? { getSheetName: () => item.getSheetName(), getNotes: () => notes } : item) } as unknown as NoteWorkbook
          validateNoteBudget(workbookNoteOperations(currentModel, proposed), staged, structural.length)
        }
      } catch (error) { command.cancel = true; feedback.textContent = (error as Error).message }
      return
    }
    // 源 FILTER_COMMAND_PATTERN 六命令：不可编辑/保存态拒绝；条件不可写回
    // （readOnlyReason）时拒绝并展示引擎理由，避免落盘前静默丢弃条件。
    if (/^sheet\.command\.(?:set-filter-range|remove-sheet-filter|smart-toggle-filter|set-filter-criteria|clear-filter-criteria|re-calc-filter)$/.test(command.id)) {
      if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) {
        command.cancel = true
        feedback.textContent = '当前工作簿处于只读、保存或关闭状态，不能修改筛选。'
        return
      }
      const sheetName = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetName()
      const reason = currentModel?.sheets.find(item => item.name === sheetName)?.filter?.readOnlyReason
      if (reason) { command.cancel = true; feedback.textContent = reason }
      return
    }
    const valueCommand = replacing && command.id === 'sheet.command.set-range-values'
    if (!workbookReplacementCommand(command.id) && !valueCommand) return
    if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) {
      command.cancel = true
      feedback.textContent = '当前工作簿处于只读、保存或关闭状态，不能执行替换。'
      return
    }
    if (command.id === 'ui.operation.open-replace-dialog') return
    if (command.id === 'ui.command.replace-current-match') {
      // The pinned provider delegates the single replacement synchronously before
      // its first await. Limit this scope to that turn, including error/no-match.
      replacing = true
      queueMicrotask(() => { replacing = false })
      return
    }
    if (command.id === 'ui.command.replace-all-matches') return
    try {
      const workbook = runtime.univerAPI.getActiveWorkbook()
      if (!workbook) throw new Error('工作簿尚未就绪')
      validateWorkbookReplacement(command, workbook.getSnapshot(), currentModel, staged, structural.length)
    } catch (error) {
      command.cancel = true
      feedback.textContent = (error as Error).message
    }
  })
  runtime.univerAPI.onCommandExecuted((command, options) => {
    if (command.id === 'ui.command.replace-current-match' || command.id === 'ui.command.replace-all-matches') replacing = false
    ribbon.refreshState?.()
    // Cached values and inferred source number formats are calculation results,
    // not user edits. The before hook removes only incoming calculated n.
    if (command.id === 'sheet.mutation.set-range-values' && options?.fromFormula === true && options?.applyFormulaCalculationResult === true) return
    // Popup toggles are view-only and never reach the file; note position
    // re-anchors ARE captured through the following markDirty diff.
    if (/^sheet\.mutation\.toggle-note-popup$/.test(command.id)) return
    // Defined-name 变更（名称管理器对话框与 Undo 重放）：Univer 顶层命令为
    // sheet.command.{insert,remove,set}-defined-name，落模型的是 formula
    // 引擎的 formula.mutation.{set,remove}-defined-name；不在结构日志里，
    // 撤销经实时差分自然回归空集。
    if (/^formula\.mutation\.(?:set|remove)-defined-name$/.test(command.id) ||
      /^sheet\.command\.(?:insert|remove|set)-defined-name$/.test(command.id)) {
      if (!loading && !saving && !saved) markDirty()
      return
    }
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
    ops.push(...workbookNoteOperations(baseline, noteWorkbook()))
    ops.push(...workbookFilterOperations(baseline, filterWorkbook()))
    // 冻结窗格：readBack 不含 freeze，直接对比实时 Univer 冻结状态与 baseline，
    // 差异经既有 applyPageSetups 协议（frozenRows/frozenColumns）落盘。
    const freezeSetups: { sheetName: string; frozenRows: number; frozenColumns: number }[] = []
    const liveWorkbook = runtime.univerAPI.getActiveWorkbook()
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const liveFreeze = (sheet.getFreeze?.() as { ySplit?: number; xSplit?: number } | undefined) ?? { ySplit: 0, xSplit: 0 }
      const frozenRows = liveFreeze.ySplit ?? 0, frozenColumns = liveFreeze.xSplit ?? 0
      const before = baseline.sheets.find(item => item.name === sheet.getSheetName())?.freeze
      if ((before?.frozenRows ?? 0) !== frozenRows || (before?.frozenColumns ?? 0) !== frozenColumns) {
        freezeSetups.push({ sheetName: sheet.getSheetName(), frozenRows, frozenColumns })
      }
    }
    if (freezeSetups.length) ops.push({ kind: 'applyPageSetups', setups: freezeSetups })
    // 网格线：同一 applyPageSetups 协议（showGridlines），与 baseline 对比。
    const gridlineSetups: { sheetName: string; showGridlines: boolean }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const liveVisible = !(sheet.hasHiddenGridLines?.() ?? false)
      const baselineVisible = baseline.sheets.find(item => item.name === sheet.getSheetName())?.showGridlines ?? true
      if (liveVisible !== baselineVisible) gridlineSetups.push({ sheetName: sheet.getSheetName(), showGridlines: liveVisible })
    }
    const zoomSetups: { sheetName: string; zoomScale: number }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const liveZoom = typeof sheet.getZoom === 'function' ? Math.round((sheet.getZoom() ?? 1) * 100) : 100
      const baselineZoom = baseline.sheets.find(item => item.name === sheet.getSheetName())?.zoomScale ?? 100
      if (liveZoom !== baselineZoom) zoomSetups.push({ sheetName: sheet.getSheetName(), zoomScale: liveZoom })
    }
    const viewSetups: Array<{ sheetName: string } & Record<string, unknown>> = [...freezeSetups, ...gridlineSetups, ...zoomSetups]
    // 页面设置日志差分：与 baseline 逐字段对比，只提交实际变化的字段；
    // 打印区域/标题 null（清除）仅在文件确有值时落盘。
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      // 非 Univer 真实工作表（测试桩）没有 getSheetId，也无日志可差分。
      const sheetId = typeof sheet.getSheetId === 'function' ? sheet.getSheetId() : undefined
      const patch = sheetId === undefined ? undefined : pageSetupJournal.get(sheetId)
      if (!patch) continue
      const before = baseline.sheets.find(item => item.name === sheet.getSheetName())
      const beforeSetup = before?.pageSetup
      const entry: Record<string, unknown> = { sheetName: sheet.getSheetName() }
      for (const key of ['orientation', 'paperSize', 'scale', 'fitToWidth', 'fitToHeight', 'fitToPage'] as const) {
        const value = patch[key]
        if (value === undefined || value === (beforeSetup?.[key] ?? undefined)) continue
        entry[key] = value
      }
      if (patch.margins !== undefined && patch.margins !== matchMarginPreset(before?.margins)) entry.margins = patch.margins
      for (const key of ['printGridlines', 'printHeadings'] as const) {
        const value = patch[key]
        if (value === undefined || value === (before?.[key] ?? false)) continue
        entry[key] = value
      }
      if (patch.printArea !== undefined && patch.printArea !== (before?.printArea ?? null)) entry.printArea = patch.printArea
      if (patch.printTitles !== undefined && patch.printTitles !== (before?.printTitles ?? null)) entry.printTitles = patch.printTitles
      for (const key of ['rowBreaks', 'colBreaks'] as const) {
        const value = patch[key]
        if (value === undefined) continue
        if (JSON.stringify(value) === JSON.stringify(before?.[key] ?? [])) continue
        entry[key] = value
      }
      if (Object.keys(entry).length > 1) viewSetups.push(entry as { sheetName: string })
    }
    if (viewSetups.length) ops.push({ kind: 'applyPageSetups', setups: viewSetups })
    // 定义名称：readBack 不含 definedNames，直接对比实时 Univer defined-name
    // 状态（全局 scope）与 baseline；差异经既有 applyDefinedNames 协议
    // （sets/removes）落盘。工作表级名称（_xlnm.Print_Area 族）由 page-setup
    // 维护，不在此收集。
    if (liveWorkbook) {
      const liveNames = liveDefinedNames(liveWorkbook as unknown as DefinedNameWorkbook)
      // liveNames === undefined：facade 读不到 defined names，跳过差分。
      const namesOperation = liveNames
        ? definedNamesPlanOperation(baseline.definedNames ?? [], liveNames) : undefined
      if (namesOperation) ops.push(namesOperation)
    }
    return ops
  }
  const loadOperations = async (ops: WorkbookOperation[]) => {
    loading = true
    const bytes = ops.length ? await applyWorkbookOperations(original, ops) : original
    currentModel = await readWorkbook(bytes)
    loadWorkbookData(runtime, withWorkbookNotes(buildWorkbookData(currentModel, 'report-workbook', '报告工作簿'), currentModel))
    selectionListener?.dispose()
    selectionListener = runtime.univerAPI.getActiveWorkbook()?.onSelectionChange?.(() => ribbon.refreshState?.())
    staged = structuredClone(ops)
    structural = []
    loading = false
    ribbon.refreshState?.()
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
    ribbon.refreshState?.()
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
      ribbon.refreshState?.()
      if (options.native && saved) shell.editor.querySelector<HTMLElement>('.workbook-grid')!.inert = true
    }
  }
  shell.save.addEventListener('click', save)
  const beforeLeave = (event: BeforeUnloadEvent) => {
    if (dirty) { event.preventDefault(); event.returnValue = '' }
  }
  window.addEventListener('beforeunload', beforeLeave)
  return { dispose() { disposed = true; selectionListener?.dispose(); numberFormatDialog.dispose(); noteDialog.dispose(); nameManagerDialog.dispose(); ribbon.dispose(); shell.save.removeEventListener('click', save); window.removeEventListener('beforeunload', beforeLeave); runtime.univer.dispose() } }
}
