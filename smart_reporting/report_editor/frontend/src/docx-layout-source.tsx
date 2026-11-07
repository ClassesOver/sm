import { useLayoutEffect, useState } from 'react'
import type { SectionSettings } from '@genoffice/docx-engine'
import { IconCaret, IconColumns, IconMargins, IconOrientation, IconPageSize } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'

type Values = Partial<Pick<SectionSettings,
  'orientation' | 'pageWidth' | 'pageHeight' | 'marginTop' | 'marginRight' | 'marginBottom' | 'marginLeft' | 'columns' | 'headerDist' | 'footerDist'>>
type Props = { editable: boolean; settings: SectionSettings | null; onChange: (values: Values) => void }

const paperSizes = { letter: [12240, 15840], a4: [11906, 16838], legal: [12240, 20160] } as const
const pageSetup = [
  ['layout-margins', '页边距', IconMargins],
  ['layout-orientation', '纸张方向', IconOrientation],
  ['layout-paper-size', '纸张大小', IconPageSize],
  ['layout-columns', '分栏', IconColumns],
] as const
const unavailable = 'DOCX 原生 section 操作未覆盖此源命令'

export function DocxLayoutSource({ editable, settings: initialSettings, onChange }: Props) {
  const [settings, setSettings] = useState(initialSettings)
  useLayoutEffect(() => { setSettings(initialSettings) }, [initialSettings])
  const [customPaper, setCustomPaper] = useState(false)
  const change = (values: Values) => {
    if (!editable || !settings) return
    setSettings(current => current ? { ...current, ...values } as SectionSettings : current)
    onChange(values)
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
      <label className="layout-num"><IconMargins size={18} /><span>页边距</span><select data-source-action="layout-margins" aria-label="页边距" value={settings && [settings.marginRight, settings.marginBottom, settings.marginLeft].every(value => value === settings.marginTop) && [720, 1440, 2160].includes(settings.marginTop) ? settings.marginTop : 'custom'} disabled={sectionDisabled} onChange={event => {
        const value = Number(event.currentTarget.value)
        change({ marginTop: value, marginRight: value, marginBottom: value, marginLeft: value })
      }}><option value="1440">普通</option><option value="720">窄</option><option value="2160">宽</option><option value="custom" disabled>自定义</option></select></label>
      <label className="layout-num"><IconOrientation size={18} /><span>纸张方向</span><select data-source-action="layout-orientation" aria-label="纸张方向" value={settings?.orientation ?? 'portrait'} disabled={sectionDisabled} onChange={event => orientationChange(event.currentTarget.value as 'portrait' | 'landscape')}><option value="portrait">纵向</option><option value="landscape">横向</option></select></label>
      <label className="layout-num"><IconPageSize size={18} /><span>纸张大小</span><select data-source-action="layout-paper-size" aria-label="纸张大小" value={customPaper ? 'custom' : settings ? Object.entries(paperSizes).find(([, size]) => size[0] === Math.min(settings.pageWidth, settings.pageHeight) && size[1] === Math.max(settings.pageWidth, settings.pageHeight))?.[0] ?? 'custom' : 'custom'} disabled={sectionDisabled} onChange={event => {
        if (event.currentTarget.value === 'custom') { setCustomPaper(true); return }
        setCustomPaper(false)
        if (!settings) return
        const [short, long] = paperSizes[event.currentTarget.value as keyof typeof paperSizes]
        change({ pageWidth: settings.orientation === 'portrait' ? short : long, pageHeight: settings.orientation === 'portrait' ? long : short })
      }}><option value="letter">Letter</option><option value="a4">A4</option><option value="legal">Legal</option><option value="custom">自定义</option></select></label>
      <label className="layout-num"><IconColumns size={18} /><span>分栏</span><select data-source-action="layout-columns" aria-label="分栏" value={settings?.columns ?? 1} disabled={sectionDisabled} onChange={event => change({ columns: Number(event.currentTarget.value) as 1 | 2 | 3 })}><option value="1">一栏</option><option value="2">两栏</option><option value="3">三栏</option></select></label>
      <label className="layout-num"><span>自定义宽度</span><input type="number" data-source-action="layout-custom-page-width" aria-label="自定义纸张宽度" value={settings?.pageWidth ?? 0} disabled={sectionDisabled || !customPaper} onChange={event => change({ pageWidth: Number(event.currentTarget.value) })} /><span className="layout-unit">twip</span></label>
      <label className="layout-num"><span>自定义高度</span><input type="number" data-source-action="layout-custom-page-height" aria-label="自定义纸张高度" value={settings?.pageHeight ?? 0} disabled={sectionDisabled || !customPaper} onChange={event => change({ pageHeight: Number(event.currentTarget.value) })} /><span className="layout-unit">twip</span></label>
      {field('layout-margin-top', '上边距', settings?.marginTop, value => change({ marginTop: value }))}
      {field('layout-margin-right', '右边距', settings?.marginRight, value => change({ marginRight: value }))}
      {field('layout-margin-bottom', '下边距', settings?.marginBottom, value => change({ marginBottom: value }))}
      {field('layout-margin-left', '左边距', settings?.marginLeft, value => change({ marginLeft: value }))}
      {field('layout-header-distance', '页眉距顶端', settings?.headerDist, value => change({ headerDist: value }))}
      {field('layout-footer-distance', '页脚距底端', settings?.footerDist, value => change({ footerDist: value }))}
      {source('layout-section-break-page', '下一页分节符', '分节符插入及多节 section 写回尚未接入')}
      {source('layout-section-break-continuous', '连续分节符', '分节符插入及多节 section 写回尚未接入')}
      {source('layout-section-break-even', '偶数页分节符', '分节符插入及多节 section 写回尚未接入')}
      {source('layout-section-break-odd', '奇数页分节符', '分节符插入及多节 section 写回尚未接入')}
    </>)}
    {group('页眉和页脚', <>
      {source('header-edit', '编辑页眉', '页眉/页脚 part 编辑写回尚未接入')}
      {source('header-remove', '删除页眉', '页眉/页脚 part 删除与关系写回尚未接入')}
      {source('footer-edit', '编辑页脚', '页眉/页脚 part 编辑写回尚未接入')}
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
      {source('page-number-format', '页码格式', '页码格式设置写回尚未接入')}
      {source('page-number-remove', '删除页码', '页码字段与页眉/页脚关系写回尚未接入')}
      {source('header-datetime', '日期和时间', '页眉/页脚字段写回尚未接入')}
      {source('header-date', '插入日期', '页眉/页脚字段写回尚未接入')}
      {source('header-time', '插入时间', '页眉/页脚字段写回尚未接入')}
      {source('header-document-info', '文档信息', '页眉/页脚字段写回尚未接入')}
      {source('header-picture', '页眉/页脚图片', '页眉/页脚图片与关系写回尚未接入')}
      {source('header-goto', '转到页眉或页脚', '页眉/页脚编辑会话尚未接入')}
      {source('header-section-navigation', '上一节或下一节', '分节导航与 section 编辑尚未接入')}
      {source('header-link-previous', '链接到前一节', '分节页眉/页脚关系写回尚未接入')}
      {source('header-title-page', '首页不同', '首页不同设置写回尚未接入')}
      {source('header-even-odd', '奇偶页不同', '奇偶页不同设置写回尚未接入')}
      {source('header-show-document-text', '显示文档文字', '页眉/页脚编辑视图尚未接入')}
      {field('header-distance', '页眉距顶端', settings?.headerDist, value => change({ headerDist: value }))}
      {field('footer-distance', '页脚距底端', settings?.footerDist, value => change({ footerDist: value }))}
      {source('header-close', '关闭页眉和页脚', '页眉/页脚编辑会话尚未接入')}
      <span className="sr-only">{unavailable}</span>
    </>)}
  </div>
}
