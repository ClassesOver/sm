import { useEffect, useState } from 'react'
import { Button, Form, Input, InputNumber, Radio, Select, Space, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'
import { documentStructureLabels } from './document-output'
import { HeaderFooterStyleFields, headerFooterLayoutLabels } from './header-footer-style'

type Doc = Record<string, unknown>
type Props = { document: Doc; format: string; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[] }
export const documentFieldLabels: Record<string, string> = { ...documentStructureLabels, ...headerFooterLayoutLabels, paper: '纸张', orientation: '方向', aspectRatio: '页面比例', enabled: '启用页眉页脚', firstPageDifferent: '首页不同', oddEvenDifferent: '奇偶页不同', hideTitleSlideFooter: '标题页隐藏页脚', left: '左侧', center: '中间', right: '右侧', layout: '图文布局', density: '内容密度', theme: '主题' }
export const documentValueLabels: Record<string, string> = { portrait: '纵向', landscape: '横向', comfortable: '舒适', compact: '紧凑', auto: '自动', text: '正文在上、图表在下', image_left: '图片居左', image_right: '图片居右', executive: '管理报告', clinical: '清爽', modern: '现代' }
export const marginSideLabels: Record<string, string> = { top: '上边距（毫米）', bottom: '下边距（毫米）', left: '左边距（毫米）', right: '右边距（毫米）' }
const marginPresets = [
  { value: 'report', label: '报告默认', margins: { top: 20, right: 18, bottom: 22, left: 18 } },
  { value: 'normal', label: '常规', margins: { top: 25, right: 22, bottom: 24, left: 22 } },
  { value: 'narrow', label: '窄（四边 12.7 毫米）', margins: { top: 12.7, right: 12.7, bottom: 12.7, left: 12.7 } },
  { value: 'wide', label: '宽（上下 25.4，左右 31.8 毫米）', margins: { top: 25.4, right: 31.8, bottom: 25.4, left: 31.8 } },
]
export function PagePreferenceFields({ document, format, onChange, disabled, errors = [] }: Props) {
  const [custom, setCustom] = useState(false)
  useEffect(() => { setCustom(false) }, [format])
  useEffect(() => {
    const issue = errors.find(error => error.path.startsWith(format + '.') && error.path.includes('.page.'))
    if (issue) { setCustom(true); globalThis.document.getElementById('preference-' + issue.path)?.focus() }
  }, [errors, format, custom])
  if (format === 'md') return null
  const prefix = format === 'xlsx' ? [format, 'print', 'page'] : [format, 'page']
  const fields = format === 'pptx' ? [{ path: [format, 'aspectRatio'], label: '页面比例', options: ['16:9', '4:3'] }, { path: [format, 'layout'], label: '图文布局', options: ['auto', 'image_left', 'image_right', 'text'] }, { path: [format, 'density'], label: '内容密度', options: ['comfortable', 'compact'] }, { path: [format, 'theme'], label: '主题', options: ['executive', 'clinical', 'modern'] }] : [
    { path: [...prefix, 'paper'], label: '纸张', options: ['A4', 'A3', 'Letter'] },
    { path: [...prefix, 'orientation'], label: '方向', options: ['portrait', 'landscape'] },
  ]
  const margins = getPreferenceValue(document, [...prefix, 'margins']) as Record<string, number> | undefined
  const preset = marginPresets.find(item => Object.entries(item.margins).every(([side, value]) => margins?.[side] === value))
  const showCustom = custom
  const sides: Record<string, string> = { top: '上', bottom: '下', left: '左', right: '右' }
  return <Form layout="vertical" disabled={disabled}>{fields.map(field => <Form.Item key={field.label} label={field.label}>
    <Select aria-label={field.label} value={String(getPreferenceValue(document, field.path))} options={field.options.map(value => ({ value, label: documentValueLabels[value] || value }))} onChange={value => onChange(field.path, value)} />
  </Form.Item>)}
    {format !== 'pptx' && margins && <>
      <Form.Item className="preference-wide-field" label="页边距"><Select aria-label="页边距" value={showCustom ? 'custom' : preset?.value || 'custom'}
        options={[...marginPresets.map(({ value, label }) => ({ value, label })), { value: 'custom', label: '自定义（毫米）' }]}
        onChange={value => { setCustom(value === 'custom'); const next = marginPresets.find(item => item.value === value); if (next) onChange([...prefix, 'margins'], { ...next.margins }) }} />
        {!preset && !showCustom && <Button type="link" aria-label="调整自定义边距" onClick={() => setCustom(true)}>调整自定义边距</Button>}
      </Form.Item>
      {showCustom && ['top', 'bottom', 'left', 'right'].map(side => {
        const path = [...prefix, 'margins', side], issue = errors.find(error => error.path === path.join('.'))
        return <Form.Item key={side} label={sides[side] + '边距（毫米）'} validateStatus={issue ? 'error' : undefined} help={issue?.message}>
          <InputNumber id={'preference-' + path.join('.')} aria-label={sides[side] + '边距（毫米）'} min={0} max={100} precision={1}
            value={margins[side]} onChange={value => { if (value !== null) onChange(path, value) }} />
        </Form.Item>
      })}
    </>}
  </Form>
}
export function HeaderFooterFields({ document, format, onChange, disabled, errors = [] }: Props) {
  const [story, setStory] = useState('header'), [variant, setVariant] = useState('ordinary')
  useEffect(() => {
    const issue = errors.find(error => error.path.startsWith(format + '.'))
    if (!issue) return
    const name = issue.path.split('.').at(-2) || 'header'
    setStory(name.toLowerCase().includes('footer') ? 'footer' : 'header')
    setVariant(name.startsWith('first') ? 'first' : name.startsWith('even') ? 'even' : 'ordinary')
  }, [errors, format])
  useEffect(() => {
    const issue = errors.find(error => error.path.startsWith(format + '.'))
    if (issue) globalThis.document.getElementById('preference-' + issue.path)?.focus()
  }, [errors, format, story, variant])
  if (format === 'md') return null
  const slides = format === 'pptx', paged = format === 'word' || format === 'pdf'
  const prefix = slides ? [format] : format === 'xlsx' ? [format, 'print', 'headerFooter'] : [format, 'headerFooter']
  const value = getPreferenceValue(document, prefix) as Doc
  const actualStory = slides ? 'footer' : story
  const actualVariant = !paged || variant === 'first' && !value.firstPageDifferent || variant === 'even' && !value.oddEvenDifferent ? 'ordinary' : variant
  const key = actualVariant === 'ordinary' ? actualStory : actualVariant + actualStory[0].toUpperCase() + actualStory.slice(1)
  const fields = ['title', 'signer', 'period', 'date', 'filename', ...(slides ? ['slide', 'slides'] : ['page', 'pages'])]
  const fieldLabels: Record<string, string> = { title: '报告标题', signer: '署名', period: '分析期间', date: '生成日期', filename: '文件名', page: '页码', pages: '总页数', slide: '幻灯片编号', slides: '幻灯片总数' }
  const visible = slides || Boolean(value.enabled)
  return <Form layout="vertical" disabled={disabled}>
    {slides ? <Form.Item label="标题页隐藏页脚"><Switch aria-label="标题页隐藏页脚" checked={Boolean(value.hideTitleSlideFooter)} onChange={next => onChange([...prefix, 'hideTitleSlideFooter'], next)} /></Form.Item> :
      <Form.Item label="启用页眉页脚"><Switch aria-label="启用页眉页脚" checked={Boolean(value.enabled)} onChange={next => onChange([...prefix, 'enabled'], next)} /></Form.Item>}
    {visible && <>
      {paged && ['firstPageDifferent', 'oddEvenDifferent'].map(name => <Form.Item key={name} label={documentFieldLabels[name]}><Switch aria-label={documentFieldLabels[name]} checked={Boolean(value[name])} onChange={next => onChange([...prefix, name], next)} /></Form.Item>)}
      <div className="preference-wide-field preference-story-selector"><Space wrap>
        {!slides && <Radio.Group aria-label="编辑页眉或页脚" optionType="button" value={actualStory} options={[{ value: 'header', label: '页眉' }, { value: 'footer', label: '页脚' }]} onChange={event => setStory(event.target.value)} />}
        {paged && <Select aria-label="页面变体" value={actualVariant} options={[{ value: 'ordinary', label: value.oddEvenDifferent ? '奇数页' : '普通页' }, ...(value.firstPageDifferent ? [{ value: 'first', label: '首页' }] : []), ...(value.oddEvenDifferent ? [{ value: 'even', label: '偶数页' }] : [])]} onChange={setVariant} />}
      </Space></div>
      {['left', 'center', 'right'].map(side => {
        const path = [...prefix, key, side], explicit = getPreferenceValue(document, [...prefix, key])
        const inherited = actualVariant === 'even' && explicit == null
        const text = String(getPreferenceValue(document, [...prefix, inherited ? actualStory : key, side]) ?? '')
        const label = (actualStory === 'header' ? '页眉' : '页脚') + documentFieldLabels[side]
        const issue = errors.find(error => error.path === path.join('.'))
        function change(next: string) {
          if (inherited) onChange([...prefix, key], { ...(value[actualStory] as Doc), [side]: next })
          else onChange(path, next)
        }
        return <Form.Item className="preference-wide-field" key={path.join('.')} label={label} validateStatus={issue ? 'error' : undefined} help={issue?.message}>
          <Space.Compact block><Input id={'preference-' + path.join('.')} aria-label={label} value={text} maxLength={200} onChange={event => change(event.target.value)} />
            <Select aria-label={'插入字段到' + label} value={undefined} placeholder="插入字段" options={fields.map(field => ({ value: field, label: fieldLabels[field] }))} onChange={field => change(text + '{' + field + '}')} /></Space.Compact>
          {inherited && <span className="preference-inheritance">沿用普通页内容</span>}
        </Form.Item>
      })}
      {actualVariant === 'even' && value[key] != null && <Button className="preference-wide-field" onClick={() => onChange([...prefix, key], null)}>恢复沿用普通页</Button>}
      <HeaderFooterStyleFields document={document} format={format} onChange={onChange} disabled={disabled} errors={errors} />
    </>}
  </Form>
}
