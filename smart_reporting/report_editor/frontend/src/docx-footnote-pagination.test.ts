import { beforeAll, expect, it } from 'vitest'
import { execFileSync } from 'node:child_process'
import { Schema } from '@tiptap/pm/model'
import { currentFootnotes, currentDocxNotes, footnotePagination, endnotePagination } from './docx-footnote-pagination'
import { parseDocxOffThread } from './vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread'
import { readSections, readSectionSettings } from '@genoffice/docx-engine'
import type { DocxNotesModel } from './docx-notes'
const schema = new Schema({ nodes: { doc: {content:'block+',attrs:{nativeNotesOperations:{default:null}}}, paragraph:{group:'block',content:'inline*',attrs:{docxIndex:{default:0}}}, table:{group:'block',content:'paragraph+',attrs:{docxIndex:{default:0}}}, text:{group:'inline'}, docNoteRef:{inline:true,group:'inline',atom:true,attrs:{id:{default:'1'},kind:{default:'footnote'},num:{default:1}}} } })
let bytes: Uint8Array, parsed: Awaited<ReturnType<typeof parseDocxOffThread>>, model: DocxNotesModel
beforeAll(async () => {
  const raw = execFileSync('../../../.venv/bin/python',['-c',`
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
import sys
b=BytesIO(); d=Document(); d.add_paragraph('Body text'); d.save(b); raw=b.getvalue(); a=inspect_docx(raw)['blocks'][0]
raw=patch_docx(raw,[{'kind':'insertNote','noteKind':kind,'blockId':a['blockId'],'expectedObjectSha256':a['expectedObjectSha256'],'offset':4,'text':'Bold note'} for kind in ('footnote','endnote')]); out=BytesIO()
with ZipFile(BytesIO(raw)) as z, ZipFile(out,'w',ZIP_DEFLATED) as target:
 for f in z.infolist():
  data=z.read(f.filename)
  if f.filename in ('word/footnotes.xml','word/endnotes.xml'):
   root=etree.fromstring(data)
   for run in root.iter(qn('w:r')):
    if run.find(qn('w:t')) is not None:
     p=etree.Element(qn('w:rPr')); p.append(etree.Element(qn('w:b'))); run.insert(0,p)
   data=etree.tostring(root)
  target.writestr(f,data)
sys.stdout.buffer.write(out.getvalue())
`],{env:{...process.env,PYTHONPATH:'../../..'},maxBuffer:2e6})
  bytes=new Uint8Array(raw); parsed=await parseDocxOffThread(bytes)
  model={footnotes:[{id:'1',text:'Bold note',expectedNoteSha256:'sha',editable:true,references:[]}],endnotes:[{id:'1',text:'Bold note',expectedNoteSha256:'end-sha',editable:true,references:[]}]}
},30000)
const doc = (operations: unknown[] = [], table=false) => schema.nodeFromJSON({type:'doc',attrs:{nativeNotesOperations:operations},content:[{type:table?'table':'paragraph',attrs:{docxIndex:0},content:table?[{type:'paragraph',content:[{type:'docNoteRef',attrs:{id:'1',num:7}}]}]:[{type:'docNoteRef',attrs:{id:'1',num:7}}]}]})
it('uses original rich NoteInfo without loading source bytes when no note changes',async()=>{
 const notes=await currentFootnotes({bytes:new Uint8Array(),parsed,doc:doc(),model},()=>true)
 expect(notes).toBe(parsed.footnotes); expect(notes[0].richParas?.flat().some(r=>r.bold)).toBe(true)
})
it('projects actual same-paragraph save XML retaining rich runs, and deletion removes entry',async()=>{
 const update={kind:'updateNote',noteKind:'footnote',noteId:'1',expectedNoteSha256:'sha',text:'Bold changed note'}
 const notes=await currentFootnotes({bytes,parsed,doc:doc([update]),model},()=>true)
 expect(notes[0].text).toBe(update.text); expect(notes[0].richParas?.flat().some(r=>r.bold)).toBe(true)
 expect(notes[0].richParas?.flat().map(r=>r.text).join('')).toBe(update.text)
 const deleted=await currentFootnotes({bytes,parsed,doc:doc([{kind:'deleteNote',noteKind:'footnote',noteId:'1',expectedNoteSha256:'sha',expectedReferences:[]}]),model},()=>true)
 expect(deleted).toEqual([])
})
it('projects inserted notes and refuses a stale request after an awaited ZIP read',async()=>{
 const inserted=await currentFootnotes({bytes,parsed,doc:doc([{kind:'insertNote',noteKind:'footnote',blockId:'b',expectedObjectSha256:'s',offset:0,text:'New note'}]),model},()=>true)
 expect(inserted.map(n=>[n.id,n.text])).toEqual([['1','Bold note'],['2','New note']])
 let checks=0
 await expect(currentFootnotes({bytes,parsed,doc:doc([{kind:'updateNote',noteKind:'footnote',noteId:'1',expectedNoteSha256:'sha',text:'new'}]),model},()=>++checks<2)).rejects.toThrow('发生变化')
})
it('uses live table references and mark numbers; assigns split references by measured band position',()=>{
 const collector=footnotePagination({parsed,notes:parsed.footnotes,doc:doc([],true),sections:readSections(parsed),section:readSectionSettings(parsed)})
 const meta=collector.blockMetaOf(0)!
 expect(meta.footnoteExtraPx).toBeGreaterThan(0)
 const pages=collector.pageFootnotesOf([{docxIndex:0,top:0,height:60,noteBands:[{offset:55,height:meta.footnoteExtraPx!}]}],[{start:0,end:50,section:0},{start:50,end:100,section:0}])
 expect(pages[0]).toEqual([]); expect(pages[1][0]).toMatchObject({id:'1',no:7,text:'Bold note'})
 expect(pages[1][0].richParas?.flat().some(r=>r.bold)).toBe(true)
 const without=schema.nodeFromJSON({type:'doc',content:[{type:'paragraph',attrs:{docxIndex:0},content:[{type:'text',text:'no ref'}]}]})
 expect(footnotePagination({parsed,notes:parsed.footnotes,doc:without,sections:readSections(parsed),section:readSectionSettings(parsed)}).blockMetaOf(0)).toBeUndefined()
})
it('falls back for missing or invalid live numbers while preserving a finite zero',()=>{
 const withNumbers={...parsed,noteNumbers:{...parsed.noteNumbers,'footnote:1':9}}
 for (const [num,expected] of [[undefined,9],[null,9],[NaN,9],[Infinity,9],['7',9],[0,0],[7,7]] as const) {
  const current=doc(); Object.assign(current.firstChild!.firstChild!.attrs, { num })
  const collector=footnotePagination({parsed:withNumbers,notes:parsed.footnotes,doc:current,sections:readSections(parsed),section:readSectionSettings(parsed)})
  const pages=collector.pageFootnotesOf([{docxIndex:0,top:0,height:20}],[{start:0,end:20,section:0}])
  expect(pages[0][0].no).toBe(expected)
 }
})
it('projects endnote save XML with rich runs for update, insert, delete and stale async reads',async()=>{
 expect(await currentDocxNotes('endnote',{bytes:new Uint8Array(),parsed,doc:doc(),model},()=>true)).toBe(parsed.endnotes)
 const update={kind:'updateNote',noteKind:'endnote',noteId:'1',expectedNoteSha256:'end-sha',text:'Bold changed endnote'}
 const notes=await currentDocxNotes('endnote',{bytes,parsed,doc:doc([update]),model},()=>true)
 expect(notes[0].richParas?.flat().some(r=>r.bold)).toBe(true)
 expect(notes[0].richParas?.flat().map(r=>r.text).join('')).toBe(update.text)
 const inserted=await currentDocxNotes('endnote',{bytes,parsed,doc:doc([{kind:'insertNote',noteKind:'endnote',blockId:'b',expectedObjectSha256:'s',offset:0,text:'New endnote'}]),model},()=>true)
 expect(inserted.map(n=>[n.id,n.text])).toEqual([['1','Bold note'],['2','New endnote']])
 expect(await currentDocxNotes('endnote',{bytes,parsed,doc:doc([{kind:'deleteNote',noteKind:'endnote',noteId:'1',expectedNoteSha256:'end-sha',expectedReferences:[]}]),model},()=>true)).toEqual([])
 let checks=0
 await expect(currentDocxNotes('endnote',{bytes,parsed,doc:doc([update]),model},()=>++checks<2)).rejects.toThrow('发生变化')
})
it('measures endnotes at the last section width with live numbering and source rich runs',()=>{
 const json=doc().toJSON(); json.content[0].content[0].attrs.kind='endnote'
 const current=schema.nodeFromJSON(json), section=readSectionSettings(parsed)
 const narrow={...section,pageWidth:4000,marginLeft:400,marginRight:400}
 const long={...parsed.endnotes[0],text:'Long endnote text '.repeat(60),richParas:undefined}
 const sections=readSections(parsed)
 const wideItems=endnotePagination({parsed,notes:[long],doc:current,sections,section:narrow})
 const items=endnotePagination({parsed,notes:[long],doc:current,sections:[...sections,{...sections[0],settings:narrow}],section})
 expect(items[0].no).toBe(7); expect(items[0].height).toBeGreaterThan(wideItems[0].height)
 expect(endnotePagination({parsed,notes:parsed.endnotes,doc:current,sections,section})[0].richParas?.flat().some(r=>r.bold)).toBe(true)
})
