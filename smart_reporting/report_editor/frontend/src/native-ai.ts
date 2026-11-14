import type { createNativeApi, NativeAIJob, NativeAISelection, NativeAIReviewSelection, NativeAINoteSelection } from './native-api'
import type { NativeDraft } from './native-draft'
import { mountNativeAIProgress, type NativeAIProgressListener } from './native-ai-progress'
import { bindOfficeAssistantPanel } from './office-assistant-panel'

/** 候选只在显式采纳后进入当前草稿，仍须用户保存为独立修订。 */
export function bindNativeAI(container: HTMLElement, options: {
  api: ReturnType<typeof createNativeApi>; draft: NativeDraft; format?: 'docx' | 'pdf'
  view: { refresh(): Promise<void>; flushPendingEdits?(): void }; onDraftChange(): void
  locked?(): boolean; onStateChange?(): void
}) {
  const panel = document.createElement('section')
  panel.className = 'native-ai'
  panel.setAttribute('aria-label', 'AI 编辑选区')
  if (options.format === 'docx') panel.hidden = true
  const input = document.createElement('textarea')
  input.placeholder = options.format === 'pdf' ? '先在“原位改字”中选择文字对象，再描述修改要求' : '先在正文中选择段落或单元格，再描述修改要求'
  input.setAttribute('aria-label', 'AI 修改要求')
  input.maxLength = 2000
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  const details = document.createElement('details')
  const summary = document.createElement('summary')
  summary.textContent = '查看建议修改'
  const changes = document.createElement('pre')
  const warnings = document.createElement('ul')
  warnings.setAttribute('aria-label', '建议中的未执行修改')
  details.append(summary, changes, warnings); details.hidden = true
  const button = (name: string, label: string) => {
    const element = document.createElement('button')
    element.type = 'button'; element.dataset.ai = name; element.textContent = label
    return element
  }
  const body = button('body-selection', '使用正文选区');body.hidden=true
  const start = button('start', '生成修改建议'), accept = button('accept', '采纳到草稿'), cancel = button('cancel', '取消建议')
  panel.append(input, start, accept, cancel, body, status, details); container.append(panel)
  let panelView: ReturnType<typeof bindOfficeAssistantPanel> | undefined
  if (options.format === 'docx') {
    panel.classList.add('native-ai-panel')
    const title = document.createElement('h3'); title.textContent = 'Word AI 编辑'
    const help = document.createElement('p'); help.textContent = '仅为当前正文选区或审阅目标生成候选，核对后显式采纳到草稿；保存后生成独立修订。'
    const dismiss = button('close', '关闭助手')
    panel.append(title,help,dismiss)
    panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close:dismiss,onClose:close})
  }
  const progress = mountNativeAIProgress(panel)
  let selection: NativeAISelection[] = [], documentSelection: NativeAISelection[] = [], reviewMode=false
  let job: NativeAIJob | undefined, busy = false, accepting = false, disposed = false, generation = 0
  let controller: AbortController | undefined
  let noteBeforeText: string | undefined
  let wordTarget: string | undefined
  let presetScope: 'selection' | 'document' | undefined, presetStale=false
  let activeRequestId: string | undefined
  const currentWordTarget = () => JSON.stringify({instruction:input.value.trim(),selection,operations:options.draft.operations})
  const editable = () => !disposed && !options.draft.closed && !options.draft.saving && !options.locked?.()
  function update() {
    start.disabled = !editable() || busy || accepting || !selection.length || presetStale
    accept.disabled = !editable() || busy || accepting || job?.status !== 'succeeded'
    cancel.disabled = disposed || !job && !busy
    options.onStateChange?.()
  }
  function show(value: NativeAIJob) {
    job = value
    details.hidden = !value.proposal
    const labels: Record<string, string> = {replaceParagraph:'替换段落',insertParagraph:'新增段落',deleteParagraph:'删除段落',formatParagraph:'调整段落格式',replaceCellText:'替换单元格文字',replaceText:'替换 PDF 原文',replyComment:'回复批注',resolveComment:'处理批注线程',resolveTextRevision:'处理正文修订',insertNote:'新增脚注／尾注',updateNote:'编辑脚注／尾注',deleteNote:'删除脚注／尾注及引用'}
    changes.textContent = value.proposal?.operations.map((operation, index) => {
      const content = operation.kind === 'resolveComment' ? '\n'+(operation.done ? '解决线程' : '重新打开线程') : operation.kind === 'resolveTextRevision' ? '\n'+(operation.action==='accept' ? '接受此修订' : '拒绝此修订') : operation.kind === 'replaceText' && typeof operation.newText === 'string' ? `\n${operation.newText || '清空原文字'}` : typeof operation.text === 'string' ? `\n${operation.text}` : ''
      const style = operation.style && typeof operation.style === 'object'
        ? Object.entries(operation.style).map(([key, enabled]) => `${({bold:'粗体',italic:'斜体',underline:'下划线'} as Record<string,string>)[key] ?? key}：${enabled ? '启用' : '取消'}`).join('，') : ''
      const noteLabel = operation.noteKind === 'footnote' ? '脚注' : operation.noteKind === 'endnote' ? '尾注' : ''
      const noteDiff = operation.kind === 'updateNote' && noteBeforeText !== undefined ? '\n原文：'+noteBeforeText+'\n候选：'+String(operation.text??'') : operation.kind === 'deleteNote' && noteBeforeText !== undefined ? '\n将删除：'+noteBeforeText : ''
      return `${index + 1}. ${labels[operation.kind] ?? '修改选区'}${noteLabel ? ' · '+noteLabel : ''}${noteDiff || content}${style ? `\n${style}` : ''}`
    }).join('\n\n') ?? ''
    warnings.replaceChildren()
    const issues = value.proposal?.issues?.map(issue => issue.message) ?? []
    const skips = value.proposal?.skippedOperations ?? []
    const notices = issues.length ? issues : skips.map(item => `第 ${item.operationIndex + 1} 项未执行，已保留原文：${item.reason}`)
    for (const notice of notices) {
      const warning = document.createElement('li')
      warning.textContent = notice; warnings.append(warning)
    }
    warnings.hidden = !notices.length
    if ((options.format === 'pdf' || selection.some(item=>'selectionKind' in item)) && value.proposal) details.open = true
    status.textContent = value.proposal?.summary ?? value.error?.message ?? ({running:'正在生成并核验建议',succeeded:'建议已核验',failed:'建议生成失败',cancelled:'建议已取消'}[value.status])
    update()
  }
  start.onclick = async () => {
    if (!editable() || busy || accepting || presetStale || !selection.length || !input.value.trim()) return
    try { options.view.flushPendingEdits?.() } catch(error) {status.textContent=error instanceof Error ? error.message : '未保存输入同步失败';return}
    if (!editable() || busy || accepting || presetStale || !selection.length || !input.value.trim()) {update();return}
    const turn = ++generation
    const instruction=input.value.trim(), selected=structuredClone(selection)
    if(options.format==='docx')wordTarget=JSON.stringify({instruction,selection:selected,operations:options.draft.operations})
    const target=wordTarget
    const requestId = crypto.randomUUID()
    activeRequestId = requestId
    controller = new AbortController(); busy = true; job = undefined; update()
    details.hidden = true
    status.textContent = '正在生成并核验建议'
    try {
      let result = await options.api.aiStart({clientRequestId:requestId, instruction, selection:selected, expectedSha256:options.draft.identity.sourceSha256, operations:options.draft.operations}, controller.signal)
      if(disposed || turn!==generation || options.format==='docx' && target!==currentWordTarget()) {
        void options.api.aiCancel(result.editId).catch(()=>{})
        if(!disposed && turn===generation) {clearCandidate();status.textContent='修改要求或选区已变化，请重新生成建议。';update()}
        return
      }
      progress.start(options.api.aiEvents as NativeAIProgressListener | undefined, result.editId, controller.signal, () => editable() && turn === generation)
      while (!disposed && turn === generation) {
        if(options.format==='docx' && target!==currentWordTarget()) {clearCandidate();status.textContent='修改要求或选区已变化，请重新生成建议。';update();break}
        show(result)
        if (result.status !== 'running') break
        result = await options.api.aiStatus(result.editId, controller.signal)
      }
    } catch (error) {
      if (!disposed && turn === generation) {
        status.textContent = error instanceof Error ? error.message : '建议生成失败'
        if (!job && activeRequestId === requestId && options.api.aiCancelRequest) {
          activeRequestId = undefined
          void options.api.aiCancelRequest(requestId).catch(() => {})
        }
      }
    }
    finally { if (turn === generation) { busy = false; update() } }
  }
  accept.onclick = async () => {
    if (!editable() || busy || accepting || job?.status !== 'succeeded') return
    try { options.view.flushPendingEdits?.() } catch(error) {status.textContent=error instanceof Error ? error.message : '未保存输入同步失败';return}
    if(!editable() || busy || accepting || presetStale) {update();return}
    if(options.format==='docx' && wordTarget!==currentWordTarget()) {clearCandidate();status.textContent='修改要求、选区或草稿已变化，请重新生成建议。';update();return}
    const turn = generation
    const target=wordTarget
    accepting = true; busy = true; update()
    try {
      const operations = options.draft.operations
      const result = await options.api.aiAccept(job.editId, {expectedSha256:options.draft.identity.sourceSha256, operations, snapshotSha256:job.snapshotSha256})
      // 网络等待期间可能发生保存或刷新；写稿前再次核验会话锁。
      if (turn !== generation || disposed) return
      if(options.format==='docx' && target!==currentWordTarget()) {clearCandidate();status.textContent='修改要求或选区已变化，请重新生成建议。';update();return}
      if (!editable()) throw new Error('当前修订正在保存、刷新或已关闭，请重新生成建议')
      if (JSON.stringify(operations) !== JSON.stringify(options.draft.operations)) throw new Error('草稿已变化，请重新生成建议')
      options.draft.setOperations(result.operations)
      options.onDraftChange()
      await options.view.refresh()
      job = undefined; activeRequestId = undefined
      status.textContent = options.format === 'pdf' ? '建议已进入草稿。保存前请核对实际 PDF 预览并确认。' : '建议已进入草稿，内容待重新核验；保存后生成新修订'
      details.hidden = true
    } catch (error) { if (turn === generation && !disposed) status.textContent = error instanceof Error ? error.message : '采纳失败' }
    finally {
      // 取消或换选区只能丢弃回包，不能提前释放仍在途的采纳请求。
      accepting = false
      if (turn === generation) busy = false
      update()
    }
  }
  cancel.onclick = async () => {
    ++generation; progress.stop(); controller?.abort(); busy = false
    const id = job?.editId, requestId = activeRequestId; activeRequestId = undefined
    job = undefined; status.textContent = '建议已取消'; update()
    details.hidden = true
    if (id) try { await options.api.aiCancel(id) } catch (error) { if (!disposed) status.textContent = error instanceof Error ? error.message : '服务端取消失败' }
    else if (requestId && options.api.aiCancelRequest) try { await options.api.aiCancelRequest(requestId) } catch (error) { if (!disposed) status.textContent = error instanceof Error ? error.message : '服务端取消失败' }
  }
  function clearCandidate() {
    const id=job?.editId, requestId=activeRequestId
    activeRequestId=undefined
    ++generation;controller?.abort();progress.reset();busy=false;job=undefined;wordTarget=undefined;details.hidden=true
    if(id)void options.api.aiCancel(id).catch(()=>{})
    else if(requestId && options.api.aiCancelRequest)void options.api.aiCancelRequest(requestId).catch(()=>{})
  }
  function close() {
    if (disposed) return
    clearCandidate(); panel.hidden = true; status.textContent = '建议已取消'; update()
  }
  body.onclick=()=>{clearCandidate();presetScope=undefined;presetStale=false;reviewMode=false;noteBeforeText=undefined;body.hidden=true;selection=structuredClone(documentSelection);input.value='';status.textContent='已切换到正文选区，请输入修改要求';update()}
  if(options.format==='docx')input.oninput=()=>{if(job || busy){clearCandidate();status.textContent='修改要求已变化，请重新生成建议。';update()}}
  update()
  return {
    update,
    get accepting() { return accepting },
    open() { if(disposed)return;panelView?.beforeOpen();panel.hidden=false;panel.scrollIntoView?.({block:'nearest'}); input.focus({preventScroll:true}) },
    close,
    openPreset(instruction:string, targets:{blockId:string;cellId?:string}[], scope:'selection'|'document') {
      if(!editable() || options.format!=='docx' || !targets.length || targets.length>100)return
      panelView?.beforeOpen();clearCandidate();presetScope=scope;presetStale=false;reviewMode=true;noteBeforeText=undefined;body.hidden=false
      selection=structuredClone(targets);input.value=instruction;panel.hidden=false
      status.textContent=`已授权${scope==='document'?'整篇正文':'选区'}的 ${targets.length} 个段落／单元格或整表；部分文字按整段／整格处理。请生成并核对候选，显式采纳后保存。`
      update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})
    },
    openNotes(value: NativeAINoteSelection, instruction='', beforeText?:string) {
      if(!editable() || options.format==='pdf')return
      panelView?.beforeOpen();clearCandidate();presetScope=undefined;presetStale=false;panel.hidden=false;reviewMode=true;noteBeforeText=beforeText;body.hidden=false;selection=[structuredClone(value)];input.value=instruction
      status.textContent=value.selectionKind==='note'?'仅授权当前脚注或尾注；编辑或删除需先核对候选，再显式采纳。':'仅授权当前段落插入脚注或尾注，不授权改写正文。与该段落相交的修改请先保存或撤销。'
      update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})
    },
    openReview(value: NativeAIReviewSelection, instruction='') {
      if(!editable() || options.format==='pdf')return
      panelView?.beforeOpen();clearCandidate();presetScope=undefined;presetStale=false;panel.hidden=false;reviewMode=true;noteBeforeText=undefined;body.hidden=false;selection=[structuredClone(value)];input.value=instruction
      status.textContent='仅授权当前审阅目标；请输入要求并生成建议，核对后采纳到草稿。已有不兼容修改请先保存或撤销。'
      update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true})
    },
    setSelection(value: NativeAISelection[]) {
      if(presetScope==='selection' && JSON.stringify(documentSelection)!==JSON.stringify(value)){clearCandidate();presetStale=true;status.textContent='Word 选区已变化，请重新点击审阅预设授权。';update()}
      documentSelection=structuredClone(value)
      if(reviewMode)return
      if(options.format==='docx' && JSON.stringify(selection)!==JSON.stringify(value) && (job || busy)) {clearCandidate();status.textContent='Word 选区已变化，请重新生成建议。'}
      if (options.format === 'pdf' && JSON.stringify(selection) !== JSON.stringify(value) && (job || busy)) {
        clearCandidate()
        status.textContent = 'PDF 文字选区已变化，请重新生成建议。'
      }
      selection = structuredClone(value); update()
    },
    dispose() { if(disposed)return;panelView?.dispose();clearCandidate();disposed = true;progress.stop();panel.remove() },
  }
}
