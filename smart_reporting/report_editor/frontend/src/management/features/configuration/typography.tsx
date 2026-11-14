import { useEffect, useState } from 'react'
import { Button, Form, Input, InputNumber, Select, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

type Doc = Record<string, unknown>
export const typographyRoles = [{ value: 'body', label: '正文' }, { value: 'h1', label: '一级标题' }, { value: 'h2', label: '二级标题' }, { value: 'h3', label: '三级标题' }, { value: 'table', label: '表格文字' }, { value: 'caption', label: '图注' }]
export const workbookTypographyRoles = [{ value: 'body', label: '数据文字' }, { value: 'header', label: '表头文字' }]
export const slidesTypographyRoles = [{ value: 'body', label: '正文' }, { value: 'h1', label: '标题' }, { value: 'table', label: '表格文字' }, { value: 'caption', label: '图注' }]
export const typographyLabels: Record<string, string> = { size: '字号（磅）', font: '字体', color: '文字颜色', bold: '加粗', lineHeight: '行距（倍）', spaceBefore: '段前（磅）', spaceAfter: '段后（磅）', indent: '首行缩进（磅）' }
export function TypographyFields({ document, format, onChange, disabled = false, errors = [] }: {
  document: Doc; format: string; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[]
}) {
  const [role, setRole] = useState('body'), [open, setOpen] = useState(false)
  const workbook = format === 'xlsx'
  const issue = errors.find(error => workbook ? /^xlsx\.(body|header)\./.test(error.path) : error.path.startsWith(format + '.typography.'))
  useEffect(() => { setRole('body'); setOpen(false) }, [format])
  useEffect(() => {
    if (issue) { setRole(issue.path.split('.')[workbook ? 1 : 2]); setOpen(true); globalThis.document.getElementById('preference-' + issue.path)?.focus() }
  }, [issue, role, open])
  if (!['word', 'pdf', 'xlsx', 'pptx'].includes(format)) return null
  const prefix = workbook ? [format, role] : [format, 'typography', role]
  return <div className="preference-typography">
    <div className="preference-story-selector"><Select aria-label="排版对象" disabled={disabled} value={role} options={workbook ? workbookTypographyRoles : format === 'pptx' ? slidesTypographyRoles : typographyRoles} onChange={value => { setRole(value); setOpen(false) }} /></div>
    <Form layout="vertical" disabled={disabled}>
      {['font', 'size', ...(workbook && role === 'header' ? [] : ['color']), 'bold', ...(!workbook && open ? ['lineHeight', 'spaceBefore', 'spaceAfter', 'indent'] : [])].map(key => {
        const path = [...prefix, key], value = getPreferenceValue(document, path)
        const error = errors.find(item => item.path === path.join('.'))
        const label = key === 'font' ? '排版字体' : key === 'color' ? '排版颜色' : key === 'size' ? '排版字号' : key === 'bold' ? '排版加粗' : key === 'lineHeight' ? '排版行距' : typographyLabels[key]
        return <Form.Item key={path.join('.')} label={typographyLabels[key]} validateStatus={error ? 'error' : undefined} help={error?.message}>
          {key === 'font' ? <Select aria-label={label} value={value == null ? 'inherit' : String(value)}
            options={[{ value: 'inherit', label: '沿用本格式字体' }, { value: 'sans', label: '无衬线（Noto Sans CJK SC）' }, { value: 'serif', label: '衬线（Noto Serif CJK SC）' }]}
            onChange={next => onChange(path, next === 'inherit' ? null : next)} /> :
          key === 'color' ? <Input id={'preference-' + path.join('.')} aria-label={label} value={String(value ?? '')} maxLength={7} placeholder={role.startsWith('h') ? '沿用主题色' : '默认文字色'} onChange={event => onChange(path, event.target.value || null)} /> :
          key === 'bold' ? <Switch aria-label={label} checked={Boolean(value)} onChange={next => onChange(path, next)} /> :
          <InputNumber id={'preference-' + path.join('.')} aria-label={label} min={key === 'size' ? 6 : key === 'lineHeight' ? 1 : 0} max={key === 'lineHeight' ? 3 : key === 'indent' ? 48 : 72}
            precision={1} value={Number(value)} onChange={next => { if (next !== null) onChange(path, next) }} />}
        </Form.Item>
      })}
      {['word', 'pdf', 'pptx'].includes(format) && role === 'caption' && <Form.Item label="图注编号"><Switch aria-label="图注编号"
        checked={Boolean(getPreferenceValue(document, [format, 'charts', 'captionNumbering']))}
        onChange={next => onChange([format, 'charts', 'captionNumbering'], next)} /></Form.Item>}
    </Form>
    {workbook && role === 'header' && <p>表头文字颜色随主题底色自动选用黑色或白色。</p>}
    {!workbook && <Button type="link" aria-label="段落细节" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起段落细节' : '段落细节'}</Button>}
  </div>
}
