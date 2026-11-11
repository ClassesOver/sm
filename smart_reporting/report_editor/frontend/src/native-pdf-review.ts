import {bindOfficeAssistantPanel} from './office-assistant-panel'
/** 按批注修改正文并回复：真实预览候选经显式采纳进入同一 NativeDraft。 */
import type {createNativeApi, NativePDFReviewJob} from './native-api'
import type {NativeDraft} from './native-draft'
import {createPdfRibbonIcon} from './pdf-ribbon-icons'
import {mountNativeAIProgress} from './native-ai-progress'

export function bindNativePDFReview(root: HTMLElement, options: {
  api: ReturnType<typeof createNativeApi>; draft: NativeDraft
  view: {refresh(): Promise<void>}; onDraftChange(): void; canEdit?: () => boolean
}) {
  const panel=document.createElement('section');panel.className='native-ai native-ai-panel native-pdf-review';panel.hidden=true
  panel.setAttribute('aria-label','AI 处理 PDF 批注')
  const title=document.createElement('h3');title.textContent='AI 处理批注'
  const help=document.createElement('p');help.textContent='Agno 驱动 · 阅读全部批注及对应正文，提出原位修改并以 AI Assistant 回复。歧义会请求澄清，不支持的操作会说明原因。采纳后仍需核对实际 PDF 预览并保存。'
  const input=document.createElement('textarea');input.maxLength=2000;input.placeholder='补充要求（可选）';input.setAttribute('aria-label','PDF 批注处理补充要求')
  function button(id: string,label: string) {const b=document.createElement('button');b.type='button';b.dataset.pdfReview=id;b.textContent=label;return b}
  const start=button('start','生成处理建议');start.prepend(createPdfRibbonIcon('sparkles'))
  const accept=button('accept','采纳到草稿'),cancel=button('cancel','取消建议'),close=button('close','关闭审阅')
  const status=document.createElement('p');status.setAttribute('role','status')
  const output=document.createElement('div');output.className='native-ai-answer';output.style.whiteSpace='pre-wrap'
  const details=document.createElement('div');details.className='native-ai-evidence'
  const progress=mountNativeAIProgress(panel)
  panel.append(title,help,input,start,accept,cancel,close,status,output,details);root.append(panel)
  const panelView=bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,onClose:()=>stop()})
  let generation=0,disposed=false,busy=false,job: NativePDFReviewJob | undefined,activeRequest: string | undefined
  let controller: AbortController | undefined
  const editable=()=>!disposed && !options.draft.closed && !options.draft.saving && (options.canEdit?.() ?? true)
  function update() {start.disabled=busy || !editable();accept.disabled=busy || !editable() || job?.status!=='succeeded' || !job.proposal;cancel.disabled=!activeRequest}
  function stop(message='建议已取消') {
    const turn=++generation,request=activeRequest
    controller?.abort();activeRequest=undefined;busy=false;job=undefined;status.textContent=message;output.textContent='';details.replaceChildren();update()
    if(request) void options.api.pdfReviewCancel(request).catch(error=>{if(turn===generation && !disposed) status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(value: NativePDFReviewJob) {
    job=value;details.replaceChildren();output.textContent=value.proposal?.answer ?? ''
    const proposal=value.proposal
    if(proposal) {
      const receipt=document.createElement('p');receipt.textContent='实际预览：已执行 '+proposal.appliedOperationIndices.length+' 项，跳过 '+proposal.skippedOperations.length+' 项'+(proposal.removedBaseOperationIndices?.length ? '；撤销草稿新增标注 '+proposal.removedBaseOperationIndices.length+' 项' : '')+'；预览摘要：'+proposal.previewDigest;details.append(receipt)
      const coverage=document.createElement('p');coverage.textContent='实际读取页码：'+(proposal.coverage?.fullyReadPages?.join('、') || '无完整正文页读取记录');details.append(coverage)
      for(const note of proposal.notes) {
        const item=document.createElement('section'),heading=document.createElement('p'),body=document.createElement('p')
        body.style.whiteSpace='pre-wrap'
        heading.textContent=(note.pageNumber ? '第 '+note.pageNumber+' 页 · ' : '')+(note.author || '未署名')+' · '+(note.status==='previewApplied' ? '已在预览执行' : note.status==='skipped' ? '已跳过' : '待核验')
        body.textContent=note.contents+'\n'+(note.reason || '')+(note.removedBaseOperationIndices?.length ? '\n撤销草稿新增标注 '+note.removedBaseOperationIndices.length+' 项' : '')+(note.reply ? '\nAI 回复建议：'+note.reply.contents : '')+(note.replyOmittedReason ? '\n'+note.replyOmittedReason : '')
        item.append(heading,body);details.append(item)
      }
      for(const skipped of proposal.skippedOperations) {const p=document.createElement('p');p.textContent='第 '+(skipped.operationIndex+1)+' 项未执行：'+skipped.reason;details.append(p)}
      for(const issue of proposal.issues ?? []) {const p=document.createElement('p');p.textContent=issue.message;details.append(p)}
    }
    status.textContent=value.error?.message ?? ({running:'正在读取批注、生成建议并核验实际 PDF',succeeded:'处理建议已核验，请逐条核对后采纳',failed:'批注处理失败',cancelled:'建议已取消'}[value.status]);update()
  }
  async function run() {
    if(busy || !editable()) return
    if(activeRequest) stop('开始新的处理建议')
    const turn=++generation,operations=structuredClone(options.draft.operations),snapshot=JSON.stringify(operations)
    const request=crypto.randomUUID();activeRequest=request;controller=new AbortController();const signal=controller.signal
    busy=true;job=undefined;output.textContent='';details.replaceChildren();status.textContent='正在读取全部批注及实际草稿';update()
    try {
      let result=await options.api.pdfReviewStart({clientRequestId:request,expectedSha256:options.draft.identity.sourceSha256,operations,instruction:input.value.trim()},signal)
      progress.start(options.api.pdfReviewEvents,result.editId,signal,()=>turn===generation && !disposed && editable())
      while(turn===generation && !disposed && result.status==='running') result=await options.api.pdfReviewStatus(result.editId,signal)
      if(turn!==generation || disposed) return
      if(!editable() || snapshot!==JSON.stringify(options.draft.operations)) {job=undefined;status.textContent='草稿已变化或当前不可编辑，请重新生成建议';return}
      display(result)
    } catch(error) {if(turn===generation && !disposed) status.textContent=error instanceof Error ? error.message : '批注处理失败'}
    finally {if(turn===generation && !disposed) {busy=false;update()}}
  }
  async function apply() {
    if(busy || !editable() || job?.status!=='succeeded' || !job.proposal) return
    const turn=generation,operations=structuredClone(options.draft.operations),snapshot=JSON.stringify(operations),candidate=job
    let staged=false
    busy=true;controller=new AbortController();update()
    try {
      const result=await options.api.pdfReviewAccept(candidate.editId,{expectedSha256:options.draft.identity.sourceSha256,operations,snapshotSha256:candidate.snapshotSha256},controller.signal)
      if(turn!==generation || disposed) return
      if(!editable() || snapshot!==JSON.stringify(options.draft.operations)) throw new Error('草稿已变化或当前不可编辑，请重新生成建议')
      options.draft.setOperations(result.operations);staged=true;options.onDraftChange();job=undefined
      await options.view.refresh()
      if(turn!==generation || disposed) return
      status.textContent='建议已进入草稿。请核对实际 PDF 预览并确认，保存后生成新修订。'
    } catch(error) {if(turn===generation && !disposed) status.textContent=(staged ? '建议已进入草稿，但预览刷新失败：' : '')+(error instanceof Error ? error.message : '采纳失败')}
    finally {if(turn===generation && !disposed) {busy=false;update()}}
  }
  start.onclick=()=>{void run()};accept.onclick=()=>{void apply()};cancel.onclick=()=>stop();close.onclick=()=>{stop();panel.hidden=true}
  update()
  return {
    open() {if(disposed) return;panelView.beforeOpen();panel.hidden=false;update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})},
    update,
    dispose() {if(disposed) return;panelView.dispose();stop();progress.reset();disposed=true;panel.remove()},
  }
}
