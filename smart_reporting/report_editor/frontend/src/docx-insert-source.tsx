import {EquationGallery,EquationModal,type MathEditTarget} from './docx-equation-source'
import { useEffect, useRef, useState } from 'react'
import type { DocxPreparedHfEdges } from './docx-hf-source'
import type { SectionChangeResult, SectionValues } from './docx-operations'
import { DocxPageNumberDialog } from './docx-page-number-dialog'
import { hfPageNumberOnly, hfHasPageField, hfWithoutPageMarks } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'
import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { DocxAnchor } from './docx-operations'
import { docxPictureUnavailable, insertDocxImageFile } from './docx-clipboard'
import { COVER_PRESETS, docxCoverUnavailable, docxHasCoverPage, insertDocxCoverPage, removeDocxCoverPage } from './docx-cover-page'
import { NEW_TABLE_LIMITS, docxTableInsertUnavailable, insertDocxTable, newTableSize } from './docx-new-table'
import { applyDocxLink, docxLinkSelection, linkSelectionUnavailable, type DocxLinkSelection } from './docx-links'
import { openDocxLinkDialog } from './docx-link-dialog'
import { applyDocxDropCap, docxDropCapUnavailable } from './docx-drop-cap'
import { IconDoc, IconCaret, IconPageBreak, IconTable, IconPicture, IconChart, IconShapes, IconTextBox, IconWordArt, IconLink, IconBook, IconRefresh, IconComment, IconHeader, IconFooter, IconPageNumber, IconSymbol, IconEquation } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { insertRibbonZh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/insert-zh'
const BIG = 28
const unavailable = 'DOCX 原生写回协议尚未支持此结构操作'

const SYMBOLS = [
  '—',
  '…',
  '·',
  '§',
  '¶',
  '†',
  '©',
  '®',
  '™',
  '°',
  '±',
  '×',
  '÷',
  '≤',
  '≥',
  '≠',
  '≈',
  '∞',
  '√',
  'µ',
  '€',
  '£',
  '¥',
  '¢',
  '←',
  '→',
  '↑',
  '↓',
  '⇐',
  '⇒',
  '★',
  '☆',
  '✓',
  '✗',
  '●',
  '○',
  '■',
  '□',
  '◆',
  '◇',
  '①',
  '②',
  '③',
  '④',
  '⑤',
  '⑥',
  '⑦',
  '⑧',
  '⑨',
  '⑩',
]
/** 固定源 page-break.ts（f8c17004）语义：段首直接给当前段落设 pageBreakBefore，段中/段尾
 *  拆段后由后半段承载 pageBreakBefore；一次 dispatch，单次撤销即可恢复。本地适配两点：
 *  拆出的后半段清空 docxIndex（固定源 splitBlock 会把原锚点复制给两半，与 extensions.ts
 *  split-twin/docx-clipboard 同规），保存时成为携带分页的 insertParagraph；文档开头的
 *  分页在固定源中写成换行符（hardBreak pageBreak），本地保存协议只承载段落
 *  pageBreakBefore，因此如实禁用。表格单元格内的段落同样不承载分页。 */
export const DOCX_PAGE_BREAK_AT_START = '文档开头的分页符需要写入换行符，当前保存协议尚不支持；请将光标放在其他段落'
export const DOCX_PAGE_BREAK_NESTED = '表格或嵌套内容中不能插入分页符'
export function docxPageBreakUnavailable(editor: Editor, editable: boolean): string | undefined {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  const { $from } = editor.state.selection
  if (!$from.parent.isTextblock || $from.depth !== 1 || !('pageBreakBefore' in $from.parent.attrs)) return DOCX_PAGE_BREAK_NESTED
  if ($from.parentOffset === 0 && $from.before($from.depth) === 0) return DOCX_PAGE_BREAK_AT_START
  return undefined
}
/** 空白页不受"文档开头"限制（空白段本身成为首页，后续段由段落分页承载）。 */
export function docxBlankPageUnavailable(editor: Editor, editable: boolean): string | undefined {
  if (!editable || !editor.isEditable) return '当前文档不可编辑或正在保存'
  const { $from } = editor.state.selection
  if (!$from.parent.isTextblock || $from.depth !== 1 || !('pageBreakBefore' in $from.parent.attrs)) return DOCX_PAGE_BREAK_NESTED
  return undefined
}
export function insertDocxPageBreak(editor: Editor): boolean {
  const reason = docxPageBreakUnavailable(editor, true)
  if (reason) throw new Error(reason)
  const tr = editor.state.tr
  if (!tr.selection.empty) tr.deleteSelection()
  const $from = tr.selection.$from
  if ($from.depth !== 1 || !$from.parent.isTextblock) throw new Error(DOCX_PAGE_BREAK_NESTED)
  if ($from.parentOffset === 0) {
    if ($from.before(1) === 0) throw new Error(DOCX_PAGE_BREAK_AT_START)
    tr.setNodeMarkup($from.before(1), undefined, { ...$from.parent.attrs, pageBreakBefore: true })
  } else {
    tr.split($from.pos, 1, [{ type: $from.parent.type, attrs: { ...$from.parent.attrs, docxIndex: null, pageBreakBefore: true } }])
  }
  editor.view.dispatch(tr.scrollIntoView())
  editor.view.focus()
  return true
}
/** 固定源 ribbon-tabs.tsx insertBlankPageAt（f8c17004）：插入一个自成一页的空段落，且仅当
 *  后面还有内容时给后续块加分页（无条件插两个分页段会把 1 页文档变成 3 页）；后续块不能
 *  承载分页（如表格）时补一个带分页的空段落。光标落在新空白页。本地在一次事务内完成并
 *  沿用分页符的锚点规则：拆段后半段清空 docxIndex，新段落不带样式属性。 */
export function insertDocxBlankPage(editor: Editor): boolean {
  if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
  const tr = editor.state.tr
  if (!tr.selection.empty) tr.deleteSelection()
  const $from = tr.selection.$from
  if ($from.depth !== 1 || !$from.parent.isTextblock || !('pageBreakBefore' in $from.parent.attrs)) throw new Error(DOCX_PAGE_BREAK_NESTED)
  const paragraph = editor.state.schema.nodes.docParagraph
  if (!paragraph) throw new Error(DOCX_PAGE_BREAK_NESTED)
  const blank = () => paragraph.create({ pageBreakBefore: true })
  const start = $from.before(1), end = $from.after(1)
  let blankPos: number
  if ($from.parentOffset === 0) {
    // 段首：空白页插在当前段之前，当前段从下一页开始。
    tr.insert(start, blank())
    blankPos = start
    const moved = tr.doc.nodeAt(start + 2)
    if (moved && !moved.attrs.pageBreakBefore) tr.setNodeMarkup(start + 2, undefined, { ...moved.attrs, pageBreakBefore: true })
  } else if ($from.parentOffset === $from.parent.content.size) {
    // 段尾：空白页插在当前段之后，后续块（若有）从下一页开始。
    tr.insert(end, blank())
    blankPos = end
    const followPos = end + 2
    const follow = followPos < tr.doc.content.size ? tr.doc.nodeAt(followPos) : null
    if (follow) {
      if ('pageBreakBefore' in follow.attrs) { if (!follow.attrs.pageBreakBefore) tr.setNodeMarkup(followPos, undefined, { ...follow.attrs, pageBreakBefore: true }) }
      else tr.insert(followPos, blank())
    }
  } else {
    // 段中：拆段，空白页夹在两半之间，后半段从再下一页开始。
    tr.split($from.pos, 1, [{ type: $from.parent.type, attrs: { ...$from.parent.attrs, docxIndex: null, pageBreakBefore: true } }])
    blankPos = tr.doc.resolve(tr.mapping.map($from.pos)).before(1)
    tr.insert(blankPos, blank())
  }
  tr.setSelection(TextSelection.create(tr.doc, blankPos + 1))
  editor.view.dispatch(tr.scrollIntoView())
  editor.view.focus()
  return true
}
/** 从固定上游 InsertTab 提取原分组、按钮和符号面板；结构操作等待写回协议。 */
export function DocxInsertSource({ editor, editable, anchors = [], headerFooter, pageNumber, onNewComment, onBookmarks, onCrossReference, onInsertObject,onInsertChart,onInsertField,onUpdateFields,onEditField,onToggleFieldCode,onToggleAllFieldCodes }:  {
  onEditField?:()=>void
  onToggleFieldCode?:()=>void
  onToggleAllFieldCodes?:()=>void
  onUpdateFields?:()=>void
  onInsertChart?:()=>void
  onInsertField?:(instruction:string)=>void
  onInsertObject?:(type:'textbox'|'shape'|'wordArt')=>void
  editor: Editor; editable: boolean; anchors?: DocxAnchor[]; onNewComment?: () => void; onBookmarks?: () => void; onCrossReference?: () => void
  headerFooter?: { prepare(): Promise<DocxPreparedHfEdges>; edit(target: DocxPreparedHfEdges['header'] | DocxPreparedHfEdges['footer']): void }
  pageNumber?: { format?: string | null; start?: number | null; reason?: string; label?: string; commit(values: SectionValues): SectionChangeResult }
}) {
  const t = (key: keyof typeof insertRibbonZh) => insertRibbonZh[key]
  const [equationDialog,setEquationDialog]=useState<MathEditTarget|null|undefined>(undefined)

  const [dropdown, setDropdown] = useState<string | null>(null)
  const [hfEdges, setHfEdges] = useState<DocxPreparedHfEdges | null>(null)
  const [hfError, setHfError] = useState('')
  const [hfLoading, setHfLoading] = useState(false)
  const hfRequest = useRef(0)
  const [numberDialog, setNumberDialog] = useState<typeof pageNumber>()
  const openHf = async (id: string) => {
    if (dropdown === id) { hfRequest.current++; setDropdown(null); return }
    const request = ++hfRequest.current
    setDropdown(id); setHfEdges(null); setHfError(''); setHfLoading(true)
    try {
      const edges = await headerFooter!.prepare()
      if (request === hfRequest.current && !editor.isDestroyed) { edges.assertCurrent(); setHfEdges(edges) }
    } catch (error) { if (request === hfRequest.current) setHfError((error as Error).message) }
    finally { if (request === hfRequest.current) setHfLoading(false) }
  }
  const runHf = (action: (edges: DocxPreparedHfEdges) => void) => {
    try {
      if (!editable || !editor.isEditable || !hfEdges) throw new Error('当前页眉页脚目标尚未就绪')
      hfEdges.assertCurrent(); action(hfEdges); setDropdown(null)
    } catch (error) { setHfError((error as Error).message) }
  }
  const hfMenu = (part: 'header' | 'footer' | 'pagenum') => <div data-rb-panel="" className="layout-menu">
    {hfLoading ? <span role="status">正在定位当前页面…</span> : null}
    {hfError ? <span role="alert">{hfError}</span> : null}
    {part !== 'pagenum' ? <>
      <button disabled={!hfEdges || hfLoading} onClick={() => runHf(edges => headerFooter!.edit(edges[part]))}>{part === 'header' ? t('ribbonHfEditHeader') : t('ribbonHfEditFooter')}</button>
      <button disabled={!hfEdges || hfLoading} onClick={() => runHf(edges => { const target = edges[part]; target.controller.onCommit(part, target.variant, { text: '' }) })}>{part === 'header' ? t('ribbonHfRemoveHeader') : t('ribbonHfRemoveFooter')}</button>
    </> : <>
      {(['header', 'footer'] as const).flatMap(kind => (['left', 'center', 'right'] as const).map((align, index) => <button key={`${kind}-${align}`} data-source-action={`insert-page-number-${kind}-${align}`} disabled={!hfEdges || hfLoading} onClick={() => runHf(edges => { const target = edges[kind]; target.controller.onCommit(kind, target.variant, hfPageNumberOnly(align)) })}>{kind === 'header' ? [t('ribbonPnTopLeft'), t('ribbonPnTopCenter'), t('ribbonPnTopRight')][index] : [t('ribbonPnBottomLeft'), t('ribbonPnBottomCenter'), t('ribbonPnBottomRight')][index]}</button>))}
      <button disabled={!pageNumber || !!pageNumber.reason} title={pageNumber?.reason} onClick={() => { setNumberDialog(pageNumber); setDropdown(null) }}>{t('ribbonPnFormat')}</button>
      <button disabled={!hfEdges || hfLoading} onClick={() => runHf(edges => { for (const kind of ['footer', 'header'] as const) { const target = edges[kind], value = target.controller.valueOf(kind, target.variant)?.value; if (hfHasPageField(value)) target.controller.onCommit(kind, target.variant, hfWithoutPageMarks(value!)) } })}>{t('ribbonPnRemove')}</button>
    </>}
  </div>
  const pictureInput = useRef<HTMLInputElement>(null)
  const pictureTarget = useRef<{ doc: Editor['state']['doc']; selection: Editor['state']['selection'] } | null>(null)
  const [pictureError, setPictureError] = useState('')
  const [pictureLoading, setPictureLoading] = useState(false)
  const pictureReason = pictureLoading ? '正在读取图片' : docxPictureUnavailable(editor, editable)
  const [linkDialog, setLinkDialog] = useState<DocxLinkSelection | null>(null)
  const [linkError, setLinkError] = useState('')
  const linkRoot = useRef<HTMLDivElement>(null)
  const linkModal = useRef<ReturnType<typeof openDocxLinkDialog> | null>(null)
  const linkEditable = useRef(editable)
  linkEditable.current = editable
  useEffect(() => {
    if (!linkDialog) return
    const dialog = openDocxLinkDialog(linkRoot.current!.closest<HTMLElement>('.docx-native') ?? document.body, linkDialog.href ?? '', {
      unavailable: () => !linkEditable.current || !editor.isEditable,
      apply: value => { if (!applyDocxLink(editor, linkDialog, value)) throw new Error('链接修改未被接受，请检查段落的保存限制') },
      onClose: () => { setLinkDialog(null); setLinkError(''); if (!editor.isDestroyed) editor.view.focus() },
    })
    linkModal.current = dialog
    return () => { dialog.dispose(); linkModal.current = null }
  }, [linkDialog, editor])
  useEffect(() => { linkModal.current?.refresh() }, [editable, editor.isEditable])
  const link = editable ? docxLinkSelection(editor, anchors) : undefined
  const pageBreakReason = docxPageBreakUnavailable(editor, editable)
  const tableReason = docxTableInsertUnavailable(editor, editable)
  const coverReason = docxCoverUnavailable(editor, editable)
  const [coverError, setCoverError] = useState('')
  const runCover = (action: () => boolean) => {
    try { action(); setDropdown(null); setCoverError('') } catch (error) { setCoverError(error instanceof Error ? error.message : String(error)) }
  }
  const [grid, setGrid] = useState({ r: 0, c: 0 })
  const [tableForm, setTableForm] = useState<{ rows: number; cols: number } | null>(null)
  const [tableError, setTableError] = useState('')
  const insertTable = (rows: number, cols: number) => {
    try {
      newTableSize({ rows, cols })
      insertDocxTable(editor, rows, cols)
      setDropdown(null); setTableForm(null); setTableError(''); setGrid({ r: 0, c: 0 })
    } catch (error) { setTableError(error instanceof Error ? error.message : String(error)) }
  }
  const blankPageReason = docxBlankPageUnavailable(editor, editable)
  const linkUnavailable = linkSelectionUnavailable
  const openLink = () => { if (link) { setLinkDialog(link); setLinkError('') } }
  const applyLink = (selection: DocxLinkSelection, value: string | null) => {
    try {
      if (!applyDocxLink(editor, selection, value)) throw new Error('链接修改未被接受，请检查段落的保存限制')
      setLinkDialog(null); setLinkError('')
    } catch (error) { setLinkError(error instanceof Error ? error.message : String(error)) }
  }
  return <div ref={linkRoot} className="ribbon-content docx-source-insert"><>
      {/* Word: Pages (cover page / blank page / page break) sits leftmost */}
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!!coverReason} title={coverReason ?? t('ribbonCoverPageTip')} aria-description={coverReason} aria-haspopup="true" aria-expanded={dropdown === 'cover'} onMouseDown={event => event.preventDefault()} onClick={() => { setCoverError(''); setDropdown(current => current === 'cover' ? null : 'cover') }} data-action="insert-cover-page" aria-label={t("ribbonCoverPageTip")}>
              <span className="rb-big-icon">
                <IconDoc size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonCoverPage')}</span>
            </button>
            {dropdown === 'cover' && !coverReason && (<div data-rb-panel="" className="cover-gallery">
                {/* 固定源 ribbon-insert-tab.tsx:729-755：预设封面卡片 + 删除当前封面 */}
                {COVER_PRESETS.map(preset => (<button key={preset.id} type="button" className="cover-card" data-cover-preset={preset.id} onMouseDown={event => event.preventDefault()} onClick={() => runCover(() => insertDocxCoverPage(editor, preset.id))}>
                    <span className="cover-card-name">{preset.name}</span>
                  </button>))}
                <button type="button" className="cover-gallery-remove" data-action="remove-cover-page" disabled={!docxHasCoverPage(editor)} onMouseDown={event => event.preventDefault()} onClick={() => runCover(() => removeDocxCoverPage(editor))}>删除当前封面</button>
                {coverError && <p role="alert" className="table-picker-error">{coverError}</p>}
              </div>)}
          </div>
          <button className="rb-big" disabled={!!blankPageReason} title={blankPageReason ?? t('ribbonBlankPageTip')} aria-description={blankPageReason} onMouseDown={event => event.preventDefault()} onClick={() => { if (!docxBlankPageUnavailable(editor, editable)) insertDocxBlankPage(editor) }} data-action="insert-blank-page" aria-label={t("ribbonBlankPageTip")}>
            <span className="rb-big-icon">
              <IconDoc size={BIG}/>
            </span>
            <span>{t('ribbonBlankPage')}</span>
          </button>
          <button className="rb-big" disabled={!!pageBreakReason} title={pageBreakReason ?? t('ribbonPageBreakTip')} aria-description={pageBreakReason} onMouseDown={event => event.preventDefault()} onClick={() => { if (!docxPageBreakUnavailable(editor, editable)) insertDocxPageBreak(editor) }} data-action="insert-page-break" aria-label={t("ribbonPageBreakTip")}>
            <span className="rb-big-icon">
              <IconPageBreak size={BIG}/>
            </span>
            <span>{t('ribbonPageBreak')}</span>
          </button>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupPages')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!!tableReason} title={tableReason ?? t('ribbonTableTip')} aria-description={tableReason} aria-haspopup="true" aria-expanded={dropdown === 'table'} onMouseDown={event => event.preventDefault()} onClick={() => { setTableError(''); setTableForm(null); setDropdown(current => current === 'table' ? null : 'table') }} data-action="insert-table" aria-label={t("ribbonTableTip")}>
              <span className="rb-big-icon">
                <IconTable size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonTable')}</span>
            </button>
            {dropdown === 'table' && !tableReason && (<div data-rb-panel="" className="table-picker" onMouseLeave={() => setGrid({ r: 0, c: 0 })}>
                {/* 固定源 ribbon-insert-tab.tsx:801-833：8×10 悬停网格 + "插入表格…" 自定义行列 */}
                <div className="table-picker-title" data-testid="table-picker-title">{grid.r > 0 ? `${grid.r}×${grid.c} 表格` : '选择表格尺寸'}</div>
                {!tableForm && <div className="table-picker-grid">
                  {Array.from({ length: 8 }, (_, ri) => Array.from({ length: 10 }, (_, ci) => (
                    <button key={`${ri}-${ci}`} type="button" className={`table-cell ${ri < grid.r && ci < grid.c ? 'hot' : ''}`} data-table-size={`${ri + 1}x${ci + 1}`} aria-label={`${ri + 1}×${ci + 1} 表格`}
                      onMouseDown={event => event.preventDefault()} onMouseEnter={() => setGrid({ r: ri + 1, c: ci + 1 })} onFocus={() => setGrid({ r: ri + 1, c: ci + 1 })} onClick={() => insertTable(ri + 1, ci + 1)} />
                  )))}
                </div>}
                {!tableForm && <button type="button" className="table-picker-custom" data-action="insert-table-custom" onMouseDown={event => event.preventDefault()} onClick={() => setTableForm({ rows: 2, cols: 5 })}>插入表格…</button>}
                {tableForm && <form className="table-picker-form" aria-label="插入表格" onSubmit={event => { event.preventDefault(); insertTable(tableForm.rows, tableForm.cols) }}>
                  <label>列数<input type="number" min={1} max={NEW_TABLE_LIMITS.cols} value={tableForm.cols} data-field="table-cols" onChange={event => setTableForm({ ...tableForm, cols: Number(event.currentTarget.value) })} /></label>
                  <label>行数<input type="number" min={1} max={NEW_TABLE_LIMITS.rows} value={tableForm.rows} data-field="table-rows" onChange={event => setTableForm({ ...tableForm, rows: Number(event.currentTarget.value) })} /></label>
                  <button type="submit" data-command="insertTable">插入</button>
                  <button type="button" data-command="cancelTable" onClick={() => { setTableForm(null); setTableError('') }}>取消</button>
                </form>}
                {tableError && <p role="alert" className="table-picker-error">{tableError}</p>}
              </div>)}
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupTables')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <input ref={pictureInput} type="file" accept="image/png,image/jpeg" hidden aria-label="选择 PNG 或 JPEG 图片" onChange={event => {
            const file = event.currentTarget.files?.[0], target = pictureTarget.current
            event.currentTarget.value = ''; pictureTarget.current = null
            if (!file || !target) return
            setPictureLoading(true); setPictureError('')
            void insertDocxImageFile(editor, file, target).catch(error => setPictureError(error instanceof Error ? error.message : String(error))).finally(() => setPictureLoading(false))
          }} />
          <button className="rb-big" disabled={!!pictureReason} title={pictureReason ?? '插入 PNG 或 JPEG 图片（最大 8MB）'} aria-description={pictureReason} onMouseDown={event => event.preventDefault()} onClick={() => {
            if (docxPictureUnavailable(editor, editable) || pictureLoading) return
            pictureTarget.current = { doc: editor.state.doc, selection: editor.state.selection }
            setPictureError(''); pictureInput.current?.click()
          }} data-action="insert-picture" aria-label={t("ribbonPictureTip")}>
            <span className="rb-big-icon">
              <IconPicture size={BIG}/>
            </span>
            <span>{t('ribbonPicture')}</span>
          </button>
          {pictureError && <p role="alert" className="table-picker-error">{pictureError}</p>}
          <button className="rb-big" disabled={!editable||!onInsertChart} title={onInsertChart?undefined:unavailable} onMouseDown={event=>event.preventDefault()} onClick={()=>onInsertChart?.()} data-action="insert-chart" aria-label={t("ribbonChartTip")}>
            <span className="rb-big-icon">
              <IconChart size={BIG}/>
            </span>
            <span>{t('ribbonChart')}</span>
          </button>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !onInsertObject} title={onInsertObject ? undefined : unavailable} onMouseDown={event=>event.preventDefault()} onClick={()=>onInsertObject?.('shape')} data-action="insert-shapes" aria-label={t("ribbonShapesTip")}>
              <span className="rb-big-icon">
                <IconShapes size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonShapes')}</span>
            </button>
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupIllustrations')}</div>
      </div>
      <div className="ribbon-sep"/>
      {/* Text group: text box + WordArt + drop cap */}
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !onInsertObject} title={onInsertObject ? undefined : unavailable} onMouseDown={event=>event.preventDefault()} onClick={()=>onInsertObject?.('textbox')} data-action="insert-text-box" aria-label={t("ribbonTextBoxTip")}>
              <span className="rb-big-icon">
                <IconTextBox size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonTextBox')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !onInsertObject} title={onInsertObject ? undefined : unavailable} onMouseDown={event=>event.preventDefault()} onClick={()=>onInsertObject?.('wordArt')} data-action="insert-word-art" aria-label={t("ribbonWordArtTip")}>
              <span className="rb-big-icon">
                <IconWordArt size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonWordArt')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !!docxDropCapUnavailable(editor, anchors)} title={docxDropCapUnavailable(editor, anchors) ?? t('ribbonDropCap')} aria-haspopup="menu" aria-expanded={dropdown === 'dropCap'} onMouseDown={event => event.preventDefault()} onClick={() => setDropdown(current => current === 'dropCap' ? null : 'dropCap')} data-action="insert-drop-cap" aria-label={t("ribbonDropCap")}>
              <span className="rb-big-icon" style={{ fontSize: 20, lineHeight: 1, fontWeight: 'bold' }}>
                A̲
                <IconCaret />
              </span>
              <span>{t('ribbonDropCap')}</span>
            </button>
            {dropdown === 'dropCap' ? <div data-rb-panel="" className="dropcap-menu" role="menu" aria-label="首字下沉方式">
              {([{ value: null, label: '无', desc: '取消首字下沉' }, { value: 'drop', label: '下沉', desc: '首字下沉（嵌入文字）' }, { value: 'margin', label: '悬挂', desc: '首字悬挂（在页边距处）' }] as const).map(option => <button type="button" role="menuitem" key={option.label} className="dropcap-option" data-drop-cap-option={option.value ?? 'none'} title={option.desc} onMouseDown={event => event.preventDefault()} onClick={() => { if (!editable || docxDropCapUnavailable(editor, anchors)) return; applyDocxDropCap(editor, anchors, option.value); setDropdown(null) }}><span className="dropcap-preview">{option.value ? 'A' : '—'}</span><span>{option.label}</span></button>)}
            </div> : null}
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!onInsertField&&!onToggleAllFieldCodes} title={onInsertField?undefined:unavailable} onMouseDown={event=>event.preventDefault()} onClick={()=>setDropdown(current=>current==='field'?null:'field')} data-action="insert-field" aria-label={t("ribbonFieldTip")}>
              <span className="rb-big-icon" style={{ fontSize: 15, lineHeight: 1.2 }}>
                {'{ }'}
                <IconCaret />
              </span>
              <span>{t('ribbonField')}</span>
            </button>
            {dropdown==='field'&&<div className="layout-menu" role="menu" aria-label="域类型">{([['DATE','日期'],['TIME','时间'],['PAGE','页码'],['NUMPAGES','总页数'],['FILENAME','文件名']] as const).map(([value,label])=><button type="button" role="menuitem" key={value} data-field={value} disabled={!editable} onMouseDown={event=>event.preventDefault()} onClick={()=>{setDropdown(null);onInsertField?.(value)}}>{label}</button>)}<button type="button" role="menuitem" data-action="update-fields" disabled={!editable||!onUpdateFields} onClick={()=>{setDropdown(null);onUpdateFields?.()}}>更新域 (F9)</button>{([['edit-field','编辑域',onEditField],['toggle-field-code','切换所选域代码',onToggleFieldCode],['toggle-all-field-codes','切换全部域代码 (Alt+F9)',onToggleAllFieldCodes]]as const).map(([action,label,callback])=><button key={action} type="button" role="menuitem" data-action={action} disabled={!callback||(action==='edit-field'&&!editable)} onMouseDown={event=>event.preventDefault()} onClick={()=>{setDropdown(null);callback?.()}}>{label}</button>)}</div>}
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupText')}</div>
      </div>
      <div className="ribbon-sep"/>
      {/* Word: Link/Bookmark/Cross-reference are small vertical buttons */}
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-col">
            <button className="rb-small" disabled={!link || editor.state.selection.empty} title={!link || editor.state.selection.empty ? linkUnavailable : undefined} aria-description={!link || editor.state.selection.empty ? linkUnavailable : undefined} onMouseDown={event => event.preventDefault()} onClick={openLink} data-action="insert-link" aria-label={t("ribbonLinkTip")}>
              <IconLink size={14}/> {t('ribbonLink')}
            </button>
            <button className="rb-small" disabled={!link?.href} title={!link?.href ? linkUnavailable : undefined} aria-description={!link?.href ? linkUnavailable : undefined} onMouseDown={event => event.preventDefault()} onClick={openLink} data-action="edit-link" aria-label="编辑超链接">
              <IconLink size={14} /> {t('ribbonLink')}（编辑）
            </button>
            <button className="rb-small" disabled={!link?.hasLink} title={!link?.hasLink ? linkUnavailable : undefined} aria-description={!link?.hasLink ? linkUnavailable : undefined} onMouseDown={event => event.preventDefault()} onClick={() => { if (link) applyLink(link, null) }} data-action="remove-link" aria-label="移除超链接">
              <IconLink size={14} /> 移除超链接
            </button>
            <button className="rb-small" disabled={!onBookmarks} title={onBookmarks ? t("ribbonBookmarkTip") : unavailable} aria-description={onBookmarks ? undefined : unavailable} onMouseDown={event => event.preventDefault()} onClick={onBookmarks} data-action="insert-bookmark" aria-label={t("ribbonBookmarkTip")}>
              <IconBook size={14}/> {t('ribbonBookmark')}
            </button>
            <button className="rb-small" disabled={!editable || !editor.isEditable || !onCrossReference} title={onCrossReference ? t("ribbonCrossRefTip") : unavailable} aria-description={onCrossReference ? undefined : unavailable} onMouseDown={event => event.preventDefault()} onClick={onCrossReference} data-action="insert-cross-ref" data-editable-action="true" aria-label={t("ribbonCrossRefTip")}>
              <IconRefresh size={14}/> {t('ribbonCrossRef')}
            </button>
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupLinks')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          {/* Word: Insert → Comment starts a new comment; the pane toggle stays on Review.
        Deliberately not gated on this tab's hasDoc (= canEdit): under the comments-only
        restriction the body is read-only yet commenting stays allowed, matching the
        Review tab's New Comment. Without a document canComment is false anyway. */}
          <button className="rb-big" disabled={!editable || !editor.isEditable || !onNewComment} title={onNewComment ? t("ribbonNewCommentTip") : unavailable} aria-description={onNewComment ? undefined : unavailable} data-action="insert-new-comment" data-editable-action="true" aria-label={t("ribbonNewCommentTip")} onMouseDown={event => event.preventDefault()} onClick={onNewComment}>
            <span className="rb-big-icon">
              <IconComment size={BIG}/>
            </span>
            <span>{t('ribbonComment')}</span>
          </button>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupComments')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !editor.isEditable || !headerFooter} onClick={() => void openHf('header')} data-action="insert-header" aria-label={t("ribbonHeaderTip")}>
              <span className="rb-big-icon">
                <IconHeader size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonHeader')}</span>
            </button>
            {dropdown === 'header' ? hfMenu('header') : null}
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !editor.isEditable || !headerFooter} onClick={() => void openHf('footer')} data-action="insert-footer" aria-label={t("ribbonFooterTip")}>
              <span className="rb-big-icon">
                <IconFooter size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonFooter')}</span>
            </button>
            {dropdown === 'footer' ? hfMenu('footer') : null}
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable || !editor.isEditable || !headerFooter} onClick={() => void openHf('pagenum')} data-action="insert-page-number" aria-label={t("ribbonPageNumber")}>
              <span className="rb-big-icon">
                <IconPageNumber size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonPageNumber')}</span>
            </button>
            {dropdown === 'pagenum' ? hfMenu('pagenum') : null}
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupHeaderFooter')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable} data-editable-action="true" onClick={() => setDropdown(current => current === 'symbol' ? null : 'symbol')} data-action="insert-symbol" aria-label={t("ribbonSymbol")}>
              <span className="rb-big-icon">
                <IconSymbol size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonSymbol')}</span>
            </button>
            {dropdown === 'symbol' && (<div data-rb-panel="" className="symbol-palette">
                {SYMBOLS.map((s) => (<button key={s} className="symbol-cell" disabled={!editable} data-editable-action="true" onClick={() => {
                editor.chain().focus().insertContent(s).run();
                setDropdown(() => null);
            }}>
                    {s}
                  </button>))}
              </div>)}
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={!editable} data-editable-action="true" onClick={()=>setDropdown(current=>current==='equation'?null:'equation')} data-action="insert-equation" aria-label={t("ribbonEquationTip")}>
              <span className="rb-big-icon">
                <IconEquation size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonEquation')}</span>
            </button>
            {dropdown==='equation'?<EquationGallery editor={editor} onPick={()=>setDropdown(null)} onCustom={()=>{setDropdown(null);setEquationDialog(null)}}/>:null}
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupSymbols')}</div>
      </div>
      {equationDialog!==undefined?<EquationModal editor={editor} editTarget={equationDialog??undefined} onClose={()=>setEquationDialog(undefined)}/>:null}
      {numberDialog ? <DocxPageNumberDialog format={numberDialog.format} start={numberDialog.start} label={numberDialog.label} disabledReason={!editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : !pageNumber ? '当前节页码设置不可用' : pageNumber.reason} onChange={values => numberDialog.commit(values)} onClose={() => setNumberDialog(undefined)} /> : null}
      {!dropdown && hfError ? <p role="alert">{hfError}</p> : null}
      {!linkDialog && linkError && <p role="alert">{linkError}</p>}
    </></div>
}
