import { useState } from 'react'
import type { Editor } from '@tiptap/core'
import { IconDoc, IconCaret, IconPageBreak, IconTable, IconPicture, IconChart, IconShapes, IconTextBox, IconWordArt, IconLink, IconBook, IconRefresh, IconComment, IconHeader, IconFooter, IconPageNumber, IconSymbol, IconEquation } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { insertRibbonZh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/insert-zh'
const BIG = 28
const unavailable = 'DOCX 原生写回协议尚未支持此结构操作'
const linkUnavailable = 'DOCX 超链接写回操作尚未接入'
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
/** 从固定上游 InsertTab 提取原分组、按钮和符号面板；结构操作等待写回协议。 */
export function DocxInsertSource({ editor, editable }: { editor: Editor; editable: boolean }) {
  const t = (key: keyof typeof insertRibbonZh) => insertRibbonZh[key]
  const [dropdown, setDropdown] = useState<string | null>(null)
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
          <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-blank-page" aria-label={t("ribbonBlankPageTip")}>
            <span className="rb-big-icon">
              <IconDoc size={BIG}/>
            </span>
            <span>{t('ribbonBlankPage')}</span>
          </button>
          <button className="rb-big" disabled={true} title={unavailable} aria-description={unavailable} data-action="insert-page-break" aria-label={t("ribbonPageBreakTip")}>
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
            <button className="rb-small" disabled={true} title={linkUnavailable} aria-description={linkUnavailable} data-action="insert-link" aria-label={`${t("ribbonLinkTip")}，${linkUnavailable}`}>
              <IconLink size={14}/> {t('ribbonLink')}
            </button>
            <button className="rb-small" disabled={true} title={linkUnavailable} aria-description={linkUnavailable} data-action="edit-link" aria-label={`编辑超链接，${linkUnavailable}`}>
              {t('ribbonLink')}（编辑）
            </button>
            <button className="rb-small" disabled={true} title={linkUnavailable} aria-description={linkUnavailable} data-action="remove-link" aria-label={`移除超链接，${linkUnavailable}`}>
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
    </></div>
}
