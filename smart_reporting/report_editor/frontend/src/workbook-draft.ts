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
