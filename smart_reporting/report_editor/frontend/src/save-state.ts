export interface SaveStateTracker {
  readonly pendingChanges: number
  readonly hasUnsavedChanges: boolean
  readonly shouldWarnBeforeUnload: boolean
  edit(markdown: string): void
  beginSave(): void
  saved(markdown: string): void
  saveFailed(): void
  reset(markdown: string): void
  savedLabel(): string
  dirtyLabel(offline: boolean): string
}

export function createSaveStateTracker(
  initialMarkdown: string,
  now: () => Date = () => new Date(),
): SaveStateTracker {
  let savedMarkdown = initialMarkdown
  let currentMarkdown = initialMarkdown
  let pendingChanges = 0
  let currentVersion = 0
  let savingVersion = 0
  let saving = false
  let lastSavedAt = now()

  const tracker: SaveStateTracker = {
    get pendingChanges() {
      return pendingChanges
    },
    get hasUnsavedChanges() {
      return currentMarkdown !== savedMarkdown
    },
    get shouldWarnBeforeUnload() {
      return saving || currentMarkdown !== savedMarkdown
    },
    edit(markdown) {
      if (markdown === currentMarkdown) return
      currentMarkdown = markdown
      currentVersion += 1
      pendingChanges = markdown === savedMarkdown ? 0 : pendingChanges + 1
    },
    beginSave() {
      saving = true
      savingVersion = currentVersion
    },
    saved(markdown) {
      savedMarkdown = markdown
      saving = false
      lastSavedAt = now()
      pendingChanges = currentMarkdown === markdown
        ? 0
        : Math.max(1, currentVersion - savingVersion)
    },
    saveFailed() {
      saving = false
    },
    reset(markdown) {
      savedMarkdown = markdown
      currentMarkdown = markdown
      pendingChanges = 0
      currentVersion = 0
      savingVersion = 0
      saving = false
      lastSavedAt = now()
    },
    savedLabel() {
      return `已保存 · ${new Intl.DateTimeFormat('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
      }).format(lastSavedAt)}`
    },
    dirtyLabel(offline) {
      const prefix = offline ? '离线' : '有未保存更改'
      return `${prefix} · ${pendingChanges} 次编辑待同步`
    },
  }
  return tracker
}
