import { createModal } from './modal'
import { readWorkbookQueries, type WorkbookQuery } from './workbook-queries-reader'
import './workbook-queries.css'

export interface WorkbookQueriesOptions {
  getWorkbook: () => object | null | undefined
  getBytes: () => Uint8Array | Promise<Uint8Array>
  onGo: (reference: string) => string | null | Promise<string | null>
  isBlocked?: () => boolean
}
const kinds = { powerQuery: 'Power Query', web: 'Web', text: '文本', database: '数据库', other: '其他连接' }

/** 固定源 QueriesDialog 的只读面板；来源见 workbook-vendor/SOURCE.md。 */
export function createWorkbookQueriesDialog(host: HTMLElement, options: WorkbookQueriesOptions) {
  let generation = 0, disposed = false, identity: object | undefined
  const close = () => { generation++; modal.close() }
  const modal = createModal({ root: host, label: '查询与连接', closeLabel: '关闭查询与连接', cardClass: 'workbook-queries-dialog', onRequestClose: close, content: '<header><h2>查询与连接</h2></header><p data-query-loading>正在读取查询与连接…</p><p data-query-empty hidden>此工作簿没有查询或数据连接。</p><ul data-query-list></ul><p data-query-note>只读查看来源文件中的连接元数据；此处不执行或刷新查询。连接定义将保留在文件中供 Excel 使用。</p><p role="alert" hidden></p><footer><button type="button" data-query-close>关闭</button></footer>' })
  const list = modal.card.querySelector<HTMLUListElement>('[data-query-list]')!, loading = modal.card.querySelector<HTMLElement>('[data-query-loading]')!, empty = modal.card.querySelector<HTMLElement>('[data-query-empty]')!, error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  const showError = (message: string) => { error.textContent = message; error.hidden = false }
  const current = (token: number) => !disposed && generation === token && !modal.overlay.hidden && options.getWorkbook() === identity && !options.isBlocked?.()
  const render = (queries: WorkbookQuery[], token: number) => {
    empty.hidden = queries.length > 0
    queries.forEach((query, index) => {
      const row = document.createElement('li'), button = document.createElement('button'), name = document.createElement('strong'), detail = document.createElement('span'), destination = query.destination
      button.type = 'button'; button.dataset.queryEntry = String(index); button.disabled = !destination
      name.textContent = query.name
      const ref = destination ? `'${destination.sheet.replaceAll("'", "''")}'!${destination.range}` : undefined
      detail.textContent = [kinds[query.kind], destination ? `${destination.rows} 行已加载到 ${destination.table ?? destination.sheet}（${ref}）` : '仅连接', query.source].filter(Boolean).join(' · ')
      if (query.description) button.title = query.description
      button.append(name, detail); row.append(button); list.append(row)
      button.addEventListener('click', () => {
        if (!current(token)) { showError('工作簿状态已变化，请重新打开查询与连接'); return }
        if (!ref) return
        void (async () => {
          const failure = await options.onGo(ref)
          if (!current(token)) return
          if (failure) showError(failure)
          else close()
        })().catch(reason => { if (current(token)) showError(reason instanceof Error ? reason.message : String(reason)) })
      })
    })
  }
  modal.card.querySelector('[data-query-close]')!.addEventListener('click', close)
  return {
    async open() {
      if (disposed || options.isBlocked?.()) return
      const workbook = options.getWorkbook()
      if (!workbook) return
      const token = ++generation; identity = workbook
      list.replaceChildren(); loading.hidden = false; empty.hidden = true; error.hidden = true; modal.open()
      try {
        const bytes = await options.getBytes()
        if (!current(token)) return
        const queries = await readWorkbookQueries(bytes)
        if (current(token)) render(queries, token)
      } catch (reason) {
        if (current(token)) showError(`无法读取查询与连接：${reason instanceof Error ? reason.message : String(reason)}`)
      } finally { if (!disposed && generation === token) loading.hidden = true }
    },
    close,
    dispose() { if (disposed) return; disposed = true; generation++; modal.remove(); identity = undefined },
  }
}
