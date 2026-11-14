import type {NativePdfMergeRequest,NativeSaveResponse} from './native-api'
import {installFocusTrap} from './focus-trap'

// 沿用外部页面上传的现有6MiB传输边界；不改固定源合并writer的结构能力。
const MAX_BYTES=6*1024*1024
export function bindPdfMergeDialog(options:{root:HTMLElement;unavailable:()=>string|null;
  prepareSource:()=>Promise<{sha256:string;merge:(payload:NativePdfMergeRequest)=>Promise<NativeSaveResponse>}>}){
  const owner=options.root.ownerDocument,dialog=owner.createElement('dialog')
  dialog.className='pdf-layout-dialog pdf-extract-dialog pdf-merge-dialog';dialog.setAttribute('aria-label','合并 PDF')
  const header=owner.createElement('header'),title=owner.createElement('h3'),topClose=owner.createElement('button')
  title.textContent='合并为独立 PDF';topClose.type='button';topClose.textContent='×';topClose.setAttribute('aria-label','关闭合并 PDF');header.append(title,topClose)
  const body=owner.createElement('div');body.className='pdf-extract-body';body.tabIndex=0;body.setAttribute('role','region');body.setAttribute('aria-label','合并文件及结果')
  const hint=owner.createElement('p');hint.textContent='当前文档在前，其后按列表顺序追加所选 PDF。先沿现有实际预览确认流程保存当前修改，再生成独立文档，原来源保留。外部上传文件合计不超过现有 6 MiB 上限。基文档结构沿源流程保留；外部表单字段树、目录及附件不保证完整迁移，签名有效性不保证，请下载核对。加密文件需先解密。若提示确认，请关闭此窗口核对并勾选实际预览后继续。'
  const label=owner.createElement('label'),file=owner.createElement('input');label.textContent='选择追加的 PDF（可多选）';file.type='file';file.multiple=true;file.accept='application/pdf,.pdf';file.setAttribute('aria-label','选择合并 PDF 文件');label.append(file)
  const list=owner.createElement('ol'),message=owner.createElement('p'),links=owner.createElement('div');list.setAttribute('aria-label','追加文件顺序');message.setAttribute('role','status');links.className='pdf-extract-links'
  const actions=owner.createElement('footer'),close=owner.createElement('button'),apply=owner.createElement('button')
  actions.className='pdf-layout-actions';close.type=apply.type='button';close.textContent='关闭';apply.textContent='保存修改并合并';apply.dataset.pdfMergeApply='';actions.append(close,apply)
  body.append(hint,label,list,message,links);dialog.append(header,body,actions);options.root.append(dialog)
  const releaseFocus=installFocusTrap(dialog)
  let files:File[]=[],busy=false,disposed=false,generation=0,requestKey='',requestId='',cached:NativeSaveResponse|undefined,opener:HTMLElement|null=null
  const clearResult=()=>{cached=undefined;links.replaceChildren();message.textContent=''}
  function renderFiles(){
    list.replaceChildren()
    files.forEach((picked,index)=>{
      const row=owner.createElement('li'),name=owner.createElement('span');name.textContent=picked.name;name.style.overflowWrap='anywhere';row.append(name)
      for(const [text,offset]of [['上移',-1],['下移',1],['移除',0]] as const){
        const button=owner.createElement('button');button.type='button';button.textContent=text;button.setAttribute('aria-label',`${text} ${picked.name}`)
        button.disabled=busy||(offset===-1&&index===0)||(offset===1&&index===files.length-1)
        button.addEventListener('click',()=>{if(busy)return;if(offset===0)files.splice(index,1);else[files[index],files[index+offset]]=[files[index+offset]!,files[index]!];clearResult();renderFiles()});row.append(button)
      }
      list.append(row)
    })
  }
  function show(result:NativeSaveResponse){
    message.textContent=`合并 PDF 已生成；${result.validation.ok?'验收通过':'验收未通过或待复核'}。${result.validation.issues.map(issue=>issue.message||issue.code).join('；')}`;links.replaceChildren()
    for(const [text,value]of [['下载合并 PDF',result.artifacts.pdf?.downloadUrl],['打开独立文档',result.editor?.openUrl]]){
      if(!value)continue
      try{const url=new URL(value,owner.baseURI);if(!['http:','https:'].includes(url.protocol)||url.origin!==new URL(owner.baseURI).origin)continue}catch{continue}
      const link=owner.createElement('a');link.textContent=text!;link.href=value;link.rel='noopener';link.referrerPolicy='no-referrer';if(text==='下载合并 PDF')link.download='merged.pdf';links.append(link)
    }
  }
  file.addEventListener('change',()=>{if(busy)return;files=Array.from(file.files??[]);clearResult();renderFiles()})
  dialog.addEventListener('close',()=>{generation++;if(opener?.isConnected&&!opener.matches(':disabled')&&!owner.querySelector('dialog[open]'))opener.focus({preventScroll:true})})
  for(const button of [close,topClose])button.addEventListener('click',()=>dialog.close())
  apply.addEventListener('click',()=>{void submit()})
  async function submit(){
    if(disposed||busy||!dialog.open)return
    const reason=options.unavailable();if(reason){message.textContent=reason;return}
    if(!files.length||files.some(value=>!value.size)||files.reduce((sum,value)=>sum+value.size,0)>MAX_BYTES){message.textContent='请选择至少一份 PDF，外部文件总大小不得超过 6 MiB';return}
    const token=generation,selected=[...files];busy=true;file.disabled=apply.disabled=true;renderFiles();dialog.setAttribute('aria-busy','true');message.textContent='正在核验上传、保存当前修改并合并 PDF…'
    try{
      const uploads:NativePdfMergeRequest['files']=[]
      for(const picked of selected){
        const bytes=new Uint8Array(await picked.arrayBuffer())
        if(bytes.length!==picked.size||new TextDecoder().decode(bytes.subarray(0,5))!=='%PDF-')throw Error(`${picked.name} 不是有效 PDF`)
        const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('')
        let binary='';for(let at=0;at<bytes.length;at+=32768)binary+=String.fromCharCode(...bytes.subarray(at,at+32768))
        uploads.push({sha256,bytesBase64:btoa(binary)})
      }
      if(disposed||!dialog.open||generation!==token)return
      const source=await options.prepareSource()
      if(disposed||!dialog.open||generation!==token)return
      const key=JSON.stringify([source.sha256,uploads.map(value=>value.sha256)]);if(key!==requestKey){requestKey=key;requestId=crypto.randomUUID();cached=undefined;links.replaceChildren()}
      cached=await source.merge({requestId,expectedSha256:source.sha256,files:uploads})
      if(!disposed&&dialog.open&&generation===token)show(cached)
    }catch(error){if(!disposed&&dialog.open&&generation===token)message.textContent=error instanceof Error?error.message:String(error)}
    finally{busy=false;if(!disposed){file.disabled=apply.disabled=false;renderFiles();dialog.setAttribute('aria-busy','false')}}
  }
  return{open(){if(disposed||busy||dialog.open||options.unavailable())return;generation++;if(cached)show(cached);else message.textContent='';opener=owner.activeElement instanceof HTMLElement?owner.activeElement:null;dialog.showModal();file.focus()},
    dispose(){if(disposed)return;disposed=true;generation++;releaseFocus();dialog.remove()}}
}
