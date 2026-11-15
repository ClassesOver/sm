import type {Editor} from '@tiptap/core'
import type {Block} from '@genoffice/docx-engine'
import {createModal} from './modal'
import {blockTexts,editorBlockTexts,compareParagraphs,summarize} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/compare'
import {parseDocxOffThread} from './vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread'

/** Source comparison reports text differences; it does not create a revision document. */
export function createDocxCompareControls(options:{editor:Editor;blocks:Block[];container:HTMLElement;flush():void;onError(error:unknown):void}){
 let modal:ReturnType<typeof createModal>|undefined,disposed=false,generation=0
 const close=()=>{++generation;modal?.remove();modal=undefined}
 function open(){
  if(disposed||options.editor.isDestroyed)return
  close()
  modal=createModal({root:options.container,label:'文档比较',closeLabel:'关闭文档比较',variant:'wide',onRequestClose:close,content:'<h2>文档比较</h2><p>比较当前未保存正文与另一份 DOCX 的段落文本。表格和对象沿用来源预览文本；不比较完整格式、页眉页脚，不修改文档或生成修订。</p><label>选择比较文件（DOCX，最大 8 MiB）<input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"></label><p role="status" aria-live="polite"></p><div data-compare-results style="white-space:pre-wrap;overflow-wrap:anywhere"></div>'})
  const current=modal,input=current.card.querySelector<HTMLInputElement>('input')!,status=current.card.querySelector<HTMLElement>('[role=status]')!,results=current.card.querySelector<HTMLElement>('[data-compare-results]')!
  input.onchange=async()=>{
   const file=input.files?.[0];if(!file)return
   const turn=++generation;results.replaceChildren();status.textContent='正在比较段落文本'
   try{
    if(file.size>8*1024*1024)throw new Error('比较文件超过8 MiB，请选择较小的 DOCX。')
    options.flush();const snapshot=options.editor.state.doc
    const other=await parseDocxOffThread(new Uint8Array(await file.arrayBuffer()))
    if(disposed||turn!==generation||modal!==current)return
    if(options.editor.state.doc!==snapshot){status.textContent='当前文档已变化，请重新选择比较文件。';return}
    const left=editorBlockTexts(snapshot.toJSON(),options.blocks),right=blockTexts(other.blocks)
    if((left.length+1)*(right.length+1)>2_000_000)throw new Error('段落数量过多，超出本次比较容量，请拆分文档后比较。')
    const entries=compareParagraphs(left,right),counts=summarize(entries)
    status.textContent=`${file.name}：新增 ${counts.added}，删除 ${counts.removed}，修改 ${counts.changed}。`
    const labels={same:'相同',added:'新增',removed:'删除',changed:'修改'}
    for(const entry of entries){if(entry.kind==='same')continue;const row=document.createElement('section'),title=document.createElement('strong');title.textContent=labels[entry.kind];row.append(title)
     for(const [key,label] of [['left','当前'],['right','比较文件']] as const){if(entry[key]===undefined)continue;const text=document.createElement('p');text.textContent=`${label}：${entry[key]}`;row.append(text)}results.append(row)}
   }catch(error){if(!disposed&&turn===generation&&modal===current){status.textContent=error instanceof Error?error.message:'文档比较失败';options.onError(error)}}
  }
  current.open()
 }
 return {open,dispose(){disposed=true;close()}}
}
