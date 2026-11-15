import { appendOfficeAnswer } from './office-answer'
import { OfficeAssistantController } from './office-assistant-controller'
import { bindOfficeAssistantPanel, createOfficeNewChatButton } from './office-assistant-panel'
import { mountOfficeReadQueue } from './office-read-queue'
/** Office 阅读与编辑候选分开；回答不会写入草稿。 */
import { createElement, MessageCircle, FileText, ListChecks, Sparkles, X, CircleStop } from 'lucide'
import type { createNativeApi, NativeOfficeReadAction, NativeOfficeReadTask, NativeOfficeReadContext, NativeWorkbookNavigation } from './native-api'
import type { NativeDraft } from './native-draft'
import { mountNativeAIProgress, nativeAIToolLabel } from './native-ai-progress'

type Options = {
  api: ReturnType<typeof createNativeApi>
  draft: NativeDraft
  format: 'xlsx' | 'pptx'
  navigate?: (target: NativeWorkbookNavigation, current: () => boolean) => Promise<void>
  context: (scope: 'document' | 'selection') => Promise<NativeOfficeReadContext>
}
type ReadMessageMeta = { action: NativeOfficeReadAction; scope: 'document' | 'selection' }

const actions = {ask: ['文档问答', MessageCircle], summarize: ['总结文档 / 选区', FileText], keyPoints: ['提取关键要点', ListChecks]} as const
export function bindNativeOfficeAssistant(root: HTMLElement, options: Options) {
  const formatLabel=options.format==='xlsx' ? 'Excel' : 'PPT'
  const panel=document.createElement('section');panel.className='native-ai native-ai-panel native-office-assistant';panel.hidden=true;panel.setAttribute('aria-label',formatLabel+' AI 阅读助手')
  const title=document.createElement('h3');title.textContent='AI 助手'
  const help=document.createElement('p');help.textContent='阅读已核验原件或当前未保存草稿；回答不会修改文件。默认整篇阅读，可选择编辑器当前选区；请核对实际覆盖范围。'
  if(options.format==='pptx')help.textContent+='读取引擎已提取的文字、表格和图表缓存；整稿包含演讲者备注，当前对象选区不包含备注。图片视觉不在范围，图表缓存可能不是最新值；范围已读完仅指已提取内容。'
  else help.textContent+='读取单元格值与公式；公式缓存可能未计算，图表、图片及批注不在本次阅读范围。'
  const controls=document.createElement('div')
  const scope=document.createElement('select');scope.dataset.officeAi='scope';scope.setAttribute('aria-label','Office AI 阅读范围')
  for(const [value,label] of [['document','整篇文档（默认）'],['selection','当前选区']]) {const item=document.createElement('option');item.value=value;item.textContent=label;scope.append(item)}
  const input=document.createElement('textarea');input.maxLength=2000;input.setAttribute('aria-label','Office AI 问题或补充要求')
  function button(key: string, label: string, icon: typeof Sparkles) {const item=document.createElement('button');item.type='button';item.dataset.officeAi=key;item.append(createElement(icon,{'aria-hidden':'true',width:18,height:18}),document.createTextNode(label));return item}
  const actionButtons=(Object.keys(actions) as NativeOfficeReadAction[]).map(action=>{const [label,icon]=actions[action];const item=button(action,label,icon);item.onclick=()=>open(action);controls.append(item);return item})
  const start=button('start','开始阅读',Sparkles),cancel=button('cancel','取消任务',CircleStop),close=button('close','关闭助手',X)
  const status=document.createElement('p');status.setAttribute('role','status')
  const transcript = document.createElement('div')
  transcript.className = 'native-ai-transcript'
  panel.append(title,help,controls,scope,input,start,cancel,close,status,transcript);root.append(panel)
  const progress=mountNativeAIProgress(panel)
  const reset = createOfficeNewChatButton()
  const queue = mountOfficeReadQueue(input, submit)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,controls,scope,headerAction:reset,queue:queue.host,onQueue:()=>queue.enqueue(messageMeta())})
  const tasks = new OfficeAssistantController({start:options.api.officeAIStart,status:options.api.officeAIStatus,cancelRequest:options.api.officeAICancel,id:(task: NativeOfficeReadTask)=>task.taskId,running:(task: NativeOfficeReadTask)=>task.status==='running'})
  let action: NativeOfficeReadAction='ask', generation=0,busy=false,disposed=false,hasTurn=false
  let previous: {taskId: string; snapshot: string} | undefined
  function update() {
    reset.hidden=!hasTurn;start.disabled=busy || action==='ask' && !input.value.trim();cancel.disabled=!busy;scope.disabled=busy
    for(const [index,item] of actionButtons.entries()){item.disabled=busy;item.setAttribute('aria-pressed',String(Object.keys(actions)[index]===action))}
    queue.setBusy(busy)
  }
  function messageMeta(): ReadMessageMeta {
    return {action,scope:scope.value==='selection' ? 'selection' : 'document'}
  }
  function submit(instruction: string, meta: ReadMessageMeta) {
    if (disposed || busy || meta.action==='ask' && !instruction) return false
    void run(instruction,meta)
    return true
  }
  function stop(message='任务已取消') {
    const turn=++generation;progress.reset();busy=false
    status.textContent=message;update()
    void tasks.cancel().catch(error=>{if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(result: NonNullable<NativeOfficeReadTask['result']>, question: string) {
    const evidence=appendOfficeAnswer(transcript,question,result.answer,options.format==='pptx')
    const detail=document.createElement('p');const coverage=result.coverage
    detail.textContent='阅读版本：'+(result.readingVersion==='draft' ? '未保存草稿' : '已核验原件')+'；范围：'+(coverage.scope==='selection' ? '当前选区' : '整篇文档')+'；实际完整读取：'+coverage.fullyReadBlockIds.length+' / '+coverage.totalBlocks+' 个内容块；'+(coverage.scopeReadComplete ? '范围已读完' : '范围尚未读完');evidence.append(detail)
    for(const issue of result.issues ?? []){const note=document.createElement('p');note.textContent=issue.message;evidence.append(note)}
    for(const limitation of result.limitations ?? []){const note=document.createElement('p');note.textContent=limitation;evidence.append(note)}
    for(const citation of result.citations ?? []){const note=document.createElement('p');note.textContent='引用：'+citation.label;evidence.append(note)}
    if(result.toolEvents?.length){const tools=document.createElement('p');tools.textContent='已执行工具：'+result.toolEvents.map(event=>nativeAIToolLabel(event.tool)).join(' → ');evidence.append(tools)}
  }
  async function run(instruction: string, {action,scope:messageScope}: ReadMessageMeta) {
    panelView.beforeTask()
    const question = action === 'ask' ? instruction : [(actions[action][0]), instruction].filter(Boolean).join(' · ')
    const turn=++generation
    busy=true;hasTurn=true;update()
    try {
      let captured: NativeOfficeReadContext
      try {
        captured=await options.context(messageScope)
        if(turn!==generation || disposed)return
        if(messageScope==='selection' && (!captured.selection || Array.isArray(captured.selection) && !captured.selection.length))throw new Error('选区无法可靠对应来源，请重新选择有效内容。')
      }catch(error){if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : '未保存编辑同步失败';return}
      const {operations,selection:selected,viewSelection}=structuredClone(captured)
      const snapshot=JSON.stringify({operations,selection:selected,viewSelection}),requestId=crypto.randomUUID()
      progress.reset();status.textContent='正在读取 '+formatLabel+' 文档'
      const task=await tasks.run({clientRequestId:requestId,action,instruction,previousTaskId:action==='ask' && previous?.snapshot===snapshot ? previous.taskId : undefined,expectedSha256:options.draft.identity.sourceSha256,operations,selection:selected,...(viewSelection && options.navigate && options.format==='xlsx' ? {viewSelection} : {})},requestId,(started,signal)=>progress.start(options.api.officeAIEvents,started.taskId,signal,()=>turn===generation && !disposed))
      if(!task || turn!==generation || disposed)return
      const current=await options.context(messageScope)
      if(turn!==generation || disposed)return
      if(snapshot!==JSON.stringify(current)){progress.reset();status.textContent='草稿或选区已变化，请重新阅读。';return}
      if(task.status==='completed' && task.result){
        if(task.result.sourceSha256!==options.draft.identity.sourceSha256){status.textContent='文件来源已变化，请重新阅读。';return}
        let navigationMessage=''
        if(task.result.navigation){
          try{
            if(options.format!=='xlsx' || !options.navigate)throw new Error('当前视图不支持定位')
            await options.navigate(task.result.navigation,()=>turn===generation && !disposed && !options.draft.closed && !options.draft.saving)
            navigationMessage='已定位到 '+task.result.navigation.sheetName+'!'+task.result.navigation.range+'。'
          }catch(error){navigationMessage='定位未完成：'+(error instanceof Error ? error.message : '目标无法显示')}
          if(turn!==generation || disposed)return
        }
        previous={taskId:task.taskId,snapshot};display(task.result,question);status.textContent='阅读完成，文档与草稿未修改。'+navigationMessage
      }
      else status.textContent=task.error?.message ?? (task.status==='cancelled' ? '任务已取消' : 'Office AI 未返回有效回答')
    }catch(error){if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : 'Office AI 阅读失败'}
    finally{if(turn===generation){busy=false;tasks.release();progress.stop();update()}}
  }
  function open(preset: NativeOfficeReadAction='ask') {
    if (disposed) return
    panelView.beforeOpen()
    panel.hidden = false
    panel.scrollIntoView?.({block:'nearest'})
    input.focus({preventScroll:true})
    if (busy && preset === 'ask') return
    if (busy) { queue.hold(); stop() }
    action = preset
    update()
    if (preset !== 'ask') submit(input.value.trim(),messageMeta())
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
  input.oninput=update;scope.onchange=()=>{status.textContent=scope.value==='selection' ? '将读取编辑器当前真实选区；无效选区不会改为整篇阅读。' : '';update()}
  start.onclick=()=>{submit(input.value.trim(),messageMeta())}
  cancel.onclick=()=>{queue.hold();stop()}
  update()
  return {open,dispose(){if(disposed)return;disposed=true;panelView.dispose();stop();queue.dispose();panel.remove()}}
}
