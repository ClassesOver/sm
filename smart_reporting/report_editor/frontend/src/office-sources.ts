import { officeRequest, OfficeRequestError, type OfficeSpace } from './office-client'

type Draft = { source_id: string; name: string; database: string; version: number; metadata_version_id: string | null }
type Source = Draft & { publishedRevision: number | null; enabled: boolean }
type Table = { database: string; name: string }
type TableAccess = { draftVersion: number; discoveryId: string | null; draftTables: Table[]; publishedTables: Table[] }
const key = (table: Table) => `${table.database}.${table.name}`
const enc = encodeURIComponent

function node<K extends keyof HTMLElementTagNameMap>(tag: K, text = '') {
  const result = document.createElement(tag)
  result.textContent = text
  return result
}

function field(label: string, value = '', type = 'text') {
  const input = node('input')
  input.value = value; input.type = type; input.required = true
  input.setAttribute('aria-label', label)
  const wrapper = node('label', label)
  wrapper.append(input)
  return { wrapper, input }
}

function choices(values: string[], selected: string[]) {
  const container = node('div')
  container.className = 'source-table-choices'
  const boxes = new Map<string, HTMLInputElement>()
  for (const value of values) {
    const label = node('label')
    const box = node('input')
    box.type = 'checkbox'; box.checked = selected.includes(value)
    boxes.set(value, box)
    label.append(box, document.createTextNode(value))
    container.append(label)
  }
  return { container, values: () => [...boxes].filter(([, box]) => box.checked).map(([value]) => value) }
}

export async function showOfficeSources(host: HTMLElement, options: { admin: boolean; space?: OfficeSpace }) {
  const queryDrafts = new Map<string, string>()
  const panel = node('dialog')
  panel.className = 'office-administration office-sources'
  const heading = node('h2', options.admin ? '公司数据源管理' : '工作区数据源')
  const content = node('div'), status = node('p'), close = node('button', '关闭')
  status.setAttribute('role', 'status')
  close.onclick = () => panel.close()
  panel.onclose = () => panel.remove()
  panel.addEventListener('click', event => event.stopPropagation())
  panel.append(heading, content, status, close)
  host.append(panel); panel.showModal()

  async function run(action: () => Promise<void>) {
    if (panel.getAttribute('aria-busy') === 'true') return
    panel.setAttribute('aria-busy', 'true')
    const controls = [...panel.querySelectorAll<HTMLButtonElement | HTMLSelectElement | HTMLTextAreaElement | HTMLInputElement>(
      'button:enabled, select:enabled, textarea:enabled, input[type=checkbox]:enabled',
    )]
    controls.forEach(control => { control.disabled = true })
    status.textContent = '正在处理…'
    try { await action(); status.textContent = '' }
    catch (error) { status.textContent = error instanceof Error ? error.message : '操作失败。' }
    finally {
      controls.forEach(control => { control.disabled = false })
      panel.removeAttribute('aria-busy')
    }
  }

  function button(label: string, action: () => Promise<void>) {
    const result = node('button', label)
    result.type = 'button'; result.onclick = () => void run(action)
    return result
  }

  async function list() {
    content.replaceChildren()
    if (!options.admin) { await available(); return }
    content.append(button('新增 StarRocks 数据源', async () => edit()))
    let cursor: string | null = null
    do {
      const page: { items: Source[]; nextCursor: string | null } = await officeRequest(
        '/admin/data-sources?limit=100' + (cursor ? `&after=${enc(cursor)}` : ''))
      for (const source of page.items) {
        const row = node('div'); row.className = 'office-admin-row'
        row.append(node('span', `${source.name} · ${source.database}`),
          node('small', source.publishedRevision ? `已发布 v${source.publishedRevision}` : '未发布'),
          button('连接与表范围', async () => edit(source.source_id)),
          button('工作区授权', async () => grants(source.source_id)))
        content.append(row)
      }
      cursor = page.nextCursor
    } while (cursor)
  }

  async function edit(id?: string) {
    const base = id ? `/admin/data-sources/${enc(id)}` : ''
    const detail = id ? await officeRequest<{ draft: Draft }>(base) : undefined
    content.replaceChildren(button('返回数据源', list))
    const form = node('form')
    form.className = 'source-form'
    const identity = field('数据源标识', id)
    identity.input.disabled = Boolean(id)
    const name = field('名称', detail?.draft.name)
    const database = field('数据库', detail?.draft.database)
    const dsn = field(id ? '更换连接地址（留空保留）' : 'StarRocks 连接地址', '', 'password')
    dsn.input.required = !id; dsn.input.autocomplete = 'new-password'
    dsn.input.placeholder = 'starrocks://user:password@host:9030/database'
    const save = node('button', '保存草稿'); save.type = 'submit'
    form.append(identity.wrapper, name.wrapper, database.wrapper, dsn.wrapper, save)
    form.onsubmit = event => {
      event.preventDefault()
      void run(async () => {
        const body = { name: name.input.value.trim(), database: database.input.value.trim(), type: 'starrocks',
          ...(dsn.input.value ? { dsn: dsn.input.value } : {}),
          ...(id ? { expectedVersion: detail!.draft.version, metadataVersionId: detail!.draft.metadata_version_id }
            : { sourceId: identity.input.value.trim() }) }
        await officeRequest(id ? `${base}/draft` : '/admin/data-sources', id ? 'PUT' : 'POST', body)
        dsn.input.value = ''
        await edit(id ?? identity.input.value.trim())
      })
    }
    content.append(form)
    if (!id || !detail) return
    const access = await officeRequest<TableAccess>(`${base}/table-access`)
    content.append(node('h3', '数据表范围'), node('p', `草稿 ${access.draftTables.length} 张表 · 已发布 ${access.publishedTables.length} 张表`),
      button('发现数据库中的表', async () => {
        await officeRequest(`${base}/table-discoveries`, 'POST', { expectedVersion: detail.draft.version })
        await edit(id)
      }))
    if (access.discoveryId) {
      const tables: Table[] = []
      let offset = 0, total = 1
      while (offset < total) {
        const page = await officeRequest<{ items: Table[]; total: number }>(
          `${base}/table-discoveries/${enc(access.discoveryId)}/tables?offset=${offset}&limit=100`)
        tables.push(...page.items); total = page.total; offset += page.items.length
        if (!page.items.length) break
      }
      const selection = choices(tables.map(key), access.draftTables.map(key))
      content.append(selection.container, button('保存表范围', async () => {
        const selected = new Set(selection.values())
        if (selected.size > 200) throw new Error('每次最多选择 200 张表。')
        await officeRequest(`${base}/table-access`, 'PUT', {
          expectedDraftVersion: access.draftVersion, discoveryId: access.discoveryId,
          selectedTables: tables.filter(table => selected.has(key(table))).map(({ database, name }) => ({ database, name })),
        })
        await edit(id)
      }))
    }
    content.append(button('检查发布', async () => {
      const check = await officeRequest<{ canPublish: boolean; issues: { message: string }[];
        warnings: unknown[]; tableAccessChanges: { added: string[]; removed: string[] } }>(
        `${base}/release-check?expectedVersion=${detail.draft.version}`)
      const review = node('section')
      review.append(node('h3', '发布预览'), node('p', `新增 ${check.tableAccessChanges.added.join('、') || '无'}；移除 ${check.tableAccessChanges.removed.join('、') || '无'}`))
      for (const issue of check.issues) review.append(node('p', issue.message))
      for (const warning of check.warnings) review.append(node('p', typeof warning === 'string' ? warning : JSON.stringify(warning)))
      if (check.canPublish) review.append(button('发布此版本', async () => {
        await officeRequest(`${base}/publish`, 'POST', { expectedVersion: detail.draft.version })
        await edit(id)
      }))
      else review.append(node('p', '当前草稿没有可发布的变化，或仍有问题需要处理。'))
      content.append(review)
    }))
  }

  async function grants(id: string) {
    const [spaces, access] = await Promise.all([
      officeRequest<{ items: OfficeSpace[] }>('/admin/workspaces'),
      officeRequest<TableAccess>(`/admin/data-sources/${enc(id)}/table-access`),
    ])
    content.replaceChildren(button('返回数据源', list), node('h3', '授权给工作区'))
    const select = node('select'); select.setAttribute('aria-label', '授权工作区')
    for (const space of spaces.items) {
      const option = node('option', `${space.name}${space.personal_user ? `（个人：${space.personal_user}）` : ''}`)
      option.value = space.id; select.append(option)
    }
    const area = node('div')
    async function showGrant() {
      area.replaceChildren()
      if (!select.value) return
      const path = `/admin/workspaces/${enc(select.value)}/data-sources/${enc(id)}`
      const grant = await officeRequest<{ tables: string[] }>(path)
      if (access.publishedTables.length) {
        const selection = choices(access.publishedTables.map(key), grant.tables)
        area.append(selection.container, button('保存工作区授权', async () => {
          await officeRequest(path, 'PUT', { tables: selection.values() })
          await showGrant()
        }))
      } else {
        area.append(node('p', '尚无已发布的数据表，请先选择表范围并发布数据源。'))
      }
      if (grant.tables.length) {
        area.append(button('撤销此工作区授权', async () => {
          await officeRequest(path, 'PUT', { tables: [] })
          await showGrant()
        }))
      }
    }
    select.onchange = () => void run(showGrant)
    content.append(select, area); await showGrant()
  }

  async function available() {
    if (!options.space) { content.append(node('p', '请先选择工作区。')); return }
    content.append(button('刷新数据源', list))
    const base = `/workspaces/${enc(options.space.id)}/data-sources`
    const result = await officeRequest<{ items: { id: string; name?: string; tables?: string[]; available: boolean; reason?: string }[] }>(base)
    if (!result.items.length) content.append(node('p', '当前工作区尚未获授数据源，请联系公司管理员。'))
    for (const source of result.items) {
      const section = node('section')
      section.append(node('h3', source.name ?? source.id))
      if (!source.available) section.append(node('p', source.reason ?? '数据源不可用'))
      else {
        section.append(node('p', `可访问表：${source.tables!.join('、')}`))
        const sql = node('textarea'); sql.rows = 4; sql.setAttribute('aria-label', `${source.name}只读 SQL`)
        sql.placeholder = '输入只读 SELECT 查询'
        sql.value = queryDrafts.get(source.id) ?? ''
        sql.oninput = () => queryDrafts.set(source.id, sql.value)
        const output = node('div'); output.className = 'source-query-result'
        section.append(sql, button('执行查询', async () => {
          output.replaceChildren()
          queryDrafts.set(source.id, sql.value)
          const result = await officeRequest<{ columns: string[]; rows: unknown[][]; source: { queryId: string } }>(
            `${base}/${enc(source.id)}/query`, 'POST', { sql: sql.value }).catch(async error => {
              if (panel.open && error instanceof OfficeRequestError && [403, 409].includes(error.status)) {
                await list().catch(() => { /* Keep the refresh button and report the original query error. */ })
              }
              throw error
            })
          const table = node('table'), head = node('tr')
          result.columns.forEach(column => head.append(node('th', column))); table.append(head)
          for (const row of result.rows.slice(0, 200)) {
            const tr = node('tr'); row.forEach(value => tr.append(node('td', value === null ? '' : String(value)))); table.append(tr)
          }
          output.replaceChildren(node('p', `返回 ${result.rows.length} 行，预览前 200 行。查询编号：${result.source.queryId}`), table)
        }), output)
      }
      if (options.space.role === 'owner') section.append(button('成员表权限', async () => memberLimits(source.id)))
      content.append(section)
    }
  }

  async function memberLimits(source: string, edits = new Map<string, Map<string, boolean>>()) {
    const base = `/workspaces/${enc(options.space!.id)}`
    const [members, limits] = await Promise.all([
      officeRequest<{ items: { user: string; name: string }[] }>(`${base}/members`),
      officeRequest<{ tables: string[]; items: { user: string; tables: string[] }[] }>(`${base}/data-sources/${enc(source)}/members`),
    ])
    content.replaceChildren(button('返回数据源', list), node('h3', '成员数据表权限'))
    const memberSelections = new Map<string, { saved: string[]; values: () => string[] }>()
    async function updateMember(user: string, tables: string[] | null) {
      const path = `${base}/data-sources/${enc(source)}/members/${enc(user)}`
      await officeRequest(path, 'PUT', { tables })
      const remaining = new Map<string, Map<string, boolean>>()
      for (const [member, selection] of memberSelections) {
        if (member === user) continue
        const selected = new Set(selection.values())
        const saved = new Set(selection.saved)
        const changes = new Map<string, boolean>()
        for (const table of limits.tables) {
          if (selected.has(table) !== saved.has(table)) changes.set(table, selected.has(table))
        }
        if (changes.size) remaining.set(member, changes)
      }
      await memberLimits(source, remaining)
    }
    for (const member of members.items) {
      const current = limits.items.find(item => item.user === member.user)
      const allowedTables = current ? limits.tables.filter(table => current.tables.includes(table)) : limits.tables
      const changes = edits.get(member.user)
      const selection = choices(limits.tables, limits.tables.filter(table => changes?.get(table) ?? allowedTables.includes(table)))
      memberSelections.set(member.user, { saved: allowedTables, values: selection.values })
      const scope = current ? '自定义范围' : '继承工作区范围'
      const count = allowedTables.length ? `${allowedTables.length} 张表` : '无可访问表'
      const section = node('section')
      section.append(node('h4', member.name), node('p', `${scope} · ${count}`), selection.container,
        button('保存成员范围', () => updateMember(member.user, selection.values())),
        button('继承工作区范围', () => updateMember(member.user, null)))
      content.append(section)
    }
  }
  await run(list)
}
