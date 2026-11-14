import type {NativePdfSplitResult} from './native-api'
import {installFocusTrap} from './focus-trap'

type SplitRequest = {requestId: string; expectedSha256: string; chunkSize: number}
export function bindPdfSplitDialog(options: {
  root: HTMLElement; pageCount: () => number; unavailable: () => string | null
  prepareSource: () => Promise<{sha256: string; split: (payload: SplitRequest) => Promise<NativePdfSplitResult>}>
}) {
  const owner=options.root.ownerDocument, dialog=owner.createElement('dialog')
  dialog.className='pdf-layout-dialog pdf-extract-dialog pdf-split-dialog';dialog.setAttribute('aria-label','拆分 PDF')
  const header=owner.createElement('header'),title=owner.createElement('h3'),topClose=owner.createElement('button')
  title.textContent='每 N 页拆分为独立 PDF';topClose.type='button';topClose.textContent='×';topClose.setAttribute('aria-label','关闭拆分 PDF');header.append(title,topClose)
  const body=owner.createElement('div');body.className='pdf-extract-body';body.tabIndex=0;body.setAttribute('role','region');body.setAttribute('aria-label','拆分说明与结果')
  const hint=owner.createElement('p');hint.textContent='先按现有预览确认流程保存当前修改，再按保存后的页序每 N 页生成一份，尾部不足 N 页也保留。至少两份；来源修订保持不变。当前支持无表单、批注或保护信息的 PDF，书签与附件不保留。若需预览确认，请关闭此窗口、核对并勾选确认后再次拆分。关闭窗口不撤销已经生成的文件。'
  const label=owner.createElement('label'),input=owner.createElement('input');label.textContent='每份页数';input.type='text';input.inputMode='numeric';input.value='1';input.setAttribute('aria-label','每份页数');label.append(input)
  const message=owner.createElement('p');message.setAttribute('role','status')
  const results=owner.createElement('section');results.setAttribute('aria-label','拆分结果')
  const actions=owner.createElement('footer'),close=owner.createElement('button'),apply=owner.createElement('button')
  actions.className='pdf-layout-actions';close.type=apply.type='button';close.textContent='关闭';apply.textContent='保存修改并拆分';apply.dataset.pdfSplitApply='';actions.append(close,apply)
  body.append(hint,label,message,results);dialog.append(header,body,actions);options.root.append(dialog)
  const releaseFocus=installFocusTrap(dialog)
  let disposed=false,busy=false,generation=0,opener:HTMLElement|null=null,cached:NativePdfSplitResult|undefined
  let requestKey='',requestId=''
  const safe=(value:string|undefined)=>{if(!value)return null;try{const url=new URL(value,owner.baseURI);return ['http:','https:'].includes(url.protocol)&&url.origin===new URL(owner.baseURI).origin?value:null}catch{return null}}
  function show(result:NativePdfSplitResult){
    results.replaceChildren();message.textContent=`拆分结果：${result.parts.length} 份；验收未通过或待复核。${result.validation.issues.map(issue=>issue.message||issue.code).join('；')}`
    for(const part of result.parts){
      const row=owner.createElement('article'),heading=owner.createElement('p');heading.textContent=`${part.filename} · 第 ${part.pages[0]}–${part.pages.at(-1)} 页`;heading.style.overflowWrap='anywhere';row.append(heading)
      const details=owner.createElement('p');details.textContent=part.error?.message??part.result?.validation.issues.map(issue=>issue.message||issue.code).join('；')??'未返回可用文件';row.append(details)
      const links=owner.createElement('div');links.className='pdf-extract-links';row.append(links)
      for(const [text,value]of [['下载 PDF',part.result?.artifacts.pdf?.downloadUrl],['打开独立文档',part.result?.editor?.openUrl]]){
        const href=safe(value);if(!href)continue
        const link=owner.createElement('a');link.textContent=text!;link.href=href;link.rel='noopener';link.referrerPolicy='no-referrer';if(text==='下载 PDF')link.download=part.filename;links.append(link)
      }
      results.append(row)
    }
  }
  dialog.addEventListener('close',()=>{generation++;if(opener?.isConnected&&!opener.matches(':disabled')&&!owner.querySelector('dialog[open]'))opener.focus({preventScroll:true})})
  for(const button of [close,topClose])button.addEventListener('click',()=>dialog.close())
  apply.addEventListener('click',()=>{void submit()})
  async function submit(){
    if(disposed||busy||!dialog.open)return
    const reason=options.unavailable();if(reason){message.textContent=reason;return}
    const text=input.value.trim(),chunkSize=Number(text)
    if(!/^\d+$/.test(text)||!Number.isSafeInteger(chunkSize)||chunkSize<1||chunkSize>=options.pageCount()){message.textContent='每份页数须为大于0且小于总页数的整数';return}
    const token=generation;busy=true;input.disabled=apply.disabled=true;dialog.setAttribute('aria-busy','true');message.textContent='正在保存当前修改并拆分 PDF…'
    try{
      const source=await options.prepareSource()
      if(disposed||!dialog.open||generation!==token)return
      const key=JSON.stringify([source.sha256,chunkSize]);if(key!==requestKey){requestKey=key;requestId=crypto.randomUUID();cached=undefined;results.replaceChildren()}
      const result=await source.split({requestId,expectedSha256:source.sha256,chunkSize});cached=result
      if(!disposed&&dialog.open&&generation===token)show(result)
    }catch(error){if(!disposed&&dialog.open&&generation===token)message.textContent=error instanceof Error?error.message:String(error)}
    finally{busy=false;if(!disposed){input.disabled=apply.disabled=false;dialog.setAttribute('aria-busy','false')}}
  }
  return{
    open(){if(disposed||busy||dialog.open)return;const reason=options.unavailable();if(reason)return;generation++;if(cached)show(cached);else message.textContent='';opener=owner.activeElement instanceof HTMLElement?owner.activeElement:null;dialog.showModal();input.focus()},
    dispose(){if(disposed)return;disposed=true;generation++;releaseFocus();dialog.remove()},
  }
}
