import { afterEach, expect, it, vi } from 'vitest'
import { showOfficeReport, submitOfficeReport } from './office-report'

afterEach(() => vi.unstubAllGlobals())

it('waits for the workspace source list before submitting a new report', async () => {
  const host = document.body.appendChild(document.createElement('div'))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  let resolveSources!: (response: Response) => void
  const sourceList = new Promise<Response>(resolve => { resolveSources = resolve })
  const send = vi.fn(async (url: string) => {
    if (url.endsWith('/data-sources')) return sourceList
    if (url.endsWith('/reports/pending')) return Response.json({pending:null})
    return Response.json({status:'COMPLETED', content:{reportId:'r1'}})
  })
  vi.stubGlobal('fetch', send)
  try {
    const done = vi.fn().mockResolvedValue(undefined)
    showOfficeReport(host, {id:'catalog-team',name:'团队',role:'owner',personal_user:null,archived:false}, done)
    const prompt = host.querySelector('textarea')!
    const submit = host.querySelector<HTMLButtonElement>('button[type=submit]')!
    await vi.waitFor(() => expect(prompt.disabled).toBe(false))
    prompt.value = '生成报告'
    expect(submit.disabled).toBe(true)
    host.querySelector('form')!.dispatchEvent(new Event('submit', {cancelable:true}))
    expect(send.mock.calls.some(([url]) => url.endsWith('/runs'))).toBe(false)
    resolveSources(Response.json({items:[{id:'sales',name:'销售',available:true}]}))
    await vi.waitFor(() => expect(submit.disabled).toBe(false))
    submit.click()
    await vi.waitFor(() => expect(done).toHaveBeenCalledOnce())
  } finally {
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})

it('explains why a workspace cannot generate a new report without an available source', async () => {
  const host = document.body.appendChild(document.createElement('div'))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  const send = vi.fn(async (url: string) => {
    if (url.endsWith('/reports/pending')) return Response.json({pending:null})
    return Response.json({items:[{id:'legacy',name:'历史连接',available:false,reason:'缺少解密历史凭据所需的密钥。'}]})
  })
  vi.stubGlobal('fetch', send)
  try {
    showOfficeReport(host, {id:'no-source-team',name:'团队',role:'owner',personal_user:null,archived:false}, async () => {})
    const notice = host.querySelector('form [aria-live=polite]')!
    await vi.waitFor(() => expect(notice?.textContent).toContain('缺少解密历史凭据所需的密钥。'))
    expect(notice.textContent).toContain('当前工作区没有可用于报告的数据源。')
    expect(host.querySelector<HTMLButtonElement>('button[type=submit]')!.disabled).toBe(true)
  } finally {
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})

it('submits the selected workspace and preserves downloads when acceptance fails', async () => {
  const report = {
    reportId: 'r1',
    word: { downloadUrl: '/reports/v1/download/token/word' },
    publicationGate: { formalReleaseAllowed: false, issues: [{ message: '缺少依据' }] },
  }
  const send = vi.fn().mockResolvedValue(Response.json({
    status: 'COMPLETED', content: '报告已生成', step_results: [{ content: report }],
  }))
  vi.stubGlobal('fetch', send)
  await expect(submitOfficeReport('team', '生成报告')).resolves.toEqual(report)
  const [url, request] = send.mock.calls[0]!
  expect(url).toBe('/workflows/enterprise-reporting-workflow-v1/runs')
  expect(request.headers['X-Office-Workspace']).toBe('team')
  expect(request.body.get('message')).toBe('生成报告')
})

it('keeps the signed artifacts already issued before a workflow error', async () => {
  const host = document.body.appendChild(document.createElement('div'))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  const send = vi.fn(async (url: string) => {
    if (url.endsWith('/reports/pending')) return Response.json({pending:null})
    if (url.endsWith('/data-sources')) return Response.json({items:[{id:'sales',available:true}]})
    return Response.json({
      status:'ERROR', content:'归档写入失败。',
      step_results:[{content:{
        reportId:'partial', word:{downloadUrl:'/reports/v1/download/word-proof/word'},
        pdf:{downloadUrl:'/reports/v1/native/download/pdf-proof/pdf'},
        validation:{ok:false, issues:[{message:'页数不一致。'}]},
      }}],
    })
  })
  vi.stubGlobal('fetch', send)
  try {
    showOfficeReport(host, {id:'partial-team',name:'团队',role:'owner',personal_user:null,archived:false}, async () => {})
    const button = host.querySelector<HTMLButtonElement>('button[type=submit]')!
    await vi.waitFor(() => expect(button.disabled).toBe(false))
    host.querySelector('textarea')!.value = '生成报告'
    button.click()
    await vi.waitFor(() => expect([...host.querySelectorAll('a')].map(link => link.textContent)).toEqual(['下载 Word','下载 PDF']))
    const status = host.querySelector('[role=status]')!.textContent
    expect(status).toContain('归档写入失败。')
    expect(status).toContain('页数不一致。')
    expect(status).not.toContain('验收通过')
  } finally {
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})

it.each([
  ['ERROR', 'https://elsewhere.example/reports/v1/download/token/word'],
  ['RUNNING', '/reports/v1/download/token/word'],
])('does not surface a preliminary or foreign receipt for %s', async (state, downloadUrl) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
    status: state, content: '流程未完成。',
    step_results: [{content:{reportId:'partial', word:{downloadUrl}}}],
  })))
  await expect(submitOfficeReport('team', '生成报告')).rejects.toThrow('流程未完成。')
})

it.each(['step_results', 'step_requirements'])('shows clarification from %s', async field => {
  const step = { content: { clarificationQuestion: '请明确唯一的分析期间。' } }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
    status: 'PAUSED', [field]: [field === 'step_results' ? step : {step_output: step}],
  })))
  await expect(submitOfficeReport('team', '生成收入报告')).rejects.toThrow('请明确唯一的分析期间。')
})

it('sends clarification to the original run and shows its download', async () => {
  const host = document.body.appendChild(document.createElement('div'))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  const refresh = vi.fn().mockResolvedValue(undefined)
  const send = vi.fn().mockImplementation(async (url: string, _request: RequestInit) => {
    if (url.endsWith('/reports/pending')) return Response.json({pending:null})
    if (url.endsWith('/data-sources')) return Response.json({items:[{id:'sales',available:true}]})
    if (url.endsWith('/clarification')) return Response.json({status:'COMPLETED',
      content:{reportId:'r1', word:{downloadUrl:'/reports/v1/download/token/word'}, validation:{ok:false}}})
    return Response.json({status:'PAUSED', run_id:'run-1', step_requirements:[{
      step_id:'normalize-report-request', retry_count:1, step_output:{content:{clarificationQuestion:'分析期间？'}},
    }]})
  })
  vi.stubGlobal('fetch', send)
  try {
    showOfficeReport(host, {id:'team',name:'团队',role:'owner',personal_user:null,archived:false}, refresh)
    const prompt = host.querySelector('textarea')!
    const submit = () => host.querySelector('form')!.dispatchEvent(new Event('submit', {cancelable:true}))
    await vi.waitFor(() => expect(prompt.disabled).toBe(false))
    prompt.value = '生成营收报告'
    submit()
    await vi.waitFor(() => expect(prompt.getAttribute('aria-label')).toBe('补充说明'))
    expect(host.querySelector('select')!.disabled).toBe(true)
    prompt.value = '2026 年 1 月'
    submit()
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    const resume = send.mock.calls.find(([url]) => url.endsWith('/run-1/clarification'))!
    expect(resume[0]).toBe('/office/api/workspaces/team/reports/run-1/clarification')
    expect(JSON.parse(resume[1].body as string)).toEqual({feedback:'2026 年 1 月',retry_count:1})
    expect(host.querySelector('[role=status]')!.textContent).toContain('验收未通过')
    expect(host.querySelector('a')!.textContent).toBe('下载 Word')
  } finally {
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})

it.each([false, true])('restores a suspended report (saved browser locator: %s)', async saved => {
  const host = document.body.appendChild(document.createElement('div'))
  const space = {id:'restore-team',name:'团队',role:'owner' as const,personal_user:null,archived:false}
  const key = 'genoffice:report-pause:' + JSON.stringify(['writer', space.id])
  if (saved) sessionStorage.setItem(key, 'saved-run')
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  const send = vi.fn().mockImplementation(async (url: string, request: RequestInit) => {
    if (url.endsWith('/data-sources')) return saved
      ? Response.json({message:'数据源暂不可用。'}, {status:503}) : Response.json({items:[]})
    if (request.method === 'GET') return Response.json({pending:{runId:'saved-run',retryCount:2,question:'请补充区域。'}})
    return Response.json({status:'COMPLETED', content:{reportId:'saved-run'}})
  })
  vi.stubGlobal('fetch', send)
  const refresh = vi.fn().mockResolvedValue(undefined)
  try {
    showOfficeReport(host, space, refresh, 'writer')
    const prompt = host.querySelector('textarea')!
    await vi.waitFor(() => expect(prompt.getAttribute('aria-label')).toBe('补充说明'))
    expect(host.querySelector<HTMLButtonElement>('button[type=submit]')!.disabled).toBe(false)
    expect(host.querySelector('[role=status]')!.textContent).toBe('请补充区域。')
    expect(sessionStorage.getItem(key)).toBe('saved-run')
    prompt.value = '华东'
    host.querySelector('form')!.dispatchEvent(new Event('submit', {cancelable:true}))
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    const calls = send.mock.calls.filter(([url]) => !url.endsWith('/data-sources'))
    expect(calls.map(([, request]) => request.method)).toEqual(['GET', 'POST'])
    expect(calls[0][0]).toContain(saved ? '/reports/saved-run/clarification' : '/reports/pending')
    expect(JSON.parse(calls[1][1].body as string)).toEqual({feedback:'华东',retry_count:2})
    expect(sessionStorage.getItem(key)).toBeNull()
  } finally {
    sessionStorage.removeItem(key)
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})

it.each([false, true])('shows reasons and preserves all usable links (malformed Excel link: %s)', async malformed => {
  const host = document.createElement('div')
  document.body.append(host)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:function (this: HTMLDialogElement) { this.open = true }})
  try {
    const report = {
      reportId: 'r1',
      word: { downloadUrl: '/reports/v1/download/token/word' },
      pdf: { downloadUrl: '/reports/v1/download/token/pdf' },
      xlsx: { downloadUrl: malformed ? 'https://[' : '/reports/v1/download/token/xlsx' },
      pptx: { downloadUrl: '/reports/v1/download/token/pptx' },
      editor: { openUrl: '/office/unexpected-editor' },
      sourceWarnings: [{ message: '来源表缺少统计口径。' }],
      validation: { ok: false, issues: [{ message: '页数不一致。' }] },
      publicationGate: { warnings: [{ message: '部分数值待核对。' }], issues: [
        { message: '验收未通过。', details: { validationIssues: [{ message: '缺少图表来源。' }] } },
      ] },
    }
    const send = vi.fn().mockImplementation(async (url: string, _request: RequestInit) => url.endsWith('/reports/pending')
      ? Response.json({pending:null}) : url.endsWith('/data-sources')
      ? Response.json({items:[{id:'sales',name:'销售',available:true},{id:'blocked',available:false,reason:'历史凭据不可用。'}]})
      : Response.json({status:'COMPLETED', content:report}))
    vi.stubGlobal('fetch', send)
    const refresh = vi.fn().mockResolvedValue(undefined)
    showOfficeReport(host, {id:'team',name:'团队',role:'owner',personal_user:null,archived:false}, refresh)
    await vi.waitFor(() => expect(host.querySelector('input[value=sales]')).not.toBeNull())
    host.querySelector('textarea')!.value = '生成报告'
    host.querySelector('select')!.value = 'pptx'
    expect(host.querySelector('input[value=blocked]')).toBeNull()
    expect(host.querySelector('form [aria-live=polite]')?.textContent).toContain('历史凭据不可用。')
    host.querySelector<HTMLInputElement>('input[value=sales]')!.checked = true
    host.querySelector('form')!.dispatchEvent(new Event('submit', {cancelable:true}))
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce())
    const submission = send.mock.calls.find(([url]) => url.endsWith('/runs'))!
    expect(JSON.parse((submission[1].body as URLSearchParams).get('message')!)).toEqual({prompt:'生成报告',deliveryFormat:'pptx',sourceIds:['sales']})
    for (const message of ['报告已生成，验收未通过。','页数不一致。','缺少图表来源。','部分数值待核对。','来源表缺少统计口径。']) {
      expect(host.querySelector('[role=status]')!.textContent).toContain(message)
    }
    expect([...host.querySelectorAll('a')].map(link => link.textContent)).toEqual(['下载 Word','下载 PDF', ...(malformed ? [] : ['下载 Excel']), '下载 PowerPoint'])
  } finally {
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    host.remove()
  }
})
