import { officeRequest, officeSession } from './office-client'

/** A generated asset becomes a native edit only after explicit acceptance against an unchanged draft. */
export function mountOfficeGeneratedImage(host: HTMLElement, options: {
  identity(): string | undefined;
  insert(file: File, expectedIdentity: string): Promise<void>;
}) {
  const panel = document.createElement('section'); panel.className = 'office-native-image-tools'
  const title = document.createElement('h3'); title.textContent = 'AI 生图'
  const form = document.createElement('form'), prompt = document.createElement('textarea')
  prompt.setAttribute('aria-label', '生图要求'); prompt.placeholder = '描述要加入当前幻灯片的图片'; prompt.maxLength = 1000; prompt.required = true
  const generate = document.createElement('button'); generate.type = 'submit'; generate.textContent = '生成预览'
  const preview = document.createElement('img'); preview.alt = 'AI 生成图片预览'; preview.hidden = true
  const accept = document.createElement('button'); accept.type = 'button'; accept.textContent = '确认加入当前幻灯片'; accept.dataset.insert = ''; accept.disabled = true
  const status = document.createElement('p'); status.setAttribute('role', 'status')
  let busy = false, candidate: {file: File; identity: string} | undefined
  const freeze = (value: boolean) => {busy=value;generate.disabled=value;prompt.disabled=value;accept.disabled=value||!candidate}
  const clear = () => {candidate=undefined;preview.hidden=true;preview.removeAttribute('src');accept.disabled=true}
  form.append(prompt,generate);panel.append(title,form,preview,accept,status);host.append(panel)
  form.onsubmit = async event => {
    event.preventDefault()
    const identity=options.identity()
    if(busy)return
    if(!identity){clear();status.textContent='当前页面不可插入图片，请选择可编辑的来源幻灯片。';return}
    if(!prompt.value.trim())return
    clear();freeze(true);status.textContent='正在生成图片…'
    try {
      await officeSession()
      const result=await officeRequest<{previewDataUrl:string;mediaType:string}>('/media/images','POST',{prompt:prompt.value.trim()})
      if(!panel.isConnected||options.identity()!==identity)throw new Error('文档、页面或草稿已变化，请重新生成图片。')
      const parts=/^data:(image\/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)$/.exec(result.previewDataUrl)
      if(!parts||parts[2]!.length>8*1024*1024+8)throw new Error('服务未返回有效图片。')
      const bytes=Uint8Array.from(atob(parts[2]!),char=>char.charCodeAt(0))
      candidate={file:new File([bytes],parts[1]==='image/png'?'generated.png':'generated.jpg',{type:parts[1]}),identity}
      preview.src=result.previewDataUrl;preview.hidden=false;status.textContent='请检查预览，确认后加入当前幻灯片草稿。'
    } catch(error) {clear();if(panel.isConnected)status.textContent=(error as Error).message}
    finally {freeze(false)}
  }
  accept.onclick=async()=>{
    if(busy||!candidate)return
    if(options.identity()!==candidate.identity){clear();status.textContent='文档、页面或草稿已变化，请重新生成图片。';return}
    freeze(true)
    try {await options.insert(candidate.file,candidate.identity);clear();status.textContent='图片已加入草稿，保存后生成新修订。'}
    catch(error){if(panel.isConnected)status.textContent=(error as Error).message}
    finally{freeze(false)}
  }
}
