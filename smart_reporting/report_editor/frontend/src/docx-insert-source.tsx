import { useState } from 'react'
import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { DocxAnchor } from './docx-operations'
import { applyDocxLink, docxLinkSelection, linkSelectionUnavailable, type DocxLinkSelection } from './docx-links'
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
export function DocxInsertSource({ editor, editable, anchors = [] }: { editor: Editor; editable: boolean; anchors?: DocxAnchor[] }) {
  const t = (key: keyof typeof insertRibbonZh) => insertRibbonZh[key]
  const [dropdown, setDropdown] = useState<string | null>(null)
  const [linkDialog, setLinkDialog] = useState<DocxLinkSelection | null>(null)
  const [href, setHref] = useState('')
  const [linkError, setLinkError] = useState('')
  const link = editable ? docxLinkSelection(editor, anchors) : undefined
  const pageBreakReason = docxPageBreakUnavailable(editor, editable)
  const blankPageReason = docxBlankPageUnavailable(editor, editable)
  const linkUnavailable = linkSelectionUnavailable
  const openLink = () => { if (link) { setLinkDialog(link); setHref(link.href ?? ''); setLinkError('') } }
  const applyLink = (selection: DocxLinkSelection, value: string | null) => {
    try {
      if (!applyDocxLink(editor, selection, value)) throw new Error('链接修改未被接受，请检查段落的保存限制')
      setLinkDialog(null); setLinkError('')
    } catch (error) { setLinkError(error instanceof Error ? error.message : String(error)) }
  }
  return <div className="ribbon-content docx-source-insert"><>
      {/* Word: Pages (cover page / blank page / page break) sits leftmost */}
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-cover-page" aria-label={t("ribbonCoverPageTip")}>
              <span className="rb-big-icon">
                <IconDoc size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonCoverPage')}</span>
            </button>
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
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-table" aria-label={t("ribbonTableTip")}>
              <span className="rb-big-icon">
                <IconTable size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonTable')}</span>
            </button>
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupTables')}</div>
      </div>
      <div className="ribbon-sep"/>
      <div className="ribbon-group">
        <div className="ribbon-group-items">
          <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-picture" aria-label={t("ribbonPictureTip")}>
            <span className="rb-big-icon">
              <IconPicture size={BIG}/>
            </span>
            <span>{t('ribbonPicture')}</span>
          </button>
          <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-chart" aria-label={t("ribbonChartTip")}>
            <span className="rb-big-icon">
              <IconChart size={BIG}/>
            </span>
            <span>{t('ribbonChart')}</span>
          </button>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-shapes" aria-label={t("ribbonShapesTip")}>
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
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-text-box" aria-label={t("ribbonTextBoxTip")}>
              <span className="rb-big-icon">
                <IconTextBox size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonTextBox')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-word-art" aria-label={t("ribbonWordArtTip")}>
              <span className="rb-big-icon">
                <IconWordArt size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonWordArt')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-drop-cap" aria-label={t("ribbonDropCap")}>
              <span className="rb-big-icon" style={{ fontSize: 20, lineHeight: 1, fontWeight: 'bold' }}>
                A̲
                <IconCaret />
              </span>
              <span>{t('ribbonDropCap')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-field" aria-label={t("ribbonFieldTip")}>
              <span className="rb-big-icon" style={{ fontSize: 15, lineHeight: 1.2 }}>
                {'{ }'}
                <IconCaret />
              </span>
              <span>{t('ribbonField')}</span>
            </button>
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
              {t('ribbonLink')}（编辑）
            </button>
            <button className="rb-small" disabled={!link?.hasLink} title={!link?.hasLink ? linkUnavailable : undefined} aria-description={!link?.hasLink ? linkUnavailable : undefined} onMouseDown={event => event.preventDefault()} onClick={() => { if (link) applyLink(link, null) }} data-action="remove-link" aria-label="移除超链接">
              移除超链接
            </button>
            <button className="rb-small" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-bookmark" aria-label={t("ribbonBookmarkTip")}>
              <IconBook size={14}/> {t('ribbonBookmark')}
            </button>
            <button className="rb-small" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-cross-ref" aria-label={t("ribbonCrossRefTip")}>
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
          <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-new-comment" aria-label={t("ribbonNewCommentTip")}>
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
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-header" aria-label={t("ribbonHeaderTip")}>
              <span className="rb-big-icon">
                <IconHeader size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonHeader')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-footer" aria-label={t("ribbonFooterTip")}>
              <span className="rb-big-icon">
                <IconFooter size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonFooter')}</span>
            </button>
          </div>
          <div className="rb-split-wrap">
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-page-number" aria-label={t("ribbonPageNumber")}>
              <span className="rb-big-icon">
                <IconPageNumber size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonPageNumber')}</span>
            </button>
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
            <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-equation" aria-label={t("ribbonEquationTip")}>
              <span className="rb-big-icon">
                <IconEquation size={BIG}/>
                <IconCaret />
              </span>
              <span>{t('ribbonEquation')}</span>
            </button>
          </div>
        </div>
        <div className="ribbon-group-label">{t('ribbonGroupSymbols')}</div>
      </div>
      {linkDialog && <div role="dialog" aria-modal="true" aria-label="Link" className="docx-link-dialog" style={{ position: 'fixed', left: '50%', top: '25%', transform: 'translateX(-50%)', zIndex: 1000, background: 'white', padding: 20, border: '1px solid #aaa', boxShadow: '0 4px 24px #0003' }}>
        <form onSubmit={event => { event.preventDefault(); applyLink(linkDialog, href) }}>
          <label>链接地址 <input autoFocus aria-label="Link URL" value={href} onChange={event => setHref(event.target.value)} /></label>
          <button type="submit" data-command="applyLink" disabled={!editable || !editor.isEditable}>应用</button>
          <button type="button" data-command="cancelLink" onClick={() => { setLinkDialog(null); setLinkError(''); editor.view.focus() }}>取消</button>
          {linkError && <p role="alert">{linkError}</p>}
        </form>
      </div>}
      {!linkDialog && linkError && <p role="alert">{linkError}</p>}
    </></div>
}
