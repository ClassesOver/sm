import { createNativeApi, type NativeContext, type NativeSaveResponse } from './native-api'

export type PdfFileOperation = '拆分' | '提取' | '导出图片' | '打印' | '插入或替换页面'

/** The save's open grant binds a PDF file operation to the new revision, not its old session. */
export async function authorizeSavedPdfSource(context: NativeContext, saved: NativeSaveResponse, operation: PdfFileOperation) {
  const grant = saved.editor?.openUrl
  const sha256 = saved.artifacts.pdf?.sha256
  if (!saved.revisionRegistered || saved.documentId !== context.documentId || !grant || !sha256) {
    throw new Error('当前修改已保存，下载保留；新修订授权尚不可用，请从已保存修订重新打开后' + operation)
  }
  const url = new URL(grant, window.location.href)
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/reports/v1/native/open/')) throw new Error('新修订授权地址无效，未' + operation + '文件')
  const opened = await fetch(url.href, { credentials:'same-origin', cache:'no-store', referrerPolicy:'no-referrer' })
  if (!opened.ok) throw new Error('新修订授权失败；已保存文件下载保留，请重新打开后' + operation)
  const { context: next, csrfToken } = await createNativeApi(saved.documentId, saved.revision).context()
  if (next.documentId !== saved.documentId || next.revision !== saved.revision || next.format !== 'pdf' || next.sourceFile.sha256 !== sha256 || JSON.stringify(next.scope) !== JSON.stringify(context.scope)) {
    throw new Error('新修订来源身份不一致，未' + operation + '文件')
  }
  return { api: createNativeApi(saved.documentId, saved.revision, csrfToken), sha256, revision: saved.revision }
}
