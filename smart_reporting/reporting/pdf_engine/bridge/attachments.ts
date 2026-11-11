/** Strict native identity/budget adapter around unchanged pinned pdf-attachments.ts. */
import { createHash } from 'node:crypto'
import { inflateSync } from 'node:zlib'
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFNull, PDFRawStream, PDFRef, PDFString } from 'pdf-lib'
import { applyAttachments } from '../src/main/pdf-attachments'
export const ATTACHMENT_FILE_MAX = 2 * 1024 * 1024
export const ATTACHMENT_TOTAL_MAX = 6 * 1024 * 1024
const hash = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex')
export interface NativeAttachment { key: string; name: string; description: string; size: number; contentSha256: string; attachmentId: string; expectedAttachmentSha256: string }
export interface NativeAttachmentModel { attachments: NativeAttachment[]; attachmentsEditable: boolean; attachmentsReason: string | null }
export function validAttachmentName(name: string): boolean { return name.length>0&&name.length<=256&&name.trim().length>0&&!/[\x00-\x1f\x7f/\\]/.test(name)&&Buffer.from(name).toString('utf8')===name }
export function decodeAttachmentPayload(value: string): Uint8Array {
  if(value.length>4*Math.ceil(ATTACHMENT_FILE_MAX/3)||! /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))throw Error('pdf_attachment_payload_invalid')
  const bytes=Buffer.from(value,'base64');if(bytes.length>ATTACHMENT_FILE_MAX||bytes.toString('base64')!==value)throw Error('pdf_attachment_payload_invalid');return bytes
}
const text = (obj: unknown) => {if(!(obj instanceof PDFString||obj instanceof PDFHexString))throw Error('pdf_attachment_text_unreadable');return obj.decodeText()}
export function inspectAttachments(doc: PDFDocument, sourceSha: string, protectedSource: boolean): NativeAttachmentModel {
  const readonly = (reason: string): NativeAttachmentModel => ({attachments:[],attachmentsEditable:false,attachmentsReason:reason})
  try {
    if(protectedSource)return readonly('含签名、权限保护或XFA的来源，附件仅可查看/下载')
    const refs=new Map<string,number>(), containers=new Set<object>()
    const objects=doc.context.enumerateIndirectObjects();if(objects.length>20000)throw Error('pdf_attachment_source_inventory_limit')
    const stack=objects.map(([,obj])=>obj)
    while(stack.length){const obj=stack.pop()!;if(obj instanceof PDFRef){refs.set(obj.toString(),(refs.get(obj.toString())??0)+1);continue}
      if(obj instanceof PDFRawStream) { stack.push(obj.dict); continue }
      if(obj instanceof PDFDict||obj instanceof PDFArray){if(containers.has(obj))throw Error('pdf_attachment_shared_container');containers.add(obj)
        if(obj instanceof PDFDict){if(obj.has(PDFName.of('AF'))||obj.has(PDFName.of('ByteRange'))||String(obj.get(PDFName.of('Type')))==='/Sig'||String(obj.get(PDFName.of('Subtype')))==='/FileAttachment')throw Error('pdf_attachment_linked_source');for(const value of obj.values())stack.push(value)}
        else for(const value of obj.asArray())stack.push(value)
      }
    }
    const unique = (raw: unknown) => {if(raw instanceof PDFRef&&refs.get(raw.toString())!==1)throw Error('pdf_attachment_shared_reference')}
    const namesRaw=doc.catalog.get(PDFName.of('Names'));if(!namesRaw)return {attachments:[],attachmentsEditable:true,attachmentsReason:null};unique(namesRaw)
    const names=doc.context.lookup(namesRaw,PDFDict),treeRaw=names.get(PDFName.of('EmbeddedFiles'))
    if(!treeRaw)return {attachments:[],attachmentsEditable:true,attachmentsReason:null};unique(treeRaw)
    const tree=doc.context.lookup(treeRaw,PDFDict);if(tree.has(PDFName.of('Kids')))throw Error('pdf_attachment_hierarchical_tree')
    const raw=tree.get(PDFName.of('Names'));if(!raw)throw Error('pdf_attachment_names_missing');unique(raw)
    const array=doc.context.lookup(raw,PDFArray);if(array.size()%2||array.size()>400)throw Error('pdf_attachment_names_invalid')
    const keys=new Set<string>(),rows: NativeAttachment[]=[];let total=0
    for(let i=0;i<array.size();i+=2){const key=text(array.get(i));if(!key||keys.has(key)||Buffer.from(key).toString('utf8')!==key)throw Error('pdf_attachment_key_ambiguous');keys.add(key)
      const specRaw=array.get(i+1);if(!(specRaw instanceof PDFRef))throw Error('pdf_attachment_direct_filespec');unique(specRaw)
      const spec=doc.context.lookup(specRaw,PDFDict);if(spec.has(PDFName.of('AFRelationship')))throw Error('pdf_attachment_associated_file')
      const name=text(spec.lookup(PDFName.of('UF'))??spec.lookup(PDFName.of('F')))
      const description=spec.has(PDFName.of('Desc'))?text(spec.lookup(PDFName.of('Desc'))):''
      const efRaw=spec.get(PDFName.of('EF'));if(!efRaw)throw Error('pdf_attachment_ef_missing');unique(efRaw)
      const ef=doc.context.lookup(efRaw,PDFDict);if(ef.keys().some(k=>!['/F','/UF'].includes(k.toString())))throw Error('pdf_attachment_ef_unsupported')
      const streamRaw=ef.get(PDFName.of('UF'))??ef.get(PDFName.of('F'));if(!(streamRaw instanceof PDFRef))throw Error('pdf_attachment_stream_invalid')
      if(ef.values().some(value=>!(value instanceof PDFRef)||value.toString()!==streamRaw.toString())||refs.get(streamRaw.toString())!==ef.keys().length)throw Error('pdf_attachment_shared_stream')
      const stream=doc.context.lookup(streamRaw);if(!(stream instanceof PDFRawStream))throw Error('pdf_attachment_stream_invalid')
      const filter=stream.dict.get(PDFName.of('Filter')),params=stream.dict.get(PDFName.of('DecodeParms'))
      if(params&&params!==PDFNull)throw Error('pdf_attachment_decode_params_unsupported')
      const filters=filter instanceof PDFArray?filter.asArray():filter?[filter]:[]
      if(filters.length>1||filters.some(f=>String(f)!=='/FlateDecode'))throw Error('pdf_attachment_filter_unsupported')
      const bytes=filters.length?inflateSync(stream.contents,{maxOutputLength:8*1024*1024}):stream.contents
      total+=bytes.length;if(bytes.length>8*1024*1024||total>24*1024*1024)throw Error('pdf_attachment_source_bytes_limit')
      const contentSha256=hash(bytes),expectedAttachmentSha256=hash(`${spec.toString()}:${stream.dict.toString()}:${hash(stream.contents)}:${contentSha256}`)
      rows.push({key,name,description,size:bytes.length,contentSha256,expectedAttachmentSha256,attachmentId:hash(`${sourceSha}:${i/2}:${key}:${expectedAttachmentSha256}`)})
    }
    return {attachments:rows,attachmentsEditable:true,attachmentsReason:null}
  } catch(error){return readonly(`附件结构暂不能安全写回：${error instanceof Error?error.message:'unreadable'}`)}
}
export interface AttachmentEdit { kind: 'addAttachment' | 'removeAttachment'; name?: string; bytesBase64?: string; description?: string; attachmentId?: string; expectedAttachmentSha256?: string }
export async function patchAttachments(bytes: Uint8Array, source: NativeAttachmentModel, edits: AttachmentEdit[]): Promise<Uint8Array> {
  if(!edits.length)return bytes
  if(!source.attachmentsEditable)throw Error('pdf_attachment_source_readonly')
  const removed=new Set<string>(),added=new Set<string>();let total=0
  const remove: string[]=[],add: {name:string;bytesBase64:string;description?:string}[]=[]
  for(const op of edits){if(op.kind==='removeAttachment'){const row=source.attachments.find(r=>r.attachmentId===op.attachmentId);if(!row||row.expectedAttachmentSha256!==op.expectedAttachmentSha256||removed.has(row.key))throw Error('pdf_attachment_identity_invalid');removed.add(row.key);remove.push(row.key)}
    else {if(!op.name||!validAttachmentName(op.name)||typeof op.bytesBase64!=='string'||added.has(op.name))throw Error('pdf_attachment_add_invalid');const data=decodeAttachmentPayload(op.bytesBase64);total+=data.length;if(total>ATTACHMENT_TOTAL_MAX)throw Error('pdf_attachment_total_limit');added.add(op.name);add.push({name:op.name,bytesBase64:op.bytesBase64,...(op.description?{description:op.description}:{})})}}
  for(const name of added)if(source.attachments.some(r=>r.key===name&&!removed.has(name)))throw Error('pdf_attachment_name_collision')
  if(source.attachments.length-removed.size+add.length>200)throw Error('pdf_attachment_entry_limit')
  const doc=await PDFDocument.load(bytes,{updateMetadata:false})
  // Page writers must not silently drop/change files before the source writer runs.
  const before=inspectAttachments(doc,'intermediate',false)
  if(!before.attachmentsEditable||before.attachments.length!==source.attachments.length||source.attachments.some(row=>!before.attachments.some(r=>r.key===row.key&&r.expectedAttachmentSha256===row.expectedAttachmentSha256)))throw Error('pdf_attachment_intermediate_drift')
  applyAttachments(doc,{add,remove})
  const names=doc.catalog.lookup(PDFName.of('Names'),PDFDict),tree=names.lookup(PDFName.of('EmbeddedFiles'),PDFDict),array=tree.lookup(PDFName.of('Names'),PDFArray)
  // PDF name trees sort encoded string bytes, not decoded JavaScript labels.
  const pairs=Array.from({length:array.size()/2},(_,i)=>[array.get(i*2),array.get(i*2+1)] as const)
  pairs.sort((a,b)=>Buffer.compare(Buffer.from((a[0] as PDFString|PDFHexString).asBytes()),Buffer.from((b[0] as PDFString|PDFHexString).asBytes())))
  tree.set(PDFName.of('Names'),doc.context.obj(pairs.flatMap(pair=>[...pair])))
  const result=await doc.save({useObjectStreams:false,updateFieldAppearances:false}),after=inspectAttachments(await PDFDocument.load(result,{updateMetadata:false}),'output',false)
  const expected=source.attachments.filter(r=>!removed.has(r.key))
  if(!after.attachmentsEditable||after.attachments.length!==expected.length+add.length||expected.some(row=>!after.attachments.some(r=>r.key===row.key&&r.expectedAttachmentSha256===row.expectedAttachmentSha256))||add.some(item=>!after.attachments.some(r=>r.key===item.name&&r.contentSha256===hash(decodeAttachmentPayload(item.bytesBase64))&&r.description===(item.description??''))))throw Error('pdf_attachment_output_drift')
  return result
}
