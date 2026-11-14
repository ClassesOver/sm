// 三个字段设置区共用桌面面板结构与焦点生命周期；不读取或修改业务草稿。
export function createPdfFormSettingsPanel(root:HTMLElement,className:string,title:string,helpText:string,closeText:string){
 const doc=root.ownerDocument,panel=doc.createElement('section'),header=doc.createElement('header'),heading=doc.createElement('h3'),help=doc.createElement('p'),close=doc.createElement('button'),status=doc.createElement('p'),body=doc.createElement('fieldset')
 panel.className=className+' pdf-form-settings-panel';panel.hidden=true;panel.setAttribute('aria-label',title)
 heading.textContent=title;help.textContent=helpText;close.type='button';close.textContent=closeText;status.setAttribute('role','status');body.className='pdf-form-settings-fields'
 header.append(heading,close);panel.append(header,help,status,body);root.append(panel)
 let opener:HTMLElement|null=null,disposed=false
 function hide(){if(disposed||panel.hidden)return;panel.hidden=true;const target=opener?.isConnected&&!opener.matches(':disabled')&&!opener.closest('[hidden],[inert]')?opener:root.querySelector<HTMLElement>('[data-pdf-ribbon-tab][aria-selected="true"]');target?.focus({preventScroll:true})}
 close.addEventListener('click',hide)
 panel.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented){event.preventDefault();event.stopPropagation();hide()}})
 const controls=()=>Array.from(body.querySelectorAll<HTMLElement>('input,select,textarea,button'))
 const controlKey=(element:HTMLElement)=>[element.getAttribute('aria-label')??element.textContent,element.closest<HTMLElement>('[data-pdf-form-widget]')?.dataset.pdfFormWidget]
 return {panel,body,status,
  open(){if(disposed)return;if(!panel.contains(doc.activeElement))opener=doc.activeElement as HTMLElement|null;panel.hidden=false;close.focus({preventScroll:true})},
  render(build:()=>void){
   if(disposed)return
   const active=doc.activeElement as HTMLElement|null,key=active&&body.contains(active)?controlKey(active):null
   build()
   const legend=doc.createElement('legend');legend.textContent='字段设置';body.prepend(legend)
   for(const input of body.querySelectorAll<HTMLInputElement>('input[type=checkbox]'))input.parentElement?.classList.add('pdf-form-settings-check')
   for(const input of body.querySelectorAll('textarea'))input.parentElement?.classList.add('pdf-form-settings-multiline')
   if(key&&!panel.hidden){const target=controls().find(element=>JSON.stringify(controlKey(element))===JSON.stringify(key)&&!element.matches(':disabled'));(target??close).focus({preventScroll:true})}
  },
  dispose(){disposed=true;panel.remove()},
 }
}
