import type {bindPdfMerge} from './pdf-merge'

/** 同步小入口；文件读取、保存来源流程及对话框在首次点击时载入。 */
export function bindPdfMergeHost(options:Parameters<typeof bindPdfMerge>[0]){
  let disposed=false,controller:ReturnType<typeof bindPdfMerge>|undefined
  return{async open(){
    if(disposed||options.unavailable())return
    const module=await import('./pdf-merge')
    if(disposed||options.unavailable())return
    controller??=module.bindPdfMerge(options);controller.open()
  },dispose(){disposed=true;controller?.dispose()}}
}
