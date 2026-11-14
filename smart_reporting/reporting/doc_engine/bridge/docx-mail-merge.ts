import {createHash} from 'node:crypto'
import {loadDocxZip} from '../packages/docx-engine/src/zip-load.ts'
import {parseDocx} from '../packages/docx-engine/src/parse.ts'
import {escapeXmlAttr} from '../packages/docx-engine/src/xml-utils.ts'
import {mergeFieldName,mergeFieldText} from '../packages/docx-engine/src/mail-merge.ts'
import {XMLParser} from 'fast-xml-parser'
import {saveDocx,mergeFieldInstruction,type Run,type SaveBlock} from '@genoffice/docx-engine'

const fail=(code:string):never=>{throw new Error(`docx_mail_merge_${code}`)}
const sha=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
type RecordValue=Record<string,string>
const decode=(instr:string)=>String(new XMLParser().parse(`<value>${instr}</value>`).value)
function fieldName(instr:string){return mergeFieldName(decode(instr))}
function replaceFieldResults(xml:string,record:RecordValue){
  const replacements:{start:number;end:number;text:string}[]=[]
  let field:{start:number;instr:string;separated:boolean;cached:string}|null=null
  for(const match of xml.matchAll(/<w:r\b[^>]*>[\s\S]*?<\/w:r>/g)){
    const run=match[0],types=[...run.matchAll(/<w:fldChar\b[^>]*w:fldCharType=["']([^"']+)["']/g)].map(m=>m[1])
    if(types.length>1)fail('complex_field_unsupported')
    if(types[0]==='begin'){if(field)fail('nested_field_unsupported');field={start:match.index!,instr:'',separated:false,cached:''};continue}
    if(!field)continue
    if(types[0]==='end'){
      if(/<\/?w:p\b/.test(xml.slice(field.start,match.index)))fail('cross_paragraph_field_unsupported')
      const instruction=decode(field.instr)
      if(/^\s*(?:IF|NEXT|NEXTIF|SKIPIF)\b/i.test(instruction))fail('control_field_unsupported')
      if(mergeFieldName(instruction)){
        let first=true
        const result=field.cached.replace(/(<w:t\b[^>]*>)[\s\S]*?(<\/w:t>)/g,(_text:string,start:string,close:string)=>{const replacement=first?escapeXmlAttr(mergeFieldText(instruction,record)):'';first=false;return start+replacement+close})
        if(first||!field.separated)fail('field_result_missing')
        replacements.push({start:field.start,end:match.index!+run.length,text:result})
      }
      field=null;continue
    }
    if(types[0]==='separate'){field.separated=true;continue}
    if(field.separated)field.cached+=run
    else for(const instruction of run.matchAll(/<w:instrText\b[^>]*>([\s\S]*?)<\/w:instrText>/g))field.instr+=instruction[1]
  }
  if(field)fail('field_unclosed')
  for(const replacement of replacements.reverse())xml=xml.slice(0,replacement.start)+replacement.text+xml.slice(replacement.end)
  return xml
}
export async function patchDocxMailMerge(bytes:Uint8Array,operation:unknown):Promise<Uint8Array>{
  if(!operation||typeof operation!=='object'||Array.isArray(operation))fail('operation_invalid')
  const op=operation as Record<string,unknown>
  if(!['mailMergeSingle','insertMailMergeField'].includes(String(op.kind)))fail('operation_invalid')
  if(op.documentSha256!==sha(bytes))fail('source_changed')
  if(op.kind==='insertMailMergeField'){
    const parsed=await parseDocx(bytes),block=parsed.blocks.find(b=>b.docxIndex===op.docxIndex)
    if(parsed.protection?.enforced||!block?.runs||block.sdtShell||!['paragraph','heading','listItem'].includes(block.type)||!block.originalXml||sha(new TextEncoder().encode(block.originalXml))!==op.expectedObjectSha256)fail('anchor_invalid')
    if(typeof op.name!=='string'||!/^[^"\x00-\x1f\x7f]{1,128}$/.test(op.name))fail('field_name_invalid')
    if(/<w:(?:fldChar|instrText|bookmarkStart|commentRangeStart|footnoteReference|drawing|sdt|hyperlink|ins|del)\b/.test(block.originalXml))fail('anchor_unsupported')
    const offset=op.offset
    const text=block.runs.map(r=>r.text).join('')
    if(typeof offset!=='number'||!Number.isInteger(offset)||offset<0||offset>text.length||offset>0&&/[\uD800-\uDBFF]/.test(text[offset-1]!)&&/[\uDC00-\uDFFF]/.test(text[offset]??''))fail('offset_invalid')
    const runs:Run[]=[],field:Run={text:`«${op.name}»`,instrField:mergeFieldInstruction(op.name),fldDirty:false};let at=0,inserted=false
    for(const run of block.runs){const end=at+run.text.length;if(!inserted&&offset<=end){if(offset>at)runs.push({...run,text:run.text.slice(0,offset-at)});runs.push(field);if(offset<end)runs.push({...run,text:run.text.slice(offset-at)});inserted=true}else runs.push(run);at=end}
    if(!inserted)runs.push(field)
    const saved:SaveBlock[]=parsed.blocks.filter(b=>!b.hidden&&b.docxIndex!=null).map(b=>b===block?{kind:'generated',block:{type:block.type as 'paragraph',runs,rawPPr:block.rawPPr,rawPAttrs:block.originalXml?.match(/^<w:p(\s[^>]*)?>/)?.[1],level:block.level,list:block.list}}:{kind:'original',docxIndex:b.docxIndex!})
    return saveDocx(parsed,saved)
  }
  if(!Array.isArray(op.records)||op.records.length<1||op.records.length>2000||!Array.isArray(op.fields))fail('source_invalid')
  const records=op.records.map(item=>{if(!item||typeof item!=='object'||Array.isArray(item))fail('source_invalid');const out:RecordValue=Object.create(null);for(const field of op.fields as unknown[]){if(typeof field!=='string'||field.length>128)fail('source_invalid');const raw=(item as Record<string,unknown>)[field];if(typeof raw!=='string'||raw.length>10000)fail('source_invalid');out[field]=raw}return out})
  const parsed=await parseDocx(bytes);if(parsed.protection?.enforced)fail('protected')
  const zip=await loadDocxZip(bytes),file=zip.file('word/document.xml');if(!file)fail('document_missing')
  const xml=await file.async('string'),body=/<w:body>([\s\S]*?)<\/w:body>/.exec(xml);if(!body)fail('document_invalid')
  const trailing=/\s*(<w:sectPr(?:\s[^>]*)?(?:\/>|>[\s\S]*?<\/w:sectPr>))\s*$/.exec(body[1]!)
  const section=trailing?.[1]??''
  const content=trailing?body[1]!.slice(0,trailing.index):body[1]!
  if(/<w:sectPr\b/.test(content))fail('multiple_sections')
  const fieldNames=[...content.matchAll(/<w:instrText\b[^>]*>([\s\S]*?)<\/w:instrText>/g)].map(match=>fieldName(match[1]!)).filter((name):name is string=>!!name)
  if(!fieldNames.length)fail('fields_missing')
  if(fieldNames.some(name=>!(op.fields as string[]).includes(name)))fail('field_source_missing')
  if(Buffer.byteLength(content)*records.length>24*1024*1024)fail('output_too_large')
  let outputSize=0,nextDrawingId=1
  const merged=records.map((record,index)=>{
    let block=replaceFieldResults(content,record)
    if(index>0){
      block=block.replace(/<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|commentReference|footnoteReference|endnoteReference)\b[^>]*\/>/g,'')
      block='<w:p><w:r><w:br w:type="page"/></w:r></w:p>'+block
    }
    block=block.replace(/(<wp:docPr\b[^>]*\bid=)["'][^"']*["']/g,(_all,prefix)=>prefix+'"'+nextDrawingId+++'"')
    outputSize+=Buffer.byteLength(block)
    if(outputSize>24*1024*1024)fail('output_too_large')
    return block
  }).join('')
  zip.file('word/document.xml',xml.slice(0,body.index)+`<w:body>${merged}${section}</w:body>`+xml.slice(body.index+body[0].length))
  return zip.generateAsync({type:'uint8array'})
}
