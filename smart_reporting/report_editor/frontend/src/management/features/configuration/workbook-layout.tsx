import { Form, InputNumber, Select, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

export const workbookLayoutLabels: Record<string, string> = { alignment: '数据对齐', wrapText: '自动换行', rowHeight: '行高（磅）', columnWidth: '列宽（字符）' }
export function WorkbookLayoutFields({ document, onChange, disabled, errors = [] }: {
  document: Record<string, unknown>; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[]
}) {
  return <Form layout="vertical" disabled={disabled}>
    <Form.Item label="数据对齐"><Select aria-label="数据对齐" value={String(getPreferenceValue(document, ['xlsx', 'alignment']))}
      options={[{ value: 'left', label: '左对齐' }, { value: 'center', label: '居中' }, { value: 'right', label: '右对齐' }]} onChange={value => onChange(['xlsx', 'alignment'], value)} /></Form.Item>
    <Form.Item label="自动换行"><Switch aria-label="自动换行" checked={Boolean(getPreferenceValue(document, ['xlsx', 'wrapText']))} onChange={value => onChange(['xlsx', 'wrapText'], value)} /></Form.Item>
    {(['rowHeight', 'columnWidth'] as const).map(key => {
      const issue = errors.find(error => error.path === 'xlsx.' + key)
      return <Form.Item key={key} label={workbookLayoutLabels[key]} validateStatus={issue ? 'error' : undefined} help={issue?.message}>
        <InputNumber id={'preference-xlsx.' + key} aria-label={workbookLayoutLabels[key]} min={key === 'rowHeight' ? 8 : 2} max={key === 'rowHeight' ? 409 : 100} precision={1}
          placeholder="使用默认" value={getPreferenceValue(document, ['xlsx', key]) as number | null} onChange={value => onChange(['xlsx', key], value)} />
      </Form.Item>
    })}
    <p className="preference-wide-field">行高和列宽清空即恢复默认；仅调整显示，单元格明确设置的样式优先。</p>
  </Form>
}
