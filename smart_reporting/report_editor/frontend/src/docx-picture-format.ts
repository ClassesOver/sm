import type {DocxAnchor,DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
export const PICTURE_WRAPS=['square-left','square-right','tight-left','tight-right','through-left','through-right','topBottom','behind','front'] as const
export type PictureFormatPatch={widthPx?:number;heightPx?:number;rotDeg?:number;flipH?:boolean;flipV?:boolean;align?:'left'|'center'|'right'|null;wrap?:typeof PICTURE_WRAPS[number]|null;posH?:'left'|'center'|'right';posV?:'top'|'center'|'bottom'}
export type PictureFormatAnchor=DocxAnchor & {imageFormatEditable?:boolean}
const mapping={widthPx:'imageWidthPx',heightPx:'imageHeightPx',rotDeg:'imageRotDeg',flipH:'imageFlipH',flipV:'imageFlipV',align:'imageAlign',wrap:'imageWrap',posH:'imagePosH',posV:'imagePosV'} as const
function patchOf(op:NativeOperation):PictureFormatPatch{
 if(Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','expectedImageSha256',...Object.keys(mapping)].includes(k)))throw new Error('图片格式字段无效')
 const patch=Object.fromEntries(Object.keys(mapping).filter(k=>Object.hasOwn(op,k)).map(k=>[k,op[k]])) as PictureFormatPatch
 if(!Object.keys(patch).length)throw new Error('图片格式为空')
 if((patch.widthPx===undefined)!==(patch.heightPx===undefined))throw new Error('图片尺寸必须成对')
 for(const k of ['widthPx','heightPx'] as const)if(patch[k]!==undefined&&(!Number.isInteger(patch[k])||patch[k]!<1||patch[k]!>10000))throw new Error('图片尺寸超出范围')
 if(patch.rotDeg!==undefined&&(!Number.isInteger(patch.rotDeg)||patch.rotDeg<0||patch.rotDeg>359))throw new Error('图片角度无效')
 for(const k of ['flipH','flipV'] as const)if(patch[k]!==undefined&&typeof patch[k]!=='boolean')throw new Error('图片翻转无效')
 if(patch.align!==undefined&&patch.align!==null&&!['left','center','right'].includes(patch.align))throw new Error('图片对齐无效')
 if(patch.wrap!==undefined&&patch.wrap!==null&&!PICTURE_WRAPS.includes(patch.wrap))throw new Error('图片环绕无效')
 if((patch.posH===undefined)!==(patch.posV===undefined)||patch.posH!==undefined&&(!['left','center','right'].includes(patch.posH)||!['top','center','bottom'].includes(patch.posV!)||patch.wrap!==(patch.posH==='right'?'square-right':'square-left')))throw new Error('图片位置无效')
 return patch
}
export function projectDocxPictureFormat(source:DocxPmNode,anchor:PictureFormatAnchor,op:NativeOperation):DocxPmNode{
 if(!anchor.imageFormatEditable||source.type!=='docProtected'||source.attrs?.blockType!=='image'||source.attrs.imageReplace||op.kind!=='formatImage'||op.blockId!==anchor.blockId||op.expectedObjectSha256!==anchor.expectedObjectSha256||op.expectedImageSha256!==anchor.imageSha256)throw new Error('图片格式来源身份无效或含未保存的图片替换')
 const patch=patchOf(op),attrs:Record<string,unknown>={...source.attrs,imageFormat:patch}
 for(const key of Object.keys(patch) as (keyof PictureFormatPatch)[])attrs[mapping[key]]=patch[key]
 if(patch.posH){attrs.imageOffsetXEmu=null;attrs.imageOffsetYEmu=null}
 return {...structuredClone(source),attrs}
}
export function normalizeDocxPictureFormats(baseline:DocxPmNode,current:DocxPmNode,anchors:PictureFormatAnchor[]){
 const result=structuredClone(current),operations:NativeOperation[]=[]
 for(const node of result.content??[]){
  if(!node.attrs?.imageFormat)continue
  const anchor=anchors.find(a=>a.docxIndex===node.attrs!.docxIndex),source=baseline.content?.find(n=>n.attrs?.docxIndex===node.attrs!.docxIndex)
  if(!anchor||!source||node.attrs.imageReplace)throw new Error('图片格式与图片替换需分别保存')
  const op={kind:'formatImage',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,expectedImageSha256:anchor.imageSha256,...node.attrs.imageFormat}
  const projected=projectDocxPictureFormat(source,anchor,op)
  for(const key of [...Object.values(mapping),'imageFormat',...((node.attrs.imageFormat as PictureFormatPatch).posH?['imageOffsetXEmu','imageOffsetYEmu']:[])]){
   if(JSON.stringify(node.attrs[key])!==JSON.stringify(projected.attrs?.[key]))throw new Error('图片格式预览与草稿不一致')
   if(Object.hasOwn(source.attrs!,key))node.attrs[key]=source.attrs![key];else delete node.attrs[key]
  }
  operations.push(op)
 }
 return {current:result,operations}
}
export function pictureSizeForSide(widthPx:number,heightPx:number,side:'w'|'h',pixels:number,lockAspect:boolean){
 if(![widthPx,heightPx,pixels].every(v=>Number.isFinite(v)&&v>0))throw new Error('图片尺寸无效')
 const next=side==='w'?{widthPx:Math.round(pixels),heightPx:lockAspect?Math.max(1,Math.round(pixels*heightPx/widthPx)):heightPx}:{widthPx:lockAspect?Math.max(1,Math.round(pixels*widthPx/heightPx)):widthPx,heightPx:Math.round(pixels)}
 if(Object.values(next).some(v=>v<1||v>10000))throw new Error('图片尺寸超出范围')
 return next
}
export function resetPictureDimensions(naturalWidth:number,naturalHeight:number,hostWidth:number){
 if(![naturalWidth,naturalHeight,hostWidth].every(v=>Number.isFinite(v)&&v>0))throw new Error('图片自然尺寸无效')
 const scale=Math.min(1,hostWidth/naturalWidth)
 const widthPx=Math.max(1,Math.round(naturalWidth*scale)),heightPx=Math.max(1,Math.round(naturalHeight*scale))
 return pictureSizeForSide(widthPx,heightPx,'w',widthPx,false)
}
