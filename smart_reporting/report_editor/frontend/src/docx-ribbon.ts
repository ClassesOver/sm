import { fillDocxCommandIcons } from './docx-command-icons'
import { bindOfficeRibbonScroll } from './office-ribbon-scroll'
import { createDocxCellBorderUiState, createDocxCellBordersControls } from './docx-cell-borders-controls'
import type { DocxTocControls } from './docx-toc'
import { docxFontPickAttrs } from '../../../reporting/doc_engine/bridge/docx-font-slots'
import { DocxNotesSource, type DocxNotesController } from './docx-notes-source'
import { applyDocxClearFormatting, docxClearFormattingUnavailable } from './docx-clear-formatting'
import { applyDocxCase, docxCaseUnavailable } from './docx-case'
import type { CaseMode } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/case-transform'
import { applyParagraphBorders, paragraphBorders, paragraphBordersTarget } from './docx-borders'
import { applyParagraphHighlight, highlightTarget, selectedHighlight, textFormattingRange } from './docx-highlight'
import { applyParagraphShading, paragraphShading, paragraphShadingTarget, DOCX_SHADING_COLORS } from './docx-shading'
import { applyDocxCellShading, docxCellShadingUnavailable } from './docx-cell-shading'
import { createParagraphStyleControl } from './docx-styles'
import type { DocxViewCommands } from './docx-view'
import { selectedVerticalAlign, toggleParagraphVerticalAlign, verticalAlignTarget } from './docx-vertical'
import { TABLE_ACTIONS, type DocxTableCommands } from './docx-tables'
import { createRoot } from 'react-dom/client'
import { createElement } from 'react'
import { flushSync } from 'react-dom'
import { IconComments, IconComment, IconToc, IconRefresh } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import type { Editor } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import { DocxHomeSource } from './docx-home-source'
import { createDocxPainter, docxClipboardCopy, docxClipboardCut, docxClipboardPaste, type DocxPasteMode } from './docx-clipboard'
import { docxLineSpacingUnavailable, openDocxLineSpacingDialog } from './docx-line-spacing'
import { docxSpecialIndentUnavailable, openDocxSpecialIndentDialog } from './docx-special-indent'
import type { DocxAnchor, SectionValues } from './docx-operations'
import { DocxInsertSource } from './docx-insert-source'
import { DocxLayoutSource } from './docx-layout-source'
import { DocxHeaderFooterSource, type DocxHeaderFooterController } from './docx-hf-source'
import type { SectionSettings } from '@genoffice/docx-engine'
import { effectiveBidi, setSelectionAlign } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/direction'
import { DOCX_WATERMARK_PRESETS, type DocxWatermarkModel, type DocxWatermarkSpec } from './docx-watermark'
import { openDocxWatermarkDialog } from './docx-watermark-dialog'

const tabs = [
  { id: 'file', label: '文件' }, { id: 'home', label: '开始' }, { id: 'insert', label: '插入' },
  { id: 'draw', label: '绘图' }, { id: 'design', label: '设计' }, { id: 'layout', label: '布局' },
  { id: 'references', label: '引用' }, { id: 'mailings', label: '邮件' }, { id: 'review', label: '审阅' }, { id: 'view', label: '视图' },
  { id: 'tableDesign', label: '表格设计', contextual: true }, { id: 'tableLayout', label: '表格布局', contextual: true },
  { id: 'pictureFormat', label: '图片格式', contextual: true }, { id: 'shapeFormat', label: '形状格式', contextual: true },
  { id: 'headerFooter', label: '页眉和页脚', contextual: true },
]
const migrating = '迁移中：当前 DOCX 保存协议不支持此命令'
const tableUnavailable = 'DOCX 表格操作尚未接入严格写回协议'
const pendingGroups: Record<string, [string, string[]][]> = {
  file: [['文件', ['打开', '保存', '另存为']]],
  draw: [['绘图工具', ['选择', '笔', '荧光笔', '橡皮擦']], ['清除', ['全部清除']]],
  design: [['文档格式', ['主题', '字体', '颜色']], ['页面背景', ['页面颜色', '水印', '页面边框']]],
  layout: [['页面设置', ['页边距', '纸张方向', '纸张大小', '分栏', '分节符']], ['段落(选中段落)', ['左缩进', '右缩进', '段前', '段后']], ['排列', ['位置', '环绕文字']]],
  references: [['Zotero', ['Zotero']], ['目录', ['目录', '更新目录']], ['脚注', ['插入脚注', '插入尾注']], ['书签', ['书签', '交叉引用']], ['引文与索引', ['插入引文', '书目', '题注', '索引']]],
  mailings: [['创建', ['信封', '标签']], ['开始邮件合并', ['开始邮件合并', '选择收件人', '编辑收件人列表']], ['编写和插入域', ['突出显示合并域', '地址块', '问候语', '插入合并域']], ['预览结果', ['预览结果', '查找收件人', '检查错误']], ['完成', ['完成并合并']]],
  review: [['校对', ['编辑器', '拼写检查']], ['语言', ['翻译']], ['批注', ['新建批注', '显示批注']], ['修订', ['修订', '显示标记', '接受', '拒绝', '上一条', '下一条']], ['保护', ['比较', '保护文档']]],
  view: [['视图', ['页面视图', 'Web 版式', '大纲', '阅读视图', '分页预览']], ['缩放', ['缩放', '缩小', '放大', '100%', '页宽', '整页']], ['显示', ['标尺', '网格线', '导航窗格']], ['外观', ['AI 面板', '深色模式']], ['窗口', ['新建标签', '拆分', '切换标签']]],
  tableDesign: [['表格样式', ['无样式', '表格样式']], ['底纹', ['单元格底纹']], ['边框', ['所有框线', '外侧框线', '内侧框线', '边框颜色', '边框粗细']]],
  tableLayout: [['删除', ['删除表格']], ['行和列', ['上方插入', '下方插入', '左侧插入', '右侧插入']], ['合并', ['合并单元格', '拆分单元格']], ['行列操作', ['删除行', '删除列']], ['对齐方式', ['顶端对齐', '垂直居中', '底端对齐']], ['单元格大小', ['行高', '列宽']], ['表格数据', ['表格属性']]],
  pictureFormat: [['调整', ['替换图片', '删除背景', '颜色', '透明度']], ['排列', ['位置', '环绕文字', '上移一层', '下移一层', '旋转', '裁剪']], ['大小', ['高度', '宽度', '重置大小']]],
  shapeFormat: [['形状样式', ['形状样式', '形状填充', '形状轮廓', '形状效果']], ['文本', ['编辑文字']], ['排列', ['位置', '环绕文字', '上移一层', '下移一层', '旋转']], ['大小', ['高度', '宽度']]],
  headerFooter: [['页眉和页脚', ['页眉', '页脚', '页码', '日期和时间', '文档信息']], ['导航', ['转到页眉', '转到页脚', '上一节', '下一节']], ['选项', ['首页不同', '奇偶页不同', '显示文档文字']], ['位置', ['页眉距顶端', '页脚距底端']], ['关闭', ['关闭页眉和页脚']]],
}
type TableRibbonCommand = { id: string; label: string }
const command = (id: string, label: string): TableRibbonCommand => ({ id, label })
const tableRibbonGroups: Record<string, [string, TableRibbonCommand[]][]> = {
  tableDesign: [
    ['表格样式', [
      command('table-style-none', '无样式'), command('table-style-grid', '网格样式'),
      command('table-style-blue-header', '蓝色标题'), command('table-style-blue-banded', '蓝色带状'),
      command('table-style-gray-banded', '灰色带状'), command('table-style-green-header', '绿色标题'),
      command('table-style-custom', '其他表格样式'),
    ]],
    ['表格样式选项', [
      command('table-look-first-row', '首行'), command('table-look-last-row', '末行'),
      command('table-look-banded-rows', '镶边行'), command('table-look-first-column', '首列'),
      command('table-look-last-column', '末列'), command('table-look-banded-columns', '镶边列'),
    ]],
    ['底纹', [command('table-cell-shading', '单元格底纹')]],
    ['边框', [
      command('table-border-apply-last', '应用最近边框'), command('table-border-bottom', '下框线'),
      command('table-border-top', '上框线'), command('table-border-left', '左框线'),
      command('table-border-right', '右框线'), command('table-border-none', '无框线'),
      command('table-border-all', '所有框线'), command('table-border-outer', '外侧框线'),
      command('table-border-inner', '内侧框线'), command('table-border-inside-horizontal', '内部横框线'),
      command('table-border-inside-vertical', '内部竖框线'), command('table-border-diagonal-down', '下斜框线'),
      command('table-border-diagonal-up', '上斜框线'), command('table-border-style', '边框样式'),
      command('table-border-width', '边框粗细'), command('table-border-color', '边框颜色'),
    ]],
  ],
  tableLayout: [
    ['选择与属性', [
      command('table-select-menu', '选择'), command('table-select-cell', '选择单元格'),
      command('table-select-column', '选择列'), command('table-select-row', '选择行'),
      command('table-select-all', '选择表格'), command('table-view-gridlines', '查看网格线'),
      command('table-properties', '表格属性'),
    ]],
    ['删除', [
      command('table-delete-menu', '删除菜单'), command('table-delete-cells', '删除单元格'),
      command('table-delete-column', '删除列'), command('table-delete-row', '删除行'),
      command('table-delete', '删除表格'),
    ]],
    ['行和列', [
      command('table-insert-row-before', '在上方插入行'), command('table-insert-row-after', '在下方插入行'),
      command('table-insert-column-before', '在左侧插入列'), command('table-insert-column-after', '在右侧插入列'),
      command('table-insert-cells', '插入单元格'),
    ]],
    ['合并', [
      command('table-merge-cells', '合并单元格'), command('table-split-cells', '拆分单元格'),
      command('table-split-table', '拆分表格'),
    ]],
    ['单元格大小', [
      command('table-row-height', '行高'), command('table-column-width', '列宽'),
      command('table-autofit-contents', '根据内容自动调整'), command('table-autofit-window', '根据窗口自动调整'),
      command('table-autofit-fixed', '固定列宽'), command('table-distribute-rows', '平均分布各行'),
      command('table-distribute-columns', '平均分布各列'),
    ]],
    ['对齐方式', [
      command('table-align-top-left', '顶端左对齐'), command('table-align-top-center', '顶端居中'),
      command('table-align-top-right', '顶端右对齐'), command('table-align-middle-left', '垂直居中左对齐'),
      command('table-align-middle-center', '垂直居中'), command('table-align-middle-right', '垂直居中右对齐'),
      command('table-align-bottom-left', '底端左对齐'), command('table-align-bottom-center', '底端居中'),
      command('table-align-bottom-right', '底端右对齐'), command('table-text-direction-horizontal', '横排文字'),
      command('table-text-direction-rotate-90', '文字旋转 90 度'), command('table-text-direction-rotate-270', '文字旋转 270 度'),
      command('table-cell-margins', '单元格边距'),
    ]],
    ['表格数据', [command('table-repeat-header-rows', '重复标题行')]],
  ],
}

/** 固定源 Design ▸ Page Color：当前值、不可用原因与选色回调（草稿写入由宿主负责）。 */
export interface DocxPageColorControls { current(): string | null; reason(): string | null; apply(color: string | null): void }
/** 固定源 Design ▸ Watermark：当前生效水印、来源模型、不可用原因与应用回调（草稿写入由宿主负责）。 */
export interface DocxWatermarkControls { current(): DocxWatermarkSpec | null; source: DocxWatermarkModel; reason(): string | null; apply(spec: DocxWatermarkSpec | null): void }

export function createDocxRibbon(editor: Editor, editable: boolean, onPaginationPreview?: () => void,
  onParagraphCommand?: (command: 'add' | 'delete') => void,
  section?: { pageNumberFmt?: string | null; pageNumberStart?: number | null; pageNumberReason?: string; settings: SectionSettings; onChange: (values: SectionValues) => void; titlePg?: boolean | null; titlePgReason?: string; evenAndOddHeaders?: boolean | null; evenAndOddHeadersReason?: string; label?: string; onSectionBreak?: (type: 'nextPage' | 'continuous' | 'evenPage' | 'oddPage') => void }, anchors: DocxAnchor[] = [], tableCommands?: DocxTableCommands, viewCommands?: DocxViewCommands, onFindReplace?: (mode: 'find' | 'replace') => void, reportError?: (error: unknown) => void, headerFooter?: DocxHeaderFooterController, notes?: DocxNotesController, noteAnchors: DocxAnchor[] = [], reviewCommands?: { open: () => void }, commentCommands?: { open: () => void; openNew?: () => void }, toc?: DocxTocControls, bookmarks?: {open:()=>void}, references?:{crossReferences:{open:()=>void};caption:{open:()=>void}}, onAssistant?: () => void, pageColor?: DocxPageColorControls, watermark?: DocxWatermarkControls): HTMLElement {
  const formattingAnchors = noteAnchors.length ? noteAnchors : anchors
  const withNotes = noteAnchors.length > 0
  const ribbon = document.createElement('div')
  ribbon.className = 'ribbon docx-ribbon'
  const disposeScroll = bindOfficeRibbonScroll(ribbon)
  const tablist = document.createElement('nav')
  tablist.className = 'ribbon-tabs'
  tablist.setAttribute('role', 'tablist')
  tablist.setAttribute('aria-label', 'Word 功能区')
  const cellBorderState = createDocxCellBorderUiState()
  let cellBorderControls: ReturnType<typeof createDocxCellBordersControls> | undefined
  let active = 'home'
  let closeLineSpacing: (() => void) | undefined
  let closeSpecialIndent: (() => void) | undefined
  const contextTabs = new Map<string, HTMLButtonElement>()
  const body = document.createElement('div')
  const refreshView = () => {
    for (const button of body.querySelectorAll<HTMLButtonElement>('[data-view-command]')) {
      button.setAttribute('aria-pressed', String(viewCommands?.active?.(button.dataset.viewCommand!) ?? false))
    }
  }
  const layout = document.createElement('div')
  let layoutRoot: ReturnType<typeof createRoot> | undefined
  let layoutParagraph: HTMLElement | undefined
  let focusedSpacingInput: HTMLInputElement | undefined
  const refreshToc = (scope: ParentNode) => {
    if (!toc) return
    for (const button of scope.querySelectorAll<HTMLButtonElement>('[data-toc-kind]')) {
      const kind = button.dataset.tocKind === 'insertToc' ? 'insertToc' : 'updateToc'
      const reason = !editable ? '当前文档不可编辑' : toc.reason(kind)
      button.disabled = reason !== null
      button.title = reason ?? '在 Word 中打开后更新域以计算页码'
      button.setAttribute('aria-description', button.title)
    }
  }
  const notesPanel = document.createElement('div')
  let notesRoot: ReturnType<typeof createRoot> | undefined
  const renderNotes = () => {
    if (!notes) return
    notesRoot ??= createRoot(notesPanel)
    flushSync(() => notesRoot!.render(createElement(DocxNotesSource, { controller: notes })))
  }
  const headerFooterPanel = document.createElement('div')
  let headerFooterRoot: ReturnType<typeof createRoot> | undefined
  let headerFooterTarget: { controller: DocxHeaderFooterController; part: 'header' | 'footer'; variant: 'default' | 'first' | 'even' } | undefined
  body.className = 'ribbon-body'
  body.setAttribute('role', 'tabpanel')
  const selectedParagraph = () => {
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) {
      const node = $from.node(depth)
      if (['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name)) return { node, pos: $from.before(depth) }
    }
  }
  const availableListLevels = (node: any): boolean[] => {
    if (node?.type.name !== 'docListItem' || !['bullet', 'ordered'].includes(node.attrs.kind)) return Array(9).fill(false)
    const defs = (editor.storage as any).listNumbering?.defs
    const definition = defs instanceof Map ? defs.get(String(node.attrs.numId)) : defs?.[String(node.attrs.numId)]
    return Array.from({ length: 9 }, (_, target) => {
      const level = definition?.levels?.[target]
      if (!level) return false
      const bullet = level.numFmt === 'bullet' || level.picBulletId != null
      return bullet === (node.attrs.kind === 'bullet')
    })
  }
  const hasListLevel = (node: any, delta: -1 | 1) => {
    const target = Number(node?.attrs?.ilvl) + delta
    return Number.isInteger(target) && target >= 0 && target <= 8 && availableListLevels(node)[target] === true
  }
  const setListLevel = (ilvl: number) => {
    const selected = selectedParagraph()
    if (!selected || selected.node.type.name !== 'docListItem' || !availableListLevels(selected.node)[ilvl]) return
    editor.view.dispatch(editor.state.tr.setNodeMarkup(selected.pos, undefined, { ...selected.node.attrs, ilvl }))
  }
  const rightIndentField = () => {
    const selected = selectedParagraph()
    const label = document.createElement('label')
    label.className = 'layout-num'
    label.setAttribute('aria-label', '段落右缩进')
    const title = document.createElement('span')
    title.textContent = '右缩进'
    const input = document.createElement('input')
    input.type = 'number'; input.inputMode = 'decimal'; input.step = '0.05'; input.min = '-720'; input.max = '720'
    input.dataset.action = 'indent-right'; input.setAttribute('aria-label', '右缩进（pt）')
    input.value = String((Number(selected?.node.attrs.indentRight) || 0) / 20)
    input.disabled = !editable || !editor.isEditable || !selected
    input.title = input.disabled ? '请先选择可编辑的正文段落' : '段落右缩进（pt）'
    let targetPosition: number | undefined
    input.addEventListener('focus', () => { targetPosition = selectedParagraph()?.pos })
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); input.blur() }
    })
    input.addEventListener('blur', event => {
      if (targetPosition !== undefined) {
        const points = Number(input.value)
        const twips = Math.round(points * 20)
        const target = editor.state.doc.nodeAt(targetPosition)
        if (Number.isFinite(points) && Number.isInteger(twips) && twips >= -14400 && twips <= 14400 && target
          && ['docParagraph', 'docHeading', 'docListItem'].includes(target.type.name)
          && twips !== (Number(target.attrs.indentRight) || 0)) {
          editor.view.dispatch(editor.state.tr.setNodeMarkup(targetPosition, undefined, { ...target.attrs, indentRight: twips || null }))
        }
      }
      targetPosition = undefined
      if (!event.relatedTarget) editor.commands.focus()
    })
    const unit = document.createElement('span')
    unit.className = 'layout-unit'; unit.textContent = 'pt'
    label.append(title, input, unit)
    return label
  }
  // Only anchored top-level paragraphs are represented by setParagraphSpacing.
  const spacingTargets = () => {
    const { from, to } = editor.state.selection
    const targets: { pos: number; node: NonNullable<ReturnType<typeof selectedParagraph>>['node']; anchor: DocxAnchor }[] = []
    let unsupported = false
    if (from === to) {
      const current = selectedParagraph()
      if (!current || editor.state.selection.$from.depth !== 1) return []
      const anchor = anchors.find(item => item.docxIndex === current.node.attrs.docxIndex)
      const sameIndexCount = editor.state.doc.content.content.filter(node => node.attrs.docxIndex === current.node.attrs.docxIndex).length
      if (!(anchor?.paragraphLayoutEditable ?? anchor?.editable) || sameIndexCount !== 1 || !anchor.blockId || !anchor.expectedObjectSha256) return []
      return [{ ...current, anchor }]
    }
    editor.state.doc.nodesBetween(from, to, (node, pos, parent) => {
      if (parent !== editor.state.doc) return false
      // A range ending at the next paragraph's text offset 0 does not include it.
      if (pos + 1 === to && from < pos) return false
      const anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex)
      const sameIndexCount = editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length
      if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name) || !(anchor?.paragraphLayoutEditable ?? anchor?.editable) || sameIndexCount !== 1
        || !anchor.blockId || !anchor.expectedObjectSha256) unsupported = true
      else targets.push({ pos, node, anchor })
      return false
    })
    return unsupported ? [] : targets
  }
  const spacingField = (action: string, title: string) => {
    const label = document.createElement('label')
    label.className = 'layout-num'
    const caption = document.createElement('span')
    caption.textContent = title
    const input = document.createElement('input')
    input.type = 'number'; input.inputMode = 'decimal'; input.step = '0.05'; input.min = '0'; input.max = '720'
    input.dataset.action = action; input.setAttribute('aria-label', `${title}（pt）`)
    const valueKey = action === 'space-before-value' ? 'spaceBefore' : 'spaceAfter'
    const autoKey = valueKey === 'spaceBefore' ? 'spaceBeforeAuto' : 'spaceAfterAuto'
    const sync = (force = false) => {
      const targets = spacingTargets()
      const first = targets[0]?.node.attrs
      const mixed = targets.some(({ node }) => node.attrs[valueKey] !== first?.[valueKey] || node.attrs[autoKey] !== first?.[autoKey])
      const automatic = first?.[autoKey] === true
      const value = first?.[valueKey]
      if (force || document.activeElement !== input) {
        input.value = mixed || automatic || value == null ? '' : String(Number(value) / 20)
        input.placeholder = mixed ? '混合' : automatic ? '自动' : '继承'
        input.dataset.spacingState = mixed ? 'mixed' : automatic ? 'auto' : value == null ? 'inherited' : 'explicit'
      }
      input.disabled = !editable || !editor.isEditable || !targets.length
      input.title = input.disabled ? '请选择已有可编辑正文段落；当前文档可能只读或正在保存' : `${title}（0–720 pt，精度 0.05 pt；空输入不修改）`
    }
    sync()
    input.addEventListener('docx-spacing-refresh', () => sync())
    let captured: { doc: typeof editor.state.doc; targets: ReturnType<typeof spacingTargets> } | undefined
    input.addEventListener('focus', () => {
      if (editable && editor.isEditable && !input.disabled) {
        focusedSpacingInput = input
        captured = { doc: editor.state.doc, targets: spacingTargets().map(target => ({ ...target, anchor: { ...target.anchor } })) }
      }
    })
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); captured = undefined; input.blur() }
      if (event.key === 'Enter') { event.preventDefault(); input.blur() }
    })
    input.addEventListener('blur', event => {
      const saved = captured
      captured = undefined
      if (saved?.targets.length && editable && editor.isEditable && !input.disabled && input.value.trim() !== '' && editor.state.doc === saved.doc) {
        const points = Number(input.value)
        const rawTwips = points * 20
        const twips = Math.round(rawTwips)
        const validTargets = saved.targets.every(({ pos, node, anchor }) => {
          const current = anchors.find(item => item.docxIndex === anchor.docxIndex)
          return editor.state.doc.nodeAt(pos) === node && (current?.paragraphLayoutEditable ?? current?.editable) && current.blockId === anchor.blockId
            && current.expectedObjectSha256 === anchor.expectedObjectSha256
        })
        if (Number.isFinite(points) && points >= 0 && points <= 720 && Math.abs(rawTwips - twips) < 1e-8 && validTargets) {
          const tr = closeHistory(editor.state.tr)
          for (const { pos, node } of saved.targets) if (node.attrs[valueKey] !== twips || node.attrs[autoKey] != null) {
            tr.setNodeMarkup(pos, undefined, { ...node.attrs, [valueKey]: twips, [autoKey]: null })
          }
          if (tr.docChanged) editor.view.dispatch(tr)
        }
      }
      // Refresh invalid/empty input as well; never retain a stale display after blur.
      sync(true)
      focusedSpacingInput = undefined
      if (!event.relatedTarget) editor.commands.focus()
    })
    const unit = document.createElement('span')
    unit.className = 'layout-unit'; unit.textContent = 'pt'
    label.append(caption, input, unit)
    return label
  }
  const renderPending = (id: string) => {
    body.replaceChildren()
    cellBorderControls = undefined
    body.setAttribute('aria-label', tabs.find(tab => tab.id === id)?.label ?? '')
    const content = document.createElement('div')
    content.className = 'ribbon-content'
    const groups = tableRibbonGroups[id] ?? (pendingGroups[id] ?? []).map(([label, commands]) =>
      [label, commands.map(commandLabel => command('', commandLabel))] as [string, TableRibbonCommand[]])
    for (const [groupLabel, commands] of groups) {
      const group = document.createElement('section')
      group.className = 'ribbon-group docx-ribbon-group'
      group.setAttribute('aria-label', groupLabel)
      const items = document.createElement('div')
      items.className = 'ribbon-group-items'
      for (const item of commands) {
        const { id: actionId, label } = item
        if (id === 'layout' && label === '右缩进') { items.append(rightIndentField()); continue }
        if (id === 'layout' && label === '段前') { items.append(spacingField('space-before-value', label)); continue }
        if (id === 'layout' && label === '段后') { items.append(spacingField('space-after-value', label)); continue }
        if (actionId.startsWith('table-border-')) {
          if (actionId === 'table-border-apply-last') {
            cellBorderControls = createDocxCellBordersControls(editor, anchors, cellBorderState, reportError)
            items.append(cellBorderControls.element)
            if (!editable) for (const control of cellBorderControls.element.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button,input,select')) control.disabled = true
          }
          continue
        }
        if (id === 'design' && label === '水印' && watermark) {
          // 固定源水印菜单：预设文字、“自定义水印…”、“删除水印”。
          const wrap = document.createElement('div'), trigger = document.createElement('button'), menu = document.createElement('div')
          wrap.className = 'rb-split-wrap'
          trigger.type = 'button'; trigger.className = 'rb-icon docx-ribbon-command'; trigger.dataset.action = 'watermark'; trigger.textContent = label
          trigger.setAttribute('aria-label', label); trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-haspopup', 'true')
          menu.className = 'layout-menu docx-watermark-menu'; menu.hidden = true; menu.dataset.rbPanel = ''; menu.setAttribute('role', 'group'); menu.setAttribute('aria-label', '水印')
          const close = () => { menu.hidden = true; trigger.setAttribute('aria-expanded', 'false') }
          const apply = (spec: DocxWatermarkSpec | null) => { try { watermark.apply(spec) } catch (error) { reportError?.(error) } close(); syncWatermark() }
          wrap.addEventListener('mousedown', event => { if (!(event.target instanceof HTMLInputElement)) event.preventDefault() })
          trigger.addEventListener('click', () => { menu.hidden = !menu.hidden; trigger.setAttribute('aria-expanded', String(!menu.hidden)) })
          for (const text of DOCX_WATERMARK_PRESETS) {
            const item = document.createElement('button'); item.type = 'button'; item.textContent = text; item.dataset.action = `watermark-preset-${text}`
            item.addEventListener('click', () => apply({ text })); menu.append(item)
          }
          const custom = document.createElement('button'); custom.type = 'button'; custom.textContent = '自定义水印…'; custom.dataset.action = 'watermark-custom'
          custom.addEventListener('click', () => { close(); openDocxWatermarkDialog(ribbon, watermark.current(), spec => apply(spec)) })
          const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '删除水印'; remove.dataset.action = 'watermark-remove'
          remove.addEventListener('click', () => apply(null))
          menu.append(custom, remove); wrap.append(trigger, menu); items.append(wrap)
          continue
        }
        if (id === 'design' && label === '页面颜色' && pageColor) {
          // 固定源 RibbonColorPalette：主题色 + 标准色 + “无颜色”；色块与单元格底纹共用同一组固定源颜色。
          const wrap = document.createElement('div'), trigger = document.createElement('button'), palette = document.createElement('div'), bar = document.createElement('span')
          wrap.className = 'rb-split-wrap'
          trigger.type = 'button'; trigger.className = 'rb-icon docx-ribbon-command docx-page-color-trigger'; trigger.dataset.action = 'page-color'
          trigger.setAttribute('aria-label', label); trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-haspopup', 'true')
          bar.className = 'docx-page-color-bar'; trigger.append(document.createTextNode(label), bar)
          palette.className = 'color-palette docx-page-color-palette'; palette.hidden = true; palette.dataset.rbPanel = ''
          palette.setAttribute('role', 'group'); palette.setAttribute('aria-label', '页面颜色')
          wrap.addEventListener('mousedown', event => event.preventDefault())
          trigger.addEventListener('click', () => { palette.hidden = !palette.hidden; trigger.setAttribute('aria-expanded', String(!palette.hidden)) })
          for (const fill of [...DOCX_SHADING_COLORS, null]) {
            const swatch = document.createElement('button')
            swatch.type = 'button'; swatch.className = fill ? 'color-swatch color-highlight-swatch' : 'color-none color-highlight-none'
            swatch.dataset.action = `page-color-${fill ?? 'none'}`; swatch.setAttribute('aria-label', fill ? `页面颜色 #${fill}` : '无页面颜色')
            if (fill) swatch.style.background = `#${fill}`; else swatch.textContent = '无颜色'
            swatch.addEventListener('click', () => {
              try { pageColor.apply(fill) } catch (error) { reportError?.(error) }
              palette.hidden = true; trigger.setAttribute('aria-expanded', 'false'); syncPageColor()
            })
            palette.append(swatch)
          }
          wrap.append(trigger, palette); items.append(wrap)
          continue
        }
        if (actionId === 'table-cell-shading') {
          const wrap = document.createElement('div'), trigger = document.createElement('button'), palette = document.createElement('div')
          wrap.className = 'rb-split-wrap'
          trigger.type = 'button'; trigger.className = 'rb-icon docx-ribbon-command'; trigger.textContent = label
          trigger.dataset.action = actionId; trigger.setAttribute('aria-label', label); trigger.setAttribute('aria-expanded', 'false')
          palette.className = 'color-palette docx-ribbon-shading-palette'; palette.hidden = true; palette.dataset.rbPanel = ''
          wrap.addEventListener('mousedown', event => event.preventDefault())
          trigger.addEventListener('click', () => { palette.hidden = !palette.hidden; trigger.setAttribute('aria-expanded', String(!palette.hidden)) })
          for (const fill of [...DOCX_SHADING_COLORS, null]) {
            const swatch = document.createElement('button')
            swatch.type = 'button'; swatch.className = fill ? 'color-swatch color-highlight-swatch' : 'color-none color-highlight-none'
            swatch.dataset.action = `${actionId}-${fill ?? 'none'}`; swatch.setAttribute('aria-label', fill ?? '无颜色')
            if (fill) swatch.style.background = `#${fill}`; else swatch.textContent = '无颜色'
            swatch.addEventListener('click', () => {
              try { applyDocxCellShading(editor, fill, anchors) } catch (error) { reportError?.(error) }
              palette.hidden = true; trigger.setAttribute('aria-expanded', 'false')
            })
            palette.append(swatch)
          }
          wrap.append(trigger, palette); items.append(wrap)
          const reason = !editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : docxCellShadingUnavailable(editor, anchors)
          trigger.disabled = reason !== null; trigger.title = reason ?? label
          continue
        }
        const command = document.createElement('button')
        command.type = 'button'
        command.className = 'rb-icon docx-ribbon-command'
        const structure = !!TABLE_ACTIONS[actionId] || ['table-repeat-header-rows', 'table-merge-cells', 'table-split-cells', 'table-column-width', 'table-distribute-columns', 'table-row-height', 'table-distribute-rows', 'table-autofit-contents', 'table-autofit-window', 'table-autofit-fixed', 'table-text-direction-horizontal', 'table-text-direction-rotate-90', 'table-text-direction-rotate-270', 'table-align-top-left', 'table-align-top-center', 'table-align-top-right', 'table-align-middle-left', 'table-align-middle-center', 'table-align-middle-right', 'table-align-bottom-left', 'table-align-bottom-center', 'table-align-bottom-right', 'table-cell-margins', 'table-properties'].includes(actionId)
        const view = id === 'view' ? viewCommands : undefined
        if(id==='references'&&references&&(label==='题注'||label==='交叉引用')) {
          command.textContent=label;command.setAttribute('aria-label',label);command.dataset.action=label==='题注'?'caption-insert':'cross-reference';command.dataset.editableAction='true';command.disabled=!editable||!editor.isEditable
          command.addEventListener('mousedown',event=>event.preventDefault());command.addEventListener('click',label==='题注'?references.caption.open:references.crossReferences.open);items.append(command);continue
        }
        if (id === 'references' && label === '书签' && bookmarks) {
          command.textContent = label; command.dataset.action = 'bookmarks'; command.setAttribute('aria-label', label)
          command.addEventListener('mousedown', event => event.preventDefault())
          command.addEventListener('click', bookmarks.open); items.append(command); continue
        }
        if (id === 'references' && groupLabel === '目录' && toc) {
          const kind = label === '更新目录' ? 'updateToc' : 'insertToc'
          const icon = document.createElement('span'), iconRoot = createRoot(icon)
          flushSync(() => iconRoot.render(createElement(kind === 'insertToc' ? IconToc : IconRefresh, { size: 20 })))
          command.append(icon.firstElementChild!.cloneNode(true)); iconRoot.unmount()
          command.append(document.createTextNode(label)); command.dataset.action = kind === 'insertToc' ? 'toc-insert' : 'toc-update'
          command.dataset.tocKind = kind
          command.addEventListener('mousedown', event => event.preventDefault())
          command.addEventListener('click', () => toc.run(kind))
          items.append(command); refreshToc(items); continue
        }
        if (id === 'review' && label === '新建批注' && commentCommands?.openNew) {
          const icon = document.createElement('span'), iconRoot = createRoot(icon)
          flushSync(() => iconRoot.render(createElement(IconComment, {size:20})))
          command.append(icon.firstElementChild!.cloneNode(true)); iconRoot.unmount()
          command.append(document.createTextNode(label)); command.dataset.action='comment-create';command.dataset.editableAction='true';command.setAttribute('aria-label',label)
          command.disabled=!editable||!editor.isEditable;command.title=label
          command.addEventListener('mousedown',event=>event.preventDefault())
          command.addEventListener('click',commentCommands.openNew);items.append(command);continue
        }
        if (id === 'review' && label === '显示批注' && commentCommands) {
          const icon = document.createElement('span'), iconRoot = createRoot(icon)
          flushSync(() => iconRoot.render(createElement(IconComments, { size: 20 })))
          command.append(icon.firstElementChild!.cloneNode(true)); iconRoot.unmount()
          command.append(document.createTextNode(label)); command.dataset.action = 'comment-text-list'; command.setAttribute('aria-label', label)
          command.title = label
          command.addEventListener('click', commentCommands.open); items.append(command); continue
        }
        const reason = view ? view.reason(label) : structure && tableCommands ? (!editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : tableCommands.reason(actionId)) : actionId ? tableUnavailable : migrating
        const available = view ? reason === null : structure && tableCommands ? reason === null : !actionId && id === 'view' && label === '分页预览' && !!onPaginationPreview
        if(actionId==='table-repeat-header-rows'||actionId?.startsWith('table-autofit-')||actionId?.startsWith('table-text-direction-')||actionId?.startsWith('table-align-'))command.setAttribute('aria-pressed',String(tableCommands?.active?.(actionId)??false))
        command.disabled = !available
        command.textContent = label
        command.title = available ? label : `${label}：${reason}`
        command.setAttribute('aria-label', available ? label : `${label}，${reason}`)
        if (!available) command.setAttribute('aria-description', reason ?? migrating)
        if (actionId) command.dataset.action = actionId
        else if (available) command.dataset.action = view && label !== '分页预览' ? `view-${label}` : 'pagination-preview'
        if (view && available && ['标尺', '导航窗格', '大纲', '页面视图', '网格线'].includes(label)) {
          command.dataset.action = label === '标尺' ? 'ruler-toggle' : label === '网格线' ? 'gridlines-toggle' : label === '导航窗格' ? 'navigation-toggle' : label === '大纲' ? 'view-outline' : 'view-page'
          command.dataset.viewCommand = label
          command.setAttribute('aria-pressed', String(view.active?.(label) ?? false))
        }
        if (structure && tableCommands) {
          command.dataset.sourceAction = actionId
          command.addEventListener('mousedown', event => event.preventDefault())
          command.addEventListener('click', () => tableCommands.run(actionId))
        } else if (view && available) {
          command.dataset.sourceAction = label === '标尺' ? 'onShowRuler' : label === '网格线' ? 'onShowGrid' : label === '导航窗格' ? 'onShowNav' : label === '大纲' || label === '页面视图' ? 'onViewMode' : label === '页宽' || label === '整页' ? 'onZoomFit' : label === '缩放' ? 'onZoomDialog' : label === '分页预览' ? 'onPagePreview' : 'onZoom'
          command.addEventListener('mousedown', event => event.preventDefault())
          command.addEventListener('click', () => { view.run(label); refreshView() })
        } else if (available) command.addEventListener('click', onPaginationPreview!)
        items.append(command)
      }
      group.append(items)
      const caption = document.createElement('div')
      caption.className = 'ribbon-group-label'
      caption.textContent = groupLabel
      group.append(caption)
      content.append(group)
    }
    if (id === 'review' && reviewCommands) {
      const group = document.createElement('section'), button = document.createElement('button')
      group.className = 'ribbon-group docx-ribbon-group'
      group.setAttribute('aria-label', '正文修订')
      button.type = 'button'; button.className = 'rb-icon docx-ribbon-command'
      button.textContent = '修订列表'; button.dataset.action = 'text-revision-list'
      button.addEventListener('click', reviewCommands.open)
      group.append(button); content.append(group)
    }
    fillDocxCommandIcons(content)
    body.append(content)
  }
  const setActive = (id: string) => {
    if (active === 'headerFooter' && id !== active) {
      headerFooter?.flushPendingEdits?.()
      headerFooterTarget = undefined
    }
    active = id
    tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]').forEach(item => {
      const selected = item.dataset.tabId === id
      item.classList.toggle('active', selected)
      item.setAttribute('aria-selected', String(selected))
      item.tabIndex = selected ? 0 : -1
    })
    if (id === 'insert') { body.replaceChildren(insert); body.setAttribute('aria-label', '插入') }
    else if (id === 'layout' && section) {
      layoutRoot ??= createRoot(layout)
      flushSync(() => layoutRoot!.render(createElement(DocxLayoutSource, { editable: editable && editor.isEditable, settings: section.settings, pageNumberFmt: section.pageNumberFmt, pageNumberStart: section.pageNumberStart, pageNumberReason: section.pageNumberReason, titlePg: section.titlePg, titlePgReason: section.titlePgReason, evenAndOddHeaders: section.evenAndOddHeaders, evenAndOddHeadersReason: section.evenAndOddHeadersReason, onChange: section.onChange, sectionLabel: section.label, onSectionBreak: section.onSectionBreak, onEditHeaderFooter: headerFooter ? () => setActive('headerFooter') : undefined })))
      const paragraph = document.createElement('section')
      paragraph.className = 'ribbon-group docx-ribbon-group'
      paragraph.setAttribute('aria-label', '段落(选中段落)')
      const controls = document.createElement('div')
      controls.className = 'ribbon-group-items'
      controls.append(rightIndentField(), spacingField('space-before-value', '段前'), spacingField('space-after-value', '段后'))
      const caption = document.createElement('div')
      caption.className = 'ribbon-group-label'; caption.textContent = '段落(选中段落)'
      paragraph.append(controls, caption)
      if (layoutParagraph) layoutParagraph.replaceWith(paragraph)
      else layout.querySelector('.docx-source-layout')!.append(paragraph)
      layoutParagraph = paragraph
      body.replaceChildren(layout); body.setAttribute('aria-label', '布局')
    }
    else if (id === 'headerFooter' && headerFooter) {
      headerFooterRoot ??= createRoot(headerFooterPanel)
      const controller = headerFooterTarget?.controller ?? headerFooter
      flushSync(() => headerFooterRoot!.render(createElement(DocxHeaderFooterSource, { key: `${controller.anchor.sectionId}:${headerFooterTarget?.part ?? ''}:${headerFooterTarget?.variant ?? ''}`, controller, target: headerFooterTarget })))
      body.replaceChildren(headerFooterPanel); body.setAttribute('aria-label', '页眉和页脚')
    }
    else if (id === 'references' && notes) {
      renderPending(id)
      body.querySelector('[aria-label="脚注"]')?.remove()
      renderNotes(); body.querySelector('.ribbon-content')!.append(notesPanel)
    }
    else if (id === 'layout') renderPending(id)
    else if (id === 'design') { renderPending(id); syncPageColor(); syncWatermark() }
    else if (id !== 'home') renderPending(id)
    else { body.replaceChildren(home); body.setAttribute('aria-label', '开始') }
  }
  const refreshContextTabs = () => {
    const selection = editor.state.selection
    const selectedNode = selection instanceof NodeSelection ? selection.node : undefined
    const names: string[] = []
    for (let depth = 0; depth <= selection.$from.depth; depth++) names.push(selection.$from.node(depth).type.name)
    if (selectedNode) names.push(selectedNode.type.name)
    const nodes = selection instanceof NodeSelection ? [selectedNode!] : Array.from({ length: selection.$from.depth + 1 }, (_, depth) => selection.$from.node(depth))
    const inTable = names.some(name => ['docTable', 'docTableRow', 'docTableCell', 'docTableHeader'].includes(name))
    const picture = nodes.some(node => node.type.name === 'docInlineImage' || (node.type.name === 'docProtected' && node.attrs.blockType === 'image'))
    const shape = nodes.some(node => node.type.name === 'docProtected' && Array.isArray(node.attrs.textboxes) && node.attrs.textboxes.length > 0)
    const states: Record<string, boolean> = { tableDesign: inTable, tableLayout: inTable, pictureFormat: picture, shapeFormat: shape, headerFooter: !!headerFooter }
    for (const [id, button] of contextTabs) button.hidden = states[id] !== true
    if (contextTabs.get(active)?.hidden) setActive('home')
  }
  for (const { id, label, contextual } of tabs) {
    const tab = document.createElement('button')
    tab.type = 'button'
    tab.className = `ribbon-tab${id === active ? ' active' : ''}${id === 'file' ? ' ribbon-tab-file' : ''}`
    tab.textContent = label
    tab.dataset.tabLabel = label
    tab.dataset.tabId = id
    tab.setAttribute('role', 'tab')
    tab.setAttribute('aria-selected', String(id === active))
    tab.tabIndex = id === active ? 0 : -1
    if (contextual) { tab.hidden = true; contextTabs.set(id, tab) }
    tab.addEventListener('click', () => setActive(id))
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const visible = [...tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]')].filter(item => !item.hidden)
      const index = visible.indexOf(tab)
      const next = event.key === 'Home' ? visible[0] : event.key === 'End' ? visible.at(-1)! : visible[(index + (event.key === 'ArrowRight' ? 1 : -1) + visible.length) % visible.length]
      setActive(next.dataset.tabId!); next.focus()
    })
    tablist.append(tab)
  }
  ribbon.append(tablist)

  const home = document.createElement('div')
  home.className = 'docx-home-host'
  const insert = document.createElement('div')
  const insertRoot = createRoot(insert)
  const renderInsert = () => {
    const numberTarget = section ? { format: section.pageNumberFmt, start: section.pageNumberStart, reason: section.pageNumberReason, label: section.label, commit: ((label, settings) => (values: SectionValues) => {
      if (section.label !== label || section.settings !== settings) throw new Error('当前节发生变化，请重新打开页码格式')
      section.onChange(values)
    })(section.label, section.settings) } : undefined
    flushSync(() => insertRoot.render(createElement(DocxInsertSource, { editor, editable, anchors, onNewComment:commentCommands?.openNew, onBookmarks:bookmarks?.open,onCrossReference:references?.crossReferences.open,
    headerFooter: headerFooter?.prepareEdges ? { prepare: () => headerFooter.prepareEdges!(), edit: target => {
      headerFooter.flushPendingEdits?.(); headerFooterTarget = target; setActive('headerFooter')
    } } : undefined,
    pageNumber: numberTarget,
  })))
  }
  renderInsert()
  const selectParagraph = () => {
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) {
      if (['docParagraph', 'docHeading', 'docListItem'].includes($from.node(depth).type.name)) {
        return { from: $from.start(depth), to: $from.end(depth) }
      }
    }
    throw new Error('请先选择正文段落')
  }
  /** 有选区时只作用于选中文字（保存为 formatRange）；光标折叠时作用于整段（formatParagraph）。 */
  const formatTarget = () => {
    const { from, to, empty } = editor.state.selection
    return empty ? selectParagraph() : { from, to }
  }
  const applyMark = (name: string) => {
    const range = formatTarget()
    editor.chain().focus().setTextSelection(range).toggleMark(name).run()
  }
  const applyTextStyle = (style: Record<string, unknown>) => {
    const range = formatTarget()
    const attrs: Record<string, unknown> = {}
    if ('fontFamily' in style) Object.assign(attrs, docxFontPickAttrs(style.fontFamily as string | null))
    if ('fontSize' in style) attrs.sizeHalfPoints = Number(style.fontSize) * 2
    if ('color' in style) attrs.color = style.color
    editor.chain().focus().setTextSelection(range).setMark('docTextStyle', attrs).run()
  }
  const adjustFontSize = (delta: number) => {
    const range = formatTarget()
    let size = 12
    let found = false
    editor.state.doc.nodesBetween(range.from, range.to, node => {
      if (found || !node.isText) return
      const style = node.marks.find(mark => mark.type.name === 'docTextStyle')
      if (style?.attrs.sizeHalfPoints != null) {
        size = Number(style.attrs.sizeHalfPoints) / 2
        found = true
      }
    })
    const next = Math.max(1, Math.min(200, size + delta))
    if (next !== size) editor.chain().focus().setTextSelection(range).setMark('docTextStyle', { sizeHalfPoints: next * 2 }).run()
  }
  const adjustIndent = (delta: -1 | 1) => {
    const range = selectParagraph()
    const $pos = editor.state.doc.resolve(range.from)
    for (let depth = $pos.depth; depth > 0; depth--) {
      const node = $pos.node(depth)
      if (node.type.name === 'docListItem') {
        const next = Number(node.attrs.ilvl) + delta
        if (!hasListLevel(node, delta)) throw new Error(delta > 0 ? '编号定义中没有兼容的下一级' : '编号定义中没有兼容的上一级')
        editor.view.dispatch(editor.state.tr.setNodeMarkup($pos.before(depth), undefined, { ...node.attrs, ilvl: next }))
        return
      }
      if (!['docParagraph', 'docHeading'].includes(node.type.name)) continue
      const current = Number(node.attrs.indentLeft) || 0
      const next = Math.min(14400, delta > 0
        ? Math.floor(current / 720) * 720 + 720
        : Math.max(Math.ceil(current / 720) * 720 - 720, 0))
      if (next !== current) editor.view.dispatch(editor.state.tr.setNodeMarkup($pos.before(depth), undefined, { ...node.attrs, indentLeft: next || null }))
      return
    }
    throw new Error('请先选择正文段落')
  }

  body.append(home)
  const homeRoot = createRoot(home)
  // 上游 Home toggleList 的正文分支：同类列表再点还原普通段落。
  // numId 只作浏览器草稿标识；真实编号身份由服务端从来源文档分配。
  const toggleList = (kind: 'bullet' | 'ordered') => {
    if (editor.isActive('docListItem', { kind })) editor.chain().focus().setNode('docParagraph').run()
    else editor.chain().focus().setNode('docListItem', { kind, numId: `native-${kind}`, ilvl: 0 }).run()
  }
  const paragraphStyleControl = createParagraphStyleControl(editor, editable, anchors)
  // 剪贴板组：格式刷控制器 + 粘贴/剪切/复制回调（docx-clipboard.ts，协议内收敛）。
  // 剪贴板/刷子的失败原因经 reportError 写回文档状态栏，按钮保持可用可重试。
  const reportClipboardError = (error: unknown) => { if (reportError) reportError(error); else console.warn(error instanceof Error ? error.message : String(error)) }
  let refreshHome: () => void = () => {}
  const painter = createDocxPainter(editor, { report: reportClipboardError, onChange: () => refreshHome() })
  const renderHome = () => {
    let alignment: string | undefined
    let listKind: string | undefined
    let indentLeft: number | null = null
    let listLevel: number | undefined
    let selected: any
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) {
      const node = $from.node(depth)
      if (['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name)) {
        selected = node
        alignment = node.attrs.align ?? (effectiveBidi(node.attrs) ? 'right' : 'left')
        listKind = node.type.name === 'docListItem' ? node.attrs.kind : undefined
        indentLeft = node.attrs.indentLeft == null ? null : Number(node.attrs.indentLeft)
        listLevel = node.type.name === 'docListItem' ? Number(node.attrs.ilvl) || 0 : undefined
        break
      }
    }
    flushSync(() => homeRoot.render(createElement(DocxHomeSource, {
      editable: editable && editor.isEditable,
      onAssistant,
      paragraphStyleControl,
      clearFormattingUnavailable: docxClearFormattingUnavailable(editor, editable, anchors),
      onClearFormatting: () => { try { applyDocxClearFormatting(editor, editable, anchors) } catch (error) { reportClipboardError(error) } },
      caseUnavailable: docxCaseUnavailable(editor, editable, anchors),
      onChangeCase: (mode: CaseMode) => { try { applyDocxCase(editor, editable, anchors, mode) } catch (error) { reportClipboardError(error) } },
      alignment,
      listKind,
      spaceBefore: selected?.attrs.spaceBefore == null ? null : Number(selected.attrs.spaceBefore),
      spaceAfter: selected?.attrs.spaceAfter == null ? null : Number(selected.attrs.spaceAfter),
      lineSpacing: selected?.attrs.lineSpacing == null ? null : Number(selected.attrs.lineSpacing),
      lineSpacingUnavailable: docxLineSpacingUnavailable(editor, anchors),
      specialIndentUnavailable: docxSpecialIndentUnavailable(editor, anchors),
      onSpecialIndentOptions: () => {
        try { closeLineSpacing?.(); closeSpecialIndent?.(); closeSpecialIndent = openDocxSpecialIndentDialog(ribbon, editor, anchors) }
        catch (error) { reportClipboardError(error) }
      },
      onLineSpacingOptions: () => {
        try { closeSpecialIndent?.(); closeLineSpacing?.(); closeLineSpacing = openDocxLineSpacingDialog(ribbon, editor, anchors) }
        catch (error) { reportClipboardError(error) }
      },
      onSpacing: (values: Record<string, unknown>) => {
        const target = selectedParagraph()
        if (!target || !editable || !editor.isEditable) return
        editor.view.dispatch(editor.state.tr.setNodeMarkup(target.pos, undefined, { ...target.node.attrs, ...values }))
      },
      onList: toggleList,
      onMark: applyMark,
      onVerticalAlign: (kind: 'superscript' | 'subscript') => { toggleParagraphVerticalAlign(editor, formattingAnchors, kind, withNotes) },
      verticalAlign: selectedVerticalAlign(editor, formattingAnchors, withNotes),
      verticalAlignAvailable: !!verticalAlignTarget(editor, formattingAnchors, withNotes) && !!textFormattingRange(editor, verticalAlignTarget(editor, formattingAnchors, withNotes)!),
      onFontSize: adjustFontSize,
      onFontFamily: (fontFamily: string) => { if (fontFamily) applyTextStyle({ fontFamily }) },
      onFontSizeValue: (fontSize: number) => applyTextStyle({ fontSize }),
      onHighlight: (value: string) => { if (editable) applyParagraphHighlight(editor, formattingAnchors, value, withNotes) },
      highlight: selectedHighlight(editor, formattingAnchors, withNotes),
      highlightAvailable: !!highlightTarget(editor, formattingAnchors, withNotes) && !!textFormattingRange(editor, highlightTarget(editor, formattingAnchors, withNotes)!),
      onShading: (value: string) => { if (editable) applyParagraphShading(editor, anchors, value) },
      shading: selected ? paragraphShading(selected.toJSON()) : undefined,
      shadingAvailable: !!paragraphShadingTarget(editor, anchors),
      onBorders: (value: { sides: string; color: string | null; szPt: number } | null) => { if (editable) applyParagraphBorders(editor, anchors, value) },
      borders: selected ? paragraphBorders(selected.toJSON()) : null,
      bordersAvailable: !!paragraphBordersTarget(editor, anchors),
      onColor: (color: string) => applyTextStyle({ color }),
      onAlignment: (value: 'left' | 'center' | 'right' | 'justify') => { setSelectionAlign(editor, value) },
      onIndent: adjustIndent,
      indentLeft,
      listLevelDecreaseAvailable: hasListLevel(selected, -1),
      listLevelIncreaseAvailable: hasListLevel(selected, 1),
      listLevelOptions: availableListLevels(selected),
      listLevel,
      onListLevel: setListLevel,
      onParagraph: onParagraphCommand ? (command: 'add' | 'delete') => onParagraphCommand(command) : undefined,
      onFindReplace,
      onSelectAll: !editor.isDestroyed ? () => { editor.chain().focus().selectAll().run() } : undefined,
      onPaste: (mode?: DocxPasteMode) => { void docxClipboardPaste(editor, mode).catch(reportClipboardError) },
      onCut: () => { try { docxClipboardCut(editor) } catch (error) { reportClipboardError(error) } },
      onCopy: () => { try { docxClipboardCopy(editor) } catch (error) { reportClipboardError(error) } },
      onPainterClick: () => painter.click(),
      onPainterDoubleClick: () => painter.doubleClick(),
      painterActive: painter.active(),
    })))
  }
  refreshHome = renderHome
  renderHome()
  ribbon.append(body)
  /** 页面颜色按钮：可用性、提示与当前色条随编辑状态和草稿刷新。 */
  function syncPageColor() {
    const trigger = body.querySelector<HTMLButtonElement>('[data-action="page-color"]')
    if (!trigger || !pageColor) return
    const reason = !editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : pageColor.reason()
    const current = pageColor.current()
    trigger.disabled = reason !== null
    trigger.title = reason ?? `页面颜色：${current ? `#${current}` : '无颜色'}`
    trigger.querySelector<HTMLElement>('.docx-page-color-bar')!.style.background = current ? `#${current}` : 'transparent'
    for (const swatch of body.querySelectorAll<HTMLButtonElement>('[data-action^="page-color-"]')) swatch.setAttribute('aria-pressed', String(swatch.dataset.action === `page-color-${current ?? 'none'}`))
  }
  /** 水印按钮：可用性、提示与菜单选中项随编辑状态和草稿刷新。 */
  function syncWatermark() {
    const trigger = body.querySelector<HTMLButtonElement>('[data-action="watermark"]')
    if (!trigger || !watermark) return
    const reason = !editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : watermark.reason()
    const current = watermark.current()
    trigger.disabled = reason !== null
    trigger.title = reason ?? (current ? `水印：${current.text}` : watermark.source.picture ? '水印：图片水印（可替换为文字水印或删除）' : '水印：无')
    trigger.classList.toggle('active', !!current || (watermark.source.picture && !trigger.title.includes('无')))
    for (const item of body.querySelectorAll<HTMLButtonElement>('[data-action^="watermark-preset-"]')) item.classList.toggle('active', current?.text === item.textContent && Object.keys(current).length === 1)
  }
  const refreshSelection = () => {
    refreshView()
    if (active === 'design') { syncPageColor(); syncWatermark() }
    refreshContextTabs()
    renderInsert()
    if (active === 'references') { renderNotes(); refreshToc(body) }
    if (active === 'tableDesign') {
      cellBorderControls?.sync()
      if (!editable && cellBorderControls) for (const control of cellBorderControls.element.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button,input,select')) control.disabled = true
      const trigger = body.querySelector<HTMLButtonElement>('[data-action="table-cell-shading"]')
      if (trigger) {
        const reason = !editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : docxCellShadingUnavailable(editor, anchors)
        trigger.disabled = reason !== null; trigger.title = reason ?? '单元格底纹'
      }
    }
    if (active === 'tableLayout' && tableCommands) for (const button of body.querySelectorAll<HTMLButtonElement>('[data-action]')) {
      const action = button.dataset.action!
      if (!TABLE_ACTIONS[action] && !['table-repeat-header-rows', 'table-merge-cells', 'table-split-cells', 'table-column-width', 'table-distribute-columns', 'table-row-height', 'table-distribute-rows', 'table-autofit-contents', 'table-autofit-window', 'table-autofit-fixed', 'table-text-direction-horizontal', 'table-text-direction-rotate-90', 'table-text-direction-rotate-270', 'table-align-top-left', 'table-align-top-center', 'table-align-top-right', 'table-align-middle-left', 'table-align-middle-center', 'table-align-middle-right', 'table-align-bottom-left', 'table-align-bottom-center', 'table-align-bottom-right', 'table-cell-margins', 'table-properties'].includes(action)) continue
      const reason = !editable || !editor.isEditable ? '当前文档不可编辑或正在保存' : tableCommands.reason(action)
      button.disabled = reason !== null
      if(action==='table-repeat-header-rows'||action.startsWith('table-autofit-')||action.startsWith('table-text-direction-')||action.startsWith('table-align-'))button.setAttribute('aria-pressed',String(tableCommands.active?.(action)??false))
      const label = button.textContent ?? action
      button.title = reason === null ? label : `${label}：${reason}`
      button.setAttribute('aria-label', reason === null ? label : `${label}，${reason}`)
      if (reason === null) button.removeAttribute('aria-description')
      else button.setAttribute('aria-description', reason)
    }
    if (active === 'headerFooter' && !body.querySelector('.docx-hf-editor-host :focus')) queueMicrotask(() => { if (ribbon.isConnected && active === 'headerFooter') setActive('headerFooter') })
    if (active === 'layout') {
      // Do not replace a focused field (or the next field during its blur/focus handoff).
      if (!focusedSpacingInput?.isConnected && !body.querySelector('.layout-num input:focus')) setActive('layout')
      else for (const input of body.querySelectorAll<HTMLInputElement>('[data-action="space-before-value"], [data-action="space-after-value"]')) input.dispatchEvent(new Event('docx-spacing-refresh'))
    }
  }
  editor.on('selectionUpdate', refreshSelection)
  editor.on('transaction', refreshSelection)
  const refreshTocAfterDraft = () => { if (active === 'references') refreshToc(body) }
  editor.on('update', refreshTocAfterDraft)
  editor.on('transaction', renderHome)
  editor.on('update', renderHome)
  editor.on('destroy', () => {
    disposeScroll()
    editor.off('selectionUpdate', refreshSelection)
    editor.off('transaction', refreshSelection)
    editor.off('update', refreshTocAfterDraft)
    editor.off('transaction', renderHome)
    editor.off('update', renderHome)
    notesRoot?.unmount()
    painter.dispose()
    closeLineSpacing?.()
    closeSpecialIndent?.()
    homeRoot.unmount(); insertRoot.unmount(); layoutRoot?.unmount(); headerFooterRoot?.unmount()
  })
  refreshContextTabs()
  return ribbon
}
