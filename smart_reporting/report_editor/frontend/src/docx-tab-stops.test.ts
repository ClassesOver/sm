import { expect, it } from 'vitest'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { projectDocxTabStops, normalizeDocxTabStops } from './docx-tab-stops'
const anchor = { docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'a'.repeat(64), editable: true, tabStopsEditable: true }
const source = () => ({ type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, nativeTabStops: null, tabStops: JSON.stringify([{pos:2160,val:'left',inherited:true}]), indentLeft:125 }, content: [{ type:'text',text:'A\tB' }] }] })

it('persists exact direct tabs and inherited clears through real collector and replay', () => {
  const before = source(), after = structuredClone(before)
  const stops = [{pos:2160,val:'clear'}, {pos:4320,val:'decimal',leader:'dot'}]
  after.content[0] = projectDocxTabStops(before.content[0]!, anchor, stops) as typeof after.content[0]
  const ops = docxOperations(before, after, [anchor])
  expect(ops).toEqual([{kind:'setParagraphTabStops',blockId:'p0',expectedObjectSha256:anchor.expectedObjectSha256,stops}])
  expect(replayDocxOperations(before, ops, [anchor])).toEqual(after)
  expect(() => replayDocxOperations(before,[...ops,...ops],[anchor])).toThrow()
  expect(() => replayDocxOperations(before,[...ops,{kind:'setParagraphRulerIndent',blockId:'p0',expectedObjectSha256:anchor.expectedObjectSha256,leftTwips:810}],[anchor])).toThrow()
  expect(() => replayDocxOperations(before,ops,[{...anchor,tabStopsEditable:false}])).toThrow()
  expect(() => replayDocxOperations(before,[{...ops[0]!,expectedObjectSha256:'stale'}],[anchor])).toThrow()
  after.content[0]!.content = [{type:'text',text:'混改'}]
  expect(() => docxOperations(before,after,[anchor])).toThrow()
})

it('removes the last direct stop without losing an explicit empty intent', () => {
  const before=source(), after=structuredClone(before)
  after.content[0]=projectDocxTabStops(before.content[0]!,anchor,[]) as typeof after.content[0]
  expect(after.content[0]!.attrs).toMatchObject({tabStops:null,nativeTabStops:[]})
  expect(docxOperations(before,after,[anchor])[0]).toMatchObject({kind:'setParagraphTabStops',stops:[]})
})

it('rejects ambiguous positions and unmodeled fields while retaining supported leaders', () => {
  expect(normalizeDocxTabStops([{pos:4320,val:'right',leader:'hyphen'},{pos:2160,val:'clear'}])).toEqual([{pos:2160,val:'clear'},{pos:4320,val:'right',leader:'hyphen'}])
  for(const stops of [null,{},[{pos:true,val:'left'}],[{pos:1.5,val:'left'}],[{pos:720,val:'num'}],[{pos:720,val:'left',inherited:true}],[{pos:720,val:'left',leader:'invalid'}],[{pos:720,val:'left'},{pos:720,val:'right'}]]) expect(()=>normalizeDocxTabStops(stops)).toThrow()
  expect(()=>projectDocxTabStops(source().content[0]!,{...anchor,editable:false},[])).toThrow()
})
