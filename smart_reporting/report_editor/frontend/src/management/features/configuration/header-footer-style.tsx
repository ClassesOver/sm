import { useEffect, useState } from 'react'
import { Button, Form, Input, InputNumber, Select, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

export const headerFooterLayoutLabels: Record<string, string> = {
  headerDistance: '页眉距页面顶端（毫米）', footerDistance: '页脚距页面底端（毫米）',
  divider: '页眉页脚分隔线', pageNumberStart: '正文页码起点',
}

export function HeaderFooterStyleFields({ document, format, onChange, disabled = false, errors = [] }: {
  document: Record<string, unknown>; format: string; onChange: (path: string[], value: unknown) => void
  disabled?: boolean; errors?: { path: string; message: string }[]
}) {
  const [open, setOpen] = useState(false)
  const prefix = format === 'xlsx' ? [format, 'print', 'headerFooter', 'style']
    : format === 'pptx' ? [format, 'footerStyle'] : [format, 'headerFooter', 'style']
  const paged = format === 'word' || format === 'pdf'
  const layoutPrefix = [format, 'headerFooter']
  const issue = errors.find(error => error.path.startsWith(prefix.join('.') + '.') ||
    paged && Object.keys(headerFooterLayoutLabels).some(key => error.path === [...layoutPrefix, key].join('.')))
  useEffect(() => { setOpen(false) }, [format])
  useEffect(() => {
    if (issue) { setOpen(true); globalThis.document.getElementById('preference-' + issue.path)?.focus() }
  }, [issue, open])
  const name = format === 'pptx' ? '页脚' : '页眉页脚'
  return <div className="preference-wide-field">
    <Button type="link" aria-label={name + '样式'} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起' + name + '样式' : name + '样式'}</Button>
    {open && <div className="preference-style-fields">
      {['font', 'size', 'color', 'bold', ...(format === 'pptx' ? ['indent'] : [])].map(key => {
        const path = [...prefix, key], value = getPreferenceValue(document, path)
        const error = errors.find(item => item.path === path.join('.'))
        const label = name + ({ font: '字体', size: '字号', color: '颜色', bold: '加粗', indent: '首行缩进' } as Record<string, string>)[key]
        const id = 'preference-' + path.join('.')
        return <Form.Item key={key} label={label + (key === 'size' || key === 'indent' ? '（磅）' : '')} validateStatus={error ? 'error' : undefined} help={error?.message}>
          {key === 'font' ? <Select id={id} aria-label={label} disabled={disabled} value={value == null ? 'inherit' : String(value)}
            options={[{ value: 'inherit', label: '沿用本格式字体' }, { value: 'sans', label: '无衬线（Noto Sans CJK SC）' }, { value: 'serif', label: '衬线（Noto Serif CJK SC）' }]}
            onChange={next => onChange(path, next === 'inherit' ? null : next)} />
            : key === 'size' || key === 'indent' ? <InputNumber id={id} aria-label={label} disabled={disabled} min={key === 'indent' ? 0 : 6} max={key === 'indent' ? 48 : 72} precision={format === 'xlsx' ? 0 : 1}
              value={Number(value)} onChange={next => { if (next !== null) onChange(path, next) }} />
              : key === 'color' ? <Input id={id} aria-label={label} disabled={disabled} value={String(value ?? '')} maxLength={7}
                placeholder="默认文字色" onChange={event => onChange(path, event.target.value || null)} />
                : <Switch id={id} aria-label={label} disabled={disabled} checked={Boolean(value)} onChange={next => onChange(path, next)} />}
        </Form.Item>
      })}
      {paged && Object.entries(headerFooterLayoutLabels).map(([key, label]) => {
        const path = [...layoutPrefix, key], value = getPreferenceValue(document, path)
        const error = errors.find(item => item.path === path.join('.'))
        const id = 'preference-' + path.join('.')
        return <Form.Item key={key} label={label} validateStatus={error ? 'error' : undefined} help={error?.message}>
          {key === 'divider' ? <Switch id={id} aria-label={label} disabled={disabled} checked={Boolean(value)}
            onChange={next => onChange(path, next)} />
            : <InputNumber id={id} aria-label={label} disabled={disabled}
              min={key === 'pageNumberStart' ? 1 : 0} max={key === 'pageNumberStart' ? 9999 : 50}
              precision={key === 'pageNumberStart' ? 0 : 1} value={Number(value)}
              onChange={next => { if (next !== null) onChange(path, next) }} />}
        </Form.Item>
      })}
      {format === 'xlsx' && <p className="preference-wide-field">打印页眉页脚使用整磅字号；页码仍按实际打印分页显示。</p>}
    </div>}
  </div>
}
