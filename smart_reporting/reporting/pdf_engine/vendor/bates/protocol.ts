import {validateBates,type BatesConfig} from './bates'
export interface BatesEntry {pageId:string;ordinal:number;origin:[number,number];rotate:number;lineXOffsets:[number]}
export interface BatesOperation {[key:string]:unknown;kind:'addBates';sourceSha256:string;config:BatesConfig;entries:BatesEntry[]}
export const BATES_POSITIONS=['top-left','top-center','top-right','bottom-left','bottom-center','bottom-right'] as const
export const BATES_COLORS:[[number,number,number],...[number,number,number][]]=[[.1,.1,.12],[.86,.22,.18],[.17,.4,1],[.1,.55,.28]]
export function validateBatesConfig(config:BatesConfig){
 if(!config||typeof config!=='object'||Object.keys(config).some(key=>!['prefix','start','digits','fontSize','color','position','firstPage','lastPage'].includes(key))||typeof config.prefix!=='string'||config.prefix.length>200||/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(config.prefix)||validateBates(config)||!Number.isSafeInteger(config.start)||!Number.isFinite(config.fontSize)||!BATES_POSITIONS.includes(config.position)||!Array.isArray(config.color)||config.color.length!==3||!BATES_COLORS.some(color=>color.every((value,index)=>value===config.color[index])))throw Error('Bates 前缀、起始编号、位数、字号、颜色、位置或页范围无效')
}
/** 每条内容保留应用时序号；删页后可以有空号，不得随最终页序重新编号。 */
export function validateBatesOperation(operation:BatesOperation,pageIds:Set<string>,sourceSha256:string){
 if(!operation||Object.keys(operation).some(key=>!['kind','sourceSha256','config','entries'].includes(key))||operation.kind!=='addBates'||operation.sourceSha256!==sourceSha256||!/^[a-f0-9]{64}$/.test(sourceSha256))throw Error('Bates 来源身份已变化')
 validateBatesConfig(operation.config)
 if(!Array.isArray(operation.entries)||!operation.entries.length||operation.entries.length>2000)throw Error('Bates 编号页面为空或超过 2000 页')
 const seen=new Set<string>();let previous=-1
 for(const entry of operation.entries){
  if(!entry||Object.keys(entry).some(key=>!['pageId','ordinal','origin','rotate','lineXOffsets'].includes(key))||!pageIds.has(entry.pageId)||seen.has(entry.pageId)||!Number.isSafeInteger(entry.ordinal)||entry.ordinal<=previous||entry.ordinal<0||!Number.isSafeInteger(operation.config.start+entry.ordinal)||operation.config.lastPage!==null&&entry.ordinal>operation.config.lastPage-operation.config.firstPage||!Array.isArray(entry.origin)||entry.origin.length!==2||entry.origin.some(value=>!Number.isFinite(value))||![0,90,180,270].includes(entry.rotate)||!Array.isArray(entry.lineXOffsets)||entry.lineXOffsets.length!==1||!Number.isFinite(entry.lineXOffsets[0])||entry.lineXOffsets[0]>0||entry.lineXOffsets[0]<-100000)throw Error('Bates 页面身份、应用序号或文字位置无效')
  seen.add(entry.pageId);previous=entry.ordinal
 }
}
