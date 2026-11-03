export async function withWorkbookLocked<T>(editor: HTMLElement, action: () => Promise<T>): Promise<T> {
  const wasInert = editor.inert
  editor.inert = true
  try { return await action() }
  finally { editor.inert = wasInert }
}
