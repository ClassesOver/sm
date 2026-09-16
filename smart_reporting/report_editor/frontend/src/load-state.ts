interface ErrorWithStatus {
  status?: unknown
}

function statusOf(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined
  const status = (error as ErrorWithStatus).status
  return typeof status === 'number' ? status : undefined
}

function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof Error && /fetch|network|连接/i.test(error.message))
}

export function createLoadStatePanel(root: HTMLElement) {
  const host = root.querySelector<HTMLElement>('.editor-surface') ?? root
  const element = document.createElement('section')
  element.className = 'editor-load-state'
  element.hidden = true
  element.setAttribute('aria-live', 'polite')
  const title = document.createElement('h2')
  const message = document.createElement('p')
  const retry = document.createElement('button')
  retry.type = 'button'
  retry.textContent = '重新加载'
  element.append(title, message, retry)
  host.append(element)

  const show = (nextTitle: string, nextMessage: string, role: 'status' | 'alert', onRetry?: () => void) => {
    title.textContent = nextTitle
    message.textContent = nextMessage
    element.setAttribute('role', role)
    retry.hidden = onRetry === undefined
    retry.onclick = onRetry ?? null
    element.hidden = false
  }

  return {
    element,
    showLoading() {
      show('正在打开报告', '正在验证编辑会话并载入 Markdown…', 'status')
    },
    showError(error: unknown, onRetry: () => void) {
      if (statusOf(error) === 410) {
        show('编辑会话已过期', '请从报告列表重新打开此报告。', 'alert', onRetry)
      } else if (isNetworkError(error)) {
        show('无法连接报告服务', '请检查网络后重试。', 'alert', onRetry)
      } else {
        show('报告暂时无法打开', '请稍后重试；如果问题持续，请联系管理员。', 'alert', onRetry)
      }
    },
    hide() {
      element.hidden = true
    },
  }
}
