import { IconBringForward, IconBringToFront, IconSendBackward, IconSendToBack } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import type { ComponentType } from 'react'
import { BringToFront, SendToBack, ArrowUp, ArrowDown, Group, Ungroup, Search, Blend, Crosshair, Images, LayoutGrid, ListX, PaintBucket, PanelTop, Printer, Rows3, Save, SquareDashed, Table, TableProperties, createElement } from 'lucide'
import { IconNoneX, IconFind, IconSave, IconPageColor } from './vendor/genoffice-slides/components/icons'
import { Icon3d, IconAnimNone, IconAnimStar, IconApplyAll, IconAudio, IconBullets, IconChangeChartType, IconCrop, IconDirLtr, IconDirRtl, IconEditChartData, IconEraser, IconGridlines, IconHideSlide, IconIndentDec, IconIndentInc, IconLink, IconNavPane, IconNewSlide, IconNotes, IconNumbered, IconObjAlignLeft, IconObjAlignCenterH, IconObjAlignRight, IconObjAlignTop, IconObjAlignMiddle, IconObjAlignBottom, IconObjDistributeH, IconObjDistributeV, IconPageSize, IconPathCircle, IconPathDiagonal, IconPathDown, IconPathRight, IconPathZigzag, IconPen, IconPicture, IconPlayCurrent, IconPosition, IconPresenterView, IconRehearse, IconRecord, IconReplacePicture, IconRuler, IconSpellcheck, IconTranslate, IconVideo, IconWatermark } from './vendor/genoffice-slides/components/icons'

/** 命令的语义图标；控件自带的 sourceIcon 优先于此补全表。 */
export const slidesRibbonSourceIcons: Record<string, ComponentType<{ size?: number }>> = {
  findReplace: IconFind, saveAs: IconSave, bringToFront: IconBringToFront, bringForward: IconBringForward, sendBackward: IconSendBackward, sendToBack: IconSendToBack,
  bulletChar: IconBullets, bulletNumber: IconNumbered, pictureBullet: IconPicture,
  indentDecrease: IconIndentDec, indentIncrease: IconIndentInc, directionLtr: IconDirLtr, directionRtl: IconDirRtl,
  alignCenter:IconObjAlignCenterH, alignRight:IconObjAlignRight, alignTop:IconObjAlignTop, alignMiddle:IconObjAlignMiddle, alignBottom:IconObjAlignBottom, distributeHorizontal:IconObjDistributeH, distributeVertical:IconObjDistributeV,
  alignLeft: IconObjAlignLeft, distribute: IconObjDistributeH, addWatermark: IconWatermark,
  insertLink: IconLink, insertAudio: IconAudio, insertVideo: IconVideo, insertModel3d: Icon3d,
  drawPen: IconPen, drawEraser: IconEraser, customSlideSize: IconPageSize, defaultSlideSize: IconNewSlide, backgroundImage: IconPicture, formatBackground: IconPageColor,
  applyTransitionAll: IconApplyAll, animationPreview: IconPlayCurrent, animationNone: IconAnimNone, addAnimation: IconAnimStar,
  toggleAnimationPane: IconNavPane, animationByParagraph: IconBullets,
  motionPathRight: IconPathRight, motionPathDown: IconPathDown, motionPathDiagonal: IconPathDiagonal, motionPathCircle: IconPathCircle, motionPathZigzag: IconPathZigzag,
  presenter: IconPresenterView, rehearse: IconRehearse, record: IconRecord, hideSlide: IconHideSlide,
  startShowCurrent: IconPlayCurrent,
  spelling: IconSpellcheck, translate: IconTranslate, ruler: IconRuler, grid: IconGridlines, notes: IconNotes,
  chartType: IconChangeChartType, chartData: IconEditChartData, replacePicture: IconReplacePicture, cropPicture: IconCrop,
  shapeGeometry: IconPosition, model3dView: Icon3d, tableRtl: IconDirRtl, shapeNoFill: IconNoneX,
}

export const slidesRibbonIcons: Record<string, Parameters<typeof createElement>[0]> = {
  groupObjects: Group, ungroupObjects: Ungroup,
  bringToFront: BringToFront, bringForward: ArrowUp, sendBackward: ArrowDown, sendToBack: SendToBack,
  findReplace: Search, print: Printer, exportImages: Images, saveAs: Save, bulletNone: ListX, normalView: PanelTop, slideSorter: LayoutGrid,
  tableStructure: TableProperties, tableFirstRow: PanelTop, tableBandRow: Rows3,
  tableShadingWholeTable: PaintBucket, tableAllBorders: Table, tableNoBorders: SquareDashed,
  pictureOpacity: Blend, shapeNoOutline: SquareDashed, guides: Crosshair,
}
