import { afterEach, expect, it, vi } from 'vitest'
import { flushSync } from 'react-dom'
import { Editor, Extension, Mark, Node } from '@tiptap/core'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, type DocxAnchor } from './docx-operations'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+', renderHTML: () => ['div', 0] })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: 0 }, align: { default: null }, bidi: { default: false }, indentLeft: { default: null }, indentRight: { default: null }, spaceBefore: { default: null }, spaceAfter: { default: null }, lineSpacing: { default: null }, lineRule: { default: null }, lineRawTwips: { default: null } }), renderHTML: () => ['p', 0] })
const ListItem = Paragraph.extend({ name: 'docListItem', addAttributes: () => ({ docxIndex: { default: 0 }, align: { default: null }, bidi: { default: false }, indentLeft: { default: null }, indentRight: { default: null }, spaceBefore: { default: null }, spaceAfter: { default: null }, lineSpacing: { default: null }, lineRule: { default: null }, lineRawTwips: { default: null }, kind: { default: 'bullet' }, numId: { default: null }, ilvl: { default: 0 } }), renderHTML: () => ['div', 0] })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docParagraph+', selectable: true, renderHTML: () => ['table', 0] })
const InlineImage = Node.create({ name: 'docInlineImage', inline: true, group: 'inline', atom: true, selectable: true, renderHTML: () => ['img'] })
const Protected = Node.create({ name: 'docProtected', group: 'block', atom: true, selectable: true, addAttributes: () => ({ blockType: { default: 'other' }, textboxes: { default: null } }), renderHTML: () => ['div'] })
const Text = Node.create({ name: 'text', group: 'inline', renderHTML: ({ node }) => ['span', {}, node.text ?? ''] })
const simpleMark = (name: string) => Mark.create({ name, parseHTML: () => [{ tag: `span[data-${name}]` }], renderHTML: () => ['span', { [`data-${name}`]: '' }, 0] })
const TextStyle = Mark.create({
  name: 'docTextStyle',
  addAttributes: () => ({ font: { default: null }, fontAscii: { default: null }, eastAsiaFont: { default: null }, sizeHalfPoints: { default: null }, color: { default: null } }),
  parseHTML: () => [{ tag: 'span[data-style]' }],
  renderHTML: ({ HTMLAttributes }) => ['span', { ...HTMLAttributes, 'data-style': '' }, 0],
})

afterEach(() => { document.body.replaceChildren() })

it('routes navigation and outline view controls while readonly and reflects their pressed state', () => {
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({element:host,extensions:[Doc,Paragraph,Text],editable:false,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'原文'}]}]}})
  let navigation = false, mode = 'page'
  const commands = {reason: () => null, active: (label:string) => label === '导航窗格' ? navigation : label === '大纲' ? mode === 'outline' : mode === 'page', run: (label:string) => {if(label === '导航窗格')navigation = !navigation;else mode = label === '大纲' ? 'outline' : 'page'}}
  const ribbon = createDocxRibbon(editor,false,undefined,undefined,undefined,[],undefined,commands)
  document.body.append(ribbon)
  try {
    const before = editor.getJSON(), selection = editor.state.selection.from
    ribbon.querySelector<HTMLButtonElement>('[data-tab-label="视图"]')!.click()
    const navigationButton = ribbon.querySelector<HTMLButtonElement>('[data-action="navigation-toggle"]')!
    expect(navigationButton.disabled).toBe(false)
    const down = new MouseEvent('mousedown',{cancelable:true}); navigationButton.dispatchEvent(down)
    expect(down.defaultPrevented).toBe(true)
    navigationButton.click(); expect(navigationButton.getAttribute('aria-pressed')).toBe('true')
    const outlineButton = ribbon.querySelector<HTMLButtonElement>('[data-action="view-outline"]')!
    outlineButton.click(); expect(outlineButton.getAttribute('aria-pressed')).toBe('true')
    ribbon.querySelector<HTMLButtonElement>('[data-action="view-page"]')!.click()
    expect(outlineButton.getAttribute('aria-pressed')).toBe('false')
    expect(editor.getJSON()).toEqual(before); expect(editor.state.selection.from).toBe(selection)
  } finally {editor.destroy()}
})

it('offers source-bound Home formatting and leaves unsupported Ribbon commands disabled', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, Table, InlineImage, Protected, Text, simpleMark('bold'), simpleMark('italic'), simpleMark('underline'), simpleMark('strike'), TextStyle],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '报告正文' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const onParagraphCommand = vi.fn(command => {
    if (command === 'add') editor.chain().insertContentAt(editor.state.doc.content.size, {
      type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: '新段落' }],
    }).run()
    else editor.chain().deleteNode('docParagraph').run()
  })
  const ribbon = createDocxRibbon(editor, true, undefined, onParagraphCommand)
  document.body.append(ribbon)

  for (const tab of ['文件', '插入', '绘图', '设计', '布局', '引用', '邮件', '审阅', '视图']) {
    expect(ribbon.querySelector<HTMLButtonElement>(`[data-tab-label="${tab}"]`)?.disabled).toBe(false)
  }
  for (const tab of ['表格设计', '表格布局', '图片格式', '形状格式']) {
    expect(ribbon.querySelector<HTMLButtonElement>(`[data-tab-label="${tab}"]`)?.hidden).toBe(true)
  }
  expect(Array.from(ribbon.querySelector('[role=tabpanel]')!.querySelectorAll('.ribbon-group-label')).map(group => group.textContent)).toEqual([
    'AI 助手', '剪贴板', '字体', '段落', '样式', '编辑', '转换',
  ])
  ribbon.querySelector<HTMLButtonElement>('[data-tab-label="插入"]')!.click()
  expect(Array.from(ribbon.querySelectorAll('.docx-ribbon-group-label, .ribbon-group-label')).map(group => group.textContent)).toEqual(['页面', '表格', '插图', '文本', '链接', '批注', '页眉和页脚', '符号'])
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="insert-symbol"]')?.disabled).toBe(false)
  for (const action of ['insert-link', 'edit-link', 'remove-link']) {
    const linkCommand = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
    expect(linkCommand?.disabled).toBe(true)
    expect(linkCommand?.title).toContain('请选择已有可编辑正文段落')
    expect(linkCommand?.getAttribute('aria-label')).toBeTruthy()
  }
  const onPreview = vi.fn()
  const withPreview = createDocxRibbon(editor, true, onPreview)
  withPreview.querySelector<HTMLButtonElement>('[data-tab-label="视图"]')!.click()
  withPreview.querySelector<HTMLButtonElement>('[data-action="pagination-preview"]')!.click()
  expect(onPreview).toHaveBeenCalledOnce()
  withPreview.querySelector<HTMLButtonElement>('[data-tab-label="开始"]')!.click()
  expect(withPreview.querySelector<HTMLButtonElement>('[data-action="add-paragraph"]')?.disabled).toBe(true)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-label="开始"]')!.click()
  for (const action of ['bold', 'italic', 'underline', 'strike']) {
    expect(ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.disabled).toBe(false)
  }
  for (const action of ['font-family', 'font-size', 'font-color']) {
    expect(ribbon.querySelector<HTMLInputElement>(`[data-action="${action}"]`)?.disabled).toBe(false)
  }
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="highlight"]')?.disabled).toBe(true)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="align-left"]')?.disabled).toBe(false)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="add-paragraph"]')?.disabled).toBe(false)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="delete-paragraph"]')?.disabled).toBe(false)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="bullets"]')?.disabled).toBe(false)
  for (const [id, reason] of [
    ['list-bullets-gallery', '项目符号库预设、清除列表和自定义项目符号写回尚未接入'],
    ['list-numbering-gallery', '编号样式库、自定义编号及其重新开始配置写回尚未接入'],
    ['list-multilevel-gallery', '多级样式库、自定义层级及级间重新开始规则写回尚未接入'],
    ['list-numbering-set-value', '起始编号、重新开始和继续列表写回尚未接入'],
  ]) {
    const control = ribbon.querySelector<HTMLButtonElement>(`[data-source-action="${id}"]`)
    expect(control?.disabled).toBe(true)
    expect(control?.title).toContain(reason)
    expect(control?.getAttribute('aria-label')).toContain(reason)
  }
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="grow-font"]')?.disabled).toBe(false)
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="shrink-font"]')?.disabled).toBe(false)

  ribbon.querySelector<HTMLButtonElement>('[data-action="add-paragraph"]')!.click()
  expect(onParagraphCommand).toHaveBeenCalledWith('add')
  expect(docxOperations(original, editor.getJSON() as any, [anchor])[0]).toEqual({
    kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', position: 'after', text: '新段落',
  })
  editor.commands.setTextSelection({ from: 1, to: 7 })

  for (const action of ['bold', 'italic', 'underline', 'strike']) {
    ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!.click()
  }
  const font = ribbon.querySelector<HTMLInputElement>('[data-action="font-family"]')!
  const choices = Array.from(document.getElementById(font.getAttribute('list')!)!.querySelectorAll('option'))
  expect(choices.map(option => option.value)).toEqual(['Noto Serif CJK SC', 'Noto Sans CJK SC', 'LXGW WenKai', 'Ma Shan Zheng', 'ZCOOL XiaoWei', 'SimSun', 'SimHei', 'Microsoft YaHei', 'KaiTi', 'FangSong'])
  expect(choices[0]!.label).toContain('内置')
  expect(choices[4]!.label).toContain('内置')
  expect(choices[5]!.label).toContain('系统字体')
  font.value = 'Microsoft YaHei'
  font.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  const size = ribbon.querySelector<HTMLInputElement>('[data-action="font-size"]')!
  size.value = '16'
  size.dispatchEvent(new Event('input', { bubbles: true }))
  const color = ribbon.querySelector<HTMLInputElement>('[data-action="font-color"]')!
  color.value = '#aabbcc'
  color.dispatchEvent(new Event('input', { bubbles: true }))

  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', position: 'after', text: '新段落' },
    { kind: 'formatParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash',
      style: { bold: true, italic: true, underline: true, strike: true, fontFamily: 'Microsoft YaHei', fontSize: 16, color: 'AABBCC' } },
  ])
  ribbon.querySelector<HTMLButtonElement>('[data-action="delete-paragraph"]')!.click()
  expect(onParagraphCommand).toHaveBeenCalledWith('delete')
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', position: 'before', text: '新段落' },
    { kind: 'deleteParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash' },
  ])
  editor.destroy()
})

it('routes source paragraph line-spacing presets and before/after toggles through DOCX operations', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, lineSpacing: 1.5, spaceBefore: 0, spaceAfter: 0 }, content: [{ type: 'text', text: '报告正文' }] }] },
  })
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash', editable: true }
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, [anchor])
  document.body.append(ribbon)
  const original = editor.getJSON() as any
  const lineSpacing = ribbon.querySelector<HTMLButtonElement>('[data-action="line-spacing"]')!
  expect(lineSpacing.disabled).toBe(false)
  expect(lineSpacing.closest('.rb-split-wrap')).not.toBeNull()
  lineSpacing.click()
  const preset = ribbon.querySelector<HTMLButtonElement>('[data-source-action="line-spacing-2"]')!
  expect(preset.disabled).toBe(false)
  preset.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash', lineSpacing: 2 },
  ])
  ribbon.querySelector<HTMLButtonElement>('[data-source-action="toggle-space-before"]')!.click()
  ribbon.querySelector<HTMLButtonElement>('[data-source-action="toggle-space-after"]')!.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash', spaceBefore: 240, spaceAfter: 240, lineSpacing: 2 },
  ])
  const options = ribbon.querySelector<HTMLButtonElement>('[data-source-action="line-spacing-options"]')!
  expect(options.disabled).toBe(true)
  expect(options.title).toContain('精确行距、段落对话框与其他行距单位尚未接入')
  ribbon.querySelector<HTMLButtonElement>('[data-tab-label="布局"]')!.click()
  for (const action of ['space-before-value', 'space-after-value']) {
    const field = ribbon.querySelector<HTMLInputElement>(`[data-action="${action}"]`)
    expect(field?.disabled).toBe(false)
    expect(field?.title).toContain('0–720 pt')
  }
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="home"]')!.click()
  flushSync(() => lineSpacing.click())
  expect(document.documentElement.classList.contains('genoffice-popover-open')).toBe(true)
  editor.destroy()
  expect(document.documentElement.classList.contains('genoffice-popover-open')).toBe(false)
})

it('routes Home paragraph border positions, width and color through DOCX operations', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const Bordered = Paragraph.extend({ addAttributes: () => ({ docxIndex: { default: 0 }, borders: { default: null }, borderLines: { default: null }, borderReset: { default: null }, borderPad: { default: null } }) })
  const editor = new Editor({
    element: host,
    extensions: [Doc, Bordered, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, borders: 't', borderLines: '{"t":{"color":"FF0000","szPt":0.5}}' }, content: [{ type: 'text', text: '报告正文' }] }] },
  })
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash', editable: true }
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, [anchor])
  document.body.append(ribbon)
  const original = editor.getJSON() as any
  const main = ribbon.querySelector<HTMLButtonElement>('[data-action="para-borders"]')!
  const caret = ribbon.querySelector<HTMLButtonElement>('[data-action="para-borders-menu"]')!
  expect(main.disabled).toBe(false)
  expect(caret.disabled).toBe(false)
  // Word 的 Home 边框默认笔画：下框线、0.5pt、黑色（Ribbon.tsx borderColor 000000/borderSz 4）。
  main.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphBorders', blockId: 'block-0', expectedObjectSha256: 'hash', borders: [{ side: 'bottom', val: 'single', color: '000000', szPt: 0.5 }] },
  ])
  // 同一笔画再点主按钮 = 还原无框线（与底纹开关同规）。
  main.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphBorders', blockId: 'block-0', expectedObjectSha256: 'hash', borders: null },
  ])
  // 主按钮点击触发事务重渲染后，弹层开关是新的 DOM 节点，需实时查询；setState 批处理需 flushSync。
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-borders-menu"]')!.click())
  for (const action of ['para-border-bottom', 'para-border-top', 'para-border-left', 'para-border-right', 'para-border-box', 'para-border-none']) {
    expect(ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.disabled, action).toBe(false)
  }
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-border-width-1.5"]')!.click())
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-border-color-00B050"]')!.click())
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-border-box"]')!.click())
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    {
      kind: 'setParagraphBorders', blockId: 'block-0', expectedObjectSha256: 'hash',
      borders: (['top', 'bottom', 'left', 'right'] as const).map(side => ({ side, val: 'single', color: '00B050', szPt: 1.5 })),
    },
  ])
  // 位置应用后弹层关闭（与 Word 库为同规），再次打开后执行无框线。
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-borders-menu"]')!.click())
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="para-border-none"]')!.click())
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphBorders', blockId: 'block-0', expectedObjectSha256: 'hash', borders: null },
  ])
  editor.destroy()
})

it('locks Home paragraph border commands while saving or without an editable anchor', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const Bordered = Paragraph.extend({ addAttributes: () => ({ docxIndex: { default: 0 }, borders: { default: null }, borderLines: { default: null }, borderReset: { default: null }, borderPad: { default: null } }) })
  const editor = new Editor({
    element: host,
    extensions: [Doc, Bordered, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '报告正文' }] }] },
  })
  const ribbon = createDocxRibbon(editor, false, undefined, undefined, undefined, [{ docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash', editable: false }])
  document.body.append(ribbon)
  for (const action of ['para-borders', 'para-borders-menu']) {
    const control = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
    expect(control?.disabled, action).toBe(true)
    expect(control?.title, action).toContain('请选择有唯一来源锚点的非空正文段落')
  }
  editor.destroy()
})

it('reveals contextual ribbons only for the matching selected Word object', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, Table, InlineImage, Protected, Text],
    content: { type: 'doc', content: [
      { type: 'docParagraph', content: [{ type: 'text', text: 'body' }] },
      { type: 'docTable', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'cell' }] }] },
      { type: 'docProtected', attrs: { blockType: 'image' } },
      { type: 'docProtected', attrs: { blockType: 'shape', textboxes: [{ text: 'shape' }] } },
    ] },
  })
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  const visible = (id: string) => ribbon.querySelector<HTMLButtonElement>(`[data-tab-id="${id}"]`)?.hidden === false
  expect(['tableDesign', 'tableLayout', 'pictureFormat', 'shapeFormat'].some(visible)).toBe(false)

  const tablePos = editor.state.doc.child(0).nodeSize
  editor.commands.setNodeSelection(tablePos)
  expect(visible('tableDesign')).toBe(true)
  expect(visible('tableLayout')).toBe(true)
  expect(visible('pictureFormat')).toBe(false)

  const imagePos = tablePos + editor.state.doc.child(1).nodeSize
  editor.commands.setNodeSelection(imagePos)
  expect(visible('tableDesign')).toBe(false)
  expect(visible('pictureFormat')).toBe(true)

  const shapePos = imagePos + editor.state.doc.child(2).nodeSize
  editor.commands.setNodeSelection(shapePos)
  expect(visible('pictureFormat')).toBe(false)
  expect(visible('shapeFormat')).toBe(true)
  editor.destroy()
})

it('keeps source Table Design and Layout commands unavailable when source capabilities are absent', () => {
  const Row = Node.create({ name: 'docTableRow', content: 'docTableCell+', renderHTML: () => ['tr', 0] })
  const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', addAttributes: () => ({ colspan: { default: 1 }, rowspan: { default: 1 }, colwidth: { default: null } }), renderHTML: () => ['td', 0] })
  const SourceTable = Table.extend({ content: 'docTableRow+' })
  const Roles = Extension.create({ name: 'tableRoles', extendNodeSchema: extension => ({ tableRole: ({ docTable: 'table', docTableRow: 'row', docTableCell: 'cell' } as Record<string, string>)[extension.name] }) })
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, SourceTable, Row, Cell, Roles, Text],
    content: { type: 'doc', content: [{ type: 'docTable', content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', content: [{ type: 'text', text: '单元格' }] }] }] }] }] },
  })
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  editor.commands.setNodeSelection(0)
  const reason = 'DOCX 表格操作尚未接入严格写回协议'
  const assertDisabled = (actions: string[]) => {
    for (const action of actions) {
      const command = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
      expect(command?.disabled, action).toBe(true)
      const expectedReason = action.startsWith('table-border-') ? '当前来源表格暂不能修改单元格边框' : action === 'table-cell-shading' ? '此单元格包含合并、嵌套、修订或不明确的来源' : reason
      expect(command?.title, action).toContain(expectedReason)
      if (action !== 'table-cell-shading') expect(command?.getAttribute('aria-label'), action).toContain(expectedReason)
    }
  }
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableDesign"]')!.click()
  assertDisabled([
    'table-style-none', 'table-style-grid', 'table-style-blue-header', 'table-style-blue-banded',
    'table-style-gray-banded', 'table-style-green-header', 'table-style-custom',
    'table-look-first-row', 'table-look-last-row', 'table-look-banded-rows', 'table-look-first-column',
    'table-look-last-column', 'table-look-banded-columns', 'table-cell-shading', 'table-border-apply-last',
    'table-border-bottom', 'table-border-top', 'table-border-left', 'table-border-right', 'table-border-none',
    'table-border-all', 'table-border-outer', 'table-border-inner', 'table-border-inside-horizontal',
    'table-border-inside-vertical', 'table-border-diagonal-down', 'table-border-diagonal-up',
    'table-border-style', 'table-border-width', 'table-border-color',
  ])
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
  assertDisabled([
    'table-select-menu', 'table-select-cell', 'table-select-column', 'table-select-row', 'table-select-all',
    'table-view-gridlines', 'table-properties', 'table-delete-menu', 'table-delete-cells', 'table-delete-column',
    'table-delete-row', 'table-delete', 'table-insert-row-before', 'table-insert-row-after',
    'table-insert-column-before', 'table-insert-column-after', 'table-insert-cells', 'table-merge-cells',
    'table-split-cells', 'table-split-table', 'table-row-height', 'table-column-width', 'table-autofit-contents',
    'table-autofit-window', 'table-autofit-fixed', 'table-distribute-rows', 'table-distribute-columns',
    'table-align-top-left', 'table-align-top-center', 'table-align-top-right', 'table-align-middle-left',
    'table-align-middle-center', 'table-align-middle-right', 'table-align-bottom-left', 'table-align-bottom-center',
    'table-align-bottom-right', 'table-text-direction-horizontal', 'table-text-direction-rotate-90',
    'table-text-direction-rotate-270', 'table-cell-margins', 'table-repeat-header-rows',
  ])
  editor.destroy()
})

it('steps paragraph indentation and only enables list levels present in the source numbering definition', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, ListItem, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, indentLeft: 300 }, content: [{ type: 'text', text: '正文' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  const increase = ribbon.querySelector<HTMLButtonElement>('[data-action="indent-increase"]')!
  const decrease = ribbon.querySelector<HTMLButtonElement>('[data-action="indent-decrease"]')!
  expect(increase.disabled).toBe(false)
  expect(decrease.disabled).toBe(false)
  increase.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphIndent', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', twips: 720 },
  ])
  decrease.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphIndent', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', twips: 0 },
  ])

  editor.view.dispatch(editor.state.tr.setNodeMarkup(0, editor.schema.nodes.docListItem, { ...editor.state.doc.firstChild!.attrs, docxIndex: 0, kind: 'bullet', numId: 'native-bullet', ilvl: 0 }))
  const listOriginal = editor.getJSON() as any
  expect(increase.disabled).toBe(true)
  expect(decrease.disabled).toBe(true)
  ;(editor.storage as any).listNumbering = { defs: new Map([['native-bullet', { levels: { 0: { numFmt: 'bullet' }, 1: { numFmt: 'bullet' }, 2: { numFmt: 'decimal' } } }]]) }
  editor.view.dispatch(editor.state.tr.setMeta('numbering-update', true))
  const levelPicker = ribbon.querySelector<HTMLSelectElement>('[data-source-action="list-change-level"]')!
  expect(levelPicker.disabled).toBe(false)
  expect(levelPicker.querySelector<HTMLOptionElement>('option[value="2"]')?.disabled).toBe(true)
  levelPicker.value = '1'
  levelPicker.dispatchEvent(new Event('change', { bubbles: true }))
  expect(docxOperations(listOriginal, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphListLevel', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', ilvl: 1 },
  ])
  editor.view.dispatch(editor.state.tr.setNodeMarkup(0, undefined, { ...editor.state.doc.firstChild!.attrs, ilvl: 0 }))
  expect(increase.disabled).toBe(false)
  expect(decrease.disabled).toBe(true)
  increase.click()
  expect(docxOperations(listOriginal, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphListLevel', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', ilvl: 1 },
  ])
  decrease.click()
  expect(docxOperations(listOriginal, editor.getJSON() as any, [anchor])).toEqual([])
  editor.destroy()
})

it.each([false, true])('commits the Layout right-indent field with section settings=%s through an anchored DOCX operation', withSection => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, ListItem, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, indentLeft: 360 }, content: [{ type: 'text', text: '正文' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, withSection ? {
    settings: { orientation: 'portrait', pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, pageBorder: false, columns: 1 },
    onChange: vi.fn(),
  } : undefined)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-label="布局"]')!.click()
  if (withSection) {
    const orientation = ribbon.querySelector<HTMLSelectElement>('[data-source-action="layout-orientation"]')!
    orientation.value = 'landscape'
    flushSync(() => orientation.dispatchEvent(new Event('change', { bubbles: true })))
    editor.commands.setTextSelection(2)
    expect(ribbon.querySelector<HTMLSelectElement>('[data-source-action="layout-orientation"]')?.value).toBe('landscape')
  }
  const input = ribbon.querySelector<HTMLInputElement>('[data-action="indent-right"]')!
  expect(input.disabled).toBe(false)
  input.focus()
  input.value = '18'
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  input.blur()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphRightIndent', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', twips: 360 },
  ])
  editor.destroy()
})

it('routes font-size step controls through the DOCX formatting operation', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, Text, TextStyle],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '正文' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-action="grow-font"]')!.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'formatParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', style: { fontSize: 13 } },
  ])
  ribbon.querySelector<HTMLButtonElement>('[data-action="shrink-font"]')!.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'formatParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', style: { fontSize: 12 } },
  ])
  editor.destroy()
})

it('inserts an upstream palette symbol as an anchored text operation and disables structural insert commands', () => {
  const editor = new Editor({
    extensions: [Doc, Paragraph, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '经营收入' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  editor.commands.setTextSelection(5)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="insert"]')!.click()
  expect(ribbon.querySelector('.docx-source-insert')).not.toBeNull()
  const insert = ribbon.querySelector<HTMLButtonElement>('[data-action="insert-symbol"]')
  expect(insert?.disabled).toBe(false)
  for (const action of ['insert-link', 'insert-equation']) {
    const button = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
    expect(button?.disabled).toBe(true)
    expect(button?.getAttribute('aria-description')).toMatch(/写回/)
  }
  // 插入表格已接通 insertTable；此测试 schema 无 docTable，按钮以位置原因禁用而非"未接入写回"。
  expect(ribbon.querySelector<HTMLButtonElement>('[data-action="insert-table"]')?.getAttribute('aria-description')).not.toMatch(/写回/)
  flushSync(() => { insert!.click() })
  const cells = ribbon.querySelectorAll<HTMLButtonElement>('.symbol-cell')
  expect(cells).toHaveLength(50)
  flushSync(() => { Array.from(cells).find(button => button.textContent === '¥')!.click() })
  expect(ribbon.querySelector('.symbol-palette')).toBeNull()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'replaceParagraph', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', text: '经营收入¥' },
  ])
  const readOnly = createDocxRibbon(editor, false)
  readOnly.querySelector<HTMLButtonElement>('[data-tab-id="insert"]')!.click()
  expect(readOnly.querySelector<HTMLButtonElement>('[data-action="insert-symbol"]')?.disabled).toBe(true)
  editor.destroy()
})

it.each(['left', 'center', 'right', 'justify'])('routes upstream %s alignment into a replayable DOCX operation', alignment => {
  const editor = new Editor({
    extensions: [Doc, Paragraph, Text],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: alignment === 'center' ? 'right' : 'center' }, content: [{ type: 'text', text: '正文' }] }] },
  })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'source-block-hash', editable: true }
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  const button = ribbon.querySelector<HTMLButtonElement>(`[data-action="align-${alignment}"]`)!
  expect(button.disabled).toBe(false)
  button.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([
    { kind: 'setParagraphAlignment', blockId: 'block-0', expectedObjectSha256: 'source-block-hash', alignment },
  ])
  expect(button.getAttribute('aria-pressed')).toBe('true')
  editor.destroy()
})

it.each([['bullets', 'bullet'], ['numbering', 'ordered']])('routes Home %s through an anchored list toggle and clear', (action, kind) => {
  const editor = new Editor({ extensions: [Doc, Paragraph, ListItem, Text], content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '列表正文' }] }] } })
  const original = editor.getJSON() as any
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash', editable: true }
  const ribbon = createDocxRibbon(editor, true)
  document.body.append(ribbon)
  const button = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  expect(button.dataset.sourceAction).toBe(kind === 'bullet' ? 'list-bullets-toggle' : 'list-numbering-toggle')
  button.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([{ kind: 'setParagraphList', blockId: 'block-0', expectedObjectSha256: 'hash', list: kind }])
  expect(button.getAttribute('aria-pressed')).toBe('true')
  button.click()
  expect(docxOperations(original, editor.getJSON() as any, [anchor])).toEqual([])
  editor.destroy()
})

it('wires the Word Home clipboard group: paste split menu, cut/copy and the format painter', async () => {
  const host = document.createElement('div')
  document.body.append(host)
  const editor = new Editor({
    element: host,
    extensions: [Doc, Paragraph, Text, simpleMark('bold'), simpleMark('italic'), simpleMark('underline'), simpleMark('strike'), TextStyle],
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'center' }, content: [{ type: 'text', text: '报告正文', marks: [{ type: 'bold' }] }] }] },
  })
  const reportError = vi.fn()
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined,
    [{ docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash', editable: true } as DocxAnchor],
    undefined, undefined, undefined, reportError)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-label="开始"]')!.click()
  for (const action of ['paste', 'paste-menu', 'cut', 'copy', 'format-painter']) {
    expect(ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.disabled).toBe(false)
  }
  // 分体菜单：源真实模式，富文本两项禁用并给出真实原因，仅保留文本可用
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="paste-menu"]')!.click())
  for (const [action, reason] of [
    ['paste-source', '无法精确映射到 DOCX 保存协议'],
    ['paste-merge', '无法精确映射到 DOCX 保存协议'],
    ['paste-special', '尚未接入'],
    ['paste-defaults', '尚未接入'],
  ] as const) {
    const item = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
    expect(item.disabled).toBe(true)
    expect(item.title).toContain(reason)
  }
  const textItem = ribbon.querySelector<HTMLButtonElement>('[data-action="paste-text"]')!
  expect(textItem.disabled).toBe(false)
  // 图片粘贴：分体菜单给出 picture 模式入口（insertParagraphImage 协议）
  const pictureItem = ribbon.querySelector<HTMLButtonElement>('[data-action="paste-picture"]')!
  expect(pictureItem?.disabled).toBe(false)
  expect(pictureItem?.getAttribute('aria-label')).toContain('粘贴图片')
  // 仅保留文本粘贴走 replaceParagraph/insertParagraph 映射
  Object.defineProperty(navigator, 'clipboard', { value: { readText: async () => '粘贴文本' }, configurable: true })
  editor.commands.setTextSelection(2)
  flushSync(() => textItem.click())
  await new Promise(resolve => setTimeout(resolve))
  expect((editor.getJSON() as any).content[0].content.map((run: any) => run.text).join('')).toBe('报粘贴文本告正文')
  Reflect.deleteProperty(navigator as any, 'clipboard')
  // 权限失败：准确原因经 reportError 上报，按钮保持可用
  Object.defineProperty(navigator, 'clipboard', { value: { readText: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) }, configurable: true })
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="paste"]')!.click())
  await new Promise(resolve => setTimeout(resolve))
  expect(reportError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('浏览器拒绝了剪贴板读取权限') }))
  Reflect.deleteProperty(navigator as any, 'clipboard')
  // 剪切/复制：execCommand 路径
  const exec = vi.fn(() => true)
  document.execCommand = exec as unknown as typeof document.execCommand
  editor.commands.setTextSelection({ from: 1, to: 3 })
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="copy"]')!.click())
  expect(exec).toHaveBeenCalledWith('copy')
  flushSync(() => ribbon.querySelector<HTMLButtonElement>('[data-action="cut"]')!.click())
  expect(exec).toHaveBeenCalledWith('cut')
  delete (document as unknown as Record<string, unknown>).execCommand
  // 格式刷：单击武装（按钮 active），Esc 解除
  const painterButton = ribbon.querySelector<HTMLButtonElement>('[data-action="format-painter"]')!
  editor.commands.setTextSelection(2)
  flushSync(() => painterButton.click())
  expect(painterButton.classList.contains('active')).toBe(true)
  expect(painterButton.getAttribute('aria-pressed')).toBe('true')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  flushSync(() => undefined)
  expect(painterButton.classList.contains('active')).toBe(false)
  editor.destroy()
})

it.each([['网格线', 'gridlines-toggle', 'onShowGrid'], ['标尺', 'ruler-toggle', 'onShowRuler']])('routes readonly %s with source identity and updates its pressed state', (label, action, source) => {
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({element:host,extensions:[Doc,Paragraph,Text],editable:false,content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'原文'}]}]}})
  let visible = false
  const commands = {reason:(value:string)=>value===label?null:'未接入',active:()=>visible,run:vi.fn(()=>{visible=!visible})}
  const ribbon = createDocxRibbon(editor,false,undefined,undefined,undefined,[],undefined,commands)
  document.body.append(ribbon)
  try {
    const before = editor.getJSON(), selection = editor.state.selection.from
    ribbon.querySelector<HTMLButtonElement>('[data-tab-label="视图"]')!.click()
    const button = ribbon.querySelector<HTMLButtonElement>('[data-action="'+action+'"]')!
    expect(button).not.toBeNull(); expect(button.disabled).toBe(false)
    expect(button.dataset.sourceAction).toBe(source); expect(button.getAttribute('aria-pressed')).toBe('false')
    const down = new MouseEvent('mousedown',{cancelable:true}); button.dispatchEvent(down); expect(down.defaultPrevented).toBe(true)
    button.click(); expect(commands.run).toHaveBeenCalledWith(label); expect(button.getAttribute('aria-pressed')).toBe('true')
    button.click(); expect(button.getAttribute('aria-pressed')).toBe('false')
    expect(editor.getJSON()).toEqual(before); expect(editor.state.selection.from).toBe(selection)
  } finally {editor.destroy()}
})
