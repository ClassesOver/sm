import { Form, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

export const documentStructureLabels: Record<string, string> = { cover: '生成封面', toc: '生成目录', sources: '来源附录' }

/** 复用当前格式的草稿和原生输出设置，不引入另一份默认。 */
export function DocumentStructureFields({ document, format, onChange, disabled }: {
  document: Record<string, unknown>; format: 'word' | 'pdf'; onChange: (path: string[], value: unknown) => void; disabled?: boolean
}) {
  return <>{Object.entries(documentStructureLabels).map(([key, label]) => <Form.Item key={key} label={label}
    extra={key === 'sources' ? '仅展示实际登记来源；关闭附录仍保留来源绑定。' : undefined}>
    <Switch aria-label={label} checked={Boolean(getPreferenceValue(document, [format, key]))} disabled={disabled}
      onChange={value => onChange([format, key], value)} />
  </Form.Item>)}</>
}
