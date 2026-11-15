import {createHash} from 'node:crypto'
import {loadDocxZip} from '../packages/docx-engine/src/zip-load.ts'
import {parseDocx} from '../packages/docx-engine/src/parse.ts'
import {escapeXmlAttr} from '../packages/docx-engine/src/xml-utils.ts'
import {mergeFieldName,mergeFieldText,mergeOutputFileName,controlEffect} from '../packages/docx-engine/src/mail-merge.ts'
import {mailMergeLayout,layoutSectionXml,labelSheetXml} from './docx-mail-merge-layout.ts'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {saveDocx,mergeFieldInstruction,type Run,type SaveBlock} from '@genoffice/docx-engine'

const fail=(code:string):never=>{throw new Error(`docx_mail_merge_${code}`)}
const sha=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
type RecordValue=Record<string,string>
const decode=(instr:string)=>String(new XMLParser().parse(`<value>${instr}</value>`).value)
function expandSimpleMergeFields(xml:string){
 return xml.replace(/<w:fldSimple\b([^>]*?)(?:\/>|>([\s\S]*?)<\/w:fldSimple>)/g,(whole,attrs:string,cached:string|undefined)=>{
  if(/<w:(?:fldSimple|fldChar)\b/.test(cached??''))fail('nested_field_unsupported')
  const raw=/\bw:instr\s*=\s*(["'])([\s\S]*?)\1/.exec(attrs)?.[2]
  if(!raw)return whole
  const instruction=decode(raw)
  if(!/^\s*(?:MERGEFIELD|IF|NEXT|NEXTIF|SKIPIF)\b/i.test(instruction))return whole
  return '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>'+escapeXmlAttr(instruction)+'</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'+(cached??'')+'<w:r><w:fldChar w:fldCharType="end"/></w:r>'
 })
}
function replaceFieldResults(xml:string,records:RecordValue[],startIndex:number,allowCursorControls:boolean){
  let index=startIndex,skipped=false,recognized=0
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
      if(/^\s*NEXTIF\b/i.test(instruction))fail('control_field_unsupported')
      const name=mergeFieldName(instruction)
      if(name&&!Object.hasOwn(records[0]!,name))fail('field_source_missing')
      const record=records[index]??Object.create(null),effect=controlEffect(instruction,record)
      if(effect||name)recognized+=1
      if(effect&&effect.kind!=='if'){
        if(!allowCursorControls)fail('control_output_mode_unsupported')
        if(effect.kind==='next')index+=1
        if(effect.kind==='skip')skipped=true
        replacements.push({start:field.start,end:match.index!+run.length,text:''})
      }else if(mergeFieldName(instruction)||effect?.kind==='if'){
        let first=true
        const result=field.cached.replace(/(<w:t\b[^>]*>)[\s\S]*?(<\/w:t>)/g,(_text:string,start:string,close:string)=>{const replacement=first?escapeXmlAttr(effect?.kind==='if'?effect.text:mergeFieldText(instruction,record)):'';first=false;return start+replacement+close})
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
  return {xml,index,skipped,recognized}
}
/** Independent guard for both editor patches and the standalone export entry. */
async function assertMergeSource(bytes:Uint8Array){
 const zip=await loadDocxZip(bytes),xml=await zip.file('word/document.xml')?.async('string'),settings=await zip.file('word/settings.xml')?.async('string')
 const ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
 if(!xml||XMLValidator.validate(xml)!==true||/<!|<\?(?!xml\s)/.test(xml)||[...xml.matchAll(/\bxmlns:w\s*=/g)].length!==1)fail('protected_or_namespace_unsupported')
 const parser=new XMLParser({preserveOrder:true,ignoreAttributes:false,attributeNamePrefix:'',parseAttributeValue:false}),name=(node:any)=>Object.keys(node).find(key=>key!==':@'),attrs=(node:any)=>node[':@']??{}
 const document=parser.parse(xml).find((node:any)=>name(node)==='w:document'),body=document?.['w:document']?.filter((node:any)=>name(node)==='w:body')
 if(!document||attrs(document)['xmlns:w']!==ns||body?.length!==1)fail('protected_or_namespace_unsupported')
 if(!settings)return
 if(XMLValidator.validate(settings)!==true||/<!/.test(settings))fail('protected_or_namespace_unsupported')
 const visit=(node:any,inherited:Record<string,string>):boolean=>{
  const a=attrs(node),namespaces={...inherited}
  for(const [key,value] of Object.entries(a))if(key==='xmlns')namespaces['']=String(value);else if(key.startsWith('xmlns:'))namespaces[key.slice(6)]=String(value)
  const tag=name(node)??'',colon=tag.indexOf(':'),prefix=colon<0?'':tag.slice(0,colon),local=colon<0?tag:tag.slice(colon+1)
  if(local==='documentProtection'&&namespaces[prefix]===ns){
   const enforcement=Object.entries(a).find(([key])=>{const i=key.indexOf(':');return i>0&&key.slice(i+1)==='enforcement'&&namespaces[key.slice(0,i)]===ns})?.[1]
   if(!enforcement||!['0','false','off'].includes(String(enforcement)))return true
  }
  return Array.isArray(node[tag])&&node[tag].some((child:any)=>visit(child,namespaces))
 }
 if(parser.parse(settings).some((node:any)=>visit(node,{})))fail('protected_or_namespace_unsupported')
}
export async function patchDocxMailMerge(bytes:Uint8Array,operation:unknown,allowCursorControls=true):Promise<Uint8Array>{
  if(!operation||typeof operation!=='object'||Array.isArray(operation))fail('operation_invalid')
  const op=operation as Record<string,unknown>
  if(!['mailMergeSingle','insertMailMergeField'].includes(String(op.kind)))fail('operation_invalid')
  if(op.documentSha256!==sha(bytes))fail('source_changed')
  await assertMergeSource(bytes)
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
  const content=expandSimpleMergeFields(trailing?body[1]!.slice(0,trailing.index):body[1]!)
  if(/<w:sectPr\b/.test(content))fail('multiple_sections')
  if(Buffer.byteLength(content)*records.length>24*1024*1024)fail('output_too_large')
  let outputSize=0,nextDrawingId=1
  const parts:string[]=[]
  for(let at=0;at<records.length;){
    const result=replaceFieldResults(content,records,at,allowCursorControls);at=result.index+1
    if(!result.recognized)fail('fields_missing')
    if(result.skipped)continue
    let block=result.xml
    if(parts.length>0){
      block=block.replace(/<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|commentReference|footnoteReference|endnoteReference)\b[^>]*\/>/g,'')
      block='<w:p><w:r><w:br w:type="page"/></w:r></w:p>'+block
    }
    block=block.replace(/(<wp:docPr\b[^>]*\bid=)["'][^"']*["']/g,(_all,prefix)=>prefix+'"'+nextDrawingId+++'"')
    outputSize+=Buffer.byteLength(block)
    if(outputSize>24*1024*1024)fail('output_too_large')
    parts.push(block)
  }
  const merged=parts.join('')
  zip.file('word/document.xml',xml.slice(0,body.index)+`<w:body>${merged}${section}</w:body>`+xml.slice(body.index+body[0].length))
  return zip.generateAsync({type:'uint8array'})
}

export interface DocxMailMergeFile {name:string;bytes:Uint8Array}
/** Called only after the native host independently reads the registered CSV. */
export async function buildDocxMailMergeFiles(bytes:Uint8Array,operation:unknown):Promise<DocxMailMergeFile[]> {
 if(!operation||typeof operation!=='object'||Array.isArray(operation))fail('operation_invalid')
 const op=operation as Record<string,unknown>
 const allowed=['kind','mode','documentSha256','sourceSha256','fields','records','namePattern','layout']
 if(op.kind!=='mailMergeOutput'||Object.keys(op).some(key=>!allowed.includes(key))||!['perRecord','labels','envelopes'].includes(String(op.mode)))fail('operation_invalid')
 if(op.documentSha256!==sha(bytes))fail('source_changed')
 if(typeof op.namePattern!=='string'||op.namePattern.length>256||/[\x00-\x1f\x7f]/.test(op.namePattern))fail('name_pattern_invalid')
 if(!Array.isArray(op.records)||op.records.length<1||op.records.length>2000||!Array.isArray(op.fields)||op.fields.length<1||op.fields.length>100||new Set(op.fields).size!==op.fields.length)fail('source_invalid')
 const fields=op.fields as string[]
 if(fields.some(name=>typeof name!=='string'||!/^[^"\x00-\x1f\x7f]{1,128}$/.test(name)))fail('source_invalid')
 const records=op.records as RecordValue[]
 for(const record of records){
  if(!record||typeof record!=='object'||Array.isArray(record)||Object.keys(record).some(key=>!fields.includes(key)))fail('source_invalid')
  for(const name of fields)if(!Object.hasOwn(record,name)||typeof record[name]!=='string'||record[name]!.length>10000||/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]/.test(record[name]!))fail('source_invalid')
 }
 const layout=op.mode==='perRecord'?undefined:mailMergeLayout(String(op.mode),op.layout)
 if(op.mode==='perRecord'&&op.layout!==undefined)fail('layout_invalid')
 const files:DocxMailMergeFile[]=[],names=new Set<string>(),labelCells:string[]=[]
 let outputSize=0,labelSize=0
 for(const record of records){
  let output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:op.documentSha256,fields,records:[record]},false)
  if(layout){
   const zip=await loadDocxZip(output),xml=await zip.file('word/document.xml')!.async('string'),body=/<w:body>([\s\S]*?)<\/w:body>/.exec(xml)!
   const trailing=/\s*(<w:sectPr(?:\s[^>]*)?(?:\/>|>[\s\S]*?<\/w:sectPr>))\s*$/.exec(body[1]!),section=layoutSectionXml(trailing?.[1]??'',layout),content=trailing?body[1]!.slice(0,trailing.index):body[1]!
   if(op.mode==='labels'){
    // The source omits unsupported label blocks with a disclosure. Reject them here so no source content is silently lost.
    const labelNodes=new XMLParser({preserveOrder:true}).parse(content)
    if(!labelNodes.every((node:Record<string,unknown>)=>Object.keys(node).every(key=>key==='w:p'))||/<w:(?:tbl|txbxContent|sdt)\b/.test(content))fail('label_content_unsupported')
    labelSize+=Buffer.byteLength(content)
    if(labelSize>24*1024*1024)fail('output_too_large')
    labelCells.push(labelCells.length?content.replace(/<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd|commentReference|footnoteReference|endnoteReference)\b[^>]*\/>/g,''):content)
    if(labelCells.length<records.length)continue
    let nextDrawingId=1
    const sheet=labelSheetXml(labelCells,layout).replace(/(<wp:docPr\b[^>]*\bid=)["'][^"']*["']/g,(_all,prefix)=>prefix+'"'+nextDrawingId+++'"')
    zip.file('word/document.xml',xml.slice(0,body.index)+`<w:body>${sheet}${section}</w:body>`+xml.slice(body.index+body[0].length))
   }else zip.file('word/document.xml',xml.slice(0,body.index)+`<w:body>${content}${section}</w:body>`+xml.slice(body.index+body[0].length))
   output=await zip.generateAsync({type:'uint8array'})
  }
  outputSize+=output.byteLength
  if(outputSize>64*1024*1024)fail('output_too_large')
  const base=op.mode==='labels'?'labels-merged':mergeOutputFileName(op.namePattern,record,fields)
  let name=base+'.docx',count=1
  while(names.has(name.toLowerCase()))name=`${base} (${++count}).docx`
  names.add(name.toLowerCase());files.push({name,bytes:output})
 }
 return files
}
