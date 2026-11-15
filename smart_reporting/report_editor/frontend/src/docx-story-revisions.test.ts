import {describe,it,expect} from 'vitest'
import {storyRevisionDraft,validatedStoryRevisionDrafts,storyRevisionItems} from './docx-story-revisions'
const target={targetId:'target',partPath:'word/footnotes.xml',expectedPartSha256:'part',expectedWrapperSha256:'wrapper',originalRevisionId:'7',kind:'footnote' as const,noteId:'2',type:'deletion' as const,author:'Ann',date:null,text:'old'}
describe('story revision draft identities',()=>{
 it('keeps source identities and validates restored drafts against live server targets',()=>{
  const draft=storyRevisionDraft(target,'reject');expect(draft).toEqual({kind:'resolveStoryRevision',targetId:'target',expectedPartSha256:'part',expectedWrapperSha256:'wrapper',action:'reject'})
  expect(validatedStoryRevisionDrafts([draft],[target])).toEqual([draft]);expect(storyRevisionItems([target],[draft])[0]).toMatchObject({pendingAction:'reject',location:'脚注 2'})
  for(const bad of [{...draft,expectedPartSha256:'stale'},{...draft,expectedWrapperSha256:'stale'},{...draft,xml:'forged'},{...draft,targetId:'unknown'}])expect(()=>validatedStoryRevisionDrafts([bad],[target])).toThrow()
  expect(()=>validatedStoryRevisionDrafts([draft,draft],[target])).toThrow()
 })
})
