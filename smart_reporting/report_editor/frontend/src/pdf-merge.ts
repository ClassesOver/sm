import {createNativeApi,type NativeContext,type NativeSaveResponse} from './native-api'
import {bindPdfMergeDialog} from './pdf-merge-dialog'

/** 首次打开才加载；草稿沿原实际预览确认保存后，授权对应的新来源修订。 */
export function bindPdfMerge(options:{root:HTMLElement;api:ReturnType<typeof createNativeApi>;context:NativeContext;
  unavailable:()=>string|null;flushForFileOperation?:()=>Promise<NativeSaveResponse|undefined>;beginMerge:()=>()=>void}){
  let api=options.api,sha256=options.context.sourceFile.sha256,revision=options.context.revision,disposed=false
  const dialog=bindPdfMergeDialog({root:options.root,unavailable:options.unavailable,prepareSource:async()=>{
    const saved=await options.flushForFileOperation?.()
    if(saved&&(revision!==saved.revision||sha256!==saved.artifacts.pdf?.sha256)){
      const value=saved.editor?.openUrl,nextSha=saved.artifacts.pdf?.sha256
      if(!saved.revisionRegistered||saved.documentId!==options.context.documentId||!value||!nextSha)throw Error('当前修改已保存，下载保留；新修订授权尚不可用，请重新打开后合并')
      const url=new URL(value,window.location.href)
      if(url.origin!==window.location.origin||!url.pathname.startsWith('/reports/v1/native/open/'))throw Error('新修订授权地址无效，未合并文件')
      const opened=await fetch(url.href,{credentials:'same-origin',cache:'no-store',referrerPolicy:'no-referrer'})
      if(!opened.ok)throw Error('新修订授权失败；已保存文件下载保留，请重新打开后合并')
      const next=await createNativeApi(saved.documentId,saved.revision).context()
      if(next.context.documentId!==saved.documentId||next.context.revision!==saved.revision||next.context.format!=='pdf'||next.context.sourceFile.sha256!==nextSha||JSON.stringify(next.context.scope)!==JSON.stringify(options.context.scope))throw Error('新修订来源身份不一致，未合并文件')
      api=createNativeApi(saved.documentId,saved.revision,next.csrfToken);sha256=nextSha;revision=saved.revision
    }
    return{sha256,merge:async payload=>{
      if(disposed)throw Error('编辑器已关闭，未提交合并')
      const release=options.beginMerge()
      try{return await api.mergePdf(payload)}finally{release()}
    }}
  }})
  return{open:dialog.open,dispose(){disposed=true;dialog.dispose()}}
}
