/// 名称管理器（Formulas ▸ 定义的名称）：Name Manager 对话框、Define Name
/// 快速定义、Use in Formula 插入，以及保存差分 → applyDefinedNames 协议。
///
/// 固定源对照（genoffice-source-full f8c17004）：
/// - apps/sheets/src/renderer/NameManagerDialog.tsx：列表/新建/编辑（名称、
///   引用）/删除；scope 在创建时选择且此后不可改。
/// - apps/sheets/src/renderer/App.tsx handleDefinedNameAction：add 走
///   newDefinedNameBuilder + insertDefinedNameBuilder，update 走
///   setName/setRef，remove 走 delete()；ref 去掉前导 "="。
/// - apps/sheets/src/renderer/ExcelShell.tsx：use-in-formula:<name> 仅在活动
///   单元格为空时写入 =<name>，拒绝覆盖已有内容。
///
/// 本地差异（诚实标注）：写盘协议 applyDefinedNames 只支持工作簿级全局名
/// （xlsx-engine defined-names.ts 明确把 localSheetId 条目留给 page-setup），
/// 读模型 readDefinedNames 也只读全局名，因此对话框省略固定源的工作表 scope
/// 下拉，仅提供工作簿 scope；工作表级名称不读取也不改写，保持原样落盘。

import { isValidDefinedName } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'

/// Univer FWorkbook.getDefinedNames() 对工作簿 scope 返回的字面量
/// （@univerjs/sheets SCOPE_WORKBOOK_VALUE_DEFINED_NAME）。
const WORKBOOK_SCOPE = 'AllDefaultWorkbook'

export interface DefinedNameRow {
  readonly name: string
  /// 引用或公式文本，按 workbook.xml 存储形式（无前导 "="）。
  readonly refersTo: string
}

export type DefinedNameAction =
  | { kind: 'add'; name: string; ref: string }
  | { kind: 'update'; originalName: string; name: string; ref: string }
  | { kind: 'remove'; name: string }

export interface DefinedNameFacadeEntry {
  getName(): string
  getFormulaOrRefString(): string
  getLocalSheetId?(): string | undefined
  setName(name: string): unknown
  setRef(ref: string): unknown
  delete(): unknown
}

export interface DefinedNameWorkbook {
  getDefinedNames(): DefinedNameFacadeEntry[]
  newDefinedNameBuilder(): { setName(name: string): { setRef(ref: string): { build(): unknown } } }
  insertDefinedNameBuilder(param: unknown): unknown
}

const isWorkbookScope = (entry: { getLocalSheetId?(): string | undefined }): boolean => {
  const scope = entry.getLocalSheetId?.()
  return scope === undefined || scope === WORKBOOK_SCOPE
}

export const normalizeRefersTo = (ref: string): string => ref.replace(/^=/, '').trim()

/// 实时读取工作簿级 defined names（FUniver getDefinedNames facade；
/// 工作表级与 _xlnm. 保留名条目排除——它们由 page-setup 维护，不可经此改写）。
/// facade 缺少 getDefinedNames（版本方差/测试桩）时返回 undefined：调用方
/// 必须跳过差分，绝不能把"读不到"当成"已全部删除"。
export function liveDefinedNames(workbook: DefinedNameWorkbook | null | undefined): DefinedNameRow[] | undefined {
  if (typeof workbook?.getDefinedNames !== 'function') return undefined
  const entries = workbook.getDefinedNames() ?? []
  return entries.flatMap(entry => {
    const name = entry.getName?.()
    const refersTo = entry.getFormulaOrRefString?.()
    if (!name || refersTo === undefined || !isWorkbookScope(entry) || name.startsWith('_xlnm.')) return []
    return [{ name, refersTo: normalizeRefersTo(refersTo) }]
  })
}

export interface DefinedNamesPlan {
  sets?: readonly { name: string; refersTo: string }[]
  removes?: readonly string[]
}

/// baseline（workbook.xml 全局名，currentModel.definedNames）与实时状态的差分。
/// 名字按大小写不敏感判重（Excel 语义）；同名换引用时按 baseline 原名原地替换，
/// 避免引擎精确大小写 replace 在 workbook.xml 留下旧条目；纯大小写改名不产生
/// 操作（引擎无法在同一次 plan 中既删又设同名）。baseline 中引擎无法校验的
/// 非法名（含 _xlnm.）保持不动。
export function definedNamesPlan(baseline: readonly DefinedNameRow[], live: readonly DefinedNameRow[]): DefinedNamesPlan {
  const baselineMap = new Map(baseline.map(row => [row.name.toLowerCase(), row]))
  const liveKeys = new Set<string>()
  const sets: { name: string; refersTo: string }[] = []
  for (const row of live) {
    const key = row.name.toLowerCase()
    if (liveKeys.has(key)) continue
    liveKeys.add(key)
    if (!isValidDefinedName(row.name)) continue
    const before = baselineMap.get(key)
    if (!before) sets.push({ name: row.name, refersTo: row.refersTo })
    else if (before.refersTo !== row.refersTo) sets.push({ name: before.name, refersTo: row.refersTo })
  }
  const removes = baseline.flatMap(row =>
    liveKeys.has(row.name.toLowerCase()) || !isValidDefinedName(row.name) ? [] : [row.name])
  return {
    ...(sets.length ? { sets } : {}),
    ...(removes.length ? { removes } : {}),
  }
}

export function definedNamesPlanOperation(
  baseline: readonly DefinedNameRow[],
  live: readonly DefinedNameRow[],
): { kind: 'applyDefinedNames'; plan: DefinedNamesPlan } | undefined {
  const plan = definedNamesPlan(baseline, live)
  return (plan.sets?.length ?? 0) + (plan.removes?.length ?? 0) > 0
    ? { kind: 'applyDefinedNames', plan }
    : undefined
}

/// Excel 引用转义：含非 [A-Za-z0-9_] 的工作表名用单引号包裹，内部引号翻倍。
const quoteSheetName = (name: string): string =>
  /^[A-Za-z0-9_]+$/.test(name) ? name : `'${name.replace(/'/g, "''")}'`

const columnLabel = (index: number): string => {
  let label = ''
  for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) {
    label = String.fromCharCode(65 + ((value - 1) % 26)) + label
  }
  return label
}

/// Define Name 快速定义：当前选区 → 含工作表名的绝对地址（$A$1:$B$9，0 基行）。
export function absoluteRangeRef(
  sheetName: string,
  startRow: number, startColumn: number, endRow: number, endColumn: number,
): string {
  const cell = (row: number, column: number): string => `$${columnLabel(column)}$${row + 1}`
  const range = startRow === endRow && startColumn === endColumn
    ? cell(startRow, startColumn)
    : `${cell(startRow, startColumn)}:${cell(endRow, endColumn)}`
  return `${quoteSheetName(sheetName)}!${range}`
}

/// 对话框动作 → Univer defined-name 命令（固定源 handleDefinedNameAction 语义）。
/// 返回错误消息，成功返回 null；应用后按实时状态判定是否生效（facade 吞掉
/// syncExecuteCommand 的同步返回值，与缩放/冻结的判定方式一致）。
export function applyDefinedNameAction(
  workbook: DefinedNameWorkbook | null,
  action: DefinedNameAction,
  live: readonly DefinedNameRow[],
): string | null {
  const name = action.name.trim()
  const ref = action.kind === 'remove' ? '' : normalizeRefersTo(action.ref)
  if (!name) return '名称不能为空。'
  if (!isValidDefinedName(name)) {
    return `名称 "${name}" 不合法：须以字母、下划线或中文开头，不能形如单元格地址，不能使用 _xlnm. 前缀。`
  }
  if (action.kind !== 'remove') {
    if (!ref) return '引用不能为空。'
    if (ref.length > 500) return `引用过长（${ref.length} 字符，上限 500）。`
  }
  const lower = name.toLowerCase()
  const kept = action.kind === 'update' ? action.originalName : name
  const collision = live.find(row => row.name !== kept && row.name.toLowerCase() === lower)
  if (collision) return `名称 "${name}" 与已有名称 "${collision.name}" 冲突（名称大小写不敏感）。`
  if (!workbook) return '工作簿尚未就绪。'
  try {
    if (action.kind === 'add') {
      workbook.insertDefinedNameBuilder(workbook.newDefinedNameBuilder().setName(name).setRef(ref).build())
    } else {
      const originalName = action.kind === 'update' ? action.originalName : action.name
      const target = workbook.getDefinedNames().find(entry => entry.getName() === originalName && isWorkbookScope(entry))
      if (!target) return '该名称已不存在，请刷新列表后重试。'
      if (action.kind === 'remove') target.delete()
      else {
        if (name !== action.originalName) target.setName(name)
        target.setRef(ref)
      }
    }
  } catch (error) {
    return (error as Error).message || '定义名称未应用。'
  }
  const after = liveDefinedNames(workbook) ?? []
  const applied = action.kind === 'remove'
    ? !after.some(row => row.name.toLowerCase() === lower)
    : after.some(row => row.name.toLowerCase() === lower && row.refersTo === ref)
  return applied ? null : '定义名称未应用（名称或引用状态未变化）。'
}

/// 名称管理器对话框（createModal 款，复用既有 token/类，不新增 CSS）：
/// 列表 + 新建/更新/删除（编辑限制与固定源一致：scope 创建后不可改，本地仅
/// 工作簿 scope）。列表显示 "名称 → 引用"。
export function createNameManagerDialog(
  root: HTMLElement,
  options: {
    rows(): DefinedNameRow[]
    apply(action: DefinedNameAction): string | null
  },
) {
  const modal = createModal({
    root,
    label: '名称管理器',
    cardClass: 'workbook-ribbon-note-dialog',
    closeLabel: '关闭名称管理器',
    content: `
      <h2>名称管理器</h2><form class="workbook-ribbon-note-form">
        <label>已定义名称<select class="workbook-ribbon-select workbook-defined-name-list" size="6" style="width:100%" aria-label="已定义名称"></select></label>
        <p class="workbook-ribbon-note-author">范围：工作簿（工作表级名称由页面设置维护，此处不显示、不可改）</p>
        <label>名称<input class="workbook-ribbon-format-code workbook-defined-name-name" maxlength="255" autocomplete="off" spellcheck="false" placeholder="MyRange"></label>
        <label>引用<input class="workbook-ribbon-format-code workbook-defined-name-ref" maxlength="500" autocomplete="off" spellcheck="false" placeholder="Sheet1!$A$1:$B$9"></label>
        <p class="workbook-defined-name-error" role="alert"></p>
        <div class="workbook-ribbon-note-actions">
          <button type="button" class="workbook-defined-name-delete" disabled>删除</button>
          <button type="button" class="workbook-defined-name-update" disabled>更新</button>
          <button type="button" class="workbook-defined-name-add">新建</button>
        </div>
      </form>`,
  })
  const list = modal.card.querySelector<HTMLSelectElement>('.workbook-defined-name-list')!
  const nameInput = modal.card.querySelector<HTMLInputElement>('.workbook-defined-name-name')!
  const refInput = modal.card.querySelector<HTMLInputElement>('.workbook-defined-name-ref')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const addButton = modal.card.querySelector<HTMLButtonElement>('.workbook-defined-name-add')!
  const updateButton = modal.card.querySelector<HTMLButtonElement>('.workbook-defined-name-update')!
  const deleteButton = modal.card.querySelector<HTMLButtonElement>('.workbook-defined-name-delete')!
  let selected: string | null = null

  const rows = (): DefinedNameRow[] => options.rows()
  const syncButtons = () => {
    updateButton.disabled = selected === null
    deleteButton.disabled = selected === null
  }
  const renderRows = () => {
    const current = rows()
    list.replaceChildren(...(current.length
      ? current.map(row => {
          const option = document.createElement('option')
          option.value = row.name
          option.textContent = `${row.name} → ${row.refersTo}`
          return option
        })
      : [Object.assign(document.createElement('option'), { value: '', textContent: '（暂无定义名称）', disabled: true })]))
    selected = null
    syncButtons()
  }
  const run = (action: DefinedNameAction) => {
    const failure = options.apply(action)
    error.textContent = failure ?? ''
    if (failure === null) {
      nameInput.value = ''
      refInput.value = ''
      renderRows()
    }
  }

  list.addEventListener('change', () => {
    const row = rows().find(item => item.name === list.value) ?? null
    selected = row?.name ?? null
    nameInput.value = row?.name ?? ''
    refInput.value = row?.refersTo ?? ''
    error.textContent = ''
    syncButtons()
  })
  addButton.addEventListener('click', () => {
    if (nameInput.value.trim() === '' || refInput.value.trim() === '') {
      error.textContent = '请填写名称和引用。'
      return
    }
    run({ kind: 'add', name: nameInput.value.trim(), ref: refInput.value.trim() })
  })
  updateButton.addEventListener('click', () => {
    if (selected === null) return
    run({ kind: 'update', originalName: selected, name: nameInput.value.trim(), ref: refInput.value.trim() })
  })
  deleteButton.addEventListener('click', () => {
    if (selected === null) return
    run({ kind: 'remove', name: selected })
  })
  return {
    open(initial?: { ref?: string }) {
      error.textContent = ''
      renderRows()
      nameInput.value = ''
      refInput.value = initial?.ref ?? ''
      modal.open(initial?.ref ? nameInput : list)
    },
    dispose: modal.remove,
  }
}
