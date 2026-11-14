import { useEffect } from 'react'
import { Form, InputNumber, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'
import { DocumentStructureFields } from './document-output'

export const pdfOutputLabels: Record<string, string> = { bookmarks: '生成书签', imageQuality: 'JPEG 图像质量' }
export function PdfOutputFields({ document, onChange, disabled, errors = [], includeStructure = false }: {
  document: Record<string, unknown>; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[]; includeStructure?: boolean
}) {
  const issue = errors.find(error => error.path === 'pdf.imageQuality')
  useEffect(() => { if (issue) globalThis.document.getElementById('preference-pdf.imageQuality')?.focus() }, [issue])
  return <Form layout="vertical" disabled={disabled}>
    {includeStructure && <DocumentStructureFields document={document} format="pdf" onChange={onChange} disabled={disabled} />}
    <Form.Item label="生成书签"><Switch aria-label="生成书签" checked={Boolean(getPreferenceValue(document, ['pdf', 'bookmarks']))}
      onChange={value => onChange(['pdf', 'bookmarks'], value)} /></Form.Item>
    <Form.Item label="JPEG 图像质量" validateStatus={issue ? 'error' : undefined} help={issue?.message}>
      <InputNumber id="preference-pdf.imageQuality" aria-label="JPEG 图像质量" min={50} max={100} precision={0}
        value={Number(getPreferenceValue(document, ['pdf', 'imageQuality']))} onChange={value => { if (value !== null) onChange(['pdf', 'imageQuality'], value) }} />
    </Form.Item>
    <p className="preference-wide-field">字体始终嵌入，保证跨设备阅读一致。书签跟随报告标题生成。图像质量仅调整 PDF 中 JPEG 压缩；PNG、原始图片和业务数据保持不变。</p>
  </Form>
}
