import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {IFormulaEditorManagerService} from '@univerjs/sheets-ui'
import {InsertFunctionFlow} from './workbook-function-flow'
import {readLiveFunctionInfos} from './workbook-function-catalog'
import {createWorkbookFunctionHost,type FunctionTarget} from './workbook-function-runtime'
import './workbook-insert-function.css'

export function createWorkbookInsertFunction(root:HTMLElement, options:{
  runtime:any;editable:()=>boolean;protectedSheet:(sheetId:string)=>boolean;
  onWrite:(formula:string,target:FunctionTarget)=>void;onError?:(message:string)=>void;
  file?: () => Promise<{ bytes: ArrayBuffer }>
}){
 const element=document.createElement('div');element.className='workbook-function-root';root.append(element)
 const react=createRoot(element),host=createWorkbookFunctionHost(options.runtime,options)
 let disposed=false,opened=false,pending=false,fx:{unsubscribe():void}|undefined
 const close=()=>{opened=false;flushSync(()=>react.render(null))}
 const open=async(category='All'):Promise<void>=>{
  if(disposed||opened||pending)return
  pending=true
  try{
   const target=await host.readTarget()
   if(disposed||!target)return
   const functions=readLiveFunctionInfos(options.runtime)
   opened=true
   flushSync(()=>react.render(<InsertFunctionFlow functions={functions} target={target} initialCategory={category} host={host} onClose={close}/>))
  }finally{pending=false}
 }
 // Univer 0.25 的原生 fx 会以 DOCS unit 开启工作表编辑，Escape 时错误地按 workbook 取选区。
 // 浏览器宿主接管真实按钮，让函数对话框独立管理编辑会话；保留 service 订阅供程序触发。
 const clickFx=(event:MouseEvent)=>{
  if(!(event.target instanceof Element))return
  const button=event.target.closest('[data-u-comp="formula-bar"] span')
  if(!button?.querySelector('.univerjs-icon-fx-icon'))return
  event.preventDefault();event.stopPropagation()
  void open().catch(error=>options.onError?.((error as Error).message))
 }
 root.addEventListener('click',clickFx,true)
 const refresh=()=>{
  if(disposed||fx)return
  const injector=options.runtime.univer?.__getInjector?.()
  if(typeof injector?.has==='function' && injector.has(IFormulaEditorManagerService)) fx=injector.get(IFormulaEditorManagerService).fxBtnClick$.subscribe(()=>{void open().catch(error=>options.onError?.((error as Error).message))})
 }
 refresh()
 return {open,refresh,dispose(){if(disposed)return;disposed=true;host.dispose();root.removeEventListener('click',clickFx,true);fx?.unsubscribe();react.unmount();element.remove()}}
}
