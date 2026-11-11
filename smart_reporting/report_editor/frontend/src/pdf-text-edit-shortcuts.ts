export function bindPdfTextEditShortcuts(textarea:HTMLTextAreaElement,stage:HTMLButtonElement,signal:AbortSignal):void{
 textarea.addEventListener('keydown',event=>{
  if(event.defaultPrevented||event.key!=='Enter'||!(event.ctrlKey||event.metaKey)||event.altKey||event.repeat||event.isComposing||event.keyCode===229)return
  if(textarea.matches(':disabled')||textarea.readOnly||stage.matches(':disabled')||textarea.closest('[hidden]'))return
  event.preventDefault();stage.click()
 },{signal})
}
