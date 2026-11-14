import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook,applySheetNotes} from '../packages/xlsx-engine/src/index'
import {applyWorkbookOperations} from './operations'
import {pictureSourceIdentity,readWorkbookPictures} from '../packages/xlsx-engine/src/pictures'
import {sha256Hex} from '../packages/xlsx-engine/src/sha256'
const base64='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'
const png=Uint8Array.from(Buffer.from(base64,'base64'))
it('inserts real drawing pictures, preserves notes and unrelated parts, then reopens both images',async()=>{
 const bytes=await applySheetNotes(await createBlankWorkbook('Report'),'Report',[{row:0,column:0,author:'作者',text:'保留'}])
 const before=await JSZip.loadAsync(bytes)
 const operation={kind:'insertPicture',sheetName:'Report',sourceIdentity:await pictureSourceIdentity(bytes),imageId:'picture-1',row:2,column:3,widthPx:128,heightPx:80,picture:{mediaType:'image/png',bytesBase64:base64,size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'公式.png'}}
 const first=await applyWorkbookOperations(bytes,[operation])
 const second=await applyWorkbookOperations(first,[{...operation,sourceIdentity:await pictureSourceIdentity(first),imageId:'picture-2',row:5}])
 const zip=await JSZip.loadAsync(second),pictures=await readWorkbookPictures(second)
 expect(pictures.pictures.map(p=>[p.imageId,p.row,p.column,p.widthPx,p.heightPx,p.sha256])).toEqual([['picture-1',2,3,128,80,sha256Hex(png)],['picture-2',5,3,128,80,sha256Hex(png)]])
 expect(pictures.issues).toEqual([])
 expect(await zip.file('xl/comments1.xml')!.async('text')).toEqual(await before.file('xl/comments1.xml')!.async('text'))
 expect(await zip.file('xl/drawings/vmlDrawing1.vml')!.async('text')).toEqual(await before.file('xl/drawings/vmlDrawing1.vml')!.async('text'))
 expect(await zip.file('xl/drawings/drawing1.xml')!.async('text')).toContain('<xdr:pic>')
 await expect(applyWorkbookOperations(first,[operation])).rejects.toThrow(/身份/)
 await expect(applyWorkbookOperations(bytes,[{...operation,picture:{...operation.picture,sha256:'0'.repeat(64)}}])).rejects.toThrow(/身份/)
 await expect(applyWorkbookOperations(bytes,[{...operation,picture:{...operation.picture,mediaType:'image/jpeg'}}])).rejects.toThrow(/身份/)
})
it('reads arbitrary namespace prefixes and refuses external or forged drawing identities',async()=>{
 const bytes=await createBlankWorkbook('Report'),operation={kind:'insertPicture',sheetName:'Report',sourceIdentity:await pictureSourceIdentity(bytes),imageId:'picture-1',row:0,column:0,widthPx:128,heightPx:80,picture:{mediaType:'image/png',bytesBase64:base64,size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'a.png'}}
 const saved=await applyWorkbookOperations(bytes,[operation]),zip=await JSZip.loadAsync(saved),drawing='xl/drawings/drawing1.xml'
 zip.file(drawing,(await zip.file(drawing)!.async('text')).replaceAll('xdr:','p:').replaceAll('xmlns:xdr=','xmlns:p='))
 const renamed=await zip.generateAsync({type:'uint8array'})
 expect((await readWorkbookPictures(renamed)).pictures).toHaveLength(1)
 zip.file('xl/drawings/_rels/drawing1.xml.rels',(await zip.file('xl/drawings/_rels/drawing1.xml.rels')!.async('text')).replace('Target="../media/image1.png"','Target="https://invalid.example/x.png" TargetMode="External"'))
 const external=await readWorkbookPictures(await zip.generateAsync({type:'uint8array'}))
 expect(external.pictures).toHaveLength(0);expect(external.issues.join()).toMatch(/外部|关系/)
 zip.file(drawing,(await zip.file(drawing)!.async('text')).replace('http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing','urn:foreign'))
 expect((await readWorkbookPictures(await zip.generateAsync({type:'uint8array'}))).issues.join()).toMatch(/命名空间/)
})

it('refuses fractional, negative and out-of-range source anchors before native drawing import',async()=>{
 const bytes=await createBlankWorkbook('Report'),operation={kind:'insertPicture',sheetName:'Report',sourceIdentity:await pictureSourceIdentity(bytes),imageId:'picture-1',row:0,column:0,widthPx:128,heightPx:80,picture:{mediaType:'image/png',bytesBase64:base64,size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'a.png'}}
 const saved=await applyWorkbookOperations(bytes,[operation]),drawing='xl/drawings/drawing1.xml'
 for(const [field,value] of [['row','1000000000'],['row','0.5'],['row','-1'],['col','16384'],['col','0.5']]){
  const zip=await JSZip.loadAsync(saved),xml=await zip.file(drawing)!.async('text')
  zip.file(drawing,xml.replace(`<xdr:${field}>0</xdr:${field}>`,`<xdr:${field}>${value}</xdr:${field}>`))
  const result=await readWorkbookPictures(await zip.generateAsync({type:'uint8array'}))
  expect(result.pictures).toHaveLength(0);expect(result.issues.join()).toMatch(/锚点/)
 }
})
