import { renderToStaticMarkup } from 'react-dom/server'
import { IconAiPanel } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'

/** 四种原生编辑器复用 GenOffice 助手图标与入口。 */
export function OfficeAIEntry({ onOpen }: { onOpen?: () => void }) {
  return <button type="button" className="office-ai-entry" data-action="ai-assistant"
    aria-label="AI 助手" title={onOpen ? 'AI 助手' : 'AI 助手尚未开放'} disabled={!onOpen} onClick={onOpen}>
    <IconAiPanel size={28} /><span>AI 助手</span>
  </button>
}

export function styleOfficeAIEntry(button: HTMLButtonElement) {
  button.classList.add('office-ai-entry')
  button.dataset.action = 'ai-assistant'
  button.setAttribute('aria-label', 'AI 助手')
  button.innerHTML = renderToStaticMarkup(<><IconAiPanel size={28} /><span>AI 助手</span></>)
}

export function createOfficeAIEntry(onOpen?: () => void) {
  const button = document.createElement('button')
  button.type = 'button'
  styleOfficeAIEntry(button)
  button.disabled = !onOpen
  button.title = onOpen ? 'AI 助手' : 'AI 助手尚未开放'
  if (onOpen) button.addEventListener('click', onOpen)
  return button
}
