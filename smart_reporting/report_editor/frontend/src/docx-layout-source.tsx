import { useLayoutEffect, useState } from 'react'
import type { SectionSettings } from '@genoffice/docx-engine'
import { type SectionChangeResult, type SectionValues } from './docx-operations'
import { DocxPageNumberDialog } from './docx-page-number-dialog'
import { IconCaret, IconColumns, IconMargins, IconOrientation, IconPageSize, IconPageBreak, IconHeader, IconPageNumber } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'

type Values = SectionValues
type BreakType = 'nextPage' | 'continuous' | 'evenPage' | 'oddPage'
type Props = { pageNumberFmt?: string | null; pageNumberStart?: number | null; pageNumberReason?: string; editable: boolean; settings: SectionSettings | null; titlePg?: boolean | null; titlePgReason?: string; evenAndOddHeaders?: boolean | null; evenAndOddHeadersReason?: string; onChange: (values: Values) => SectionChangeResult; onEditHeaderFooter?: () => void; sectionLabel?: string; onSectionBreak?: (type: BreakType) => void }

// 固定源 ribbon-layout-tab.tsx PAPER_SIZES：纵向 twip，保留 Word 画廊顺序。
const paperSizes = [
  { key: 'letter', name: 'Letter', w: 12240, h: 15840 },
  { key: 'legal', name: 'Legal', w: 12240, h: 20160 },
  { key: 'executive', name: 'Executive', w: 10440, h: 15120 },
  { key: 'a3', name: 'A3', w: 16838, h: 23811 },
  { key: 'a4', name: 'A4', w: 11906, h: 16838 },
  { key: 'a5', name: 'A5', w: 8391, h: 11906 },
  { key: 'b4', name: 'B4 (JIS)', w: 14572, h: 20639 },
  { key: 'b5', name: 'B5 (JIS)', w: 10319, h: 14572 },
  { key: 'tabloid', name: 'Tabloid', w: 15840, h: 24480 },
  { key: 'statement', name: 'Statement', w: 7920, h: 12240 },
  { key: 'env10', name: 'Envelope #10', w: 5940, h: 13680 },
  { key: 'envdl', name: 'Envelope DL', w: 6237, h: 12474 },
  { key: 'envc5', name: 'Envelope C5', w: 9185, h: 12983 },
] as const
const unavailable = 'DOCX 原生 section 操作未覆盖此源命令'

export function DocxLayoutSource({ pageNumberFmt, pageNumberStart, pageNumberReason, editable, settings: initialSettings, titlePg, titlePgReason, evenAndOddHeaders, evenAndOddHeadersReason, onChange, onEditHeaderFooter, sectionLabel, onSectionBreak }: Props) {
  const [settings, setSettings] = useState(initialSettings)
  useLayoutEffect(() => { setSettings(initialSettings) }, [initialSettings])
  const [pageNumberOpen, setPageNumberOpen] = useState(false)
  useLayoutEffect(() => { setPageNumberOpen(false) }, [sectionLabel])
  const numberReason = pageNumberReason ?? (pageNumberFmt === undefined || pageNumberStart === undefined ? '页码格式来源状态不可判定' : undefined)
  const [customPaper, setCustomPaper] = useState(false)
  useLayoutEffect(() => { setCustomPaper(false) }, [sectionLabel])
  const paperKey = settings ? paperSizes.find(size => Math.abs(size.w - Math.min(settings.pageWidth, settings.pageHeight)) <= 2 && Math.abs(size.h - Math.max(settings.pageWidth, settings.pageHeight)) <= 2)?.key : undefined
  const isCustomPaper = customPaper || !paperKey
  const marginPreset = settings && settings.marginTop === 1440 && settings.marginBottom === 1440 && settings.marginLeft === 2880 && settings.marginRight === 2880 ? 'wide'
    : settings && [settings.marginRight, settings.marginBottom, settings.marginLeft].every(value => value === settings.marginTop) && [720, 1440].includes(settings.marginTop) ? settings.marginTop : 'custom'
  const change = (values: Values) => {
    if (!editable || !settings) return { error: '当前文档不可编辑或正在保存' }
    setSettings(current => current ? { ...current, ...values } as SectionSettings : current)
    return onChange(values)
  }
  const source = (id: string, label: string, reason: string) => <button type="button" className="rb-icon docx-source-command" data-source-action={id} disabled title={`${label}：${reason}`} aria-label={`${label}，${reason}`}><IconCaret size={10} /></button>
  const sectionDisabled = !editable || !settings
  const field = (id: string, label: string, value: number | undefined, onCommit: (value: number) => void) => <label className="layout-num"><span>{label}</span><input type="number" data-source-action={id} aria-label={label} value={value ?? 0} disabled={sectionDisabled} onChange={event => onCommit(Number(event.currentTarget.value))} /><span className="layout-unit">twip</span></label>
  const group = (label: string, children: React.ReactNode) => <section className="ribbon-group docx-ribbon-group" aria-label={label}><div className="ribbon-group-items">{children}</div><div className="ribbon-group-label">{label}</div></section>
  const orientationChange = (orientation: 'portrait' | 'landscape') => {
    if (!settings) return
    const width = Math.min(settings.pageWidth, settings.pageHeight), height = Math.max(settings.pageWidth, settings.pageHeight)
    change({ orientation, pageWidth: orientation === 'portrait' ? width : height, pageHeight: orientation === 'portrait' ? height : width })
  }
  return <div className="ribbon-content docx-source-layout">
    {group('页面设置', <>
      <label className="layout-num"><IconMargins size={18} /><span>页边距</span><select data-source-action="layout-margins" aria-label="页边距" value={marginPreset} disabled={sectionDisabled} onChange={event => {
        if (event.currentTarget.value === 'wide') { change({ marginTop: 1440, marginRight: 2880, marginBottom: 1440, marginLeft: 2880 }); return }
        const value = Number(event.currentTarget.value)
        change({ marginTop: value, marginRight: value, marginBottom: value, marginLeft: value })
      }}><option value="1440">普通</option><option value="720">窄</option><option value="wide">宽</option><option value="custom" disabled>自定义</option></select></label>
      <label className="layout-num"><IconOrientation size={18} /><span>纸张方向</span><select data-source-action="layout-orientation" aria-label="纸张方向" value={settings?.orientation ?? 'portrait'} disabled={sectionDisabled} onChange={event => orientationChange(event.currentTarget.value as 'portrait' | 'landscape')}><option value="portrait">纵向</option><option value="landscape">横向</option></select></label>
      <label className="layout-num"><IconPageSize size={18} /><span>纸张大小</span><select data-source-action="layout-paper-size" aria-label="纸张大小" value={isCustomPaper ? 'custom' : paperKey} disabled={sectionDisabled} onChange={event => {
        if (event.currentTarget.value === 'custom') { setCustomPaper(true); return }
        setCustomPaper(false)
        if (!settings) return
        const size = paperSizes.find(item => item.key === event.currentTarget.value)!
        change({ pageWidth: settings.orientation === 'portrait' ? size.w : size.h, pageHeight: settings.orientation === 'portrait' ? size.h : size.w })
      }}>{paperSizes.map(size => <option key={size.key} value={size.key}>{size.name}</option>)}<option value="custom">自定义</option></select></label>
      <label className="layout-num"><IconColumns size={18} /><span>分栏</span><select data-source-action="layout-columns" aria-label="分栏" value={settings?.columns ?? 1} disabled={sectionDisabled} onChange={event => change({ columns: Number(event.currentTarget.value) as 1 | 2 | 3 })}><option value="1">一栏</option><option value="2">两栏</option><option value="3">三栏</option></select></label>
      <label className="layout-num"><span>自定义宽度</span><input type="number" data-source-action="layout-custom-page-width" aria-label="自定义纸张宽度" value={settings?.pageWidth ?? 0} disabled={sectionDisabled || !isCustomPaper} onChange={event => change({ pageWidth: Number(event.currentTarget.value) })} /><span className="layout-unit">twip</span></label>
      <label className="layout-num"><span>自定义高度</span><input type="number" data-source-action="layout-custom-page-height" aria-label="自定义纸张高度" value={settings?.pageHeight ?? 0} disabled={sectionDisabled || !isCustomPaper} onChange={event => change({ pageHeight: Number(event.currentTarget.value) })} /><span className="layout-unit">twip</span></label>
      {field('layout-margin-top', '上边距', settings?.marginTop, value => change({ marginTop: value }))}
      {field('layout-margin-right', '右边距', settings?.marginRight, value => change({ marginRight: value }))}
      {field('layout-margin-bottom', '下边距', settings?.marginBottom, value => change({ marginBottom: value }))}
      {field('layout-margin-left', '左边距', settings?.marginLeft, value => change({ marginLeft: value }))}
      {field('layout-header-distance', '页眉距顶端', settings?.headerDist, value => change({ headerDist: value }))}
      {field('layout-footer-distance', '页脚距底端', settings?.footerDist, value => change({ footerDist: value }))}
      {sectionLabel ? <span className="layout-num" data-source-action="layout-section-label">{sectionLabel}</span> : null}
      {([['layout-section-break-page', '下一页分节符', 'nextPage'], ['layout-section-break-continuous', '连续分节符', 'continuous'],
        ['layout-section-break-even', '偶数页分节符', 'evenPage'], ['layout-section-break-odd', '奇数页分节符', 'oddPage']] as const).map(([id, label, type]) => onSectionBreak
        ? <button key={id} type="button" className="rb-icon docx-source-command" data-source-action={id} disabled={!editable} title={`${label}：在光标所在段落后插入，此前内容成为新的一节`} aria-label={label} onClick={() => onSectionBreak(type)}><IconPageBreak size={16} />{label}</button>
        : <span key={id}>{source(id, label, '分节符插入及多节 section 写回尚未接入')}</span>)}
    </>)}
    {group('页眉和页脚', <>
      {onEditHeaderFooter
        ? <button type="button" className="rb-icon docx-source-command" data-source-action="header-edit" disabled={!editable} onClick={onEditHeaderFooter} aria-label="编辑页眉或页脚"><IconHeader size={16} />编辑页眉/页脚</button>
        : source('header-edit', '编辑页眉', '页眉/页脚 part 编辑写回尚未接入')}
      {source('header-remove', '删除页眉', '页眉/页脚 part 删除与关系写回尚未接入')}
      {source('footer-remove', '删除页脚', '页眉/页脚 part 删除与关系写回尚未接入')}
      {source('page-number', '页码', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-top-left', '页码置于页眉左侧', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-top-center', '页码置于页眉居中', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-top-right', '页码置于页眉右侧', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-bottom-left', '页码置于页脚左侧', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-bottom-center', '页码置于页脚居中', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-bottom-right', '页码置于页脚右侧', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('page-number-current-position', '当前位置页码', '页码字段写回尚未接入')}
      {source('page-number-total-pages', '总页数', '页码字段写回尚未接入')}
      <button type="button" className="rb-icon docx-source-command" data-source-action="page-number-format" aria-label="页码格式" title={numberReason ?? '设置当前节的页码格式和起始页码'} disabled={sectionDisabled || !!numberReason} onMouseDown={event => event.preventDefault()} onClick={() => { setPageNumberOpen(true) }}><IconPageNumber size={16} />页码格式</button>
      {pageNumberOpen ? <DocxPageNumberDialog format={pageNumberFmt} start={pageNumberStart} label={sectionLabel} disabledReason={!editable ? '当前文档不可编辑或正在保存' : !settings ? '当前节设置不可用' : numberReason} onChange={change} onClose={() => setPageNumberOpen(false)} /> : null}
      {source('page-number-remove', '删除页码', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('header-datetime', '日期和时间', '页眉/页脚字段写回尚未接入')}
      {source('header-date', '插入日期', '页眉/页脚字段写回尚未接入')}
      {source('header-time', '插入时间', '页眉/页脚字段写回尚未接入')}
      {source('header-document-info', '文档信息', '页眉/页脚字段写回尚未接入')}
      {source('header-picture', '页眉/页脚图片', '页眉/页脚图片与关系写回尚未接入')}
      {source('header-goto', '转到页眉或页脚', '页眉/页脚编辑会话尚未接入')}
      {source('header-section-navigation', '上一节或下一节', '分节导航与 section 编辑尚未接入')}
      {source('header-link-previous', '链接到前一节', '分节页眉/页脚关系写回尚未接入')}
      <label className="layout-num"><input type="checkbox" data-source-action="header-title-page" aria-label="首页不同"
        ref={input => { if (input) input.indeterminate = typeof titlePg !== 'boolean' }} checked={titlePg === true}
        disabled={sectionDisabled || typeof titlePg !== 'boolean' || !!titlePgReason}
        title={titlePgReason ?? (typeof titlePg !== 'boolean' ? '首页不同的来源状态不可判定' : '仅作用于当前节，保留页眉和页脚内容')}
        onMouseDown={event => event.preventDefault()}
        onChange={event => change({ titlePg: event.currentTarget.checked })} /><span>首页不同</span></label>
      <label className="layout-num"><input type="checkbox" data-source-action="header-even-odd" aria-label="奇偶页不同"
        ref={input => { if (input) input.indeterminate = typeof evenAndOddHeaders !== 'boolean' }} checked={evenAndOddHeaders === true}
        disabled={!editable || typeof evenAndOddHeaders !== 'boolean' || !!evenAndOddHeadersReason}
        title={evenAndOddHeadersReason ?? (typeof evenAndOddHeaders !== 'boolean' ? '奇偶页不同的来源状态不可判定' : '作用于整篇文档，保留全部页眉和页脚内容')}
        onMouseDown={event => event.preventDefault()}
        onChange={event => { if (editable) onChange({ evenAndOddHeaders: event.currentTarget.checked }) }} /><span>奇偶页不同</span></label>
      {source('header-show-document-text', '显示文档文字', '页眉/页脚编辑视图尚未接入')}
      {field('header-distance', '页眉距顶端', settings?.headerDist, value => change({ headerDist: value }))}
      {field('footer-distance', '页脚距底端', settings?.footerDist, value => change({ footerDist: value }))}
      {source('header-close', '关闭页眉和页脚', '页眉/页脚编辑会话尚未接入')}
      <span className="sr-only">{unavailable}</span>
    </>)}
  </div>
}
