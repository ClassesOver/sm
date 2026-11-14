import { Button, Form, Input, Select } from 'antd'
import { getPreferenceValue } from './preference-draft'

type Doc = Record<string, unknown>
export const commonStyleLabels: Record<string, string> = { font: '字体', accentColor: '主题色' }
export function CommonStyleFields({ document, format, onChange, disabled = false, errors = [] }: {
  document: Doc; format: string; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[]
}) {
  if (format === 'md') return null
  const common = format === 'common', prefix = common ? ['common'] : [format, 'common']
  return <>{['font', 'accentColor'].map(key => {
    const path = [...prefix, key], value = getPreferenceValue(document, path)
    const override = !common && ((document[format] as Doc)?.common as Doc)?.[key] != null
    const issue = errors.find(error => error.path === path.join('.'))
    return <Form.Item key={key} label={commonStyleLabels[key]} validateStatus={issue ? 'error' : undefined} help={issue?.message}>
      {key === 'font' ? <Select id={'preference-' + path.join('.')} aria-label="字体" disabled={disabled} value={String(value)}
        options={[{ value: 'sans', label: '无衬线（Noto Sans CJK SC）' }, { value: 'serif', label: '衬线（Noto Serif CJK SC）' }]}
        onChange={next => onChange(path, next)} /> :
        <Input id={'preference-' + path.join('.')} aria-label="主题色" disabled={disabled} value={String(value ?? '')} maxLength={7} placeholder="#174a66" onChange={event => onChange(path, event.target.value)} />}
      {!common && <div className="preference-inheritance"><span>{override ? '已单独设置' : '沿用通用偏好'}</span>
        {override && <Button aria-label={'恢复沿用' + commonStyleLabels[key]} disabled={disabled} type="link" size="small" onClick={() => onChange(path, null)}>恢复沿用</Button>}</div>}
    </Form.Item>
  })}</>
}
