import type {createNativeApi,NativeContext,NativeSaveResponse} from './native-api'

interface SplitState {
  disposed: boolean; loaded: boolean; locked: boolean; previewing: boolean; printing: boolean
  mutating: boolean; blocked: boolean; editable: boolean; pages: number
  closed: boolean; dirty: boolean; unstaged: boolean
}

/** 小宿主随 PDF 加载；来源流程与对话框只在首次点击时动态载入。 */
export function bindPdfSplitHost(options:{
  root:HTMLElement;api:ReturnType<typeof createNativeApi>;context:NativeContext
  state:()=>SplitState;flushForFileOperation?:()=>Promise<NativeSaveResponse|undefined>
  beginMutation:()=>()=>void;setLocked:(value:boolean)=>void
}){
  let disposed=false,controller:ReturnType<typeof import('./pdf-split')['bindPdfSplit']>|undefined
  const unavailable=()=>{
    const state=options.state()
    if(disposed||state.disposed||!state.loaded||state.locked||state.previewing||state.printing||state.mutating||state.blocked||!state.editable)return '当前 PDF 只读或正在变更，请稍后拆分'
    if(state.pages<2)return '至少两页才能拆分 PDF'
    if(!options.flushForFileOperation&&(state.closed||state.dirty||state.unstaged))return '请先保存当前修改后重新打开，再拆分 PDF'
    return null
  }
  return{unavailable,async open(){
    if(unavailable())return
    const {bindPdfSplit}=await import('./pdf-split')
    if(disposed||options.state().disposed)return
    controller??=bindPdfSplit({root:options.root,api:options.api,context:options.context,pageCount:()=>options.state().pages,
      unavailable,flushForFileOperation:options.flushForFileOperation,beginSplit:()=>{
        if(disposed||options.state().disposed)throw new Error('编辑器已关闭，未提交拆分')
        const release=options.beginMutation();options.setLocked(true)
        return()=>{release();options.setLocked(false)}
      }})
    controller.open()
  },dispose(){disposed=true;controller?.dispose()}}
}
