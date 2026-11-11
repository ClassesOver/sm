import type { EditorView } from '@tiptap/pm/view'
import type { Node as PmNode } from '@tiptap/pm/model'

/** 读取真实内容布局；临时100%避免CSS zoom的折叠边框取整影响，绝不平均声明行高。 */
export async function measureDocxRowHeight(view: EditorView, table: PmNode, tableStart: number, top: number, bottom: number, current: () => boolean): Promise<number> {
  const root = view.dom, document = root.ownerDocument, window = document.defaultView!
  const hosts = [root, root.closest<HTMLElement>('.doc-zoom')].filter((node): node is HTMLElement => !!node)
  const zoom = hosts.map(node => ({ node, value: node.style.getPropertyValue('zoom'), priority: node.style.getPropertyPriority('zoom'), computed: window.getComputedStyle(node).getPropertyValue('zoom') }))
  const unchanged = () => {
    if (!current()) throw new Error('均分行高准备期间文档、选区或可编辑状态已改变，请重试')
    if (zoom.some(({node,value,priority,computed}) => node.style.getPropertyValue('zoom') !== value || node.style.getPropertyPriority('zoom') !== priority || window.getComputedStyle(node).getPropertyValue('zoom') !== computed)) throw new Error('均分行高准备期间缩放已改变，请重试')
  }
  const tableDOM = view.nodeDOM(tableStart - 1)
  if (!(tableDOM instanceof window.HTMLElement) || !tableDOM.isConnected || !root.contains(tableDOM)) throw new Error('当前表格尚未布局，无法测量行高')
  const controller = new AbortController(), cleanups: (() => void)[] = []
  const wait = <T>(promise: PromiseLike<T>) => new Promise<T>((resolve,reject) => {
    const aborted = () => reject(controller.signal.reason)
    if (controller.signal.aborted) { aborted(); return }
    controller.signal.addEventListener('abort',aborted,{once:true})
    Promise.resolve(promise).then(resolve,reject).finally(() => controller.signal.removeEventListener('abort',aborted))
    cleanups.push(() => controller.signal.removeEventListener('abort',aborted))
  })
  const timeout = setTimeout(() => controller.abort(new Error('字体、图片或布局准备超时，请加载完成后重试')),15000)
  const monitor = setInterval(() => { try { unchanged() } catch (error) { controller.abort(error) } },100)
  try {
    // ready保证当前字体布局稳定；浏览器fallback字体也是实际渲染内容。
    try { await wait(document.fonts?.ready ?? Promise.resolve()) } catch (error) {
      if (controller.signal.aborted) throw error
      throw new Error('字体布局准备失败，无法均分行高')
    }
    await Promise.all([...tableDOM.querySelectorAll('img')].map(async image => {
      try {
        if (!image.complete) {
          if (image.decode) await wait(image.decode())
          else await wait(new Promise<void>((resolve,reject) => {
            const loaded = () => resolve(), failed = () => reject(new Error('image error'))
            image.addEventListener('load',loaded,{once:true});image.addEventListener('error',failed,{once:true})
            cleanups.push(() => { image.removeEventListener('load',loaded);image.removeEventListener('error',failed) })
          }))
        }
        if (!image.complete || !image.naturalWidth) throw new Error()
      } catch (error) {
        if (controller.signal.aborted) throw error
        throw new Error('表格图片加载失败，无法均分行高')
      }
    }))
    await wait(new Promise<void>(resolve => {
      const frame = window.requestAnimationFrame(() => resolve())
      cleanups.push(() => window.cancelAnimationFrame(frame))
    }))
  } finally {
    clearTimeout(timeout);clearInterval(monitor)
    controller.abort(new Error('行高布局准备已结束'))
    cleanups.forEach(cleanup => cleanup())
  }
  unchanged()
  const owner = tableDOM.tagName === 'TABLE' ? tableDOM : tableDOM.querySelector('table')
  let total = 0, measured = 0
  try {
    for (const {node} of zoom) node.style.setProperty('zoom', '1', 'important')
    table.forEach((_row, offset, index) => {
      if (index < top || index >= bottom) return
      const row = view.nodeDOM(tableStart + offset)
      if (!(row instanceof window.HTMLTableRowElement) || !row.isConnected || !tableDOM.contains(row)) throw new Error(`第 ${index + 1} 行尚未布局，无法完整测量行高`)
      const rowTable = row.closest('table')
      if (!rowTable || owner !== rowTable) throw new Error('行高测量来源表格不一致')
      const height = row.getBoundingClientRect().height
      if (!Number.isFinite(height) || height <= 0) throw new Error(`第 ${index + 1} 行高度无效，无法完整测量行高`)
      total += height; measured++
    })
    if (measured !== bottom - top || !measured) throw new Error('目标行带无法完整测量行高')
  } finally {
    for (const {node,value,priority} of zoom) { if (value) node.style.setProperty('zoom',value,priority); else node.style.removeProperty('zoom') }
  }
  const twips = Math.round(total / measured * 15)
  if (!Number.isSafeInteger(twips) || twips <= 0 || twips > 31680) throw new Error('来源内容行高超出当前支持范围（1–31680 twip）')
  return twips
}
