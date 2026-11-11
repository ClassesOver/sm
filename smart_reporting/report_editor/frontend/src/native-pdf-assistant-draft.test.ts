import { afterEach, expect, it, vi } from 'vitest'
import { bindNativePDFAssistant } from './native-pdf-assistant'
import { NativeDraft } from './native-draft'

afterEach(() => { document.body.replaceChildren(); localStorage.clear() })

it('草稿阅读展示实际投影页码、跳过原因并保留原始导航身份', async () => {
  const root = document.createElement('div'); document.body.append(root)
  const draft = new NativeDraft({documentId:'draft-read',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}, localStorage)
  const navigate = vi.fn()
  const api = {pdfAIStart:vi.fn().mockResolvedValue({taskId:'t',status:'completed',result:{
    answer:'当前草稿内容',coverage:{pageCount:3,fullyReadPages:[1,3]},
    projection:{originalSourceSha256:'a'.repeat(64),effectiveSha256:'b'.repeat(64),effectiveSize:123,previewDigest:'c'.repeat(64),draftSnapshotSha256:'d'.repeat(64),appliedOperationIndices:[0],skippedOperations:[{operationIndex:1,kind:'replaceText',pageId:'p1',reason:'原文字身份已变化'}],pageMapping:[],selectionMapping:[]},
    citations:[{pageNumber:2,pageId:'source-p2',effectivePageNumber:1,effectivePageId:'draft-p1'},{pageNumber:null,pageId:null,effectivePageNumber:3,effectivePageId:'draft-p3'}],
  }}),pdfAICancel:vi.fn()}
  const binding = bindNativePDFAssistant(root,{api:api as never,draft,selection:()=>[],onNavigate:navigate})
  binding.open('summarize')
  await vi.waitFor(()=>expect(root.textContent).toContain('当前草稿内容'))
  expect(root.textContent).toContain('阅读版本：未保存草稿')
  expect(root.textContent).toContain('实际读取草稿页码：1、3')
  expect(root.textContent).toContain('原文字身份已变化')
  const links = [...root.querySelectorAll<HTMLButtonElement>('.native-ai-evidence button')]
  expect(links[0].textContent).toBe('转到原始第 2 页（草稿第 1 页）')
  links[0].click(); expect(navigate).toHaveBeenCalledWith('source-p2')
  expect(links[1].textContent).toBe('草稿新增第 3 页（无原始页面）')
  expect(links[1].disabled).toBe(true)
  links[1].click(); expect(navigate).toHaveBeenCalledTimes(1)
  expect(draft.operations).toEqual([])
  binding.dispose()
})
