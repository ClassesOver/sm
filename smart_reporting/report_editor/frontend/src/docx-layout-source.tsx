import { useLayoutEffect, useState } from 'react'
import type { SectionSettings } from '@genoffice/docx-engine'
import { type SectionChangeResult, type SectionValues } from './docx-operations'
import { MarginDialog } from './docx-margin-dialog'
import { PaperSizeDialog } from './docx-paper-size-dialog'
import { MARGIN_PRESETS, marginsFitPage, paperSizeInRange, readLastCustomMargins, rememberCustomMargins, type PageMargins } from './docx-page-setup'
import { DocxPageNumberDialog } from './docx-page-number-dialog'
import { IconCaret, IconColumns, IconMargins, IconOrientation, IconPageSize, IconPageBreak, IconHeader, IconPageNumber } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'

type Values = SectionValues
type BreakType = 'nextPage' | 'continuous' | 'evenPage' | 'oddPage'
type Props = { mirrorMargins?: boolean; mirrorMarginsReason?: string; onMirrorMargins?: (on: boolean, values?: Values) => SectionChangeResult; onPaperSizeAll?: (width: number, height: number, orientation: 'portrait' | 'landscape') => SectionChangeResult; pageNumberFmt?: string | null; pageNumberStart?: number | null; pageNumberReason?: string; editable: boolean; settings: SectionSettings | null; titlePg?: boolean | null; titlePgReason?: string; evenAndOddHeaders?: boolean | null; evenAndOddHeadersReason?: string; onChange: (values: Values) => SectionChangeResult; onEditHeaderFooter?: () => void; sectionLabel?: string; onSectionBreak?: (type: BreakType) => void }

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

export function DocxLayoutSource({ mirrorMargins, mirrorMarginsReason, onMirrorMargins, onPaperSizeAll, pageNumberFmt, pageNumberStart, pageNumberReason, editable, settings: initialSettings, titlePg, titlePgReason, evenAndOddHeaders, evenAndOddHeadersReason, onChange, onEditHeaderFooter, sectionLabel, onSectionBreak }: Props) {
  const [settings, setSettings] = useState(initialSettings)
  useLayoutEffect(() => { setSettings(initialSettings) }, [initialSettings])
  const [pageNumberOpen, setPageNumberOpen] = useState(false)
  useLayoutEffect(() => { setPageNumberOpen(false) }, [sectionLabel])
  const numberReason = pageNumberReason ?? (pageNumberFmt === undefined || pageNumberStart === undefined ? '页码格式来源状态不可判定' : undefined)
  const [setupDialog, setSetupDialog] = useState<'margins' | 'paper' | null>(null)
  useLayoutEffect(() => { setSetupDialog(null) }, [sectionLabel, initialSettings])
  const [customPaper, setCustomPaper] = useState(false)
  useLayoutEffect(() => { setCustomPaper(false) }, [sectionLabel])
  const paperKey = settings ? paperSizes.find(size => Math.abs(size.w - Math.min(settings.pageWidth, settings.pageHeight)) <= 2 && Math.abs(size.h - Math.max(settings.pageWidth, settings.pageHeight)) <= 2)?.key : undefined
  const isCustomPaper = customPaper || !paperKey
  const currentMargins = settings ? { top:settings.marginTop,right:settings.marginRight,bottom:settings.marginBottom,left:settings.marginLeft } : null
  const lastCustom = readLastCustomMargins()
  const usableLastCustom = lastCustom && settings && marginsFitPage(lastCustom,settings.pageWidth,settings.pageHeight) ? lastCustom : null
  const matchingPreset = currentMargins && MARGIN_PRESETS.find(m => (m.key === 'mirrored') === (mirrorMargins === true) && ['top','right','bottom','left'].every(side => m[side as keyof PageMargins] === currentMargins[side as keyof PageMargins]))
  const marginPreset = matchingPreset?.key ?? 'custom'
  const [setupError, setSetupError] = useState('')
  const change = (values: Values): SectionChangeResult => {
    const fail = (error:string) => { setSetupError(error); return {error} }
    if (!editable || !settings) return fail('当前文档不可编辑或正在保存')
    const next = { ...settings, ...values } as SectionSettings
    if (!paperSizeInRange(next.pageWidth,next.pageHeight)) return fail('纸张宽度和高度须为 144–31680 twip')
    if (['marginTop','marginRight','marginBottom','marginLeft','pageWidth','pageHeight'].some(k => k in values) && !marginsFitPage({top:next.marginTop,right:next.marginRight,bottom:next.marginBottom,left:next.marginLeft},next.pageWidth,next.pageHeight)) return fail('页边距必须为有效整数，并至少保留一英寸正文空间')
    if (['headerDist','footerDist'].some(k => k in values && (!Number.isSafeInteger(values[k as keyof Values]) || Number(values[k as keyof Values]) < 0 || Number(values[k as keyof Values]) > 31680))) return fail('页眉页脚距离须为 0–31680 twip')
    try {
      const result = onChange(values)
      if (result?.error) return fail(result.error)
      setSettings(next); setSetupError('')
      return result
    } catch(e) { return fail(e instanceof Error ? e.message : String(e)) }
  }
  const applyMargins = (m:PageMargins, mirror:boolean) => {
    if (!editable || !settings) throw new Error('当前文档不可编辑或正在保存')
    if (!marginsFitPage(m,settings.pageWidth,settings.pageHeight)) throw new Error('页边距至少需保留一英寸正文空间')
    const values:Values = {marginTop:m.top,marginRight:m.right,marginBottom:m.bottom,marginLeft:m.left}
    if (mirror !== (mirrorMargins === true)) {
      if (!onMirrorMargins || mirrorMarginsReason || mirrorMargins === undefined) throw new Error(mirrorMarginsReason ?? '镜像页边距来源状态不可判定或尚未接入')
      const result=onMirrorMargins(mirror, values)
      if (result?.error) throw new Error(result.error)
      setSettings({...settings,...values} as SectionSettings)
    } else { const result=change(values); if(result?.error) throw new Error(result.error) }
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
    {setupError && <p role="alert">{setupError}</p>}
    {setupDialog==='margins' && settings && currentMargins ? <MarginDialog margins={currentMargins} mirror={mirrorMargins===true} pageWidth={settings.pageWidth} pageHeight={settings.pageHeight} disabledReason={sectionDisabled?'当前文档不可编辑或正在保存':undefined} mirrorReason={mirrorMarginsReason ?? (!onMirrorMargins || mirrorMargins===undefined ? '镜像页边距尚未接入' : undefined)} onApply={(m,mirror)=>{applyMargins(m,mirror);rememberCustomMargins(m)}} onClose={()=>setSetupDialog(null)}/> : null}
    {setupDialog==='paper' && settings ? <PaperSizeDialog section={settings} multiSection={!!sectionLabel} disabledReason={sectionDisabled?'当前文档不可编辑或正在保存':undefined} documentReason={onPaperSizeAll?undefined:'整篇文档纸张设置尚未接入'} onApply={(w,h,scope)=>{
      if(!editable)throw new Error('当前文档不可编辑或正在保存')
      const orientation=w===h?settings.orientation:w>h?'landscape':'portrait'
      const result=scope==='document'?onPaperSizeAll?.(Math.min(w,h),Math.max(w,h),orientation):change({pageWidth:w,pageHeight:h,orientation})
      if(scope==='document'&&!onPaperSizeAll)throw new Error('整篇文档纸张设置尚未接入')
      if(result?.error)throw new Error(result.error)
    }} onClose={()=>setSetupDialog(null)}/> : null}
    {group('页面设置', <>
      <label className="layout-num"><IconMargins size={18} /><span>页边距</span><select data-source-action="layout-margins" aria-label="页边距" value={marginPreset} disabled={sectionDisabled} onChange={event => {
        const key=event.currentTarget.value
        if(key==='custom') { setSetupDialog('margins'); return }
        const preset=key==='lastCustom'?usableLastCustom:MARGIN_PRESETS.find(m=>m.key===key)
        if(!preset)return
        try { applyMargins(preset,key==='mirrored'); setSetupError('') } catch(e) { setSetupError(e instanceof Error?e.message:String(e)) }
      }}>{usableLastCustom && <option value="lastCustom">上次自定义设置</option>}{MARGIN_PRESETS.map(m=><option key={m.key} value={m.key} disabled={!settings || !marginsFitPage(m,settings.pageWidth,settings.pageHeight) || (m.key==='mirrored' && (!onMirrorMargins || !!mirrorMarginsReason || mirrorMargins===undefined))}>{m.name}</option>)}<option value="custom">自定义</option></select></label>
      <button type="button" data-source-action="layout-custom-margins" disabled={sectionDisabled} onClick={()=>setSetupDialog('margins')}>自定义页边距…</button>
      <label className="layout-num"><IconOrientation size={18} /><span>纸张方向</span><select data-source-action="layout-orientation" aria-label="纸张方向" value={settings?.orientation ?? 'portrait'} disabled={sectionDisabled} onChange={event => orientationChange(event.currentTarget.value as 'portrait' | 'landscape')}><option value="portrait">纵向</option><option value="landscape">横向</option></select></label>
      <label className="layout-num"><IconPageSize size={18} /><span>纸张大小</span><select data-source-action="layout-paper-size" aria-label="纸张大小" value={isCustomPaper ? 'custom' : paperKey} disabled={sectionDisabled} onChange={event => {
        if (event.currentTarget.value === 'custom') { setCustomPaper(true); return }
        setCustomPaper(false)
        if (!settings) return
        const size = paperSizes.find(item => item.key === event.currentTarget.value)!
        change({ pageWidth: settings.orientation === 'portrait' ? size.w : size.h, pageHeight: settings.orientation === 'portrait' ? size.h : size.w })
      }}>{paperSizes.map(size => <option key={size.key} value={size.key}>{size.name}</option>)}<option value="custom">自定义</option></select></label>
      <button type="button" data-source-action="layout-more-paper-sizes" disabled={sectionDisabled} onClick={()=>setSetupDialog('paper')}>其他纸张大小…</button>
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
