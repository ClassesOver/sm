const baseKey = 'genoffice-assistant-preferences'
const identityKey = 'genoffice-assistant-identity'
let identity: string | null = null
try { identity = localStorage.getItem(identityKey) } catch { /* storage unavailable */ }
function currentKey() { return identity ? baseKey + ':' + identity : baseKey }
function assertCurrentIdentity() {
  if (localStorage.getItem(identityKey) !== identity) throw new Error('账户已变化，请重新打开设置。')
}
export function setOfficeAssistantIdentity(value: string | null) {
  identity = value || 'anonymous'
  try { localStorage.setItem(identityKey, identity) } catch { /* disabled browser storage uses defaults */ }
}

export function readOfficeAssistantPreferences(): { side: 'left' | 'right'; openInNewDocs: boolean; fontSize?: number; spellcheck: boolean } {
  try {
    const value = JSON.parse(localStorage.getItem(currentKey()) ?? '{}')
    const fontSize = typeof value?.fontSize === 'number' && Number.isFinite(value.fontSize)
      ? Math.min(32, Math.max(10, Math.round(value.fontSize))) : undefined
    return { side: value?.side === 'right' ? 'right' : 'left',
      openInNewDocs: value?.openInNewDocs !== false, fontSize, spellcheck: value?.spellcheck !== false }
  } catch {
    return { side: 'left', openInNewDocs: true, spellcheck: true }
  }
}

export function saveOfficeAssistantSide(side: 'left' | 'right') {
  assertCurrentIdentity()
  localStorage.setItem(currentKey(), JSON.stringify({...readOfficeAssistantPreferences(),side}))
}

export function watchOfficeAssistantSide(onChange: (side: 'left' | 'right') => void) {
  const sync = (event: StorageEvent) => {
    if (event.key === currentKey() || event.key === identityKey || event.key === null) onChange(readOfficeAssistantPreferences().side)
  }
  window.addEventListener('storage',sync)
  return () => window.removeEventListener('storage',sync)
}

export function showOfficeAssistantPreferences(host: HTMLElement) {
  const preferences = readOfficeAssistantPreferences()
  const openedKey = currentKey()
  const dialog = document.createElement('dialog')
  dialog.className = 'office-administration'
  dialog.addEventListener('click', event => event.stopPropagation())
  const title = document.createElement('h2')
  title.textContent = 'AI 助手设置'
  const form = document.createElement('form')
  const side = document.createElement('select')
  side.setAttribute('aria-label', '侧栏位置')
  side.add(new Option('左侧', 'left'))
  side.add(new Option('右侧', 'right'))
  side.value = preferences.side
  const auto = document.createElement('input')
  auto.type = 'checkbox'
  auto.checked = preferences.openInNewDocs
  const label = document.createElement('label')
  label.append(auto, document.createTextNode('打开文件时显示 AI 助手'))
  const fontSize = document.createElement('input')
  fontSize.type = 'number'
  fontSize.min = '10'
  fontSize.max = '32'
  fontSize.placeholder = '默认'
  fontSize.value = preferences.fontSize === undefined ? '' : String(preferences.fontSize)
  const fontLabel = document.createElement('label')
  fontLabel.append(document.createTextNode('助手字号（px）'), fontSize)
  const spellcheck = document.createElement('input')
  spellcheck.type = 'checkbox'
  spellcheck.checked = preferences.spellcheck
  const spellLabel = document.createElement('label')
  spellLabel.append(spellcheck, document.createTextNode('输入时检查拼写'))
  const save = document.createElement('button')
  save.textContent = '保存'
  const close = document.createElement('button')
  close.type = 'button'
  close.textContent = '取消'
  close.onclick = () => dialog.close()
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  form.append(side, label, fontLabel, spellLabel, save, close)
  form.onsubmit = event => {
    event.preventDefault()
    try {
      assertCurrentIdentity()
      if (currentKey() !== openedKey) throw new Error('账户已变化，请重新打开设置。')
      localStorage.setItem(currentKey(), JSON.stringify({ side: side.value, openInNewDocs: auto.checked,
        fontSize: fontSize.valueAsNumber, spellcheck: spellcheck.checked }))
      dialog.close()
    } catch {
      status.textContent = '浏览器无法保存助手设置。'
    }
  }
  dialog.onclose = () => dialog.remove()
  dialog.append(title, form, status)
  host.append(dialog)
  dialog.showModal()
}
