import { OfficeAssistantController } from './office-assistant-controller'
import { bindOfficeAssistantPanel } from './office-assistant-panel'
/** Word 阅读与编辑候选分开；回答不会写入草稿。 */
import { createElement, MessageCircle, FileText, ListChecks, Sparkles, X, CircleStop } from 'lucide'
import type { createNativeApi, NativeWordReadAction, NativeWordReadTask } from './native-api'
import type { NativeDraft } from './native-draft'
import { mountNativeAIProgress } from './native-ai-progress'

type Selection = {blockId: string; cellId?: string}[]
type Options = {
  api: ReturnType<typeof createNativeApi>
  draft: NativeDraft
  selection: () => Selection
  flushPendingEdits: () => void
}
const actions = {ask: ['Word 问答', MessageCircle], summarize: ['总结正文 / 选区', FileText], keyPoints: ['提取关键要点', ListChecks]} as const
const toolLabels = new Map([['get_document_context','读取文档上下文'],['read_blocks','读取文档内容块'],['search_text','搜索文本'],['read_comments','读取批注'],['read_revisions','读取修订']])
export function bindNativeWordAssistant(root: HTMLElement, options: Options) {
  const panel=document.createElement('section');panel.className='native-ai native-ai-panel native-word-assistant';panel.hidden=true;panel.setAttribute('aria-label','Word AI 阅读助手')
  const title=document.createElement('h3');title.textContent='AI 助手'
  const help=document.createElement('p');help.textContent='阅读正文、表格文字及可核验的批注和修订并回答，不修改文档。审阅信息的实际覆盖单独列出。整篇正文阅读包含当前未保存修改；不含页眉、脚注和图片；部分段落按整段读取，单元格按整格读取。结构变更后选区无法核验时请先保存，请核对实际覆盖范围。'
  const controls=document.createElement('div')
  const scope=document.createElement('select');scope.dataset.wordAi='scope';scope.setAttribute('aria-label','Word AI 阅读范围')
  for(const [value,label] of [['document','整篇正文（默认）'],['selection','所选段落/单元格']]) {const item=document.createElement('option');item.value=value;item.textContent=label;scope.append(item)}
  const input=document.createElement('textarea');input.maxLength=2000;input.setAttribute('aria-label','Word AI 问题或补充要求')
  function button(key: string, label: string, icon: typeof Sparkles) {const item=document.createElement('button');item.type='button';item.dataset.wordAi=key;item.append(createElement(icon,{'aria-hidden':'true',width:18,height:18}),document.createTextNode(label));return item}
  const actionButtons=(Object.keys(actions) as NativeWordReadAction[]).map(action=>{const [label,icon]=actions[action];const item=button(action,label,icon);item.onclick=()=>open(action);controls.append(item);return item})
  const start=button('start','开始阅读',Sparkles),cancel=button('cancel','取消任务',CircleStop),close=button('close','关闭助手',X)
  const status=document.createElement('p');status.setAttribute('role','status')
  const output=document.createElement('div');output.style.whiteSpace='pre-wrap'
  const evidence=document.createElement('div');evidence.className='native-ai-evidence'
  panel.append(title,help,controls,scope,input,start,cancel,close,status,output,evidence);root.append(panel)
  const progress=mountNativeAIProgress(panel)
  const panelView = bindOfficeAssistantPanel(panel,{title,help,input,start,cancel,close,controls,scope,onClose:()=>{if(busy)stop()}})
  const tasks = new OfficeAssistantController({start:options.api.wordAIStart,status:options.api.wordAIStatus,cancelRequest:options.api.wordAICancel,id:(task: NativeWordReadTask)=>task.taskId,running:(task: NativeWordReadTask)=>task.status==='running'})
  let action: NativeWordReadAction='ask', generation=0,busy=false,disposed=false
  const selection=()=>scope.value==='selection' ? options.selection() : []
  function update() {start.disabled=busy || action==='ask' && !input.value.trim();cancel.disabled=!busy;scope.disabled=busy;for(const [index,item] of actionButtons.entries()){item.disabled=busy;item.setAttribute('aria-pressed',String(Object.keys(actions)[index]===action))}}
  function stop(message='任务已取消') {
    const turn=++generation;progress.reset();busy=false
    status.textContent=message;update()
    void tasks.cancel().catch(error=>{if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : '服务端取消失败'})
  }
  function display(result: NonNullable<NativeWordReadTask['result']>) {
    output.textContent=result.answer;evidence.replaceChildren()
    const detail=document.createElement('p');const coverage=result.coverage
    detail.textContent='阅读版本：'+(result.readingVersion==='draft' ? '未保存草稿' : '已核验原件')+'；范围：'+(coverage.scope==='selection' ? '当前选区' : '整篇正文')+'；实际完整读取：'+coverage.fullyReadBlockIds.length+' / '+coverage.totalBlocks+' 个内容块；'+(coverage.scopeReadComplete ? '范围已读完' : '范围尚未读完');evidence.append(detail)
    for(const limitation of result.limitations ?? []){const note=document.createElement('p');note.textContent='阅读边界：'+limitation;evidence.append(note)}
    if(result.reviewCoverage){
      for(const [key,label] of [['comments','批注'],['revisions','修订']] as const){
        const coverage=result.reviewCoverage[key],note=document.createElement('p')
        note.textContent=label+'实际完整读取：'+coverage.fullyReadIds.length+' / '+coverage.totalItems+'；'+label+(coverage.readComplete ? '已读完可读取项' : '尚未读完可读取项');evidence.append(note)
      }
    }
    for(const citation of result.reviewCitations ?? []){const note=document.createElement('p');note.textContent='审阅引用：'+citation.label;evidence.append(note)}
    for(const issue of result.issues ?? []){const note=document.createElement('p');note.textContent=issue.message;evidence.append(note)}
    for(const citation of result.citations ?? []){const note=document.createElement('p');note.textContent='引用：第 '+citation.blockNumber+' 个内容块'+(citation.cellId ? '（已选单元格）' : '');evidence.append(note)}
    if(result.toolEvents?.length){const tools=document.createElement('p');tools.textContent='已执行工具：'+result.toolEvents.map(event=>toolLabels.get(event.tool) ?? event.tool).join(' → ');evidence.append(tools)}
  }
  async function run() {
    if(disposed || busy || action==='ask' && !input.value.trim())return
    try {options.flushPendingEdits()} catch(error){status.textContent=error instanceof Error ? error.message : '未保存编辑同步失败';return}
    if(scope.value==='selection' && !selection().length){status.textContent='选区无法可靠对应来源，请选择原有段落/单元格；表结构或新增段落变更后请先保存。';return}
    const turn=++generation,operations=structuredClone(options.draft.operations),selected=structuredClone(selection())
    const snapshot=JSON.stringify({operations,selection:selected}),requestId=crypto.randomUUID()
    busy=true;progress.reset();output.textContent='';evidence.replaceChildren();status.textContent='正在读取 Word 并运行 Agno 工具';update()
    try {
      const task=await tasks.run({clientRequestId:requestId,action,instruction:input.value.trim(),expectedSha256:options.draft.identity.sourceSha256,operations,selection:selected},requestId,(started,signal)=>progress.start(options.api.wordAIEvents,started.taskId,signal,()=>turn===generation && !disposed))
      if(!task || turn!==generation || disposed)return
      options.flushPendingEdits()
      if(snapshot!==JSON.stringify({operations:options.draft.operations,selection:selection()})){progress.reset();status.textContent='草稿或选区已变化，请重新阅读。';return}
      if(task.status==='completed' && task.result){display(task.result);status.textContent='阅读完成，文档与草稿未修改。'}
      else status.textContent=task.error?.message ?? (task.status==='cancelled' ? '任务已取消' : 'Word AI 未返回有效回答')
    }catch(error){if(turn===generation && !disposed)status.textContent=error instanceof Error ? error.message : 'Word AI 阅读失败'}
    finally{if(turn===generation){busy=false;tasks.release();progress.stop();update()}}
  }
  function open(preset: NativeWordReadAction='ask') {if(disposed)return;panelView.beforeOpen();if(busy)stop();action=preset;panel.hidden=false;update();panel.scrollIntoView?.({block:'nearest'});input.focus({preventScroll:true});if(preset!=='ask')void run()}
  input.oninput=update;scope.onchange=()=>{output.textContent='';evidence.replaceChildren();status.textContent=scope.value==='selection' && !selection().length ? '请先选择要阅读的内容。' : '';update()}
  start.onclick=()=>{void run()};cancel.onclick=()=>stop();update()
  return {open,dispose(){if(disposed)return;panelView.dispose();stop();disposed=true;panel.remove()}}
}
