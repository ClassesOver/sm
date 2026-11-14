import {createNativeApi, type NativeContext, type NativeSaveResponse} from './native-api'
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
      const value=saved.editor?.openUrl,sha=saved.artifacts.pdf?.sha256
      if(!saved.revisionRegistered||!value||!sha)throw new Error('当前修改已保存，下载保留；新修订授权尚不可用，请从已保存修订重新打开后拆分')
      const url=new URL(value,window.location.href)
      if(url.origin!==window.location.origin||!url.pathname.startsWith('/reports/v1/native/open/'))throw new Error('新修订编辑授权地址无效，未拆分文件')
      const opened=await fetch(url.href,{credentials:'same-origin',cache:'no-store',referrerPolicy:'no-referrer'})
      if(!opened.ok)throw new Error('新修订授权失败；已保存文件下载保留，请重新打开后拆分')
      const next=await createNativeApi(saved.documentId,saved.revision).context()
      if(next.context.documentId!==saved.documentId||next.context.revision!==saved.revision||next.context.format!=='pdf'||next.context.sourceFile.sha256!==sha||JSON.stringify(next.context.scope)!==JSON.stringify(context.scope))throw new Error('新修订来源身份不一致，未拆分文件')
      splitApi=createNativeApi(saved.documentId,saved.revision,next.csrfToken);splitSha256=sha;splitRevision=saved.revision
    }
    return{sha256:splitSha256,split:async payload=>{
      if(disposed)throw new Error('编辑器已关闭，未提交拆分')
      const release=options.beginSplit()
      try{return await splitApi.splitPdf(payload)}finally{release()}
    }}
  }})
  return{open:dialog.open,dispose(){disposed=true;dialog.dispose()}}
}
