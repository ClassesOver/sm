import { useEffect, useState } from 'react'
import { Button, Form, Input, InputNumber, Select, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

type Doc = Record<string, unknown>
export const signatureStyleLabels: Record<string, string> = { font: '落款字体', size: '落款字号', color: '落款颜色', align: '落款对齐', bold: '落款加粗', lineHeight: '落款行距（倍）', spaceBefore: '与前文间距（磅）', spaceAfter: '落款段后（磅）', dateGap: '日期及说明段前（磅）', indent: '落款首行缩进（磅）' }
export function SignatureStyleFields({ document, format, onChange, disabled = false, errors = [] }: {
  document: Doc; format: string; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[]
}) {
  const [open, setOpen] = useState(false)
  const issue = errors.find(error => error.path.startsWith(format + '.signature.') && error.path.split('.').at(-1) !== 'description')
  useEffect(() => { setOpen(false) }, [format])
  useEffect(() => {
    if (issue) { setOpen(true); globalThis.document.getElementById('preference-' + issue.path)?.focus() }
  }, [issue, open])
  if (format === 'md') return null
  const prefix = [format, 'signature']
  const font = getPreferenceValue(document, [...prefix, 'font'])
  const color = getPreferenceValue(document, [...prefix, 'color'])
  const spacing = format === 'word' || format === 'pdf' ? ['lineHeight', 'spaceBefore', 'spaceAfter', 'dateGap'] : format === 'pptx' ? ['spaceBefore', 'indent'] : []
  return <div className="preference-wide-field">
    <Button type="link" aria-label="落款样式" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起落款样式' : '落款样式'}</Button>
    {open && <div className="preference-style-fields">
      {['font', 'size', 'align', 'color', 'bold', ...spacing].map(key => {
        const path = [...prefix, key], value = getPreferenceValue(document, path)
        const fieldIssue = errors.find(error => error.path === path.join('.'))
        const label = format === 'pptx' && key === 'spaceBefore' ? '与落款页标题间距（磅）' : signatureStyleLabels[key]
        return <Form.Item key={key} label={label} validateStatus={fieldIssue ? 'error' : undefined} help={fieldIssue?.message}>
          {key === 'font' ? <Select aria-label={label} value={font == null ? 'inherit' : String(font)}
            options={[{ value: 'inherit', label: '沿用通用字体' }, { value: 'sans', label: '无衬线（Noto Sans CJK SC）' }, { value: 'serif', label: '衬线（Noto Serif CJK SC）' }]}
            onChange={next => onChange(path, next === 'inherit' ? null : next)} /> :
            key === 'size' || spacing.includes(key) ? <InputNumber id={'preference-' + path.join('.')} aria-label={label} disabled={disabled}
              min={key === 'size' ? 6 : key === 'lineHeight' ? 1 : 0} max={key === 'lineHeight' ? 3 : key === 'spaceBefore' ? 144 : key === 'indent' ? 48 : 72}
              precision={1} step={key === 'lineHeight' ? 0.1 : 1} value={value === undefined ? undefined : Number(value)} onChange={next => { if (next !== null) onChange(path, next) }} /> :
            key === 'align' ? <Select aria-label={label} value={String(value)} options={[{ value: 'left', label: '左对齐' }, { value: 'center', label: '居中' }, { value: 'right', label: '右对齐' }]} onChange={next => onChange(path, next)} /> :
            key === 'color' ? <><Input id={'preference-' + path.join('.')} aria-label={label} value={String(color ?? '')} placeholder="默认 #172033" maxLength={7} onChange={event => onChange(path, event.target.value || null)} />
              {color != null && <Button type="link" size="small" onClick={() => onChange(path, null)}>恢复默认颜色</Button>}</> :
              <Switch aria-label={label} disabled={disabled} checked={Boolean(value)} onChange={next => onChange(path, next)} />}
        </Form.Item>
      })}
    </div>}
  </div>
}
