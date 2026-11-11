import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesChartFormatPane, type SlidesChartFormatState } from './slides-chart-format-pane'

const initial: SlidesChartFormatState = { target:'rev1:0:chart', kind:'bar', categories:['甲','乙'],
  series:[{name:'收入',values:[1,2]},{name:'成本',values:[3,4]}],
  pointColors:{0:{0:'#123ABC'}}, seriesColors:['#ED7D31','#FFC000'] }
let pane: ReturnType<typeof createSlidesChartFormatPane>
beforeEach(()=>{vi.useFakeTimers();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)})
afterEach(()=>{act(()=>pane?.dispose());document.body.replaceChildren();vi.useRealTimers();vi.unstubAllGlobals()})
function open(state=initial) {
 const onConfirm=vi.fn();pane=createSlidesChartFormatPane(onConfirm)
 document.body.append(pane.element);act(()=>pane.update(state))
 return onConfirm
}
const well=(point:string)=>pane.element.querySelector<HTMLButtonElement>(`[data-chart-format-well="${point}"]`)!
function pick(point:string,color:string) {
 if(document.querySelector('[data-chart-format-palette]'))act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
 act(()=>well(point).click())
 const input=document.querySelector<HTMLInputElement>('[data-chart-format-custom]')!
 act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,color);input.dispatchEvent(new Event('input',{bubbles:true}))})
}
it('源侧栏分组和共享颜色图库呈现来源覆盖、系列色，支持主题色和键盘退出',()=>{
 const confirm=open()
 expect(pane.element.textContent).toContain('数据点颜色')
 expect([...pane.element.querySelectorAll('.fp-chart-series')].map(el=>el.textContent)).toEqual(['收入','成本'])
 expect(well('0:0').querySelector<HTMLElement>('.fp-color-well-swatch')!.style.background).toBe('rgb(18, 58, 188)')
 expect(well('1:0').querySelector<HTMLElement>('.fp-color-well-swatch')!.style.background).toBe('rgb(255, 192, 0)')
 act(()=>well('0:0').click())
 expect(document.querySelectorAll('[role="gridcell"]')).toHaveLength(70)
 expect(document.querySelector('[data-chart-format-custom]')).not.toBeNull()
 act(()=>document.querySelector<HTMLButtonElement>('[role="gridcell"][data-pos="0-5"]')!.click())
 act(()=>vi.advanceTimersByTime(200))
 expect(confirm).toHaveBeenLastCalledWith({0:{0:'#E97132'}},initial.target)
 act(()=>well('1:0').click())
 act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
 expect(document.querySelector('[data-chart-format-palette]')).toBeNull()
})
it('200ms内多个点合并单笔提交，更多颜色对话框在回填后保持同一input',()=>{
 const confirm=open()
 pick('0:1','#abcdef')
 act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
 pick('1:0','#112233')
 const custom=document.querySelector('[data-chart-format-custom]')
 act(()=>vi.advanceTimersByTime(199));expect(confirm).not.toHaveBeenCalled()
 act(()=>vi.advanceTimersByTime(1))
 expect(confirm).toHaveBeenCalledExactlyOnceWith({0:{1:'#ABCDEF'},1:{0:'#112233'}},initial.target)
 act(()=>pane.update({...initial,pointColors:{0:{0:'#123ABC',1:'#ABCDEF'},1:{0:'#112233'}}}))
 expect(document.querySelector('[data-chart-format-custom]')).toBe(custom)
})
it('切目标、外部回填、锁定和dispose取消待生效颜色，旧控件不能提交到新目标',()=>{
 const confirm=open();const stale=well('0:0')
 pick('0:0','#abcdef')
 act(()=>pane.update({...initial,target:'rev1:0:other'}))
 act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
 act(()=>stale.click());expect(document.querySelector('[data-chart-format-palette]')).toBeNull()
 pick('0:0','#112233');act(()=>pane.update(initial,true))
 expect(well('0:0').disabled).toBe(true)
 act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
 act(()=>pane.update(initial));pick('0:0','#123abc')
 expect(pane.flush()).toBe(true);expect(confirm).not.toHaveBeenCalled()
 pick('0:0','#abcdef');act(()=>pane.dispose());act(()=>vi.advanceTimersByTime(250))
 expect(confirm).not.toHaveBeenCalled()
})
it('恢复来源覆盖写显式null，保存前flush且提交失败保留重试机会',()=>{
 const confirm=open()
 act(()=>pane.element.querySelector<HTMLButtonElement>('[data-chart-format-reset="0:0"]')!.click())
 confirm.mockImplementationOnce(()=>{throw new Error('来源已变化')})
 act(()=>expect(pane.flush()).toBe(false))
 expect(pane.element.textContent).toContain('来源已变化')
 act(()=>expect(pane.flush()).toBe(true))
 expect(confirm).toHaveBeenCalledTimes(2)
 expect(confirm).toHaveBeenLastCalledWith({0:{0:null}},initial.target)
})
it('饼图家族按类别回退，散点和不安全来源只显示具体只读原因',()=>{
 open({...initial,kind:'doughnut',pointColors:{},seriesColors:['#000000']})
 expect(well('0:1').querySelector<HTMLElement>('.fp-color-well-swatch')!.style.background).toBe('rgb(237, 125, 49)')
 act(()=>pane.update({...initial,kind:'scatter'}))
 expect(pane.element.textContent).toContain('散点图')
 expect(pane.element.querySelector('[data-chart-format-well]')).toBeNull()
 act(()=>pane.update({...initial,reason:'来源图表含不支持扩展'}))
 expect(pane.element.textContent).toContain('来源图表含不支持扩展')
 act(()=>pane.update(null));expect(pane.element.hidden).toBe(true)
})
it('同一目标锁定再解锁不会自动重开旧颜色浮层',()=>{
 open();act(()=>well('0:0').click())
 expect(document.querySelector('[data-chart-format-palette]')).not.toBeNull()
 act(()=>pane.setLocked(true));act(()=>pane.setLocked(false))
 expect(document.querySelector('[data-chart-format-palette]')).toBeNull()
})
