/** Native adapter for pinned App sidebar drag lifecycle. Source: genoffice-pdf-sidebar-source.json. */
import { SIDEBAR_W_KEY, SIDEBAR_W_DEFAULT, SIDEBAR_W_MIN, clampSidebarW, loadSidebarW } from './genoffice-pdf-sidebar-config'
export function createPdfSidebarSizing(divider: HTMLElement, onWidth: (width: number, committed: boolean) => void) {
  const lifetime = new AbortController()
  let width: number
  try { width = clampSidebarW(loadSidebarW()) } catch { width = clampSidebarW(SIDEBAR_W_DEFAULT) }
  let disposed = false, panel: HTMLElement | undefined
  let drag: { id: number; x: number; start: number; next: number; cursor: string; select: string; events: AbortController; frame?: number } | undefined
  const sync = () => {
    divider.hidden = !panel
    const max = clampSidebarW(Number.MAX_SAFE_INTEGER)
    divider.setAttribute('aria-valuemin', String(Math.min(SIDEBAR_W_MIN,max))); divider.setAttribute('aria-valuemax',String(max)); divider.setAttribute('aria-valuenow',String(Math.round(width)))
    if (panel) divider.setAttribute('aria-controls',panel.id); else divider.removeAttribute('aria-controls')
  }
  const apply = (next: number, committed = false) => {
    if (disposed) return
    width = clampSidebarW(next); onWidth(width,committed); sync()
    if (committed) try { localStorage.setItem(SIDEBAR_W_KEY,String(Math.round(width))) } catch { /* optional UI preference */ }
  }
  const end = (commit: boolean) => {
    const current = drag
    if (!current) return
    drag = undefined; current.events.abort()
    if (current.frame !== undefined) cancelAnimationFrame(current.frame)
    try { divider.releasePointerCapture(current.id) } catch { /* capture may have ended */ }
    document.body.style.cursor=current.cursor; document.body.style.userSelect=current.select
    divider.classList.remove('is-resizing')
    if (!disposed) apply(commit?current.next:current.start,commit)
  }
  divider.setAttribute('role','separator'); divider.setAttribute('aria-orientation','vertical'); divider.setAttribute('aria-label','调整 PDF 侧栏宽度'); divider.tabIndex=0
  divider.addEventListener('pointerdown', event => {
    if (disposed || !panel || event.button!==0 || !event.isPrimary) return
    event.preventDefault(); end(false)
    drag={id:event.pointerId,x:event.clientX,start:width,next:width,cursor:document.body.style.cursor,select:document.body.style.userSelect,events:new AbortController()}
    const current=drag
    document.body.style.cursor='col-resize'; document.body.style.userSelect='none'; divider.classList.add('is-resizing'); divider.focus()
    try { divider.setPointerCapture(event.pointerId) } catch { /* window listeners also track capture */ }
    window.addEventListener('pointermove', ev => {
      if (drag!==current || ev.pointerId!==current.id) return
      current.next=clampSidebarW(current.start+ev.clientX-current.x)
      if (current.frame===undefined) current.frame=requestAnimationFrame(()=>{current.frame=undefined;if(drag===current)apply(current.next)})
    },{signal:current.events.signal})
    window.addEventListener('pointerup', ev => {
      if (drag!==current || ev.pointerId!==current.id) return
      current.next=clampSidebarW(current.start+ev.clientX-current.x); end(true)
    },{signal:current.events.signal})
    window.addEventListener('pointercancel', ev => {if(drag===current&&ev.pointerId===current.id)end(false)},{signal:current.events.signal})
  },{signal:lifetime.signal})
  divider.addEventListener('lostpointercapture',()=>end(false),{signal:lifetime.signal})
  window.addEventListener('blur',()=>end(false),{signal:lifetime.signal})
  window.addEventListener('keydown', event => {if(event.key==='Escape'&&drag&&!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented){event.preventDefault();end(false)}},{signal:lifetime.signal})
  divider.addEventListener('keydown', event => {
    if(disposed||!panel||drag||event.isComposing||event.keyCode===229||event.defaultPrevented)return
    const target=event.key==='Home'?SIDEBAR_W_MIN:event.key==='End'?Number.MAX_SAFE_INTEGER:event.key==='ArrowLeft'?width-10:event.key==='ArrowRight'?width+10:undefined
    if(target===undefined)return
    event.preventDefault(); apply(target,true)
  },{signal:lifetime.signal})
  window.addEventListener('resize',()=>{end(false);apply(width)},{signal:lifetime.signal})
  apply(width)
  return { get width(){return width}, setPanel(next?:HTMLElement){end(false);panel=next;sync()}, dispose(){if(disposed)return;end(false);disposed=true;lifetime.abort()} }
}
