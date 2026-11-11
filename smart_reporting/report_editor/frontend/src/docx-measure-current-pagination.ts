import { slicePaginationSnapshot, withMeasuredPaginationSnapshot, type PaginationMeasurementInput, type PaginationSnapshotInput } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'

export type CurrentDocxPaginationInput = PaginationMeasurementInput & Omit<PaginationSnapshotInput, 'live' | 'blocks' | 'flowH' | 'factor'>

/** 仅按需读取当前真实布局；等待期间的正文/页面/HF变化由宿主身份闭包拒绝。 */
export async function measureCurrentDocxPagination(input: CurrentDocxPaginationInput, stillCurrent: () => boolean) {
  const checkCurrent = () => {
    if (!input.pm.isConnected || !stillCurrent()) throw new Error('文档或页面设置发生变化，请重新打开页眉页脚菜单')
  }
  checkCurrent()
  if (document.fonts) await document.fonts.ready
  checkCurrent()
  for (const image of input.pm.querySelectorAll('img')) {
    await image.decode()
    checkCurrent()
  }
  await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
  checkCurrent()
  const previousZoom = input.pm.style.zoom
  const readSnapshot = () => withMeasuredPaginationSnapshot(input, measured => ({ ...slicePaginationSnapshot({ ...input, ...measured }), live: measured.live, blocks: measured.blocks }))
  let snapshot: ReturnType<typeof readSnapshot>
  try {
    input.pm.style.zoom = '1'
    snapshot = readSnapshot()
  } finally {
    if (previousZoom) input.pm.style.zoom = previousZoom
    else input.pm.style.zoom = ''
  }
  checkCurrent()
  return snapshot
}
