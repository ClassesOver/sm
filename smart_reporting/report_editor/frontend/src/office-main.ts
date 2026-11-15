import { setOfficeAssistantIdentity } from './office-assistant-preferences'
import {openInlineFolder, renameInlineItem} from './office-inline-folder'
import type { renderOfficeAnswer } from './office-answer'
import { applyOfficeTheme, loadOfficePreferences, refreshOfficeTheme } from './office-personal-theme'
import { bm25Score, mergeSearchCorpus, type SearchCorpus } from './office-search-rank'
import './office.css'
import { officeRequest, officeSession, loginOffice, OfficeRequestError, type OfficeLibrary, type OfficeSpace, type OfficeUser } from './office-client'
import { showOfficeAdministration } from './office-administration'
import { showOfficeSources } from './office-sources'
import { showOfficeFileActions, type OfficeFileAction } from './office-file-actions'

const formats = {
  docx: ['AI Docs', '文档', '未命名文档'],
  xlsx: ['AI Sheets', '表格', '未命名表格'],
  pptx: ['AI Slides', '演示', '未命名演示'],
  pdf: ['AI PDF', 'PDF', '未命名 PDF'],
} as const
type Format = keyof typeof formats
type Folder = { id: string; parent: string; name: string }
type Entry = { id: string; space: string; version: number; revision: number; name: string; format: Format; folder: string; path: string; seen: number; starred: boolean; recentHidden?: boolean; favoriteGroup?: string | null }
type Workspace = { folders: Folder[]; entries: Entry[] }
type View = 'recent' | 'starred' | 'ask' | 'folder'
type KnowledgeTurn = { id: string; question: string; answer: string; citations: { fileId: string; name: string; revision: number }[] }

const root = document.querySelector<HTMLElement>('#office')!
const assets = `${import.meta.env.BASE_URL}office/`
const rootFolder = 'root'
let library: Workspace = { folders: [], entries: [] }
let currentUser: OfficeUser | undefined
let spaces: OfficeSpace[] = []
let currentSpace = ''
const tabEntries = new Map<string, Entry>()
const closedTabs: Entry[] = []
let view: View = 'recent'
let folder = rootFolder
let filter: Format | '' = ''
let favoriteGroup = ''
let sortByName = false
let selectedTab = ''
let sidebarHidden = false
let busy = false
let status = ''
const collapsed = new Set<string>()
const selectedFiles = new Set<string>()
let folderTreeKey = ''
const tabs = new Map<string, HTMLIFrameElement>()
const activeKnowledgeConversation = new Map<string, string>()
const newKnowledgeConversations = new Map<string, string>()
const knowledgeConversations = new Map<string, {id: string; title: string}[]>()
const conversationOf = (space: string) => activeKnowledgeConversation.get(space) ?? 'default'
const draftKey = (space: string) => space + '/' + conversationOf(space)
let formatOfficeAnswer: typeof renderOfficeAnswer | undefined
const knowledgeTurns = new Map<string, KnowledgeTurn[]>()
const savedKnowledgeDocuments = new Map<string, string>()
const knowledgeInputs = new Map<string, string>()
const knowledgePending = new Map<string, AbortController>()
const knowledgeAttachments = new Map<string, string[]>()
let accountGeneration = 0
let spacesRequest = 0
const knowledgeGeneration = new Map<string, number>()

const paths = {
  home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-6h6v6"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2-5.5-2.9-5.5 2.9 1-6.2L3 9.6l6.2-.9z"/>',
  chat: '<path d="M4 4h16v12H9l-5 4zM8 8h8m-8 4h6"/>',
  folder: '<path d="M3 6h7l2 3h9v11H3z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  file: '<path d="M5 2h9l5 5v15H5zM14 2v6h5"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  sort: '<path d="M3 7h8M3 12h6m-6 5h4m10 2V5m-4 4 4-4 4 4"/>',
  book: '<path d="M12 20c-3-3-7-3-9-3V4c4 0 7 1 9 3 2-2 5-3 9-3v13c-2 0-6 0-9 3V7"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
}

function icon(name: keyof typeof paths, size = 16) {
  return `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name]}</svg>`
}

function escape(value: string) {
  const element = document.createElement('span')
  element.textContent = value
  return element.innerHTML.replaceAll('"', '&quot;')
}

function loadFolderTree() {
  const key = currentUser && currentSpace ? `genoffice:folder-tree:${JSON.stringify([currentUser.user, currentSpace])}` : ''
  if (key !== folderTreeKey) {
    folderTreeKey = key
    collapsed.clear()
    if (!key) return
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
      if (Array.isArray(saved)) for (const id of saved) if (typeof id === 'string') collapsed.add(id)
    } catch { /* Storage may be unavailable. */ }
  }
  const existing = new Set(library.folders.map(item => item.id))
  for (const id of collapsed) if (!existing.has(id)) collapsed.delete(id)
}

function setFolderCollapsed(id: string, value: boolean) {
  if (collapsed.has(id) === value) return false
  if (value) collapsed.add(id)
  else collapsed.delete(id)
  if (folderTreeKey) {
    try { localStorage.setItem(folderTreeKey, JSON.stringify([...collapsed])) }
    catch { /* The in-memory tree is still usable. */ }
  }
  return true
}

async function refreshLibrary() {
  if (!currentSpace) return
  const selectedSpace = currentSpace
  const account = accountGeneration
  const result = await officeRequest<OfficeLibrary>(`/workspaces/${selectedSpace}/library`)
  if (account !== accountGeneration || selectedSpace !== currentSpace) return
  installLibrary(result)
}

function installLibrary(result: OfficeLibrary) {
  library = {
    folders: result.folders.map(item => ({ ...item, parent: item.parent ?? rootFolder })),
    entries: result.files.map(item => ({
      ...item, folder: item.folder ?? rootFolder,
      path: `/reports/v1/native/${item.document}/${item.revision}`,
    })),
  }
  loadFolderTree()
}

async function refreshSpaces() {
  const account = accountGeneration
  const request = ++spacesRequest
  const result = await officeRequest<{ items: OfficeSpace[] }>('/workspaces')
  if (account !== accountGeneration || request !== spacesRequest) return
  spaces = result.items
  if (!spaces.some(item => item.id === currentSpace)) currentSpace = spaces[0]?.id ?? ''
  await refreshLibrary()
}

function clearAccount() {
  accountGeneration += 1
  busy = false
  applyOfficeTheme('system')
  setOfficeAssistantIdentity(null)
  for (const frame of tabs.values()) frame.remove()
  tabs.clear(); tabEntries.clear()
  closedTabs.length = 0
  knowledgeTurns.clear(); knowledgeInputs.clear(); knowledgeAttachments.clear(); savedKnowledgeDocuments.clear()
  for (const controller of knowledgePending.values()) controller.abort()
  knowledgePending.clear(); knowledgeGeneration.clear(); activeKnowledgeConversation.clear(); newKnowledgeConversations.clear(); knowledgeConversations.clear()
  currentUser = undefined; spaces = []; currentSpace = ''; selectedTab = ''
  library = { folders: [], entries: [] }
  favoriteGroup = ''
  folderTreeKey = ''
  collapsed.clear()
  selectedFiles.clear()
  folder = rootFolder
  view = 'recent'
  filter = ''
}

window.addEventListener('genoffice-session-expired', () => {
  clearAccount()
  for (const dialog of root.querySelectorAll('dialog[open]')) (dialog as HTMLDialogElement).close()
  status = '登录已失效，请重新登录。'
  render()
})

function openPersonalSettings(initialSection: 'account' | 'general' = 'account') {
  if (!currentUser) return
  const account = accountGeneration, user = currentUser
  void import('./office-settings').then(({ showOfficeSettings }) => showOfficeSettings(root, { user, initialSection, isCurrent: () => account === accountGeneration,
    onLogout: () => { clearAccount(); render() } })).catch(error => { status = error.message; render() })
}
function openRequestedPreferences() {
  const url = new URL(window.location.href)
  if (currentUser && url.searchParams.get('settings') === 'preferences') {
    url.searchParams.delete('settings'); history.replaceState(null, '', url)
    openPersonalSettings('general')
  }
}

async function start() {
  const account = ++accountGeneration
  try {
    const user = await officeSession()
    if (account !== accountGeneration) return
    currentUser = user
    await loadOfficePreferences(() => account === accountGeneration)
    if (account !== accountGeneration) return
    await refreshSpaces()
    if (account !== accountGeneration) return
    status = ''
  } catch (error) { if (account === accountGeneration) status = error instanceof Error ? error.message : 'Office 登录失败。' }
  if (account === accountGeneration) { render(); openRequestedPreferences() }
}

function showLogin() {
  const dialog = document.createElement('dialog')
  dialog.className = 'office-administration'
  dialog.innerHTML = '<h2>登录 GenOffice</h2><form><label>组织域<input name="database" required></label><label>公司<input name="company" required></label><label>账号<input name="user" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><button>登录</button><button type="button" data-dismiss>取消</button></form><p role="status"></p>'
  dialog.addEventListener('click', event => event.stopPropagation())
  dialog.onclose = () => dialog.remove()
  dialog.querySelector<HTMLButtonElement>('[data-dismiss]')!.onclick = () => dialog.close()
  const form = dialog.querySelector('form')!
  const submit = form.querySelector('button')!
  form.onsubmit = async event => {
    event.preventDefault()
    if (submit.disabled) return
    submit.disabled = true
    const account = ++accountGeneration
    try {
      const user = await loginOffice(Object.fromEntries(new FormData(form)) as Record<string, string>)
      if (account !== accountGeneration) return
      currentUser = user
      await loadOfficePreferences(() => account === accountGeneration)
      if (account !== accountGeneration) return
      await refreshSpaces()
      if (account !== accountGeneration) return
      status = ''
      dialog.close()
      render()
      openRequestedPreferences()
    } catch (error) {
      if (account === accountGeneration) dialog.querySelector('p')!.textContent = error instanceof Error ? error.message : '登录失败。'
    } finally { submit.disabled = false }
  }
  root.append(dialog)
  dialog.showModal()
}

function badge(format: Format, size = 30) {
  return `<img src="${assets}file-${format}.svg" width="${size}" height="${size}" alt="">`
}

function folderTree(parent: string, depth: number): string {
  const children = parent === '' ? [{ id: rootFolder, parent: '', name: 'GenOffice' }] :
    library.folders.filter(item => item.parent === parent)
  return children.map(item => `<div class="folder-row ${view === 'folder' && folder === item.id ? 'active' : ''}" style="--depth:${depth}" data-drop-folder="${escape(item.id)}">
    <button data-collapse="${escape(item.id)}" aria-label="${collapsed.has(item.id) ? '展开' : '折叠'} ${escape(item.name)}" aria-expanded="${!collapsed.has(item.id)}">${icon('chevron', 12)}</button>
    <button data-folder="${escape(item.id)}" ${item.id !== rootFolder && canWrite() ? 'draggable="true"' : ''}>${icon('folder')} ${escape(item.name)}</button>
    ${item.id !== rootFolder && canWrite() ? `<button class="folder-actions" data-folder-actions="${escape(item.id)}" aria-label="管理文件夹 ${escape(item.name)}">${icon('more', 12)}</button>` : ''}
  </div>${collapsed.has(item.id) ? '' : folderTree(item.id, depth + 1)}`).join('')
}

function nav(item: View, label: string, glyph: keyof typeof paths, count?: number) {
  return `<button data-view="${item}" ${item === 'ask' && !currentSpace ? 'disabled' : ''} class="nav ${view === item ? 'active' : ''}">${icon(glyph)}${label}${count === undefined ? '' : `<small>${count}</small>`}</button>`
}

function quickStart() {
  return `<div class="quick-cards">${Object.entries(formats).map(([format, [title]]) =>
    `<button class="quick-card" data-new="${format}" ${canWrite() ? '' : 'disabled'}>${badge(format as Format)}<span><strong>${title}</strong> <b>AI</b><small>.${format}</small></span></button>`).join('')}
    <button class="quick-card" data-action="browse" ${canWrite() ? '' : 'disabled'}><span class="open-icon">${icon('folder', 19)}</span><span><strong>打开本地文件</strong><small>.docx / .xlsx / .pptx / .pdf</small></span></button></div>`
}

function canSendKnowledge(draft: string) {
  return Boolean(currentUser && currentSpace && draft.trim() && !busy &&
    knowledgeConversations.has(currentSpace) && !knowledgePending.has(currentSpace))
}

function knowledgeWordKey(turn: string) {
  return 'genoffice:knowledge-word:' + JSON.stringify([currentUser?.user, currentSpace, conversationOf(currentSpace), turn])
}

function knowledgeWordAction(turn: KnowledgeTurn) {
  if (!turn.citations.length) return ''
  const key = knowledgeWordKey(turn.id)
  let fileId = savedKnowledgeDocuments.get(key)
  if (!fileId) {
    try { fileId = sessionStorage.getItem(key) ?? undefined } catch { /* Session storage is optional. */ }
  }
  const file = fileId && library.entries.find(item => item.id === fileId)
  const disabled = busy ? 'disabled' : ''
  if (file) return `<div class="kb-citations"><button data-open-answer-docx="${escape(file.id)}" ${disabled}>打开已保存的 ${escape(file.name)}</button></div>`
  return canWrite() ? `<div class="kb-citations"><button data-answer-docx="${escape(turn.id)}" ${disabled}>另存为 Word</button></div>` : ''
}

function knowledgeDraftStorageKey(space: string, conversation: string) {
  return 'genoffice:knowledge-draft:' + JSON.stringify([currentUser?.user, space, conversation])
}

function createKnowledgeConversation(space: string) {
  const id = crypto.randomUUID()
  newKnowledgeConversations.set(space, id)
  return id
}

function canStoreKnowledgeDraft(space: string, conversation: string) {
  return newKnowledgeConversations.get(space) === conversation ||
    knowledgeConversations.get(space)?.some(item => item.id === conversation)
}

function rememberNewKnowledgeDraft(space: string, conversation: string) {
  if (newKnowledgeConversations.get(space) === conversation && conversationOf(space) === conversation) {
    sessionStorage.setItem(knowledgeConversationKey(space), 'new:' + conversation)
  }
}

function knowledgeDraft(space: string): string {
  const cached = knowledgeInputs.get(draftKey(space))
  if (cached !== undefined) return cached
  try { return sessionStorage.getItem(knowledgeDraftStorageKey(space, conversationOf(space))) ?? '' }
  catch { return '' }
}

function setKnowledgeDraft(space: string, value: string, conversation = conversationOf(space)) {
  const key = space + '/' + conversation
  if (value) knowledgeInputs.set(key, value)
  else knowledgeInputs.delete(key)
  const storageKey = knowledgeDraftStorageKey(space, conversation)
  try {
    if (!value) sessionStorage.removeItem(storageKey)
    else if (canStoreKnowledgeDraft(space, conversation)) {
      sessionStorage.setItem(storageKey, value)
      rememberNewKnowledgeDraft(space, conversation)
    }
  } catch { /* The in-page draft is still available. */ }
}

function knowledgeDraftAttachments(space: string): Entry[] {
  if (space !== currentSpace) return []
  let ids = knowledgeAttachments.get(draftKey(space))
  if (!ids) {
    try {
      const stored: unknown = JSON.parse(sessionStorage.getItem(knowledgeDraftStorageKey(space, conversationOf(space)) + ':attachments') ?? 'null')
      if (Array.isArray(stored)) ids = stored.filter((id): id is string => typeof id === 'string').slice(0, 10)
    } catch { /* No recoverable attachment IDs. */ }
  }
  return [...new Set(ids)].flatMap(id => library.entries.find(item => item.id === id && item.space === space) ?? [])
}

function setKnowledgeDraftAttachments(space: string, ids: string[], conversation = conversationOf(space)) {
  const key = space + '/' + conversation
  if (ids.length) knowledgeAttachments.set(key, ids)
  else knowledgeAttachments.delete(key)
  const storageKey = knowledgeDraftStorageKey(space, conversation) + ':attachments'
  try {
    if (!ids.length) sessionStorage.removeItem(storageKey)
    else if (canStoreKnowledgeDraft(space, conversation)) {
      sessionStorage.setItem(storageKey, JSON.stringify(ids))
      rememberNewKnowledgeDraft(space, conversation)
    }
  } catch { /* Keep the in-page attachments. */ }
}

function chooseWorkspaceAttachments() {
  const space = currentSpace, conversation = conversationOf(space), account = accountGeneration
  if (!space || busy || !knowledgeConversations.has(space) || knowledgePending.has(space)) return
  const current = new Set(knowledgeDraftAttachments(space).map(file => file.id))
  const candidates = library.entries.filter(file => file.space === space && !current.has(file.id))
  const location = workspaceFileLocation()
  const dialog = document.createElement('dialog')
  dialog.className = 'office-administration office-attachment-picker'
  dialog.setAttribute('aria-label', '从工作区选择附件')
  dialog.innerHTML = `<h2>从工作区选择附件</h2><form>
    <label>筛选文件<input type="text" maxlength="160" autofocus></label>
    <fieldset><legend>工作区文件</legend>${candidates.map(file => `<label>
      <input type="checkbox" aria-label="${escape(file.name)}" value="${escape(file.id)}">
      <span>${escape(file.name)}</span><small>${escape(location(file.folder))}</small></label>`).join('')}
      <p data-empty-files hidden>没有可添加的文件。</p>
    </fieldset>
    <button type="submit" disabled>添加所选文件</button><button type="button" data-close>取消</button>
    <p role="status"></p></form>`
  dialog.addEventListener('click', event => event.stopPropagation())
  dialog.onclose = () => dialog.remove()
  const form = dialog.querySelector('form')!
  const filter = form.querySelector<HTMLInputElement>('[type=text]')!
  const submit = form.querySelector<HTMLButtonElement>('[type=submit]')!
  const choices = [...form.querySelectorAll<HTMLInputElement>('[type=checkbox]')]
  const selected = () => choices.filter(choice => choice.checked).map(choice => choice.value)
  const empty = form.querySelector<HTMLElement>('[data-empty-files]')!
  empty.hidden = choices.length > 0
  filter.oninput = () => {
    const query = filter.value.trim().toLowerCase()
    let visible = 0
    for (const choice of choices) {
      const row = choice.closest('label')!
      row.hidden = !row.textContent!.toLowerCase().includes(query)
      if (!row.hidden) visible++
    }
    empty.hidden = visible > 0
  }
  form.onchange = () => { submit.disabled = !selected().length }
  form.onsubmit = event => {
    event.preventDefault()
    if (account !== accountGeneration || space !== currentSpace || conversation !== conversationOf(space) || knowledgePending.has(space)) {
      dialog.close()
      return
    }
    const choices = new Set(selected())
    const next = [...knowledgeDraftAttachments(space).map(file => file.id),
      ...library.entries.filter(file => file.space === space && choices.has(file.id)).map(file => file.id)]
    if (new Set(next).size > 10) {
      form.querySelector('[role=status]')!.textContent = '一次最多添加 10 个附件。'
      return
    }
    setKnowledgeDraftAttachments(space, [...new Set(next)], conversation)
    dialog.close()
    render()
    root.querySelector<HTMLTextAreaElement>('.composer textarea')?.focus()
  }
  form.querySelector<HTMLButtonElement>('[data-close]')!.onclick = () => dialog.close()
  root.append(dialog)
  dialog.showModal()
}

function ask() {
  const turns = knowledgeTurns.get(currentSpace) ?? []
  const pending = knowledgePending.has(currentSpace)
  const conversation = conversationOf(currentSpace)
  const key = draftKey(currentSpace)
  const ready = knowledgeConversations.has(currentSpace)
  const draft = ready ? knowledgeDraft(currentSpace) : ''
  const canSend = canSendKnowledge(draft)
  const pendingQuestion = pending ? draft.trim() : ''
  const hasMessages = turns.length > 0 || Boolean(pendingQuestion)
  const conversations = knowledgeConversations.get(currentSpace) ?? []
  const listed = conversations.some(item => item.id === conversation)
  return `<section class="kb">
    <div class="kb-citations">
      <button data-action="kb-new" ${pending || busy || !currentUser ? 'disabled' : ''}>新对话</button>
      <select aria-label="问答会话" ${pending || busy || !currentUser ? 'disabled' : ''}>
        ${listed ? '' : `<option value="${escape(conversation)}">当前对话</option>`}
        ${conversations.map(item => `<option value="${escape(item.id)}" ${item.id === conversation ? 'selected' : ''}>${escape(item.title)}</option>`).join('')}
      </select>
      ${listed ? `<button data-action="kb-delete" ${pending || busy ? 'disabled' : ''}>删除会话</button>` : ''}
    </div>
    <div class="kb-thread ${hasMessages ? 'has-messages' : ''}" data-thread="${escape(key)}" data-last-turn="${escape(pendingQuestion ? 'pending' : turns.at(-1)?.id ?? '')}">${hasMessages ? turns.map(turn => `<article class="kb-turn">
      <div class="kb-question">${escape(turn.question)}</div><div class="kb-answer">${formatOfficeAnswer?.(turn.answer) ?? escape(turn.answer)}</div>
      ${knowledgeWordAction(turn)}
      <div class="kb-citations">${turn.citations.map(citation => `<button data-citation="${escape(citation.fileId)}" data-revision="${citation.revision}">${icon('file', 14)} ${escape(citation.name)} · 修订 ${citation.revision}</button>`).join('')}</div>
    </article>`).join('') : `<div class="kb-hero">
      <span class="kb-icon">${icon('book', 22)}</span><h2>问知识库</h2>
      <p>把常读的文件点上星，AI 就能跨文件检索、引用原文回答<br>——来源点一下就能打开。</p>
      <div class="kb-steps">${[['收藏文件', '在最近或文件夹里，点文件行上的星标'], ['回来提问', '像聊天一样问，不用先打开任何文档'], ['点击引用', '回答标注来源文件，点引用直接跳过去']].map(([title, body], i) => `<div><b>${i + 1}</b><span>${title}<small>${body}</small></span></div>`).join('')}</div>
      <button class="kb-cta" data-view="recent">${icon('star', 14)} 去最近文件收藏</button>
    </div>`}${pendingQuestion ? `<article class="kb-turn" aria-busy="true"><div class="kb-question">${escape(pendingQuestion)}</div></article>` : ''}</div>
    <div class="kb-bottom"><p aria-live="polite">${pending ? '正在检索和阅读工作区资料…' : `当前工作区已收藏 ${library.entries.filter(item => item.starred).length} 个文件。回答会注明来源文件。`}</p><div class="composer">
      <div class="kb-citations">${(ready ? knowledgeDraftAttachments(currentSpace) : []).map(file =>
        `<button data-remove-attachment="${escape(file.id)}" ${pending ? 'disabled' : ''}
          aria-label="移除附件 ${escape(file.name)}">${escape(file.name)} ×</button>`).join('')}</div>
      <textarea aria-label="向知识库提问" placeholder="问一个关于收藏文件的问题…" maxlength="8000" ${pending || !ready || !currentUser ? 'disabled' : ''}>${pending ? '' : escape(draft)}</textarea>
      <div><span class="kb-model">默认模型</span><button data-action="kb-attach" ${ready && canWrite() && !pending ? '' : 'disabled'} aria-label="添加附件">${icon('plus')}</button>
      <button data-action="kb-choose-attachment" ${ready && !pending && !busy && library.entries.length ? '' : 'disabled'}>从工作区选择附件</button>
      ${pending ? '<button data-action="kb-stop" class="send">停止</button>' :
        `<button data-action="kb-send" ${canSend ? '' : 'disabled'} class="send" aria-label="发送"><img alt="" src="${assets}send-enter-${canSend ? 'on' : 'off'}.png"></button>`}</div>
    </div></div></section>`
}

function advanceKnowledgeGeneration(space: string) {
  const generation = (knowledgeGeneration.get(space) ?? 0) + 1
  knowledgeGeneration.set(space, generation)
  return generation
}

function invalidateKnowledge(space: string) {
  knowledgeTurns.delete(space)
  return advanceKnowledgeGeneration(space)
}

function knowledgeConversationKey(space: string) {
  return 'genoffice:knowledge-conversation:' + JSON.stringify([currentUser?.user, space])
}

async function loadKnowledge(space = currentSpace, { preserveTurns = false } = {}) {
  if (!space) return
  const account = accountGeneration
  const generation = preserveTurns ? advanceKnowledgeGeneration(space) : invalidateKnowledge(space)
  try {
    const listing = officeRequest<{ items: {id: string; title: string}[] }>(`/workspaces/${space}/knowledge/conversations`)
    let conversation = activeKnowledgeConversation.get(space)
    if (!conversation) {
      const { items } = await listing
      if (account !== accountGeneration || generation !== (knowledgeGeneration.get(space) ?? 0)) return
      let saved: string | null = null
      try {
        saved = sessionStorage.getItem(knowledgeConversationKey(space))
        const unsent = saved?.match(/^new:([0-9a-f-]{36})$/)?.[1]
        if (unsent && !items.some(item => item.id === unsent)) {
          const draftKey = knowledgeDraftStorageKey(space, unsent)
          if (sessionStorage.getItem(draftKey) || sessionStorage.getItem(draftKey + ':attachments')) {
            newKnowledgeConversations.set(space, unsent)
            conversation = unsent
          }
        }
      } catch { /* Use the normal default. */ }
      conversation ??= items.find(item => item.id === saved || 'new:' + item.id === saved)?.id ??
        items.find(item => item.id === 'default')?.id ?? items[0]?.id ?? createKnowledgeConversation(space)
    }
    const [result, conversations] = await Promise.all([
      officeRequest<{ items: KnowledgeTurn[] }>(`/workspaces/${space}/knowledge?conversation=${encodeURIComponent(conversation)}`),
      listing,
    ])
    if (account !== accountGeneration || generation !== (knowledgeGeneration.get(space) ?? 0)) return
    if (result.items.length && !formatOfficeAnswer) {
      try { formatOfficeAnswer = (await import('./office-answer')).renderOfficeAnswer } catch { /* plain text remains available */ }
      if (account !== accountGeneration || generation !== (knowledgeGeneration.get(space) ?? 0)) return
    }
    activeKnowledgeConversation.set(space, conversation)
    knowledgeTurns.set(space, result.items)
    knowledgeConversations.set(space, conversations.items)
    if (conversations.items.some(item => item.id === conversation)) {
      if (newKnowledgeConversations.get(space) === conversation) newKnowledgeConversations.delete(space)
      try { sessionStorage.setItem(knowledgeConversationKey(space), conversation) } catch { /* Page state remains available. */ }
    }
  } catch (error) {
    if (account !== accountGeneration || generation !== (knowledgeGeneration.get(space) ?? 0)) return
    if (error instanceof OfficeRequestError && error.status === 403) {
      knowledgeTurns.delete(space)
      knowledgeConversations.delete(space)
    }
    if (currentSpace === space) status = error instanceof Error ? error.message : '无法读取问答记录。'
  }
  if (currentSpace === space && view === 'ask') render()
}

async function sendKnowledge() {
  const space = currentSpace
  const account = accountGeneration
  const conversation = conversationOf(space)
  const question = knowledgeDraft(space).trim()
  if (!canSendKnowledge(question)) return
  knowledgeGeneration.set(space, (knowledgeGeneration.get(space) ?? 0) + 1)
  const controller = new AbortController()
  knowledgePending.set(space, controller); status = ''; render()
  try {
    const turn = await officeRequest<KnowledgeTurn>(`/workspaces/${space}/knowledge`, 'POST', { question, conversation, attachmentIds: knowledgeDraftAttachments(space).map(file => file.id) }, controller.signal)
    if (account !== accountGeneration || controller.signal.aborted) return
    setKnowledgeDraft(space, '', conversation)
    setKnowledgeDraftAttachments(space, [], conversation)
    if (conversationOf(space) === conversation) {
      const turns = knowledgeTurns.get(space) ?? []
      knowledgeTurns.set(space, [...turns.filter(item => item.id !== turn.id), turn].slice(-30))
      if (currentSpace === space && view === 'ask') render()
    }
    await loadKnowledge(space, { preserveTurns: true })
  } catch (error) { if (account === accountGeneration && currentSpace === space) status = controller.signal.aborted ? '已停止问答。' : error instanceof Error ? error.message : '知识问答失败。' }
  finally { if (account === accountGeneration) { knowledgePending.delete(space); if (currentSpace === space) render() } }
}

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return '早上好。'
  return hour < 18 ? '下午好。' : '晚上好。'
}

function home() {
  const heading = view === 'recent' ? `<h1>${greeting()}<span>今天从哪里开始？</span></h1>` :
    view === 'folder' ? '<h2 class="quick-heading">快速开始</h2>' : '<h1>收藏</h1>'
  return `<section class="workspace">${heading}${view === 'starred' ? '' : quickStart()}
    <div class="toolbar">
      <div class="filters" aria-label="文件类型">${[['', '全部'], ...Object.entries(formats).map(([name, [, label]]) => [name, label])].map(([value, label]) =>
    `<button data-filter="${value}" class="${value === filter ? 'active' : ''}">${label}</button>`).join('')}</div>
      <label class="search">${icon('search', 14)}<input type="search" maxlength="160" placeholder="搜索文件、文件夹或正文…" aria-label="搜索文件、文件夹或正文" aria-keyshortcuts="Control+F Control+P Meta+F Meta+P"></label>
      <button class="sort" data-action="sort" aria-label="切换按名称排序" aria-pressed="${sortByName}">${icon('sort')}</button>
      <button type="button" data-action="rerank-search" title="将查询和当前文件结果的短片段提交给已配置的 AI 模型" hidden>AI 重排</button>
      <span class="file-count"></span>
    </div>
    <div class="filters" aria-label="收藏分组" data-favorite-groups hidden></div>
    <div class="office-file-selection" hidden></div><div class="file-list"></div></section>`
}

type TextHit = {
  id: string; revision: number; length: number; frequencies: number[]; exactTerms: number; matchedTerms: number; complete: boolean; snippet: string
  nameStartsWithQuery: boolean; metadataMatch: boolean; relaxedCoverage: number
}
let textSearch: AbortController | undefined
let textSearchTimer: ReturnType<typeof setTimeout> | undefined
type SearchResult = {
  input: HTMLInputElement; hits: TextHit[]; corpus: SearchCorpus; searching: boolean; failed: boolean
  modelOrder?: string[]; rerankPending?: boolean; rerankUnavailable?: boolean
}
let searchResult: SearchResult | undefined

function favoriteGroups(): string[] {
  return [...new Set(library.entries.flatMap(item => item.starred && item.favoriteGroup ? [item.favoriteGroup] : []))]
}

function showFavoriteGroups(entries: Entry[]) {
  const space = currentSpace, account = accountGeneration
  const dialog = document.createElement('dialog')
  dialog.className = 'office-administration'
  dialog.setAttribute('aria-label', '收藏分组')
  dialog.innerHTML = `<h2>收藏分组</h2><form><label>分组名称<input name="group" list="office-favorite-group-options" maxlength="80" required></label>
    <datalist id="office-favorite-group-options">${favoriteGroups().map(name => `<option value="${escape(name)}"></option>`).join('')}</datalist>
    <button type="submit">保存分组</button><button type="button" data-clear>移出分组</button><button type="button" data-close>取消</button></form><p role="status"></p>`
  dialog.addEventListener('click', event => event.stopPropagation())
  dialog.onclose = () => dialog.remove()
  const form = dialog.querySelector('form')!
  const input = form.querySelector('input')!
  if (entries.every(item => item.favoriteGroup === entries[0].favoriteGroup)) input.value = entries[0].favoriteGroup ?? ''
  let submitting = false
  async function save(group: string | null) {
    if (submitting || account !== accountGeneration || space !== currentSpace) return
    submitting = true
    for (const button of form.querySelectorAll('button')) button.disabled = true
    try {
      await officeRequest(`/workspaces/${encodeURIComponent(space)}/files/bulk`, 'POST', {
        action: 'group', group, versions: Object.fromEntries(entries.map(item => [item.id, item.version])),
      })
      if (account !== accountGeneration || space !== currentSpace) return
      for (const item of entries) selectedFiles.delete(item.id)
      await refreshLibrary()
      if (account !== accountGeneration || space !== currentSpace) return
      dialog.close()
      render()
    } catch (error) {
      dialog.querySelector('p')!.textContent = error instanceof Error ? error.message : '收藏分组保存失败。'
    } finally {
      submitting = false
      for (const button of form.querySelectorAll('button')) button.disabled = false
    }
  }
  form.onsubmit = event => {
    event.preventDefault()
    const name = input.value.trim()
    if (name) void save(name)
  }
  form.querySelector<HTMLButtonElement>('[data-clear]')!.onclick = () => { void save(null) }
  form.querySelector<HTMLButtonElement>('[data-close]')!.onclick = () => dialog.close()
  root.append(dialog)
  dialog.showModal()
  input.select()
}

function workspaceFileLocation() {
  const workspaceName = spaces.find(space => space.id === currentSpace)?.name ?? 'GenOffice'
  const foldersById = new Map(library.folders.map(item => [item.id, item]))
  return (id: string) => {
    const ancestors: string[] = []
    const visited = new Set<string>()
    let item = foldersById.get(id)
    while (item && !visited.has(item.id)) {
      visited.add(item.id)
      ancestors.push(item.name)
      item = foldersById.get(item.parent)
    }
    return [workspaceName, ...ancestors.reverse()].join(' / ')
  }
}

function renderEntries() {
  const list = root.querySelector('.file-list')
  if (!list) return
  const groupBar = root.querySelector<HTMLElement>('[data-favorite-groups]')!
  const groups = view === 'starred' ? favoriteGroups() : []
  if (!groups.includes(favoriteGroup)) favoriteGroup = ''
  groupBar.hidden = groups.length === 0
  groupBar.innerHTML = groups.length ? ['', ...groups].map(group => `<button data-favorite-group="${escape(group)}" class="${group === favoriteGroup ? 'active' : ''}" aria-pressed="${group === favoriteGroup}">${escape(group || '全部')}</button>`).join('') : ''
  const input = root.querySelector<HTMLInputElement>('input[type=search]')
  const query = input?.value.trim().toLowerCase() ?? ''
  const result = searchResult?.input === input ? searchResult : undefined
  const { hits, corpus, searching, failed } = result ?? { hits: [], corpus: undefined, searching: false, failed: false }
  const byId = new Map(hits.map(hit => [hit.id, hit]))
  const match = (item: Entry) => {
    const hit = byId.get(item.id)
    return hit?.revision === item.revision ? hit : undefined
  }
  const folderResults = !filter && (view === 'folder' || (view === 'recent' && query)) ? library.folders.filter(item =>
    (view !== 'folder' || item.parent === folder) && item.name.toLowerCase().includes(query)) : []
  const eligible = library.entries.filter(item =>
    (view !== 'folder' || item.folder === folder) && (view !== 'starred' || (item.starred && (!favoriteGroup || item.favoriteGroup === favoriteGroup))) &&
    (view !== 'recent' || query || !item.recentHidden) &&
    (!filter || item.format === filter) && (!query || match(item)))
  const complete = query ? eligible.filter(item => match(item)?.complete) : eligible
  const entries = complete.length || searching || failed ? complete : eligible
  const scores = new Map(corpus ? hits.map(hit => [hit.id, bm25Score(hit.length, hit.frequencies, corpus)]) : [])
  const modelOrder = new Map(result?.modelOrder?.map((id, index) => [id, index]))
  const partial = Boolean(query && entries.length && !complete.length)
  entries.sort((a, b) => {
    if (sortByName) return a.name.localeCompare(b.name, 'zh-CN')
    const preferred = (modelOrder.get(a.id) ?? modelOrder.size) - (modelOrder.get(b.id) ?? modelOrder.size)
    if (preferred) return preferred
    const first = match(a), second = match(b)
    if (!first || !second) return b.seen - a.seen
    return Number(second.nameStartsWithQuery) - Number(first.nameStartsWithQuery) ||
      second.matchedTerms - first.matchedTerms || Number(second.metadataMatch) - Number(first.metadataMatch) ||
      second.exactTerms - first.exactTerms || second.relaxedCoverage - first.relaxedCoverage ||
      (scores.get(second.id) ?? 0) - (scores.get(first.id) ?? 0) || b.seen - a.seen
  })
  const count = entries.length + folderResults.length
  const selected = entries.filter(item => selectedFiles.has(item.id))
  const controls = root.querySelector<HTMLElement>('.office-file-selection')!
  controls.hidden = !entries.length
  controls.innerHTML = entries.length ? `<label><input type="checkbox" data-select-files aria-label="全选文件" ${selected.length === entries.length ? 'checked' : ''} ${entries.length > 500 ? 'disabled' : ''}>全选</label>
    ${selected.length ? `<span>已选 ${selected.length} 项</span><button data-bulk-files="${view === 'starred' ? 'unstar' : 'star'}">${view === 'starred' ? '取消收藏' : '收藏所选'}</button>
      ${view === 'starred' ? '<button data-bulk-files="group">收藏分组</button>' : ''}
      ${view === 'recent' && !query ? '<button data-bulk-files="hide_recent">从最近使用移除</button>' : ''}
      ${canWrite() ? '<button data-bulk-files="move">移动所选</button><button data-bulk-files="delete">删除所选</button>' : ''}` : ''}` : ''
  const all = controls.querySelector<HTMLInputElement>('[data-select-files]')
  if (all) all.indeterminate = Boolean(selected.length && selected.length < entries.length)
  const rerank = root.querySelector<HTMLButtonElement>('[data-action="rerank-search"]')!
  rerank.hidden = !query || Boolean(searching || failed || sortByName) || entries.length < 2
  rerank.disabled = Boolean(result?.rerankPending)
  rerank.textContent = result?.rerankPending ? '正在重排…' : 'AI 重排'
  root.querySelector('.file-count')!.textContent = searching ? `${count} 项，正在搜索正文…` : failed ? `${count} 项，正文搜索失败` :
    view === 'recent' && !query ? `最近使用　${entries.length} 个文件` :
    `${count} 项${partial ? '（部分匹配）' : ''}${modelOrder.size && !sortByName ? ' · 已由 AI 重排' : result?.rerankUnavailable ? ' · AI 重排暂不可用' : ''}`
  const message = searching ? '正在搜索正文…' : failed ? '正文搜索失败，请重试。' : query || filter ? '找不到匹配的文件。' : view === 'folder' ? '这个文件夹还是空的。新建文件，或把文件拖到这里。' :
    view === 'starred' ? '暂无收藏文件。' : '暂无最近文件 — 新建或打开一个文件开始使用。'
  const location = workspaceFileLocation()
  list.innerHTML = count ? folderResults.map(item => `<div class="file-row folder-list-row" data-drop-folder="${escape(item.id)}">
    <button data-folder="${escape(item.id)}" ${canWrite() ? 'draggable="true"' : ''}>${icon('folder')} ${escape(item.name)}</button>
    ${canWrite() ? `<button data-folder-actions="${escape(item.id)}" aria-label="管理文件夹 ${escape(item.name)}">${icon('more')}</button>` : ''}
  </div>`).join('') + entries.map(item => {
    const folderLabel = escape(location(item.folder))
    return `<div class="file-row" ${canWrite() ? `draggable="true" data-drag-file="${escape(item.id)}"` : ''}>
    <input type="checkbox" data-select-file="${escape(item.id)}" aria-label="选择 ${escape(item.name)}" ${selectedFiles.has(item.id) ? 'checked' : ''}>
    <button data-open="${escape(item.path)}">${badge(item.format, 24)} <span class="file-entry-text"><span class="file-name" title="${escape(item.name)}">${escape(item.name)}</span>${match(item)?.snippet ? `<small class="file-search-snippet">${escape(match(item)!.snippet)}</small>` : ''}</span></button>
    <span class="file-location" title="${folderLabel}">${folderLabel}</span>
    <button data-star="${escape(item.path)}" aria-label="${item.starred ? '取消收藏' : '收藏'} ${escape(item.name)}" aria-pressed="${item.starred}">${icon('star')}</button>
    ${canWrite() ? `<button data-file-actions="${escape(item.id)}" aria-label="管理文件 ${escape(item.name)}">${icon('more')}</button>` : ''}
  </div>`
  }).join('') : `<div class="empty">${icon('file', 38)}<p>${message}</p></div>`
}

async function rerankSearch() {
  const state = searchResult
  if (!state?.input.isConnected || state.searching || state.rerankPending) return
  const paths = [...root.querySelectorAll<HTMLElement>('.file-list [data-open]')].slice(0, 20).map(button => button.dataset.open)
  const entries = paths.flatMap(path => library.entries.find(item => item.path === path) ?? [])
  if (entries.length < 2) return
  state.rerankPending = true
  state.rerankUnavailable = false
  renderEntries()
  try {
    const response = await officeRequest<{order: string[]}>(
      `/workspaces/${encodeURIComponent(currentSpace)}/search/rerank`, 'POST',
      {query: state.input.value.trim(), candidates: Object.fromEntries(entries.map(item => [item.id, item.revision]))},
      textSearch?.signal,
    )
    state.modelOrder = response.order.length ? response.order : undefined
    state.rerankUnavailable = !response.order.length
  } catch {
    state.modelOrder = undefined
    state.rerankUnavailable = true
  } finally {
    state.rerankPending = false
    if (searchResult === state && state.input.isConnected) renderEntries()
  }
}

function searchDocuments(input: HTMLInputElement) {
  clearTimeout(textSearchTimer)
  textSearch?.abort()
  const space = currentSpace
  const query = input.value.trim()
  const corpus: SearchCorpus = { documents: 0, totalLength: 0, documentFrequencies: [] }
  const result = { input, hits: [] as TextHit[], corpus, searching: Boolean(query && space), failed: false }
  searchResult = result
  renderEntries()
  if (!query || !space) return
  const controller = new AbortController()
  textSearch = controller
  textSearchTimer = setTimeout(async () => {
    const current = () => input.isConnected && space === currentSpace && !controller.signal.aborted
    let after: string | null = null
    try {
      do {
        if (!current()) return
        const params = new URLSearchParams({ q: query, after: after ?? '' })
        const page: { hits: TextHit[]; after: string | null; corpus: SearchCorpus } = await officeRequest(
          `/workspaces/${encodeURIComponent(space)}/search?${params}`, 'GET', undefined, controller.signal,
        )
        result.hits.push(...page.hits)
        mergeSearchCorpus(corpus, page.corpus)
        after = page.after
        result.searching = Boolean(after)
        if (current()) renderEntries()
      } while (after)
    } catch {
      result.failed = true
      result.searching = false
      if (current()) renderEntries()
    }
  }, 250)
}

root.innerHTML = '<header class="tabbar"></header><div class="office-body"></div><div class="editors"></div><div class="notice" role="status"></div><input type="file" hidden accept=".docx,.xlsx,.pptx,.pdf">'
const picker = root.querySelector<HTMLInputElement>('input[type=file]')!
picker.multiple = true


function canWrite(spaceId = currentSpace) {
  const space = spaces.find(item => item.id === spaceId)
  return Boolean(space && !space.archived && space.role !== 'viewer')
}

function render() {
  root.querySelector('.tabbar')!.innerHTML = `<button class="top-menu" data-action="sidebar" aria-label="切换侧栏">${icon('menu', 13)}</button>
    <button class="tab ${selectedTab ? '' : 'active'}" data-tab="">${icon('home', 14)} GenOffice</button>
    ${Array.from(tabs.keys(), path => {
    const entry = tabEntries.get(path)!
    return `<div class="file-tab ${selectedTab === path ? 'active' : ''}"><button data-tab="${escape(path)}">${badge(entry.format, 16)}${escape(entry.name)}</button><button data-close="${escape(path)}" aria-label="关闭 ${escape(entry.name)}">${icon('close', 12)}</button></div>`
  }).join('')}<button class="top-menu" data-action="home" aria-label="新建或打开文件">${icon('plus', 15)}</button>`
  const body = root.querySelector<HTMLElement>('.office-body')!
  const priorThread = body.querySelector<HTMLElement>('.kb-thread')
  const priorTop = priorThread?.scrollTop ?? 0
  const wasAtBottom = priorThread && priorThread.scrollHeight - priorThread.clientHeight - priorTop <= 2
  body.hidden = Boolean(selectedTab)
  body.innerHTML = `<aside ${sidebarHidden ? 'hidden' : ''}>
    <img class="logo" src="${assets}genoffice-logo.svg" alt="GenOffice">
    <select class="space-selector" aria-label="当前工作区" ${busy ? 'disabled' : ''}>${spaces.map(item =>
      `<option value="${escape(item.id)}" ${item.id === currentSpace ? 'selected' : ''}>${escape(item.name)}${item.archived ? '（已归档）' : ''}</option>`).join('')}</select>
    <nav>${nav('recent', '最近', 'clock', library.entries.filter(item => !item.recentHidden).length)}${nav('starred', '收藏', 'star', library.entries.filter(item => item.starred).length)}${nav('ask', 'AI 问答', 'chat')}</nav>
    <div class="folders-head"><span>文件夹</span><div><button data-action="browse-directory" ${canWrite() ? '' : 'disabled'}>导入文件夹</button><button data-action="new-folder" aria-label="新建文件夹" ${canWrite() ? '' : 'disabled'}>${icon('plus', 14)}</button></div></div>
    ${folderTree('', 0)}
    <div class="space-controls">
      ${currentUser ? '<button data-action="space-sources">工作区数据源</button>' : ''}

      ${spaces.find(item => item.id === currentSpace)?.role === 'owner' && !spaces.find(item => item.id === currentSpace)?.personal_user ? '<button data-action="members">成员管理</button>' : ''}
      ${currentUser?.role === 'admin' ? '<a href="/office/admin" target="_blank" rel="noopener noreferrer">管理后台</a><button data-action="new-space">新建团队工作区</button>' : ''}
    </div>
    <footer><button class="office-account-entry" data-action="${currentUser ? 'personal-settings' : 'login'}" aria-haspopup="dialog" aria-label="${currentUser ? '账户设置' : '登录'}"><span class="office-account-avatar">${escape(currentUser?.name.slice(0, 1) || '○')}</span><span class="office-account-name">${escape(currentUser?.name || '登录')}</span><svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M5 6.2 8 3.4l3 2.8M5 9.8l3 2.8 3-2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg></button></footer></aside>
    <main>${view === 'ask' ? ask() : home()}</main>`
  const thread = body.querySelector<HTMLElement>('.kb-thread.has-messages')
  if (thread && !body.hidden) {
    const sameTurn = priorThread?.dataset.thread === thread.dataset.thread &&
      priorThread?.dataset.lastTurn === thread.dataset.lastTurn
    thread.scrollTop = sameTurn && !wasAtBottom ? priorTop : thread.scrollHeight
  }
  for (const [path, iframe] of tabs) iframe.hidden = selectedTab !== path
  root.querySelector('.notice')!.textContent = status
  renderEntries()
}

function open(entry: Entry, source = entry.path) {
  const closedIndex = closedTabs.findIndex(item => item.path === entry.path)
  if (closedIndex >= 0) closedTabs.splice(closedIndex, 1)
  entry.seen = Date.now()
  entry.recentHidden = false
  const listing = library.entries.find(item => item.id === entry.id && item.space === entry.space)
  if (listing) { listing.seen = entry.seen; listing.recentHidden = false }
  tabEntries.set(entry.path, entry)
  if (!tabs.has(entry.path)) {
    const frame = document.createElement('iframe')
    frame.title = entry.name
    frame.referrerPolicy = 'no-referrer'
    frame.src = source
    root.querySelector('.editors')!.append(frame)
    tabs.set(entry.path, frame)
  }
  selectedTab = entry.path
  render()
}

function grantPath(input: string) {
  const url = new URL(input, location.origin)
  if (url.origin !== location.origin || !/^\/reports\/v1\/native\/open\/[^/]+$/.test(url.pathname)) throw new Error('文件编辑入口无效。')
  return url.pathname
}

async function reopen(entry: Entry, revision?: number) {
  const account = accountGeneration
  const result = await officeRequest<{ documentId: string; revision: number; editor: { url: string } }>(
    `/files/${entry.id}/open`, 'POST', revision === undefined ? undefined : { revision })
  if (account !== accountGeneration) return
  const path = `/reports/v1/native/${result.documentId}/${result.revision}`
  open({ ...entry, path, revision: result.revision }, grantPath(result.editor.url))
}

async function reopenClosedTab() {
  const account = accountGeneration
  while (closedTabs.length && account === accountGeneration) {
    const entry = closedTabs.at(-1)!
    try {
      await reopen(entry, entry.revision)
      return
    } catch (error) {
      if (!(error instanceof OfficeRequestError) || ![403, 404, 410].includes(error.status)) throw error
      if (account === accountGeneration) closedTabs.pop()
    }
  }
  if (account === accountGeneration) throw new Error('最近关闭的文件均已不可用。')
}

function currentTabRevision(entry: Entry, frame?: HTMLIFrameElement): Entry {
  let path: string | undefined
  try { path = frame?.contentWindow?.location.pathname }
  catch { return entry }
  const documentPath = entry.path.slice(0, entry.path.lastIndexOf('/') + 1)
  if (!path?.startsWith(documentPath)) return entry
  const number = path.slice(documentPath.length)
  const revision = Number(number)
  if (!/^[1-9]\d*$/.test(number) || !Number.isSafeInteger(revision)) return entry
  return { ...entry, path, revision }
}

async function importFile(file: File, destination = view === 'folder' ? folder : rootFolder, openAfter = true) {
  const format = file.name.split('.').pop()?.toLowerCase() as Format
  if (!Object.hasOwn(formats, format)) throw new Error('请选择 DOCX、XLSX、PPTX 或 PDF 文件。')
  if (!file.size || file.size > 24 * 1024 * 1024) throw new Error('文件必须为 1 字节至 24 MiB。')
  if (!currentSpace) throw new Error('请先登录并选择工作区。')
  const body = new FormData()
  body.append('requestId', crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''))
  body.append('file', file, file.webkitRelativePath.split('/').pop() || file.name)
  if (destination !== rootFolder) body.append('folder', destination)
  const result = await officeRequest<{ fileId: string; editor: { url: string } }>(
    `/workspaces/${currentSpace}/files`, 'POST', body)
  await refreshLibrary()
  const entry = library.entries.find(item => item.id === result.fileId)
  if (entry && openAfter) open(entry, grantPath(result.editor.url))
  return result.fileId
}

async function importBatch(files: File[], destination: string, attach?: (id: string, file: File) => void) {
  const space = currentSpace, account = accountGeneration
  const failed: string[] = []
  let imported = 0
  for (const file of files) {
    if (account !== accountGeneration || space !== currentSpace) return
    try {
      const id = await importFile(file, destination, !attach)
      if (account !== accountGeneration || space !== currentSpace) return
      attach?.(id, file)
      imported++
    } catch (error) {
      if (account !== accountGeneration || space !== currentSpace) return
      failed.push(`${file.name}：${error instanceof Error ? error.message : '导入失败。'}`)
    }
  }
  if (failed.length) throw new Error(`已导入 ${imported} 个文件。 ${failed.join('；')}`)
}

async function withImport(operation: () => Promise<void>) {
  if (busy) return
  const account = accountGeneration
  busy = true
  status = '正在打开文件…'
  render()
  try { await operation(); if (account === accountGeneration) status = '' }
  catch (error) { if (account === accountGeneration) status = error instanceof Error ? error.message : '文件打开失败。' }
  finally { if (account === accountGeneration) { busy = false; render() } }
}

function manageOfficeItem(data: DOMStringMap, mode?: OfficeFileAction) {
    const file = library.entries.find(item => item.id === data.fileActions)
    const targetFolder = library.folders.find(item => item.id === data.folderActions)
    if (file || targetFolder) void showOfficeFileActions(root, {
      space: currentSpace, spaces, file, folder: targetFolder, mode,
      onCopy: file ? () => duplicateOfficeEntry(file) : undefined,
      onChanged: async deleted => {
        invalidateKnowledge(currentSpace)
        await refreshLibrary()
        if (deleted && targetFolder) { folder = rootFolder; view = 'folder' }
        for (const [path, entry] of tabEntries) {
          const updated = library.entries.find(item => item.id === entry.id)
          if (updated) tabEntries.set(path, updated)
          else if (file?.id === entry.id || targetFolder && entry.space === currentSpace) {
            tabs.get(path)?.remove(); tabs.delete(path); tabEntries.delete(path)
            if (selectedTab === path) selectedTab = ''
          }
        }
        render()
      },
    })
}

async function duplicateOfficeEntry(entry: Entry) {
  const account = accountGeneration
  const { files } = await officeRequest<OfficeLibrary>(`/workspaces/${entry.space}/library`)
  if (account !== accountGeneration) return
  const source = files.find(item => item.id === entry.id)
  if (!source) throw new Error('源文件已移出此工作区或不可用。')
  const result = await officeRequest<{
    fileId: string; documentId: string; name: string; revision: number; editor: { url: string }
  }>(`/files/${entry.id}/copy`, 'POST', {
    expectedVersion: source.version, requestId: crypto.randomUUID(),
  })
  if (account !== accountGeneration) return
  if (entry.space === currentSpace) await refreshLibrary()
  if (account !== accountGeneration) return
  open({
    ...source, id: result.fileId, name: result.name, revision: result.revision, version: 1,
    folder: source.folder ?? rootFolder, seen: Date.now(), starred: false, recentHidden: false,
    path: `/reports/v1/native/${result.documentId}/${result.revision}`,
  }, grantPath(result.editor.url))
}

function expandOfficeFolderPath(id: string) {
  let changed = false
  for (let ancestor: string | undefined = id; ancestor; ancestor = library.folders.find(item => item.id === ancestor)?.parent) {
    changed = setFolderCollapsed(ancestor, false) || changed
  }
  return changed
}

async function revealOfficeFile(entry: Entry) {
  const account = accountGeneration
  let targetPath: string | undefined
  await withImport(async () => {
    const result = await officeRequest<OfficeLibrary>(`/workspaces/${entry.space}/library`)
    if (account !== accountGeneration) return
    const file = result.files.find(item => item.id === entry.id)
    if (!file) throw new Error('文件已移出此工作区或不可用。')
    currentSpace = entry.space
    installLibrary(result)
    folder = file.folder ?? rootFolder
    expandOfficeFolderPath(folder)
    selectedFiles.clear()
    view = 'folder'
    filter = ''
    selectedTab = ''
    sidebarHidden = false
    targetPath = `/reports/v1/native/${file.document}/${file.revision}`
  })
  if (targetPath && account === accountGeneration) {
    root.querySelector<HTMLButtonElement>(`.file-list [data-open="${CSS.escape(targetPath)}"]`)?.focus()
  }
}

function updateRenamedOfficeTabs(renamed: Pick<Entry, 'id' | 'name' | 'version'>) {
  for (const [path, tab] of tabEntries) {
    if (tab.id !== renamed.id) continue
    tabEntries.set(path, { ...tab, name: renamed.name, version: renamed.version })
    const frame = tabs.get(path)
    if (frame) frame.title = renamed.name
  }
}

function renameOfficeFile(id: string) {
  if (busy || !canWrite()) return
  const entry = library.entries.find(item => item.id === id)
  const action = root.querySelector<HTMLButtonElement>(`.file-list [data-file-actions="${CSS.escape(id)}"]`)
  const button = action?.closest('.file-row')?.querySelector<HTMLButtonElement>('button[data-open]')
  if (!entry || !button) return
  const suffix = '.' + entry.format
  const hasSuffix = entry.name.toLowerCase().endsWith(suffix)
  const baseName = hasSuffix ? entry.name.slice(0, -suffix.length) : entry.name
  const extension = hasSuffix ? entry.name.slice(-suffix.length) : suffix
  renameInlineItem(button, baseName, '重命名文件', name => {
    if (entry.space !== currentSpace || !canWrite()) return
    void withImport(async () => {
      await officeRequest(`/files/${encodeURIComponent(id)}`, 'PATCH', {
        name: name + extension, expectedVersion: entry.version,
      })
      invalidateKnowledge(entry.space)
      await refreshLibrary()
      const renamed = library.entries.find(item => item.id === id)
      if (renamed) updateRenamedOfficeTabs(renamed)
    })
  })
}

async function renameOfficeTab(entry: Entry) {
  const account = accountGeneration
  const libraryUrl = `/workspaces/${entry.space}/library`
  const { files } = await officeRequest<OfficeLibrary>(libraryUrl)
  if (account !== accountGeneration) return
  const source = files.find(item => item.id === entry.id)
  if (!source) throw new Error('源文件已移出此工作区或不可用。')
  await showOfficeFileActions(root, {
    space: entry.space, spaces, file: { ...source, folder: source.folder ?? rootFolder }, mode: 'rename',
    onChanged: async () => {
      if (account !== accountGeneration) return
      invalidateKnowledge(entry.space)
      const { files: updated } = await officeRequest<OfficeLibrary>(libraryUrl)
      if (account !== accountGeneration) return
      const renamed = updated.find(item => item.id === entry.id)
      if (renamed) updateRenamedOfficeTabs(renamed)
      if (entry.space === currentSpace) await refreshLibrary()
      render()
    },
  })
}

function createOfficeFolder(parent: string) {
  if (!canWrite() || busy) return
  const space = currentSpace
  if (expandOfficeFolderPath(parent)) render()
  const row = root.querySelector<HTMLElement>(`.folder-row[data-drop-folder="${CSS.escape(parent)}"]`)
  if (!row) return
  openInlineFolder(row, name => {
    if (space !== currentSpace || !canWrite()) return
    void withImport(async () => {
      await officeRequest<Folder>(`/workspaces/${space}/folders`, 'POST',
        {name, parent: parent === rootFolder ? null : parent})
      setFolderCollapsed(parent, false)
      await refreshLibrary()
    })
  })
}

function renameOfficeFolder(id: string, inList: boolean) {
  if (busy || !canWrite()) return
  const item = library.folders.find(item => item.id === id)
  const surface = inList ? ".folder-list-row" : ".folder-row"
  const button = root.querySelector<HTMLButtonElement>(`${surface} button[data-folder="${CSS.escape(id)}"]`)
  if (!item || !button) return
  const space = currentSpace
  renameInlineItem(button, item.name, '重命名文件夹', name => {
    if (space !== currentSpace || !canWrite()) return
    void withImport(async () => {
      await officeRequest(`/workspaces/${space}/folders/${id}`, 'PATCH', {name})
      invalidateKnowledge(space)
      await refreshLibrary()
    })
  })
}

function applyOfficeFileAction(entries: Entry[], action: string) {
  const space = currentSpace
  if (action === 'delete' && !window.confirm(`删除所选的 ${entries.length} 个文件？`)) return
  void withImport(async () => {
    await officeRequest(`/workspaces/${encodeURIComponent(space)}/files/bulk`, 'POST', {
      action, versions: Object.fromEntries(entries.map(item => [item.id, item.version])),
    })
    const ids = new Set(entries.map(item => item.id))
    for (const id of ids) selectedFiles.delete(id)
    if (action === 'delete') for (const [path, entry] of tabEntries) {
      if (!ids.has(entry.id)) continue
      tabs.get(path)?.remove(); tabs.delete(path); tabEntries.delete(path)
      if (selectedTab === path) selectedTab = ''
    }
    if (action !== 'hide_recent') invalidateKnowledge(space)
    await refreshLibrary()
  })
}

root.addEventListener('contextmenu', event => {
  if (!(event.target instanceof Element) || busy) return
  const tabButton = event.target.closest('.file-tab')?.querySelector<HTMLButtonElement>('[data-tab]')
  const tabEntry = tabButton ? tabEntries.get(tabButton.dataset.tab!) : undefined
  const homeTab = event.target.closest<HTMLButtonElement>('button[data-tab=""]')
  if (!currentUser) return
  const row = event.target.closest<HTMLElement>('.file-row, .folder-row')
  const fileButton = row?.querySelector<HTMLButtonElement>('[data-open]')
  const entry = fileButton && library.entries.find(item => item.path === fileButton.dataset.open)
  const writable = canWrite()
  const action = writable ? row?.querySelector<HTMLButtonElement>('[data-file-actions], [data-folder-actions]') : undefined
  const parent = writable ? row?.dataset.dropFolder : undefined
  if (!action && !parent && !entry && !tabEntry && !homeTab) return
  event.preventDefault()
  root.querySelector('.office-context-menu')?.remove()
  const menu = document.createElement('div')
  menu.className = 'office-context-menu'
  menu.popover = 'auto'
  menu.setAttribute('role', 'menu')
  const origin = tabButton ?? homeTab ?? row?.querySelector<HTMLElement>('[data-open], [data-folder]')
  const items: HTMLButtonElement[] = []
  const add = (label: string, invoke: () => void, enabled = true) => {
    const item = document.createElement('button')
    item.type = 'button'
    item.setAttribute('role', 'menuitem')
    item.textContent = label
    item.disabled = !enabled
    item.onclick = () => { menu.hidePopover(); invoke() }
    menu.append(item)
    if (enabled) items.push(item)
  }
  if (parent) add('新建子文件夹', () => requestAnimationFrame(() => createOfficeFolder(parent)))
  if (tabEntry) {
    if (canWrite(tabEntry.space)) {
      add('重命名', () => void withImport(() => renameOfficeTab(tabEntry)))
      add('创建副本（复制已保存的文件）', () => void withImport(() => duplicateOfficeEntry(tabEntry)))
    }
    add('在文件夹中显示', () => void revealOfficeFile(tabEntry))
    const tabPath = tabButton?.dataset.tab
    const index = [...tabs.keys()].indexOf(tabPath ?? '')
    const move = (offset: -1 | 1) => {
      const order = [...tabs.entries()]
      const index = order.findIndex(([path]) => path === tabPath)
      const destination = index + offset
      if (index < 0 || destination < 0 || destination >= order.length) return
      const moved = order[index]
      order[index] = order[destination]
      order[destination] = moved
      tabs.clear()
      for (const [path, frame] of order) tabs.set(path, frame)
      render()
      root.querySelector<HTMLButtonElement>(`.file-tab [data-tab="${CSS.escape(moved[0])}"]`)?.focus()
    }
    add('向左移动', () => move(-1), index > 0)
    add('向右移动', () => move(1), index >= 0 && index < tabs.size - 1)
  }
  if (tabEntry || homeTab) {
    add('重新打开关闭的标签页', () => void withImport(reopenClosedTab), closedTabs.length > 0)
  }
  if (entry) {
    add('打开', () => void withImport(() => reopen(entry)))
    add('在文件夹中显示', () => void revealOfficeFile(entry))
    if (entry.starred) add('收藏分组', () => showFavoriteGroups([entry]))
    if (view === 'recent' && !entry.recentHidden) {
      add('从最近使用移除', () => applyOfficeFileAction([entry], 'hide_recent'))
    }
    if (view === 'starred') add('取消收藏', () => applyOfficeFileAction([entry], 'unstar'))
  }
  if (action) {
    for (const [mode, label] of [['rename','重命名'], ['move','移动到文件夹'], ['delete','删除']] as const) {
      const folderId = action.dataset.folderActions
      const inList = row?.classList.contains('folder-list-row') === true
      add(label, () => {
        if (mode === 'rename' && folderId) requestAnimationFrame(() => renameOfficeFolder(folderId, inList))
        else if (mode === 'rename' && action.dataset.fileActions) {
          const fileId = action.dataset.fileActions
          requestAnimationFrame(() => renameOfficeFile(fileId))
        } else manageOfficeItem(action.dataset, mode)
      })
    }
    if (entry) add('复制文件', () => void withImport(() => duplicateOfficeEntry(entry)))
  }
  menu.addEventListener('toggle', () => { if (!menu.matches(':popover-open')) menu.remove() })
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault()
      menu.hidePopover()
      origin?.focus()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const index = items.findIndex(item => item === document.activeElement)
    items[(index + items.length + (event.key === 'ArrowDown' ? 1 : -1)) % items.length]?.focus()
  })
  root.append(menu)
  menu.showPopover()
  const anchor = origin?.getBoundingClientRect()
  const x = event.clientX || anchor?.left || 0
  const y = event.clientY || anchor?.bottom || 0
  menu.style.left = Math.max(0, Math.min(x, innerWidth - menu.offsetWidth)) + 'px'
  menu.style.top = Math.max(0, Math.min(y, innerHeight - menu.offsetHeight)) + 'px'
  items[0]?.focus()
})

root.addEventListener('click', event => {
  const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button')
  if (!button) return
  const data = button.dataset
  if (data.favoriteGroup !== undefined) {
    favoriteGroup = data.favoriteGroup
    selectedFiles.clear()
    renderEntries()
    root.querySelector<HTMLButtonElement>(`[data-favorite-group="${CSS.escape(favoriteGroup)}"]`)?.focus()
    return
  }
  if (data.bulkFiles) {
    const action = data.bulkFiles
    const chosen = [...root.querySelectorAll<HTMLInputElement>('[data-select-file]:checked')]
      .flatMap(input => library.entries.find(item => item.id === input.dataset.selectFile) ?? [])
    if (!chosen.length || busy) return
    const space = currentSpace
    if (action === 'group') { showFavoriteGroups(chosen); return }
    if (action === 'move') {
      void showOfficeFileActions(root, {space, spaces, files: chosen, mode: 'move', async onChanged() {
        invalidateKnowledge(space)
        for (const item of chosen) selectedFiles.delete(item.id)
        await refreshLibrary()
        for (const [path, entry] of tabEntries) {
          if (!chosen.some(item => item.id === entry.id)) continue
          const updated = library.entries.find(item => item.id === entry.id)
          if (updated) tabEntries.set(path, updated)
          else {
            tabs.get(path)?.remove(); tabs.delete(path); tabEntries.delete(path)
            if (selectedTab === path) selectedTab = ''
          }
        }
        render()
      }})
      return
    }
    applyOfficeFileAction(chosen, action)
    return
  }
  if (data.action === 'rerank-search') { void rerankSearch(); return }
  if (data.action === 'kb-delete') {
    if (!confirm('删除当前会话及其问答记录？')) return
    const space = currentSpace, account = accountGeneration, conversation = conversationOf(space)
    void withImport(async () => {
      await officeRequest(`/workspaces/${space}/knowledge/conversations?conversation=${encodeURIComponent(conversation)}`, 'DELETE')
      if (account !== accountGeneration) return
      setKnowledgeDraft(space, '', conversation)
      setKnowledgeDraftAttachments(space, [], conversation)
      activeKnowledgeConversation.set(space, createKnowledgeConversation(space))
      await loadKnowledge(space)
    })
    return
  }
  if (data.action === 'kb-new') {
    activeKnowledgeConversation.set(currentSpace, createKnowledgeConversation(currentSpace))
    void loadKnowledge()
    render()
    root.querySelector<HTMLTextAreaElement>('.composer textarea')?.focus()
    return
  }
  if (data.action === 'kb-stop') { knowledgePending.get(currentSpace)?.abort(); return }
  if (data.action === 'kb-send') { void sendKnowledge(); return }
  if (data.removeAttachment && !knowledgePending.has(currentSpace)) {
    setKnowledgeDraftAttachments(currentSpace, knowledgeDraftAttachments(currentSpace).map(file => file.id).filter(id => id !== data.removeAttachment))
    render()
    return
  }
  if (data.action === 'kb-choose-attachment') { chooseWorkspaceAttachments(); return }
  if (data.action === 'kb-attach') { picker.removeAttribute('webkitdirectory'); picker.click(); return }
  if (data.openAnswerDocx) {
    const entry = library.entries.find(item => item.id === data.openAnswerDocx)
    if (entry) void withImport(() => reopen(entry))
    return
  }
  if (data.answerDocx) {
    const space = currentSpace, account = accountGeneration
    const turn = data.answerDocx
    const key = knowledgeWordKey(turn)
    const conversation = encodeURIComponent(conversationOf(space))
    void withImport(async () => {
      const result = await officeRequest<{ fileId: string }>(
        `/workspaces/${space}/knowledge/${encodeURIComponent(turn)}/docx?conversation=${conversation}`, 'POST')
      if (account !== accountGeneration) return
      savedKnowledgeDocuments.set(key, result.fileId)
      try { sessionStorage.setItem(key, result.fileId) } catch { /* Keep the current page's record. */ }
      await refreshLibrary()
    })
    return
  }
  if (data.citation) {
    void withImport(async () => {
      const result = await officeRequest<{ fileId: string; documentId: string; revision: number; name: string; format: Format; space: string; editor: { url: string } }>(
        `/files/${data.citation}/open`, 'POST', { revision: Number(data.revision) })
      open({ id: result.fileId, name: `${result.name} · 修订 ${result.revision}`, format: result.format,
        space: result.space, folder: rootFolder, version: 0, revision: result.revision, starred: true, seen: Date.now(),
        path: `/reports/v1/native/${result.documentId}/${result.revision}` }, grantPath(result.editor.url))
    })
    return
  }
  if (data.filter !== undefined) {
    filter = data.filter as Format | ''
    selectedFiles.clear()
    root.querySelectorAll<HTMLButtonElement>('[data-filter]').forEach(control => control.classList.toggle('active', control.dataset.filter === filter))
    renderEntries()
    return
  }
  if (data.action === 'sort') {
    sortByName = !sortByName
    button.setAttribute('aria-pressed', String(sortByName))
    renderEntries()
    return
  }
  if (data.fileActions || data.folderActions) { manageOfficeItem(data); return }
  if (data.view) {
    view = data.view as View; filter = ''; favoriteGroup = ''; selectedTab = ''
    selectedFiles.clear()
    if (view === 'ask') void loadKnowledge()
  }
  if (data.folder) {
    view = 'folder'; folder = data.folder; filter = ''
    selectedFiles.clear()
    expandOfficeFolderPath(folder)
  }
  if (data.collapse) {
    setFolderCollapsed(data.collapse, !collapsed.has(data.collapse))
  }
  if (data.action === 'home' || data.tab === '') {
    selectedTab = ''
    if (data.action === 'home') { view = 'recent'; filter = '' }
    void refreshLibrary().then(render).catch(error => {
      status = error instanceof Error ? error.message : '无法刷新文件列表。'
      render()
    })
  }
  if (data.action === 'sidebar') sidebarHidden = !sidebarHidden
  if (data.action === 'browse' || data.action === 'browse-directory') {
    picker.toggleAttribute('webkitdirectory', data.action === 'browse-directory')
    picker.click()
    return
  }
  if (data.action === 'login') { showLogin(); return }
  if (data.action === 'personal-settings' && currentUser) {
    openPersonalSettings()
    return
  }
  if (data.action === 'company-sources' || data.action === 'space-sources') {
    if (currentUser) void showOfficeSources(root, {
      admin: data.action === 'company-sources', space: spaces.find(item => item.id === currentSpace),
    })
    return
  }
  if (data.action === 'logout') {
    const account = accountGeneration
    void withImport(async () => {
      await officeRequest('/logout', 'POST')
      if (account === accountGeneration) { clearAccount(); status = ''; render() }
    })
    return
  }
  if (data.action === 'users' || data.action === 'members') {
    const account = accountGeneration
    if (currentUser) void showOfficeAdministration(root, {
      user: currentUser,
      space: data.action === 'members' ? spaces.find(item => item.id === currentSpace) : undefined,
      onChanged: async () => {
        if (account !== accountGeneration) return
        await refreshSpaces()
        if (account === accountGeneration) render()
      },
    })
    return
  }
  if (data.action === 'new-space') {
    const account = accountGeneration
    const name = prompt('团队工作区名称')?.trim()
    if (!name) return
    const owner = prompt('工作区负责人用户 ID', currentUser!.user)?.trim()
    if (!owner) return
    void withImport(async () => {
      const created = await officeRequest<OfficeSpace>('/workspaces', 'POST', { name, owner })
      if (account !== accountGeneration) return
      currentSpace = created.id
      await refreshSpaces()
    })
    return
  }
  if (data.action === 'new-folder') {
    createOfficeFolder(view === 'folder' ? folder : rootFolder)
    return
  }
  if (data.new) {
    const format = data.new as Format
    const destination = view === 'folder' ? folder : rootFolder
    void withImport(async () => {
      const template = await fetch(`${assets}blank.${format}`)
      if (!template.ok) throw new Error('无法加载空白模板。')
      await importFile(new File([await template.blob()], `${formats[format][2]}.${format}`), destination)
    })
    return
  }
  if (data.open) {
    const entry = library.entries.find(item => item.path === data.open)
    if (entry) { void withImport(() => reopen(entry)); return }
  }
  if (data.star) {
    const entry = library.entries.find(item => item.path === data.star)
    if (entry) void withImport(async () => {
      await officeRequest(`/files/${entry.id}/favorite`, 'PUT', { starred: !entry.starred })
      invalidateKnowledge(entry.space)
      await refreshLibrary()
    })
    return
  }
  if (data.tab !== undefined) selectedTab = data.tab
  if (data.close) {
    const entry = tabEntries.get(data.close)
    const frame = tabs.get(data.close)
    if (entry) {
      const closed = currentTabRevision(entry, frame)
      const prior = closedTabs.findIndex(item => item.path === closed.path)
      if (prior >= 0) closedTabs.splice(prior, 1)
      closedTabs.push(closed)
      if (closedTabs.length > 20) closedTabs.shift()
    }
    frame?.remove()
    tabs.delete(data.close)
    tabEntries.delete(data.close)
    if (selectedTab === data.close) selectedTab = ''
  }
  render()
})

root.addEventListener('input', event => {
  if ((event.target as HTMLInputElement).type === 'search') searchDocuments(event.target as HTMLInputElement)
  const input = event.target
  if (input instanceof HTMLTextAreaElement && input.matches('.composer textarea')) {
    setKnowledgeDraft(currentSpace, input.value)
    const send = root.querySelector<HTMLButtonElement>('[data-action=kb-send]')
    if (send) {
      const disabled = !canSendKnowledge(input.value)
      if (send.disabled !== disabled) {
        send.disabled = disabled
        send.querySelector('img')!.src = `${assets}send-enter-${disabled ? 'off' : 'on'}.png`
      }
    }
  }
})
window.addEventListener('keydown', event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.isComposing ||
      (event.key !== 'f' && event.key !== 'p') || selectedTab || root.querySelector('dialog[open]')) return
  const input = root.querySelector<HTMLInputElement>('input[type=search]')
  if (!input) return
  event.preventDefault()
  input.focus()
  input.select()
})
root.addEventListener('paste', event => {
  if (!(event.target as HTMLElement).matches('.composer textarea')) return
  const files = Array.from(event.clipboardData?.files ?? [])
  if (!files.length) return
  event.preventDefault()
  attachKnowledgeFiles(files)
})
root.addEventListener('keydown', event => {
  if ((event.target as HTMLElement).matches('.composer textarea') && event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && !event.repeat) {
    event.preventDefault(); void sendKnowledge()
  }
})
root.addEventListener('change', event => {
  const select = event.target as HTMLSelectElement
  if (select.matches('[data-select-files], [data-select-file]')) {
    const input = select as unknown as HTMLInputElement
    const affected = input.matches('[data-select-files]')
      ? [...root.querySelectorAll<HTMLInputElement>('[data-select-file]')].map(item => item.dataset.selectFile!)
      : [input.dataset.selectFile!]
    if (input.checked && new Set([...selectedFiles, ...affected]).size > 500) {
      status = '一次最多选择 500 个文件。'
      root.querySelector('.notice')!.textContent = status
    } else for (const id of affected) {
      if (input.checked) selectedFiles.add(id)
      else selectedFiles.delete(id)
    }
    renderEntries()
    const replacement = [...root.querySelectorAll<HTMLInputElement>('[data-select-files], [data-select-file]')]
      .find(item => item.dataset.selectFile === input.dataset.selectFile)
    replacement?.focus({preventScroll:true})
    return
  }
  if (select.matches('select[aria-label="问答会话"]')) {
    activeKnowledgeConversation.set(currentSpace, select.value)
    void loadKnowledge()
    render()
    return
  }
  if (!select.matches('.space-selector')) return
  if (busy) { select.value = currentSpace; return }
  currentSpace = select.value
  favoriteGroup = ''
  selectedFiles.clear()
  folder = rootFolder; view = 'recent'; filter = ''
  void withImport(refreshLibrary)
})
type DirectoryEntry = { file?: File; path: string }

async function readDroppedDirectory(entry: FileSystemEntry, files: DirectoryEntry[]) {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject))
    files.push({ file, path: entry.fullPath.replace(/^\//, '') })
    return
  }
  if (!entry.isDirectory) return
  files.push({ path: entry.fullPath.replace(/^\//, '') })
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  for (;;) {
    const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
    if (!entries.length) return
    for (const child of entries) await readDroppedDirectory(child, files)
  }
}

async function importDirectory(files: DirectoryEntry[], destination: string) {
  const space = currentSpace, account = accountGeneration
  const byParentAndName = new Map(library.folders.map(item => [JSON.stringify([item.parent, item.name]), item.id]))
  let imported = 0, skipped = 0, directories = 0
  const failures: string[] = []
  for (const {file, path} of files) {
    if (account !== accountGeneration || space !== currentSpace) return
    const parts = path.split('/')
    if (file) {
      parts.pop()
      const format = file.name.split('.').pop()?.toLowerCase() ?? ''
      if (!Object.hasOwn(formats, format)) { skipped++; continue }
    }
    let parent = destination
    try {
      for (const name of parts) {
        if (account !== accountGeneration || space !== currentSpace) return
        const key = JSON.stringify([parent, name])
        let id = byParentAndName.get(key)
        if (!id) {
          const created = await officeRequest<Folder>(`/workspaces/${space}/folders`, 'POST',
            {name, parent: parent === rootFolder ? null : parent})
          id = created.id
          byParentAndName.set(key, id)
        }
        setFolderCollapsed(parent, false)
        parent = id
      }
      if (account !== accountGeneration || space !== currentSpace) return
      if (file) {
        await importFile(file, parent, false)
        imported++
      } else directories++
    } catch (error) {
      failures.push(`${path}：${error instanceof Error ? error.message : '导入失败。'}`)
    }
  }
  if (account !== accountGeneration || space !== currentSpace) return
  await refreshLibrary()
  if ((!imported && !directories) || skipped || failures.length) {
    throw new Error([`已导入 ${imported} 个文件。`, skipped ? `跳过 ${skipped} 个不支持的文件。` : '', ...failures].filter(Boolean).join(' '))
  }
}
picker.addEventListener('change', () => {
  const files = Array.from(picker.files ?? [])
  picker.value = ''
  if (picker.hasAttribute('webkitdirectory')) {
    picker.removeAttribute('webkitdirectory')
    const destination = view === 'folder' ? folder : rootFolder
    if (files.length && canWrite()) void withImport(() => importDirectory(files.map(file => ({file, path:file.webkitRelativePath})), destination))
    return
  }
  if (view === 'ask') {
    attachKnowledgeFiles(files)
    return
  }
  const destination = view === 'folder' ? folder : rootFolder
  if (files.length) void withImport(async () => {
    await importBatch(files, destination)
  })
})
function attachKnowledgeFiles(files: File[]) {
  const space = currentSpace, conversation = conversationOf(currentSpace)
  if (!files.length || !canWrite() || !knowledgeConversations.has(space) || knowledgePending.has(space)) return
  void withImport(async () => {
    const attachments = knowledgeDraftAttachments(space).map(file => file.id)
    if (attachments.length + files.length > 10) throw new Error('一次最多添加 10 个附件。')
    await importBatch(files, rootFolder, id => {
      attachments.push(id)
      setKnowledgeDraftAttachments(space, [...new Set(attachments)], conversation)
    })
  })
}
const officeFileDragType = 'application/x-genoffice-file'
const officeFolderDragType = 'application/x-genoffice-folder'
let highlightedFolder: HTMLElement | null = null
let folderExpandTimer: number | undefined
let activeDrag: { id: string; type: string } | undefined

function canMoveFolder(id: string, target: string) {
  const parents = new Map(library.folders.map(item => [item.id, item.parent]))
  if (!parents.has(id) || parents.get(id) === target) return false
  const visited = new Set([id])
  for (let ancestor: string | undefined = target; ancestor; ancestor = parents.get(ancestor)) {
    if (visited.has(ancestor)) return false
    visited.add(ancestor)
  }
  return true
}
function highlightFolder(target: HTMLElement | null) {
  if (highlightedFolder === target) return
  window.clearTimeout(folderExpandTimer)
  highlightedFolder?.classList.remove('drop-target')
  highlightedFolder = target
  if (!target) return
  target.classList.add('drop-target')
  const id = target.dataset.dropFolder
  if (!id || !target.classList.contains('folder-row') || !collapsed.has(id)) return
  folderExpandTimer = window.setTimeout(() => {
    if (highlightedFolder !== target || !target.isConnected || !setFolderCollapsed(id, false)) return
    const toggle = target.querySelector<HTMLButtonElement>('[data-collapse]')!
    toggle.setAttribute('aria-expanded', 'true')
    toggle.setAttribute('aria-label', toggle.getAttribute('aria-label')!.replace(/^展开 /, '折叠 '))
    const depth = Number(target.style.getPropertyValue('--depth'))
    target.insertAdjacentHTML('afterend', folderTree(id, depth + 1))
  }, 600)
}

root.addEventListener('dragstart', event => {
  const file = (event.target as HTMLElement).closest<HTMLElement>('[data-drag-file]')?.dataset.dragFile
  const draggedFolder = (event.target as HTMLElement).closest<HTMLElement>('[data-folder][draggable=true]')?.dataset.folder
  const id = file ?? draggedFolder
  if (!id || !event.dataTransfer || !canWrite()) return
  activeDrag = { id, type: file ? officeFileDragType : officeFolderDragType }
  event.dataTransfer.setData(activeDrag.type, id)
  event.dataTransfer.effectAllowed = 'move'
})
root.addEventListener('dragover', event => {
  const types = event.dataTransfer?.types
  if (view === 'ask' && !selectedTab && types?.includes('Files')) {
    event.preventDefault()
    if (canWrite() && !knowledgePending.has(currentSpace)) event.dataTransfer!.dropEffect = 'copy'
    return
  }
  if (!types || selectedTab || view === 'ask' || !canWrite()) {
    highlightFolder(null)
    return
  }
  const target = (event.target as HTMLElement).closest<HTMLElement>('[data-drop-folder]')
  const folderId = target?.dataset.dropFolder
  const local = types.includes('Files')
  const drag = activeDrag
  const internal = folderId && drag && types.includes(drag.type) &&
    (drag.type === officeFolderDragType ? canMoveFolder(drag.id, folderId) :
      library.entries.some(item => item.id === drag.id && item.folder !== folderId))
  highlightFolder(internal || local ? target : null)
  if (internal) {
    event.preventDefault()
    event.dataTransfer!.dropEffect = 'move'
  } else if (local) event.preventDefault()
})
root.addEventListener('dragleave', event => {
  if (!(event.relatedTarget instanceof Node) || !highlightedFolder?.contains(event.relatedTarget)) highlightFolder(null)
})
root.addEventListener('dragend', () => {
  activeDrag = undefined
  highlightFolder(null)
})
root.addEventListener('drop', event => {
  activeDrag = undefined
  highlightFolder(null)
  const transfer = event.dataTransfer
  if (!transfer || selectedTab) return
  if (view === 'ask') {
    if (transfer.types.includes('Files')) {
      event.preventDefault()
      attachKnowledgeFiles(Array.from(transfer.files))
    }
    return
  }
  const target = (event.target as HTMLElement).closest<HTMLElement>('[data-drop-folder]')?.dataset.dropFolder
  if (transfer.types.includes(officeFileDragType)) {
    event.preventDefault()
    const entry = library.entries.find(item => item.id === transfer.getData(officeFileDragType))
    if (!canWrite() || !target || !entry || entry.folder === target) return
    void withImport(async () => {
      await officeRequest(`/files/${encodeURIComponent(entry.id)}`, 'PATCH', {
        expectedVersion: entry.version, folder: target === rootFolder ? null : target,
      })
      invalidateKnowledge(currentSpace)
      await refreshLibrary()
    })
    return
  }
  if (transfer.types.includes(officeFolderDragType)) {
    event.preventDefault()
    const source = library.folders.find(item => item.id === transfer.getData(officeFolderDragType))
    if (!canWrite() || !target || !source || !canMoveFolder(source.id, target)) return
    void withImport(async () => {
      await officeRequest(`/workspaces/${encodeURIComponent(currentSpace)}/folders/${encodeURIComponent(source.id)}`,
        'PATCH', { parent: target === rootFolder ? null : target })
      setFolderCollapsed(target, false)
      await refreshLibrary()
    })
    return
  }
  const files = Array.from(transfer.files)
  const entries = Array.from(transfer.items).filter(item => item.kind === 'file')
    .map(item => ({ entry:item.webkitGetAsEntry?.(), file:item.getAsFile() }))
  if (!files.length && !entries.length) return
  event.preventDefault()
  if (!canWrite()) return
  const destination = target ?? (view === 'folder' ? folder : rootFolder)
  void withImport(async () => {
    if (!entries.some(item => item.entry?.isDirectory)) {
      await importBatch(files, destination)
      return
    }
    const tree: DirectoryEntry[] = []
    for (const {entry, file} of entries) {
      if (entry) await readDroppedDirectory(entry, tree)
      else if (file) tree.push({file, path:file.name})
    }
    await importDirectory(tree, destination)
  })
})

render()
void start()

root.addEventListener('load', event => { if (event.target instanceof HTMLIFrameElement) refreshOfficeTheme() }, true)
