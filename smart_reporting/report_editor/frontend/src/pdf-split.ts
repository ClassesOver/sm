import type {createNativeApi, NativeContext, NativeSaveResponse} from './native-api'
import { authorizeSavedPdfSource } from './pdf-file-source'
import {bindPdfSplitDialog} from './pdf-split-dialog'

/** 每 N 页拆分的保存来源与授权流程，只在首次打开拆分时加载。 */
export function bindPdfSplit(options: {
  root: HTMLElement; api: ReturnType<typeof createNativeApi>; context: NativeContext
  pageCount: () => number; unavailable: () => string | null
  flushForFileOperation?: () => Promise<NativeSaveResponse | undefined>
  beginSplit: () => () => void
}) {
  const {context}=options
  let splitApi=options.api,splitSha256=context.sourceFile.sha256,splitRevision=context.revision,disposed=false
  const dialog=bindPdfSplitDialog({root:options.root,pageCount:options.pageCount,unavailable:options.unavailable,prepareSource:async()=>{
    const saved=await options.flushForFileOperation?.()
    if(saved&&(splitRevision!==saved.revision||splitSha256!==saved.artifacts.pdf?.sha256)){
      const source = await authorizeSavedPdfSource(context, saved, '拆分')
      splitApi = source.api; splitSha256 = source.sha256; splitRevision = source.revision
    }
    return{sha256:splitSha256,split:async payload=>{
      if(disposed)throw new Error('编辑器已关闭，未提交拆分')
      const release=options.beginSplit()
      try{return await splitApi.splitPdf(payload)}finally{release()}
    }}
  }})
  return{open:dialog.open,dispose(){disposed=true;dialog.dispose()}}
}
