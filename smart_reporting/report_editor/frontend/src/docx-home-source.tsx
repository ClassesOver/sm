import { OfficeAIEntry } from './office-ai-entry'
import {
  IconAlignCenter, IconAlignJustify, IconAlignLeft, IconAlignRight, IconBorderAll, IconBorderBottom,
  IconBorderLeft, IconBorderNone, IconBorderRight, IconBorderTop, IconBullets,
  IconChangeCase, IconClearFormat, IconCopy, IconCut, IconFormatPainter,
  IconGrowFont, IconHighlight, IconIndentDec, IconIndentInc, IconLineSpacing,
  IconNumbered, IconPaste, IconPasteMerge, IconPasteSource, IconPasteText, IconPicture, IconShading,
  IconShrinkFont, IconSubscript, IconSuperscript, IconCaret, IconSelectAll, IconSearch, IconReplace, IconConvert,
  IconPilcrow,
} from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import type { DocxPasteMode } from './docx-clipboard'
import type { CaseMode } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/case-transform'
import { DOCX_BORDER_COLORS, DOCX_BORDER_WIDTHS_PT, safeDocxBorders, type DocxBorderSpec } from './docx-borders'
import { DOCX_HIGHLIGHTS } from './docx-highlight'
import { DOCX_SHADING_COLORS } from './docx-shading'
import { HIGHLIGHT_CSS } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/marks'
import { useId, useRef, useState } from 'react'
import { useDismissablePopover } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
import { homeRibbonZh as zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/home-zh'
import { zh as ribbonZh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { zh as appZh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/app/zh'

type Props = {
  onExport?:(format:'html'|'markdown'|'pdf')=>void
  onAssistant?: () => void
  onClearFormatting?: () => void
  clearFormattingUnavailable?: string | null
  editable: boolean
  onChangeCase?: (mode: CaseMode) => void
  caseUnavailable?: string | null
  paragraphStyleControl?: HTMLElement
  bulletListControl?: HTMLElement
  numberListControl?: HTMLElement
  multilevelListControl?: HTMLElement
  onSetNumberingValue?: () => void
  numberingValueUnavailable?: string | null
  onVerticalAlign?: (kind: 'superscript' | 'subscript') => void
  verticalAlign?: string
  verticalAlignAvailable?: boolean
  onMark: (name: 'bold' | 'italic' | 'underline' | 'strike') => void
  onFontSize: (delta: number) => void
  onFontFamily: (value: string) => void
  onFontSizeValue: (value: number) => void
  onHighlight?: (value: string) => void
  highlight?: string | null
  highlightAvailable?: boolean
  onColor: (value: string) => void
  onAlignment: (value: 'left' | 'center' | 'right' | 'justify') => void
  onIndent: (delta: -1 | 1) => void
  alignment?: string
  indentLeft?: number | null
  onList: (kind: 'bullet' | 'ordered') => void
  listKind?: string
  listLevelDecreaseAvailable?: boolean
  listLevelIncreaseAvailable?: boolean
  listLevelOptions?: boolean[]
  listLevel?: number
  onListLevel?: (ilvl: number) => void
  spaceBefore?: number | null
  spaceAfter?: number | null
  lineSpacing?: number | null
  onSpacing?: (values: Record<string, unknown>) => void
  onFontOptions?: () => void
  fontOptionsUnavailable?: string | null
  onParagraphOptions?: () => void
  paragraphOptionsUnavailable?: string | null
  onLineSpacingOptions?: () => void
  lineSpacingUnavailable?: string | null
  onSpecialIndentOptions?: () => void
  specialIndentUnavailable?: string | null
  onShading?: (value: string) => void
  shading?: string | null
  shadingAvailable?: boolean
  onBorders?: (value: { sides: string; color: string | null; szPt: number } | null) => void
  borders?: DocxBorderSpec | null
  bordersAvailable?: boolean
  onParagraph?: (command: 'add' | 'delete') => void
  onFindReplace?: (mode: 'find' | 'replace') => void
  onSelectAll?: () => void
  onToggleFormattingMarks?: () => void
  formattingMarksVisible?: boolean
  onPaste?: (mode?: DocxPasteMode) => void
  onPasteSpecial?: (defaults?:boolean) => void
  onCut?: () => void
  onCopy?: () => void
  onPainterClick?: () => void
  onPainterDoubleClick?: () => void
  painterActive?: boolean
  onUnavailable?: (reason: string) => void
}

const unavailable = '原版控件保留；当前 DOCX 原生操作协议未支持此命令'

/**
 * Browser extraction of GenOffice Ribbon.tsx's Home branch (fixed source SHA
 * recorded in SOURCE-SHA256.json). Its App callbacks are replaced by Native
 * Tiptap/DOCX operations; unsupported commands remain visible and disabled.
 */
export function DocxHomeSource({ onExport, onAssistant, onClearFormatting, clearFormattingUnavailable, editable, onChangeCase, caseUnavailable, onMark, onFontSize, onFontFamily, onFontSizeValue, onColor, onHighlight, highlight, highlightAvailable, onAlignment, onIndent, alignment, indentLeft, onList, listKind, listLevelDecreaseAvailable, listLevelIncreaseAvailable, listLevelOptions, listLevel, onListLevel, spaceBefore, spaceAfter, lineSpacing, onSpacing, onFontOptions, fontOptionsUnavailable, onParagraphOptions, paragraphOptionsUnavailable, onLineSpacingOptions, lineSpacingUnavailable, onSpecialIndentOptions, specialIndentUnavailable, onShading, shading, shadingAvailable, onBorders, borders, bordersAvailable, onParagraph, onVerticalAlign, verticalAlign, verticalAlignAvailable, paragraphStyleControl, multilevelListControl, bulletListControl, numberListControl, onSetNumberingValue, numberingValueUnavailable, onFindReplace, onSelectAll, onToggleFormattingMarks, formattingMarksVisible, onPaste, onPasteSpecial, onCut, onCopy, onPainterClick, onPainterDoubleClick, painterActive }: Props) {
  const fontListId = useId()
  const [caseOpen, setCaseOpen] = useState(false)
  const caseWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(caseOpen, () => setCaseOpen(false), { inside: () => [caseWrap.current], escape: true })
  const canCase = editable && !!onChangeCase && !caseUnavailable
  const caseModes: [CaseMode, string][] = [
    ['sentence', ribbonZh.ribbonCaseSentence], ['lower', ribbonZh.ribbonCaseLower], ['upper', ribbonZh.ribbonCaseUpper],
    ['title', ribbonZh.ribbonCaseTitle], ['toggle', ribbonZh.ribbonCaseToggle],
    ['halfWidth', ribbonZh.ribbonCaseHalfWidth], ['fullWidth', ribbonZh.ribbonCaseFullWidth],
  ]
  const [highlightOpen, setHighlightOpen] = useState(false)
  const [penHighlight, setPenHighlight] = useState('yellow')
  const highlightWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(highlightOpen, () => setHighlightOpen(false), { inside: () => [highlightWrap.current], escape: true })
  const canHighlight = editable && !!highlightAvailable && !!onHighlight
  const highlightTip = '文字突出显示颜色；作用于选中文字，未选文字时作用于整段'
  const [shadingOpen, setShadingOpen] = useState(false)
  const [penShading, setPenShading] = useState('EDF5FC')
  const shadingWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(shadingOpen, () => setShadingOpen(false), { inside: () => [shadingWrap.current], escape: true })
  const canShading = editable && !!shadingAvailable && !!onShading
  const shadingTip = '段落底纹；请选择有唯一来源锚点的非空正文段落'
  // GenOffice f8c17004 Ribbon.tsx table pen defaults (borderColor 000000, borderSz 4
  // eighth-points) with Word's Home border split default (bottom); the paragraph
  // menu writes w:val="single" lines only — other line styles fail closed.
  const [bordersOpen, setBordersOpen] = useState(false)
  const [penBorder, setPenBorder] = useState<'bottom' | 'top' | 'left' | 'right' | 'tblr'>('bottom')
  const [penBorderColor, setPenBorderColor] = useState<string | null>('000000')
  const [penBorderWidth, setPenBorderWidth] = useState(0.5)
  const bordersWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(bordersOpen, () => setBordersOpen(false), { inside: () => [bordersWrap.current], escape: true })
  const canBorders = editable && !!bordersAvailable && !!onBorders
  // 粘贴分体（固定源 Ribbon.tsx:3619-3663）：主按钮按默认粘贴，分体菜单给出
  // 源真实模式；保留源格式/合并格式因富文本无法映射保存协议而禁用并说明。
  const [pasteOpen, setPasteOpen] = useState(false)
  const pasteWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(pasteOpen, () => setPasteOpen(false), { inside: () => [pasteWrap.current], escape: true })
  const canPaste = editable && !!onPaste
  const BORDER_MODE_SIDES = { bottom: 'b', top: 't', left: 'l', right: 'r', tblr: 'tblr' } as const
  const borderPenSpec = (mode: keyof typeof BORDER_MODE_SIDES) => safeDocxBorders({ sides: BORDER_MODE_SIDES[mode], color: penBorderColor, szPt: penBorderWidth })
  const bordersActive = !!borders?.length
  const bordersTip = '段落边框（单实线）；请选择有唯一来源锚点的非空正文段落'
  const applyPenBorders = (mode: keyof typeof BORDER_MODE_SIDES) => {
    const spec = borderPenSpec(mode)
    if (JSON.stringify(spec) === JSON.stringify(borders ?? null)) onBorders?.(null)
    else onBorders?.({ sides: BORDER_MODE_SIDES[mode], color: penBorderColor, szPt: penBorderWidth })
    setBordersOpen(false)
  }
  const [spacingOpen, setSpacingOpen] = useState(false)
  const spacingWrap = useRef<HTMLDivElement>(null)
  useDismissablePopover(spacingOpen, () => setSpacingOpen(false), {
    inside: () => [spacingWrap.current],
    escape: true,
  })
  const disabled = (action: string, label: string, glyph: ReactNode, reason = unavailable) => <button type="button" className="rb-icon docx-source-command" data-action={action} disabled title={`${label}：${reason}`} aria-label={`${label}，${reason}`}>{glyph}</button>
  const unavailableSourceAction = (id: string, action: string, label: string, reason: string) => <button type="button" className="rb-icon docx-source-command" data-action={action} data-source-action={id} disabled title={`${label}：${reason}`} aria-label={`${label}，${reason}`}><IconCaret size={10} /></button>
  const action = (id: string, label: string, children: ReactNode, onClick: () => void, pressed?: boolean, available = true, unavailableReason = '段落操作回调不可用') => (
    <button type="button" className={`rb-icon${pressed ? ' active' : ''}`} data-action={id} data-editable-action="true" disabled={!editable || !available} title={available ? label : `${label}：${unavailableReason}`} aria-label={available ? label : `${label}，${unavailableReason}`} aria-pressed={pressed} onClick={onClick}>{children}</button>
  )
  const group = (key: string, children: ReactNode) => (
    <div className={key === "AI 助手" ? "ribbon-group office-ai-group" : "ribbon-group"}><div className="ribbon-group-items">{children}</div><div className="ribbon-group-label">{key}</div></div>
  )
  return <div className="ribbon-content docx-source-home">
    {group('AI 助手', <OfficeAIEntry onOpen={onAssistant} />)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupClipboard, <>
      <div className="rb-split-wrap rb-big-split" ref={pasteWrap}>
        <button type="button" className="rb-big" data-action="paste" data-editable-action="true" disabled={!canPaste} title={canPaste ? zh.ribbonPaste : '粘贴：剪贴板回调不可用'} aria-label={canPaste ? zh.ribbonPaste : `粘贴，剪贴板回调不可用`} onClick={() => onPaste?.()}>
          <IconPaste size={28} />
        </button>
        <button type="button" className={`rb-big-split-caret${pasteOpen ? ' active' : ''}`} data-action="paste-menu" data-editable-action="true" disabled={!canPaste} aria-haspopup="menu" aria-expanded={pasteOpen} title={zh.ribbonPaste} aria-label={zh.ribbonPaste} onClick={() => setPasteOpen(open => !open)}>
          <span>{zh.ribbonPaste}</span>
          <span className="rb-caret-inline"><IconCaret /></span>
        </button>
        {pasteOpen && <div data-rb-panel="" className="spacing-menu paste-menu" role="menu">
          <button type="button" role="menuitem" data-action="paste-source" disabled={!canPaste} onClick={()=>{setPasteOpen(false);onPaste?.('source')}}><IconPasteSource size={16}/>{appZh.appPasteKeepSource}</button>
          <button type="button" role="menuitem" data-action="paste-merge" disabled={!canPaste} onClick={()=>{setPasteOpen(false);onPaste?.('merge')}}><IconPasteMerge size={16}/>{appZh.appPasteMergeFormat}</button>
          <button type="button" role="menuitem" data-action="paste-text" data-source-action="paste-text" disabled={!canPaste} title={zh.ribbonPaste} aria-label={appZh.appPasteTextOnly} onClick={() => { setPasteOpen(false); onPaste?.('text') }}>
            <IconPasteText size={16} />{appZh.appPasteTextOnly}
          </button>
          <button type="button" role="menuitem" data-action="paste-picture" data-source-action="paste-picture" disabled={!canPaste} title="粘贴剪贴板中的图片" aria-label="粘贴图片（PNG/JPEG/GIF）" onClick={() => { setPasteOpen(false); onPaste?.('picture') }}>
            <IconPicture size={16} />图片
          </button>
          <button type="button" role="menuitem" data-action="paste-special" disabled={!canPaste||!onPasteSpecial} onClick={()=>{setPasteOpen(false);onPasteSpecial?.()}}>{ribbonZh.ribbonPasteSpecial}</button>
          <button type="button" role="menuitem" data-action="paste-defaults" disabled={!canPaste||!onPasteSpecial} onClick={()=>{setPasteOpen(false);onPasteSpecial?.(true)}}>{ribbonZh.ribbonSetDefaultPaste}</button>
        </div>}
      </div>
      <div className="rb-col">
        <button type="button" className="rb-small" data-action="cut" data-editable-action="true" disabled={!editable || !onCut} title={onCut ? zh.ribbonCutTip : '剪切：剪贴板回调不可用'} aria-label={onCut ? zh.ribbonCutTip : '剪切，剪贴板回调不可用'} onClick={() => onCut?.()}><IconCut size={17} /></button>
        <button type="button" className="rb-small" data-action="copy" data-editable-action="true" disabled={!editable || !onCopy} title={onCopy ? zh.ribbonCopyTip : '复制：剪贴板回调不可用'} aria-label={onCopy ? zh.ribbonCopyTip : '复制，剪贴板回调不可用'} onClick={() => onCopy?.()}><IconCopy size={17} /></button>
        <button type="button" className={`rb-small${painterActive ? ' active' : ''}`} data-action="format-painter" data-editable-action="true" disabled={!editable || !onPainterClick} aria-pressed={!!painterActive} title={painterActive ? ribbonZh.ribbonPainterActiveTip : zh.ribbonPainterTip} aria-label={painterActive ? ribbonZh.ribbonPainterActiveTip : zh.ribbonPainterTip} onClick={() => onPainterClick?.()} onDoubleClick={() => onPainterDoubleClick?.()}><IconFormatPainter size={17} /></button>
      </div>
    </>)}
    <div className="ribbon-sep" />
    {group('字体', <>
      <button type="button" data-action="font-options" disabled={!editable || !onFontOptions || !!fontOptionsUnavailable} title={fontOptionsUnavailable ?? '字体设置'} onMouseDown={event => event.preventDefault()} onClick={() => onFontOptions?.()}>字体…</button>
      <div className="rb-row">
        <input className="rb-select rb-font-family" data-action="font-family" data-editable-action="true" aria-label={zh.ribbonFontFamilyTip} placeholder={zh.ribbonFontFamilyTip} disabled={!editable} list={fontListId} title="选择或输入字体，按 Enter 应用；系统字体需本机安装"
          onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); onFontFamily(event.currentTarget.value.trim()) } }} />
        <datalist id={fontListId}>
          <option value="Noto Serif CJK SC" label="思源宋体（内置常用中文）" />
          <option value="Noto Sans CJK SC" label="思源黑体（内置常用中文）" />
          <option value="LXGW WenKai" label="霞鹜文楷（内置常用中文）" />
          <option value="Ma Shan Zheng" label="马善政毛笔楷书（内置常用中文）" />
          <option value="ZCOOL XiaoWei" label="站酷小薇（内置常用中文）" />
          {[['SimSun', '宋体'], ['SimHei', '黑体'], ['Microsoft YaHei', '微软雅黑'], ['KaiTi', '楷体'], ['FangSong', '仿宋']].map(([value, label]) => <option key={value} value={value} label={`${label}（系统字体）`} />)}
        </datalist>
        <input className="rb-select rb-font-size" data-action="font-size" data-editable-action="true" type="number" min="1" max="1638" step="0.5" defaultValue="12" aria-label={zh.ribbonFontSizeTip} disabled={!editable}
          onInput={event => { const value = Number(event.currentTarget.value); if (value >= 1 && value <= 1638 && Number.isInteger(value * 2)) onFontSizeValue(value) }} />
        {action('grow-font', zh.ribbonGrowFont, <IconGrowFont size={17} />, () => onFontSize(1))}
        {action('shrink-font', zh.ribbonShrinkFont, <IconShrinkFont size={17} />, () => onFontSize(-1))}
        <div className="rb-split-wrap" ref={caseWrap} onMouseDown={event => event.preventDefault()}>
          <button type="button" className="rb-icon" data-action="change-case" disabled={!canCase} title={caseUnavailable ?? zh.ribbonChangeCase} aria-label={zh.ribbonChangeCase} aria-expanded={caseOpen && canCase} onClick={() => setCaseOpen(open => !open)}><IconChangeCase size={17} /><span className="rb-caret-inline"><IconCaret /></span></button>
          {caseOpen && canCase && <div data-rb-panel="" className="spacing-menu case-menu" role="menu">
            {caseModes.map(([mode, label]) => <button key={mode} type="button" role="menuitem" data-action={`change-case:${mode}`} onClick={() => { setCaseOpen(false); onChangeCase?.(mode) }}>{label}</button>)}
          </div>}
        </div>{action('clear-formatting', zh.ribbonClearFormatting, <IconClearFormat size={17} />, () => onClearFormatting?.(), undefined, !!onClearFormatting && !clearFormattingUnavailable, clearFormattingUnavailable ?? '清除格式回调不可用')}
      </div>
      <div className="rb-row">
        {action('bold', zh.ribbonBoldTip, <b>B</b>, () => onMark('bold'))}
        {action('italic', zh.ribbonItalicTip, <i>I</i>, () => onMark('italic'))}
        {action('underline', zh.ribbonUnderlineTip, <u>U</u>, () => onMark('underline'))}
        {action('strike', zh.ribbonStrikethrough, <s>ab</s>, () => onMark('strike'))}
        {action('subscript', zh.ribbonSubscript, <IconSubscript size={17} />, () => onVerticalAlign?.('subscript'), verticalAlign === 'subscript', !!verticalAlignAvailable, '作用于同一来源段落内的选中文字，未选文字时作用于整段')}
        {action('superscript', zh.ribbonSuperscript, <IconSuperscript size={17} />, () => onVerticalAlign?.('superscript'), verticalAlign === 'superscript', !!verticalAlignAvailable, '作用于同一来源段落内的选中文字，未选文字时作用于整段')}
        <div className="rb-split-wrap docx-ribbon-highlight" ref={highlightWrap} onMouseDown={event => { if ((event.target as HTMLElement).closest('button')) event.preventDefault() }}>
          <button type="button" className={`rb-icon rb-color-btn${highlight && highlight !== 'none' ? ' active' : ''}`} data-action="highlight" data-editable-action="true" disabled={!canHighlight} title={highlightTip} aria-label={highlightTip} onClick={() => onHighlight?.(highlight === penHighlight ? 'none' : penHighlight)}>
            <span className="rb-color-glyph rb-color-glyph-svg"><IconHighlight size={17} /><span className="rb-color-bar" style={{ background: HIGHLIGHT_CSS[penHighlight] }} /></span>
          </button>
          <button type="button" className={`rb-caret rb-color-caret${highlightOpen ? ' active' : ''}`} data-action="highlight-palette" disabled={!canHighlight} title={highlightTip} aria-label="高亮颜色选择" aria-expanded={highlightOpen && canHighlight} onClick={() => setHighlightOpen(open => !open)}><IconCaret size={10} /></button>
          {highlightOpen && canHighlight && <div data-rb-panel="" className="color-palette color-palette-highlight color-palette-highlight-word docx-ribbon-highlight-palette">
            <div className="color-section-title color-highlight-title">{ribbonZh.ribbonHighlightColors}</div>
            <div className="color-highlight-grid">{DOCX_HIGHLIGHTS.map(value => <button type="button" key={value} className={`color-swatch color-highlight-swatch${highlight === value ? ' selected' : ''}`} data-action={`highlight-${value}`} aria-label={value} aria-pressed={highlight === value} title={value} style={{ background: HIGHLIGHT_CSS[value] }} onClick={() => { setPenHighlight(value); onHighlight?.(value) }} />)}</div>
            <button type="button" className={`color-none color-highlight-none${highlight == null || highlight === 'none' ? ' selected' : ''}`} data-action="highlight-none" onClick={() => onHighlight?.('none')}>{ribbonZh.ribbonNoColor}</button>
          </div>}
        </div>
        <input className="rb-color-input" data-action="font-color" data-editable-action="true" type="color" aria-label={zh.ribbonFontColor} title={zh.ribbonFontColor} disabled={!editable} onInput={event => onColor(event.currentTarget.value.slice(1).toUpperCase())} />
      </div>
    </>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupParagraph, <>
      <div className="rb-row">
        <button type="button" className={`rb-icon${listKind === 'bullet' ? ' active' : ''}`} data-action="bullets" data-source-action="list-bullets-toggle" data-editable-action="true" disabled={!editable} title={zh.ribbonBullets} aria-label={zh.ribbonBullets} aria-pressed={listKind === 'bullet'} onClick={() => onList('bullet')}><IconBullets size={16} /></button>
        {bulletListControl ? <span ref={element => { if (element && bulletListControl.parentElement !== element) element.append(bulletListControl) }} /> : unavailableSourceAction('list-bullets-gallery', 'list-bullets-gallery', '项目符号库', '项目符号库预设、清除列表和自定义项目符号写回尚未接入')}
        <button type="button" className={`rb-icon${listKind === 'ordered' ? ' active' : ''}`} data-action="numbering" data-source-action="list-numbering-toggle" data-editable-action="true" disabled={!editable} title={zh.ribbonNumbering} aria-label={zh.ribbonNumbering} aria-pressed={listKind === 'ordered'} onClick={() => onList('ordered')}><IconNumbered size={16} /></button>
        {numberListControl ? <span ref={element => { if (element && numberListControl.parentElement !== element) element.append(numberListControl) }} /> : unavailableSourceAction('list-numbering-gallery', 'list-numbering-gallery', '编号库', '编号样式库、自定义编号及其重新开始配置写回尚未接入')}
        {multilevelListControl ? <span ref={element => { if (element && multilevelListControl.parentElement !== element) element.append(multilevelListControl) }} /> : unavailableSourceAction('list-multilevel-gallery', 'list-multilevel-gallery', '多级列表库', '多级样式库、自定义层级及级间重新开始规则写回尚未接入')}
        <select className="rb-select" data-action="list-level-picker" data-source-action="list-change-level" aria-label="列表级别" title="选择当前编号定义中可用的列表级别" disabled={!editable || !['bullet', 'ordered'].includes(String(listKind)) || !listLevelOptions?.some(Boolean)} value={String(listLevel ?? 0)} onChange={event => onListLevel?.(Number(event.currentTarget.value))}>
          {Array.from({ length: 9 }, (_, level) => <option key={level} value={level} disabled={!listLevelOptions?.[level]}>{level + 1}</option>)}
        </select>
        <button type="button" className="rb-icon docx-source-command" data-action="list-numbering-set-value" data-source-action="list-numbering-set-value" disabled={!editable || !onSetNumberingValue || !!numberingValueUnavailable} title={numberingValueUnavailable ? `设置编号值：${numberingValueUnavailable}` : '设置编号值'} aria-label={numberingValueUnavailable ? `设置编号值，${numberingValueUnavailable}` : '设置编号值'} onMouseDown={event => event.preventDefault()} onClick={onSetNumberingValue}><span>1</span></button>
        {action('indent-decrease', zh.ribbonDecreaseIndent, <IconIndentDec size={16} />, () => onIndent(-1), false, listKind === 'bullet' || listKind === 'ordered' ? listLevelDecreaseAvailable === true : Number(indentLeft) > 0, listKind === 'bullet' || listKind === 'ordered' ? '编号定义中没有兼容的上一级' : '段落已无可减少的缩进')}
        {action('indent-increase', zh.ribbonIncreaseIndent, <IconIndentInc size={16} />, () => onIndent(1), false, listKind === 'bullet' || listKind === 'ordered' ? listLevelIncreaseAvailable === true : Number(indentLeft) < 14400, listKind === 'bullet' || listKind === 'ordered' ? '编号定义中没有兼容的下一级' : '段落缩进已达到支持范围上限')}
      </div>
      <div className="rb-row">{action('align-left', zh.ribbonAlignLeftTip, <IconAlignLeft size={16} />, () => onAlignment('left'), alignment === 'left')}{action('align-center', zh.ribbonAlignCenterTip, <IconAlignCenter size={16} />, () => onAlignment('center'), alignment === 'center')}{action('align-right', zh.ribbonAlignRightTip, <IconAlignRight size={16} />, () => onAlignment('right'), alignment === 'right')}{action('align-justify', zh.ribbonJustifyTip, <IconAlignJustify size={16} />, () => onAlignment('justify'), alignment === 'justify')
        }{action('add-paragraph', '新增段落', <span>+</span>, () => onParagraph?.('add'), false, !!onParagraph)}{action('delete-paragraph', '删除段落', <span>−</span>, () => onParagraph?.('delete'), false, !!onParagraph)}</div>
      <button type="button" data-action="paragraph-options" disabled={!editable || !onParagraphOptions || !!paragraphOptionsUnavailable} title={paragraphOptionsUnavailable ?? '段落设置'} onMouseDown={event => event.preventDefault()} onClick={() => onParagraphOptions?.()}>段落…</button>
      <div className="rb-split-wrap" ref={spacingWrap}>
        <button type="button" className={`rb-icon${lineSpacing != null ? ' active' : ''}`} data-action="line-spacing" data-source-action="line-spacing-menu" data-editable-action="true" disabled={!editable} title={zh.ribbonLineSpacing} aria-label={zh.ribbonLineSpacing} aria-expanded={spacingOpen} onClick={() => setSpacingOpen(open => !open)}><IconLineSpacing size={16} /><IconCaret size={10} /></button>
        <div className="spacing-menu" data-rb-panel="" data-source-action="line-spacing-options-menu" hidden={!spacingOpen}>
          {([1, 1.15, 1.5, 2, 2.5, 3] as const).map(value => <button type="button" key={value} data-source-action={`line-spacing-${value}`} disabled={!editable} className={lineSpacing === value ? 'active' : ''} onClick={() => { onSpacing?.({ lineSpacing: value, lineRule: null, lineRawTwips: null }); setSpacingOpen(false) }}>{value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '.0')}</button>)}
          <button type="button" data-action="toggle-space-before" data-source-action="toggle-space-before" disabled={!editable} onClick={() => onSpacing?.({ spaceBefore: Number(spaceBefore) > 0 ? 0 : 240, spaceBeforeAuto: null })}>{Number(spaceBefore) > 0 ? '删除段前间距' : zh.ribbonAddSpaceBefore}</button>
          <button type="button" data-action="toggle-space-after" data-source-action="toggle-space-after" disabled={!editable} onClick={() => onSpacing?.({ spaceAfter: Number(spaceAfter) > 0 ? 0 : 240, spaceAfterAuto: null })}>{Number(spaceAfter) > 0 ? '删除段后间距' : zh.ribbonAddSpaceAfter}</button>
          <button type="button" data-action="line-spacing-options" data-source-action="line-spacing-options" disabled={!editable || !onLineSpacingOptions || !!lineSpacingUnavailable} title={lineSpacingUnavailable ?? zh.ribbonLineSpacingOptions} aria-label={zh.ribbonLineSpacingOptions} onMouseDown={event => event.preventDefault()} onClick={() => { setSpacingOpen(false); onLineSpacingOptions?.() }}>{zh.ribbonLineSpacingOptions}</button>
          <button type="button" data-action="special-indent-options" disabled={!editable || !onSpecialIndentOptions || !!specialIndentUnavailable} title={specialIndentUnavailable ?? '特殊缩进（首行／悬挂）'} aria-label="特殊缩进" onMouseDown={event => event.preventDefault()} onClick={() => { setSpacingOpen(false); onSpecialIndentOptions?.() }}>特殊缩进…</button>
        </div>
      </div>
      <div className="rb-split-wrap docx-ribbon-shading" ref={shadingWrap} onMouseDown={event => { if ((event.target as HTMLElement).closest('button')) event.preventDefault() }}>
        <button type="button" className={`rb-icon rb-color-btn${shading && shading !== 'none' && shading !== 'auto' ? ' active' : ''}`} data-action="shading" data-editable-action="true" disabled={!canShading} title={shadingTip} aria-label={shadingTip} onClick={() => onShading?.(shading === penShading ? 'none' : penShading)}>
          <span className="rb-color-glyph rb-color-glyph-svg"><IconShading size={17} /><span className="rb-color-bar" style={{ background: `#${penShading}` }} /></span>
        </button>
        <button type="button" className={`rb-caret rb-color-caret${shadingOpen ? ' active' : ''}`} data-action="shading-palette" disabled={!canShading} title={shadingTip} aria-label="段落底纹颜色选择" aria-expanded={shadingOpen && canShading} onClick={() => setShadingOpen(open => !open)}><IconCaret size={10} /></button>
        {shadingOpen && canShading && <div data-rb-panel="" className="color-palette docx-ribbon-shading-palette">
          <div className="color-section-title">{ribbonZh.ribbonParagraphShading}</div>
          <div className="color-highlight-grid">{DOCX_SHADING_COLORS.map(value => <button type="button" key={value} className={`color-swatch color-highlight-swatch${shading === value.toLowerCase() ? ' selected' : ''}`} data-action={`shading-${value}`} aria-label={value} aria-pressed={shading === value.toLowerCase()} title={`#${value}`} style={{ background: `#${value}` }} onClick={() => { setPenShading(value); onShading?.(value.toLowerCase()) }} />)}</div>
          <button type="button" className={`color-none color-highlight-none${shading == null || shading === 'none' ? ' selected' : ''}`} data-action="shading-none" onClick={() => onShading?.('none')}>{ribbonZh.ribbonNoColor}</button>
        </div>}
      </div>
      <div className="rb-split-wrap docx-ribbon-borders" ref={bordersWrap} onMouseDown={event => { if ((event.target as HTMLElement).closest('button')) event.preventDefault() }}>
        <button type="button" className={`rb-icon${bordersActive ? ' active' : ''}`} data-action="para-borders" data-editable-action="true" disabled={!canBorders} title={bordersTip} aria-label={bordersTip} onClick={() => applyPenBorders(penBorder)}>
          <span className="rb-color-glyph rb-color-glyph-svg"><IconBorderAll size={17} /><span className="rb-color-bar" style={{ background: penBorderColor ? `#${penBorderColor}` : 'transparent' }} /></span>
        </button>
        <button type="button" className={`rb-caret rb-color-caret${bordersOpen ? ' active' : ''}`} data-action="para-borders-menu" disabled={!canBorders} title={bordersTip} aria-label="段落边框位置、宽度和颜色" aria-expanded={bordersOpen && canBorders} onClick={() => setBordersOpen(open => !open)}><IconCaret size={10} /></button>
        {bordersOpen && canBorders && <div data-rb-panel="" className="spacing-menu docx-ribbon-borders-menu">
          <div className="rb-row">
            <button type="button" className={penBorder === 'bottom' ? 'active' : ''} data-action="para-border-bottom" title="下框线" onClick={() => { setPenBorder('bottom'); applyPenBorders('bottom') }}><IconBorderBottom size={16} /></button>
            <button type="button" className={penBorder === 'top' ? 'active' : ''} data-action="para-border-top" title="上框线" onClick={() => { setPenBorder('top'); applyPenBorders('top') }}><IconBorderTop size={16} /></button>
            <button type="button" className={penBorder === 'left' ? 'active' : ''} data-action="para-border-left" title="左框线" onClick={() => { setPenBorder('left'); applyPenBorders('left') }}><IconBorderLeft size={16} /></button>
            <button type="button" className={penBorder === 'right' ? 'active' : ''} data-action="para-border-right" title="右框线" onClick={() => { setPenBorder('right'); applyPenBorders('right') }}><IconBorderRight size={16} /></button>
            <button type="button" className={penBorder === 'tblr' ? 'active' : ''} data-action="para-border-box" title="所有框线" onClick={() => { setPenBorder('tblr'); applyPenBorders('tblr') }}><IconBorderAll size={16} /></button>
            <button type="button" data-action="para-border-none" title="无框线" onClick={() => { onBorders?.(null); setBordersOpen(false) }}><IconBorderNone size={16} /></button>
          </div>
          <div className="rb-row">
            {DOCX_BORDER_WIDTHS_PT.map(width => <button type="button" key={width} className={penBorderWidth === width ? 'active' : ''} data-action={`para-border-width-${width}`} title={`边框宽度 ${width}pt`} onClick={() => setPenBorderWidth(width)}>{width}pt</button>)}
          </div>
          <div className="color-highlight-grid">{DOCX_BORDER_COLORS.map(value => <button type="button" key={value} className={`color-swatch color-highlight-swatch${penBorderColor?.toUpperCase() === value ? ' selected' : ''}`} data-action={`para-border-color-${value}`} aria-label={value} aria-pressed={penBorderColor?.toUpperCase() === value} title={`#${value}`} style={{ background: `#${value}` }} onClick={() => setPenBorderColor(value)} />)}</div>
          <button type="button" className={`color-none color-highlight-none${penBorderColor == null ? ' selected' : ''}`} data-action="para-border-color-auto" onClick={() => setPenBorderColor(null)}>自动颜色</button>
        </div>}
      </div>
    </>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupStyles, paragraphStyleControl ? <div ref={element => { if (element && paragraphStyleControl.parentElement !== element) element.append(paragraphStyleControl) }} /> : <button type="button" className="rb-big" disabled title={unavailable}>{zh.ribbonStyleNormal}</button>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupEditing, <>{(['find', 'replace'] as const).map(mode => <button key={mode} type="button" className="rb-icon docx-source-command" data-action={mode} data-source-action={mode} disabled={!onFindReplace} onClick={() => onFindReplace?.(mode)}>{mode === 'find' ? <IconSearch /> : <IconReplace />}{mode === 'find' ? '查找' : '替换'}</button>)}<button type="button" className="rb-small" data-action="select" data-source-action="select" title={ribbonZh.ribbonSelectAllTip} disabled={!onSelectAll} onClick={() => onSelectAll?.()}><IconSelectAll />{ribbonZh.ribbonSelectAll}</button><button type="button" className={`rb-icon${formattingMarksVisible ? ' active' : ''}`} data-action="formatting-marks" aria-label="显示/隐藏编辑标记" title="显示/隐藏编辑标记" aria-pressed={!!formattingMarksVisible} disabled={!onToggleFormattingMarks} onClick={() => onToggleFormattingMarks?.()}><IconPilcrow /></button></>)}
    {group('转换', <><button type="button" className="rb-icon" data-action="convert-pdf" disabled={!onExport || !editable} title="转换为 PDF" onClick={()=>onExport?.('pdf')}><IconConvert/><span>PDF</span></button><button type="button" className="rb-icon" data-action="convert-html" disabled={!onExport} title="转换为 HTML" onClick={()=>onExport?.('html')}><IconConvert/><span>HTML</span></button><button type="button" className="rb-icon" data-action="convert-markdown" disabled={!onExport} title="转换为 Markdown" onClick={()=>onExport?.('markdown')}><IconConvert/><span>MD</span></button>{disabled('export-images', '导出图像', <><IconPicture /><span>IMG</span></>)}</>)}
    <div className="ribbon-sep" />
  </div>
}
import type { ReactNode } from 'react'
