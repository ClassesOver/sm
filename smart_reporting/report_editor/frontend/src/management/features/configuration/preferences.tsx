import { useState } from 'react'
import { Descriptions, Menu, Tabs } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { request } from '../../api/http'
import { AsyncState, PageHeader } from '../../components/common'
import { detailSchema } from './contracts'
import { useSession } from '../../app/session'
import { SignatureEditor } from './signature-editor'
import { preferenceFields } from './preference-fields'
import { formatOptions } from './format-labels'
import './settings.css'

const formats = formatOptions.map(item => ({ key: item.key, label: <span title={item.hint}>{item.label}</span> }))
const labels: Record<string, string> = { signer: '署名', generatedByLabel: '生成说明', dateFormat: '日期格式', font: '字体', accentColor: '主题色',
  description: '附加说明', align: '对齐', size: '字号', color: '文字颜色', bold: '加粗', lineHeight: '行距', spaceBefore: '段前间距', spaceAfter: '段后间距', indent: '首行缩进', dateGap: '署名与日期间距',
  paper: '纸张', orientation: '方向', margins: '页边距', top: '上', bottom: '下', left: '左', center: '中', right: '右', enabled: '启用', header: '页眉', footer: '页脚', style: '样式',
  headerDistance: '页眉距边缘', footerDistance: '页脚距边缘', divider: '分隔线', firstPageDifferent: '首页不同', oddEvenDifferent: '奇偶页不同', firstHeader: '首页页眉', firstFooter: '首页页脚', evenHeader: '偶数页页眉', evenFooter: '偶数页页脚',
  pageNumbers: '页码', pageNumberStart: '页码起点', body: '正文', h1: '一级标题', h2: '二级标题', h3: '三级标题', table: '表格文字', caption: '图注',
  repeatHeader: '重复表头', splitRows: '允许跨页断行', borders: '边框', striped: '条纹', captionNumbering: '标题编号', imageDpi: '图像分辨率', keepWithCaption: '图文保持同页',
  cover: '封面', toc: '目录', sources: '来源附录', bookmarks: '书签', imageQuality: '图像质量', aspectRatio: '页面比例', theme: '主题', density: '内容密度', layout: '图文布局',
  wrapText: '自动换行', rowHeight: '行高', columnWidth: '列宽', freezeHeader: '冻结表头', autoFilter: '自动筛选', alignment: '默认对齐',
  numbers: '数字格式', decimalPlaces: '小数位', thousandsSeparator: '千分位', percentPlaces: '百分比小数位', negativeStyle: '负数样式', print: '打印', fitToWidth: '适配页宽', fitToHeight: '适配页高', scalePercent: '打印缩放', repeatTitleRows: '重复标题行数',
  tableStyle: '表格写法', listMarker: '列表符号', codeFence: '代码块', imageCaptions: '图片说明', references: '引用', hideTitleSlideFooter: '标题页隐藏页脚', footerStyle: '页脚样式', opacity: '透明度', text: '文字' }
const values: Record<string, string> = { chinese: '中文日期', iso: 'YYYY-MM-DD', slash: 'YYYY/MM/DD', sans: '无衬线（Noto Sans CJK SC）', serif: '衬线（Noto Serif CJK SC）',
  portrait: '纵向', landscape: '横向', left: '左对齐', center: '居中', right: '右对齐', light: '浅色边框', all: '全部边框', none: '无边框', comfortable: '舒适', compact: '紧凑', auto: '自动', text: '文字为主', image_left: '图片居左', image_right: '图片居右', executive: '管理报告', clinical: '清爽', modern: '现代', pipe: '标准 Markdown 表格', html: 'HTML 表格', backticks: '反引号', tildes: '波浪号', minus: '负号', parentheses: '括号', red: '红色' }
const sections = [{ key: 'common', label: '通用偏好' }, { key: 'signature', label: '落款' }, { key: 'page', label: '页面与排版' }, { key: 'headerFooter', label: '页眉页脚' }, { key: 'tables', label: '表格与图表' }, { key: 'export', label: '导出' }]
function display(value: unknown): string {
  if (value === null) return '沿用通用偏好'
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)))
  return values[String(value)] || String(value === '' || value === undefined ? '未填写' : value)
}
function flatten(value: Record<string, unknown>, prefix = ''): { key: string; label: string; children: string }[] {
  return Object.entries(value).filter(([, item]) => item !== null && item !== undefined && item !== '').flatMap(([key, item]) => {
    const label = prefix + (labels[key] || key)
    return item && typeof item === 'object' && !Array.isArray(item) ? flatten(item as Record<string, unknown>, label + ' · ') : [{ key: label, label, children: display(item) }]
  })
}
export default function Preferences() {
  const { state } = useSession()
  const [format, setFormat] = useState('word'), [section, setSection] = useState('signature')
  const query = useQuery({ queryKey: ['configuration', 'preferences'], queryFn: ({ signal }) => request('/configuration/preferences', detailSchema, { signal }) })
  const document = query.data?.draft.document
  const selected = document?.[format] as Record<string, unknown> | undefined
  const applicable = sections.filter(item => item.key !== 'headerFooter' || format !== 'md').filter(item => item.key !== 'page' || format !== 'md')
    .filter(item => !(format === 'md' && item.key === 'export'))
    .map(item => format === 'md' && item.key === 'tables' ? { ...item, label: '语法样式' } : item)
  const actualSection = applicable.some(item => item.key === section) ? section : 'signature'
  let fields: Record<string, unknown> = {}
  if (selected && document) {
    if (actualSection === 'common') fields = { ...document.common as Record<string, unknown>, ...Object.fromEntries(Object.entries(selected.common as Record<string, unknown>).filter(([, value]) => value !== null)) }
    else if (actualSection === 'signature') fields = { signer: (selected.common as Record<string, unknown>).signer ?? (document.common as Record<string, unknown>).signer,
      dateFormat: (selected.common as Record<string, unknown>).dateFormat ?? (document.common as Record<string, unknown>).dateFormat, ...selected.signature as Record<string, unknown> }
    else if (actualSection === 'page') fields = Object.fromEntries(['page', 'typography', 'aspectRatio', 'body', 'header', 'alignment', 'wrapText', 'rowHeight', 'columnWidth', 'density', 'layout'].filter(key => key in selected).map(key => [key, selected[key]]))
    else if (actualSection === 'headerFooter') fields = (selected.headerFooter || selected.print && (selected.print as Record<string, unknown>).headerFooter || { footer: selected.footer, footerStyle: selected.footerStyle, hideTitleSlideFooter: selected.hideTitleSlideFooter }) as Record<string, unknown>
    else if (actualSection === 'tables') fields = Object.fromEntries(['tables', 'charts', 'numbers', 'borders', 'striped', 'freezeHeader', 'autoFilter'].filter(key => key in selected).map(key => [key, selected[key]]))
    else fields = Object.fromEntries(['cover', 'toc', 'sources', 'bookmarks', 'imageQuality', 'tableStyle', 'listMarker', 'codeFence', 'imageCaptions', 'references', 'print'].filter(key => key in selected).map(key => [key, selected[key]]))
  }
  return <><PageHeader title="偏好管理" description="按交付格式查看全局默认；落款、页眉页脚与 Office 排版分别维护。" />
    <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
      {query.data && <section className="global-settings"><Tabs className="global-format-tabs" activeKey={format} onChange={setFormat} items={formats} />
        <SignatureEditor section={actualSection} detail={query.data} format={format} common={actualSection === 'common'} csrf={state.session?.csrfToken || ''}
          active={actualSection === 'common' || actualSection === 'signature'}
          onNavigate={(target, targetSection = 'signature') => { if (target === 'common') setSection('common'); else { setFormat(target); setSection(targetSection) } }}
          readonlyContent={
          <div className="global-settings-form"><h2>{applicable.find(item => item.key === actualSection)?.label}</h2>
            {actualSection === 'signature' && <p>独立落款包含署名和本次修订日期，可附加说明；页脚和封面署名不代替正文落款。</p>}
            <Descriptions column={{ xs: 1, sm: 1, md: 2 }} size="middle" items={flatten(preferenceFields(actualSection, fields))} />
          </div>}>
          <aside className="global-settings-directory"><Menu selectedKeys={[actualSection]} items={applicable} onClick={({ key }) => setSection(key)} /></aside>
        </SignatureEditor>
      </section>}
    </AsyncState></>
}
