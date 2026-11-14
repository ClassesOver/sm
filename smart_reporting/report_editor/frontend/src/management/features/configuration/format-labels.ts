/** 使用易读名称呈现格式；键仍对应既有接口与冻结快照。 */
export const formatOptions = [
  { key: 'md', label: '文本报告', hint: 'Markdown（.md）' },
  { key: 'xlsx', label: '电子表格', hint: 'Excel（.xlsx）' },
  { key: 'pptx', label: '演示文稿', hint: 'PowerPoint（.pptx）' },
  { key: 'pdf', label: 'PDF', hint: 'PDF（.pdf）' },
  { key: 'word', label: '文字文档', hint: 'Word（.docx）' },
]
export const formatLabels: Record<string, string> = Object.fromEntries(formatOptions.map(item => [item.key, item.label]))
