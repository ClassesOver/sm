import { afterEach, expect, it, vi } from 'vitest'
import { createNativeChartGallery, type NativeChartGalleryState } from './slides-native-chart-gallery'
import { chartColorSchemes } from '../../../reporting/slides_engine/bridge/pptx-chart-design'

const galleries: ReturnType<typeof createNativeChartGallery>[] = []
afterEach(()=>{galleries.splice(0).forEach(gallery=>gallery.dispose());document.body.replaceChildren()})
const state: NativeChartGalleryState={target:'revision:1:chart',kind:'bar',style:{legendPos:'b',dataLabels:false,gridlines:false},colorSchemes:chartColorSchemes()}
function fixture(){
 const host=document.body.appendChild(document.createElement('div')),action=vi.fn(),gallery=createNativeChartGallery(host,action);galleries.push(gallery);gallery.setState(state)
 return {host,action,gallery,toggle:host.querySelector<HTMLButtonElement>('[data-chart-colors-toggle]')!,menu:document.querySelector<HTMLElement>('[data-chart-colors-menu]')!}
}
function protectedKey(node:HTMLElement,key:string,protection:string){const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();node.dispatchEvent(event);return event}
it.each(['composition','legacy','handled'])('图表配色图库保留受保护打开按键：%s',protection=>{
 const f=fixture();f.toggle.focus();const event=protectedKey(f.toggle,'ArrowDown',protection)
 expect(f.menu.hidden).toBe(true);expect(f.toggle.getAttribute('aria-expanded')).toBe('false');expect(document.activeElement).toBe(f.toggle);expect(event.defaultPrevented).toBe(protection==='handled');expect(f.action).not.toHaveBeenCalled()
 f.toggle.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));expect(f.menu.hidden).toBe(false);expect(document.activeElement).toBe(f.menu.querySelector('button'))
})
it.each(['composition','legacy','handled'])('图表配色图库保留受保护Escape和当前卡片：%s',protection=>{
 const f=fixture();f.toggle.click();const card=f.menu.querySelector<HTMLButtonElement>('[data-chart-scheme-card=blue]')!;card.focus()
 const event=protectedKey(card,'Escape',protection);expect(f.menu.hidden).toBe(false);expect(document.activeElement).toBe(card);expect(event.defaultPrevented).toBe(protection==='handled');expect(f.action).not.toHaveBeenCalled()
 card.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(f.menu.hidden).toBe(true);expect(document.activeElement).toBe(f.toggle)
})
it('图库选择只执行一次，目标切换和锁定后旧卡片不再写入',()=>{
 const f=fixture();f.toggle.click();const stale=f.menu.querySelector<HTMLButtonElement>('[data-chart-scheme-card=blue]')!
 f.gallery.setState({...state,target:'revision:1:other'});stale.click();expect(f.action).not.toHaveBeenCalled()
 f.toggle.click();f.menu.querySelector<HTMLButtonElement>('[data-chart-scheme-card=warm]')!.click();expect(f.action).toHaveBeenCalledExactlyOnceWith('chartColorScheme','warm');expect(document.activeElement).toBe(f.toggle)
 f.toggle.click();f.gallery.setLocked(true);expect(f.menu.hidden).toBe(true);expect(f.toggle.disabled).toBe(true)
 f.gallery.setLocked(false);expect(f.menu.hidden).toBe(true)
})
