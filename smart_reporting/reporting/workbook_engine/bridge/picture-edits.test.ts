import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook} from '../packages/xlsx-engine/src/index'
import {applyWorkbookOperations} from './operations'
import {pictureSourceIdentity,readWorkbookPictures} from '../packages/xlsx-engine/src/pictures'
import {sha256Hex} from '../packages/xlsx-engine/src/sha256'
const base64='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'
const png=Uint8Array.from(Buffer.from(base64,'base64')),drawing='xl/drawings/drawing1.xml'
const geometry=(p:any)=>({row:p.row,column:p.column,rowOffsetPx:p.rowOffsetPx,columnOffsetPx:p.columnOffsetPx,widthPx:p.widthPx,heightPx:p.heightPx})
async function fixture(){const bytes=await createBlankWorkbook('Report');return applyWorkbookOperations(bytes,[{kind:'insertPicture',sheetName:'Report',sourceIdentity:await pictureSourceIdentity(bytes),imageId:'picture-1',row:2,column:3,widthPx:128,heightPx:80,picture:{mediaType:'image/png',bytesBase64:base64,size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'a.png'}}])}
async function operation(bytes:Uint8Array,next:any,pictureIndex=0){const p:any=(await readWorkbookPictures(bytes)).pictures[pictureIndex];return {kind:'editPicture',sheetName:p.sheetName,sourceIdentity:await pictureSourceIdentity(bytes),drawingPart:p.drawingPart,pictureId:p.pictureId,mediaSha256:p.sha256,before:geometry(p),geometry:next}}
async function unchangedParts(before:Uint8Array,after:Uint8Array){const a=await JSZip.loadAsync(before),b=await JSZip.loadAsync(after);expect(Object.keys(b.files).sort()).toEqual(Object.keys(a.files).sort());for(const path of Object.keys(a.files).filter(p=>!a.files[p]!.dir&&p!==drawing))expect(sha256Hex(await b.file(path)!.async('uint8array')),path).toBe(sha256Hex(await a.file(path)!.async('uint8array')))}
it('persists move and resize to the exact picture and deletes only its anchor',async()=>{
 const bytes=await fixture(),next={row:5,column:6,rowOffsetPx:2,columnOffsetPx:3,widthPx:100,heightPx:60}
 const op=await operation(bytes,next);expect(op.pictureId).toMatch(/^\d+$/);expect(op.drawingPart).toBe(drawing)
 const moved=await applyWorkbookOperations(bytes,[op]),result=await readWorkbookPictures(moved)
 expect(result.issues).toEqual([]);expect(geometry(result.pictures[0])).toEqual(next);await unchangedParts(bytes,moved)
 const deleted=await applyWorkbookOperations(moved,[await operation(moved,null)])
 expect((await readWorkbookPictures(deleted)).pictures).toEqual([]);await unchangedParts(moved,deleted)
})
it('rejects stale source, geometry, media and malformed picture identities',async()=>{
 const bytes=await fixture(),op=await operation(bytes,null)
 for(const change of [{sourceIdentity:'0'.repeat(64)},{before:{...op.before,row:3}},{mediaSha256:'0'.repeat(64)},{pictureId:'01'},{pictureId:1},{drawingPart:'xl/drawings/other.xml'}])await expect(applyWorkbookOperations(bytes,[{...op,...change}])).rejects.toThrow()
})
it('preserves arbitrary prefixes and neutral picture transforms when editing one-cell anchors',async()=>{
 const zip=await JSZip.loadAsync(await fixture()),xml=await zip.file(drawing)!.async('text')
 zip.file(drawing,xml.replaceAll('xdr:','q:').replaceAll('xmlns:xdr=','xmlns:q=').replace(/<q:twoCellAnchor[^>]*>/,'<q:oneCellAnchor>').replace('</q:twoCellAnchor>','</q:oneCellAnchor>').replace(/<q:to>[\s\S]*?<\/q:to>/,'<q:ext cx="1219200" cy="762000"/>').replace('<q:spPr>','<q:spPr><a:xfrm rot="0" flipH="0" xmlns:k="urn:kept" k:token="keep"><a:off x="0" y="0"/><a:ext cx="1219200" cy="762000"/></a:xfrm>'))
 const bytes=await zip.generateAsync({type:'uint8array'}),next={row:1,column:2,rowOffsetPx:1,columnOffsetPx:2,widthPx:96,heightPx:48}
 const saved=await applyWorkbookOperations(bytes,[await operation(bytes,next)]),after=await JSZip.loadAsync(saved),out=await after.file(drawing)!.async('text')
 expect(geometry((await readWorkbookPictures(saved)).pictures[0])).toEqual(next)
 expect(out).toContain('rot="0" flipH="0" xmlns:k="urn:kept" k:token="keep"');expect(out).toContain('<a:off x="1238250" y="200025"/>');expect(out).toContain('cx="914400" cy="457200"');expect(out).toContain('<q:oneCellAnchor>');await unchangedParts(bytes,saved)
})
it('keeps charts, unknown sibling anchors, crop and shared image bytes intact',async()=>{
 const {applyChartAdditions}=await import('../packages/xlsx-engine/src/chart-add')
 const original=await applyChartAdditions(await fixture(),[{worksheetSheetName:'Report',anchor:{fromRow:1,fromColumn:3,toRow:15,toColumn:11,fromRowOffset:0,fromColumnOffset:0,toRowOffset:0,toColumnOffset:0},chart:{chartType:'column',title:'Keep original',series:[{name:'Amount',categories:['Q1','Q2'],values:[10,20],valuesRef:'Report!$B$2:$B$3'}]}}])
 const zip=await JSZip.loadAsync(original);let xml=await zip.file(drawing)!.async('text')
 const anchor=xml.match(/<xdr:twoCellAnchor[^>]*>[\s\S]*?<\/xdr:twoCellAnchor>/)![0]
 expect(anchor).toContain('<xdr:pic>')
 const sibling=anchor.replace(/(<xdr:cNvPr id=")[^"]+/, '$1999').replace('name="picture-1"','name="picture-2"')
 const unknown='<u:opaqueAnchor xmlns:u="urn:kept"><u:object token="unchanged"/></u:opaqueAnchor>'
 xml=xml.replace('</xdr:wsDr>',sibling+unknown+'</xdr:wsDr>').replaceAll('<a:stretch>','<a:srcRect l="1000" t="2000"/><a:stretch>')
 zip.file(drawing,xml);const bytes=await zip.generateAsync({type:'uint8array'}),op=await operation(bytes,null)
 const deleted=await applyWorkbookOperations(bytes,[op]),after=await JSZip.loadAsync(deleted),out=await after.file(drawing)!.async('text')
 expect((await readWorkbookPictures(deleted)).pictures.map(p=>p.imageId)).toEqual(['picture-2'])
 expect(out).toContain(unknown);expect(out).toContain('<c:chart');expect(out).toContain('<a:srcRect l="1000" t="2000"/>');await unchangedParts(bytes,deleted)
})
it('rejects protected, shared, ambiguous and multi-object targets',async()=>{
 const original=await fixture()
 for(const mode of ['protected','shared','duplicate','multi-object','external','absolute','duplicate-marker']){
  const zip=await JSZip.loadAsync(original),xml=await zip.file(drawing)!.async('text')
  if(mode==='protected'){const p='xl/worksheets/sheet1.xml';zip.file(p,(await zip.file(p)!.async('text')).replace('</worksheet>','<sheetProtection sheet="1"/></worksheet>'))}
  if(mode==='shared'){const p='xl/worksheets/_rels/sheet1.xml.rels';zip.file(p,(await zip.file(p)!.async('text')).replace('</Relationships>','<Relationship Id="rIdShared" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>'))}
  if(mode==='duplicate')zip.file(drawing,xml.replace('</xdr:wsDr>',xml.match(/<xdr:twoCellAnchor[^>]*>[\s\S]*?<\/xdr:twoCellAnchor>/)![0]+'</xdr:wsDr>'))
  if(mode==='multi-object')zip.file(drawing,xml.replace('<xdr:clientData/>','<xdr:sp/><xdr:clientData/>'))
  if(mode==='duplicate-marker')zip.file(drawing,xml.replace('<xdr:row>2</xdr:row>','<xdr:row>2</xdr:row><xdr:row>2</xdr:row>'))
  if(mode==='absolute')zip.file(drawing,xml.replaceAll('twoCellAnchor','absoluteAnchor'))
  if(mode==='external'){const p='xl/drawings/_rels/drawing1.xml.rels';zip.file(p,(await zip.file(p)!.async('text')).replace('Target="../media/image1.png"','Target="https://invalid.example/x.png" TargetMode="External"'))}
  const bytes=await zip.generateAsync({type:'uint8array'}),op={...await operation(original,null),sourceIdentity:await pictureSourceIdentity(bytes)}
  await expect(applyWorkbookOperations(bytes,[op]),mode).rejects.toThrow()
 }
})
it('rejects invalid geometry and workbook edges without changing the package',async()=>{
 const bytes=await fixture(),base={row:2,column:3,rowOffsetPx:0,columnOffsetPx:0,widthPx:128,heightPx:80},op=await operation(bytes,base)
 for(const geometry of [{...base,row:-1},{...base,column:1.2},{...base,widthPx:0},{...base,heightPx:Infinity},{...base,rowOffsetPx:20},{...base,column:16383,widthPx:100},{...base,row:1048575,heightPx:100}])await expect(applyWorkbookOperations(bytes,[{...op,geometry}])).rejects.toThrow()
})

it('reopens saved geometry with independent openpyxl rather than the engine reader',async()=>{
 const bytes=await fixture(),next={row:5,column:6,rowOffsetPx:2,columnOffsetPx:3,widthPx:100,heightPx:60},saved=await applyWorkbookOperations(bytes,[await operation(bytes,next)])
 const python=fileURLToPath(new URL('../../../../.venv/bin/python',import.meta.url))
 const result=execFileSync(python,['-c',`import sys,io,json,base64,openpyxl
w=openpyxl.load_workbook(io.BytesIO(base64.b64decode(sys.stdin.read())))
a=w['Report']._images[0].anchor
print(json.dumps({'row':a._from.row,'column':a._from.col,'rowOff':a._from.rowOff,'colOff':a._from.colOff,'toRow':a.to.row,'toCol':a.to.col,'toRowOff':a.to.rowOff,'toColOff':a.to.colOff}))`],{input:Buffer.from(saved).toString('base64'),encoding:'utf8'})
 expect(JSON.parse(result)).toEqual({row:5,column:6,rowOff:19050,colOff:28575,toRow:8,toCol:7,toRowOff:19050,toColOff:371475})
})

it('replays insert then two picture edits with each current package identity in one batch',async()=>{
 const bytes=await fixture(),insert={kind:'insertPicture',sheetName:'Report',sourceIdentity:await pictureSourceIdentity(bytes),imageId:'picture-2',row:7,column:2,widthPx:128,heightPx:80,picture:{mediaType:'image/png',bytesBase64:base64,size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'b.png'}}
 const inserted=await applyWorkbookOperations(bytes,[insert]),firstGeometry={row:1,column:2,rowOffsetPx:0,columnOffsetPx:0,widthPx:96,heightPx:48},secondGeometry={row:9,column:4,rowOffsetPx:1,columnOffsetPx:2,widthPx:80,heightPx:40}
 const first=await operation(inserted,firstGeometry),firstSaved=await applyWorkbookOperations(inserted,[first]),second=await operation(firstSaved,secondGeometry,1)
 const saved=await applyWorkbookOperations(bytes,[insert,first,second]),result=await readWorkbookPictures(saved)
 expect(result.issues).toEqual([]);expect(result.pictures.map(geometry)).toEqual([firstGeometry,secondGeometry])
 expect(first.sourceIdentity).not.toBe(second.sourceIdentity)
})
it.each(['../drawings/%64rawing1.xml','../drawings/drawing1.xml#fragment'])('rejects URI-equivalent shared drawing target %s',async target=>{
 const original=await fixture(),zip=await JSZip.loadAsync(original),path='xl/worksheets/_rels/sheet1.xml.rels'
 zip.file(path,(await zip.file(path)!.async('text')).replace('</Relationships>',`<Relationship Id="rIdEncodedShared" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="${target}"/></Relationships>`))
 const bytes=await zip.generateAsync({type:'uint8array'}),op=await operation(bytes,null)
 await expect(applyWorkbookOperations(bytes,[op])).rejects.toThrow(/共享/)
})

it.each([['rot="60000"','旋转'],['flipH="1"','翻转'],['flipV="true"','翻转'],['crop','裁剪']])('refuses unprojected %s geometry while allowing exact deletion',async(attribute,reason)=>{
 const zip=await JSZip.loadAsync(await fixture()),xml=await zip.file(drawing)!.async('text')
 zip.file(drawing,attribute==='crop'?xml.replace('<a:stretch>','<a:srcRect l="1000"/><a:stretch>'):xml.replace('<xdr:spPr>',`<xdr:spPr><a:xfrm ${attribute}><a:off x="0" y="0"/><a:ext cx="1219200" cy="762000"/></a:xfrm>`))
 const bytes=await zip.generateAsync({type:'uint8array'}),read=await readWorkbookPictures(bytes),p:any=read.pictures[0]
 expect(p.geometryReadOnlyReason).toContain(reason)
 const op=await operation(bytes,{...geometry(p),row:5})
 await expect(applyWorkbookOperations(bytes,[op])).rejects.toThrow(reason)
 const deleted=await applyWorkbookOperations(bytes,[{...op,geometry:null}])
 expect((await readWorkbookPictures(deleted)).pictures).toEqual([]);await unchangedParts(bytes,deleted)
})
it('reads source default metrics instead of SDK implicit dimensions',async()=>{
 const {readWorkbook}=await import('../packages/xlsx-engine/src/workbook-read'),model=await readWorkbook(await fixture())
 expect(model.sheets[0]).toMatchObject({defaultColumnWidthPx:64,defaultRowHeightPx:20})
})
it('shares rounded source defaults and fractional explicit dimensions with picture anchors',async()=>{
 const {readWorkbook}=await import('../packages/xlsx-engine/src/workbook-read'),zip=await JSZip.loadAsync(await fixture()),part='xl/worksheets/sheet1.xml'
 zip.file(part,(await zip.file(part)!.async('text')).replace(/<sheetFormatPr\b[^>]*\/>/g,'').replace('<sheetData/>','<sheetFormatPr defaultColWidth="10.2" defaultRowHeight="15.4"/><cols><col min="4" max="4" width="10.1"/></cols><sheetData><row r="3" ht="15.5" customHeight="1"/></sheetData>'))
 const bytes=await zip.generateAsync({type:'uint8array'}),model=await readWorkbook(bytes),p=(await readWorkbookPictures(bytes)).pictures[0]!
 expect(model.sheets[0]).toMatchObject({defaultColumnWidthPx:76,defaultRowHeightPx:21})
 expect([p.widthPx,p.heightPx]).toEqual([152,84])
 const next={row:2,column:3,rowOffsetPx:20,columnOffsetPx:75,widthPx:100,heightPx:60},saved=await applyWorkbookOperations(bytes,[await operation(bytes,next)])
 expect(geometry((await readWorkbookPictures(saved)).pictures[0])).toEqual(next)
})
