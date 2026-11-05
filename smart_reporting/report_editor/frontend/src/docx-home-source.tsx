import {
  IconAlignCenter, IconAlignJustify, IconAlignLeft, IconAlignRight, IconBullets,
  IconChangeCase, IconClearFormat, IconCopy, IconCut, IconFormatPainter,
  IconFontColorA, IconGrowFont, IconHighlight, IconIndentDec, IconIndentInc, IconLineSpacing,
  IconNumbered, IconPaste, IconShrinkFont, IconSubscript, IconSuperscript, IconCaret,
} from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { useRef, useState } from 'react'
import { useDismissablePopover } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
import { homeRibbonZh as zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/home-zh'

type Props = {
  editable: boolean
  onMark: (name: 'bold' | 'italic' | 'underline' | 'strike') => void
  onFontSize: (delta: number) => void
  onFontFamily: (value: string) => void
  onFontSizeValue: (value: number) => void
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
  onParagraph?: (command: 'add' | 'delete') => void
  onUnavailable?: (reason: string) => void
}

const unavailable = '原版控件保留；当前 DOCX 原生操作协议未支持此命令'

/**
 * Browser extraction of GenOffice Ribbon.tsx's Home branch (fixed source SHA
 * recorded in SOURCE-SHA256.json). Its App callbacks are replaced by Native
 * Tiptap/DOCX operations; unsupported commands remain visible and disabled.
 */
export function DocxHomeSource({ editable, onMark, onFontSize, onFontFamily, onFontSizeValue, onColor, onAlignment, onIndent, alignment, indentLeft, onList, listKind, listLevelDecreaseAvailable, listLevelIncreaseAvailable, listLevelOptions, listLevel, onListLevel, spaceBefore, spaceAfter, lineSpacing, onSpacing, onParagraph }: Props) {
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
    <div className="ribbon-group"><div className="ribbon-group-items">{children}</div><div className="ribbon-group-label">{key}</div></div>
  )
  return <div className="ribbon-content docx-source-home">
    {group('Genspark AI', <button type="button" className="rb-big ai-entry" disabled title={unavailable}>Genspark AI</button>)}
    <div className="ribbon-sep" />
    {group('转换', <>{disabled('convert-pdf', '转换为 PDF', <span>PDF</span>)}{disabled('convert-html', '转换为 HTML', <span>HTML</span>)}{disabled('convert-markdown', '转换为 Markdown', <span>MD</span>)}{disabled('export-images', '导出图像', <span>IMG</span>)}</>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupClipboard, <>
      {disabled('paste', zh.ribbonPaste, <IconPaste size={28} />)}
      {disabled('cut', zh.ribbonCutTip, <IconCut size={17} />)}
      {disabled('copy', zh.ribbonCopyTip, <IconCopy size={17} />)}
      {disabled('format-painter', zh.ribbonPainterTip, <IconFormatPainter size={17} />)}
    </>)}
    <div className="ribbon-sep" />
    {group('字体', <>
      <div className="rb-row">
        <input className="rb-select rb-font-family" data-action="font-family" data-editable-action="true" aria-label={zh.ribbonFontFamilyTip} placeholder={zh.ribbonFontFamilyTip} disabled={!editable}
          onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); onFontFamily(event.currentTarget.value.trim()) } }} />
        <input className="rb-select rb-font-size" data-action="font-size" data-editable-action="true" type="number" min="1" max="200" step="0.5" defaultValue="12" aria-label={zh.ribbonFontSizeTip} disabled={!editable}
          onInput={event => { const value = Number(event.currentTarget.value); if (value >= 1 && value <= 200 && Number.isInteger(value * 2)) onFontSizeValue(value) }} />
        {action('grow-font', zh.ribbonGrowFont, <IconGrowFont size={17} />, () => onFontSize(1))}
        {action('shrink-font', zh.ribbonShrinkFont, <IconShrinkFont size={17} />, () => onFontSize(-1))}
        {disabled('change-case', zh.ribbonChangeCase, <IconChangeCase size={17} />)}{disabled('clear-formatting', zh.ribbonClearFormatting, <IconClearFormat size={17} />)}
      </div>
      <div className="rb-row">
        {action('bold', zh.ribbonBoldTip, <b>B</b>, () => onMark('bold'))}
        {action('italic', zh.ribbonItalicTip, <i>I</i>, () => onMark('italic'))}
        {action('underline', zh.ribbonUnderlineTip, <u>U</u>, () => onMark('underline'))}
        {action('strike', zh.ribbonStrikethrough, <s>ab</s>, () => onMark('strike'))}
        {disabled('subscript', zh.ribbonSubscript, <IconSubscript size={17} />)}{disabled('superscript', zh.ribbonSuperscript, <IconSuperscript size={17} />)}
        {disabled('highlight', zh.ribbonTextHighlightColor, <IconHighlight size={17} />)}
        <input className="rb-color-input" data-action="font-color" data-editable-action="true" type="color" aria-label={zh.ribbonFontColor} title={zh.ribbonFontColor} disabled={!editable} onInput={event => onColor(event.currentTarget.value.slice(1).toUpperCase())} />
      </div>
    </>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupParagraph, <>
      <div className="rb-row">
        <button type="button" className={`rb-icon${listKind === 'bullet' ? ' active' : ''}`} data-action="bullets" data-source-action="list-bullets-toggle" data-editable-action="true" disabled={!editable} title={zh.ribbonBullets} aria-label={zh.ribbonBullets} aria-pressed={listKind === 'bullet'} onClick={() => onList('bullet')}><IconBullets size={16} /></button>
        {unavailableSourceAction('list-bullets-gallery', 'list-bullets-gallery', '项目符号库', '项目符号库预设、清除列表和自定义项目符号写回尚未接入')}
        <button type="button" className={`rb-icon${listKind === 'ordered' ? ' active' : ''}`} data-action="numbering" data-source-action="list-numbering-toggle" data-editable-action="true" disabled={!editable} title={zh.ribbonNumbering} aria-label={zh.ribbonNumbering} aria-pressed={listKind === 'ordered'} onClick={() => onList('ordered')}><IconNumbered size={16} /></button>
        {unavailableSourceAction('list-numbering-gallery', 'list-numbering-gallery', '编号库', '编号样式库、自定义编号及其重新开始配置写回尚未接入')}
        {unavailableSourceAction('list-multilevel-gallery', 'list-multilevel-gallery', '多级列表库', '多级样式库、自定义层级及级间重新开始规则写回尚未接入')}
        <select className="rb-select" data-action="list-level-picker" data-source-action="list-change-level" aria-label="列表级别" title="选择当前编号定义中可用的列表级别" disabled={!editable || !['bullet', 'ordered'].includes(String(listKind)) || !listLevelOptions?.some(Boolean)} value={String(listLevel ?? 0)} onChange={event => onListLevel?.(Number(event.currentTarget.value))}>
          {Array.from({ length: 9 }, (_, level) => <option key={level} value={level} disabled={!listLevelOptions?.[level]}>{level + 1}</option>)}
        </select>
        <button type="button" className="rb-icon docx-source-command" data-action="list-numbering-set-value" data-source-action="list-numbering-set-value" disabled title="设置编号值：起始编号、重新开始和继续列表写回尚未接入" aria-label="设置编号值，起始编号、重新开始和继续列表写回尚未接入"><span>1</span></button>
        {action('indent-decrease', zh.ribbonDecreaseIndent, <IconIndentDec size={16} />, () => onIndent(-1), false, listKind === 'bullet' || listKind === 'ordered' ? listLevelDecreaseAvailable === true : Number(indentLeft) > 0, listKind === 'bullet' || listKind === 'ordered' ? '编号定义中没有兼容的上一级' : '段落已无可减少的缩进')}
        {action('indent-increase', zh.ribbonIncreaseIndent, <IconIndentInc size={16} />, () => onIndent(1), false, listKind === 'bullet' || listKind === 'ordered' ? listLevelIncreaseAvailable === true : Number(indentLeft) < 14400, listKind === 'bullet' || listKind === 'ordered' ? '编号定义中没有兼容的下一级' : '段落缩进已达到支持范围上限')}
      </div>
      <div className="rb-row">{action('align-left', zh.ribbonAlignLeftTip, <IconAlignLeft size={16} />, () => onAlignment('left'), alignment === 'left')}{action('align-center', zh.ribbonAlignCenterTip, <IconAlignCenter size={16} />, () => onAlignment('center'), alignment === 'center')}{action('align-right', zh.ribbonAlignRightTip, <IconAlignRight size={16} />, () => onAlignment('right'), alignment === 'right')}{action('align-justify', zh.ribbonJustifyTip, <IconAlignJustify size={16} />, () => onAlignment('justify'), alignment === 'justify')
        }{action('add-paragraph', '新增段落', <span>+</span>, () => onParagraph?.('add'), false, !!onParagraph)}{action('delete-paragraph', '删除段落', <span>−</span>, () => onParagraph?.('delete'), false, !!onParagraph)}</div>
      <div className="rb-split-wrap" ref={spacingWrap}>
        <button type="button" className={`rb-icon${lineSpacing != null ? ' active' : ''}`} data-action="line-spacing" data-source-action="line-spacing-menu" data-editable-action="true" disabled={!editable} title={zh.ribbonLineSpacing} aria-label={zh.ribbonLineSpacing} aria-expanded={spacingOpen} onClick={() => setSpacingOpen(open => !open)}><IconLineSpacing size={16} /><IconCaret size={10} /></button>
        <div className="spacing-menu" data-rb-panel="" data-source-action="line-spacing-options-menu" hidden={!spacingOpen}>
          {([1, 1.15, 1.5, 2, 2.5, 3] as const).map(value => <button type="button" key={value} data-source-action={`line-spacing-${value}`} disabled={!editable} className={lineSpacing === value ? 'active' : ''} onClick={() => { onSpacing?.({ lineSpacing: value, lineRule: null, lineRawTwips: null }); setSpacingOpen(false) }}>{value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '.0')}</button>)}
          <button type="button" data-action="toggle-space-before" data-source-action="toggle-space-before" disabled={!editable} onClick={() => onSpacing?.({ spaceBefore: Number(spaceBefore) > 0 ? 0 : 240, spaceBeforeAuto: null })}>{Number(spaceBefore) > 0 ? '删除段前间距' : zh.ribbonAddSpaceBefore}</button>
          <button type="button" data-action="toggle-space-after" data-source-action="toggle-space-after" disabled={!editable} onClick={() => onSpacing?.({ spaceAfter: Number(spaceAfter) > 0 ? 0 : 240, spaceAfterAuto: null })}>{Number(spaceAfter) > 0 ? '删除段后间距' : zh.ribbonAddSpaceAfter}</button>
          <button type="button" data-action="line-spacing-options" data-source-action="line-spacing-options" disabled title={`${zh.ribbonLineSpacingOptions}：精确行距、段落对话框与其他行距单位尚未接入`} aria-label={`${zh.ribbonLineSpacingOptions}，精确行距、段落对话框与其他行距单位尚未接入`}>{zh.ribbonLineSpacingOptions}</button>
        </div>
      </div>
    </>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupStyles, <button type="button" className="rb-big" disabled title={unavailable}>{zh.ribbonStyleNormal}</button>)}
    <div className="ribbon-sep" />
    {group(zh.ribbonGroupEditing, <>{disabled('find', '查找', <span>查找</span>)}{disabled('replace', '替换', <span>替换</span>)}{disabled('select', '选择', <span>选择</span>)}</>)}
  </div>
}
import type { ReactNode } from 'react'
