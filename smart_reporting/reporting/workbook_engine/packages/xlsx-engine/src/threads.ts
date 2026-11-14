import {z} from 'zod'
import {readSheetThreads, threadRelationship, THREAD_REL, threadAddress, PERSON_REL} from './thread-read'
import {syncThreadedComments, threadMirrorText, type ThreadedNote} from './thread-write-source'
import {readSheetNotes,noteKey} from './note-read'
import {patchSheetNotes} from './notes'
import {createBufferEntrySource,assemblePackage} from './zip'
import {parseSheetElements,resolveWorksheetPath} from './workbook-read'
import {readXmlAttribute,decodeXmlText} from './xml'
const text = z.string().min(1).max(32767).refine(v => !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v))
const id = z.string().regex(/^\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}$/)
const entry = {id,personId:id,author:z.string().min(1).max(256),dT:z.string().regex(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z?$/),text}
const row = z.number().int().min(0).max(1048575), column = z.number().int().min(0).max(16383)
export const patchThreadedCommentsSchema = z.object({kind:z.literal('patchThreadedComments'),sheetName:z.string().min(1).max(31),sourceIdentity:z.string().regex(/^[a-f0-9]{64}$/),changes:z.array(z.object({row,column,expectedThreadId:id.nullable(),thread:z.object({...entry,row,column,done:z.boolean(),replies:z.array(z.object(entry).strict()).max(999)}).strict().nullable()}).strict()).max(1000)}).strict()
export async function patchThreadedComments(bytes: Uint8Array, input: unknown): Promise<Uint8Array> {
  const op = patchThreadedCommentsSchema.parse(input)
  let source = await createBufferEntrySource(bytes)
  const sheet = parseSheetElements(await source.readText('xl/workbook.xml')).find(s => s.name === op.sheetName)
  if (!sheet?.relationshipId) throw new Error('线程批注工作表不存在')
  const path = await resolveWorksheetPath(source,sheet.relationshipId)
  const state = await readSheetThreads(source,path)
  if (state.readOnlyReason) throw new Error(state.readOnlyReason)
  if (state.sourceIdentity !== op.sourceIdentity) throw new Error('线程批注来源身份已变化，请刷新')
  const old = new Map(state.threads.map(t => [noteKey(t.row,t.column),t]))
  const next = new Map(old), touched = new Set<string>()
  for (const c of op.changes) {
    const key = noteKey(c.row,c.column), existing = old.get(key)
    if (touched.has(key) || (existing?.id ?? null) !== c.expectedThreadId) throw new Error('线程批注目标重复或身份已变化')
    touched.add(key)
    if (c.thread === null) next.delete(key)
    else {
      if (c.thread.row !== c.row || c.thread.column !== c.column || existing && c.thread.id !== existing.id) throw new Error('线程批注坐标或根身份不匹配')
      next.set(key,c.thread)
    }
  }
  const ids = new Set<string>(), people = new Map<string,string>()
  for (const t of next.values()) for (const e of [t,...t.replies]) {
    if (ids.has(e.id) || people.has(e.personId) && people.get(e.personId) !== e.author) throw new Error('线程批注身份重复或人物名称冲突')
    ids.add(e.id); people.set(e.personId,e.author)
  }
  const originalThreadPart=(await threadRelationship(source,path,THREAD_REL)).path
  for(const part of await source.paths())if(part.startsWith('xl/threadedComments/')&&part.endsWith('.xml')&&part!==originalThreadPart) {
    for(const m of (await source.readText(part)).matchAll(/<threadedComment\b[^>]*>/g))if(ids.has(readXmlAttribute(m[0],'id')??''))throw new Error('线程批注身份已被其他工作表使用')
  }
  const historical = new Map(state.threads.flatMap(t => [t,...t.replies]).map(e => [e.id,e]))
  for (const t of next.values()) for (const e of [t,...t.replies]) {
    const before = historical.get(e.id)
    if (before && (before.personId !== e.personId || before.author !== e.author || before.dT !== e.dT)) throw new Error('历史线程作者与时间不可改写')
  }
  const personsRel = await threadRelationship(source,'xl/workbook.xml',PERSON_REL)
  if(personsRel.path)for(const m of (await source.readText(personsRel.path)).matchAll(/<person\b[^>]*\/?\s*>/g)) {
    const personId=readXmlAttribute(m[0],'id'), author=readXmlAttribute(m[0],'displayName')
    if(personId && people.has(personId) && people.get(personId)!==decodeXmlText(author??''))throw new Error('共享线程人物名称冲突')
  }
  const legacy = await readSheetNotes(source,path,{allowPictures:true,allowThreads:true})
  if (legacy.readOnlyReason) throw new Error(legacy.readOnlyReason)
  for (const c of op.changes) if (!old.has(noteKey(c.row,c.column)) && legacy.notes.some(n => n.row === c.row && n.column === c.column)) throw new Error('此单元格已有旧式批注，请保留原批注')
  const mirrors = new Map<string,string>()
  const mirrorChanges = op.changes.map(c => {
    if(c.thread) mirrors.set(noteKey(c.row,c.column),`tc=${c.thread.id}`)
    return {row:c.row,column:c.column,text:c.thread ? threadMirrorText(c.thread.text,c.thread.replies) : null}
  })
  bytes = await patchSheetNotes(bytes,op.sheetName,legacy.sourceIdentity,mirrorChanges,{allowPictures:true,allowThreads:true,mirrorAuthors:mirrors})
  source = await createBufferEntrySource(bytes)
  const rel = await threadRelationship(source,path,THREAD_REL)
  const replaced = new Map<string,string>(), added = new Map<string,string>(), removed = new Set<string>()
  const pkg = {has:async(p:string) => !removed.has(p) && (added.has(p) || replaced.has(p) || await source.has(p)),readText:async(p:string) => added.get(p) ?? replaced.get(p) ?? await source.readText(p),write:(p:string,v:string) => {replaced.set(p,v)},add:(p:string,v:string) => {added.set(p,v)},remove:(p:string) => {removed.add(p)}}
  const notes = new Map<string,ThreadedNote>([...next.values()].map(t => [threadAddress(t.row,t.column),{author:t.author,text:t.text,thread:t}]))
  const result = await syncThreadedComments(pkg,path,rel.rels || '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',notes,new Map(),new Set())
  let rels = result.relsXml
  if(result.partRemoved) {
    rels = rels.replace(/<Relationship\b[^>]*\/>/g,r => readXmlAttribute(r,'Type') === THREAD_REL ? '' : r)
    const types = await pkg.readText('[Content_Types].xml')
    replaced.set('[Content_Types].xml',types.replace(/<Override\b[^>]*\/>/g,r => readXmlAttribute(r,'PartName') === `/${result.partPath}` ? '' : r))
  }
  if(rels !== rel.rels) (await source.has(rel.relsPath) ? replaced : added).set(rel.relsPath,rels)
  return (await assemblePackage(bytes,{replaced,added,addedBinary:new Map(),removedEntries:[...removed],addedEntries:[...added.keys()],touchedEntries:[...replaced.keys(),...added.keys(),...removed]})).buffer
}
