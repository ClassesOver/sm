import type {ISheetDrawingPosition} from '@univerjs/sheets-drawing'

export const WORKBOOK_PICTURE_EDIT_COMMANDS = ['sheet.command.set-sheet-image', 'sheet.command.remove-sheet-image'] as const
export const WORKBOOK_PICTURE_EDIT_WRAPPERS = ['sheet.command.move-drawing', 'sheet.command.delete-drawing'] as const

export interface PictureGeometry {
  row:number;column:number;rowOffsetPx:number;columnOffsetPx:number;widthPx:number;heightPx:number
}
interface PictureSource extends PictureGeometry {
  sheetName:string;drawingPart:string;pictureId:string;sha256:string;geometryReadOnlyReason?:string
}
export interface WorkbookPictureBinding {picture:PictureSource;drawing:Record<string,unknown>}
export interface WorkbookPictureEdit {
  kind:'editPicture';sheetName:string;drawingPart:string;pictureId:string;mediaSha256:string
  before:PictureGeometry;geometry:PictureGeometry|null
}
export type ResolvePictureTransform = (subUnitId:string,position:ISheetDrawingPosition) =>
  {left?:number;top?:number;width?:number;height?:number}|null|undefined

const problem = () => new Error('普通图片编辑参数或身份不一致，请重新选择图片')
function object(value:unknown):Record<string,unknown> {
  if(!value || typeof value!=='object' || Array.isArray(value))throw problem()
  return value as Record<string,unknown>
}
function same(a:unknown,b:unknown):boolean {
  if(a===b)return true
  if(!a || !b || typeof a!=='object' || typeof b!=='object')return false
  const x=Object.keys(a),y=Object.keys(b)
  return x.length===y.length && x.every(key=>Object.hasOwn(b,key) && same((a as Record<string,unknown>)[key],(b as Record<string,unknown>)[key]))
}
function unchanged(value:Record<string,unknown>,baseline:Record<string,unknown>,mutable:readonly string[]) {
  for(const [key,item] of Object.entries(value))if(!mutable.includes(key) && !same(item,baseline[key]))throw problem()
}
function number(value:unknown,min:number,max=Number.MAX_SAFE_INTEGER,integer=false):number {
  if(typeof value!=='number' || !Number.isFinite(value) || value<min || value>max || integer && !Number.isInteger(value))throw problem()
  return value
}
function neutral(value:Record<string,unknown>) {
  for(const key of ['angle','skewX','skewY'])if(value[key]!==undefined && value[key]!==0)throw problem()
  for(const key of ['flipX','flipY'])if(value[key]!==undefined && value[key]!==false)throw problem()
}
const rotation=['angle','skewX','skewY','flipX','flipY']
function position(value:unknown):ISheetDrawingPosition {
  const pos=object(value);neutral(pos)
  if(Object.keys(pos).some(key=>!['from','to',...rotation].includes(key)))throw problem()
  for(const key of ['from','to']) {
    const cell=object(pos[key])
    if(Object.keys(cell).some(field=>!['row','column','rowOffset','columnOffset'].includes(field)))throw problem()
    number(cell.row,0,1048575,true);number(cell.column,0,16383,true)
    number(cell.rowOffset,0);number(cell.columnOffset,0)
  }
  return pos as unknown as ISheetDrawingPosition
}
function geometry(picture:PictureGeometry):PictureGeometry {
  const {row,column,rowOffsetPx,columnOffsetPx,widthPx,heightPx}=picture
  return {row,column,rowOffsetPx,columnOffsetPx,widthPx,heightPx}
}

/** 仅翻译原生命令。宿主须取消默认执行，再将整批交给现有草稿历史。 */
export function captureWorkbookPictureEdits(
  command:{id:string;params?:unknown},unitId:string,
  bindings:ReadonlyMap<string,WorkbookPictureBinding>,resolveTransform:ResolvePictureTransform,
):WorkbookPictureEdit[]|undefined {
  if(!WORKBOOK_PICTURE_EDIT_COMMANDS.some(id=>id===command.id))return undefined
  const params=object(command.params)
  if(params.unitId!==unitId || !Array.isArray(params.drawings) || !params.drawings.length ||
    Object.keys(params).some(key=>!['unitId','drawings'].includes(key)))throw problem()
  const seen=new Set<string>()
  // 整批先校验，任何一项失败均不返回可提交的部分结果。
  return params.drawings.map(raw=>{
    const drawing=object(raw),id=drawing.drawingId
    if(typeof id!=='string' || seen.has(id))throw problem()
    seen.add(id)
    const binding=bindings.get(id)
    if(!binding || drawing.unitId!==unitId || binding.drawing.unitId!==unitId ||
      binding.drawing.drawingId!==id || drawing.subUnitId!==binding.drawing.subUnitId)throw problem()
    const deleting=command.id===WORKBOOK_PICTURE_EDIT_COMMANDS[1]
    unchanged(drawing,binding.drawing,deleting?[]:['transform','sheetTransform','axisAlignSheetTransform'])
    let next:PictureGeometry|null=null
    if(!deleting) {
      if(binding.picture.geometryReadOnlyReason)throw new Error(binding.picture.geometryReadOnlyReason)
      const pos=position(drawing.sheetTransform),axis=position(drawing.axisAlignSheetTransform)
      if(!same(pos.from,axis.from) || !same(pos.to,axis.to))throw problem()
      const transform=object(drawing.transform);neutral(transform)
      unchanged(transform,object(binding.drawing.transform),['left','top','width','height',...rotation])
      const actual={left:number(transform.left,0),top:number(transform.top,0),
        width:number(transform.width,Number.MIN_VALUE,4000),height:number(transform.height,Number.MIN_VALUE,4000)}
      const normalized=resolveTransform(drawing.subUnitId as string,pos)
      if(!normalized || (Object.keys(actual) as (keyof typeof actual)[]).some(key=>
        typeof normalized[key]!=='number' || !Number.isFinite(normalized[key]) || Math.abs(actual[key]-normalized[key]!)>1e-5))throw problem()
      next={row:pos.from.row,column:pos.from.column,rowOffsetPx:pos.from.rowOffset,
        columnOffsetPx:pos.from.columnOffset,widthPx:actual.width,heightPx:actual.height}
    }
    const picture=binding.picture
    return {kind:'editPicture',sheetName:picture.sheetName,drawingPart:picture.drawingPart,
      pictureId:picture.pictureId,mediaSha256:picture.sha256,before:geometry(picture),geometry:next}
  })
}
