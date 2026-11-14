import type {NativeOperation} from './native-draft'

type TrackRevisionsModel={sourceSha256:string;enabled:boolean}
const fail=():never=>{throw new Error('Word 跟踪修订设置与当前来源不一致')}

export function docxTrackRevisionsEnabled(model:TrackRevisionsModel,operations:readonly NativeOperation[]):boolean{
 if(!/^[a-f0-9]{64}$/i.test(model.sourceSha256)||typeof model.enabled!=='boolean')return fail()
 const matches=operations.filter(operation=>operation.kind==='setTrackRevisions')
 if(!matches.length)return model.enabled
 if(matches.length!==1)return fail()
 const operation=matches[0]!
 if(Object.keys(operation).sort().join(',')!=='enabled,kind,sourceSha256'||operation.sourceSha256!==model.sourceSha256||typeof operation.enabled!=='boolean')return fail()
 return operation.enabled
}

export function withDocxTrackRevisions(operations:readonly NativeOperation[],model:TrackRevisionsModel,enabled:boolean):NativeOperation[]{
 if(typeof enabled!=='boolean')return fail()
 const next=operations.filter(operation=>operation.kind!=='setTrackRevisions')
 return enabled===model.enabled?next:[...next,{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled}]
}
