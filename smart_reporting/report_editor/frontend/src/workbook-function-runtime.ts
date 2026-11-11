/**
 * Univer side of the Function Arguments dialog: where the formula goes,
 * what the cell editor holds when the dialog opens, live sub-expression
 * evaluation, grid range picks and the formula bar's fx button.
 */
import { DOCS_FORMULA_BAR_EDITOR_UNIT_ID_KEY, DOCS_NORMAL_EDITOR_UNIT_ID_KEY } from '@univerjs/core'
import { IEditorService } from '@univerjs/docs-ui'

import { columnLabel, pickedRangeRef, type PreviewValue } from './workbook-function-arguments'
import { createBufferEntrySource, type EntrySource } from '@sheets-web/xlsx-engine/zip'
import { decodeXmlText, escapeRegExp, readXmlAttribute } from '@sheets-web/xlsx-engine/xml'

export interface FunctionTarget {
  readonly workbookCore: object
  readonly sheetCore: object
  readonly unitId: string
  readonly sheetId: string
  readonly sheetName: string
  readonly row: number
  readonly col: number
  readonly label: string
  /// Formula text the dialog edits (`=` included); '' for a cell without one.
  readonly formula: string
  readonly caret: number
  /// The cell editor was open with this text; Cancel reopens it.
  readonly editorText: string | null
}

export interface ExternalPickTarget {
  /// The link's stored `[n]` index.
  readonly index: number
  readonly name: string
  readonly source: string
  /// True when the source workbook is open in another tab: a grid pick can
  /// relay the range. Closed sources take a typed range instead.
  readonly open: boolean
  readonly wcId: number | null
  readonly sheetNames: readonly string[]
}

export interface FunctionArgumentsHost {
  readTarget(): Promise<FunctionTarget | null>
  write(target: FunctionTarget, formula: string): string | null
  evaluate(target: FunctionTarget, expressions: readonly string[]): Promise<PreviewValue[]>
  observeRangePick(target: FunctionTarget, onPick: (ref: string) => void): () => void
  /** Linked workbooks of the file being edited, flagged by whether their
      source is open in another tab. */
  listExternalPickTargets(): Promise<ExternalPickTarget[]>
  /** Arms a cross-workbook pick against one open linked workbook; the next
      range selected on that workbook's grid arrives through onPick as the
      stored `'[n]Sheet'!A1:B2` spelling. */
  pickExternalRange(target: ExternalPickTarget, onPick: (ref: string) => void): () => void
  cancel(target: FunctionTarget): void
}

/** Read only the current package's external-link declarations. Source files
 * are intentionally not opened or probed; the result only enables a typed
 * `[n]Sheet!A1` formula reference. */
export async function readExternalPickTargetsFromSource(source: Pick<EntrySource, 'has' | 'readText'>): Promise<ExternalPickTarget[]> {
  const workbook = await source.readText('xl/workbook.xml')
  const relationships = await source.readText('xl/_rels/workbook.xml.rels')
  const references = [...workbook.matchAll(/<externalReference\b[^>]*\br:id="([^"]+)"[^>]*\/?\s*>/g)]
  const targets: ExternalPickTarget[] = []
  for (let index = 0; index < references.length; index += 1) {
    const relationshipId = references[index]?.[1]
    if (!relationshipId) continue
    const relationship = relationships.match(new RegExp(`<Relationship\\b[^>]*\\bId="${escapeRegExp(relationshipId)}"[^>]*/?>`))?.[0]
    const rawTarget = relationship ? readXmlAttribute(relationship, 'Target') : undefined
    if (!rawTarget || !relationship || !/\/externalLink$/.test(readXmlAttribute(relationship, 'Type') ?? '') || readXmlAttribute(relationship, 'TargetMode') === 'External') continue
    const path = `xl/${rawTarget.replace(/^\/?xl\//, '').replace(/^\.\//, '')}`
    if (!(await source.has(path))) continue
    const link = await source.readText(path)
    const sheetNames = [...link.matchAll(/<sheetName\b[^>]*\bval="([^"]*)"[^>]*\/?\s*>/g)].map((match) => decodeXmlText(match[1] ?? ''))
    const relsPath = path.replace(/([^/]+)$/, '_rels/$1.rels')
    let sourceUri: string | undefined
    if (await source.has(relsPath)) {
      const linkRels = await source.readText(relsPath)
      const externalPath = linkRels.match(/<Relationship\b[^>]*\bType="[^"]*\/externalLinkPath"[^>]*\/?\s*>/)?.[0]
      if (externalPath && readXmlAttribute(externalPath, 'TargetMode') === 'External') {
        sourceUri = readXmlAttribute(externalPath, 'Target')
      }
    }
    const labelSource = sourceUri ?? `External workbook ${index + 1}`
    const name = labelSource.replaceAll('\\', '/').slice(labelSource.replaceAll('\\', '/').lastIndexOf('/') + 1) || labelSource
    targets.push({ index: index + 1, name, source: sourceUri ?? labelSource, open: false, wcId: null, sheetNames })
  }
  return targets
}

export async function readExternalPickTargets(bytes: Uint8Array): Promise<ExternalPickTarget[]> {
  return readExternalPickTargetsFromSource(await createBufferEntrySource(bytes))
}

function editorTextAndCaret(runtime: any): { text: string; caret: number } | null {
  const editorService = runtime.univer.__getInjector().get(IEditorService)
  const editor = editorService.getEditor(DOCS_NORMAL_EDITOR_UNIT_ID_KEY)
  if (!editor) return null
  const text = (editor.getDocumentData().body?.dataStream ?? '').replace(/\r?\n$/, '')
  const ranges =
    editor.getSelectionRanges().length > 0
      ? editor.getSelectionRanges()
      : (editorService.getEditor(DOCS_FORMULA_BAR_EDITOR_UNIT_ID_KEY)?.getSelectionRanges() ?? [])
  const caret = Math.min(text.length, ranges[0]?.startOffset ?? text.length)
  return { text, caret }
}

let evaluationQueue: Promise<void> = Promise.resolve()

/// The stored spelling of one external sheet reference: `[1]Sheet1` when the
/// name reads as a bare identifier (Excel leaves it unquoted), the quoted
/// `'[1]Sheet Name'` otherwise — the two shapes the gateway's break/renumber
/// scan and the sidecar's usage scan both match.
export function formatExternalRef(index: number, sheetName: string, body: string): string {
  const bare = /^[A-Za-z_][A-Za-z0-9_.]*$/.test(sheetName) && !/^[A-Za-z]{1,3}\d+$/.test(sheetName)
  const part = bare ? `[${index}]${sheetName}` : `'[${index}]${sheetName.replace(/'/g, "''")}'`
  return `${part}!${body}`
}

/// The stored spelling for a range picked on another workbook's grid: the
/// sheet name comes from the link's stored list when the picked tab's sheet
/// matches one (case-insensitive), the live name otherwise. Whole-row/column
/// picks keep their `1:3` / `A:C` bodies.
export function formatExternalPickRef(
  target: ExternalPickTarget,
  selection: {
    sheetName: string
    startRow: number
    endRow: number
    startColumn: number
    endColumn: number
    rangeType?: number | undefined
  },
): string {
  const stored =
    target.sheetNames.find((name) => name.toLowerCase() === selection.sheetName.toLowerCase()) ??
    selection.sheetName
  // equal names keep pickedRangeRef sheet-unqualified, leaving the A1 body
  const body = pickedRangeRef(selection, stored, stored)
  return formatExternalRef(target.index, stored, body)
}

export function createWorkbookFunctionHost(runtime: any, options: {
  editable: () => boolean; protectedSheet: (sheetId: string) => boolean;
  onWrite: (formula: string, target: FunctionTarget) => void;
  file?: () => Promise<{ bytes: ArrayBuffer }>
}): FunctionArgumentsHost & {dispose(): void} {
  let disposed = false
  const identity = (target: FunctionTarget) => {
    const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getSheetBySheetId(target.sheetId)
    if (disposed || !workbook || workbook.getWorkbook() !== target.workbookCore || !sheet || sheet.getSheet() !== target.sheetCore) throw new Error('函数目标工作簿或工作表已关闭或替换')
    return {workbook,sheet}
  }
  const writable = (sheetId: string) => {
    if (disposed || !options.editable()) throw new Error('当前工作簿不可编辑或正在保存')
    if (options.protectedSheet(sheetId)) throw new Error('工作表受保护，请先撤销保护')
  }
  return {
    async readTarget() {
      const workbook = runtime.univerAPI.getActiveWorkbook(), worksheet = workbook?.getActiveSheet(), range = workbook?.getActiveRange()
      if (!workbook || !worksheet || !range) return null
      writable(worksheet.getSheetId())
      const workbookCore = workbook.getWorkbook(), sheetCore = worksheet.getSheet(), row = range.getRow(), col = range.getColumn()
      let editorText: string | null = null, caret = 0
      if (workbook.isCellEditing?.()) {
        const editing = editorTextAndCaret(runtime)
        editorText = editing?.text ?? ''; caret = editing?.caret ?? 0
        await workbook.endEditingAsync(false)
      }
      const cellFormula = worksheet.getRange(row,col,1,1).getFormula(), formula = editorText ?? cellFormula, isFormula = formula.startsWith('=')
      const target = {workbookCore,sheetCore,unitId:workbook.getId(),sheetId:worksheet.getSheetId(),sheetName:worksheet.getSheetName(),row,col,label:`${columnLabel(col)}${row+1}`,formula:isFormula?formula:'',caret:isFormula?(editorText===null?formula.length:caret):0,editorText}
      identity(target);writable(target.sheetId)
      return target
    },
    write(target, formula) {
      try {
        const {workbook,sheet}=identity(target);writable(target.sheetId)
        const cell=sheet.getRange(target.row,target.col,1,1)
        cell.setValue({f:formula})
        identity(target)
        if (cell.getFormula() !== formula) return '函数公式未写入目标单元格'
        identity(target);workbook.setActiveSheet(sheet)
        identity(target);workbook.setActiveRange(cell)
        identity(target);options.onWrite(formula,target)
        return null
      } catch(error) {return (error as Error).message}
    },
    async evaluate(target,expressions) {
      if (!expressions.length) return []
      identity(target)
      const formulas=expressions.map(expr=>expr.startsWith('=')?expr:`=${expr}`)
      const run=evaluationQueue.then(()=>{
        identity(target)
        return runtime.univerAPI.getFormula().executeFormulas({[target.unitId]:{[target.sheetId]:{[target.row]:{[target.col]:formulas}}}},3000)
      })
      evaluationQueue=run.then(()=>undefined,()=>undefined)
      const result=await run,items=result[target.unitId]?.[target.sheetId]?.[target.row]?.[target.col]??[]
      const byFormula=new Map(items.map((item:any)=>[item.formula,item.value as PreviewValue]))
      return formulas.map(formula=>byFormula.get(formula) as PreviewValue)
    },
    observeRangePick(target,onPick) {
      let armed=false
      const arm=(event:PointerEvent)=>{if(event.target instanceof Element && event.target.closest('#workbook-grid'))armed=true}
      document.addEventListener('pointerdown',arm,true)
      const subscription=runtime.univerAPI.addEvent(runtime.univerAPI.Event.SelectionMoveEnd,(params:any)=>{
        const range=params.selections[0]
        if (!armed || !range || params.workbook.getWorkbook() !== target.workbookCore) return
        onPick(pickedRangeRef(range,params.worksheet.getSheetName(),target.sheetName))
      })
      return ()=>{document.removeEventListener('pointerdown',arm,true);subscription.dispose()}
    },
    // 本地没有desktop外链工作簿宿主；外部picker仍是独立未实现缺口。
    async listExternalPickTargets(){
      if (!options.file) return []
      try { return await readExternalPickTargets(new Uint8Array((await options.file()).bytes)) }
      catch (error) { throw new Error(`外部工作簿链接清单不可用：${error instanceof Error ? error.message : String(error)}`) }
    },
    pickExternalRange(){throw new Error('当前浏览器尚未提供外部工作簿范围选择宿主')},
    cancel(target){
      if(target.editorText===null)return
      try{
        const {workbook,sheet}=identity(target);writable(target.sheetId)
        const cell=sheet.getRange(target.row,target.col,1,1);workbook.setActiveSheet(sheet);workbook.setActiveRange(cell)
        if(!workbook.startEditing())return
        runtime.univer.__getInjector().get(IEditorService).getEditor(DOCS_NORMAL_EDITOR_UNIT_ID_KEY)?.replaceText(target.editorText,true)
      }catch{ /* 来源已关闭/只读时不重开编辑器。 */ }
    },
    dispose(){disposed=true},
  }
}
