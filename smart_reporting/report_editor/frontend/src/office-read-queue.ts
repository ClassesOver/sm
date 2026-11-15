import { createElement as reactElement, useLayoutEffect } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { AiQueueStrip } from './vendor/genoffice-docs/packages/ui/src/AiQueueStrip'
import { useChatRunQueue, type ChatRunQueue } from './vendor/genoffice-docs/packages/ui/src/chat-run-queue'
import { AI_QUEUE_LABELS } from './vendor/genoffice-docs/packages/ui/src/strings-ai-queue'
import './vendor/genoffice-docs/packages/ui/src/ai-queue-strip.css'
import './native-office-assistant-queue.css'

function OfficeReadQueue<M>({busy, submit, publish}: {
  busy: boolean
  submit: (text: string, meta: M) => boolean
  publish: (queue: ChatRunQueue<M>) => void
}) {
  const queue=useChatRunQueue({busy,submit})
  useLayoutEffect(() => { publish(queue) },[publish,queue])
  return reactElement(AiQueueStrip,{
    items:queue.queued,labels:AI_QUEUE_LABELS.zh,paused:queue.paused,maxLength:2000,
    onTogglePause:queue.togglePaused,onUpdate:queue.update,onMove:queue.move,
    onRemove:queue.remove,onClear:queue.clear,
  })
}

export function mountOfficeReadQueue<M>(input: HTMLTextAreaElement, submit: (text: string, meta: M) => boolean) {
  const host = input.ownerDocument.createElement('div')
  host.className = 'office-assistant-queue'
  const root = createRoot(host)
  let queue: ChatRunQueue<M>
  let renderedBusy: boolean | undefined
  let normalPlaceholder: string | undefined
  let disposed = false
  const publish = (value: ChatRunQueue<M>) => { queue = value }
  function setBusy(busy: boolean) {
    if (disposed || renderedBusy === busy) return
    if (busy) normalPlaceholder ??= input.placeholder
    input.placeholder = busy ? AI_QUEUE_LABELS.zh.queuePlaceholder : normalPlaceholder ?? input.placeholder
    renderedBusy = busy
    root.render(reactElement(OfficeReadQueue<M>, { busy, submit, publish }))
  }
  flushSync(() => setBusy(false))
  return {
    host,
    setBusy,
    enqueue(meta: M) {
      const text = input.value.trim()
      if (disposed || !renderedBusy || !text) return
      queue.enqueue(text, meta)
      input.value = ''
    },
    hold() { queue.hold() },
    clear() { queue.clear() },
    dispose() { disposed = true; root.unmount() },
  }
}
