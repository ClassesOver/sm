/** Strict new-link boundary for styled mixed saves; the fixed writer remains authoritative. */
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNull,PDFNumber,PDFRef,PDFString} from 'pdf-lib'
const fail=(reason:string):never=>{throw Error('pdf_text_link_'+reason)}
export function validateMixedLinkTarget(url:unknown,destPage:unknown,pageCount:number){
 if((url===undefined)===(destPage===undefined))return fail('ambiguous_target')
 if(destPage!==undefined){if(typeof destPage!=='number'||!Number.isInteger(destPage)||destPage<1||destPage>pageCount)return fail('invalid_destination');return}
 if(typeof url!=='string'||!url||url.length>2048||!/^[\x21-\x7e]+$/.test(url))return fail('invalid_url')
 let parsed:URL,decoded:string
 try{parsed=new URL(url);decoded=decodeURIComponent(url)}catch{return fail('invalid_url')}
 if(/[\p{Cc}\p{Cf}]/u.test(decoded)||parsed.username||parsed.password||/^https?:\/\/[^/?#]*@/i.test(url))return fail('unsafe_url')
 if(/^https?:\/\//i.test(url)&&['http:','https:'].includes(parsed.protocol)&&parsed.hostname)return
 if(/^mailto:/i.test(url)&&parsed.protocol==='mailto:'&&parsed.pathname&&!parsed.hash)return
 return fail('unsupported_url')
}
export function assertMixedLinkSource(document:PDFDocument){
 if(['OpenAction','AA'].some(key=>document.catalog.has(PDFName.of(key))))fail('source_actions_unsupported')
 if(document.catalog.lookupMaybe(PDFName.of('Names'),PDFDict)?.has(PDFName.of('JavaScript')))fail('source_actions_unsupported')
 for(const page of document.getPages()){
  if(page.node.has(PDFName.of('AA')))fail('source_actions_unsupported')
  const annotations=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
  for(let index=0;index<(annotations?.size()??0);index++)if(['A','AA','Dest'].some(key=>annotations!.lookup(index,PDFDict).has(PDFName.of(key))))fail('source_actions_unsupported')
 }
}
const keys=(dict:PDFDict,allowed:string[])=>{if(dict.keys().some(key=>!allowed.includes(key.decodeText())))fail('output_unexpected_action_or_metadata')}
export function reviewMixedLink(document:PDFDocument,pageIndex:number,annotation:PDFDict,rect:[number,number,number,number],target:{url?:string;destPage?:number}){
 const page=document.getPage(pageIndex)
 keys(annotation,['Type','Subtype','Rect','F','P',...(target.url!==undefined?['A']:['Dest'])])
 if(String(annotation.get(PDFName.of('Type')))!=='/Annot'||String(annotation.get(PDFName.of('Subtype')))!=='/Link'||String(annotation.get(PDFName.of('F')))!=='4'||String(annotation.get(PDFName.of('P')))!==String(page.ref))fail('output_identity_changed')
 const bounds=annotation.lookup(PDFName.of('Rect'))
 if(!(bounds instanceof PDFArray)||bounds.size()!==4||bounds.asArray().some((value,index)=>!(value instanceof PDFNumber)||value.asNumber()!==Math.round(rect[index]!*100)/100))fail('output_rect_changed')
 if(target.url!==undefined){
  const action=annotation.lookup(PDFName.of('A'),PDFDict);keys(action,['Type','S','URI'])
  const uri=action.lookup(PDFName.of('URI'))
  if(String(action.get(PDFName.of('Type')))!=='/Action'||String(action.get(PDFName.of('S')))!=='/URI'||!(uri instanceof PDFString)||uri.decodeText()!==target.url)fail('output_uri_changed')
 }else{
  const destination=annotation.lookup(PDFName.of('Dest')),pageRef=document.getPage(target.destPage!-1).ref
  if(!(destination instanceof PDFArray)||destination.size()!==5||!(destination.get(0)instanceof PDFRef)||String(destination.get(0))!==String(pageRef)||String(destination.get(1))!=='/XYZ'||destination.asArray().slice(2).some(value=>value!==PDFNull))fail('output_destination_changed')
 }
}
