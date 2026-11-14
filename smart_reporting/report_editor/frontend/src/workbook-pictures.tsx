import {createRoot,type Root} from 'react-dom/client'
import {EquationDialog} from './workbook-picture-equation'
import {IconsDialog} from './workbook-picture-icons'
import {noteImageInfo} from '@sheets-web/xlsx-engine/note-pictures'
import {sha256Hex} from '@sheets-web/xlsx-engine/sha256'
import type {WorkbookPicture} from '@sheets-web/xlsx-engine/pictures'
import './workbook-pictures.css'
export interface PictureInput {dataUrl:string;width:number;height:number;name:string}
export function controlledWorkbookPicture(input:PictureInput){
 const match=/^data:(image\/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)$/.exec(input.dataUrl)
 if(!match)throw new Error('仅支持受控 PNG/JPEG 图片')
 const bytes=Uint8Array.from(atob(match[2]!),c=>c.charCodeAt(0)),info=noteImageInfo(bytes)
 if(info.mediaType!==match[1])throw new Error('图片格式身份不匹配')
 return {mediaType:info.mediaType,bytesBase64:match[2]!,size:bytes.length,sha256:sha256Hex(bytes),widthPx:info.width,heightPx:info.height,name:input.name.slice(0,255)}
}
export function createWorkbookPictures(){
 let root:Root|undefined,host:HTMLDivElement|undefined,disposed=false,input:HTMLInputElement|undefined
 const close=()=>{root?.unmount();root=undefined;host?.remove();host=undefined;input?.remove();input=undefined}
 return {
  open(mode:'insert-equation'|'insert-icons'|'insert-picture',commit:(picture:PictureInput)=>Promise<void>,error:(error:unknown)=>void){
   if(disposed)return;close()
   if(mode==='insert-picture'){
    input=document.createElement('input');input.type='file';input.dataset.workbookPicture='true';input.accept='image/png,image/jpeg';input.hidden=true;document.body.append(input)
    const picker=input;picker.addEventListener('cancel',close)
    picker.addEventListener('change',async()=>{const file=picker.files?.[0];if(!file)return;try{if(file.size>6*1024*1024)throw new Error('图片须在6 MiB以内');const bytes=new Uint8Array(await file.arrayBuffer()),info=noteImageInfo(bytes);if(info.mediaType==='image/gif')throw new Error('普通图片仅支持PNG/JPEG');let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);const scale=Math.min(1,480/info.width,320/info.height);await commit({dataUrl:`data:${info.mediaType};base64,${btoa(binary)}`,width:info.width*scale,height:info.height*scale,name:file.name});close()}catch(e){error(e);close()}})
    input.click();return
   }
   host=document.createElement('div');document.body.append(host);root=createRoot(host)
   if(mode==='insert-equation')root.render(<EquationDialog onClose={close} onInsert={(dataUrl,width,height)=>commit({dataUrl,width,height,name:'Equation.png'})}/>)
   else root.render(<IconsDialog onClose={close} onInsert={(dataUrl,size,name)=>commit({dataUrl,width:size,height:size,name:`${name}.png`})}/>)
  },
  dispose(){disposed=true;close()},
 }
}
/** 使用 Univer 原生 drawing 导入，并保留文件目标与原生导入快照的独立绑定。 */
export async function installWorkbookPictures(api:any,pictures:readonly WorkbookPicture[]){
 const bindings=new Map<string,{picture:WorkbookPicture;drawing:Record<string,unknown>}>()
 const book=api.getActiveWorkbook();if(!book)return bindings
 for(const [index,picture] of pictures.entries()){
  const sheet=book.getSheets().find((sheet:any)=>sheet.getSheetName()===picture.sheetName);if(!sheet)continue
  let binary='';for(const byte of picture.bytes)binary+=String.fromCharCode(byte)
  const image=await sheet.newOverGridImage().setImage({drawingId:`xlsx-picture-${index}`,drawingType:api.Enum.DrawingType.DRAWING_IMAGE,imageSourceType:api.Enum.ImageSourceType.BASE64,source:`data:${picture.mediaType};base64,${btoa(binary)}`,unitId:book.getId(),subUnitId:sheet.getSheetId()}).setColumn(picture.column).setRow(picture.row).setColumnOffset(picture.columnOffsetPx).setRowOffset(picture.rowOffsetPx).setWidth(picture.widthPx).setHeight(picture.heightPx).buildAsync()
  if(api.getActiveWorkbook()?.getWorkbook()!==book.getWorkbook())throw new Error('图片载入期间工作簿已变化')
  if(!sheet.insertImages([image]))throw new Error('图片未能加载到工作表')
  bindings.set(image.drawingId,{picture,drawing:structuredClone(image)})
 }
 return bindings
}
