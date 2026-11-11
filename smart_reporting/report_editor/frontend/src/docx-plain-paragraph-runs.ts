import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { normalizeDocxNotes, notesOperationsOf, type DocxNoteOperation, type DocxNotesModel } from './docx-notes'
import { replayNoteParagraphRuns } from './docx-note-paragraph-runs'

/** 纯正文只复用来源run编译器，不声明任何脚注尾注能力。 */
function plainSourceModel(anchors: readonly DocxAnchor[]): DocxNotesModel {
  return { footnotes: [], endnotes: [], referenceBlocks: anchors.map(anchor => ({ blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, editable: anchor.editable })) }
}
export function normalizePlainDocxRuns(baseline: DocxPmNode, current: DocxPmNode, anchors: readonly DocxAnchor[]) {
  if (notesOperationsOf(current).length) throw new Error('当前来源未提供脚注尾注编辑能力')
  return normalizeDocxNotes(baseline, current, anchors, plainSourceModel(anchors), true)
}
export function replayPlainDocxRuns(source: DocxPmNode, plans: DocxNoteOperation[], anchors: readonly DocxAnchor[]) {
  if (plans.some(plan => !Array.isArray(plan.runs) || plan.runs.some((piece: Record<string, unknown>) => 'noteOperationIndex' in piece || 'referenceIndex' in piece))) throw new Error('纯正文草稿不能包含注释引用')
  return replayNoteParagraphRuns(source, plans, [], plainSourceModel(anchors), anchors)
}
