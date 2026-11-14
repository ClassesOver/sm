import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook,applySheetNotes} from '../packages/xlsx-engine/src/index'
import {readNotePictures,applyNotePictureOperation} from '../packages/xlsx-engine/src/note-pictures'
import {sha256Hex} from '../packages/xlsx-engine/src/sha256'
const PNG=Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=','base64'))
export async function picturedFixture(shared=false){
 const zip=await JSZip.loadAsync(await applySheetNotes(await createBlankWorkbook('Report'),'Report',[{row:0,column:0,author:'作者甲',text:'保留批注文字'},{row:1,column:1,author:'作者乙',text:'另一图片'}]))
 const vml='xl/drawings/vmlDrawing1.vml',xml=await zip.file(vml)!.async('text')
 let n=0;zip.file(vml,xml.replace(/<v:fill\b[^>]*\/>/g,()=>'<v:fill type="frame" o:relid="pic'+(++n)+'"/>'))
 zip.file('xl/drawings/_rels/vmlDrawing1.vml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="pic1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/note1.png"/><Relationship Id="pic2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/'+(shared?'note1.png':'note2.png')+'"/></Relationships>')
 zip.file('xl/media/note1.png',PNG);if(!shared)zip.file('xl/media/note2.png',PNG)
 zip.file('customXml/keep.bin',new Uint8Array([1,2,3,255]))
 return zip.generateAsync({type:'uint8array'})
}
it('reads actual VML picture bytes identity author and text in cell order',async()=>{
 const result=await readNotePictures(await picturedFixture())
 expect(result.pictures.map(p=>[p.sheetName,p.row,p.column,p.author,p.text,p.mediaType,p.sha256])).toEqual([['Report',0,0,'作者甲','保留批注文字','image/png',sha256Hex(PNG)],['Report',1,1,'作者乙','另一图片','image/png',sha256Hex(PNG)]])
 expect(result.pictures[0]!.bytes).toEqual(PNG);expect(result.issues).toEqual([])
})
it('removes only selected fill owned relationship and unshared media preserving comments and other picture',async()=>{
 const bytes=await picturedFixture(),picture=(await readNotePictures(bytes)).pictures[0]!,before=await JSZip.loadAsync(bytes)
 const after=await JSZip.loadAsync(await applyNotePictureOperation(bytes,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:picture.sourceIdentity,picture:null}))
 expect(await after.file('xl/comments1.xml')!.async('text')).toEqual(await before.file('xl/comments1.xml')!.async('text'))
 expect(after.file('xl/media/note1.png')).toBeNull();expect(after.file('xl/media/note2.png')).not.toBeNull()
 expect(await after.file('xl/drawings/vmlDrawing1.vml')!.async('text')).not.toContain('o:relid="pic1"')
 expect(await after.file('customXml/keep.bin')!.async('uint8array')).toEqual(new Uint8Array([1,2,3,255]))
})
it('keeps media referenced by another note and rejects stale picture source identity',async()=>{
 const bytes=await picturedFixture(true),picture=(await readNotePictures(bytes)).pictures[0]!
 const after=await JSZip.loadAsync(await applyNotePictureOperation(bytes,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:picture.sourceIdentity,picture:null}))
 expect(after.file('xl/media/note1.png')).not.toBeNull()
 await expect(applyNotePictureOperation(bytes,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:'0'.repeat(64),picture:null})).rejects.toThrow(/身份|变化/)
})
it('inserts actual PNG into a new empty note without changing existing pictured notes',async()=>{
 const bytes=await picturedFixture(),before=await readNotePictures(bytes),sheet=before.sheets[0]!
 const operation={kind:'setNotePicture',sheetName:'Report',row:3,column:3,sourceIdentity:sheet.sourceIdentity,picture:{mediaType:'image/png',bytesBase64:Buffer.from(PNG).toString('base64'),size:PNG.length,sha256:sha256Hex(PNG),widthPx:1,heightPx:1,name:'照片.png'}}
 const result=await applyNotePictureOperation(bytes,operation),after=await readNotePictures(result)
 expect(after.pictures.map(p=>[p.row,p.column,p.sha256,p.text])).toEqual([[0,0,sha256Hex(PNG),'保留批注文字'],[1,1,sha256Hex(PNG),'另一图片'],[3,3,sha256Hex(PNG),'']])
 await expect(applyNotePictureOperation(bytes,{...operation,picture:{...operation.picture,mediaType:'image/jpeg'}})).rejects.toThrow(/MIME|身份/)
})
it('refuses foreign namespace protected or external picture input without reading URL',async()=>{
 const bytes=await picturedFixture(),base=await readNotePictures(bytes)
 const foreign=await JSZip.loadAsync(bytes);foreign.file('xl/drawings/vmlDrawing1.vml',(await foreign.file('xl/drawings/vmlDrawing1.vml')!.async('text')).replace('urn:schemas-microsoft-com:vml','urn:forged'))
 expect((await readNotePictures(await foreign.generateAsync({type:'uint8array'}))).issues[0]?.message).toMatch(/命名空间/)
 const external=await JSZip.loadAsync(bytes);external.file('xl/drawings/_rels/vmlDrawing1.vml.rels',(await external.file('xl/drawings/_rels/vmlDrawing1.vml.rels')!.async('text')).replace('Target="../media/note1.png"','Target="https://must-not-fetch.invalid/image.png" TargetMode="External"'))
 const record=(await readNotePictures(await external.generateAsync({type:'uint8array'}))).pictures[0]!
 expect(record.bytes).toBeNull();expect(record.unavailable).toMatch(/外部/)
 const protectedZip=await JSZip.loadAsync(bytes);protectedZip.file('xl/worksheets/sheet1.xml',(await protectedZip.file('xl/worksheets/sheet1.xml')!.async('text')).replace('</worksheet>','<sheetProtection sheet="1"/></worksheet>'))
 await expect(applyNotePictureOperation(await protectedZip.generateAsync({type:'uint8array'}),{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:base.sheets[0]!.sourceIdentity,picture:null})).rejects.toThrow(/保护/)
})
it('keeps a target media when a separate drawing relationship also owns it',async()=>{
 const bytes=await picturedFixture(),zip=await JSZip.loadAsync(bytes)
 zip.file('xl/drawings/_rels/unrelated.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="also" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/note1.png"/></Relationships>')
 const shared=await zip.generateAsync({type:'uint8array'}),picture=(await readNotePictures(shared)).pictures[0]!
 const result=await JSZip.loadAsync(await applyNotePictureOperation(shared,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:picture.sourceIdentity,picture:null}))
 expect(result.file('xl/media/note1.png')).not.toBeNull()
})
it('accepts actual JPEG GIF bytes and refuses truncated PNG masquerading as an image',async()=>{
 const {noteImageInfo}=await import('../packages/xlsx-engine/src/note-pictures')
 expect(()=>noteImageInfo(PNG.slice(0,24))).toThrow(/结构|完整|PNG/)
 const gif=Uint8Array.from(Buffer.from('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==','base64'))
 expect(noteImageInfo(gif)).toEqual({mediaType:'image/gif',width:1,height:1})
})
