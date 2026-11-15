import type {NativePDFNavigation} from './native-api'

/** Verify host page identity and actual viewport; this cannot edit or save a PDF. */
export async function navigatePDFReadTarget(target: NativePDFNavigation, options: {
  pages(): readonly {pageId:string}[]
  currentPage(): string
  pageNode(pageId:string): HTMLElement | undefined
  viewport: HTMLElement
  current(): boolean
  available(): boolean
  navigate(pageId:string): void
}): Promise<void> {
  const order=()=>JSON.stringify(options.pages().map(page=>page.pageId)),before=order()
  if(!options.current() || !options.available())throw new Error('任务或文档状态已变化')
  if(!Number.isSafeInteger(target.page) || target.page<1 || typeof target.pageId!=='string' || !target.pageId
    || options.pages()[target.page-1]?.pageId!==target.pageId)throw new Error('目标页码与当前 PDF 页面身份不一致')
  const node=options.pageNode(target.pageId),viewport=options.viewport
  if(!node || !node.isConnected || !viewport.contains(node) || node.dataset.pageId!==target.pageId)
    throw new Error('目标页面尚未就绪')
  options.navigate(target.pageId)
  await new Promise<void>(resolve=>window.requestAnimationFrame(()=>resolve()))
  if(!options.current() || !options.available() || before!==order() || options.currentPage()!==target.pageId
    || options.pageNode(target.pageId)!==node || !node.isConnected || !node.classList.contains('is-active'))
    throw new Error('当前页面或任务已变化，定位未完成')
  const card=node.getBoundingClientRect(),view=viewport.getBoundingClientRect()
  if(card.width<=0 || card.height<=0 || view.width<=0 || view.height<=0
    || card.top>=view.bottom || card.bottom<=view.top || card.left>=view.right || card.right<=view.left)
    throw new Error('目标页面未能显示')
}
