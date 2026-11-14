/** CustomShowDialog来源UI+本地OOXML扩展，引用绑定实际部件；统一runTxn原子提交。 */
import {XMLParser} from 'fast-xml-parser'
import type {OpenedPptx} from '@genoffice/pptx-engine'
import {readCustomShows,writeCustomShows,type CustomShow,type BoundCustomShow} from '../packages/pptx-engine/src/custom-shows.ts'
import {loadMasterOps} from './pptx-master-text.ts'
import {register} from '../packages/pptx-ops/src/ops/registry.ts'
export type {CustomShow}
export function inspectCustomShows(opened:OpenedPptx){
 try{return {customShows:readCustomShows(opened).map(({id,name,slidePaths})=>({id,name,slideIndices:slidePaths.map(p=>opened.deck.slides.findIndex(s=>s.path===p))})),customShowsEditable:true,customShowsReason:null}}
 catch(cause){return {customShows:[],customShowsEditable:false,customShowsReason:cause instanceof Error?cause.message:'custom_show_source_invalid'}}
}
export function prepareCustomShows(opened:OpenedPptx,input:unknown):BoundCustomShow[]|undefined{
 let old:BoundCustomShow[]
 try{old=readCustomShows(opened)}catch(error){if(input===undefined)return undefined;throw error}
 if(input===undefined)return old
 if(!Array.isArray(input)||input.length>100)throw Error('custom_shows_invalid')
 const seen=new Set<string>(),used=new Set(old.map(s=>s.id)),byId=new Map(old.map(s=>[s.id,s]));let next=0,total=0
 const result=input.map(item=>{
  if(!item||Object.keys(item).sort().join()!=='id,name,slideIndices'||typeof item.id!=='string'||!(/^(?:0|[1-9]\d*)$/.test(item.id)||/^cs-[a-z0-9-]{1,80}$/.test(item.id))||seen.has(item.id)||typeof item.name!=='string'||!item.name.trim()||item.name.length>255||/[\u0000-\u001f\u007f-\u009f\ufffe\uffff]|\p{Cs}/u.test(item.name)||!Array.isArray(item.slideIndices)||item.slideIndices.length>500||item.slideIndices.some((i:unknown)=>!Number.isInteger(i)||(i as number)<0||(i as number)>=opened.deck.slides.length))throw Error('custom_show_invalid')
  seen.add(item.id);total+=item.slideIndices.length;if(total>5000)throw Error('custom_show_budget_exceeded')
  const source=byId.get(item.id);if(!source&&!item.id.startsWith('cs-'))throw Error('custom_show_identity_invalid')
  let id=source?.id;if(id===undefined){while(used.has(String(next)))next++;if(next>4294967295)throw Error('custom_show_id_exhausted');id=String(next++);used.add(id)}
  return {id,name:item.name,slidePaths:item.slideIndices.map((i:number)=>opened.deck.slides[i]!.path),...(source?.original?{original:source.original}:{})}
 })
 const retained=new Set(result.map(s=>s.id)),removed=old.filter(s=>!retained.has(s.id))
 const activeShow=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'@_'}).parse(opened.archive.readText('ppt/presProps.xml')??'')?.['p:presentationPr']?.['p:showPr']?.['p:custShow']?.['@_id']
 if(removed.some(show=>show.id===String(activeShow)))throw Error('custom_show_referenced_cannot_delete')
 if(removed.length)for(const [part,bytes] of opened.archive.entries){if(!part.endsWith('.xml'))continue;const xml=Buffer.from(bytes).toString('utf8');for(const show of removed)if(new RegExp('ppaction://customshow\\?[^"\\s<>]*\\bid='+show.id+'(?:&amp;|[&"\\s<])','i').test(xml))throw Error('custom_show_referenced_cannot_delete')}
 return result
}
register({name:'setCustomShows',validate(op){if(!Array.isArray(op.shows))throw Error('custom_shows_transaction_invalid')},apply(op,ctx){const before=ctx.opened.archive.readText('ppt/presentation.xml');writeCustomShows(ctx.opened,op.shows as BoundCustomShow[]);return {op,before,after:op.shows}}})
export async function applyCustomShows(opened:OpenedPptx,shows:BoundCustomShow[]|undefined){if(shows===undefined)return;const runTxn=await loadMasterOps();const result=runTxn(opened,{ops:[{op:'setCustomShows',shows}]});if(!result.applied)throw Error(result.failures?.[0]?.error??'custom_show_transaction_failed')}
