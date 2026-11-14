import { SheetsNotePopupService } from '@univerjs/sheets-note-ui'
import type { NotePictureSnapshot } from './workbook-note-pictures'

type PictureLookup = (sheetId: string, row: number, column: number) => { key: string; pictures?: any[]; picture?: any } | undefined

export function installNotePictureHover(runtime: any, picturesAt: PictureLookup, onCard: (picture: any, key: string) => void) {
  const injector = runtime?.univer?.__getInjector?.()
  const service = injector?.get?.(SheetsNotePopupService)
  if (!service?.activePopup$?.subscribe) return { dispose() {} }
  let lastKey = ''
  const subscription = service.activePopup$.subscribe((popup: any) => {
    if (!popup) { onCard(null, lastKey); return }
    const value = picturesAt(String(popup.subUnitId ?? popup.sheetId ?? ''), Number(popup.row ?? 0), Number(popup.col ?? popup.column ?? 0))
    if (!value) { onCard(null, lastKey); return }
    lastKey = value.key
    onCard(value.picture ?? value.pictures?.[0] ?? null, value.key)
  })
  return { dispose: () => subscription.unsubscribe() }
}

export function projectPictureNotes(model: any, snapshot: NotePictureSnapshot) {
  // 快照是扁平图片列表；宿主按 sheetName 归组，避免伪造不存在的 sheet 结构。
  for (const sheet of model?.sheets ?? []) {
    const pictures = snapshot.pictures.filter((picture: any) => picture.sheetName === sheet.name)
    if (!pictures.length) continue
    const source = snapshot.sheets?.find(item => item.sheetName === sheet.name)
    sheet.notes = { ...(sheet.notes ?? {}), notes: source?.notes ?? pictures.map(picture => ({row: picture.row, column: picture.column, author: picture.author, text: picture.text})), pictures, pictureProjection: true, readOnlyReason: sheet.notes?.readOnlyReason ?? '图片批注由独立图片操作保存' }
  }
  return model
}
