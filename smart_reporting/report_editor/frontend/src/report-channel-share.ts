import type { createNativeApi } from './native-api'

export function mountReportChannelShare(panel: HTMLElement, api: ReturnType<typeof createNativeApi>,
  followWordTask: (taskId: string) => Promise<void>) {
  const sharing = document.createElement('details')
  sharing.className = 'office-assistant-details'
  const title = document.createElement('summary')
  title.textContent = '分享报告频道'
  const label = document.createElement('label')
  label.textContent = 'DSH 连接器身份'
  const subject = document.createElement('input')
  subject.maxLength = 256
  label.append(subject)
  const invite = document.createElement('button')
  const revoke = document.createElement('button')
  invite.type = revoke.type = 'button'
  invite.textContent = '生成邀请链接'
  revoke.textContent = '撤销该身份的授权'
  const link = document.createElement('input')
  link.readOnly = true
  link.hidden = true
  link.setAttribute('aria-label', '报告频道邀请链接')
  link.onclick = () => link.select()
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  async function submit(action: 'invite' | 'revoke') {
    const identity = subject.value.trim()
    if (!identity) { subject.focus(); return }
    invite.disabled = revoke.disabled = subject.disabled = true
    link.hidden = true
    link.value = ''
    status.textContent = ''
    try {
      if (action === 'invite') {
        link.value = (await api.inviteReportConnector(identity)).url
        link.hidden = false
        link.focus()
        link.select()
      } else {
        await api.revokeReportConnector(identity)
        status.textContent = '已撤销频道授权'
      }
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : '频道操作失败'
    } finally {
      invite.disabled = revoke.disabled = subject.disabled = false
    }
  }
  invite.onclick = () => { void submit('invite') }
  revoke.onclick = () => { void submit('revoke') }
  const conversation = document.createElement('ol')
  conversation.setAttribute('aria-label', '报告频道消息')
  conversation.setAttribute('aria-live', 'polite')
  const message = document.createElement('textarea')
  message.setAttribute('aria-label', '频道消息')
  message.maxLength = 8000
  const send = document.createElement('button')
  send.type = 'button'
  send.textContent = '发送到频道'
  const chatStatus = document.createElement('p')
  chatStatus.setAttribute('role', 'status')
  const lifetime = new AbortController()
  let cursor = 0
  let reading = false
  let pending: {id: string; text: string} | undefined
  async function read() {
    if (reading || !sharing.open || panel.hidden || lifetime.signal.aborted) return
    reading = true
    try {
      const messages = await api.readReportChannel(cursor, lifetime.signal)
      if (lifetime.signal.aborted) return
      for (const entry of messages) {
        if (entry.sequence <= cursor) continue
        const item = document.createElement('li')
        if (entry.sender === 'word-task' && /^[A-Za-z0-9_-]{1,128}$/.test(entry.text)) {
          const review = document.createElement('button')
          review.type = 'button'
          review.textContent = '查看 Word 任务进度和候选'
          review.onclick = () => { void followWordTask(entry.text) }
          item.append(review)
        } else {
          item.textContent = `${entry.sender === 'editor' ? '编辑者' : '连接器'} · ${entry.text}`
        }
        conversation.append(item)
        cursor = entry.sequence
      }
    } catch (error) {
      if (!lifetime.signal.aborted) chatStatus.textContent = error instanceof Error ? error.message : '频道消息读取失败'
    } finally { reading = false }
  }
  send.onclick = async () => {
    const text = message.value.trim()
    if (!text || send.disabled) return
    if (pending?.text !== text) pending = {id: crypto.randomUUID(), text}
    send.disabled = message.disabled = true
    chatStatus.textContent = ''
    try {
      await api.postReportChannel(pending.id, text, lifetime.signal)
      pending = undefined
      message.value = ''
      await read()
    } catch (error) {
      if (!lifetime.signal.aborted) chatStatus.textContent = error instanceof Error ? error.message : '频道消息发送失败'
    } finally { send.disabled = message.disabled = false }
  }
  sharing.ontoggle = () => { void read() }
  const refresh = window.setInterval(() => { void read() }, 3000)
  sharing.append(title, label, invite, revoke, link, status, conversation, message, send, chatStatus)
  ;(panel.querySelector('.office-assistant-body') ?? panel).append(sharing)
  return () => { lifetime.abort(); window.clearInterval(refresh); sharing.remove() }
}
