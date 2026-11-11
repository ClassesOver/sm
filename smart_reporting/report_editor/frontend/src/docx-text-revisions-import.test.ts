import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {parseDocx,saveDocx,readSections} from '@genoffice/docx-engine'
import {buildDocx} from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import {inspectTextRevisions,resolveTextRevisions} from '../../../reporting/doc_engine/bridge/docx-revisions'
import {blocksToPmDoc,pmDocOptions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import {getDocxTextRevisionTargets,projectDocxTextRevisions} from './docx-text-revisions'
import type {DocxPmNode} from './docx-operations'
function schemaFor(node:DocxPmNode){
 const attrs=Object.fromEntries(Object.keys(node.attrs??{}).map(key=>[key,{default:null}])),marks:Record<string,any>={}
 for(const run of node.content??[])for(const mark of run.marks??[])marks[mark.type]={attrs:Object.fromEntries(Object.keys(mark.attrs??{}).map(key=>[key,{default:null}]))}
 return new Schema({nodes:{doc:{content:'docParagraph+'},docParagraph:{content:'inline*',attrs:{...attrs,nativeTextRevisionOperations:{default:null}}},text:{group:'inline'},hardBreak:{inline:true,group:'inline',attrs:{pageBreak:{default:false},colBreak:{default:false},wrapBreak:{default:false}}}},marks})
}
it('real XML parse/import and four source-wrapper resolutions agree with exact frontend projection',async()=>{
 const wrapper='<w:ins w:id="7" w:author="甲 &amp; A" w:date="2026-11-10T01:02:03Z"><w:r><w:rPr><w:b/></w:rPr><w:t>😀</w:t></w:r><w:r><w:t>同</w:t></w:r></w:ins>'
 const deletion='<w:del w:id="7" w:author="甲 &amp; A"><w:r><w:rPr><w:i/></w:rPr><w:delText>旧</w:delText><w:tab/><w:br w:clear="none"/><w:br w:type="page"/><w:br w:type="column"/><w:cr/></w:r></w:del>'
 const parsed=await parseDocx(await buildDocx({bodyXml:`<w:p><w:r><w:t>前</w:t></w:r>${wrapper}${wrapper}${deletion}<w:r><w:t>尾</w:t></w:r></w:p>`})),block=parsed.blocks[0],info=inspectTextRevisions(block,'source'),raw=(blocksToPmDoc(parsed.blocks,readSections(parsed),pmDocOptions(parsed)) as DocxPmNode).content![0],schema=schemaFor(raw),source=schema.nodeFromJSON(raw).toJSON() as DocxPmNode
 expect(info.revisionReadOnlyReason).toBeNull()
 // 显式测试fixture的服务端源贡献范围，身份来自真正core，范围不从PM mark列表反推。
 const ranges=[{from:1,to:4,text:'😀同'},{from:4,to:7,text:'😀同'},{from:7,to:13,text:'旧\t\u001e\f\v\n'}],anchor={docxIndex:block.docxIndex!,blockId:'source',expectedObjectSha256:info.reviewTargets[0].expectedObjectSha256,reviewTargets:info.reviewTargets.map((target,index)=>({...target,sourceRange:ranges[index]}))}
 expect(getDocxTextRevisionTargets(source,anchor).map(target=>target.text)).toEqual(ranges.map(range=>range.text))
 for(const [index,action] of [[0,'accept'],[0,'reject'],[2,'accept'],[2,'reject']] as const){
  const operation={kind:'resolveTextRevision' as const,blockId:'source',expectedObjectSha256:anchor.expectedObjectSha256,revisionId:anchor.reviewTargets[index].revisionId,action},projected=projectDocxTextRevisions(source,anchor,[operation],schema)
  const {kind:_,...coreOperation}=operation,changed=resolveTextRevisions(block,'source',[coreOperation]),reopened=await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex!,xml:changed.xml}])),expected=(blocksToPmDoc(reopened.blocks,readSections(reopened),pmDocOptions(reopened)) as DocxPmNode).content![0]
  expect(projected.content).toEqual(schema.nodeFromJSON(expected).toJSON().content)
  expect(getDocxTextRevisionTargets(source,anchor)[1].revisionId).not.toBe(operation.revisionId)
 }
})
