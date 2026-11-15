/** Labels for the queued-messages strip above the AI composer (all editors share them). */
export interface AiQueueStripLabels {
  /** collapsed strip title, e.g. "3 queued" */
  queuedCount: (n: number) => string
  clearTitle: string
  editTitle: string
  removeTitle: string
  /** hold the queue: the run in flight finishes, nothing after it starts */
  pauseTitle: string
  /** let the queue run again */
  resumeTitle: string
  /** strip hint while the gate is closed */
  pausedHint: string
  /** row tooltip: press and drag to change the order (Alt+arrows for keyboards) */
  moveTitle: string
  /** composer placeholder while a reply runs and Enter queues instead of sending */
  queuePlaceholder: string
}

export const AI_QUEUE_LABELS: {zh: AiQueueStripLabels} = {
  zh: {
    queuedCount: (n) => `${n} 条排队中`,
    clearTitle: '清空排队消息',
    editTitle: '编辑排队消息',
    removeTitle: '移除排队消息',
    pauseTitle: '暂停排队',
    resumeTitle: '继续排队',
    pausedHint: '已暂停',
    moveTitle: '拖动调整顺序（或 Alt+↑/↓）',
    queuePlaceholder: 'Enter 排队 · Esc 停止',
  },
}
