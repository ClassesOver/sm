import {expect,it} from 'vitest'
import {controlledWorkbookPicture,installWorkbookPictures} from './workbook-pictures'
import type {WorkbookPicture} from '@sheets-web/xlsx-engine/pictures'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'
it('carries actual image bytes and identity rather than a remote URL or note',()=>{
 const picture=controlledWorkbookPicture({dataUrl:`data:image/png;base64,${png}`,width:128,height:128,name:'photo.png'})
 expect(picture.mediaType).toBe('image/png');expect(picture.widthPx).toBe(1);expect(picture.sha256).toMatch(/^[a-f0-9]{64}$/)
 expect(()=>controlledWorkbookPicture({dataUrl:'https://invalid.example/img.png',width:1,height:1,name:'x.png'})).toThrow(/受控/)
 expect(()=>controlledWorkbookPicture({dataUrl:`data:image/jpeg;base64,${png}`,width:1,height:1,name:'x.jpg'})).toThrow(/身份/)
})
it('binds each native drawing id to its verified source picture and an independent import snapshot',async()=>{
 const core={},image={drawingId:'xlsx-picture-0',unitId:'book',subUnitId:'sheet',transform:{left:12,top:24,width:120,height:80}}
 const builder:Record<string,any>={buildAsync:async()=>image}
 for(const name of ['setImage','setColumn','setRow','setColumnOffset','setRowOffset','setWidth','setHeight'])builder[name]=()=>builder
 const sheet={getSheetName:()=> 'Report',getSheetId:()=> 'sheet',newOverGridImage:()=>builder,insertImages:()=>true}
 const book={getId:()=> 'book',getWorkbook:()=>core,getSheets:()=>[sheet]}
 const api={getActiveWorkbook:()=>book,Enum:{DrawingType:{DRAWING_IMAGE:0},ImageSourceType:{BASE64:0}}}
 const picture={sheetName:'Report',imageId:'source-image',drawingPart:'xl/drawings/drawing1.xml',pictureId:'2',anchorKind:'oneCellAnchor',relationshipId:'rId1',mediaPart:'xl/media/image1.png',row:1,column:2,rowOffsetPx:3,columnOffsetPx:4,widthPx:120,heightPx:80,mediaType:'image/png',sha256:'a'.repeat(64),bytes:new Uint8Array([1])} as WorkbookPicture
 const bindings=await installWorkbookPictures(api,[picture])
 const binding=bindings?.get('xlsx-picture-0')
 expect(binding?.picture).toBe(picture)
 expect(binding?.drawing).toEqual(image)
 image.transform.width=240
 expect(binding?.drawing.transform).toEqual({left:12,top:24,width:120,height:80})
})
