import {afterEach,expect,it,vi} from 'vitest'
import {createSlidesNativeRibbon} from './slides-native-ribbon'
afterEach(()=>document.body.replaceChildren())
it('开放对象剪贴板、格式刷和超链接，并保留固定源动作身份',()=>{
 const host=document.body.appendChild(document.createElement('div')),onAction=vi.fn(),ribbon=createSlidesNativeRibbon(host,{onAction})
 for(const [command,source] of [['copy','onCopy'],['cut','onCut'],['paste','onPaste'],['formatBrush','onFormatBrushClick'],['insertLink','onOpenLink']]){
  const control=host.querySelector<HTMLButtonElement>('[data-command="'+command+'"]')!
  expect(control.disabled,command).toBe(false);expect(control.dataset.sourceAction).toBe(source);control.click()
 }
 expect(onAction.mock.calls.map(([command])=>command)).toEqual(['copy','cut','paste','formatBrush','insertLink'])
 ribbon.dispose()
})
it('格式刷双击可进入持续模式',()=>{
 const host=document.body.appendChild(document.createElement('div')),onAction=vi.fn(),ribbon=createSlidesNativeRibbon(host,{onAction})
 host.querySelector('[data-command="formatBrush"]')!.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))
 expect(onAction).toHaveBeenCalledWith('formatBrush','continuous');ribbon.dispose()
})
