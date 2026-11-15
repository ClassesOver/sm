import { mountOfficeReadQueue } from './office-read-queue'
import { appendOfficeAnswer } from './office-answer'
import { OfficeAssistantController } from './office-assistant-controller'
import { bindOfficeAssistantPanel, createOfficeNewChatButton } from './office-assistant-panel'
/** 只读 PDF Agno 助手；写入仍走独立候选、预览与显式采纳链。 */
import type { createNativeApi, NativePDFReadAction, NativePDFReadTask, NativePDFNavigation } from './native-api'
import type { NativeDraft } from './native-draft'
import { createPdfRibbonIcon } from './pdf-ribbon-icons'
import { mountNativeAIProgress } from './native-ai-progress'

type Options = {
  api: ReturnType<typeof createNativeApi>
  draft: NativeDraft
  selection: () => {pageId: string; objectId: string}[]
  onNavigate: (pageId: string) => void
  viewPageId?: () => string | undefined
  onReadNavigate?: (target: NativePDFNavigation, current: () => boolean) => Promise<void>
}
const labels: Record<NativePDFReadAction, string> = {ask:'PDF 问答',summarize:'AI 总结',keyPoints:'AI 关键要点',reviewSummary:'AI 总结审阅'}
export function bindNativePDFAssistant(root: HTMLElement, options: Options) {
  const panel = document.createElement('section'); panel.className = 'native-ai native-ai-panel native-pdf-assistant'; panel.hidden = true
  panel.setAttribute('aria-label', 'PDF AI 助手')
  const title = document.createElement('h3')
  const help = document.createElement('p'); help.textContent = '阅读已核验来源，仅回答，不修改文档。请核对页码及实际读取范围。'
  const input = document.createElement('textarea'); input.maxLength = 2000; input.setAttribute('aria-label','PDF AI 问题或补充要求')
  const start = document.createElement('button'); start.type='button'; start.dataset.pdfAi='start'; start.append(createPdfRibbonIcon('sparkles'),document.createTextNode('开始阅读'))
  const cancel = document.createElement('button'); cancel.type='button'; cancel.dataset.pdfAi='cancel'; cancel.textContent='取消任务'
  const close = document.createElement('button'); close.type='button'; close.textContent='关闭助手'
  const status = document.createElement('p'); status.setAttribute('role','status')
  const transcript = document.createElement('div')
  transcript.className = 'native-ai-transcript'
  const progress = mountNativeAIProgress(panel)
  panel.append(title,help,input,start,cancel,close,status,transcript); root.append(panel)
  const reset = createOfficeNewChatButton()
  const queue = mountOfficeReadQueue(input, submit)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,headerAction:reset,queue:queue.host,onQueue:()=>queue.enqueue(action)})
  let action: NativePDFReadAction = 'ask', generation=0, disposed=false, busy=false, hasTurn=false
  const tasks = new OfficeAssistantController({start:options.api.pdfAIStart,status:options.api.pdfAIStatus,cancelRequest:options.api.pdfAICancel,id:(task: NativePDFReadTask)=>task.taskId,running:(task: NativePDFReadTask)=>task.status==='running'})
  let previous: {taskId: string; snapshot: string} | undefined
  function update() { reset.hidden=!hasTurn; start.disabled=busy || action==='ask' && !input.value.trim(); cancel.disabled=!busy; queue.setBusy(busy) }
  function stop(message='任务已取消') {
    const turn=++generation; progress.reset(); busy=false
    status.textContent=message; update()
    void tasks.cancel().catch(error=>{if(turn===generation && !disposed) status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(result: NonNullable<NativePDFReadTask['result']>, question: string) {
    const evidence=appendOfficeAnswer(transcript,question,result.answer)
    if(result.projection) {
      const version=document.createElement('p');version.textContent='阅读版本：未保存草稿；已应用 '+result.projection.appliedOperationIndices.length+' 项，跳过 '+result.projection.skippedOperations.length+' 项。';evidence.append(version)
      for(const skipped of result.projection.skippedOperations) { const note=document.createElement('p');note.textContent='草稿操作 '+(skipped.operationIndex+1)+' 已跳过：'+skipped.reason;evidence.append(note) }
    }
    const coverage=document.createElement('p')
    const read=result.coverage?.fullyReadPages ?? []
    coverage.textContent=(result.projection ? '实际读取草稿页码：' : '实际读取页码：')+(read.length ? read.join('、') : '尚无正文页读取记录')+'；总页数：'+(result.coverage?.pageCount ?? '未知')
    evidence.append(coverage)
    for(const issue of result.issues ?? []) { const note=document.createElement('p');note.textContent=issue.message;evidence.append(note) }
    for(const citation of result.citations ?? []) {
      const link=document.createElement('button');link.type='button'
      const pageId=citation.pageId
      if(!pageId || citation.pageNumber===null) { link.textContent='草稿新增第 '+citation.effectivePageNumber+' 页（无原始页面）';link.disabled=true }
      else {
        link.textContent=result.projection ? '转到原始第 '+citation.pageNumber+' 页（草稿第 '+citation.effectivePageNumber+' 页）' : '转到第 '+citation.pageNumber+' 页'
        link.onclick=()=>options.onNavigate(pageId)
      }
      evidence.append(link)
    }
    if(result.toolEvents?.length) { const tools=document.createElement('p');tools.textContent='已执行工具：'+result.toolEvents.map(event=>event.tool).join(' → ');evidence.append(tools) }
  }
  function submit(instruction: string, preset: NativePDFReadAction) {
    if (disposed || busy || preset === 'ask' && !instruction) return false
    void run(instruction, preset)
    return true
  }
  async function run(instruction: string, action: NativePDFReadAction) {
    panelView.beforeTask()
    const question = action === 'ask' ? instruction : [(labels[action]), instruction].filter(Boolean).join(' · ')
    const turn=++generation, operations=structuredClone(options.draft.operations), selection=structuredClone(options.selection())
    const snapshot=JSON.stringify({operations,selection})
    const viewPageId=options.onReadNavigate ? options.viewPageId?.() : undefined
    const requestId=crypto.randomUUID();busy=true;hasTurn=true
    status.textContent='正在读取已核验 PDF';update()
    try {
      const task=await tasks.run({clientRequestId:requestId,action,instruction,previousTaskId:action==='ask' && previous?.snapshot===snapshot ? previous.taskId : undefined,expectedSha256:options.draft.identity.sourceSha256,operations,selection,...(viewPageId ? {viewPageId} : {})},requestId,(started,signal)=>progress.start(options.api.pdfAIEvents,started.taskId,signal,()=>turn===generation && !disposed))
      if(!task || turn!==generation || disposed) return
      if(snapshot!==JSON.stringify({operations:options.draft.operations,selection:options.selection()})) { status.textContent='草稿或选区已变化，请重新阅读。';return }
      if(task.status==='completed' && task.result) {
        if(task.result.sourceSha256 && task.result.sourceSha256!==options.draft.identity.sourceSha256)throw new Error('PDF 回答来源已变化')
        previous={taskId:task.taskId,snapshot};display(task.result,question)
        let navigationStatus=''
        if(task.result.navigation) {
          try {
            if(!viewPageId || !options.onReadNavigate)throw new Error('当前视图不支持定位')
            if(options.viewPageId?.()!==viewPageId)throw new Error('当前页面已变化，定位未执行')
            const current=()=>turn===generation && !disposed && !panel.hidden && !options.draft.closed && !options.draft.saving
              && snapshot===JSON.stringify({operations:options.draft.operations,selection:options.selection()})
            if(!current())throw new Error('任务或文档状态已变化')
            await options.onReadNavigate(task.result.navigation,current)
            if(!current())return
            navigationStatus=`已定位到第 ${task.result.navigation.page} 页。`
          } catch(error) {
            if(turn!==generation || disposed)return
            navigationStatus='定位未完成：'+(error instanceof Error ? error.message : 'PDF 定位失败')+'。'
          }
        }
        if(turn!==generation || disposed)return
        status.textContent='阅读完成，文档与草稿未修改。'+navigationStatus
      }
      else status.textContent=task.error?.message ?? (task.status==='cancelled' ? '任务已取消' : 'PDF AI 未返回有效回答')
    } catch(error) { if(turn===generation && !disposed) status.textContent=error instanceof Error ? error.message : 'PDF AI 阅读失败' }
    finally { if(turn===generation) { busy=false;tasks.release();progress.stop();update() } }
  }
  reset.onclick = () => {
    queue.clear()
    stop('')
    hasTurn = false
    previous = undefined
    action = 'ask'
    title.textContent = 'AI 助手'
    transcript.replaceChildren()
    update()
    input.focus({preventScroll:true})
  }
  input.oninput=update;start.onclick=()=>{submit(input.value.trim(),action)};cancel.onclick=()=>{queue.hold();stop()}
  update()
  return {
    open(preset: NativePDFReadAction='ask') {
      if(disposed) return
      panelView.beforeOpen()
      panel.hidden = false
      panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})
      // 停靠栏通过 MutationObserver 展开；展开后补回首次被隐藏祖先阻止的焦点。
      queueMicrotask(()=>{if(!disposed && !panel.hidden && document.activeElement!==input)input.focus({preventScroll:true})})
      if (busy && preset === 'ask') return
      if (busy) { queue.hold(); stop('已取消上一任务，开始新的阅读任务') }
      action = preset
      title.textContent = preset === 'ask' ? 'AI 助手' : 'AI 助手 · '+labels[preset]
      update()
      if (preset !== 'ask') submit(input.value.trim(),action)
    },
    dispose() { if(disposed) return;disposed=true;panelView.dispose();stop();queue.dispose();panel.remove() },
  }
}
