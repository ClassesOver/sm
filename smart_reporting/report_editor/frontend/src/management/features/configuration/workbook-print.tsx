import { useState } from 'react'
import { Form, InputNumber, Select } from 'antd'
import { getPreferenceValue } from './preference-draft'

type Doc = Record<string, unknown>
export const workbookPrintLabels: Record<string, string> = { fitToWidth: '适配宽度（页）', fitToHeight: '适配高度（页）', scalePercent: '打印缩放（%）', repeatTitleRows: '重复标题行数' }
export function WorkbookPrintFields({ document, onChange, disabled = false }: { document: Doc; onChange: (path: string[], value: unknown) => void; disabled?: boolean }) {
  const [custom, setCustom] = useState(false)
  const value = getPreferenceValue(document, ['xlsx', 'print']) as Doc
  const mode = value.scalePercent != null ? 'scale' : custom ? 'custom' : value.fitToWidth === 1 && value.fitToHeight == null ? 'width' : value.fitToWidth === 1 && value.fitToHeight === 1 ? 'page' : 'custom'
  function changeMode(next: string) {
    setCustom(next === 'custom')
    onChange(['xlsx', 'print'], { ...value, scalePercent: next === 'scale' ? 100 : null,
      fitToWidth: next === 'scale' ? null : 1, fitToHeight: next === 'page' ? 1 : null })
  }
  return <Form layout="vertical" disabled={disabled}>
    <Form.Item className="preference-wide-field" label="打印缩放方式"><Select aria-label="打印缩放方式" value={mode}
      options={[{ value: 'width', label: '适配为一页宽（高度自动）' }, { value: 'page', label: '整张表适配一页' }, { value: 'scale', label: '按比例缩放' }, { value: 'custom', label: '自定义适配页数' }]}
      onChange={changeMode} /></Form.Item>
    {mode === 'scale' && <Form.Item label="打印缩放（%）"><InputNumber aria-label="打印缩放（%）" min={10} max={400} precision={0} value={Number(value.scalePercent)}
      onChange={next => { if (next !== null) onChange(['xlsx', 'print', 'scalePercent'], next) }} /></Form.Item>}
    {mode === 'custom' && ['fitToWidth', 'fitToHeight'].map(key => <Form.Item key={key} label={workbookPrintLabels[key]}>
      <InputNumber aria-label={workbookPrintLabels[key]} min={1} max={100} precision={0} placeholder="自动" value={value[key] as number | null}
        onChange={next => onChange(['xlsx', 'print', key], next)} />
    </Form.Item>)}
    <Form.Item label="重复标题行数" extra="从第一行开始；0 表示不重复。"><InputNumber aria-label="重复标题行数" min={0} max={20} precision={0} value={Number(value.repeatTitleRows)}
      onChange={next => { if (next !== null) onChange(['xlsx', 'print', 'repeatTitleRows'], next) }} /></Form.Item>
  </Form>
}
