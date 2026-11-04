export type WorkbookOperation = Record<string, unknown>
export type WorkbookProposal = { summary: string; operations: WorkbookOperation[] }

export class WorkbookDraft {
  operations: WorkbookOperation[] = []
  private candidate?: { proposal: WorkbookProposal; base: string }
  private undoOperations?: WorkbookOperation[]

  setOperations(operations: WorkbookOperation[]) {
    this.operations = structuredClone(operations)
  }

  preview(proposal: WorkbookProposal) {
    this.candidate = { proposal: structuredClone(proposal), base: JSON.stringify(this.operations) }
  }

  reject() { this.candidate = undefined }

  accept() {
    if (!this.candidate || this.candidate.base !== JSON.stringify(this.operations)) {
      throw new Error('工作簿内容已变化，请重新生成候选。')
    }
    this.undoOperations = structuredClone(this.operations)
    this.operations.push(...structuredClone(this.candidate.proposal.operations))
    this.candidate = undefined
  }

  undo() {
    if (this.undoOperations) this.operations = this.undoOperations
    this.undoOperations = undefined
    this.candidate = undefined
  }
}

export type WorkbookSaveResult = { revision: number; revisionRegistered: boolean; editor?: { openUrl: string } }
export type WorkbookSaveOutcome =
  | { kind: 'reopen'; url: string; status: string }
  | { kind: 'locked'; status: string }
  | { kind: 'retry'; status: string }

/**
 * 保存后的去向。已登记的新修订总要结束当前底稿的编辑：否则页面仍持有旧的
 * expectedSha256，再次保存会从同一底稿重复生成修订。只有新修订未登记时才保留草稿供重试。
 */
export function workbookSaveOutcome(result: WorkbookSaveResult): WorkbookSaveOutcome {
  if (result.revisionRegistered && result.editor?.openUrl) {
    return { kind: 'reopen', url: result.editor.openUrl, status: `已保存修订 ${result.revision}` }
  }
  if (result.revisionRegistered) {
    return { kind: 'locked', status: `已保存修订 ${result.revision}；新修订编辑入口暂不可用，请重新打开报告后继续编辑` }
  }
  return { kind: 'retry', status: '文件已保存，修订未登记；草稿已保留，可再次保存' }
}
