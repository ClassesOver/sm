import { bindOfficeAssistantPanel } from './office-assistant-panel'
/** 只读 PDF Agno 助手；写入仍走独立候选、预览与显式采纳链。 */
import type { createNativeApi, NativePDFReadAction, NativePDFReadTask } from './native-api'
import type { NativeDraft } from './native-draft'
import { createPdfRibbonIcon } from './pdf-ribbon-icons'
import { mountNativeAIProgress } from './native-ai-progress'

type Options = {
  api: ReturnType<typeof createNativeApi>
  draft: NativeDraft
  selection: () => {pageId: string; objectId: string}[]
  onNavigate: (pageId: string) => void
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
  const output = document.createElement('div'); output.className='native-ai-answer'; output.style.whiteSpace='pre-wrap'
  const evidence = document.createElement('div'); evidence.className='native-ai-evidence'
  const progress = mountNativeAIProgress(panel)
  panel.append(title,help,input,start,cancel,close,status,output,evidence); root.append(panel)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,onClose:()=>{if(busy)stop()}})
  let action: NativePDFReadAction = 'ask', generation=0, disposed=false, busy=false
  let controller: AbortController | undefined, activeRequest: string | undefined
  function update() { start.disabled=busy || action==='ask' && !input.value.trim(); cancel.disabled=!busy }
  function stop(message='任务已取消') {
    const turn=++generation; controller?.abort(); busy=false
    const requestId=activeRequest; activeRequest=undefined; status.textContent=message; update()
    if (requestId) void options.api.pdfAICancel(requestId).catch(error=>{if(turn===generation && !disposed && !activeRequest) status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(result: NonNullable<NativePDFReadTask['result']>) {
    output.textContent=result.answer; evidence.replaceChildren()
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
  async function run() {
    if(disposed || busy || action==='ask' && !input.value.trim()) return
    const turn=++generation, operations=structuredClone(options.draft.operations), selection=structuredClone(options.selection())
    const snapshot=JSON.stringify({operations,selection})
    const requestId=crypto.randomUUID();activeRequest=requestId;controller=new AbortController();busy=true
    const signal=controller.signal;status.textContent='正在读取已核验 PDF';output.textContent='';evidence.replaceChildren();update()
    try {
      let task=await options.api.pdfAIStart({clientRequestId:requestId,action,instruction:input.value.trim(),expectedSha256:options.draft.identity.sourceSha256,operations,selection},signal)
      progress.start(options.api.pdfAIEvents, task.taskId, signal, () => turn===generation && !disposed)
      while(turn===generation && !disposed && task.status==='running') task=await options.api.pdfAIStatus(task.taskId,signal)
      if(turn!==generation || disposed) return
      if(snapshot!==JSON.stringify({operations:options.draft.operations,selection:options.selection()})) { status.textContent='草稿或选区已变化，请重新阅读。';return }
      if(task.status==='completed' && task.result) { display(task.result);status.textContent='阅读完成，文档与草稿未修改。' }
      else status.textContent=task.error?.message ?? (task.status==='cancelled' ? '任务已取消' : 'PDF AI 未返回有效回答')
    } catch(error) { if(turn===generation && !disposed) status.textContent=error instanceof Error ? error.message : 'PDF AI 阅读失败' }
    finally { if(turn===generation) { busy=false;activeRequest=undefined;update() } }
  }
  input.oninput=update;start.onclick=()=>{void run()};cancel.onclick=()=>stop()
  update()
  return {
    open(preset: NativePDFReadAction='ask') {
      if(disposed) return
      panelView.beforeOpen()
      if(busy) stop('已取消上一任务，开始新的阅读任务')
      action=preset;title.textContent=preset==='ask' ? 'AI 助手' : 'AI 助手 · '+labels[preset];panel.hidden=false;update()
      panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})
      // 停靠栏通过 MutationObserver 展开；展开后补回首次被隐藏祖先阻止的焦点。
      queueMicrotask(()=>{if(!disposed && !panel.hidden && document.activeElement!==input)input.focus({preventScroll:true})})
      if(preset!=='ask') void run()
    },
    dispose() { if(disposed) return;panelView.dispose();stop();progress.reset();disposed=true;panel.remove() },
  }
}
