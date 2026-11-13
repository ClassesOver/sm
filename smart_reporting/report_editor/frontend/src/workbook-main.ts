import { subtotalPreflightOperations } from './workbook-subtotal-preflight'
import { openWorkbookCsvImport } from './workbook-import-csv'
import { createWorkbookQueriesDialog } from './workbook-queries'
import { installSubtotal, type SubtotalTarget } from './workbook-subtotal'
import { createSubtotalDialog } from './workbook-subtotal-dialog'
import { advancedFilterPreflightOperations } from './workbook-advanced-filter-preflight'
import { installAdvancedFilter } from './workbook-advanced-filter'
import { createAdvancedFilterDialog } from './workbook-advanced-filter-dialog'
import { createWorkbookErrorChecking } from './workbook-error-checking'
import { createWorkbookWatchWindow } from './workbook-watch-window'
import './assets/docx-cjk/fonts.css'
import { waitForWorkbookRendered, installWorkbookLoadingLock } from './workbook-render-ready'
import { UniverSheetsNotePreset } from '@univerjs/preset-sheets-note'
import NoteZhCN from '@univerjs/preset-sheets-note/locales/zh-CN'
import '@univerjs/preset-sheets-note/lib/index.css'
import { adjacentNote, validateNoteCommand, captureNoteTarget, validateNoteTarget, noteSource, noteStructureReason, withWorkbookNotes, workbookNoteOperations, validateNoteBudget, createNoteDialog, type NoteWorkbook } from './workbook-notes'
import { withWorkbookFilters, workbookFilterOperations, type FilterWorkbook } from './workbook-filters'
import { withWorkbookDataValidations, workbookDataValidationOperations, validateDataValidationEdit, DV_MUTATION, DV_EDIT_COMMAND, type ValidationWorkbook } from './workbook-data-validation'
import { UniverSheetsDataValidationPreset } from '@univerjs/preset-sheets-data-validation'
import DataValidationZhCN from '@univerjs/preset-sheets-data-validation/locales/zh-CN'
import '@univerjs/preset-sheets-data-validation/lib/index.css'
import { UniverSheetsConditionalFormattingPreset } from '@univerjs/preset-sheets-conditional-formatting'
import ConditionalFormattingZhCN from '@univerjs/preset-sheets-conditional-formatting/locales/zh-CN'
import '@univerjs/preset-sheets-conditional-formatting/lib/index.css'
import { withWorkbookConditionalFormatting, workbookConditionalFormattingOperations, validateConditionalFormattingEdit, CF_MUTATION_IDS, CF_EDIT_COMMAND_IDS, type ConditionalFormattingWorkbook } from './workbook-conditional-formatting'
import { withWorkbookView } from './workbook-view'
import { createFormulaBarView } from './workbook-formula-bar-view'
import { installDataValidationNames } from './workbook-data-validation-names'
import { installDataValidationStructure } from './workbook-data-validation-structure'
import { assertConditionalFormattingSheetRemoval } from './workbook-cf-sheet-removal'
import { assertDataValidationSheetRemoval } from './workbook-dv-sheet-removal'
import { assertCellFormulaSheetRemoval, unprojectedCellFormulaNodes } from './workbook-cell-formula-removal'
import { assertDefinedNameSheetRemoval } from './workbook-defined-name-removal'
import { assertChartSheetRemoval } from './workbook-chart-sheet-removal'
import { assertTableSheetRemoval } from './workbook-table-sheet-removal'
import { readWorkbookChartSource, type WorkbookChartSource } from './workbook-chart-source'
import { createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { planSheetRemovalParts } from '@sheets-web/xlsx-engine/sheet-removal-parts'
import { isPivotCacheDefinitionPath, pivotCacheReadsFromSheet } from '@sheets-web/xlsx-engine/pivot-cache-source'
import { CellValueType, CustomCommandExecutionError, ICommandService, IUndoRedoService, LifecycleService, LifecycleStages, LocaleType, mergeLocales } from '@univerjs/core'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import { UniverSheetsFindReplacePreset } from '@univerjs/preset-sheets-find-replace'
import { UniverSheetsDrawingPreset } from '@univerjs/preset-sheets-drawing'
import { UniverSheetsTablePreset } from '@univerjs/preset-sheets-table'
import TableZhCN from '@univerjs/preset-sheets-table/locales/zh-CN'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { withWorkbookTables, workbookTableConfig, workbookTableOperations } from './workbook-tables'
import { installTableHeaders, tableHeaderProtectionReason } from './workbook-table-headers'
import { tablePivotColumnChangeReason } from './workbook-table-pivot-source'
import { planPivotTableFieldRename, type PivotFieldRenameSupport } from '@sheets-web/xlsx-engine/pivot-source-field-rename'
import { installTableDesign } from './workbook-table-design'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableResize } from './workbook-table-resize'
import { installTableConvert } from './workbook-table-convert'
import { installTableCreate, inferTableRegion, tableCreateCellEdits } from './workbook-table-create'
import { createTableCreateDialog } from './workbook-table-create-dialog'
import { installTableTotals } from './workbook-table-totals'
import { installTableHeaderRow } from './workbook-table-header-row'
import { installTableFilterButton } from './workbook-table-filter-button'
import { installTableStyleEdit } from './workbook-table-style-edit'
import { createTableResizeDialog } from './workbook-table-resize-dialog'
import { installTableFormulaReferences } from './workbook-table-formulas'
import { UniverSheetsSortPreset } from '@univerjs/preset-sheets-sort'
import '@univerjs/preset-sheets-sort/lib/index.css'
import { UniverSheetsFilterPreset } from '@univerjs/preset-sheets-filter'
import '@univerjs/preset-sheets-filter/lib/index.css'
import FilterUiZhCN from '@univerjs/sheets-filter-ui/locale/zh-CN'
import CoreZhCN from '@univerjs/preset-sheets-core/locales/zh-CN'
import FindReplaceZhCN from '@univerjs/preset-sheets-find-replace/locales/zh-CN'
import SortZhCN from '@univerjs/preset-sheets-sort/locales/zh-CN'
import '@univerjs/preset-sheets-core/lib/index.css'
import { formatAddress, parseRange, matchMarginPreset, readWorkbook, readPackageSheetHyperlinks, cellHyperlinkState, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { createWorkbookLinkDialog, LINK_TEXT } from './workbook-link-dialog'
import { createSparklineDialog } from './workbook-sparkline-dialog'
import { createChartDesignDialog } from './workbook-chart-design-dialog'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { chartAdditionFromGrid } from './workbook-chart-add'
import { switchChartSeries } from './workbook-chart-switch'
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
import { readWorkbookThemeSource, themeOperation, type ThemeCommandKind, type WorkbookThemeSource } from './workbook-theme'
import { stepSelectionDecimals } from './workbook-vendor/grid/decimal-step'
import { CLIPBOARD_COMMANDS, clipboardCommandParams } from './workbook-clipboard'
import { CELL_SHIFT_COMMANDS, cellShiftRange, cellsCommandId, cellsCommandParams, createCellsDialog, decideCellsAction, type CellRange, type CellShiftEntry, type CellsChoice, type CellsMode } from './workbook-cell-shift'
import { assertProtectionRespected, planProtection, protectionBlockReason } from './workbook-protection'
import { readWorkbookEditableRanges, protectedValueCommandContext, type EditableRange } from './workbook-editable-ranges'
import { installCalculation, type CalculationControl } from './workbook-calculation'
import { installDataTable } from './workbook-data-table'
import { createDataTableDialog } from './workbook-data-table-dialog'
import { installGoalSeek } from './workbook-goal-seek'
import { createGoalSeekDialog } from './workbook-goal-seek-dialog'
import { applyWorkbookOutline, workbookOutlineOperations, installWorkbookOutline, readWorkbookOutlineSummary, setWorkbookOutlineSummary, toggleWorkbookOutlineGroup, showWorkbookOutlineLevel } from './workbook-outline'
import { zoomWorkbookToSelection } from './workbook-zoom-selection'
import { createWorkbookSymbolDialog, symbolInsertion } from './workbook-symbol-dialog'
import { createWorkbookZoomDialog, applyWorkbookZoomPercent, captureWorkbookZoomTarget, isWorkbookZoomTargetCurrent, type WorkbookZoomCommand, type WorkbookZoomTarget } from './workbook-zoom-dialog'
import { createPrintScaleDialog, printScaleState, printScalePatch } from './workbook-print-scale'
import { createHeaderFooterDialog, headerFooterEditorState } from './workbook-header-footer-editor'
import { installWorkbookZoomDialogLauncher } from './workbook-zoom-launcher'
import { readWorkbookStatistics } from './workbook-statistics'
import { createWorkbookInsertFunction } from './workbook-insert-function'
import { installWorkbookFunctionOverrides } from './workbook-function-overrides'
import { applyWorkbookCheckbox } from './workbook-checkbox'
import { installWorkbookSparklines } from './workbook-sparklines'
import { setSparklines, setSparklineWorkbookResolver } from './workbook-vendor/grid/sparkline-render'
import { IRenderManagerService } from '@univerjs/engine-render'
import { applyWorkbookCellStyle } from './workbook-cell-style-presets'
import { toggleWorkbookHeadings } from './workbook-headings'
import { installWorkbookRtl } from './workbook-rtl'
import { installFunctionShortcuts } from './workbook-function-shortcuts'
import { installOutlineShortcuts } from './workbook-outline-shortcuts'
import { installOutlineGutter, type OutlineGutterHandle } from './workbook-outline-gutter'
import { applyConsolidate } from './workbook-consolidate'
import { createConsolidateDialog } from './workbook-consolidate-dialog'
import { createSortDialog, type SortRange } from './workbook-sort-dialog'
import { createFormatCellsDialog } from './workbook-numfmt-dialog'
import { applyFillSeries, createFillSeriesDialog, fillSeriesDefaultType, fillSeriesDirection } from './workbook-fill-series'
import { createGoToDialog, focusWorkbookGrid, resolveGoToRef } from './workbook-goto'
import { createWorkbookReveal } from './workbook-goto-reveal'
import { planWorkbookFlashFill } from './workbook-flash-fill'
import { planWorkbookTextToColumns } from './workbook-text-to-columns'
import { createDedupeDialog, planWorkbookDedupe } from './workbook-dedupe'
import { AUTOFIT_COMMANDS, applyAxisSize, autofitSpans, captureAxisTarget, createAxisSizeDialog } from './workbook-axis-size'
import { applyFormatPainterClick, formatPainterActive, formatPainterReady, installFormatPainter, turnOffFormatPainter } from './workbook-format-painter'
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
import { installDefinedNameScopes } from './workbook-defined-name-scope'
import { requestJson } from './api-request'
import type { NativeDraft, NativeOperation } from './native-draft'
import { mountWorkbookNativeAI, type WorkbookNativeAIClient } from './workbook-native-ai'
import { shiftSpecOf } from '@sheets-web/xlsx-engine/structural'
import { cellShiftSpec } from '@sheets-web/xlsx-engine/cell-shift'
import { createPageSetupJournal, pageBreakPreviewSetup } from './workbook-page-break-context'
import { createPageBreakPreviewController } from './workbook-page-break-controller'
import { installPageBreakOverlay, planPageBreakPreview } from './workbook-page-break-preview'
import { planFormulaTrace, installFormulaTraceOverlay } from './workbook-formula-trace'
import { createFormulaTraceController } from './workbook-formula-trace-controller'
import { installCrossHighlight, loadCrossHighlightPreference, storeCrossHighlightPreference } from './workbook-cross-highlight'
import './workbook.css'
import './office-theme.css'

type AIStatus = { editId: string; status: string; snapshotSha256: string; proposal?: WorkbookProposal; error?: { message: string } }

export interface WorkbookEditorOptions {
  request?: <T>(path: string, payload?: unknown) => Promise<T>
  file?: () => Promise<{ bytes: ArrayBuffer; sha256: string; path?: string }>
  native?: boolean
  draft?: NativeDraft
  onAssistant?: () => void
  nativeAI?: WorkbookNativeAIClient
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
    <div class="workbook-grid-frame"><div id="workbook-grid" class="workbook-grid" aria-label="报告工作簿"></div></div>`
  const feedback = shell.editor.querySelector<HTMLElement>('.workbook-feedback')!
  const form = shell.editor.querySelector<HTMLFormElement>('form')!
  const instruction = shell.editor.querySelector<HTMLTextAreaElement>('textarea')!
  const submit = form.querySelector<HTMLButtonElement>('[type="submit"]')!
  const candidate = shell.editor.querySelector<HTMLElement>('.workbook-candidate')!
  const accept = candidate.querySelector<HTMLButtonElement>('.workbook-accept')!
  const reject = candidate.querySelector<HTMLButtonElement>('.workbook-reject')!
  const undo = form.querySelector<HTMLButtonElement>('.workbook-undo')!
  if (options.native) {
    form.hidden = true; form.inert = true; submit.disabled = true
    const aiPlaceholder = shell.editor.querySelector<HTMLElement>('.workbook-ai')!
    aiPlaceholder.style.display = 'contents'
    feedback.hidden = true
  }
  let original: Uint8Array
  let currentModel!: WorkbookModel
  let expectedSha256 = ''
  let sourcePath: string | undefined
  let staged: WorkbookOperation[] = []
  let editableRanges = new Map<string, EditableRange[]>()
  let aiId = ''
  let candidateOperations = ''
  let dirty = false
  // 新修订已登记后不再从当前底稿保存，避免重复生成修订。
  let saved = false
  let loading = true
  let saving = false
  let nativeAI: ReturnType<typeof mountWorkbookNativeAI> | undefined
  let nativeAIAccepting = false
  let disposed = false
  let gridChanged = false
  let captureGeneration = 0
  let mergeGeneration = 0
  let persistence = Promise.resolve()
  // 结构日志：行列增删（Univer mutation）与插入/删除单元格移位（命令 + 撤销元素），按发生顺序回放。
  let structural: (NonNullable<ReturnType<typeof structuralMutation>> | CellShiftEntry)[] = []
  let cfBaseline: { source: WorkbookModel; model: WorkbookModel; signature: string } | undefined
  const structureSourceXml = new WeakMap<WorkbookModel, Map<string, string>>()
  const workbookSourceXml = new WeakMap<WorkbookModel, string>()
  const chartSources = new WeakMap<WorkbookModel, WorkbookChartSource | Error>()
  const tableRemovalParts = new WeakMap<WorkbookModel, Map<string, ReadonlySet<string> | Error>>()
  const pivotCacheSources = new WeakMap<WorkbookModel, string[] | Error>()
  const pivotFieldRenameSupports = new WeakMap<WorkbookModel, Map<string, PivotFieldRenameSupport | Error>>()
  const pivotTableColumnReason = (table: any, names: readonly string[], nextStartColumn?: number) => {
    const before = originalSheet(table.subUnitId)?.tables?.find(item => table.id === `file-table-${table.subUnitId}-${item.id}`)
    return tablePivotColumnChangeReason(table, names, pivotCacheSources.get(currentModel), before ? [before.name, before.displayName] : [], nextStartColumn, before ? pivotFieldRenameSupports.get(currentModel)?.get(before.path) : undefined)
  }
  let unprojectedNames: { name: string; scopeSheetId?: string }[] = []
  const readModelWithStructureSource = async (bytes: Uint8Array) => {
    const model = await readWorkbook(bytes)
    const source = await createBufferEntrySource(bytes)
    workbookSourceXml.set(model, await source.readText('xl/workbook.xml'))
    try { chartSources.set(model, await readWorkbookChartSource(source, model.sheets)) }
    catch (error) { chartSources.set(model, error instanceof Error ? error : new Error(String(error))) }
    try {
      pivotCacheSources.set(model, await Promise.all((await source.paths()).filter(isPivotCacheDefinitionPath).map(path => source.readText(path))))
    } catch (error) { pivotCacheSources.set(model, error instanceof Error ? error : new Error(String(error))) }
    const fieldRenameSupports = new Map<string, PivotFieldRenameSupport | Error>()
    await Promise.all(model.sheets.flatMap(sheet => (sheet.tables ?? []).map(async table => {
      try {
        const fields = table.columns.map(column => column.name)
        const plan = await planPivotTableFieldRename(bytes, { aliases: [table.name, table.displayName], sheetName: sheet.name, startColumn: table.range.startColumn, beforeNames: fields, afterNames: fields })
        if (plan.replacements.size) fieldRenameSupports.set(table.path, plan.support)
      } catch (error) { fieldRenameSupports.set(table.path, error instanceof Error ? error : new Error(String(error))) }
    })))
    pivotFieldRenameSupports.set(model, fieldRenameSupports)
    const tablePlans = new Map<string, ReadonlySet<string> | Error>()
    await Promise.all(model.sheets.filter(sheet => sheet.tableSources?.length || sheet.tablesReadOnlyReason || sheet.tableSourcesReadOnlyReason).map(async sheet => {
      try { tablePlans.set(sheet.name, (await planSheetRemovalParts(source, [sheet.path])).removedParts) }
      catch (error) { tablePlans.set(sheet.name, error instanceof Error ? error : new Error(String(error))) }
    }))
    tableRemovalParts.set(model, tablePlans)
    const entries = await Promise.all(model.sheets.map(async sheet => {
      const xml = await source.readText(sheet.path)
      let unprojected = true
      try { unprojected = unprojectedCellFormulaNodes(xml).length > 0 } catch { /* 删除前再明确报告无法核对，不阻断普通文件加载。 */ }
      return sheet.conditionalFormatting?.issues.length || sheet.dataValidations?.readOnlyReason || unprojected
        ? [sheet.name, xml] as const : undefined
    }))
    structureSourceXml.set(model, new Map(entries.filter((entry): entry is readonly [string, string] => entry !== undefined)))
    return model
  }
  const cfStructureSignature = (snapshot: GridSnapshot) => JSON.stringify([
    planGridSheets(currentModel.sheets.map(sheet => sheet.name), snapshot),
    structural.map(item => 'op' in item ? { sheetId: item.sheetId, op: item.op } : { sheetId: item.sheetId, cellShift: item.cellShift }),
  ])
  const preflightPivotRowColumns = (command: { id: string; params?: Record<string, any> }, workbook: any) => {
    if (loading || !/^sheet\.(?:command|mutation)\.(?:insert-row|remove-rows?|insert-col|remove-col)(?:-|$)/.test(command.id)) return
    try {
      if (!workbook) throw new Error('工作簿尚未就绪')
      const snapshot = workbook.getSnapshot() as GridSnapshot
      const plan = planGridSheets(currentModel.sheets.map(sheet => sheet.name), snapshot)
      // 行列几何不改变缓存来源工作表身份；仅工作表计划变化需要已同步的来源模型。
      const changed = plan.renames.length || plan.additions.length || plan.removals.length
        || plan.order.some((name, index) => name !== currentModel.sheets[index]?.name)
      let sourceModel = currentModel
      if (changed) {
        if (cfBaseline?.source !== currentModel || JSON.stringify(cfBaseline.model.sheets.map(sheet => sheet.name)) !== JSON.stringify(snapshot.sheetOrder.map(id => snapshot.sheets[id]?.name)))
          throw new Error('结构修改正在同步，请稍后重试插入/删除行列')
        sourceModel = cfBaseline.model
      }
      const target = command.params?.subUnitId ? workbook.getSheetBySheetId(command.params.subUnitId) : workbook.getActiveSheet()
      const caches = pivotCacheSources.get(sourceModel)
      if (!caches || !target) throw new Error('透视表来源正在同步，请稍后重试插入/删除行列')
      if (caches instanceof Error) throw caches
      for (const xml of caches) if (pivotCacheReadsFromSheet(xml, target.getSheetName()))
        throw new Error(`仍有透视表读取工作表 "${target.getSheetName()}" 的来源数据，已拒绝插入/删除行列。`)
    } catch (error) { feedback.textContent = (error as Error).message; throw error }
  }
  const undone: CellShiftEntry[] = []
  // 单元格移位/其撤销重做同步执行期间，Univer 为扩容附带的 insert/remove-col|row mutation 不进行列日志。
  let suppressStructural = false
  // 审阅▸保护：按原工作表 id（sheet-N）记录切换后的期望状态；undefined/缺省 = 文件原状态。
  const sheetProtection = new Map<string, boolean>()
  let structureLock: boolean | undefined
  // 公式▸显示公式：按 Univer 工作表 id 记录公式视图（文件 sheetView/@showFormulas 为基线）；计算模式为编辑器状态。
  const formulaSheets = new Set<string>()
  let calculation: CalculationControl | undefined
  let dataTable: ReturnType<typeof installDataTable> | undefined
  let goalSeek: ReturnType<typeof installGoalSeek> | undefined
  let subtotal: ReturnType<typeof installSubtotal> | undefined
  let subtotalMutating = false
  let advancedFilter: ReturnType<typeof installAdvancedFilter> | undefined
  let advancedFilterMutating = false
  let calculationBusy = false
  let acceptedSnapshot = ''
  // Canvas 首次测量前加载内置中文字体，避免缓存系统替代字体的字宽。
  if (document.fonts) await Promise.allSettled([
    document.fonts.load('12px "Noto Sans CJK SC"', '中文'),
    document.fonts.load('12px "Noto Serif CJK SC"', '中文'),
    document.fonts.load('12px "LXGW WenKai"', '中文'),
    document.fonts.load('12px "Ma Shan Zheng"', '中文'),
    document.fonts.load('12px "ZCOOL XiaoWei"', '中文'),
  ])
  const runtime = createUniver({
    locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, FindReplaceZhCN, SortZhCN, NoteZhCN, FilterUiZhCN, DataValidationZhCN, TableZhCN, ConditionalFormattingZhCN) },
    presets: [
      UniverSheetsCorePreset({ container: 'workbook-grid', header: true, toolbar: false, contextMenu: true, formulaBar: true, footer: { sheetBar: true, statisticBar: true, menus: true, zoomSlider: false } }),
      UniverSheetsFindReplacePreset(),
      UniverSheetsDrawingPreset(),
      { plugins: UniverSheetsTablePreset().plugins.map(entry => entry === UniverSheetsTablePlugin ? [entry, workbookTableConfig] : entry) },
      UniverSheetsSortPreset(),
      UniverSheetsFilterPreset(),
      UniverSheetsNotePreset(),
      UniverSheetsDataValidationPreset(),
      UniverSheetsConditionalFormattingPreset(),
    ],
  })
  const loadingLock = installWorkbookLoadingLock(shell.editor.querySelector<HTMLElement>('.workbook-grid')!, () => loading)
  const rtl = installWorkbookRtl(runtime)
  let rtlBusy = false
  const formulaBar = createFormulaBarView(shell.editor.querySelector<HTMLElement>('.workbook-grid')!)
  let crossHighlightVisible = loadCrossHighlightPreference()
  const crossHighlightTheme = window.matchMedia?.('(prefers-color-scheme: dark)')
  const crossHighlight = installCrossHighlight(runtime, { theme: () => crossHighlightTheme?.matches ? 'dark' : 'light' })
  const refreshCrossHighlight = () => crossHighlight.refresh()
  crossHighlightTheme?.addEventListener('change', refreshCrossHighlight)

  let functionOverrides: { dispose(): void } | undefined
  let headingsBusy = false
  const markDirty = () => {
    if (loading || saving || saved || disposed || calculationBusy || subtotalMutating || advancedFilterMutating) return
    mergeGeneration++
    dirty = true
    gridChanged = true
    shell.statusLabel.textContent = '有未保存修改'
    if (!candidate.hidden) feedback.textContent = '内容已变化时需重新生成 AI 候选。'
    if (nativeDraft || structural.length || currentModel.sheets.some(sheet => sheet.conditionalFormatting?.rules.length)) {
      // 连续 mutation 只采集最新网格；异步结构操作不得让旧快照覆盖新草稿。
      const generation = ++captureGeneration
      persistence = persistence.then(async () => {
        if (generation !== captureGeneration || disposed) return
        const operations = await currentOperations()
        if (generation !== captureGeneration || disposed) return
        nativeDraft?.setOperations(operations as NativeOperation[])
        if (!loading && !saving && !saved) {
          dirty = operations.length > 0
          shell.statusLabel.textContent = dirty ? '有未保存修改' : '已保存'
        }
        if (nativeDraft?.persistenceError) feedback.textContent = nativeDraft.persistenceError
      }).catch(error => { feedback.textContent = `本地草稿暂未更新：${(error as Error).message}` })
    }
  }
  const indentUnavailable = () => {
    const name = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetName()
    return currentModel?.sheets.find(sheet => sheet.name === name)?.indentReadOnlyReason ? '此工作表包含尚不能完整回读的继承格式，暂不支持缩进编辑' : undefined
  }
  const rotationUnavailable = () => {
    const name = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetName()
    return currentModel?.sheets.find(sheet => sheet.name === name)?.rotationReadOnlyReason ? '此工作表包含尚不能完整回读的继承格式，暂不支持旋转编辑' : undefined
  }
  const editable = () => !loading && !saving && !saved && !disposed && !calculationBusy && !shell.editor.inert && !shell.editor.closest('[inert]')
  let disposeCsvImport: (() => void) | undefined
  let printPreviewDialog: { open(options: { hasSelection: boolean; sheetCount: number }): void; dispose(): void } | undefined
  const formulaBarAvailable = () => !loading && !saving && !disposed && !calculationBusy
  const zoomAvailable = editable
  const runZoom = (command: WorkbookZoomCommand | 'zoom-in' | 'zoom-out' | 'zoom-reset', target?: WorkbookZoomTarget) => {
    if (!zoomAvailable()) return
    if (target && !isWorkbookZoomTargetCurrent(runtime, target)) { feedback.textContent = '原工作表已切换，请重新打开缩放设置'; return }
    const current = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getZoom?.() ?? 1
    const percent = command === 'zoom-reset' ? 100 : command === 'zoom-in' || command === 'zoom-out'
      ? Math.min(400, Math.max(10, Math.round((current + (command === 'zoom-in' ? 0.1 : -0.1)) * 100))) : Number(command.slice(5))
    const pending = command === 'zoom-to-selection' ? zoomWorkbookToSelection(runtime) : applyWorkbookZoomPercent(runtime, percent, target)
    void pending.then(result => {
      if (disposed || loading) return
      if (result.changed) { if (editable()) markDirty(); ribbon.refreshState?.() }
      feedback.textContent = !editable() ? result.message.replace('，修改尚未保存。', '。') : result.message
    }).catch(error => { if (!disposed) feedback.textContent = (error as Error).message })
  }
  const zoomDialog = createWorkbookZoomDialog(shell.editor, runZoom)
  const openZoom = () => {
    if (!zoomAvailable()) return
    const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
    if (sheet) zoomDialog.open(Math.round(sheet.getZoom() * 100), captureWorkbookZoomTarget(runtime))
  }
  const zoomLauncher = installWorkbookZoomDialogLauncher(runtime, shell.editor, command => {
    if (command === 'zoom-open') openZoom()
    else runZoom(command)
  }, zoomAvailable)
  const formatWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as FormatWorkbook | null
  const formatState = () => selectedWorkbookFormat(formatWorkbook(), currentModel)
  // 行高/列宽对话框：打开时冻结选区（同数字格式对话框），应用经 worksheet facade 写入网格，
  // 保存时由既有 geometryChanges 差分写回 applyRowHeights/applyColumnWidths。
  const axisDialog = createAxisSizeDialog(shell.editor, (target, value) => {
    applyAxisSize(target, runtime.univerAPI.getActiveWorkbook() as never, value, editable())
    markDirty()
    ribbon.refreshState?.()
    feedback.textContent = `${target.axis === 'row' ? '行高' : '列宽'}已更新，修改尚未保存。`
  })
  const tableResizeDialog = createTableResizeDialog(shell.editor, (id, range) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    if (!tableResize || !tableResize.resize(id, range)) throw new Error('表格范围未更新，请重新选择表格')
    markDirty(); ribbon.refreshState?.()
    feedback.textContent = '表格范围已更新，修改尚未保存。'
  })
  const tableCreateDialog = createTableCreateDialog(shell.editor, (sheetId, text, hasHeaders) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getSheetBySheetId(sheetId)
    if (!sheet || !tableCreate) throw new Error('工作表身份已变化，请重新选择')
    const source = originalSheet(sheetId) ?? currentModel.sheets.find(item => item.name === sheet.getSheetName())
    if (source?.tablesReadOnlyReason) throw new Error(source.tablesReadOnlyReason)
    const ids = new Set(workbook!.getTableList?.().map(table => table.id))
    if (!tableCreate.create(sheetId, parseRange(text), hasHeaders)) throw new Error('创建表格未执行')
    const created = workbook!.getTableList?.().find(table => !ids.has(table.id))
    if (created) sheet.setActiveSelection(sheet.getRange(created.range.startRow, created.range.startColumn))
    markDirty(); ribbon.refreshState?.()
    shell.editor.querySelector<HTMLButtonElement>('[data-ribbon-tab="Table Design"]')?.click()
    feedback.textContent = '表格已创建，修改尚未保存。'
  })
  const originalSheet = (sheetId: string | undefined) => {
    const index = /^sheet-(\d+)$/.exec(sheetId ?? '')?.[1]
    return index === undefined ? undefined : currentModel?.sheets[Number(index)]
  }
  const sheetProtected = (sheetId: string | undefined) =>
    sheetId !== undefined && (sheetProtection.get(sheetId) ?? originalSheet(sheetId)?.protection?.protected ?? false)
  // 固定源 Insert ▸ 符号（handleInsertSymbol）：追加到活动单元格，经官方 FRange.setValue 写入网格，保存差分写回值。
  const symbolDialog = createWorkbookSymbolDialog(shell.editor, char => {
    if (!editable()) throw new Error('工作簿正在加载或保存')
    const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
    const anchor = active?.getSelection()?.getActiveRange()
    if (!active || !anchor) throw new Error('请先选中一个单元格，再插入符号')
    if (sheetProtected(active.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
    const row = anchor.getRow(), column = anchor.getColumn()
    const cell = active.getRange(row, column)
    const data = (cell as unknown as { getCellData?: () => { v?: unknown; f?: string | null; si?: string | null; p?: unknown } | null }).getCellData?.() ?? null
    const next = symbolInsertion({ value: (data?.v ?? cell.getValue()) as string | number | boolean | null | undefined, formula: data?.f || data?.si || cell.getFormula?.() || null, richText: !!data?.p }, char)
    cell.setValue(next)
    markDirty(); ribbon.refreshState?.()
    let label = ''
    for (let value = column + 1; value > 0; value = Math.floor((value - 1) / 26)) label = String.fromCharCode(65 + ((value - 1) % 26)) + label
    const message = `已插入 ${char} 到 ${label}${row + 1}，修改尚未保存。`
    feedback.textContent = message
    return message
  })
  let sparklines: ReturnType<typeof installWorkbookSparklines> | undefined
  let sparklineDialog: ReturnType<typeof createSparklineDialog> | undefined
  let chartDesignDialog: ReturnType<typeof createChartDesignDialog> | undefined
  const insertFunction = createWorkbookInsertFunction(shell.editor, {
    runtime, editable, protectedSheet: sheetProtected,
    file: options.file,
    onWrite: (_formula, target) => { markDirty(); ribbon.refreshState?.(); feedback.textContent = `函数公式已写入 ${target.label}，修改尚未保存。` },
    onError: message => { if (!disposed) feedback.textContent = message },
  })
  const structureLocked = () => structureLock ?? currentModel?.workbookProtection?.lockStructure ?? false
  const activeSheetId = () => {
    const workbook = runtime.univerAPI.getActiveWorkbook() as { getActiveSheet?(): { getSheetId?(): string } | null } | null
    return workbook?.getActiveSheet?.()?.getSheetId?.()
  }
  const protectionView = () => {
    const sheetId = activeSheetId(), password = originalSheet(sheetId)?.protection?.hasPassword
    return {
      sheet: { protected: sheetProtected(sheetId), reason: password ? '此工作表受密码保护，暂不支持撤销或修改其保护' : undefined },
      workbook: { locked: structureLocked(), reason: currentModel?.workbookProtection?.hasPassword ? '工作簿结构受密码保护，暂不支持撤销或修改其保护' : undefined },
    }
  }
  // 无注入器的测试替身没有撤销栈：单元格移位仍记日志，只是不能按撤销元素认领。
  const undoStack = () => typeof runtime.univer.__getInjector === 'function'
    ? runtime.univer.__getInjector().get<{ pitchTopUndoElement(): unknown; pitchTopRedoElement(): unknown }>(IUndoRedoService) : undefined
  const runCellsChoice = (mode: CellsMode, choice: CellsChoice, range: CellRange) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    void runtime.univerAPI.executeCommand(cellsCommandId(mode, choice), cellsCommandParams(mode, choice, range)).then(applied => {
      if (!applied) feedback.textContent ||= mode === 'insert' ? '插入单元格未应用' : '删除单元格未应用'
    }, (error: unknown) => { feedback.textContent = (error as Error).message })
  }
  let cellsRange: CellRange | undefined
  const cellsDialog = createCellsDialog(shell.editor, (mode, choice) => {
    if (!cellsRange) throw new Error('请先选择单元格或区域')
    runCellsChoice(mode, choice, cellsRange)
  })
  // 数据▸自定义排序：打开时冻结选区，确定后执行官方 sort-range（批注/值/样式在网格内迁移，保存走既有差分）。
  let dedupeTarget: { sheetId: string; range: SortRange } | undefined
  const dedupeDialog = createDedupeDialog(shell.editor, hasHeader => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
    if (!sheet || sheet.getSheetId() !== dedupeTarget?.sheetId) throw new Error('工作表已变化，请重新打开删除重复值')
    const reason = protectionBlockReason('sheet.command.set-range-values', sheetProtected(sheet.getSheetId()), structureLocked())
    if (reason) throw new Error(reason)
    const range = dedupeTarget.range
    if (sheet.getMergedRanges().some(item => {
      const merged = item.getRange()
      return merged.startRow <= range.endRow && merged.endRow >= range.startRow && merged.startColumn <= range.endColumn && merged.endColumn >= range.startColumn
    })) throw new Error('选区包含合并单元格，请使用普通区域')
    const active = sheet.getRange(range.startRow, range.startColumn, range.endRow - range.startRow + 1, range.endColumn - range.startColumn + 1)
    const plan = planWorkbookDedupe(active, hasHeader)
    if (!plan.removed) { feedback.textContent = '选区没有重复值'; return }
    const params = { unitId: workbook!.getId(), subUnitId: sheet.getSheetId(), value: plan.value }
    // 预算投影使用预检器既有的值/公式协议；实际命令保留显式类型和清除标记。
    const projected = Object.fromEntries(Object.entries(plan.value).map(([row, cells]) => [row,
      Object.fromEntries(Object.entries(cells).map(([column, cell]) => [column, { v: cell.v, f: '' }])),
    ]))
    validateWorkbookReplacement({ id: 'sheet.command.set-range-values', params: { ...params, value: projected } }, workbook!.getSnapshot(), currentModel, staged, structural.length)
    if (!runtime.univerAPI.syncExecuteCommand('sheet.command.set-range-values', params)) throw new Error(feedback.textContent || '删除重复值未应用')
    feedback.textContent = `已删除 ${plan.removed} 行重复值，修改尚未保存。`
  })
  const sortDialog = createSortDialog(shell.editor, (range, hasTitle, orderRules) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const workbook = runtime.univerAPI.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
    const reason = noteStructureReason(currentModel, noteWorkbook(), { id: 'sheet.command.sort-range' })
    if (reason) throw new Error(reason)
    const applied = runtime.univerAPI.syncExecuteCommand('sheet.command.sort-range', { range, orderRules, hasTitle, unitId: workbook.getId(), subUnitId: sheet.getSheetId() })
    if (!applied) throw new Error(feedback.textContent || '排序未应用')
    markDirty(); ribbon.refreshState?.()
    feedback.textContent = `已按 ${orderRules.length} 个关键字排序${hasTitle ? '（首行为标题）' : ''}，修改尚未保存。`
  })
  const withCalculationLock = async <T,>(target: { workbookId: string; sheetId: string }, work: () => Promise<T>): Promise<T> => {
    if (!editable()) throw new Error('工作簿尚未就绪或当前不可编辑')
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
    if (workbook?.getId() !== target.workbookId || sheet?.getSheetId() !== target.sheetId) throw new Error('工作表身份已变化，请重新打开模拟分析对话框')
    const core = workbook.getWorkbook(), sheetCore = sheet.getSheet()
    const locked = [...shell.editor.querySelectorAll<HTMLElement>('#workbook-grid, .workbook-ribbon-host, .workbook-ai')]
    const previous = locked.map(element => element.inert), saveDisabled = shell.save.disabled
    calculationBusy = true
    shell.save.disabled = true
    locked.forEach(element => { element.inert = true })
    ribbon.refreshState?.()
    try {
      // 先完成已有草稿采集，再临时代入输入；中间 mutation 不生成草稿。
      await persistence
      const active = runtime.univerAPI.getActiveWorkbook()
      if (disposed || active?.getWorkbook() !== core || active.getActiveSheet()?.getSheet() !== sheetCore) throw new Error('工作表身份已变化，请重新打开模拟分析对话框')
      return await work()
    } finally {
      calculationBusy = false
      locked.forEach((element, index) => { element.inert = previous[index]! })
      shell.save.disabled = saveDisabled || saved || disposed
      ribbon.refreshState?.()
    }
  }
  const dataTableDialog = createDataTableDialog(shell.editor, async (target, input) => {
    if (!dataTable) throw new Error('工作簿尚未就绪')
    const result = await withCalculationLock(target, () => dataTable!.apply(input))
    markDirty()
    feedback.textContent = `模拟运算表已生成 ${result.cells} 个静态结果，修改尚未保存。`
    return result
  })
  const subtotalDialog = createSubtotalDialog(shell.editor, async (target, input) => {
    if (!subtotal || !editable()) throw new Error('工作簿尚未就绪或当前不可编辑')
    const saveDisabled = shell.save.disabled
    shell.save.disabled = true
    try {
      const result = await subtotal.apply(target, input)
      markDirty(); ribbon.refreshState?.(); outlineGutter?.refresh()
      feedback.textContent = `分类汇总已插入 ${result.addedRows} 行，修改尚未保存。`
      return result
    } finally { shell.save.disabled = saveDisabled || saving || saved || disposed }
  })
  const advancedFilterDialog = createAdvancedFilterDialog(shell.editor, async (target, input) => {
    if (!advancedFilter || !editable()) throw new Error('工作簿尚未就绪或当前不可编辑')
    const saveDisabled = shell.save.disabled
    shell.save.disabled = true
    try {
      const result = await advancedFilter.apply(target, input)
      markDirty(); ribbon.refreshState?.()
      feedback.textContent = '高级筛选条件已应用，修改尚未保存。'
      return result
    } finally { shell.save.disabled = saveDisabled || saving || saved || disposed }
  })
  const goalSeekDialog = createGoalSeekDialog(shell.editor, async (target, input) => {
    if (!goalSeek) throw new Error('工作簿尚未就绪')
    const result = await withCalculationLock(target, () => goalSeek!.solve(input))
    if (result.found) { markDirty(); feedback.textContent = '单变量求解已完成，修改尚未保存。' }
    else feedback.textContent = '单变量求解未找到解，已恢复原输入。'
    return result
  })
  let consolidateCore: unknown, consolidateSheetCore: unknown
  const consolidateDialog = createConsolidateDialog(shell.editor, (target, input) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet(), range = workbook?.getActiveRange()
    if (workbook?.getId() !== target.workbookId || sheet?.getSheetId() !== target.sheetId || workbook.getWorkbook() !== consolidateCore || sheet.getSheet() !== consolidateSheetCore) throw new Error('工作表身份已变化，请重新打开合并计算')
    if (range?.getRow() !== target.row || range.getColumn() !== target.column) throw new Error('目标选区已变化，请重新选择合并计算的目标')
    const result = applyConsolidate(runtime, input, id => sheetProtected(id), params => {
      const projected = Object.fromEntries(Object.entries(params.value).map(([row, cells]) => [row,
        Object.fromEntries(Object.entries(cells).map(([column, cell]) => [column, { v: cell.v, f: cell.f ?? '' }])),
      ]))
      validateWorkbookReplacement({ id: 'sheet.command.set-range-values', params: { ...params, value: projected } }, workbook.getSnapshot(), currentModel, staged, structural.length)
    })
    markDirty(); ribbon.refreshState?.()
    feedback.textContent = `已合并 ${result.sources} 个来源，生成 ${result.rows} 行 ${result.columns} 列公式，修改尚未保存。`
  })
  // 开始▸编辑▸填充▸序列（固定源 fill-series-apply.ts）：写入为普通 set-values，可撤销、走保存差分。
  const fillSeriesDialog = createFillSeriesDialog(shell.editor, options => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet(), active = workbook?.getActiveRange()
    if (!sheet || !active) return '请先选择单元格或区域'
    const failure = applyFillSeries(sheet as never, active as never, options)
    if (!failure) { markDirty(); ribbon.refreshState?.(); feedback.textContent = '已填充序列，修改尚未保存。' }
    return failure
  })
  // 开始▸编辑▸定位（固定源 data-tools-actions.ts goToReference）：仅移动选区，只读亦可用。
  const goToReveal = createWorkbookReveal()
  const errorChecking = createWorkbookErrorChecking({
    workbook: () => formulaBarAvailable() ? runtime.univerAPI.getActiveWorkbook() : null,
    reveal: (sheet, row, column, current) => goToReveal.reveal(sheet, row, column, current),
    message: text => { feedback.textContent = text },
    refreshSelection: () => { ribbon.refreshState?.() },
  })
  let goToGeneration = 0
  const navigateReference = (reference: string) => {
    goToReveal.cancel()
    const navigation = ++goToGeneration
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
    if (!workbook || !sheet) return '工作簿尚未就绪'
    const trimmed = reference.trim()
    if (!trimmed) return '请输入引用位置'
    const resolved = resolveGoToRef(trimmed, definedNameRows().map(row => ({ name: row.name, ref: row.refersTo })))
    if (resolved === null) return `无法定位到“${trimmed}”：不是有效的引用或已定义名称`
    try {
      const range = sheet.getRange(resolved)
      const target = workbook.getSheetBySheetId(range.getSheetId()) ?? sheet
      if (target.getSheetId() !== sheet.getSheetId()) workbook.setActiveSheet(target)
      workbook.setActiveRange(range)
      const current = () => {
        const active = runtime.univerAPI.getActiveWorkbook(), selection = active?.getActiveRange()?.getRange()
        return !loading && !disposed && navigation === goToGeneration && active?.getActiveSheet()?.getSheet() === target.getSheet()
          && selection?.startRow === range.getRow() && selection?.startColumn === range.getColumn()
      }
      feedback.textContent = `已选择 ${trimmed}，正在显示目标。`
      void goToReveal.reveal(target, range.getRow(), range.getColumn(), current).then(visible => {
        if (visible === null || !current()) return
        feedback.textContent = visible ? `已定位到 ${trimmed}，目标已显示。` : `已选择 ${trimmed}，但未能将目标显示到可见区域，请重试。`
      }).catch(error => {
        if (current()) feedback.textContent = `已选择 ${trimmed}，但无法显示目标：${(error as Error).message}`
      })
      return null
    } catch (error) {
      const detail = (error as Error).message ?? ''
      return detail.includes('Range not found') ? `找不到“${trimmed}”所在的工作表` : `无法定位到“${trimmed}”`
    }
  }
  const goToDialog = createGoToDialog(shell.editor, navigateReference, () => focusWorkbookGrid(runtime))
  const queriesDialog = createWorkbookQueriesDialog(shell.editor, {
    getWorkbook: () => runtime.univerAPI.getActiveWorkbook()?.getWorkbook(),
    getBytes: () => original,
    isBlocked: () => !formulaBarAvailable(),
    onGo: reference => {
      if (staged.length || structural.length) return '工作簿结构或底稿已变化，请保存并重新打开后再定位来源查询'
      const resolved = resolveGoToRef(reference, [])
      const match = /^'((?:[^']|'')*)'!(.+)$/.exec(resolved ?? '')
      const sourceIndex = currentModel.sheets.findIndex(sheet => sheet.name === match?.[1]?.replaceAll("''", "'"))
      const live = sourceIndex < 0 ? undefined : runtime.univerAPI.getActiveWorkbook()?.getSheetBySheetId(`sheet-${sourceIndex}`)
      if (!live || !match) return '来源查询工作表已变化，无法定位；请保存并重新打开后重试'
      return navigateReference(`'${live.getSheetName().replaceAll("'", "''")}'!${match[2]}`)
    },
  })
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
  // 开始▸单元格▸格式▸设置单元格格式（数字页）：分类+选项生成格式代码，经同一校验与预算写入。
  let formatCellsTarget: ReturnType<typeof captureNumberFormatTarget>
  const formatCellsDialog = createFormatCellsDialog(shell.editor, {
    current: () => {
      const state = formatState().numberFormat
      const range = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSelection()?.getActiveRange()
      const value = range?.getValue?.()
      return { pattern: state.kind === 'value' ? String(state.value) : undefined, anchor: typeof value === 'number' || typeof value === 'string' ? value : null }
    },
    apply: pattern => {
      if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
      if (!formatCellsTarget) throw new Error('请先选择单元格或区域')
      if (formatState().numberFormat.kind === 'unavailable') throw new Error('来源格式未完整投影，暂不能安全编辑数字格式')
      validateNumberFormatBudget(runtime.univerAPI.getActiveWorkbook()!.getSnapshot(), currentModel, staged, structural.length, formatCellsTarget, pattern)
      applyCapturedNumberFormat(formatCellsTarget, formatWorkbook(), pattern, editable())
      markDirty(); ribbon.refreshState?.()
      feedback.textContent = `数字格式已设为 ${pattern}，值和公式保持不变；修改尚未保存。`
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
  // 按稳定工作表身份区分同名；保存时再将scope解析为当时的工作表名。
  const definedNameWorkbook = () => runtime.univerAPI.getActiveWorkbook() as unknown as DefinedNameWorkbook | null
  // facade 缺少 getDefinedNames（版本方差）时返回 undefined，对话框按空列表
  // 展示，保存差分跳过 defined names（绝不能把"读不到"当成"已全部删除"）。
  const definedNameRows = () => liveDefinedNames(definedNameWorkbook()) ?? []
  const definedNameSheets = () => runtime.univerAPI.getActiveWorkbook()?.getSheets().map(sheet => ({ id: sheet.getSheetId(), name: sheet.getSheetName() })) ?? []
  const projectedNameBaseline = (model: WorkbookModel) => (model.definedNames ?? []).filter(entry => !unprojectedNames.some(failed => {
    if (failed.name.toLowerCase() !== entry.name.toLowerCase()) return false
    if (!failed.scopeSheetId) return entry.scopeSheetName === undefined
    const scope = definedNameSheets().find(sheet => sheet.id === failed.scopeSheetId)
    return scope !== undefined && scope.name === entry.scopeSheetName
  }))
  const nameManagerDialog = createNameManagerDialog(shell.editor, {
    rows: definedNameRows,
    sheets: definedNameSheets,
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
  const pageSetupJournal = createPageSetupJournal(sheetId => structural.filter(item => item.sheetId === sheetId).map(item =>
    'op' in item ? shiftSpecOf(item.op) : cellShiftSpec(parseRange(item.cellShift.range), item.cellShift.shift)))
  let printCaptureEpoch = 0
  // 页面设置按真实保存顺序重放；几何来自同一轮实时快照，禁止混用旧模型坐标。
  const capturePrintInput = async (sheet: NonNullable<ReturnType<NonNullable<ReturnType<typeof runtime.univerAPI.getActiveWorkbook>>['getActiveSheet']>>) => {
    const { printSourceFromSnapshotSheet } = await import('./workbook-print')
    const workbook = runtime.univerAPI.getActiveWorkbook()!, epoch = printCaptureEpoch
    const snapshot = structuredClone(workbook.getSnapshot()), sheetId = sheet.getSheetId(), core = sheet.getSheet()
    const operations = await currentOperations()
    const model = await readModelWithStructureSource(await applyWorkbookOperations(original, operations))
    if (disposed || loading || epoch !== printCaptureEpoch || runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheet() !== core)
      throw new Error('工作表已变化，请重新预览或打印。')
    const file = model.sheets.find(item => item.name === sheet.getSheetName())
    if (!file || !snapshot.sheets[sheetId]) throw new Error('无法读取当前工作表的打印设置或网格快照，请重新加载。')
    return { source: printSourceFromSnapshotSheet(snapshot.sheets[sheetId], snapshot.styles as Record<string, import('./workbook-vendor/core/style-map').UniverStyleData>), setup: pageBreakPreviewSetup(file, {}) }
  }
  const openPrintPreview = async () => {
    const module = await import('./workbook-print-preview')
    const printModule = await import('./workbook-print')
    if (disposed) return
    if (!printPreviewDialog) printPreviewDialog = module.createWorkbookPrintPreviewDialog(shell.editor, {
      capture: async () => {
        const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
        if (!workbook || !sheet) throw new Error('工作簿尚未就绪')
        const epoch = printCaptureEpoch, version = mergeGeneration, core = sheet.getSheet(), snapshot = structuredClone(workbook.getSnapshot()) as unknown as { sheetOrder: readonly string[]; sheets: Readonly<Record<string, { name?: string; hidden?: number }>>; styles?: Readonly<Record<string, import('./workbook-vendor/core/style-map').UniverStyleData>> }
        const selection = sheet.getSelection()?.getActiveRange()
        const area = selection ? { startRow: selection.getRow(), endRow: selection.getRow() + selection.getHeight() - 1, startColumn: selection.getColumn(), endColumn: selection.getColumn() + selection.getWidth() - 1 } : null
        const operations = await currentOperations()
        const model = await readModelWithStructureSource(await applyWorkbookOperations(original, operations))
        return { snapshot, model, activeSheetId: sheet.getSheetId(), selection: area, fileName: sourcePath?.split(/[\\/]/).pop() ?? '', current: () => !disposed && !loading && epoch === printCaptureEpoch && version === mergeGeneration && runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheet() === core }
      },
      print: html => printModule.printDocument(html),
    })
    const workbook = runtime.univerAPI.getActiveWorkbook(), active = workbook?.getActiveSheet(), selection = active?.getSelection()?.getActiveRange()
    const visibleCount = workbook?.getSheets().filter(item => item.getSheet().getConfig().hidden !== 1).length ?? 0
    printPreviewDialog.open({ hasSelection: Boolean(selection), sheetCount: visibleCount })
  }
  const pageBreakPreview = createPageBreakPreviewController({
    target: () => loading || disposed ? null : runtime.univerAPI.getActiveWorkbook()?.getActiveSheet() ?? null,
    plan: async sheet => { const input = await capturePrintInput(sheet); return planPageBreakPreview(input.source, input.setup) },
    render: (sheet, plan, prefix) => installPageBreakOverlay(runtime, sheet, plan, prefix, sheet.getSheet().getConfig().rightToLeft === 1),
    changed: () => { ribbon.refreshState?.() },
  })
  let previewRefreshQueued = false
  const refreshPageBreakPreview = () => {
    printCaptureEpoch++
    if (previewRefreshQueued) return
    previewRefreshQueued = true
    queueMicrotask(() => { previewRefreshQueued = false; if (!disposed) void pageBreakPreview.refresh() })
  }
  // 监视窗口不参与保存时的底稿交互锁，仍可添加、删除和关闭监视。
  const watchWindow = createWorkbookWatchWindow(shell.editor.parentElement!, () => loading || disposed ? null : runtime.univerAPI.getActiveWorkbook(), () => { ribbon.refreshState?.() })
  const formulaTrace = createFormulaTraceController({
    target: () => loading || disposed ? null : runtime.univerAPI.getActiveWorkbook()?.getActiveSheet() ?? null,
    plan: (sheet, kind) => {
      const range = sheet.getSelection()?.getActiveRange()
      if (!range) throw new Error('请先选择单元格。')
      return planFormulaTrace(runtime.univerAPI.getActiveWorkbook()!.getSnapshot(), sheet.getSheetName(), { row: range.getRow(), column: range.getColumn() }, kind,
        { lastRow: sheet.getLastRow(), lastColumn: sheet.getLastColumn(), maxRows: sheet.getMaxRows(), maxColumns: sheet.getMaxColumns() })
    },
    render: (sheet, plan, prefix) => installFormulaTraceOverlay(runtime, {
      getRange: (row, column, rows, columns) => sheet.getRange(row, column, rows, columns),
      addFloatDomToRange: (range, layer, layout, key) => sheet.addFloatDomToRange(range, layer, layout, key),
      getColumnWidth: index => sheet.getSheet().getColVisible(index) ? sheet.getColumnWidth(index) : 0,
      getRowHeight: index => sheet.getSheet().getRowRawVisible(index) ? sheet.getRowHeight(index) : 0,
      isMergedCell: (row, column) => Boolean(sheet.getSheet().getMergedCell(row, column)),
      getFreeze: () => sheet.getSheet().getFreeze(),
    }, plan, prefix, sheet.getSheet().getConfig().rightToLeft === 1),
    changed: () => { ribbon.refreshState?.() },
  })
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
  const printScaleDialog = createPrintScaleDialog(shell.editor, (scale, target) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const context = activePageSetupContext()
    if (!context || context.liveWorkbook.getWorkbook() !== target.book || context.sheet.getSheet() !== target.sheet || context.sheet.getSheetId() !== target.sheetId)
      throw new Error('原工作表已变化，请重新打开打印缩放比例')
    if (sheetProtected(target.sheetId)) throw new Error('工作表受保护，请先撤销保护')
    const patch = printScalePatch(originalSheet(target.sheetId)?.pageSetup, pageSetupJournal.get(target.sheetId), scale)
    if (!patch) return
    pageSetupJournal.set(target.sheetId, patch)
    refreshPageBreakPreview()
    markDirty()
    ribbon.refreshState?.()
    feedback.textContent = `打印缩放比例已设为 ${scale}%，修改尚未保存。`
  })
  const headerFooterDialog = createHeaderFooterDialog(shell.editor, (changes, target) => {
    if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
    const context = activePageSetupContext()
    if (!context || context.liveWorkbook.getWorkbook() !== target.book || context.sheet.getSheet() !== target.sheet || context.sheet.getSheetId() !== target.sheetId)
      throw new Error('原工作表已变化，请重新打开页眉页脚')
    if (sheetProtected(target.sheetId)) throw new Error('工作表受保护，请先撤销保护')
    pageSetupJournal.set(target.sheetId, { ...pageSetupJournal.get(target.sheetId), ...changes })
    refreshPageBreakPreview()
    markDirty()
    ribbon.refreshState?.()
    feedback.textContent = '页眉页脚已更新，修改尚未保存。'
  })
  let outlineGutter: OutlineGutterHandle | undefined
  const applyOutlineResult = (result: { changed: boolean; message: string }) => {
    if (result.changed) { markDirty(); ribbon.refreshState?.(); outlineGutter?.refresh() }
    feedback.textContent = result.message
  }
  const runOutlineCommand = (command: string) => {
    if (!editable()) return
    if (command === 'outline-summary-below' || command === 'outline-summary-right') {
      const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
      if (!sheet) throw new Error('请先选择工作表')
      const summary = readWorkbookOutlineSummary(sheet)
      applyOutlineResult(setWorkbookOutlineSummary(runtime, command === 'outline-summary-below' ? { below: !summary.summaryBelow } : { right: !summary.summaryRight }, id => sheetProtected(id)))
      return
    }
    const action = command.startsWith('outline-group:') ? 'group' : command.startsWith('outline-ungroup:') ? 'ungroup'
      : command.startsWith('outline-hide-detail') ? 'hide-detail' : command === 'outline-clear' ? 'clear' : 'show-detail'
    const axis = command.endsWith(':rows') ? 'rows' : command.endsWith(':cols') ? 'cols' : 'auto'
    applyOutlineResult(applyWorkbookOutline(runtime, action, axis, id => sheetProtected(id)))
  }
  let pivotContext: {bytes:Uint8Array;operations:WorkbookOperation[]} | undefined
  let pivotControlOverlay: ReturnType<(typeof import('./workbook-pivot-controls'))['installPivotControlOverlay']> | undefined
  let pivotControlGeneration = 0
  let pivotDialog: ReturnType<(typeof import('./workbook-pivot-dialog'))['createPivotDialog']> | undefined
  let pivotFilterDialog: ReturnType<(typeof import('./workbook-pivot-filters-dialog'))['createPivotFilterDialog']> | undefined
  let editableRangesDialog: ReturnType<(typeof import('./workbook-editable-ranges-dialog'))['createEditableRangesDialog']> | undefined
  let editableRangesContext: { bytes: Uint8Array; operations: WorkbookOperation[] } | undefined
  // 固定源 Insert ▸ 链接（ExcelShell LinkDialog → set_hyperlink）：链接写在工作表 hyperlinks 与关系部件里，
  // 当前状态来自草稿重放后的字节；写入以单元格当前链接为来源身份，追加到草稿后由浏览器内引擎重放。
  let linkTarget: { sheetName: string; sheetId: string; row: number; column: number; current: string | null } | undefined
  const openLinkDialog = async () => {
    if (!editable()) throw new Error('工作簿正在加载或保存')
    const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
    const anchor = active?.getSelection()?.getActiveRange()
    if (!active || !anchor) throw new Error('请先选中一个单元格，再插入链接')
    if (sheetProtected(active.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
    await persistence
    const operations = await currentOperations()
    const bytes = operations.length ? await applyWorkbookOperations(original, operations) : original
    const row = anchor.getRow(), column = anchor.getColumn(), sheetName = active.getSheetName()
    const current = cellHyperlinkState(await readPackageSheetHyperlinks(bytes, sheetName), row, column)
    linkTarget = { sheetName, sheetId: active.getSheetId(), row, column, current }
    linkDialog.open(current)
  }
  const applyLink = async (target: string | null) => {
    const context = linkTarget
    if (!editable() || !context) throw new Error('工作簿不可编辑，请重新打开链接')
    if (target === context.current) return
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      const before = await currentOperations()
      const ref = formatAddress(context.row, context.column)
      const operation = { kind: 'applySheetHyperlinks', sheetName: context.sheetName, edits: [{ ref, expectedTarget: context.current, target }] }
      // 固定源 applyAiHyperlink / link-set：链接单元格为蓝色下划线（#0563C1）；删除链接时清除下划线与字体颜色（cl/ul 置空）。
      // 作为同一步的仅样式单元格编辑写入，撤销/重做与链接一起进出历史。
      const style = { kind: 'applyCellEdits', edits: [{ sheetName: context.sheetName, row: context.row, column: context.column, writeValue: false, cell: { value: null },
        style: target === null ? { underline: false, fontColor: null } : { underline: true, underlineStyle: 'single', fontColor: '#0563C1' } }] }
      const operations = [...before, operation as unknown as WorkbookOperation, style as unknown as WorkbookOperation]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(before); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(before as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
    feedback.textContent = `${target === null ? LINK_TEXT.removed : LINK_TEXT.saved}修改尚未保存。`
  }
  const linkDialog = createWorkbookLinkDialog(shell.editor, applyLink)
  // 页面布局▸主题：状态来自当前重放字节的主题部件（含草稿中已应用的主题操作）。
  let themeSource: WorkbookThemeSource | undefined
  const applyTheme = async (kind: ThemeCommandKind, id: string) => {
    if (!editable() || !themeSource) throw new Error('当前工作簿不可编辑或尚未就绪')
    const { operation, name } = themeOperation(kind, id, themeSource)
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      const before = await currentOperations()
      const operations = [...before, operation as unknown as WorkbookOperation]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(before); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(before as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
      feedback.textContent = `${kind === 'theme' ? '主题' : kind === 'theme-colors' ? '主题颜色' : '主题字体'}已设为「${name}」，修改尚未保存；引用主题色或主题字体的单元格已随之更新。`
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const applyEditableRanges = async (sheetName: string, ranges: { name: string; sqref: string }[]) => {
    if (!editable() || !editableRangesContext) throw new Error('工作簿不可编辑，请重新打开允许编辑区域')
    const context = editableRangesContext
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      if (JSON.stringify(await currentOperations()) !== JSON.stringify(context.operations)) throw new Error('草稿已变化，请重新打开允许编辑区域')
      const target = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === sheetName)
      if (!target || sheetProtected(target.getSheetId())) throw new Error('工作表不存在或受保护，请先撤销保护后管理允许编辑区域')
      const { createEditableRangesPlan } = await import('./workbook-editable-ranges')
      const plan = await createEditableRangesPlan(context.bytes, sheetName, ranges)
      const operations = [...context.operations, ...plan.operations]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(context.operations); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(context.operations as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
      feedback.textContent = '允许编辑区域已更新，保存后写入文件；启用工作表保护后可在这些区域输入值和公式。'
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const openEditableRanges = async () => {
    const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
    if (!editable() || !sheet) return
    if (sheetProtected(sheet.getSheetId())) throw new Error('请先撤销工作表保护后管理允许编辑区域')
    await persistence
    const operations = await currentOperations(), bytes = await applyWorkbookOperations(original, operations)
    const ranges = await readWorkbookEditableRanges(bytes)
    if (!editableRangesDialog) {
      const { createEditableRangesDialog } = await import('./workbook-editable-ranges-dialog')
      if (disposed) return
      editableRangesDialog = createEditableRangesDialog(shell.editor, applyEditableRanges)
    }
    editableRangesContext = { bytes, operations }
    const selection = sheet.getSelection()?.getActiveRange()
    editableRangesDialog.open({ sheetName: sheet.getSheetName(), ranges: ranges.get(sheet.getSheetName()) ?? [],
      selection: selection ? formatAddress(selection.getRow(), selection.getColumn()) + ':' + formatAddress(selection.getRow() + selection.getHeight() - 1, selection.getColumn() + selection.getWidth() - 1) : undefined })
  }
  const applyPivot = async (config:import('./workbook-pivot').PivotConfig,tablePath?:string,control?:import('../../../reporting/workbook_engine/packages/xlsx-engine/src/pivot-controls').PivotControlRequest) => {
    if (!editable() || !pivotContext) throw new Error('工作簿不可编辑，请重新打开透视表配置')
    const context = pivotContext
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      if (JSON.stringify(await currentOperations()) !== JSON.stringify(context.operations)) throw new Error('草稿已变化，请重新打开透视表配置')
      const targetSheet = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === config.targetSheetName)
      if (!targetSheet || sheetProtected(targetSheet.getSheetId())) throw new Error('目标工作表不存在或受保护')
      const {createPivotPlan,editPivotPlan} = await import('./workbook-pivot')
      const plan = tablePath ? await editPivotPlan(context.bytes, tablePath, config) : await createPivotPlan(context.bytes, config)
      const pivotOperations = control ? plan.operations.map(operation => operation.kind === 'applyPivotLayoutExpansions' ? { ...operation, controlRequest: control } : operation) : plan.operations
      const operations = [...context.operations, ...pivotOperations, ...(control ? [{ kind: 'upsertPivotControl', request: control }] : [])]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(context.operations); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(context.operations as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
      feedback.textContent = tablePath ? '透视表字段与缓存已更新，修改尚未保存。' : '数据透视表已创建，修改尚未保存。'
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const removePivotControl = async (control:import('../../../reporting/workbook_engine/packages/xlsx-engine/src/pivot-controls').PivotControl) => {
    if (!editable() || !pivotContext) throw new Error('工作簿不可编辑，请重新打开透视表筛选')
    const context = pivotContext
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      if (JSON.stringify(await currentOperations()) !== JSON.stringify(context.operations)) throw new Error('草稿已变化，请重新打开透视表筛选')
      const { readWorkbookPivots } = await import('./workbook-pivot')
      const pivot = (await readWorkbookPivots(context.bytes)).find(item => item.tablePath === control.tablePath)
      const target = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === pivot?.targetSheetName)
      if (!pivot || !target || sheetProtected(target.getSheetId())) throw new Error('目标工作表不存在或受保护')
      const operations = [...context.operations, { kind: 'removePivotControl', request: { tablePath: control.tablePath, name: control.name } }]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(context.operations); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(context.operations as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
      feedback.textContent = '原生控件已删除，当前筛选结果已保留，修改尚未保存。'
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const refreshAllPivots = async () => {
    if (!editable()) return
    await withWorkbookLocked(shell.editor, async () => {
      await persistence
      const before = await currentOperations()
      const bytes = await applyWorkbookOperations(original, before)
      const { readWorkbookPivots, refreshWorkbookPivotsPlan } = await import('./workbook-pivot')
      const pivots = await readWorkbookPivots(bytes)
      for (const pivot of pivots) {
        const target = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === pivot.targetSheetName)
        if (!target || sheetProtected(target.getSheetId())) throw new Error('透视表目标工作表不存在或受保护，未执行全部刷新')
      }
      const plan = await refreshWorkbookPivotsPlan(bytes)
      if (disposed) return
      const operations = [...before, ...plan.operations]
      captureGeneration++
      try { await loadOperations(operations) }
      catch (error) { await loadOperations(before); throw error }
      if (nativeDraft) {
        nativeDraft.setOperations(before as NativeOperation[])
        nativeDraft.setOperations(operations as NativeOperation[])
      } else draft.setOperations(operations)
      gridChanged = false; dirty = true
      shell.statusLabel.textContent = '有未保存修改'
      feedback.textContent = `已刷新 ${plan.count} 个透视表的结果与缓存，修改尚未保存。`
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const getPivotDialog = async () => {
    if (!pivotDialog) {
      const module = await import('./workbook-pivot-dialog')
      if (disposed) throw new Error('工作簿已关闭')
      pivotDialog = module.createPivotDialog(shell.editor,applyPivot)
    }
    return pivotDialog
  }
  const openPivot = async (editing:boolean) => {
    const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), selection = sheet?.getSelection()?.getActiveRange()
    if (!editable() || !sheet || !selection) return
    const sheetName = sheet.getSheetName(), row = selection.getRow(), column = selection.getColumn()
    const bounds = selection.getHeight() === 1 && selection.getWidth() === 1 ? inferTableRegion(sheet,row,column) : undefined
    const sourceRange = formatAddress(bounds?.startRow ?? row,bounds?.startColumn ?? column) + ':' + formatAddress(bounds?.endRow ?? row+selection.getHeight()-1,bounds?.endColumn ?? column+selection.getWidth()-1)
    await persistence
    const operations = await currentOperations(), bytes = await applyWorkbookOperations(original,operations)
    const {readWorkbookPivots} = await import('./workbook-pivot')
    const pivots = editing ? await readWorkbookPivots(bytes) : undefined
    if (editing && !pivots?.length) throw new Error('当前工作簿没有可编辑的数据透视表')
    pivotContext = {bytes,operations}
    const selected = pivots?.find(pivot => pivot.targetSheetName===sheetName && row>=pivot.location.startRow && row<=pivot.location.endRow && column>=pivot.location.startColumn && column<=pivot.location.endColumn)
    await (await getPivotDialog()).open({bytes,sourceSheetName:sheetName,sourceRange,targetCell:formatAddress(row,column+selection.getWidth()+2),pivots,selectedTablePath:selected?.tablePath})
  }
  const openPivotFilter = async (mode: 'slicer' | 'timeline') => {
    const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), selection = sheet?.getSelection()?.getActiveRange()
    if (!editable() || !sheet || !selection) return
    await persistence
    const operations = await currentOperations(), bytes = await applyWorkbookOperations(original, operations)
    const { readWorkbookPivots } = await import('./workbook-pivot')
    const pivots = await readWorkbookPivots(bytes)
    if (!pivots.length) throw new Error('当前工作簿没有可筛选的数据透视表')
    if (!pivotFilterDialog) {
      const { createPivotFilterDialog } = await import('./workbook-pivot-filters-dialog')
      if (disposed) return
      pivotFilterDialog = createPivotFilterDialog(shell.editor, applyPivot, removePivotControl)
    }
    pivotContext = { bytes, operations }
    const selected = pivots.find(pivot => pivot.targetSheetName === sheet.getSheetName() && selection.getRow() >= pivot.location.startRow && selection.getRow() <= pivot.location.endRow && selection.getColumn() >= pivot.location.startColumn && selection.getColumn() <= pivot.location.endColumn)
    await pivotFilterDialog.open({ bytes, pivots, selectedTablePath: selected?.tablePath, mode })
  }
  const nativeHistory = async (direction:'undo'|'redo') => {
    if (!nativeDraft) return
    await withWorkbookLocked(shell.editor,async()=>{
      await persistence
      nativeDraft.setOperations(await currentOperations() as NativeOperation[])
      if(direction==='undo')nativeDraft.undo();else nativeDraft.redo()
      captureGeneration++;await loadOperations(nativeDraft.operations as WorkbookOperation[])
      gridChanged=false;dirty=nativeDraft.dirty
      shell.statusLabel.textContent=dirty?'有未保存修改':'已保存'
    }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
  }
  const pivotHistoryShortcut = (event:KeyboardEvent) => {
    if (!nativeDraft || gridChanged || !editable() || runtime.univerAPI.getActiveWorkbook()?.isCellEditing?.() || !event.ctrlKey && !event.metaKey) return
    const direction = event.key.toLowerCase()==='y' || event.key.toLowerCase()==='z' && event.shiftKey ? 'redo' : event.key.toLowerCase()==='z' ? 'undo' : undefined
    if (!direction || !(direction==='undo'?nativeDraft.canUndo:nativeDraft.canRedo)) return
    if ((event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]')) return
    event.preventDefault();event.stopImmediatePropagation()
    void nativeHistory(direction).catch(error=>{feedback.textContent=(error as Error).message})
  }
  shell.editor.addEventListener('keydown',pivotHistoryShortcut,true)
  const ribbon = mountWorkbookRibbon(
    shell.editor.querySelector<HTMLElement>('.workbook-ribbon-host')!,
    (command, capturedTarget) => {
      if (calculationBusy) return
      if (command === 'allow-edit-ranges-open') {
        void openEditableRanges().catch(error => { feedback.textContent = (error as Error).message }); return
      }
      if (command === 'slicer-open' || command === 'timeline-open') {
        void openPivotFilter(command === 'slicer-open' ? 'slicer' : 'timeline').catch(error => { feedback.textContent = (error as Error).message }); return
      }
      if (command === 'refresh-all') {
        void refreshAllPivots().catch(error => { feedback.textContent = (error as Error).message }); return
      }
      if (command === 'pivot-open' || command === 'pivot-edit') {
        void openPivot(command === 'pivot-edit').catch(error => { feedback.textContent = (error as Error).message }); return
      }
      if (command === 'toggle-right-to-left') {
        if (!formulaBarAvailable() || rtlBusy) return
        const next = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheet().getConfig().rightToLeft !== 1
        rtlBusy = true; ribbon.refreshState?.()
        void rtl.set(next).then(() => { if (editable()) markDirty(); feedback.textContent = next ? '已切换为从右到左。' : '已切换为从左到右。' },
          (error: unknown) => { feedback.textContent = (error as Error).message }).finally(() => { rtlBusy = false; ribbon.refreshState?.() })
        return
      }
      if (command === 'toggle-headings') {
        if (!formulaBarAvailable() || headingsBusy) return
        headingsBusy = true
        ribbon.refreshState?.()
        void toggleWorkbookHeadings(runtime, () => !disposed).then(result => {
          if (editable()) markDirty()
          feedback.textContent = `已${result.showHeadings ? '显示' : '隐藏'}行列标题。`
        }, (error: unknown) => { feedback.textContent = (error as Error).message }).finally(() => {
          headingsBusy = false; ribbon.refreshState?.()
        })
        return
      }
      if (command === 'toggle-cross-highlight') {
        if (!formulaBarAvailable()) return
        crossHighlightVisible = !crossHighlightVisible
        crossHighlight.setVisible(crossHighlightVisible)
        storeCrossHighlightPreference(crossHighlightVisible)
        feedback.textContent = crossHighlightVisible ? '已开启活动行列突出显示。' : '已关闭活动行列突出显示。'
        ribbon.refreshState?.()
        return
      }
      if (command === 'toggle-formula-bar') {
        if (!formulaBarAvailable()) return
        feedback.textContent = formulaBar.toggle() ? '已显示编辑栏。' : '已隐藏编辑栏。'
        ribbon.refreshState?.()
        return
      }
      if (command === 'insert-function-open' || command.startsWith('insert-function-open:')) {
        if (!editable()) return
        void insertFunction.open(command.includes(':') ? command.slice(command.indexOf(':') + 1) : 'All')
          .catch(error => { if (!disposed) feedback.textContent = (error as Error).message })
        return
      }
      if (command === 'workbook-statistics') {
        if (loading || disposed) return
        const statistics = readWorkbookStatistics(runtime)
        feedback.textContent = statistics?.message ?? '工作簿尚未就绪'
        return
      }
      if (command === 'error-checking') {
        if (!formulaBarAvailable()) return
        const check = errorChecking.check()
        ribbon.refreshState?.()
        void check.finally(() => { if (!disposed) ribbon.refreshState?.() })
        return
      }
      if (command === 'watch-window') { if (!loading && !disposed) watchWindow.toggle(); return }
      if (command === 'queries-open') { void queriesDialog.open(); return }
      if (command === 'trace-precedents' || command === 'trace-dependents' || command === 'remove-arrows') {
        if (loading || saving || disposed) return
        try {
          feedback.textContent = command === 'remove-arrows' ? formulaTrace.clear() : formulaTrace.trace(command === 'trace-precedents' ? 'precedents' : 'dependents') ?? ''
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'normal-view' || command === 'toggle-page-break-preview') {
        if (loading || disposed) return
        void pageBreakPreview.setVisible(command === 'toggle-page-break-preview').then(() => {
          const state = pageBreakPreview.state()
          if (!disposed) feedback.textContent = state.reason ?? (state.active ? ['已开启分页预览。', ...state.issues].join(' ') : '已切换到普通视图。')
        })
        return
      }
      if (command === 'print' || command === 'undo' || command === 'redo') {
        // 固定源 File/Edit 菜单语义：打印为只读操作（与查找一致，保存后仍可
        // 用）；撤销/恢复重放 Univer 历史（与网格快捷键同一命令栈），需可编辑态。
        const blocked = loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')
        if (command === 'print' ? loading || disposed : blocked) return
        try {
          const workbook = runtime.univerAPI.getActiveWorkbook()
          const sheet = workbook?.getActiveSheet()
          if (!workbook || !sheet) throw new Error('工作簿尚未就绪')
          if ((command === 'undo' || command === 'redo') && nativeDraft && !gridChanged && (command === 'undo' ? nativeDraft.canUndo : nativeDraft.canRedo)) {
            void nativeHistory(command).catch(error => { feedback.textContent = (error as Error).message }); return
          }
          if (command === 'undo' || command === 'redo') {
            void (command === 'undo' ? runtime.univerAPI.undo() : runtime.univerAPI.redo()).then(applied => {
              feedback.textContent = applied
                ? command === 'undo' ? '已撤销上一步修改，修改尚未保存。' : '已恢复上一步修改，修改尚未保存。'
                : command === 'undo' ? '没有可撤销的修改。' : '没有可恢复的修改。'
            }, (error: unknown) => { feedback.textContent = (error as Error).message })
            return
          }
          void openPrintPreview().catch(error => { if (!disposed) feedback.textContent = (error as Error).message })
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'merge-workbooks') {
        if (!editable() || structureLocked()) return
        void import('./workbook-merge').then(({ openWorkbookMergeAction }) => openWorkbookMergeAction({
          capture: () => ({ workbook: runtime.univerAPI.getActiveWorkbook(), draft: `${mergeGeneration}:${JSON.stringify(staged)}${JSON.stringify(structural)}` }),
          isBlocked: () => !editable() || structureLocked(),
          setMessage: message => { if (!disposed) feedback.textContent = message },
          wait: () => persistence,
          original: () => original,
          currentOperations,
          loadOperations,
          locked: operation => withWorkbookLocked(shell.editor, operation),
          onApplied: (files, sheets) => { markDirty(); feedback.textContent = `已合并 ${files} 个工作簿、${sheets} 个工作表，修改尚未保存。`; ribbon.refreshState?.() },
        })).catch(error => { if (!disposed) feedback.textContent = (error as Error).message })
        return
      }
      if (command === 'import-csv') {
        if (!editable()) return
        disposeCsvImport?.()
        disposeCsvImport = openWorkbookCsvImport({
          getWorkbook: () => runtime.univerAPI.getActiveWorkbook(),
          isBlocked: () => !editable() || sheetProtected(activeSheetId()),
          setMessage: message => { if (!disposed) feedback.textContent = message },
          onImported: () => { markDirty(); ribbon.refreshState?.() },
        })
        return
      }
      if (command.startsWith('cell-style:')) {
        if (!editable()) return
        try {
          if (sheetProtected(activeSheetId())) throw new Error('工作表受保护，请先撤销保护')
          if (!applyWorkbookCellStyle(runtime, command.slice('cell-style:'.length))) throw new Error('请选择单元格和有效的样式预设')
          feedback.textContent = '已应用单元格样式，修改尚未保存。'
          ribbon.refreshState?.()
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command.startsWith('sparkline:')) {
        if (!editable() || !sparklines) return
        try {
        const type = command.slice('sparkline:'.length)
        if (type === 'delete') sparklines.remove()
        else if (type === 'edit') {
          const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
          const spec = sheet && range ? sparklines.display(sheet.getSheetId()).find(item => item.target.replaceAll('$', '') === formatAddress(range.getRow(), range.getColumn())) : undefined
          if (!spec) throw new Error('请选择一个迷你图宿主单元格')
          const target = { sheetId: sheet!.getSheetId(), target: formatAddress(range!.getRow(), range!.getColumn()) }
          sparklineDialog ??= createSparklineDialog(shell.editor, (updates, captured) => {
            if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
            const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), selected = active?.getSelection()?.getActiveRange()
            if (active?.getSheetId() !== captured.sheetId || !selected || selected.getHeight() !== 1 || selected.getWidth() !== 1 || formatAddress(selected.getRow(), selected.getColumn()) !== captured.target) throw new Error('迷你图目标已变化，请重新选择后操作')
            sparklines!.edit(updates); markDirty(); ribbon.refreshState?.(); feedback.textContent = '迷你图已更新，修改尚未保存。'
          })
          sparklineDialog.open(spec, target)
          return
        } else sparklines.add(type as 'line' | 'column' | 'stacked')
          feedback.textContent = '已新增迷你图，修改尚未保存。'
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'insert-checkbox') {
        if (!editable()) return
        try {
          const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
          if (!sheet || !sheet.getSelection()?.getActiveRange()) throw new Error('请先选择单元格或区域')
          if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          const source = originalSheet(sheet.getSheetId()) ?? currentModel.sheets.find(item => item.name === sheet.getSheetName())
          if (source?.dataValidations?.readOnlyReason) throw new Error(source.dataValidations.readOnlyReason)
          if (!applyWorkbookCheckbox(runtime)) throw new Error('请先选择单元格或区域')
          feedback.textContent = '已插入复选框，修改尚未保存。'
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'format-as-table') {
        if (!editable()) return
        try {
          const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
          if (!sheet || !range) throw new Error('请先选择单元格或区域')
          if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          const source = originalSheet(sheet.getSheetId()) ?? currentModel.sheets.find(item => item.name === sheet.getSheetName())
          if (source?.tablesReadOnlyReason) throw new Error(source.tablesReadOnlyReason)
          const area = range.getHeight() === 1 && range.getWidth() === 1 ? inferTableRegion(sheet, range.getRow(), range.getColumn()) ?? { startRow: range.getRow(), endRow: range.getRow(), startColumn: range.getColumn(), endColumn: range.getColumn() }
            : { startRow: range.getRow(), endRow: range.getRow() + range.getHeight() - 1, startColumn: range.getColumn(), endColumn: range.getColumn() + range.getWidth() - 1 }
          tableCreateDialog.open({ sheetId: sheet.getSheetId(), range: `${formatAddress(area.startRow, area.startColumn)}:${formatAddress(area.endRow, area.endColumn)}` })
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'toggle-show-formulas' || command === 'calculate-now' || command === 'calculate-sheet' || command.startsWith('calc-mode:')) {
        // 仅改变显示/计算结果，只读与保存后亦可用；公式视图在可编辑时随保存写回 sheetView/@showFormulas。
        if (loading || disposed) return
        try {
          const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
          if (!sheet || !calculation) throw new Error('工作簿尚未就绪')
          if (command === 'toggle-show-formulas') {
            const sheetId = sheet.getSheetId(), next = !formulaSheets.has(sheetId)
            if (next) formulaSheets.add(sheetId); else formulaSheets.delete(sheetId)
            calculation.syncFormulaView(next)
            if (editable()) markDirty()
            feedback.textContent = next ? '正在显示公式（保存后写入工作表视图）。' : '正在显示计算结果。'
          } else if (command === 'calculate-now' || command === 'calculate-sheet') {
            if (command === 'calculate-now') calculation.calculateNow()
            else calculation.calculateSheet({ unitId: runtime.univerAPI.getActiveWorkbook()!.getId(), sheetId: sheet.getSheetId(), sheetName: sheet.getSheetName(), rows: sheet.getMaxRows(), columns: sheet.getMaxColumns() })
            feedback.textContent = command === 'calculate-now' ? '已重新计算工作簿；计算结果不作为修改保存。' : '已重新计算当前工作表；计算结果不作为修改保存。'
          } else {
            const manual = command === 'calc-mode:manual'
            calculation.setManual(manual)
            feedback.textContent = manual ? '计算模式为手动：修改后按“开始计算”或“计算工作表”更新结果（仅当前编辑会话）。' : '计算模式为自动，已重新计算。'
          }
          ribbon.refreshState?.()
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'zoom-open') {
        openZoom()
        return
      }
      if (command === 'zoom-to-selection' || command.startsWith('zoom:')) {
        runZoom(command as WorkbookZoomCommand)
        return
      }
      if (command === 'zoom-in' || command === 'zoom-out' || command === 'zoom-reset') {
        runZoom(command)
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
      if (command === 'link-open') {
        void openLinkDialog().catch(error => { feedback.textContent = (error as Error).message })
        return
      }
      if (command === 'insert-symbol') {
        if (!editable()) return
        const active = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
        if (!active?.getSelection()?.getActiveRange()) { feedback.textContent = '请先选中一个单元格，再插入符号'; return }
        if (sheetProtected(active.getSheetId())) { feedback.textContent = '工作表受保护，请先撤销保护'; return }
        symbolDialog.open()
        return
      }
      if (command === 'header-footer-open') {
        if (!editable()) return
        try {
          const context = activePageSetupContext()
          if (!context) throw new Error('工作簿尚未就绪')
          const { liveWorkbook, sheet } = context
          if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          headerFooterDialog.open(headerFooterEditorState(originalSheet(sheet.getSheetId())?.headerFooter, pageSetupJournal.get(sheet.getSheetId())), { book: liveWorkbook.getWorkbook(), sheet: sheet.getSheet(), sheetId: sheet.getSheetId() })
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (command === 'print-scale-open') {
        if (!editable()) return
        try {
          const context = activePageSetupContext()
          if (!context) throw new Error('工作簿尚未就绪')
          const { liveWorkbook, sheet } = context
          if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          printScaleDialog.open(printScaleState(originalSheet(sheet.getSheetId())?.pageSetup, pageSetupJournal.get(sheet.getSheetId())), { book: liveWorkbook.getWorkbook(), sheet: sheet.getSheet(), sheetId: sheet.getSheetId() })
        } catch (error) { feedback.textContent = (error as Error).message }
        return
      }
      if (/^theme(-colors|-fonts)?:/.test(command)) {
        if (loading || saving || saved || disposed || shell.editor.inert || shell.editor.closest('[inert]')) return
        const [kind, id] = command.split(/:(.*)/s) as [ThemeCommandKind, string]
        void applyTheme(kind, id).catch(error => { feedback.textContent = (error as Error).message })
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
            refreshPageBreakPreview()
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
      if (command === 'format-painter' || command === 'format-painter:dblclick') {
        // 固定源 ribbon-actions format-painter：单击刷一次、双击锁定、再次单击或 Esc 取消；
        // 刷出的样式经 set-range-values 写入网格，保存时由样式差分写回。
        if (!editable()) return
        try {
          const action = applyFormatPainterClick(runtime, command === 'format-painter' ? 1 : 2)
          if (action === 'once') feedback.textContent = '已复制格式，选择目标区域即可应用（一次）。'
          else if (action === 'lock') feedback.textContent = '格式刷已锁定，可连续应用；按 Esc 或再次点击取消。'
          else if (action === 'cancel') feedback.textContent = '格式刷已取消。'
          else if (action === 'not-ready') feedback.textContent = '格式刷正在初始化，请稍候再试。'
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
        return
      }
      if (CLIPBOARD_COMMANDS[command]) {
        // 固定源 ribbon-actions：复制为只读安全命令；剪切/粘贴/选择性粘贴需可编辑态。
        // 粘贴经 Univer sheet 剪贴板（Clipboard API 不可用时回退内部复制缓存），写入走
        // sheet.mutation.*（已标记未保存），保存时由值/样式/合并/列宽差分写回。
        if (command === 'copy' ? loading || disposed : !editable()) return
        void runtime.univerAPI.executeCommand(CLIPBOARD_COMMANDS[command]!, clipboardCommandParams(command)).then(applied => {
          if (!applied) { feedback.textContent = command === 'copy' || command === 'cut' ? '请先选择单元格或区域' : '剪贴板中没有可粘贴的内容，或浏览器未授予剪贴板读取权限'; return }
          if (command === 'copy') feedback.textContent = '已复制选区。'
          else if (command === 'cut') feedback.textContent = '已剪切选区；粘贴后原位置内容移出，修改尚未保存。'
          else { markDirty(); ribbon.refreshState?.(); feedback.textContent = '已粘贴，修改尚未保存。' }
        }, (error: unknown) => { feedback.textContent = (error as Error).message })
        return
      }
      const readingNote = ['note-open', 'note-prev', 'note-next', 'note-show-toggle'].includes(command)
      // 定位只移动选区（固定源只读安全）：保存中/已保存/只读亦可用。
      if (command === 'goto-open') {
        if (loading || disposed) return
        goToDialog.open(definedNameRows().map(row => ({ name: row.name, ref: row.refersTo })))
        return
      }
      if (readingNote ? loading || saving || disposed : !editable()) return
      const workbook = runtime.univerAPI.getActiveWorkbook()
      if (!workbook) return
      try {
        if (command === 'chart-delete') {
          const sheetName = workbook.getActiveSheet()?.getSheetName()
          const charts = currentModel.sheets.find(sheet => sheet.name === sheetName)?.charts ?? []
          if (charts.length !== 1) throw new Error(charts.length ? '当前工作表含多个图表，暂不支持选择要删除的图表' : '请先打开包含图表的工作表')
          const chart = charts[0]!
          void loadOperations([...staged, { kind: 'applyChartDeletions', deletions: [{ sheetName: sheetName!, chartPath: chart.chartPath }] }]).then(() => {
            markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表已删除，修改尚未保存。'
          }).catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'chart-switch-row-col') {
          const sheet = workbook.getActiveSheet(), sheetName = sheet?.getSheetName()
          const charts = currentModel.sheets.find(item => item.name === sheetName)?.charts ?? []
          if (!sheet || charts.length !== 1) throw new Error('请打开仅包含一个图表的工作表后切换行列')
          if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          const chart = charts[0]!
          const seriesSet = switchChartSeries(chart, sheet.getSheetName(), (row, column) => sheet.getRange(row, column).getValue())
          void currentOperations().then(operations => {
            if (!editable() || workbook.getActiveSheet()?.getSheet() !== sheet.getSheet()) throw new Error('图表来源已变化，请重新操作')
            return loadOperations([...operations, { kind: 'applyChartEdits', edits: [{ chartPath: chart.chartPath, seriesSet }] }])
          }).then(() => {
            markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表行列已切换，修改尚未保存。'
          }).catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'chart-select-data') {
          const sheet = workbook.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
          const sheetName = sheet?.getSheetName()
          const charts = currentModel.sheets.find(item => item.name === sheetName)?.charts ?? []
          if (!sheet || !range || !sheetName) throw new Error('请先选择新的图表数据区域')
          if (charts.length !== 1) throw new Error(charts.length ? '当前工作表含多个图表，暂不支持选择要编辑的图表' : '请先打开包含图表的工作表')
          const chart = charts[0]!
          if (chart.kind === 'combo') throw new Error('组合图暂不支持整体替换数据系列')
          const values = typeof range.getValues === 'function' ? range.getValues() as unknown as (readonly (string | number | boolean | null | undefined)[][]) : undefined
          if (!Array.isArray(values)) throw new Error('当前工作簿无法读取图表数据区域')
          const selection = range.getRange()
          const type = chart.kind === 'scatter' ? 'scatter' : chart.kind === 'radar' ? 'radar' : chart.kind
          const replacement = chartAdditionFromGrid({ sheetName, chartType: type as 'column' | 'bar' | 'line' | 'area' | 'pie' | 'scatter' | 'radar' | 'doughnut', range: { startRow: selection.startRow, endRow: selection.endRow, startColumn: selection.startColumn, endColumn: selection.endColumn }, values })
          void loadOperations([...staged, { kind: 'applyChartEdits', edits: [{ chartPath: chart.chartPath, seriesSet: replacement.chart.series }] }]).then(() => {
            markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表数据已更新，修改尚未保存。'
          }).catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'chart-title' || command === 'chart-legend' || command === 'chart-axis-cat' || command === 'chart-axis-val' || command === 'chart-labels' || command === 'chart-format-pane' || command.startsWith('chart-type-')) {
          const sheetName = workbook.getActiveSheet()?.getSheetName()
          const charts = currentModel.sheets.find(sheet => sheet.name === sheetName)?.charts ?? []
          if (charts.length !== 1) throw new Error(charts.length ? '当前工作表含多个图表，暂不支持选择要编辑的图表' : '请先打开包含图表的工作表')
          const chart = charts[0]!
          if (command === 'chart-format-pane' && !['column', 'bar', 'line', 'area'].includes(chart.kind))
            throw new Error('当前图表类型暂不支持分组和主网格线格式')
          if ((command === 'chart-axis-cat' || command === 'chart-axis-val') && !['column', 'bar', 'line', 'area'].includes(chart.kind))
            throw new Error('当前图表类型暂不支持坐标轴标题')
          if (!command.startsWith('chart-type-')) {
            const sheet = workbook.getActiveSheet()!
            if (sheetProtected(sheet.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
            chartDesignDialog ??= createChartDesignDialog(shell.editor, (edit, target) => {
              if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
              if (sheetProtected(target.sheetId)) throw new Error('工作表受保护，请先撤销保护')
              if (runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetId() !== target.sheetId ||
                !currentModel.sheets.find(item => item.name === target.sheetName)?.charts?.some(item => item.chartPath === target.chartPath))
                throw new Error('图表目标已变化，请重新选择后操作')
              void currentOperations().then(operations => {
                if (!editable() || runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheetId() !== target.sheetId)
                  throw new Error('图表目标已变化，请重新选择后操作')
                return loadOperations([...operations, { kind: 'applyChartEdits', edits: [edit] }])
              }).then(() => {
                markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表已更新，修改尚未保存。'
              }).catch(error => { feedback.textContent = (error as Error).message })
            })
            const property = command === 'chart-title' ? 'title' : command === 'chart-legend' ? 'legend' : command === 'chart-axis-cat' ? 'categoryTitle' : command === 'chart-axis-val' ? 'valueTitle' : command === 'chart-labels' ? 'labels' : 'format'
            const target = { chartPath: chart.chartPath, sheetId: sheet.getSheetId(), sheetName: sheet.getSheetName() }
            chartDesignDialog.open(property === 'title' ? { ...target, property, initialTitle: chart.title ?? '' } : { ...target, property })
            return
          }
          const edit = { chartPath: chart.chartPath, chartType: command.slice('chart-type-'.length) as 'column' | 'bar' | 'line' | 'area' | 'pie' | 'doughnut' }
          void loadOperations([...staged, { kind: 'applyChartEdits', edits: [edit] }]).then(() => {
            markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表已更新，修改尚未保存。'
          }).catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command.startsWith('insert-chart:')) {
          const sheet = workbook.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
          if (!sheet || !range) throw new Error('请先选择图表数据区域')
          const values = typeof range.getValues === 'function' ? range.getValues() as unknown as (readonly (string | number | boolean | null | undefined)[][]) : undefined
          if (!Array.isArray(values)) throw new Error('当前工作簿无法读取图表数据区域')
          const chartType = command.slice('insert-chart:'.length) as 'column' | 'bar' | 'line' | 'area' | 'pie' | 'scatter' | 'radar' | 'doughnut' | 'combo'
          const addition = chartAdditionFromGrid({ sheetName: sheet.getSheetName(), chartType, title: '',
            range: { startRow: range.getRow(), endRow: range.getRow() + range.getHeight() - 1,
              startColumn: range.getColumn(), endColumn: range.getColumn() + range.getWidth() - 1 }, values })
          void loadOperations([...staged, { kind: 'applyChartAdditions', additions: [addition] }]).then(() => {
            markDirty(); ribbon.refreshState?.(); feedback.textContent = '图表已插入，修改尚未保存。'
          }).catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'cf-open') {
          const sheet = workbook.getActiveSheet()
          if (sheetProtected(sheet?.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          void (async () => {
            await runtime.univer.__getInjector().get(LifecycleService).onStage(LifecycleStages.Rendered)
            if (!editable()) return
            await runtime.univerAPI.executeCommand('sheet.operation.open.conditional.formatting.panel', { value: 2 })
          })().catch(error => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'dv-open') {
          const sheet = workbook.getActiveSheet()
          const reason = currentModel.sheets.find(item => item.name === sheet?.getSheetName())?.dataValidations?.readOnlyReason
          if (reason) throw new Error(reason)
          if (sheetProtected(sheet?.getSheetId())) throw new Error('工作表受保护，请先撤销保护')
          // 官方面板组件在 Rendered 阶段注册；草稿恢复后 Ribbon 可能先于该阶段可点击。
          void (async () => {
            if (typeof runtime.univer.__getInjector === 'function') {
              await runtime.univer.__getInjector().get(LifecycleService).onStage(LifecycleStages.Rendered)
            }
            if (!editable()) return
            await runtime.univerAPI.executeCommand('data-validation.operation.open-validation-panel', {})
          })().catch(error => { feedback.textContent = (error as Error).message })
          return
        }
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
        if (command === 'autofit-row-height' || command === 'autofit-col-width') {
          const axis = command === 'autofit-row-height' ? 'row' : 'col'
          const sheet = workbook.getActiveSheet()
          const range = sheet?.getSelection()?.getActiveRange()
          if (!sheet || !range) throw new Error('请先选择单元格或区域')
          const ranges = autofitSpans(axis, range.getRange(), sheet.getMaxRows(), sheet.getMaxColumns())
          void runtime.univerAPI.executeCommand(AUTOFIT_COMMANDS[axis], { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), ranges }).then(applied => {
            if (!applied) { feedback.textContent = axis === 'row' ? '自动调整行高未应用' : '自动调整列宽未应用'; return }
            markDirty(); ribbon.refreshState?.()
            feedback.textContent = `${axis === 'row' ? '行高' : '列宽'}已按内容自动调整，修改尚未保存。`
          }, (error: unknown) => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'sheet-protect') {
          const sheetId = activeSheetId(), view = protectionView()
          if (!sheetId) throw new Error('请先选择工作表')
          if (view.sheet.reason) throw new Error(view.sheet.reason)
          const next = !view.sheet.protected
          if (next === (originalSheet(sheetId)?.protection?.protected ?? false)) sheetProtection.delete(sheetId)
          else sheetProtection.set(sheetId, next)
          markDirty(); ribbon.refreshState?.()
          pivotControlOverlay?.refreshState()
          feedback.textContent = next ? '工作表已设为受保护（无密码，Excel 默认权限），保存后写入文件；仅允许编辑区域内可输入值和公式。' : '工作表保护将在保存后移除。'
          return
        }
        if (command === 'workbook-protect') {
          const view = protectionView()
          if (view.workbook.reason) throw new Error(view.workbook.reason)
          const next = !view.workbook.locked
          structureLock = next === (currentModel.workbookProtection?.lockStructure ?? false) ? undefined : next
          markDirty(); ribbon.refreshState?.()
          feedback.textContent = next ? '工作簿结构已设为受保护（无密码），保存后写入文件；期间不能增删、重命名、移动或隐藏工作表。' : '工作簿结构保护将在保存后移除。'
          return
        }
        if (command === 'fill-down' || command === 'fill-right') {
          void runtime.univerAPI.executeCommand(command === 'fill-down' ? 'sheet.command.copy-down' : 'sheet.command.copy-right').then(applied => {
            feedback.textContent = applied ? `已${command === 'fill-down' ? '向下' : '向右'}填充，修改尚未保存。` : feedback.textContent || '填充未应用'
          }, (error: unknown) => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'fill-up' || command === 'fill-left') {
          // 固定源：Univer 只有 copy-down/right，向上/向左以选区末行/末列为源走 auto-fill COPY。
          const sheet = workbook.getActiveSheet(), active = workbook.getActiveRange()
          if (!sheet || !active) throw new Error('请先选择单元格或区域')
          const up = command === 'fill-up'
          const { startRow, startColumn } = active.getRange()
          let { endRow, endColumn } = active.getRange()
          if (up && startRow === endRow) { if (endRow + 1 >= sheet.getMaxRows()) throw new Error('下方没有可作为来源的行'); endRow += 1 }
          else if (!up && startColumn === endColumn) { if (endColumn + 1 >= sheet.getMaxColumns()) throw new Error('右侧没有可作为来源的列'); endColumn += 1 }
          void runtime.univerAPI.executeCommand('sheet.command.auto-fill', {
            unitId: workbook.getId(), subUnitId: sheet.getSheetId(),
            sourceRange: { startRow: up ? endRow : startRow, endRow, startColumn: up ? startColumn : endColumn, endColumn },
            targetRange: { startRow, endRow, startColumn, endColumn }, applyType: 'COPY',
          }).then(applied => {
            feedback.textContent = applied ? `已${up ? '向上' : '向左'}填充，修改尚未保存。` : feedback.textContent || '填充未应用'
          }, (error: unknown) => { feedback.textContent = (error as Error).message })
          return
        }
        if (command === 'remove-duplicates-open') {
          const sheet = workbook.getActiveSheet(), range = workbook.getActiveRange()?.getRange()
          if (!sheet || !range) throw new Error('请先选择单元格或区域')
          if (range.endRow <= range.startRow) throw new Error('请选择至少两行数据')
          dedupeTarget = { sheetId: sheet.getSheetId(), range: { startRow: range.startRow, endRow: range.endRow, startColumn: range.startColumn, endColumn: range.endColumn } }
          dedupeDialog.open()
          return
        }
        if (command === 'subtotal-open') {
          if (!subtotal) throw new Error('工作簿尚未就绪')
          subtotalDialog.open(subtotal.capture())
          return
        }
        if (command === 'filter-advanced') {
          if (!advancedFilter) throw new Error('工作簿尚未就绪')
          const sheet = workbook.getActiveSheet(), source = currentModel.sheets.find(item => item.name === sheet?.getSheetName())?.filter
          if (source?.readOnlyReason) throw new Error(source.readOnlyReason)
          if (source?.columns.some(column => column.dateGroups !== undefined)) throw new Error('筛选含日期分组条件，网格暂不能编辑回写')
          advancedFilterDialog.open(advancedFilter.capture())
          return
        }
        if (command === 'data-table-open') {
          const sheet = workbook.getActiveSheet(), range = workbook.getActiveRange()?.getRange()
          if (!sheet || !range || !dataTable) throw new Error('工作簿尚未就绪或未选择区域')
          dataTableDialog.open({ workbookId: workbook.getId(), sheetId: sheet.getSheetId(), range: `${formatAddress(range.startRow, range.startColumn)}:${formatAddress(range.endRow, range.endColumn)}` })
          return
        }
        if (command === 'goal-seek-open') {
          const sheet = workbook.getActiveSheet(), range = workbook.getActiveRange()?.getRange()
          if (!sheet || !range || !goalSeek) throw new Error('工作簿尚未就绪或未选择单元格')
          goalSeekDialog.open({ workbookId: workbook.getId(), sheetId: sheet.getSheetId(), setCell: formatAddress(range.startRow, range.startColumn) })
          return
        }
        if (command.startsWith('outline-')) { runOutlineCommand(command); return }
        if (command === 'consolidate-open') {
          const sheet = workbook.getActiveSheet(), range = workbook.getActiveRange()
          if (!sheet || !range) throw new Error('请先选择合并计算的目标单元格')
          consolidateCore = workbook.getWorkbook(); consolidateSheetCore = sheet.getSheet()
          const name = sheet.getSheetName(), prefix = /^[A-Za-z_][A-Za-z0-9_.]*$/.test(name) ? name : `'${name.replaceAll("'", "''")}'`
          consolidateDialog.open({ workbookId: workbook.getId(), sheetId: sheet.getSheetId(), row: range.getRow(), column: range.getColumn(),
            defaultReference: range.getHeight() === 1 && range.getWidth() === 1 ? '' : `${prefix}!${range.getA1Notation()}`, targetLabel: `${prefix}!${formatAddress(range.getRow(), range.getColumn())}` })
          return
        }
        if (command.startsWith('text-to-columns:')) {
          const sheet = workbook.getActiveSheet(), active = workbook.getActiveRange()
          if (!sheet || !active) throw new Error('请先选择单列区域')
          const reason = protectionBlockReason('sheet.command.set-range-values', sheetProtected(sheet.getSheetId()), structureLocked())
          if (reason) throw new Error(reason)
          const delimiter = ({ '1': '\t', '2': ',', '4': ';', '8': ' ' } as Record<string, string>)[command.split(':')[1]!]
          if (!delimiter) throw new Error('不支持的分隔符')
          const plan = planWorkbookTextToColumns(sheet, active, delimiter)
          const params = { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), value: plan.value }
          validateWorkbookReplacement({ id: 'sheet.command.set-range-values', params }, workbook.getSnapshot(), currentModel, staged, structural.length)
          const value = Object.fromEntries(Object.entries(plan.value).map(([row, cells]) => [row, Object.fromEntries(
            Object.entries(cells).map(([column, cell]) => [column, { ...cell, t: typeof cell.v === 'string' ? CellValueType.STRING : typeof cell.v === 'boolean' ? CellValueType.BOOLEAN : CellValueType.NUMBER }]),
          )]))
          if (!runtime.univerAPI.syncExecuteCommand('sheet.command.set-range-values', { ...params, value })) throw new Error('文本分列未应用')
          feedback.textContent = `文本分列已更新 ${plan.count} 个单元格，修改尚未保存。`
          return
        }
        if (command === 'flash-fill') {
          const sheet = workbook.getActiveSheet(), active = workbook.getActiveRange()
          if (!sheet || !active) throw new Error('请先选择单列目标区域')
          const reason = protectionBlockReason('sheet.command.set-range-values', sheetProtected(sheet.getSheetId()), structureLocked())
          if (reason) throw new Error(reason)
          const plan = planWorkbookFlashFill(sheet, active)
          const params = { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), value: plan.value }
          validateWorkbookReplacement({ id: 'sheet.command.set-range-values', params }, workbook.getSnapshot(), currentModel, staged, structural.length)
          // 显式文本类型，避免以 = 开头或数字形态的结果被转换成公式/数字。
          const value = Object.fromEntries(Object.entries(plan.value).map(([row, cells]) => [row, Object.fromEntries(
            Object.entries(cells).map(([column, cell]) => [column, { ...cell, t: CellValueType.STRING }]),
          )]))
          if (!runtime.univerAPI.syncExecuteCommand('sheet.command.set-range-values', { ...params, value })) throw new Error('快速填充未应用')
          feedback.textContent = `快速填充已更新 ${plan.count} 个空白单元格，修改尚未保存。`
          return
        }
        if (command === 'fill-series-open') {
          const active = workbook.getActiveRange()
          if (!active) throw new Error('请先选择单元格或区域')
          const numberFormat = formatState().numberFormat
          const dateFormatted = numberFormat.kind === 'value' && /[ymd]/i.test(String(numberFormat.value).replace(/"[^"]*"|\[[^\]]*\]/g, ''))
          fillSeriesDialog.open(fillSeriesDirection(active), fillSeriesDefaultType(dateFormatted))
          return
        }
        if (command === 'sort-custom-open') {
          const range = workbook.getActiveSheet()?.getSelection()?.getActiveRange()?.getRange() as SortRange | undefined
          if (!range) throw new Error('请先选择要排序的区域')
          sortDialog.open({ startRow: range.startRow, endRow: range.endRow, startColumn: range.startColumn, endColumn: range.endColumn })
          return
        }
        if (command === 'insert-cells' || command === 'delete-cells') {
          const sheet = workbook.getActiveSheet()
          const range = sheet?.getSelection()?.getActiveRange()?.getRange() as CellRange | undefined
          if (!sheet || !range) throw new Error('请先选择单元格或区域')
          const mode: CellsMode = command === 'insert-cells' ? 'insert' : 'delete'
          const decision = decideCellsAction({ range, rowCount: sheet.getMaxRows(), columnCount: sheet.getMaxColumns() })
          cellsRange = { startRow: range.startRow, endRow: range.endRow, startColumn: range.startColumn, endColumn: range.endColumn }
          if (decision.kind === 'direct') runCellsChoice(mode, decision.choice, cellsRange)
          else cellsDialog.open(mode)
          return
        }
        if (command === 'row-height-open' || command === 'col-width-open') {
          const target = captureAxisTarget(runtime.univerAPI.getActiveWorkbook() as never, command === 'row-height-open' ? 'row' : 'col')
          if (!target) throw new Error('请先选择单元格或区域')
          axisDialog.open(target)
          return
        }
        if (command === 'format-cells') {
          formatCellsTarget = captureNumberFormatTarget(formatWorkbook())
          if (!formatCellsTarget) throw new Error('请先选择单元格或区域')
          const state = formatState().numberFormat
          if (state.kind === 'unavailable') throw new Error(state.reason)
          formatCellsDialog.open()
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
        if (command.startsWith('indent-step:') && indentUnavailable()) throw new Error(indentUnavailable())
        const rowColumnCommands: Record<string, string> = {
          'insert-row-here': 'sheet.command.insert-row-by-range', 'delete-row-here': 'sheet.command.remove-row-by-range',
          'insert-col-here': 'sheet.command.insert-col-by-range', 'delete-col-here': 'sheet.command.remove-col-by-range',
        }
        if (rowColumnCommands[command]) preflightPivotRowColumns({ id: rowColumnCommands[command]!, params: {
          unitId: workbook.getId(), subUnitId: workbook.getActiveSheet().getSheetId(),
        } }, workbook)
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
      onAssistant: options.onAssistant ?? (options.nativeAI ? () => nativeAI?.open() : !options.native ? () => { shell.editor.querySelector<HTMLTextAreaElement>('.workbook-ai textarea')?.focus() } : undefined),
      rotation: () => selectedWorkbookRotation(runtime.univerAPI.getActiveWorkbook() as unknown as RibbonWorkbook | null),
      editable, unavailableReason: rotationUnavailable, indentReason: indentUnavailable, format: formatState,
      crossHighlight: () => ({ active: crossHighlightVisible, available: formulaBarAvailable() }),
      formulaBar: () => ({ visible: formulaBar.visible(), available: formulaBarAvailable() }),
      headings: () => ({ visible: runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheet().getConfig().rowHeader.hidden !== 1, available: formulaBarAvailable() && !headingsBusy }),
      rightToLeft: () => ({ active: runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSheet().getConfig().rightToLeft === 1, available: formulaBarAvailable() && !rtlBusy }),
      formatPainterActive: () => formatPainterActive(runtime),
      protection: protectionView,
      outlineSummary: () => { const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet(); const state = sheet && readWorkbookOutlineSummary(sheet); return { below: state?.summaryBelow ?? true, right: state?.summaryRight ?? true } },
      calculation: () => ({ formulaView: formulaSheets.has(activeSheetId() ?? ''), manual: calculation?.manual() ?? false }),
      formatPainterReady: () => formatPainterReady(runtime),
      hasSelection: () => !!runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()?.getSelection()?.getActiveRange(),
      zoomSelectionAvailable: zoomAvailable,
      captureTarget: () => captureNumberFormatTarget(formatWorkbook()),
      errorChecking: () => ({ ...errorChecking.state(), available: formulaBarAvailable() && !!runtime.univerAPI.getActiveWorkbook()?.getActiveSheet() }),
      watchWindow: () => ({ ...watchWindow.state(), available: formulaBarAvailable() }),
      queries: () => ({ available: formulaBarAvailable() }),
      formulaTrace: () => ({ ...formulaTrace.state(), available: formulaBarAvailable() }),
      pageBreakPreview: () => ({ ...pageBreakPreview.state(), available: !loading && !disposed }),
      theme: () => themeSource && !loading && !disposed ? {
        colorName: themeSource.colorName, fontName: themeSource.fontName, reason: themeSource.reason,
        fontsReason: themeSource.fontsAvailable ? undefined : '主题没有可改写的字体方案',
      } : undefined,
      pageSetup: () => {
        const context = activePageSetupContext()
        return context ? mergedPageSetup(context.sheet.getSheetName(), pageSetupJournal.get(context.sheet.getSheetId()) ?? {}) : undefined
      },
      definedNames: () => {
        const active = activeSheetId(), sheets = definedNameSheets()
        return [...new Set(definedNameRows().flatMap(row => {
          if (!row.scopeSheetId || row.scopeSheetId === active) return [row.name]
          const sheet = sheets.find(item => item.id === row.scopeSheetId)
          return sheet ? [`'${sheet.name.replaceAll("'", "''")}'!${row.name}`] : []
        }))]
      },
      table: () => {
        const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
        const selection = sheet?.getSelection()?.getActiveRange()
        if (!selection) return
        const row = selection.getRow(), column = selection.getColumn()
        const table = workbook?.getTableList?.().find(table => table.subUnitId === sheet!.getSheetId() &&
          row >= table.range.startRow && row <= table.range.endRow && column >= table.range.startColumn && column <= table.range.endColumn)
        if (!table) return
        const reason = sheetProtected(table.subUnitId) ? '工作表受保护，请先撤销保护'
          : currentModel.sheets.find(item => item.name === sheet!.getSheetName())?.tablesReadOnlyReason
        return { id: table.id, name: table.name,
          header: table.showHeader,
          filterButton: table.meta?.nativeFilterButton !== false,
          totals: (table.meta?.nativeTotalsRowCount ?? 0) > 0,
          style: table.meta?.nativeTableStyleName ?? table.meta?.nativeTableStyle?.name ?? '',
          styleOptions: table.meta?.nativeTableStyle,
          range: `${formatAddress(table.range.startRow, table.range.startColumn)}:${formatAddress(table.range.endRow, table.range.endColumn)}`,
          ...(reason ? { reason } : {}) }
      },
      renameTable: (id, name) => {
        if (!editable() || !tableDesign) return
        try {
          if (tableDesign.rename(id, name)) { markDirty(); feedback.textContent = '表格名称已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      resizeTable: (tableId, range) => {
        if (editable() && tableResize) tableResizeDialog.open({ tableId, range })
      },
      setTableTotals: (id, enabled) => {
        if (!editable() || !tableTotals) return
        try {
          if (tableTotals.setTotals(id, enabled)) { markDirty(); feedback.textContent = '汇总行已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      setTableHeaderRow: (id, enabled) => {
        if (!editable() || !tableHeaderRow) return
        if (!enabled) {
          const controller = tableHeaderRow
          void withWorkbookLocked(shell.editor, async () => {
            await persistence
            if (disposed || controller !== tableHeaderRow) throw new Error('表格状态已变化，请重新选择')
            const workbook = runtime.univerAPI.getActiveWorkbook(), table = workbook?.getTableList?.().find(table => table.id === id)
            const sheet = table && workbook?.getSheetBySheetId(table.subUnitId)
            if (!table || !sheet) throw new Error('当前表格不存在，请重新选择')
            const operations = await currentOperations()
            // 清空字段名单元格前验证透视依赖，拒绝时保留草稿和撤销历史。
            await applyWorkbookOperations(original, [...operations, { kind: 'applyTableEdits', edits: [{ worksheetSheetName: sheet.getSheetName(), tableName: table.name, headerRow: false }] }])
            if (disposed || controller !== tableHeaderRow) throw new Error('表格状态已变化，请重新选择')
            if (controller.setHeaderRow(id, enabled)) { markDirty(); feedback.textContent = '标题行已更新，修改尚未保存。' }
          }).catch(error => { feedback.textContent = (error as Error).message }).finally(() => { ribbon.refreshState?.() })
          return
        }
        try {
          if (tableHeaderRow.setHeaderRow(id, enabled)) { markDirty(); feedback.textContent = '标题行已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      setTableFilterButton: (id, enabled) => {
        if (!editable() || !tableFilterButton) return
        try {
          if (tableFilterButton.setFilterButton(id, enabled)) { markDirty(); feedback.textContent = '筛选按钮已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      setTableStyle: (id, style) => {
        if (!editable() || !tableStyleEdit) return
        try {
          if (tableStyleEdit.setStyle(id, style)) { markDirty(); feedback.textContent = '表格样式已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      setTableStyleOption: (id, option, enabled) => {
        if (!editable() || !tableStyleEdit) return
        try {
          if (tableStyleEdit.setOption(id, option, enabled)) { markDirty(); feedback.textContent = '表格样式选项已更新，修改尚未保存。' }
        } catch (error) { feedback.textContent = (error as Error).message }
        ribbon.refreshState?.()
      },
      convertTable: id => {
        if (!editable() || !tableConvert) return
        if (!window.confirm('转换后将移除表格、条纹和筛选，保留单元格内容及显式格式。结构化引用可能失效。是否继续？')) return
        const controller = tableConvert
        void withWorkbookLocked(shell.editor, async () => {
          await persistence
          if (disposed || controller !== tableConvert) throw new Error('表格状态已变化，请重新选择')
          const workbook = runtime.univerAPI.getActiveWorkbook(), table = workbook?.getTableList?.().find(table => table.id === id)
          const sheet = table && workbook?.getSheetBySheetId(table.subUnitId)
          if (!table || !sheet) throw new Error('当前表格不存在，请重新选择')
          const operations = await currentOperations()
          // 先通过真实保存引擎验证依赖，拒绝后保留网格、表格样式及撤销历史。
          await applyWorkbookOperations(original, [...operations, { kind: 'applyTableEdits', edits: [{ worksheetSheetName: sheet.getSheetName(), tableName: table.name, remove: true }] }])
          if (disposed || controller !== tableConvert) throw new Error('表格状态已变化，请重新选择')
          if (controller.convert(id)) { markDirty(); feedback.textContent = '已转换为区域，修改尚未保存。结构化引用可能失效，可撤销恢复表格。' }
        }).catch(error => { feedback.textContent = (error as Error).message }).finally(() => { ribbon.refreshState?.() })
      },
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
  let validationNames: ReturnType<typeof installDataValidationNames> | undefined
  let definedNameScopes: ReturnType<typeof installDefinedNameScopes> | undefined
  let validationStructure: ReturnType<typeof installDataValidationStructure> | undefined
  let outline: ReturnType<typeof installWorkbookOutline> | undefined
  let tableHeaders: ReturnType<typeof installTableHeaders> | undefined
  let tableDesign: ReturnType<typeof installTableDesign> | undefined
  let tableStyleRendering: ReturnType<typeof installNativeTableStyleRendering> | undefined
  let tableResize: ReturnType<typeof installTableResize> | undefined
  let tableTotals: ReturnType<typeof installTableTotals> | undefined
  let tableHeaderRow: ReturnType<typeof installTableHeaderRow> | undefined
  let tableFilterButton: ReturnType<typeof installTableFilterButton> | undefined
  let tableConvert: ReturnType<typeof installTableConvert> | undefined
  let tableCreate: ReturnType<typeof installTableCreate> | undefined
  let tableStyleEdit: ReturnType<typeof installTableStyleEdit> | undefined
  let tableFormulaReferences: ReturnType<typeof installTableFormulaReferences> | undefined
  let replacing = false
  let pendingShiftUndo: { id: string; element: unknown } | undefined
  runtime.univerAPI.addEvent(runtime.univerAPI.Event.BeforeCommandExecute, command => {
    if (!loading && (CF_EDIT_COMMAND_IDS.has(command.id) || CF_MUTATION_IDS.has(command.id))) {
      const workbook = runtime.univerAPI.getActiveWorkbook()
      const targetId = (command.params as { subUnitId?: string } | undefined)?.subUnitId
      const sheet = targetId ? workbook?.getSheetBySheetId(targetId) : workbook?.getActiveSheet()
      const reason = !editable() ? '当前工作簿不可编辑或正在保存'
        : sheetProtected(sheet?.getSheetId()) ? '工作表受保护，请先撤销保护' : undefined
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
      try {
        const structuralFollower = CF_MUTATION_IDS.has(command.id) && validationStructure?.ownsMutation((command.params ?? {}) as object)
        const snapshot = workbook!.getSnapshot() as unknown as GridSnapshot
        const plan = planGridSheets(currentModel.sheets.map(item => item.name), snapshot)
        const changed = structural.length || plan.renames.length || plan.additions.length || plan.removals.length
          || plan.order.some((name, index) => name !== currentModel.sheets[index]?.name)
        let sourceModel = currentModel
        if (!structuralFollower && changed) {
          if (cfBaseline?.source !== currentModel || cfBaseline.signature !== cfStructureSignature(snapshot))
            throw new Error('结构修改正在同步，请稍后重试条件格式编辑')
          sourceModel = cfBaseline.model
        }
        validateConditionalFormattingEdit(command.id, (command.params ?? {}) as Record<string, any>,
          sheet?.getConditionalFormattingRules() ?? [], structuralFollower ? undefined
            : sourceModel.sheets.find(item => item.name === sheet?.getSheetName())?.conditionalFormatting)
      } catch (error) { command.cancel = true; feedback.textContent = (error as Error).message; return }
    }
    if (!loading) {
      const reason = tableHeaderProtectionReason(runtime.univerAPI.getActiveWorkbook(), command, id => sheetProtected(id), pivotTableColumnReason)
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
    }
    if (!loading && /^sheet\.(?:command|mutation)\.(?:add-table|delete-table|set-sheet-table|set-table-config|set-table-filter|add-table-theme|remove-table-theme|table-)/.test(command.id) &&
        !validationStructure?.ownsMutation((command.params ?? {}) as object) && !tableDesign?.ownsMutation((command.params ?? {}) as object) && !tableResize?.ownsMutation((command.params ?? {}) as object) && !tableTotals?.ownsMutation((command.params ?? {}) as object) && !tableFilterButton?.ownsMutation((command.params ?? {}) as object) && !tableHeaderRow?.ownsMutation((command.params ?? {}) as object) && !tableStyleEdit?.ownsMutation((command.params ?? {}) as object) && !tableConvert?.ownsMutation((command.params ?? {}) as object) && !tableCreate?.ownsMutation((command.params ?? {}) as object)) {
      command.cancel = true
      feedback.textContent = '此表格操作尚未接入完整文件回写；更名请使用“表格设计”页签。'
      return
    }
    if (!loading && (DV_EDIT_COMMAND.test(command.id) || DV_MUTATION.test(command.id))) {
      const workbook = runtime.univerAPI.getActiveWorkbook()
      const targetId = (command.params as { subUnitId?: string } | undefined)?.subUnitId
      const sheet = targetId ? workbook?.getSheetBySheetId(targetId) : workbook?.getActiveSheet()
      const structuralFollower = validationStructure?.ownsMutation((command.params ?? {}) as object) || tableHeaders?.ownsMutation((command.params ?? {}) as object) || tableDesign?.ownsMutation((command.params ?? {}) as object) || tableResize?.ownsMutation((command.params ?? {}) as object) || tableTotals?.ownsMutation((command.params ?? {}) as object) || tableFilterButton?.ownsMutation((command.params ?? {}) as object) || tableHeaderRow?.ownsMutation((command.params ?? {}) as object) || tableStyleEdit?.ownsMutation((command.params ?? {}) as object) || tableConvert?.ownsMutation((command.params ?? {}) as object) || tableCreate?.ownsMutation((command.params ?? {}) as object)
      const reason = !editable() ? '当前工作簿不可编辑或正在保存'
        : structuralFollower ? undefined
        : sheetProtected(sheet?.getSheetId()) ? '工作表受保护，请先撤销保护'
        : currentModel.sheets.find(item => item.name === sheet?.getSheetName())?.dataValidations?.readOnlyReason
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
      if (structuralFollower) return
      try {
        validateDataValidationEdit(command.id, (command.params ?? {}) as Record<string, any>,
          sheet?.getDataValidations?.().map(item => item.rule) ?? [], staged, structural.length)
      } catch (error) { command.cancel = true; feedback.textContent = (error as Error).message; return }
    }
    if (omitCalculatedNumberFormats(command, runtime.univerAPI.getActiveWorkbook()?.getSnapshot())) return
    if (!loading) {
      const reason = noteStructureReason(currentModel, noteWorkbook(), command)
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
    }
    if (!loading) {
      const target = (command.params as { subUnitId?: string } | undefined)?.subUnitId ?? activeSheetId()
      const targetSheet = target ? runtime.univerAPI.getActiveWorkbook()?.getSheetBySheetId(target) : undefined
      const selection = targetSheet?.getSelection()
      const fallback = selection?.getActiveRangeList?.().length === 1 ? selection.getActiveRange()?.getRange() : undefined
      const ranges = editableRanges.get(originalSheet(target)?.name ?? '') ?? []
      const context = command.id === 'sheet.command.set-range-values' ? protectedValueCommandContext(command.params, fallback, ranges) : undefined
      if (context && sheetProtected(target)) {
        // 表头值同时改写表格列元数据；允许编辑区域仅放行值/公式，必须在原生写入前拒绝。
        const writes = context.writtenRanges ?? [context.range]
        const header = runtime.univerAPI.getActiveWorkbook()?.getTableList?.().some(table => table.subUnitId === target && table.showHeader && writes.some(range =>
          range.startRow <= table.range.startRow && range.endRow >= table.range.startRow && range.startColumn <= table.range.endColumn && range.endColumn >= table.range.startColumn))
        if (header) { command.cancel = true; feedback.textContent = '工作表受保护，表头更名涉及表格定义，请先撤销工作表保护'; return }
      }
      const reason = protectionBlockReason(command.id, sheetProtected(target), structureLocked(), context)
      if (reason) { command.cancel = true; feedback.textContent = reason; return }
      // 官方键盘附带字体patch；保护区域只授权值/公式。缺少s时原生merge保留原始格式。
      if (context && sheetProtected(target)) (command.params as { value: unknown }).value = context.safeValue
    }
    if (!loading && CELL_SHIFT_COMMANDS[command.id]) {
      if (!editable()) { command.cancel = true; feedback.textContent = '当前工作簿不可编辑或正在保存'; return }
      suppressStructural = true; queueMicrotask(() => { suppressStructural = false })
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
      const filter = currentModel?.sheets.find(item => item.name === sheetName)?.filter
      // dateGroups 同样无法由网格承载（未灌入网格），拒绝网格内新建/改写以免覆盖。
      const reason = filter?.readOnlyReason ?? (filter?.columns.some(column => column.dateGroups !== undefined)
        ? '筛选含日期分组条件，网格暂不能编辑回写（仅服务端路径可写 dateGroups）' : undefined)
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
  // Facade 的 BeforeCommandExecute 不派发 undo/redo；直接挂命令服务，在栈顶元素出栈前认领单元格移位。
  const historyListener = typeof runtime.univer.__getInjector !== 'function' ? undefined : runtime.univer.__getInjector().get<ICommandService>(ICommandService).beforeCommandExecuted(command => {
    if (loading || (command.id !== 'univer.command.undo' && command.id !== 'univer.command.redo')) return
    if (calculationBusy || subtotalMutating || advancedFilterMutating) {
      // 快捷键直接走命令服务，不能仅靠Ribbon/网格inert阻止破坏运行中的历史批次。
      const service = runtime.univer.__getInjector().get<ICommandService>(ICommandService)
      const stack = (service as unknown as { _commandExecutionStack?: unknown[] })._commandExecutionStack
      const index = stack?.indexOf(command) ?? -1
      if (index >= 0) stack?.splice(index, 1)
      throw new CustomCommandExecutionError('模拟分析正在计算，请稍候再撤销或恢复')
    }
    const top = command.id === 'univer.command.undo' ? undoStack()?.pitchTopUndoElement() : undoStack()?.pitchTopRedoElement()
    const owned = command.id === 'univer.command.undo'
      ? structural.some(item => 'cellShift' in item && item.element === top) : undone.some(item => item.element === top)
    if (top && owned) {
      pendingShiftUndo = { id: command.id, element: top }
      suppressStructural = true; queueMicrotask(() => { suppressStructural = false })
    }
  })
  runtime.univerAPI.onCommandExecuted((command, options) => {
    formulaTrace.syncTarget()
    if (command.id.startsWith('sheet.mutation.') || command.id === 'univer.command.undo' || command.id === 'univer.command.redo') {
      if (formulaTrace.invalidate() && !loading) feedback.textContent = '工作表内容或显示已变化，追踪箭头已清除，请重新追踪。'
    }
    if (!loading && (command.id.startsWith('sheet.mutation.') || command.id.includes('worksheet-activ') || command.id === 'univer.command.undo' || command.id === 'univer.command.redo')) refreshPageBreakPreview()
    if (CF_MUTATION_IDS.has(command.id)) {
      if (!loading && !saving && !saved) markDirty()
      return
    }
    if (command.id === 'sheet.mutation.set-worksheet-right-to-left' && editable()) markDirty()
    if (!loading && !saving && !saved && DV_MUTATION.test(command.id)) markDirty()
    if (command.id === 'ui.command.replace-current-match' || command.id === 'ui.command.replace-all-matches') replacing = false
    if (!loading && command.id.includes('worksheet-activ')) calculation?.syncFormulaView(formulaSheets.has(activeSheetId() ?? ''))
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
    if (!loading && !saving && !saved && CELL_SHIFT_COMMANDS[command.id]) {
      const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
      const range = (command.params as { range?: CellRange } | undefined)?.range ?? sheet?.getSelection()?.getActiveRange()?.getRange() as CellRange | undefined
      if (sheet && range) {
        structural.push({ sheetId: sheet.getSheetId(), cellShift: { range: cellShiftRange(range), shift: CELL_SHIFT_COMMANDS[command.id]! }, element: undoStack()?.pitchTopUndoElement() })
        undone.length = 0
        markDirty()
        // 引擎按同一规则预演；不支持移位的来源特性（表格、验证、共享公式等）立即撤销并说明原因。
        const entry = structural[structural.length - 1]
        void currentOperations().catch((error: unknown) => {
          const message = (error as Error).message ?? ''
          if (!message.includes('插入/删除单元格已拒绝')) return
          const element = (entry as CellShiftEntry).element
          if (element && undoStack()?.pitchTopUndoElement() === element) void runtime.univerAPI.undo()
          feedback.textContent = message
        })
      }
      return
    }
    if (pendingShiftUndo && command.id === pendingShiftUndo.id) {
      const element = pendingShiftUndo.element
      pendingShiftUndo = undefined
      if (command.id === 'univer.command.undo') {
        const index = structural.findIndex(item => 'cellShift' in item && item.element === element)
        if (index >= 0) undone.push(structural.splice(index, 1)[0] as CellShiftEntry)
      } else {
        const index = undone.findIndex(item => item.element === element)
        if (index >= 0) structural.push(undone.splice(index, 1)[0]!)
      }
      if (!saving && !saved) markDirty()
      return
    }
    if (!loading && !saving && !saved && command.id.startsWith('sheet.mutation.')) {
      const mutation = suppressStructural ? undefined : structuralMutation(command.id, command.params)
      if (mutation) {
        const trigger = (command.params as { trigger?: string }).trigger
        const inverse = mutation.op.kind.startsWith('insert-')
          ? mutation.op.kind.replace('insert-', 'remove-') : mutation.op.kind.replace('remove-', 'insert-')
        const reverted = trigger === 'univer.command.undo' ? structural.findLastIndex(item => 'op' in item &&
          item.sheetId === mutation.sheetId && item.op.kind === inverse &&
          item.op.index === mutation.op.index && item.op.count === mutation.op.count) : -1
        // 仅真实 Univer Undo 撤回对应结构日志；手动删后插仍须保留破坏性引用语义。
        if (reverted >= 0) structural.splice(reverted, 1)
        else structural.push(mutation)
      }
      markDirty()
    }
  })
  // 格式刷状态镜像到功能区（aria-pressed），并绑定 Esc 取消；无 painter 服务的替身跳过。
  const outlineShortcuts = installOutlineShortcuts(shell.editor, editable, () => runtime.univerAPI.getActiveWorkbook()?.isCellEditing?.() === true, command => {
    try { runOutlineCommand(command) } catch (error) { feedback.textContent = (error as Error).message }
  })
  const functionShortcuts = installFunctionShortcuts(shell.editor, editable, () => {
    void insertFunction.open().catch(error => { if (!disposed) feedback.textContent = (error as Error).message })
  })
  let painterListener: { dispose(): void } | undefined
  try { painterListener = installFormatPainter(runtime, () => ribbon.refreshState?.()) } catch { painterListener = undefined }
  const currentOperations = async (): Promise<WorkbookOperation[]> => {
    const readback = readBack(runtime)
    const workbook = runtime.univerAPI.getActiveWorkbook()
    const snapshot = workbook!.getSnapshot() as unknown as GridSnapshot
    const sourceAtCapture = currentModel, cfSignature = cfStructureSignature(snapshot)
    const plan = planGridSheets(currentModel.sheets.map(sheet => sheet.name), snapshot)
    const ops: WorkbookOperation[] = [...staged]
    const protection = planProtection(currentModel, sheetProtection, structureLock, id => snapshot.sheets[id]?.name, editableRanges)
    ops.push(...protection.leading)
    const editsFrom = ops.length
    const sheetChanged = plan.renames.length || plan.additions.length || plan.removals.length ||
      plan.order.some((name, index) => name !== currentModel.sheets[index]?.name)
    if (sheetChanged && !plan.removals.length) ops.push({ kind: 'applySheetEdits', plan })
    if (plan.removals.length && (plan.renames.length || plan.additions.length
      || plan.order.some((name, index) => name !== currentModel.sheets.filter(sheet => !plan.removals.includes(sheet.name))[index]?.name)))
      ops.push({ kind: 'applySheetEdits', plan: { ...plan, removals: [], order: [...plan.order, ...plan.removals] } })
    for (const mutation of structural) {
      const name = snapshot.sheets[mutation.sheetId]?.name
      if (name) ops.push('cellShift' in mutation
        ? { kind: 'applyCellShift', sheetName: name, ...mutation.cellShift }
        : { kind: 'applyRowColumnOps', sheetName: name, ops: [mutation.op] })
    }
    if (plan.removals.length) {
      // 先写回存续表当前规则，解除用户已清除的依赖，再让文件引擎验证删除。
      const beforeRemoval = ops.length > editsFrom ? await readModelWithStructureSource(await applyWorkbookOperations(original, ops)) : currentModel
      ops.push(...workbookConditionalFormattingOperations(beforeRemoval, workbook as unknown as ConditionalFormattingWorkbook))
      ops.push(...workbookDataValidationOperations(beforeRemoval, workbook as unknown as ValidationWorkbook))
      const formulaEdits = tableCreateCellEdits(diffToEdits(beforeRemoval, readback), snapshot).filter(edit => {
        const before = beforeRemoval.sheets.find(sheet => sheet.name === edit.sheetName)?.cells[formatAddress(edit.row, edit.column)]
        return edit.writeValue && before?.formula !== undefined && before.formula !== edit.cell.formula
      })
      if (formulaEdits.length) ops.push({ kind: 'applyCellEdits', edits: formulaEdits })
      const liveNames = liveDefinedNames(workbook as unknown as DefinedNameWorkbook)
      const namesOperation = liveNames ? definedNamesPlanOperation(projectedNameBaseline(beforeRemoval), liveNames, definedNameSheets()) : undefined
      if (namesOperation) ops.push(namesOperation)
      ops.push({ kind: 'applySheetEdits', plan: { renames: [], additions: [], removals: plan.removals, order: plan.order } })
    }
    const baseline = sheetChanged || structural.length
      ? await readModelWithStructureSource(await applyWorkbookOperations(original, ops)) : currentModel
    if (sourceAtCapture === currentModel && cfSignature === cfStructureSignature(workbook!.getSnapshot() as unknown as GridSnapshot))
      cfBaseline = { source: currentModel, model: baseline, signature: cfSignature }
    // 公式缓存由 Univer 自动重算，不属于编辑；恢复后不得因此追加重复操作并更换重试身份。
    for (const sheet of readback.sheets) {
      const before = baseline.sheets.find(item => item.name === sheet.name)
      for (const [address, cell] of Object.entries(sheet.cells)) {
        const originalCell = before?.cells[address]
        if (cell.formula && cell.formula === originalCell?.formula) cell.value = originalCell.value
      }
    }
    const edits = tableCreateCellEdits(diffToEdits(baseline, readback), snapshot)
    const geometry = geometryChanges(baseline, readback)
    if (edits.length) ops.push({ kind: 'applyCellEdits', edits })
    ops.push(...workbookTableOperations(baseline, workbook))
    ops.push(...workbookOutlineOperations(baseline, workbook))
    for (const change of gridMergeChanges(baseline, readback)) ops.push({ kind: 'applySheetMerges', ...change })
    for (const change of geometry.columns) ops.push({ kind: 'applyColumnWidths', sheetName: change.sheet, entries: [{ index: change.index, widthChars: change.widthChars }] })
    for (const change of geometry.rows) ops.push({ kind: 'applyRowHeights', sheetName: change.sheet, entries: [{ index: change.index, heightPoints: change.heightPoints }] })
    ops.push(...workbookNoteOperations(baseline, noteWorkbook()))
    ops.push(...workbookFilterOperations(baseline, filterWorkbook()))
    ops.push(...workbookDataValidationOperations(baseline, workbook as unknown as ValidationWorkbook))
    ops.push(...workbookConditionalFormattingOperations(baseline, workbook as unknown as ConditionalFormattingWorkbook))
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
    const headingSetups: { sheetName: string; showHeadings: boolean }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const visible = sheet.getSheet().getConfig().rowHeader.hidden !== 1
      if (visible !== (baseline.sheets.find(item => item.name === sheet.getSheetName())?.showHeadings ?? true))
        headingSetups.push({ sheetName: sheet.getSheetName(), showHeadings: visible })
    }
    const rtlSetups: { sheetName: string; rightToLeft: boolean }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const rightToLeft = sheet.getSheet().getConfig().rightToLeft === 1
      if (rightToLeft !== (baseline.sheets.find(item => item.name === sheet.getSheetName())?.rightToLeft ?? false))
        rtlSetups.push({ sheetName: sheet.getSheetName(), rightToLeft })
    }
    const zoomSetups: { sheetName: string; zoomScale: number }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      const liveZoom = typeof sheet.getZoom === 'function' ? Math.round((sheet.getZoom() ?? 1) * 100) : 100
      const baselineZoom = baseline.sheets.find(item => item.name === sheet.getSheetName())?.zoomScale ?? 100
      if (liveZoom !== baselineZoom) zoomSetups.push({ sheetName: sheet.getSheetName(), zoomScale: liveZoom })
    }
    // 公式视图：同一 applyPageSetups 协议（showFormulas），与 baseline 对比。
    const formulaViewSetups: { sheetName: string; showFormulas: boolean }[] = []
    for (const sheet of liveWorkbook?.getSheets() ?? []) {
      if (typeof sheet.getSheetId !== 'function') continue
      const live = formulaSheets.has(sheet.getSheetId())
      if (live !== (baseline.sheets.find(item => item.name === sheet.getSheetName())?.showFormulas ?? false)) formulaViewSetups.push({ sheetName: sheet.getSheetName(), showFormulas: live })
    }
    const viewSetups: Array<{ sheetName: string } & Record<string, unknown>> = [...freezeSetups, ...gridlineSetups, ...headingSetups, ...rtlSetups, ...zoomSetups, ...formulaViewSetups]
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
      for (const key of ['header', 'footer'] as const) if (patch[key] !== undefined) entry[key] = patch[key]
      for (const key of ['rowBreaks', 'colBreaks'] as const) {
        const value = patch[key]
        if (value === undefined) continue
        if (JSON.stringify(value) === JSON.stringify(before?.[key] ?? [])) continue
        entry[key] = value
      }
      if (Object.keys(entry).length > 1) viewSetups.push(entry as { sheetName: string })
    }
    if (viewSetups.length) ops.push({ kind: 'applyPageSetups', setups: viewSetups })
    // 定义名称：按实时scope身份比较；打印区域等_xlnm名称仍由page-setup维护。
    if (liveWorkbook) {
      const liveNames = liveDefinedNames(liveWorkbook as unknown as DefinedNameWorkbook)
      // liveNames === undefined：facade 读不到 defined names，跳过差分。
      const namesOperation = liveNames
        ? definedNamesPlanOperation(projectedNameBaseline(baseline), liveNames, definedNameSheets()) : undefined
      if (namesOperation) ops.push(namesOperation)
    }
    ops.push(...(sparklines?.operations() ?? []))
    // 保护：本次前后都受保护的工作表/工作簿结构不得被本次修改触及（草稿重放同样受限）。
    assertProtectionRespected(ops.slice(editsFrom), protection,
      (currentModel.workbookProtection?.lockStructure ?? false) && structureLock !== false)
    ops.push(...protection.trailing)
    return ops
  }
  const loadOperations = async (ops: WorkbookOperation[], controlDrafts?: import('./workbook-pivot-controls').PivotControlDrafts) => {
    const controlGeneration = ++pivotControlGeneration
    pivotControlOverlay?.dispose(); pivotControlOverlay = undefined
    goToReveal.cancel()
    formulaTrace.clear()
    watchWindow.reset()
    errorChecking.reset()
    loading = true
    refreshPageBreakPreview()
    pageSetupJournal.clear()
    const bytes = ops.length ? await applyWorkbookOperations(original, ops) : original
    currentModel = await readModelWithStructureSource(bytes)
    themeSource = await readWorkbookThemeSource(bytes)
    editableRanges = await readWorkbookEditableRanges(bytes)
    // 批注、筛选、视图状态随快照资源/工作表配置一并灌入，保存差分才有真实基线。
    const data = withWorkbookConditionalFormatting(withWorkbookDataValidations(withWorkbookTables(withWorkbookView(withWorkbookFilters(withWorkbookNotes(buildWorkbookData(currentModel, 'report-workbook', '报告工作簿'), currentModel), currentModel), currentModel), currentModel), currentModel), currentModel)
    // 完整官方resource负责CF导入；停用旧窄投影，避免重复规则和无关cell mutation。
    for (const sheet of Object.values(data.sheets)) delete sheet.cfRules
    setSparklineWorkbookResolver(runtime.univerAPI.getActiveWorkbook()?.getId() ?? '', undefined)
    // 官方选区订阅读取当前工作簿；先解绑，避免旧实例销毁时收到空工作簿通知。
    selectionListener?.dispose()
    selectionListener = undefined
    loadWorkbookData(runtime, data)
    const sparklineBook = runtime.univerAPI.getActiveWorkbook()
    if (sparklineBook) setSparklineWorkbookResolver(sparklineBook.getId(), name => {
      const live = runtime.univerAPI.getActiveWorkbook()
      if (live?.getId() !== sparklineBook.getId()) return undefined
      const index = currentModel.sheets.findIndex(sheet => sheet.name.toLowerCase() === name.toLowerCase())
      const source = (index >= 0 ? live.getSheetBySheetId(`sheet-${index}`) : live.getSheets().find(sheet => sheet.getSheetName().toLowerCase() === name.toLowerCase()))?.getSheet()
      return source ? { getCell: (row, column) => source.getCell(row, column) ?? undefined } : undefined
    })
    if (!sparklines && typeof runtime.univer.__getInjector === 'function') sparklines = installWorkbookSparklines(runtime, {
      readonly: () => !editable(), protectedSheet: sheetProtected,
      existing: id => originalSheet(id)?.sparklines ?? [], changed: markDirty,
      sourceSheetId: name => {
        const index = currentModel.sheets.findIndex(sheet => sheet.name.toLowerCase() === name.toLowerCase())
        return index >= 0 ? `sheet-${index}` : runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName().toLowerCase() === name.toLowerCase())?.getSheetId()
      },
      refresh: (id, specs) => {
        const book = runtime.univerAPI.getActiveWorkbook()
        if (!book) return
        setSparklines(book.getId(), id, specs)
        const injector = runtime.univer.__getInjector()
        if (injector.has(IRenderManagerService)) injector.get(IRenderManagerService).getRenderById(book.getId())?.scene.makeDirty(true)
      },
    })
    sparklines?.reset()
    const loadedNames = liveDefinedNames(definedNameWorkbook())
    unprojectedNames = (data.definedNames ?? []).filter(expected => !loadedNames?.some(actual =>
      actual.name.toLowerCase() === expected.name.toLowerCase() && actual.scopeSheetId === expected.scopeSheetId
      && actual.refersTo === expected.refersTo.replace(/^=/, '').trim()))
      .map(({ name, scopeSheetId }) => ({ name, ...(scopeSheetId ? { scopeSheetId } : {}) }))
    if (!functionOverrides) {
      functionOverrides = installWorkbookFunctionOverrides(runtime, () => sourcePath)
    }
    if (!validationStructure && typeof runtime.univer.__getInjector === 'function') validationStructure = installDataValidationStructure(runtime, mutation => {
      const sheet = runtime.univerAPI.getActiveWorkbook()?.getSheetBySheetId(mutation.params.subUnitId)
      try {
        validateDataValidationEdit(mutation.id, mutation.params, sheet?.getDataValidations?.().map(item => item.rule) ?? [], staged, structural.length + 1)
      } catch (error) { feedback.textContent = (error as Error).message; throw error }
    }, (command, workbook) => {
      try {
        const snapshot = workbook.getSnapshot() as GridSnapshot
        const plan = planGridSheets(currentModel.sheets.map(sheet => sheet.name), snapshot)
        const changed = structural.length || plan.renames.length || plan.additions.length || plan.removals.length
          || plan.order.some((name, index) => name !== currentModel.sheets[index]?.name)
        let sourceModel = currentModel
        if (changed) {
          if (cfBaseline?.source !== currentModel || cfBaseline.signature !== cfStructureSignature(snapshot))
            throw new Error('结构修改正在同步，请稍后重试删除')
          sourceModel = cfBaseline.model
        }
        assertConditionalFormattingSheetRemoval(workbook, command.params?.subUnitId, sheetId => {
          const name = snapshot.sheets[sheetId]?.name
          const source = sourceModel.sheets.find(sheet => sheet.name === name)?.conditionalFormatting
          const sourceXml = structureSourceXml.get(sourceModel)?.get(name!)
          if (source?.issues.length && sourceXml === undefined) throw new Error('条件格式来源正在同步，请稍后重试删除')
          return source && { issues: source.issues, sourceXml: sourceXml ?? '' }
        })
        assertDataValidationSheetRemoval(workbook, command.params?.subUnitId, sheetId => {
          const name = snapshot.sheets[sheetId]?.name
          const source = sourceModel.sheets.find(sheet => sheet.name === name)?.dataValidations
          const sourceXml = structureSourceXml.get(sourceModel)?.get(name!)
          if (source?.readOnlyReason && sourceXml === undefined) throw new Error('数据验证来源正在同步，请稍后重试删除')
          return source && { readOnlyReason: source.readOnlyReason, sourceXml: sourceXml ?? '' }
        })
        assertCellFormulaSheetRemoval(workbook, command.params?.subUnitId, sheetId => {
          const name = snapshot.sheets[sheetId]?.name
          const sourceXml = structureSourceXml.get(sourceModel)?.get(name!)
          return sourceXml === undefined ? undefined : { sourceXml, unprojected: true }
        })
        const workbookXml = workbookSourceXml.get(sourceModel)
        if (workbookXml === undefined) throw new Error('定义名称来源正在同步，请稍后重试删除')
        assertDefinedNameSheetRemoval(workbook, command.params?.subUnitId, { workbookXml, unprojectedNames })
        const targetSheet = command.params?.subUnitId ? workbook.getSheetBySheetId(command.params.subUnitId) : workbook.getActiveSheet()
        const caches = pivotCacheSources.get(sourceModel)
        if (!caches) throw new Error('透视表来源正在同步，请稍后重试删除')
        if (caches instanceof Error) throw caches
        for (const xml of caches) if (pivotCacheReadsFromSheet(xml, targetSheet?.getSheetName() ?? ''))
          throw new Error(`仍有透视表读取工作表 "${targetSheet?.getSheetName()}" 的来源数据，已拒绝删除。`)
        const tableSource = sourceModel.sheets.find(sheet => sheet.name === targetSheet?.getSheetName())
        if (!tableSource) throw new Error('表格来源正在同步，请稍后重试删除')
        if (!tableSource.tableSources) throw new Error(`表格来源无法完整核对：${tableSource.tableSourcesReadOnlyReason ?? '来源身份缺失'}`)
        const removedTableParts = tableRemovalParts.get(sourceModel)?.get(tableSource.name)
        if (removedTableParts instanceof Error) throw removedTableParts
        if (tableSource.tableSources.length && !removedTableParts) throw new Error('表格删除来源正在同步，请稍后重试删除')
        assertTableSheetRemoval(workbook, command.params?.subUnitId, {
          tables: tableSource.tableSources, readOnlyReason: tableSource.tableSourcesReadOnlyReason, workbookXml, unprojectedNames,
          retainedNames: tableSource.tableSources.filter(table => !removedTableParts?.has(table.path)).flatMap(table => [table.name, table.displayName]),
          worksheet: sheetId => {
            const name = snapshot.sheets[sheetId]?.name, xml = structureSourceXml.get(sourceModel)?.get(name!)
            const sheet = sourceModel.sheets.find(sheet => sheet.name === name)
            return xml === undefined ? undefined : { xml, conditionalFormattingIncomplete: !!sheet?.conditionalFormatting?.issues.length, dataValidationIncomplete: !!sheet?.dataValidations?.readOnlyReason }
          },
        })
        assertChartSheetRemoval(workbook, command.params?.subUnitId, sheetId => {
          const charts = chartSources.get(sourceModel)
          if (!charts) throw new Error('图表来源正在同步，请稍后重试删除')
          if (charts instanceof Error) throw charts
          const owned = charts.sheets.get(snapshot.sheets[sheetId]?.name ?? '')
          if (!owned) throw new Error('图表所属工作表正在同步，请稍后重试删除')
          return [...owned, ...charts.unowned]
        })
      } catch (error) { feedback.textContent = (error as Error).message; throw error }
    }, (command, workbook) => {
      if (!loading) {
        try { sparklines?.assertStructure(command, workbook) }
        catch (error) { feedback.textContent = (error as Error).message; throw error }
      }
      preflightPivotRowColumns(command, workbook)
    })
    if (!definedNameScopes && typeof runtime.univer.__getInjector === 'function') definedNameScopes = installDefinedNameScopes(runtime)
    if (!validationNames && typeof runtime.univer.__getInjector === 'function') validationNames = installDataValidationNames(runtime)
    if (!outline && typeof runtime.univer.__getInjector === 'function') outline = installWorkbookOutline(runtime)
    if (!outlineGutter && typeof runtime.univer.__getInjector === 'function') outlineGutter = installOutlineGutter({ runtime, host: shell.editor.querySelector<HTMLElement>('.workbook-grid-frame')!,
      onToggleGroup: (axis, group, collapsed) => { if (!editable()) return; try { applyOutlineResult(toggleWorkbookOutlineGroup(runtime, axis, group, collapsed, id => sheetProtected(id))) } catch (error) { feedback.textContent = (error as Error).message } },
      onLevel: (axis, level) => { if (!editable()) return; try { applyOutlineResult(showWorkbookOutlineLevel(runtime, axis, level, id => sheetProtected(id))) } catch (error) { feedback.textContent = (error as Error).message } },
    })
    outlineGutter?.refresh()
    if (!tableHeaders && typeof runtime.univer.__getInjector === 'function') tableHeaders = installTableHeaders(runtime, id => sheetProtected(id), pivotTableColumnReason, message => { feedback.textContent = message })
    if (!tableDesign && typeof runtime.univer.__getInjector === 'function') tableDesign = installTableDesign(runtime, id => sheetProtected(id))
    if (!tableStyleRendering && typeof runtime.univer.__getInjector === 'function') tableStyleRendering = installNativeTableStyleRendering(runtime.univer.__getInjector())
    if (!tableResize && typeof runtime.univer.__getInjector === 'function') tableResize = installTableResize(runtime, id => sheetProtected(id), pivotTableColumnReason)
    if (!tableCreate && typeof runtime.univer.__getInjector === 'function') tableCreate = installTableCreate({ ...runtime, themePalette: currentModel.themePalette }, id => sheetProtected(id))
    if (!tableConvert && typeof runtime.univer.__getInjector === 'function') tableConvert = installTableConvert(runtime, id => sheetProtected(id))
    if (!tableTotals && typeof runtime.univer.__getInjector === 'function') tableTotals = installTableTotals(runtime, id => sheetProtected(id))
    if (!tableFilterButton && typeof runtime.univer.__getInjector === 'function') tableFilterButton = installTableFilterButton(runtime, id => sheetProtected(id))
    if (!tableHeaderRow && typeof runtime.univer.__getInjector === 'function') tableHeaderRow = installTableHeaderRow(runtime, id => sheetProtected(id))
    if (!tableStyleEdit && typeof runtime.univer.__getInjector === 'function') tableStyleEdit = installTableStyleEdit(runtime, id => sheetProtected(id))
    if (!tableFormulaReferences && typeof runtime.univer.__getInjector === 'function') tableFormulaReferences = installTableFormulaReferences(runtime)
    formulaSheets.clear()
    currentModel.sheets.forEach((sheet, index) => { if (sheet.showFormulas) formulaSheets.add(`sheet-${index}`) })
    // 无注入器的测试替身不提供拦截器服务：公式视图与计算选项不可用。
    if (!calculation && typeof runtime.univer.__getInjector === 'function') {
      try { calculation = installCalculation(runtime as never, sheetId => formulaSheets.has(sheetId)) } catch { calculation = undefined }
    }
    calculation?.calculateNow()
    calculation?.syncFormulaView(formulaSheets.has(activeSheetId() ?? ''))
    if (!dataTable && calculation) dataTable = installDataTable(runtime, calculation, id => sheetProtected(id))
    if (!goalSeek && calculation) goalSeek = installGoalSeek(runtime, calculation, id => sheetProtected(id))
    if (!subtotal && typeof runtime.univer.__getInjector === 'function') subtotal = installSubtotal(runtime, {
      readonly: () => !editable(), protectedSheet: sheetProtected,
      transaction: active => { subtotalMutating = active },
      captureMetadata: () => ({ structural: structural.slice(), undone: undone.slice(), dirty, gridChanged, status: shell.statusLabel.textContent }),
      restoreMetadata: (value, phase) => {
        const state = value as { structural: typeof structural; undone: CellShiftEntry[]; dirty: boolean; gridChanged: boolean; status: string | null }
        structural = state.structural.slice(); undone.splice(0, undone.length, ...state.undone); cfBaseline = undefined
        if (phase === 'rollback') {
          captureGeneration++; dirty = state.dirty; gridChanged = state.gridChanged; shell.statusLabel.textContent = state.status
        } else { markDirty(); ribbon.refreshState?.(); outlineGutter?.refresh() }
      },
      preflight: async (target: SubtotalTarget, plan) => {
        if (!editable() || structureLocked()) throw new Error('当前工作簿不可编辑或结构受保护')
        const workbook = runtime.univerAPI.getActiveWorkbook()!, sheet = workbook.getSheetBySheetId(target.sheetId)
        if (!sheet) throw new Error('分类汇总来源工作表已变化')
        for (const row of plan.inserts) {
          const command = { id: 'sheet.command.insert-row', params: { unitId: target.unitId, subUnitId: target.sheetId,
            range: { startRow: row, endRow: row, startColumn: 0, endColumn: sheet.getMaxColumns() - 1 } } }
          sparklines?.assertStructure(command, workbook)
          preflightPivotRowColumns(command, workbook)
        }
        // 在首次原生修改前按真实完整文件预演全部插行、公式与大纲，复用现有依赖和预算校验。
        const operations = await currentOperations(), name = sheet.getSheetName()
        await applyWorkbookOperations(original, subtotalPreflightOperations(operations, name, plan))
      },
    })
    if (!advancedFilter && typeof runtime.univer.__getInjector === 'function') advancedFilter = installAdvancedFilter(runtime, {
      readonly: () => !editable(), protectedSheet: sheetProtected,
      transaction: active => { advancedFilterMutating = active },
      captureMetadata: () => ({ dirty, gridChanged, status: shell.statusLabel.textContent }),
      restoreMetadata: (value, phase) => {
        const state = value as { dirty: boolean; gridChanged: boolean; status: string | null }
        if (phase === 'rollback') {
          captureGeneration++; dirty = state.dirty; gridChanged = state.gridChanged; shell.statusLabel.textContent = state.status
        } else { markDirty(); ribbon.refreshState?.() }
      },
      preflight: async (target, plan) => {
        if (!editable()) throw new Error('当前工作簿不可编辑或正在保存')
        const sheet = runtime.univerAPI.getActiveWorkbook()?.getSheetBySheetId(target.sheetId)
        if (!sheet) throw new Error('高级筛选来源工作表已变化')
        const operations = await currentOperations()
        await applyWorkbookOperations(original, advancedFilterPreflightOperations(operations, staged.length, sheet.getSheetName(), plan.filter))
      },
    })
    selectionListener = runtime.univerAPI.getActiveWorkbook()?.onSelectionChange?.(() => { ribbon.refreshState?.(); void nativeAI?.refresh() })
    staged = structuredClone(ops)
    structural = []
    undone.length = 0
    sheetProtection.clear(); structureLock = undefined
    await waitForWorkbookRendered(runtime, () => disposed)
    loading = false
    try {
      const { readPivotControlViews, installPivotControlOverlay, pivotControlGeometryOperation } = await import('./workbook-pivot-controls')
      const views = await readPivotControlViews(bytes)
      if (!disposed && controlGeneration === pivotControlGeneration && views.length) {
        const controlOperations = JSON.stringify(ops)
        pivotControlOverlay = installPivotControlOverlay(runtime, views, {
          stateHost: shell.editor,
          canEdit: view => {
            const sheet = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === view.pivot.targetSheetName)
            return editable() && !!sheet && !sheetProtected(sheet.getSheetId())
          },
          apply: async (config, control) => {
            if (disposed || controlGeneration !== pivotControlGeneration) throw new Error('控件已变化，请重新打开工作表')
            await persistence
            const operations = await currentOperations(), same = JSON.stringify(operations) === controlOperations
            const currentBytes = same ? bytes : await applyWorkbookOperations(original, operations)
            if (!same) {
              const before = views.find(view => view.control.name === control.name && view.control.tablePath === control.tablePath)
              const current = (await readPivotControlViews(currentBytes)).find(view => view.control.name === control.name && view.control.tablePath === control.tablePath)
              if (JSON.stringify(before) !== JSON.stringify(current)) throw new Error('透视表来源或控件已变化，请先刷新透视表')
            }
            if (disposed || controlGeneration !== pivotControlGeneration) throw new Error('控件已变化，请重新打开工作表')
            pivotContext = { bytes: currentBytes, operations }
            await applyPivot(config, control.tablePath, control)
            const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getSheets().find(sheet => sheet.getSheetName() === config.targetSheetName)
            if (sheet && !disposed) workbook!.setActiveSheet(sheet)
          },
          changeAnchor: async (view, anchor) => {
            if (!editable() || disposed || controlGeneration !== pivotControlGeneration) throw new Error('控件不可编辑或已变化，请重新打开工作表')
            await withWorkbookLocked(shell.editor, async () => {
              await persistence
              const target = runtime.univerAPI.getActiveWorkbook()?.getSheets().find(sheet => sheet.getSheetName() === view.pivot.targetSheetName)
              if (!target || sheetProtected(target.getSheetId())) throw new Error('目标工作表不存在或受保护')
              const before = await currentOperations(), currentBytes = await applyWorkbookOperations(original, before)
              const operation = await pivotControlGeometryOperation(currentBytes, view, anchor)
              if (disposed || controlGeneration !== pivotControlGeneration) throw new Error('控件已变化，请重新打开工作表')
              const drafts = pivotControlOverlay?.snapshotDrafts(), operations = [...before, operation]
              captureGeneration++
              try { await loadOperations(operations, drafts) }
              catch (error) { await loadOperations(before, drafts); throw error }
              if (nativeDraft) {
                nativeDraft.setOperations(before as NativeOperation[])
                nativeDraft.setOperations(operations as NativeOperation[])
              } else draft.setOperations(operations)
              const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getSheets().find(sheet => sheet.getSheetName() === view.pivot.targetSheetName)
              if (sheet && !disposed) workbook!.setActiveSheet(sheet)
              gridChanged = false; dirty = true
              shell.statusLabel.textContent = '有未保存修改'
              feedback.textContent = '原生控件位置与尺寸已更新，修改尚未保存。'
            }).finally(() => { ribbon.refreshState?.(); nativeAI?.refresh() })
          },
          error: message => { feedback.textContent = message },
        }, `pivot-controls-${controlGeneration}`, controlDrafts)
      }
    } catch (error) { feedback.textContent = '原生控件未显示：' + (error as Error).message }
    crossHighlight.setVisible(crossHighlightVisible)
    insertFunction.refresh()
    zoomLauncher.refresh()
    void pageBreakPreview.refresh()
    ribbon.refreshState?.()
  }
  const hideCandidate = () => { candidate.hidden = true; draft.reject(); aiId = '' }
  try {
    if (options.file) {
      const file = await options.file()
      sourcePath = file.path
      expectedSha256 = file.sha256
      original = new Uint8Array(file.bytes)
    } else {
      const response = await fetch(`${base}/api/file`, { credentials: 'same-origin' })
      if (!response.ok) throw new Error('工作簿载入失败，请刷新重试。')
      sourcePath = decodeURIComponent(response.headers.get('X-Workbook-Path') ?? '')
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
    if (options.native) { pivotControlOverlay?.dispose(); pageBreakPreview.dispose(); formulaTrace.dispose(); watchWindow.dispose(); errorChecking.dispose(); loadingLock.dispose(); goToReveal.dispose(); crossHighlight.dispose(); crossHighlightTheme?.removeEventListener('change', refreshCrossHighlight); formulaBar.dispose(); rtl.dispose(); functionOverrides?.dispose(); runtime.univer.dispose(); throw error }
    return
  }
  if (options.nativeAI && nativeDraft) {
    const syncNativeStatus = () => {
      gridChanged = false; dirty = nativeDraft.dirty
      shell.statusLabel.textContent = dirty ? '有未保存修改' : '已保存'
      ribbon.refreshState?.()
    }
    nativeAI = mountWorkbookNativeAI(shell.editor.querySelector<HTMLElement>('.workbook-ai')!, {
      api: options.nativeAI,
      locked: () => !editable() || nativeDraft.closed || nativeDraft.saving,
      accepting: value => { nativeAIAccepting = value; shell.save.disabled = value || saved },
      context: async scope => {
        const sheet = runtime.univerAPI.getActiveWorkbook()?.getActiveSheet()
        const range = sheet?.getSelection()?.getActiveRange()
        if (!sheet || !range) throw new Error('请选择有效的工作簿选区')
        // 先同步冻结范围，异步采集完整草稿不能把用户后来点击的选区带入本次请求。
        const selection = { sheetName: sheet.getSheetName(), startRow: range.getRow(), endRow: range.getRow() + range.getHeight() - 1,
          startColumn: range.getColumn(), endColumn: range.getColumn() + range.getWidth() - 1 }
        const label = scope === 'workbook' ? '整份工作簿' : selection.sheetName + '!' + formatAddress(selection.startRow, selection.startColumn) + ':' + formatAddress(selection.endRow, selection.endColumn)
        const cells = readBack(runtime).sheets.find(item => item.name === selection.sheetName)?.cells ?? {}
        await persistence
        const operations = await currentOperations()
        return { expectedSha256, operations: operations as NativeOperation[], selection, scope, label, cells }
      },
      apply: async operations => {
        await withWorkbookLocked(shell.editor, async () => {
          await persistence; captureGeneration++
          await loadOperations(operations as WorkbookOperation[])
          nativeDraft.setOperations(operations)
          syncNativeStatus()
        })
      },
      history: async direction => {
        await withWorkbookLocked(shell.editor, async () => {
          await persistence
          nativeDraft.setOperations(await currentOperations() as NativeOperation[])
          if (direction === 'undo') nativeDraft.undo(); else nativeDraft.redo()
          captureGeneration++
          await loadOperations(nativeDraft.operations as WorkbookOperation[])
          syncNativeStatus()
        })
      },
    })
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
    if (saved || saving || nativeAIAccepting || calculationBusy || subtotal?.isRunning() || advancedFilter?.isRunning()) return
    saving = true
    zoomLauncher.refresh()
    // 保存期间网格不可编辑：解除单次/锁定格式刷，避免保存中或保存后继续刷写。
    turnOffFormatPainter(runtime)
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
      shell.editor.inert = false
      form.inert = Boolean(options.native || saved)
      zoomLauncher.refresh()
      ribbon.refreshState?.()
      if (saved) shell.editor.querySelector<HTMLElement>('.workbook-grid')!.inert = true
    }
  }
  shell.save.addEventListener('click', save)
  const beforeLeave = (event: BeforeUnloadEvent) => {
    if (dirty) { event.preventDefault(); event.returnValue = '' }
  }
  window.addEventListener('beforeunload', beforeLeave)
  return { officeEditAssistant: nativeAI, async officeReadContext(scope: 'document' | 'selection') {
    const { captureWorkbookReadContext } = await import('./workbook-ai-read-context')
    return captureWorkbookReadContext(scope, { runtime, closed: () => disposed || Boolean(nativeDraft?.closed || nativeDraft?.saving),
      epoch: () => mergeGeneration, persisted: () => persistence, operations: async () => await currentOperations() as NativeOperation[],
      setOperations: operations => nativeDraft?.setOperations(operations) })
  }, dispose() {
    disposed = true; pivotControlOverlay?.dispose(); queriesDialog.dispose(); symbolDialog.dispose(); linkDialog.dispose(); disposeCsvImport?.(); printPreviewDialog?.dispose(); shell.editor.removeEventListener('keydown',pivotHistoryShortcut,true); pivotDialog?.dispose(); pivotFilterDialog?.dispose(); editableRangesDialog?.dispose(); nativeAI?.dispose(); pageBreakPreview.dispose(); formulaTrace.dispose(); watchWindow.dispose(); errorChecking.dispose(); loadingLock.dispose(); goToReveal.dispose(); crossHighlight.dispose(); crossHighlightTheme?.removeEventListener('change', refreshCrossHighlight); formulaBar.dispose(); rtl.dispose(); functionOverrides?.dispose(); functionShortcuts.dispose(); zoomLauncher.dispose(); insertFunction.dispose(); zoomDialog.dispose(); printScaleDialog.dispose(); headerFooterDialog.dispose(); painterListener?.dispose(); selectionListener?.dispose(); dataTable?.dispose(); dataTableDialog.dispose(); subtotal?.dispose(); subtotalDialog.dispose(); advancedFilter?.dispose(); advancedFilterDialog.dispose(); goalSeek?.dispose(); goalSeekDialog.dispose(); consolidateDialog.dispose(); numberFormatDialog.dispose(); axisDialog.dispose(); tableResizeDialog.dispose(); cellsDialog.dispose(); sortDialog.dispose(); dedupeDialog.dispose(); formatCellsDialog.dispose(); fillSeriesDialog.dispose(); goToDialog.dispose(); chartDesignDialog?.dispose(); historyListener?.dispose(); outlineShortcuts.dispose(); outlineGutter?.dispose(); outline?.dispose(); validationStructure?.dispose(); validationNames?.dispose(); definedNameScopes?.dispose(); tableHeaders?.dispose(); tableDesign?.dispose(); tableStyleRendering?.dispose(); tableResize?.dispose(); tableTotals?.dispose(); tableHeaderRow?.dispose(); tableFilterButton?.dispose(); tableConvert?.dispose(); tableCreate?.dispose(); tableCreateDialog.dispose(); tableStyleEdit?.dispose(); tableFormulaReferences?.dispose(); sparklines?.dispose(); setSparklineWorkbookResolver(runtime.univerAPI.getActiveWorkbook()?.getId() ?? "", undefined); calculation?.dispose(); noteDialog.dispose(); nameManagerDialog.dispose(); ribbon.dispose(); shell.save.removeEventListener('click', save); window.removeEventListener('beforeunload', beforeLeave); runtime.univer.dispose()
  } }
}
