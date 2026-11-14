import assert from 'node:assert/strict'
import { test } from 'node:test'
import { inspectUiSource } from './office-ui-inventory.mjs'

test('枚举真实 UI 声明及静态、动态导入，忽略注释和纯类型导入', () => {
  const result = inspectUiSource(`
import './theme.css'
import type { Model } from './types'
export { helper } from './helper'
const load = () => import('./dialog')
// document.createElement('fake')
const button = document.createElement('button')
const modal = createModal({ root, content: '<h2>设置</h2>' })
const controls = [{ id: 'save', label: '保存', command: 'save' }]
const view = <button aria-label="保存" disabled={busy}>保存</button>
root.innerHTML = '<input aria-label="数值">'
`)
  assert.deepEqual(result.imports, ['./dialog', './helper', './theme.css'])
  assert.deepEqual(result.sites.map(site => site.kind), ['element', 'modal', 'control-definition', 'jsx', 'html-template', 'html-control'])
  assert.equal(result.sites[0].tag, 'button')
  assert.equal(result.sites[2].command, 'save')
  assert.deepEqual(result.sites[3].attributes, { 'aria-label': '保存', disabled: '{busy}' })
  assert.ok(result.sites.every(site => Number.isInteger(site.line) && site.line > 0))
})

test('动态创建保留表达式，不伪造为已解析的按钮或功能', () => {
  const result = inspectUiSource('document.createElement(tag); const a = { id: prefix + name, label: title }')
  assert.equal(result.sites[0].tag, 'tag')
  assert.equal(result.sites[1].id, 'prefix + name')
  assert.equal(result.sites[1].label, 'title')
})

test('展开弹窗和innerHTML中的实际控件，解码名称并忽略注释/脚本文字', () => {
  const result = inspectUiSource(`
createModal({content: '<header><h2>设置</h2></header><form><label>链接地址<input name="url"></label><button data-command="apply">应用 &amp; 保存</button></form>'})
root.innerHTML = '<!-- <button>不存在</button> --><script>document.write("<button>脚本生成</button>");</script><select aria-label="方向"><option value="row">行</option></select><p role="alert" tabindex="0" aria-label="错误"></p>'
`)
  const controls = result.sites.filter(site => site.kind === 'html-control')
  assert.deepEqual(controls.map(site => [site.tag, site.label]), [
    ['input', '链接地址'], ['button', '应用 & 保存'], ['select', '方向'], ['option', '行'], ['p', '错误'],
  ])
  assert.equal(controls[1].attributes['data-command'], 'apply')
  assert.ok(controls.every(site => site.line === 2 || site.line === 3))
  assert.deepEqual(result.templates.map(template => [template.origin, template.controls, template.expressions]), [
    ['modal-content', 2, []], ['innerHTML', 3, []],
  ])
})

test('模板插值与动态HTML只登记来源，不执行代码或假定动态控件已穷尽', () => {
  const result = inspectUiSource('createModal({content: `<button data-action="${command}">${label}</button>${rows.map(renderRow)}`}); root.innerHTML = htmlFor(state)')
  const controls = result.sites.filter(site => site.kind === 'html-control')
  assert.equal(controls.length, 1)
  assert.equal(controls[0].dynamic, true)
  assert.equal(controls[0].label, '[动态表达式]')
  assert.deepEqual(result.templates.map(template => template.expressions), [['command', 'label', 'rows.map(renderRow)'], ['htmlFor(state)']])
  assert.equal(result.templates[1].controls, 0)
})

test('静态拼接和HTML转义后的换行保留真实来源行，不伪造标签源码行', () => {
  const result = inspectUiSource(`root.innerHTML = '<button data-action="a">甲</button>\\n' + '<input aria-label="乙">'`)
  const controls = result.sites.filter(site => site.kind === 'html-control')
  assert.deepEqual(controls.map(site => [site.tag, site.label, site.line]), [['button', '甲', 1], ['input', '乙', 1]])
  assert.ok(controls[1].htmlLine > controls[0].htmlLine)
})

test('保留静态隐藏/禁用属性与标签引用，动态状态不伪造为已解析布尔值', () => {
  const result = inspectUiSource('createModal({content: `<span id="name">范围</span><input aria-labelledby="name" disabled hidden><button disabled="${busy}" data-action="apply">应用</button>`})')
  const controls = result.sites.filter(site => site.kind === 'html-control')
  assert.equal(controls[0].label, '范围')
  assert.equal(controls[0].attributes.disabled, true)
  assert.equal(controls[0].attributes.hidden, true)
  assert.equal(controls[0].dynamic, false)
  assert.equal(controls[1].label, '应用')
  assert.equal(controls[1].dynamic, true)
  assert.equal(typeof controls[1].attributes.disabled, 'string')
  assert.deepEqual(result.templates[0].expressions, ['busy'])
})

test('命名引用列表同样列出，而不是只收集可点击按钮', () => {
  const result = inspectUiSource(`root.innerHTML = '<ul aria-label="所有引用位置"></ul><fieldset><legend>选项</legend><label><input type="checkbox">保留格式</label></fieldset>'`)
  const controls = result.sites.filter(site => site.kind === 'html-control')
  assert.deepEqual(controls.map(site => [site.tag, site.label]), [['ul', '所有引用位置'], ['fieldset', '选项'], ['input', '保留格式']])
})
