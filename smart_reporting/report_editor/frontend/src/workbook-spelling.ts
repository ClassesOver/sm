import { buttonClasses } from './button'
import { createModal } from './modal'
import { collectWorkbookTextCells, replaceSuggestion, type SpellFinding, type SpellSnapshot } from './vendor/genoffice-sheets-spelling/spell-check'
import { loadLearnedWords, saveLearnedWords } from './vendor/genoffice-sheets-spelling/spellcheck-pref'

export function planWorkbookSpellingReplacements(data: SpellSnapshot, findings: SpellFinding[], suggestion: string,
  protectedSheet: (id: string) => boolean) {
  const groups = new Map<string, { subUnitId: string; count: number; value: Record<number, Record<number, { v: string }>> }>()
  for (const { cell, word } of findings) {
    const sheet = data.sheets[cell.sheetId]
    const current = sheet?.cellData?.[String(cell.row)]?.[String(cell.column)]
    if (sheet?.name !== cell.sheetName || !current || current.v !== cell.text || current.f ||
        (current as { si?: unknown }).si || current.p || protectedSheet(cell.sheetId)) {
      throw new Error(`${cell.address} 的文本已变化、含特殊格式或受保护，请重新检查。`)
    }
    const next = replaceSuggestion(cell.text, word, suggestion)
    if (next === cell.text) continue
    const group = groups.get(cell.sheetId) ?? { subUnitId: cell.sheetId, count: 0, value: {} }
    const row = group.value[cell.row] ??= {}
    if (!row[cell.column]) group.count++
    row[cell.column] = { v: next }
    groups.set(cell.sheetId, group)
  }
  if (!groups.size) throw new Error('没有可更正的单元格，请重新检查。')
  return [...groups.values()]
}

export function createWorkbookSpelling(root: HTMLElement, options: {
  snapshot(): { data: SpellSnapshot; sheets: { sheetId: string; sheetName: string }[] } | undefined
  jump(finding: SpellFinding): void
  editable(): boolean
  replace(findings: SpellFinding[], suggestion: string): Promise<number>
}) {
  const modal = createModal({
    root, label: '拼写检查', closeLabel: '关闭拼写检查', variant: 'wide', onRequestClose: close,
    content: '<h2>拼写检查</h2><p role="status"></p><select aria-label="疑似错误" size="7" hidden></select><div data-spell-actions></div><button type="button" data-spell-recheck>重新检查</button>',
  })
  const status = modal.card.querySelector<HTMLElement>('[role="status"]')!
  const list = modal.card.querySelector<HTMLSelectElement>('select')!
  const actions = modal.card.querySelector<HTMLElement>('[data-spell-actions]')!
  const recheck = modal.card.querySelector<HTMLButtonElement>('[data-spell-recheck]')!
  recheck.className = buttonClasses('secondary')
  const ignored = new Set<string>()
  let learned = new Set<string>(), findings: SpellFinding[] = [], worker: Worker | undefined, run = 0, replacing = false

  function render(message?: string) {
    const entries = document.createDocumentFragment()
    for (const [index, entry] of findings.entries()) {
      entries.append(new Option(`${entry.cell.sheetName}!${entry.cell.address} · ${entry.word} · ${entry.cell.text.slice(0, 90)}`, String(index)))
    }
    list.replaceChildren(entries)
    list.selectedIndex = -1
    list.hidden = !findings.length
    actions.replaceChildren()
    status.textContent = message ?? (findings.length ? `${findings.length} 处疑似拼写错误，选择一项可定位。` : '未发现疑似拼写错误。')
  }

  function scan() {
    const pass = ++run
    findings = []
    render('正在本地检查拼写…')
    const snapshot = options.snapshot()
    if (!snapshot) { render('工作簿尚未就绪。'); return }
    learned = new Set(loadLearnedWords().map(word => word.toLowerCase()))
    const { cells, truncated } = collectWorkbookTextCells(snapshot.data, snapshot.sheets)
    try {
      worker ??= new Worker(new URL('./workbook-spelling-worker.ts', import.meta.url), { type: 'module' })
      worker.onmessage = (event: MessageEvent<{ run: number; findings?: SpellFinding[]; failed?: boolean }>) => {
        if (event.data.run !== pass || pass !== run) return
        findings = event.data.findings ?? []
        render(event.data.failed ? '此窗口无法使用拼写检查。'
          : truncated ? `已检查部分文本单元格，发现 ${findings.length} 处疑似拼写错误。` : undefined)
      }
      worker.onerror = () => {
        if (pass !== run) return
        worker?.terminate()
        worker = undefined
        render('此窗口无法使用拼写检查。')
      }
      worker.postMessage({ run: pass, cells, learned: [...learned], ignored: [...ignored] })
    } catch { render('此窗口无法使用拼写检查。') }
  }

  function button(label: string, action: () => void, disabled = false) {
    const element = document.createElement('button')
    element.type = 'button'
    element.className = buttonClasses('secondary')
    element.textContent = label
    element.disabled = disabled
    element.onclick = action
    actions.append(element)
  }

  async function replace(next: SpellFinding[], suggestion: string) {
    if (replacing) return
    replacing = true
    const pass = run
    for (const button of actions.querySelectorAll('button')) button.disabled = true
    try {
      const count = await options.replace(next, suggestion)
      if (pass !== run) return
      findings = findings.filter(finding => !next.includes(finding))
      render(`已更正 ${count} 处，修改尚未保存。`)
    } catch (error) {
      if (pass === run) render(error instanceof Error ? error.message : '更正失败，请重新检查。')
    } finally { replacing = false }
  }

  list.onchange = () => {
    actions.replaceChildren()
    const finding = findings[list.selectedIndex]
    if (!finding) return
    options.jump(finding)
    const word = finding.word.toLowerCase()
    button('忽略', () => { findings = findings.filter(item => item !== finding); render() })
    button('全部忽略', () => {
      ignored.add(word)
      findings = findings.filter(item => item.word.toLowerCase() !== word)
      render()
    })
    button('加入词典', () => {
      learned.add(word)
      saveLearnedWords([...learned])
      findings = findings.filter(item => item.word.toLowerCase() !== word)
      render()
    })
    for (const suggestion of finding.suggestions) {
      const disabled = !options.editable() || replacing
      button(suggestion, () => void replace([finding], suggestion), disabled)
      button(`全部替换为“${suggestion}”`, () => void replace(
        findings.filter(item => item.word === finding.word), suggestion,
      ), disabled)
    }
    if (!finding.suggestions.length) actions.append('无修改建议')
  }
  recheck.onclick = scan
  function close() {
    run++
    worker?.terminate()
    worker = undefined
    modal.close()
  }
  return { open() { modal.open(recheck); scan() }, close, dispose() { close(); modal.remove() } }
}
