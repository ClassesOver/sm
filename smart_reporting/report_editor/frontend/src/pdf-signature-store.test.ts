import {expect,it} from 'vitest'
import {createPdfSignatureStore} from './pdf-signature-store'
const scope={database:'db',companyId:'org',userId:'user',threadId:'thread'}
const ink={kind:'strokes' as const,width:420,height:150,paths:[[1,2,30,40]]}
function memory(){const data=new Map<string,string>();return {getItem:(key:string)=>data.get(key)??null,setItem:(key:string,value:string)=>{data.set(key,value)}}}
it('persists exact native stroke coordinates across documents but isolates organization and user',async()=>{
 const storage=memory(),a=createPdfSignatureStore(scope,storage);await a.addSavedSignature(ink)
 expect((await createPdfSignatureStore({...scope,threadId:'other'},storage).listSavedSignatures())[0]?.data).toEqual(ink)
 for(const patch of [{companyId:'other'},{userId:'other'},{database:'other'}])expect(await createPdfSignatureStore({...scope,...patch},storage).listSavedSignatures()).toEqual([])
})
it('deduplicates payloads newest first, caps ten and removes exactly one saved signature',async()=>{
 const store=createPdfSignatureStore(scope,memory());for(let i=0;i<12;i++)await store.addSavedSignature({...ink,paths:[[i,2,30,40]]})
 let list=await store.listSavedSignatures();expect(list).toHaveLength(10);await store.addSavedSignature(list[4]!.data);list=await store.listSavedSignatures();expect(list).toHaveLength(10)
 const id=list[0]!.id;await store.removeSavedSignature(id);expect(await store.listSavedSignatures()).toHaveLength(9);expect((await store.listSavedSignatures()).some(item=>item.id===id)).toBe(false)
})
it('rejects malformed or oversized payloads without erasing valid entries; storage errors are visible',async()=>{
 const store=createPdfSignatureStore(scope,memory());await store.addSavedSignature(ink)
 for(const data of [{...ink,paths:[[1,2,3]]},{...ink,width:Infinity},{...ink,paths:[[1,2,NaN,4]]},{kind:'image',width:5,height:5,image:'not PNG'}])await expect(store.addSavedSignature(data as typeof ink)).rejects.toThrow()
 expect(await store.listSavedSignatures()).toHaveLength(1)
 await expect(createPdfSignatureStore(scope,{getItem:()=>null,setItem:()=>{throw Error('quota')}}).addSavedSignature(ink)).rejects.toThrow('quota')
})
