import type { Block } from '@genoffice/docx-engine'
import type { DocxPmNode } from './docx-operations'
import { runsToInline } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'

/** 原文件空段的输入格式投影；不向正文添加占位文字或客户端XML。 */
export function sourceEmptyDocxParagraphs(doc: DocxPmNode, blocks: readonly Block[]): DocxPmNode {
  const result = structuredClone(doc)
  for (const node of result.content ?? []) {
    const block = blocks.find(block => block.docxIndex === node.attrs?.docxIndex)
    if (!block?.emptyRun || block.runs?.length || node.content?.length) continue
    const marks = runsToInline([{ ...block.emptyRun, text: 'x' }])[0]?.marks
    if (marks?.length) node.attrs = { ...node.attrs, caretMarks: JSON.stringify(marks) }
  }
  return result
}

export function emptyDocxInheritanceNode(paragraph: DocxPmNode): DocxPmNode {
  return { type: 'text', text: '', ...(paragraph.attrs?.caretMarks ? { marks: JSON.parse(String(paragraph.attrs.caretMarks)) } : {}) }
}
