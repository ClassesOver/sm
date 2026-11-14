import type {NativeDraftIdentity} from './native-draft'
export type PdfSignatureData={kind:'strokes';paths:number[][];width:number;height:number}|{kind:'image';image:string;width:number;height:number}
export interface SavedPdfSignature{id:string;createdAt:number;data:PdfSignatureData}
export interface PdfSignatureStore{listSavedSignatures():Promise<SavedPdfSignature[]>;addSavedSignature(data:PdfSignatureData):Promise<SavedPdfSignature[]>;removeSavedSignature(id:string):Promise<SavedPdfSignature[]>}
// 固定源 signature-store 的校验、同值去重、最新优先及十项上限；桌面文件改为当前用户浏览器存储。
function valid(value:unknown):value is PdfSignatureData{
 if(!value||typeof value!=='object')return false
 const v=value as PdfSignatureData
 if(!Number.isFinite(v.width)||!Number.isFinite(v.height)||v.width<=0||v.height<=0||v.width>16000||v.height>16000)return false
 if(v.kind==='image')return typeof v.image==='string'&&v.image.length<=6_000_000&&/^iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(v.image)
 return v.kind==='strokes'&&Array.isArray(v.paths)&&v.paths.length>0&&v.paths.length<=20&&v.paths.every(p=>Array.isArray(p)&&p.length>=4&&p.length<=4000&&p.length%2===0&&p.every(n=>typeof n==='number'&&Number.isFinite(n)))
}
export function createPdfSignatureStore(scope:NativeDraftIdentity['scope'],storage:Pick<Storage,'getItem'|'setItem'>):PdfSignatureStore{
 const key='native-pdf-signatures:v1:'+JSON.stringify([scope.database,scope.companyId,scope.userId])
 const read=():SavedPdfSignature[]=>{const raw=storage.getItem(key);if(!raw)return [];let parsed:unknown;try{parsed=JSON.parse(raw)}catch{return []}if(!Array.isArray(parsed))return [];const out:SavedPdfSignature[]=[];for(const item of parsed){if(!item||typeof item.id!=='string'||!item.id||out.some(s=>s.id===item.id)||!valid(item.data))continue;out.push({id:item.id,createdAt:Number.isFinite(item.createdAt)?item.createdAt:0,data:item.data});if(out.length===10)break}return out}
 const write=(list:SavedPdfSignature[])=>{storage.setItem(key,JSON.stringify(list));return structuredClone(list)}
 return {async listSavedSignatures(){return structuredClone(read())},async addSavedSignature(data){if(!valid(data))throw Error('签名数据或尺寸无效');const rest=read().filter(item=>JSON.stringify(item.data)!==JSON.stringify(data));return write([{id:crypto.randomUUID(),createdAt:Date.now(),data:structuredClone(data)},...rest].slice(0,10))},async removeSavedSignature(id){return write(read().filter(item=>item.id!==id))}}
}
