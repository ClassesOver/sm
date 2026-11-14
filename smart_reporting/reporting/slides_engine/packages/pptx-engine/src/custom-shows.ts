/** 本地受控扩展：固定源CustomShowDialog只存localStorage，此模块补真实p:custShowLst。 */
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import type {OpenedPptx} from './index'
import {resolveTarget} from './zip'
import {escapeXmlAttr} from './xml-utils'
import {topLevelChildren} from './generate'
const path='ppt/presentation.xml',parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'@_',processEntities:true})
export type CustomShow={id:string;name:string;slideIndices:number[]}
export type BoundCustomShow={id:string;name:string;slidePaths:string[];original?:string}
function array(v:any):any[]{return v===undefined?[]:Array.isArray(v)?v:[v]}
export function readCustomShows(opened:OpenedPptx):BoundCustomShow[]{
 const xml=opened.archive.readText(path)??''
 if(XMLValidator.validate(xml)!==true||/<!DOCTYPE|<!ENTITY/.test(xml))throw Error('custom_show_xml_invalid')
 const root=parser.parse(xml)['p:presentation'];if(!root||root['@_xmlns:p']!=='http://schemas.openxmlformats.org/presentationml/2006/main'||root['@_xmlns:r']!=='http://schemas.openxmlformats.org/officeDocument/2006/relationships'||[...xml.matchAll(/xmlns:([pr])=['"]([^'"]*)['"]/g)].some(m=>m[2]!==root['@_xmlns:'+m[1]]))throw Error('custom_show_namespace_invalid')
 const lists=[...xml.matchAll(/<p:custShowLst\b[^>]*>([\s\S]*?)<\/p:custShowLst>|<p:custShowLst\b[^>]*\/>/g)]
 if(lists.length>1)throw Error('custom_show_list_invalid');if(!lists.length)return []
 const list=lists[0]![0],node=root['p:custShowLst'];if(node==='')return [];if(!node||Array.isArray(node)||Object.keys(node).some(k=>k!=='p:custShow'&&!k.startsWith('@_')))throw Error('custom_show_list_invalid')
 const raw=[...list.matchAll(/<p:custShow\b[^>]*>[\s\S]*?<\/p:custShow>/g)].map(m=>m[0]);const shows=array(node['p:custShow']);if(raw.length!==shows.length)throw Error('custom_show_list_invalid')
 const relationXml=opened.archive.readText('ppt/_rels/presentation.xml.rels')??'',relationDoc=parser.parse(relationXml)?.Relationships,relationNodes=array(relationDoc?.Relationship);if(XMLValidator.validate(relationXml)!==true||new Set(relationNodes.map(r=>r['@_Id'])).size!==relationNodes.length)throw Error('custom_show_relationship_ambiguous')
 const rels=opened.archive.readRels(path),seen=new Set<string>()
 return shows.map((show,i)=>{
  const id=String(show['@_id']??''),name=show['@_name'],body=show['p:sldLst'];if(!/^(0|[1-9]\d*)$/.test(id)||Number(id)>4294967295||seen.has(id)||typeof name!=='string'||!name.trim()||body===undefined||Array.isArray(body)||Object.keys(show).some(k=>!['@_id','@_name','p:sldLst','p:extLst'].includes(k))||Object.keys(body).some(k=>k!=='p:sld'))throw Error('custom_show_source_invalid');seen.add(id)
  const slidePaths=array(body['p:sld']).map(s=>{const rid=s['@_r:id'],rel=rels.get(rid);if(Object.keys(s).join()!=='@_r:id'||!rel||!rel.type.endsWith('/slide')||rel.targetMode === 'External')throw Error('custom_show_relationship_invalid');const target=resolveTarget(path,rel.target);if(!opened.deck.slides.some(slide=>slide.path===target))throw Error('custom_show_relationship_missing');return target})
  return {id,name,slidePaths,original:raw[i]!}
 })
}
export function writeCustomShows(opened:OpenedPptx,shows:BoundCustomShow[]){
 const xml=opened.archive.readText(path)!,rels=opened.archive.readRels(path),byPath=new Map<string,string>()
 for(const [id,rel] of rels)if(rel.type.endsWith('/slide')&&rel.targetMode !== 'External')byPath.set(resolveTarget(path,rel.target),id)
 const body=shows.map(show=>{
  const paths=show.slidePaths.filter(p=>opened.deck.slides.some(s=>s.path===p)),ids=paths.map(p=>{const id=byPath.get(p);if(!id)throw Error('custom_show_relationship_missing');return id})
  if(show.original){const old=parser.parse(show.original)['p:custShow'];const oldIds=array(old?.['p:sldLst']?.['p:sld']).map(s=>s['@_r:id']);if(old?.['@_name']===show.name&&String(old?.['@_id'])===show.id&&JSON.stringify(oldIds)===JSON.stringify(ids))return show.original
   const next=show.original.replace(/\bname=(['"])[\s\S]*?\1/,()=> 'name="'+escapeXmlAttr(show.name)+'"');return next.replace(/<p:sldLst\b[^>]*>[\s\S]*?<\/p:sldLst>|<p:sldLst\b[^>]*\/>/,()=>'<p:sldLst>'+ids.map(id=>'<p:sld r:id="'+escapeXmlAttr(id)+'"/>').join('')+'</p:sldLst>')}
  return '<p:custShow name="'+escapeXmlAttr(show.name)+'" id="'+show.id+'"><p:sldLst>'+ids.map(id=>'<p:sld r:id="'+escapeXmlAttr(id)+'"/>').join('')+'</p:sldLst></p:custShow>'
 }).join(''),list=body?((/<p:custShowLst\b[^>]*>/.exec(xml)?.[0]??'<p:custShowLst>').replace(/\/>$/,'>'))+body+'</p:custShowLst>':''
 const existing=/<p:custShowLst\b[^>]*>[\s\S]*?<\/p:custShowLst>|<p:custShowLst\b[^>]*\/>/
 const open=/<p:presentation\b[^>]*>/.exec(xml),end=xml.lastIndexOf('</p:presentation>');if(!open||end<0)throw Error('custom_show_root_invalid')
 const children=topLevelChildren(xml,open.index+open[0].length,end),before=children.find(c=>['p:photoAlbum','p:custDataLst','p:kinsoku','p:defaultTextStyle','p:modifyVerifier','p:extLst'].includes(c.name))?.start??end
 const next=existing.test(xml)?xml.replace(existing,()=>list):xml.slice(0,before)+list+xml.slice(before)
 if(XMLValidator.validate(next)!==true)throw Error('custom_show_write_invalid');opened.archive.entries.set(path,new Uint8Array(Buffer.from(next,'utf8')))
}
