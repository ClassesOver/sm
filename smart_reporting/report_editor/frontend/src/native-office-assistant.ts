import { bindOfficeAssistantPanel } from './office-assistant-panel'
/** Office 阅读与编辑候选分开；回答不会写入草稿。 */
import { createElement, MessageCircle, FileText, ListChecks, Sparkles, X, CircleStop } from 'lucide'
import type { createNativeApi, NativeOfficeReadAction, NativeOfficeReadTask, NativeOfficeReadContext } from './native-api'
import type { NativeDraft } from './native-draft'
import { mountNativeAIProgress, nativeAIToolLabel } from './native-ai-progress'

type Options = {
  api: ReturnType<typeof createNativeApi>
  draft: NativeDraft
  format: 'xlsx' | 'pptx'
  context: (scope: 'document' | 'selection') => Promise<NativeOfficeReadContext>
}
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
  const output=document.createElement('div');output.style.whiteSpace='pre-wrap'
  const evidence=document.createElement('div');evidence.className='native-ai-evidence'
  panel.append(title,help,controls,scope,input,start,cancel,close,status,output,evidence);root.append(panel)
  const progress=mountNativeAIProgress(panel)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,controls,scope,onClose:()=>{if(busy)stop()}})
  let action: NativeOfficeReadAction='ask', generation=0,busy=false,disposed=false,activeRequest: string | undefined,controller: AbortController | undefined
  function update() {start.disabled=busy || action==='ask' && !input.value.trim();cancel.disabled=!busy;scope.disabled=busy;for(const [index,item] of actionButtons.entries()){item.disabled=busy;item.setAttribute('aria-pressed',String(Object.keys(actions)[index]===action))}}
  function stop(message='任务已取消') {
    const turn=++generation;controller?.abort();progress.reset();busy=false
    const id=activeRequest;activeRequest=undefined;status.textContent=message;update()
    if(id) void options.api.officeAICancel(id).catch(error=>{if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(result: NonNullable<NativeOfficeReadTask['result']>) {
    output.textContent=result.answer;evidence.replaceChildren()
    const detail=document.createElement('p');const coverage=result.coverage
    detail.textContent='阅读版本：'+(result.readingVersion==='draft' ? '未保存草稿' : '已核验原件')+'；范围：'+(coverage.scope==='selection' ? '当前选区' : '整篇文档')+'；实际完整读取：'+coverage.fullyReadBlockIds.length+' / '+coverage.totalBlocks+' 个内容块；'+(coverage.scopeReadComplete ? '范围已读完' : '范围尚未读完');evidence.append(detail)
    for(const issue of result.issues ?? []){const note=document.createElement('p');note.textContent=issue.message;evidence.append(note)}
    for(const limitation of result.limitations ?? []){const note=document.createElement('p');note.textContent=limitation;evidence.append(note)}
    for(const citation of result.citations ?? []){const note=document.createElement('p');note.textContent='引用：'+citation.label;evidence.append(note)}
    if(result.toolEvents?.length){const tools=document.createElement('p');tools.textContent='已执行工具：'+result.toolEvents.map(event=>nativeAIToolLabel(event.tool)).join(' → ');evidence.append(tools)}
  }
  async function run() {
    if(disposed || busy || action==='ask' && !input.value.trim())return
    const turn=++generation
    busy=true;update()
    let captured: NativeOfficeReadContext
    try {
      captured=await options.context(scope.value==='selection' ? 'selection' : 'document')
      if(turn!==generation || disposed)return
      if(scope.value==='selection' && (!captured.selection || Array.isArray(captured.selection) && !captured.selection.length))throw new Error('选区无法可靠对应来源，请重新选择有效内容。')
    }catch(error){if(turn===generation && !disposed){busy=false;status.textContent=error instanceof Error ? error.message : '未保存编辑同步失败';update()}return}
    const {operations,selection:selected}=structuredClone(captured)
    const snapshot=JSON.stringify({operations,selection:selected}),requestId=crypto.randomUUID()
    activeRequest=requestId;controller=new AbortController();const signal=controller.signal;busy=true;progress.reset();output.textContent='';evidence.replaceChildren();status.textContent='正在读取 '+formatLabel+' 文档';update()
    try {
      let task=await options.api.officeAIStart({clientRequestId:requestId,action,instruction:input.value.trim(),expectedSha256:options.draft.identity.sourceSha256,operations,selection:selected},signal)
      if(turn!==generation || disposed)return
      progress.start(options.api.officeAIEvents,task.taskId,signal,()=>turn===generation && !disposed)
      while(turn===generation && !disposed && task.status==='running')task=await options.api.officeAIStatus(task.taskId,signal)
      if(turn!==generation || disposed)return
      const current=await options.context(scope.value==='selection' ? 'selection' : 'document')
      if(turn!==generation || disposed)return
      if(snapshot!==JSON.stringify(current)){progress.reset();status.textContent='草稿或选区已变化，请重新阅读。';return}
      if(task.status==='completed' && task.result){display(task.result);status.textContent='阅读完成，文档与草稿未修改。'}
      else status.textContent=task.error?.message ?? (task.status==='cancelled' ? '任务已取消' : 'Office AI 未返回有效回答')
    }catch(error){if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : 'Office AI 阅读失败'}
    finally{if(turn===generation){busy=false;activeRequest=undefined;progress.stop();update()}}
  }
  function open(preset: NativeOfficeReadAction='ask') {if(disposed)return;panelView.beforeOpen();if(busy)stop();action=preset;panel.hidden=false;update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true});if(preset!=='ask')void run()}
  input.oninput=update;scope.onchange=()=>{output.textContent='';evidence.replaceChildren();status.textContent=scope.value==='selection' ? '将读取编辑器当前真实选区；无效选区不会改为整篇阅读。' : '';update()}
  start.onclick=()=>{void run()};cancel.onclick=()=>stop();update()
  return {open,dispose(){if(disposed)return;panelView.dispose();stop();disposed=true;panel.remove()}}
}
