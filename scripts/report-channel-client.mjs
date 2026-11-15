// Connector adapters supply authenticated retry-free exchange and browser navigation.
export async function joinReportChannel(link, { origin, exchange, openEditor }) {
  const base = new URL(origin)
  if (base.protocol !== 'https:' || base.href !== base.origin + '/') {
    throw new Error('Invalid report service origin')
  }
  const prefix = base.origin + '/reports/join#'
  const reference = link.slice(prefix.length)
  if (!link.startsWith(prefix) || !/^[A-Za-z0-9_-]{43}$/.test(reference)) {
    throw new Error('Invalid report channel invitation')
  }
  const joined = await exchange(new URL('/reports/v1/channels/invitations/exchange', base), { reference })
  if (typeof joined.editorPath !== 'string' || !joined.editorPath.startsWith('/reports/')) {
    throw new Error('Invalid report editor path')
  }
  const editor = new URL(joined.editorPath, base)
  if (editor.origin !== base.origin || !editor.pathname.startsWith('/reports/') ||
      editor.search || editor.hash) {
    throw new Error('Invalid report editor path')
  }
  if (typeof joined.channel !== 'string' || !joined.channel) {
    throw new Error('Invalid report channel')
  }
  const channelPath = '/reports/v1/channels/' + encodeURIComponent(joined.channel)
  if (joined.messagesPath !== channelPath + '/messages' ||
      (joined.wordTasksPath !== undefined && joined.wordTasksPath !== channelPath + '/word-tasks')) {
    throw new Error('Invalid report channel endpoints')
  }
  await openEditor(editor.href)
  return {
    channel: joined.channel,
    messagesPath: joined.messagesPath,
    ...(joined.wordTasksPath === undefined ? {} : { wordTasksPath: joined.wordTasksPath }),
  }
}
